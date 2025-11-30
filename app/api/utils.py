"""API utility functions for message processing and database operations."""

import json
import uuid
import time
import asyncio
import logging
from datetime import datetime
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import text
from fastapi import HTTPException, status

from app.models.message import CanonicalMessage, MessageParty, MessageContent
from app.services.tenant_context_service import get_tenant_context
from app.services.prompt_builder import build_messages
from app.services.tool_registry import get_allowed_tools
from app.services.tool_execution_engine import execute_tool_call
from app.services.agentic_planner import create_plan, refine_plan
from app.services.agentic_reflector import reflect_on_execution
from app.services.agentic_task_manager import create_task, update_task_state, complete_task
from app.adapters.vendor_adapter_openai import call_openai_responses, build_openai_tools
from app.adapters.vendor_adapter_gemini import call_gemini
from app.logging.event_logger import log_event, log_tool_call
from app.infra.database import get_db_session
from app.services.conversation_stats import update_conversation_stats
from app.infra.rate_limiter import check_rate_limit, get_rate_limit_headers
from app.services.cost_calculator import calculate_llm_cost, calculate_tool_cost
from app.infra.error_handler import retry_with_backoff, classify_error, RateLimitError, AuthError
from app.infra.circuit_breaker import openai_circuit_breaker, gemini_circuit_breaker
from app.infra.timeout import LLM_CALL_TIMEOUT
from app.infra.metrics import (
    llm_calls_total, llm_call_duration, tool_calls_total,
    plans_created_total, plan_execution_duration,
    tasks_created_total, tasks_resumed_total
)

# Maximum tool call iterations to prevent infinite loops
# Now loaded from TenantContext.max_tool_steps (default: 10)
MAX_TOOL_STEPS = 10  # Fallback default if not set in tenant context


def get_or_create_conversation(
    session: Session,
    tenant_id: str,
    channel_id: Optional[str],
    external_thread_id: Optional[str],
) -> str:
    """Get or create a conversation and return its ID."""
    # Try to find existing conversation
    if external_thread_id and channel_id:
        conv_row = session.execute(
            text("""
                SELECT id FROM conversations
                WHERE tenant_id = :tenant_id
                  AND channel_id = :channel_id
                  AND external_thread_id = :external_thread_id
            """),
            {
                "tenant_id": tenant_id,
                "channel_id": channel_id,
                "external_thread_id": external_thread_id,
            }
        ).fetchone()
        
        if conv_row:
            return str(conv_row.id)
    
    # Create new conversation
    conv_id = uuid.uuid4()
    session.execute(
        text("""
            INSERT INTO conversations (id, tenant_id, channel_id, external_thread_id, status)
            VALUES (:id, :tenant_id, :channel_id, :external_thread_id, 'open')
        """),
        {
            "id": conv_id,
            "tenant_id": tenant_id,
            "channel_id": channel_id,
            "external_thread_id": external_thread_id,
        }
    )
    return str(conv_id)


def persist_message(
    session: Session,
    tenant_id: str,
    conversation_id: str,
    channel_id: Optional[str],
    msg: CanonicalMessage,
) -> str:
    """Persist a message to the database and return its ID."""
    msg_id = uuid.uuid4()
    session.execute(
        text("""
            INSERT INTO messages (
                id, tenant_id, conversation_id, channel_id, direction,
                source_message_id, from_type, from_external_id, from_display_name,
                content_type, content_text, metadata
            ) VALUES (
                :id, :tenant_id, :conversation_id, :channel_id, :direction,
                :source_message_id, :from_type, :from_external_id, :from_display_name,
                :content_type, :content_text, CAST(:metadata AS jsonb)
            )
        """),
        {
            "id": msg_id,
            "tenant_id": tenant_id,
            "conversation_id": conversation_id,
            "channel_id": channel_id,
            "direction": msg.direction,
            "source_message_id": msg.source_message_id,
            "from_type": msg.from_.type,
            "from_external_id": msg.from_.external_id,
            "from_display_name": msg.from_.display_name,
            "content_type": msg.content.type,
            "content_text": msg.content.text,
            "metadata": json.dumps(msg.metadata or {}),
        }
    )
    return str(msg_id)


def get_conversation_history(
    session: Session,
    tenant_id: str,
    conversation_id: str,
    limit: int = 10,
) -> List[CanonicalMessage]:
    """Get recent conversation history."""
    rows = session.execute(
        text("""
            SELECT id, direction, source_message_id, from_type, from_external_id,
                   from_display_name, content_type, content_text, metadata, created_at
            FROM messages
            WHERE tenant_id = :tenant_id AND conversation_id = :conversation_id
            ORDER BY created_at DESC
            LIMIT :limit
        """),
        {
            "tenant_id": tenant_id,
            "conversation_id": conversation_id,
            "limit": limit,
        }
    ).fetchall()
    
    # Convert to CanonicalMessage objects (reverse to get chronological order)
    messages = []
    for row in reversed(rows):
        msg = CanonicalMessage(
            id=str(row.id),
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            channel="",  # Not stored in messages table, would need join
            direction=row.direction,
            source_message_id=row.source_message_id,
            from_=MessageParty(
                type=row.from_type,
                external_id=row.from_external_id or "",
                display_name=row.from_display_name,
            ),
            to=MessageParty(type="bot", external_id=""),  # Simplified
            content=MessageContent(type=row.content_type, text=row.content_text),
            metadata=row.metadata or {},
            timestamp=row.created_at.isoformat(),
        )
        messages.append(msg)
    
    return messages


async def handle_inbound_message_sync(
    message: CanonicalMessage,
    db: Session,
    api_tenant_id: Optional[str] = None,  # NEW: From API key auth
) -> Dict[str, Any]:
    """
    Internal handler for message processing (used by both sync and async endpoints).
    
    Flow:
    1. Validate tenant_id from API key matches message.tenant_id (prevent spoofing)
    2. Create immutable execution context from authentication
    3. Resolve TenantContext
    4. Get/create conversation
    5. Persist inbound message
    6. Build prompts
    7. Get allowed tools
    8. Call LLM
    9. Execute tool calls if needed (with execution context)
    10. Generate response
    11. Persist outbound message
    12. Log events
    """
    # SECURITY: Tenant ID must come from API key authentication, not message content
    # If api_tenant_id is provided, validate it matches message.tenant_id
    if api_tenant_id:
        if message.tenant_id != api_tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Tenant ID mismatch - potential spoofing attempt. Tenant ID must match API key."
            )
        tenant_id = api_tenant_id  # Use API key tenant_id (authoritative)
    else:
        # Fallback: use message.tenant_id (for backward compatibility, but less secure)
        tenant_id = message.tenant_id
    
    start_time = time.time()
    
    try:
        # Rate limiting check
        if not check_rate_limit(tenant_id, message.channel):
            rate_limit_headers = get_rate_limit_headers(tenant_id, message.channel)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded",
                headers=rate_limit_headers,
            )
        
        # Set tenant context for DB operations
        db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
        db.commit()
        
        # SECURITY: Create immutable execution context from authentication
        # This context cannot be modified by LLM or user input
        user_external_id = message.from_.external_id if message.from_ else None
        if not user_external_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Message must include user external_id in 'from' field"
            )
        
        # Load tenant context
        tenant_ctx = get_tenant_context(tenant_id)
        
        # Get or create conversation FIRST (before logging events)
        # Resolve channel_id from message metadata or channel lookup
        channel_id = message.metadata.get("channel_id")
        if not channel_id:
            # Try to lookup channel by tenant_id + channel type
            channel_row = db.execute(
                text("""
                    SELECT id FROM channels
                    WHERE tenant_id = :tenant_id
                      AND channel_type = :channel_type
                      AND is_active = TRUE
                    LIMIT 1
                """),
                {
                    "tenant_id": tenant_id,
                    "channel_type": message.channel,
                }
            ).fetchone()
            if channel_row:
                channel_id = str(channel_row.id)
        
        external_thread_id = message.metadata.get("external_thread_id")
        conversation_id = get_or_create_conversation(
            db, tenant_id, channel_id, external_thread_id
        )
        
        # Commit conversation creation before logging events
        db.commit()
        
        # Update message with actual conversation_id
        message.conversation_id = conversation_id
        
        # SECURITY: Create immutable execution context from authentication
        # This context is stored in session, NOT in LLM conversation
        # LLM cannot see or modify this context
        execution_context = {
            "tenant_id": tenant_id,  # From API key auth - IMMUTABLE
            "user_external_id": user_external_id,  # From authenticated message - IMMUTABLE
            "conversation_id": conversation_id,
            "channel": message.channel,
        }
        
        # Log inbound message event (after conversation is created and committed)
        await log_event(
            tenant_id=tenant_id,
            event_type="inbound_message",
            provider="channel",
            conversation_id=conversation_id,
        )
        
        # Persist inbound message
        inbound_msg_id = persist_message(db, tenant_id, conversation_id, channel_id, message)
        db.commit()
        
        # Get conversation history
        history = get_conversation_history(db, tenant_id, conversation_id)
        
        # Get allowed tools
        tools = get_allowed_tools(tenant_ctx)
        
        # Generate plan if planning is enabled
        plan = None
        plan_id = None
        if tenant_ctx.planning_enabled:
            try:
                planning_start_time = time.time()
                plan = await create_plan(
                    tenant_ctx=tenant_ctx,
                    goal=message.content.text,
                    available_tools=tools,
                    conversation_id=conversation_id,
                    message_id=inbound_msg_id,
                )
                plan_id = plan.get("plan_id")
                planning_latency_ms = int((time.time() - planning_start_time) * 1000)
                
                # Log plan creation
                await log_event(
                    tenant_id=tenant_id,
                    event_type="plan_created",
                    provider=tenant_ctx.llm_provider,
                    status="success",
                    latency_ms=planning_latency_ms,
                    conversation_id=conversation_id,
                    message_id=inbound_msg_id,
                    payload={"plan_id": plan_id, "step_count": len(plan.get("steps", [])), "complexity": plan.get("complexity", "medium")}
                )
                
                # Record metrics
                plans_created_total.labels(
                    tenant_id=tenant_id,
                    status="success"
                ).inc()
                plan_execution_duration.labels(
                    tenant_id=tenant_id
                ).observe(planning_latency_ms / 1000.0)
                
                # Update plan status to executing
                with get_db_session(tenant_id) as plan_session:
                    plan_session.execute(
                        text("""
                            UPDATE agentic_plans
                            SET status = 'executing', updated_at = now()
                            WHERE id = :plan_id AND tenant_id = :tenant_id
                        """),
                        {"plan_id": plan_id, "tenant_id": tenant_id}
                    )
                    plan_session.commit()
                
            except Exception as e:
                logger = logging.getLogger("app.api.utils")
                logger.warning(f"Plan generation failed, falling back to reactive execution: {str(e)}", exc_info=True)
                await log_event(
                    tenant_id=tenant_id,
                    event_type="plan_created",
                    provider=tenant_ctx.llm_provider,
                    status="failure",
                    conversation_id=conversation_id,
                    message_id=inbound_msg_id,
                    payload={"error": str(e)}
                )
                # Record metrics
                plans_created_total.labels(
                    tenant_id=tenant_id,
                    status="failure"
                ).inc()
                # Continue with reactive execution
        
        # Build prompts (include plan context if available)
        llm_messages = build_messages(tenant_ctx, history, message)
        
        # Add plan context to system message if plan exists
        if plan and plan_id:
            plan_context = f"\n\nEXECUTION PLAN:\n"
            plan_context += f"Goal: {plan.get('goal', '')}\n"
            plan_context += f"Steps ({len(plan.get('steps', []))} total):\n"
            for step in plan.get("steps", [])[:5]:  # Show first 5 steps
                plan_context += f"  {step.get('step_number')}. {step.get('description', '')}\n"
            if len(plan.get("steps", [])) > 5:
                plan_context += f"  ... and {len(plan.get('steps', [])) - 5} more steps\n"
            plan_context += "\nFollow this plan when executing tools. Update plan status as you progress."
            
            # Add to first system message or create new one
            if llm_messages and llm_messages[0].get("role") == "system":
                llm_messages[0]["content"] += plan_context
            else:
                llm_messages.insert(0, {"role": "system", "content": plan_context})
        
        # Create task if plan exists (for long-running operations)
        task_id = None
        if plan_id and plan:
            try:
                task = await create_task(
                    tenant_ctx=tenant_ctx,
                    goal=plan.get("goal", message.content.text),
                    plan_id=plan_id,
                    conversation_id=conversation_id,
                )
                task_id = task.get("task_id")
                tasks_created_total.labels(tenant_id=tenant_id, status="success").inc()
            except Exception as e:
                logger = logging.getLogger("app.api.utils")
                logger.warning(f"Failed to create task: {str(e)}", exc_info=True)
        
        # Call LLM with tool calling loop
        response_text = ""
        tool_calls_executed = 0
        max_steps = tenant_ctx.max_tool_steps if hasattr(tenant_ctx, 'max_tool_steps') else MAX_TOOL_STEPS
        execution_results = []  # Track execution results for reflection
        
        for step in range(max_steps):
            llm_start_time = time.time()
            
            # Call LLM with retry logic
            async def call_llm():
                if tenant_ctx.llm_provider == "openai":
                    # Build OpenAI tools
                    openai_tools = build_openai_tools(tools) if tools else None
                    
                    # Get vector store IDs from KB configs
                    vector_store_ids = []
                    logger = logging.getLogger("app.api.utils")
                    logger.info(f"KB configs for tenant {tenant_ctx.tenant_id}: {tenant_ctx.kb_configs}")
                    
                    for kb_name, kb_config in tenant_ctx.kb_configs.items():
                        logger.info(f"Processing KB: {kb_name}, config: {kb_config}")
                        if kb_config.get("provider") == "openai_file":
                            provider_config = kb_config.get("provider_config")
                            logger.info(f"Provider config type: {type(provider_config)}, value: {provider_config}")
                            
                            # Handle both dict and None cases
                            if provider_config:
                                if isinstance(provider_config, dict):
                                    vs_id = provider_config.get("vector_store_id")
                                else:
                                    vs_id = None
                                logger.info(f"Extracted vector_store_id: {vs_id}")
                                if vs_id:
                                    vector_store_ids.append(vs_id)
                    
                    logger.info(f"Final vector_store_ids: {vector_store_ids}")
                    logger.info(f"DEBUG EXTRACTION: tenant_id={tenant_ctx.tenant_id}, vector_store_ids={vector_store_ids}, kb_configs_keys={list(tenant_ctx.kb_configs.keys())}")
                    
                    return await call_openai_responses(
                        tenant_ctx, llm_messages, tools, vector_store_ids
                    )
                    
                elif tenant_ctx.llm_provider == "gemini":
                    # Get File Search Store names from KB configs
                    file_search_store_names = []
                    for kb_name, kb_config in tenant_ctx.kb_configs.items():
                        if kb_config.get("provider") == "gemini_file":
                            store_name = kb_config.get("provider_config", {}).get("file_search_store_name")
                            if store_name:
                                file_search_store_names.append(store_name)
                    
                    return await call_gemini(tenant_ctx, llm_messages, tools, file_search_store_names)
                else:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Unsupported LLM provider: {tenant_ctx.llm_provider}"
                    )
            
            async def on_retry_callback(e, attempt):
                """Callback for retry attempts."""
                await log_event(
                    tenant_id=tenant_id,
                    event_type="llm_call_retry",
                    provider=tenant_ctx.llm_provider,
                    status="retry",
                    conversation_id=conversation_id,
                    message_id=inbound_msg_id,
                )
            
            # Select circuit breaker
            circuit_breaker = (
                openai_circuit_breaker if tenant_ctx.llm_provider == "openai"
                else gemini_circuit_breaker
            )
            
            try:
                # Wrap call_llm with circuit breaker and timeout
                async def call_llm_with_circuit_breaker():
                    return await asyncio.wait_for(
                        circuit_breaker.call_async(call_llm),
                        timeout=LLM_CALL_TIMEOUT
                    )
                
                response = await retry_with_backoff(
                    call_llm_with_circuit_breaker,
                    max_retries=3,
                    initial_delay=1.0,
                    max_delay=30.0,
                    on_retry=on_retry_callback
                )
                
                # Calculate latency after successful call
                llm_latency_ms = int((time.time() - llm_start_time) * 1000)
                
                # Record metrics
                llm_calls_total.labels(
                    provider=tenant_ctx.llm_provider,
                    model=tenant_ctx.llm_model,
                    status="success"
                ).inc()
                llm_call_duration.labels(
                    provider=tenant_ctx.llm_provider,
                    model=tenant_ctx.llm_model
                ).observe(llm_latency_ms / 1000.0)
            except RuntimeError as e:
                # Circuit breaker open
                if "Circuit breaker is OPEN" in str(e):
                    llm_calls_total.labels(
                        provider=tenant_ctx.llm_provider,
                        model=tenant_ctx.llm_model,
                        status="circuit_open"
                    ).inc()
                    raise HTTPException(
                        status_code=503,
                        detail=f"Service temporarily unavailable: {str(e)}"
                    )
                raise
            except RateLimitError as e:
                # Rate limit - return 429
                raise HTTPException(
                    status_code=429,
                    detail=f"Rate limit exceeded: {e.message}",
                    headers={"Retry-After": str(int(e.retry_after or 60))} if e.retry_after else {}
                )
            except AuthError as e:
                # Auth error - return 401
                raise HTTPException(
                    status_code=401,
                    detail=f"Authentication failed: {e.message}"
                )
            except Exception as e:
                # Other errors - log and re-raise
                category, retryable, _ = classify_error(e)
                error_id = str(uuid.uuid4())
                llm_calls_total.labels(
                    provider=tenant_ctx.llm_provider,
                    model=tenant_ctx.llm_model,
                    status="failure"
                ).inc()
                await log_event(
                    tenant_id=tenant_id,
                    event_type="llm_call_failed",
                    provider=tenant_ctx.llm_provider,
                    status="failure",
                    conversation_id=conversation_id,
                    message_id=inbound_msg_id,
                    payload={"error": str(e), "category": category.value, "error_id": error_id}
                )
                raise HTTPException(
                    status_code=500,
                    detail=f"LLM call failed. Error ID: {error_id}"
                )
            
            # Extract response based on provider
            annotations = []
            if tenant_ctx.llm_provider == "openai":
                if response.get("choices"):
                    choice = response["choices"][0]
                    msg = choice.get("message", {})
                    response_text = msg.get("content") or ""
                    
                    if msg.get("annotations"):
                        annotations = msg["annotations"]
                        logger = logging.getLogger("app.api.utils")
                        logger.info(f"Extracted {len(annotations)} annotations from OpenAI response")
                    
                    tool_calls = []
                    if msg.get("tool_calls"):
                        for tc in msg["tool_calls"]:
                            tool_calls.append({
                                "id": tc.get("id"),
                                "function": {
                                    "name": tc.get("function", {}).get("name"),
                                    "arguments": tc.get("function", {}).get("arguments"),
                                }
                            })
                else:
                    tool_calls = []
                    
            elif tenant_ctx.llm_provider == "gemini":
                if response.get("candidates"):
                    candidate = response["candidates"][0]
                    content = candidate.get("content", {})
                    parts = content.get("parts", [])
                    response_text = parts[0].get("text", "") if parts else ""
                    
                    tool_calls = []
                    function_calls = content.get("function_calls")
                    if function_calls:
                        for fc in function_calls:
                            tool_calls.append({
                                "id": f"gemini-{fc.get('name')}",
                                "function": {
                                    "name": fc.get("name"),
                                    "arguments": json.dumps(fc.get("args", {})),
                                }
                            })
                else:
                    tool_calls = []
            
            # Calculate cost
            usage = response.get("usage") or response.get("usage_metadata")
            if usage:
                prompt_tokens = usage.get("prompt_tokens") or usage.get("prompt_token_count")
                completion_tokens = usage.get("completion_tokens") or usage.get("candidates_token_count")
                total_tokens = usage.get("total_tokens") or usage.get("total_token_count")
                
                llm_cost = calculate_llm_cost(
                    tenant_ctx.llm_provider,
                    tenant_ctx.llm_model,
                    prompt_tokens,
                    completion_tokens,
                    total_tokens,
                )
            else:
                llm_cost = 0.0
            
            # Store LLM trace (include plan_id if available)
            trace_payload = {
                "messages": llm_messages,
                "tools": [{"name": t.name, "description": t.description} for t in tools],
            }
            if plan_id:
                trace_payload["plan_id"] = plan_id
            
            with get_db_session(tenant_id) as trace_session:
                trace_session.execute(
                    text("""
                        INSERT INTO llm_traces (
                            tenant_id, conversation_id, message_id,
                            provider, model, request_payload, response_payload
                        ) VALUES (
                            :tenant_id, :conversation_id, :message_id,
                            :provider, :model, CAST(:request_payload AS jsonb), CAST(:response_payload AS jsonb)
                        )
                    """),
                    {
                        "tenant_id": tenant_id,
                        "conversation_id": conversation_id,
                        "message_id": inbound_msg_id,
                        "provider": tenant_ctx.llm_provider,
                        "model": tenant_ctx.llm_model,
                        "request_payload": json.dumps(trace_payload),
                        "response_payload": json.dumps(response) if isinstance(response, dict) else json.dumps({"content": str(response)}),
                    }
                )
                trace_session.commit()
            
            # Log LLM call
            await log_event(
                tenant_id=tenant_id,
                event_type="llm_call_completed",
                provider=tenant_ctx.llm_provider,
                status="success",
                latency_ms=llm_latency_ms,
                cost=llm_cost,
                conversation_id=conversation_id,
                message_id=inbound_msg_id,
            )
            
            # If no tool calls, we're done
            if not tool_calls:
                break
            
            # Add assistant message with tool_calls to messages (required by OpenAI)
            if tenant_ctx.llm_provider == "openai":
                assistant_msg = {
                    "role": "assistant",
                    "content": response_text if response_text else None,
                    "tool_calls": [
                        {
                            "id": tc.get("id"),
                            "type": "function",
                            "function": {
                                "name": tc.get("function", {}).get("name"),
                                "arguments": tc.get("function", {}).get("arguments"),
                            }
                        }
                        for tc in tool_calls
                    ]
                }
                llm_messages.append(assistant_msg)
            elif tenant_ctx.llm_provider == "gemini":
                if response_text:
                    llm_messages.append({
                        "role": "assistant",
                        "content": response_text
                    })
            
            # Execute tool calls
            for tool_call in tool_calls:
                tool_call_start_time = time.time()
                tool_name = tool_call.get("function", {}).get("name")
                tool_args_raw = tool_call.get("function", {}).get("arguments", {})
                
                # Parse tool arguments
                if isinstance(tool_args_raw, str):
                    try:
                        tool_args = json.loads(tool_args_raw)
                    except json.JSONDecodeError:
                        tool_args = {}
                else:
                    tool_args = tool_args_raw
                
                # Find tool definition
                tool_def = next((t for t in tools if t.name == tool_name), None)
                if not tool_def:
                    await log_tool_call(
                        tenant_id=tenant_id,
                        tool_name=tool_name,
                        provider="unknown",
                        arguments=tool_args,
                        result_summary={},
                        status="failure",
                        error_message=f"Tool {tool_name} not found",
                        conversation_id=conversation_id,
                        message_id=inbound_msg_id,
                    )
                    continue
                
                try:
                    # SECURITY: Execute tool with execution context for parameter override and header injection
                    tool_result = await execute_tool_call(
                        tenant_ctx, 
                        tool_def, 
                        tool_args,
                        execution_context=execution_context  # Pass immutable context
                    )
                    tool_latency_ms = int((time.time() - tool_call_start_time) * 1000)
                    
                    # Calculate tool cost
                    tool_cost = calculate_tool_cost(
                        tool_def.provider,
                        tool_name,
                        tool_latency_ms,
                    )
                    
                    # Record metrics
                    tool_calls_total.labels(
                        tool_name=tool_name,
                        provider=tool_def.provider,
                        status="success"
                    ).inc()
                    
                    # Log tool call with enhanced security audit fields
                    await log_tool_call(
                        tenant_id=tenant_id,
                        tool_name=tool_name,
                        provider=tool_def.provider,
                        arguments=tool_args,  # Already overridden if user-scoped
                        result_summary=tool_result,
                        status="success",
                        latency_ms=tool_latency_ms,
                        cost=tool_cost,
                        conversation_id=conversation_id,
                        message_id=inbound_msg_id,
                        execution_context=execution_context,  # For security audit
                    )
                    
                    # Add tool result to messages for next LLM call
                    tool_content = json.dumps(tool_result) if isinstance(tool_result, dict) else str(tool_result)
                    llm_messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.get("id"),
                        "content": tool_content,
                    })
                    
                    tool_calls_executed += 1
                    
                    # Track execution result for reflection
                    execution_results.append({
                        "step_number": step + 1,
                        "tool_name": tool_name,
                        "status": "success",
                        "result": tool_result,
                    })
                    
                    # Update task state if task exists
                    if task_id:
                        try:
                            await update_task_state(
                                tenant_ctx=tenant_ctx,
                                task_id=task_id,
                                current_step=step + 1,
                                state={"step_results": execution_results},
                            )
                        except Exception as e:
                            logger = logging.getLogger("app.api.utils")
                            logger.warning(f"Failed to update task state: {str(e)}", exc_info=True)
                except Exception as e:
                    tool_latency_ms = int((time.time() - tool_call_start_time) * 1000)
                    tool_cost = calculate_tool_cost(tool_def.provider, tool_name, tool_latency_ms)
                    
                    tool_calls_total.labels(
                        tool_name=tool_name,
                        provider=tool_def.provider,
                        status="failure"
                    ).inc()
                    
                    # SECURITY: Sanitize error message to prevent information disclosure
                    error_msg = str(e)
                    sanitized_error = "Unable to retrieve data"  # Generic error for users
                    if any(keyword in error_msg.lower() for keyword in ["tenant", "user", "customer", "id", "unauthorized", "forbidden"]):
                        # Log detailed error server-side only
                        logger = logging.getLogger("app.api.utils")
                        logger.error(f"Tool execution failed for {tool_name}: {error_msg}", exc_info=True)
                    
                    await log_tool_call(
                        tenant_id=tenant_id,
                        tool_name=tool_name,
                        provider=tool_def.provider,
                        arguments=tool_args,
                        result_summary={},
                        status="failure",
                        error_message=sanitized_error,  # Generic error to user
                        latency_ms=tool_latency_ms,
                        cost=tool_cost,
                        conversation_id=conversation_id,
                        message_id=inbound_msg_id,
                        execution_context=execution_context,  # For security audit
                    )
                    
                    # Track execution result for reflection
                    execution_results.append({
                        "step_number": step + 1,
                        "tool_name": tool_name,
                        "status": "failure",
                        "error": str(e),
                    })
        
        # Update plan status and complete task if plan exists
        if plan_id:
            plan_status = "completed" if response_text else "failed"
            final_outcome = "success" if response_text else "failed"
            
            with get_db_session(tenant_id) as plan_session:
                plan_session.execute(
                    text("""
                        UPDATE agentic_plans
                        SET status = :status, updated_at = now()
                        WHERE id = :plan_id AND tenant_id = :tenant_id
                    """),
                    {"plan_id": plan_id, "tenant_id": tenant_id, "status": plan_status}
                )
                plan_session.commit()
            
            # Log plan execution completion
            await log_event(
                tenant_id=tenant_id,
                event_type="plan_execution_completed",
                provider=tenant_ctx.llm_provider,
                status=plan_status,
                conversation_id=conversation_id,
                message_id=inbound_msg_id,
                payload={"plan_id": plan_id, "tool_calls_executed": tool_calls_executed}
            )
            
            # Reflect on execution and generate insights
            if execution_results:
                try:
                    await reflect_on_execution(
                        tenant_ctx=tenant_ctx,
                        plan_id=plan_id,
                        task_id=task_id,
                        execution_results=execution_results,
                        final_outcome=final_outcome,
                    )
                except Exception as e:
                    logger = logging.getLogger("app.api.utils")
                    logger.warning(f"Failed to reflect on execution: {str(e)}", exc_info=True)
            
            # Complete task if it exists
            if task_id:
                try:
                    await complete_task(
                        tenant_ctx=tenant_ctx,
                        task_id=task_id,
                        final_state={"execution_results": execution_results, "final_outcome": final_outcome},
                    )
                except Exception as e:
                    logger = logging.getLogger("app.api.utils")
                    logger.warning(f"Failed to complete task: {str(e)}", exc_info=True)
        
        # Create outbound message
        outbound_metadata = {}
        if annotations:
            outbound_metadata["annotations"] = annotations
            file_ids = []
            for ann in annotations:
                if ann.get("file_citation"):
                    file_ids.append(ann["file_citation"].get("file_id"))
                elif ann.get("file_path"):
                    file_ids.append(ann["file_path"].get("file_id"))
            if file_ids:
                outbound_metadata["file_ids"] = list(set(file_ids))
        if plan_id:
            outbound_metadata["plan_id"] = plan_id
        if task_id:
            outbound_metadata["task_id"] = task_id
        
        outbound_msg = CanonicalMessage(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            channel=message.channel,
            direction="outbound",
            source_message_id=None,
            from_=MessageParty(type="bot", external_id="orchestrator"),
            to=message.from_,
            content=MessageContent(type="text", text=response_text),
            metadata=outbound_metadata,
            timestamp=datetime.utcnow().isoformat(),
        )
        
        # Persist outbound message
        outbound_msg_id = persist_message(db, tenant_id, conversation_id, channel_id, outbound_msg)
        db.commit()
        
        # Log outbound message event
        await log_event(
            tenant_id=tenant_id,
            event_type="outbound_message",
            provider="channel",
            conversation_id=conversation_id,
            message_id=outbound_msg_id,
        )
        
        # Update conversation stats
        await update_conversation_stats(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            tool_calls=tool_calls_executed,
        )
        
        total_latency_ms = int((time.time() - start_time) * 1000)
        
        return {
            "status": "success",
            "message": outbound_msg.dict(),
            "latency_ms": total_latency_ms,
            "tool_calls_executed": tool_calls_executed,
        }
    
    except HTTPException:
        raise
    except Exception as e:
        # SECURITY: Don't expose internal error details to clients
        error_id = str(uuid.uuid4())
        await log_event(
            tenant_id=tenant_id,
            event_type="error",
            status="failure",
            payload={"error": str(e), "error_id": error_id},
            conversation_id=message.conversation_id,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error. Error ID: {error_id}"
        )

