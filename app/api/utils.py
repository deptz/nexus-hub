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
from app.infra.metrics import llm_calls_total, llm_call_duration, tool_calls_total

# Maximum tool call iterations to prevent infinite loops
MAX_TOOL_STEPS = 3


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
) -> Dict[str, Any]:
    """
    Internal handler for message processing (used by both sync and async endpoints).
    
    Flow:
    1. Resolve TenantContext
    2. Get/create conversation
    3. Persist inbound message
    4. Build prompts
    5. Get allowed tools
    6. Call LLM
    7. Execute tool calls if needed
    8. Generate response
    9. Persist outbound message
    10. Log events
    """
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
        
        # Build prompts
        llm_messages = build_messages(tenant_ctx, history, message)
        
        # Get allowed tools
        tools = get_allowed_tools(tenant_ctx)
        
        # Call LLM with tool calling loop
        response_text = ""
        tool_calls_executed = 0
        
        for step in range(MAX_TOOL_STEPS):
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
            
            # Store LLM trace
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
                        "request_payload": json.dumps({
                            "messages": llm_messages,
                            "tools": [{"name": t.name, "description": t.description} for t in tools],
                        }),
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
                    # Execute tool
                    tool_result = await execute_tool_call(tenant_ctx, tool_def, tool_args)
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
                    
                    # Log tool call
                    await log_tool_call(
                        tenant_id=tenant_id,
                        tool_name=tool_name,
                        provider=tool_def.provider,
                        arguments=tool_args,
                        result_summary=tool_result,
                        status="success",
                        latency_ms=tool_latency_ms,
                        cost=tool_cost,
                        conversation_id=conversation_id,
                        message_id=inbound_msg_id,
                    )
                    
                    # Add tool result to messages for next LLM call
                    tool_content = json.dumps(tool_result) if isinstance(tool_result, dict) else str(tool_result)
                    llm_messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.get("id"),
                        "content": tool_content,
                    })
                    
                    tool_calls_executed += 1
                except Exception as e:
                    tool_latency_ms = int((time.time() - tool_call_start_time) * 1000)
                    tool_cost = calculate_tool_cost(tool_def.provider, tool_name, tool_latency_ms)
                    
                    tool_calls_total.labels(
                        tool_name=tool_name,
                        provider=tool_def.provider,
                        status="failure"
                    ).inc()
                    
                    await log_tool_call(
                        tenant_id=tenant_id,
                        tool_name=tool_name,
                        provider=tool_def.provider,
                        arguments=tool_args,
                        result_summary={},
                        status="failure",
                        error_message=str(e),
                        latency_ms=tool_latency_ms,
                        cost=tool_cost,
                        conversation_id=conversation_id,
                        message_id=inbound_msg_id,
                    )
        
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

