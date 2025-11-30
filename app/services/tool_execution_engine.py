"""Tool execution engine that dispatches to appropriate providers."""

import asyncio
import logging
import re
from typing import Dict, Any, List, Optional
from app.models.tenant import TenantContext
from app.models.tool import ToolDefinition

from app.adapters.internal_rag_client import internal_rag_client
from app.adapters.vendor_adapter_openai import openai_file_client
from app.adapters.vendor_adapter_gemini import gemini_file_client
from app.adapters.mcp_client import mcp_client
from app.services.tool_mapping_service import get_provider_tools_for_abstract, get_provider_from_tool_name

logger = logging.getLogger(__name__)


def override_user_scoped_parameters(
    tool_def: ToolDefinition,
    llm_args: Dict[str, Any],
    execution_context: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Override user-scoped parameters with execution context.
    LLM arguments are ignored for user-scoped params to prevent LLM from fabricating user IDs.
    
    Args:
        tool_def: ToolDefinition (may have is_user_scoped and user_context_params)
        llm_args: Arguments provided by LLM
        execution_context: Immutable execution context from authentication
    
    Returns:
        Modified args dict with user-scoped parameters removed (MCP server will use headers)
    """
    if not tool_def.is_user_scoped or not tool_def.user_context_params:
        return llm_args
    
    overridden_args = llm_args.copy()
    overrides_applied = []
    
    for param_name in tool_def.user_context_params:
        if param_name in overridden_args:
            original_value = overridden_args[param_name]
            # Remove the param - MCP server will resolve from X-User-External-ID header
            del overridden_args[param_name]
            overrides_applied.append({
                "param": param_name,
                "original_value": str(original_value)[:50],  # Truncate for log
            })
    
        # Log overrides for security audit (detect injection attempts)
        if overrides_applied:
            logger.warning(
                f"Parameter override applied for tool {tool_def.name}: {overrides_applied}. "
                f"User: {execution_context.get('user_external_id')}, Tenant: {execution_context.get('tenant_id')}"
            )
            # Log to security audit (if security event logging exists)
            # Note: This is best-effort logging, don't block execution if it fails
            try:
                from app.logging.event_logger import log_event
                import asyncio
                # Create task but don't await (fire and forget for audit logging)
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.create_task(log_event(
                            tenant_id=execution_context.get("tenant_id"),
                            event_type="parameter_override",
                            provider="security",
                            status="success",
                            payload={
                                "tool_name": tool_def.name,
                                "overrides": overrides_applied,
                                "user_external_id": execution_context.get("user_external_id"),
                            },
                            conversation_id=execution_context.get("conversation_id"),
                        ))
                    else:
                        loop.run_until_complete(log_event(
                            tenant_id=execution_context.get("tenant_id"),
                            event_type="parameter_override",
                            provider="security",
                            status="success",
                            payload={
                                "tool_name": tool_def.name,
                                "overrides": overrides_applied,
                                "user_external_id": execution_context.get("user_external_id"),
                            },
                            conversation_id=execution_context.get("conversation_id"),
                        ))
                except RuntimeError:
                    # No event loop, skip async logging
                    pass
            except Exception:
                pass  # Don't fail if logging fails
    
    return overridden_args


def validate_tool_arguments_pattern(
    tool_def: ToolDefinition,
    args: Dict[str, Any],
    execution_context: Dict[str, Any],
) -> List[str]:
    """
    Validate tool arguments for suspicious patterns (defense-in-depth).
    Returns list of warnings (does not block execution - MCP server is final validator).
    
    Args:
        tool_def: ToolDefinition
        args: Tool arguments from LLM
        execution_context: Execution context
    
    Returns:
        List of warning messages (empty if no issues)
    """
    warnings = []
    
    # Check for SQL injection patterns
    sql_patterns = [
        r"';?\s*(DROP|DELETE|UPDATE|INSERT|ALTER|CREATE|TRUNCATE)",
        r"UNION\s+SELECT",
        r"OR\s+1\s*=\s*1",
        r"--",
        r"/\*",
    ]
    
    for param_name, param_value in args.items():
        if not isinstance(param_value, str):
            continue
        
        param_lower = param_value.lower()
        for pattern in sql_patterns:
            if re.search(pattern, param_lower, re.IGNORECASE):
                warnings.append(f"Suspicious SQL pattern detected in {param_name}")
                break
    
    # Check for cross-user reference attempts (if we have user context)
    user_scoped_params = ["customer_id", "user_id", "account_id", "client_id"]
    if execution_context.get("user_external_id"):
        for param_name in user_scoped_params:
            if param_name in args:
                # Log that we'll override this (defense-in-depth)
                warnings.append(f"User-scoped parameter {param_name} will be overridden with execution context")
    
    return warnings


async def execute_tool_call(
    tenant_ctx: TenantContext,
    tool_def: ToolDefinition,
    args: Dict[str, Any],
    execution_context: Optional[Dict[str, Any]] = None,  # NEW: Immutable execution context
) -> Dict[str, Any]:
    """
    Execute a tool call by dispatching to the appropriate provider client.
    
    For abstract tools like file_search, queries all enabled providers in parallel
    and merges results.
    
    SECURITY: Overrides user-scoped parameters with execution context to prevent LLM
    from fabricating user IDs.
    
    Args:
        tenant_ctx: TenantContext for tenant isolation
        tool_def: ToolDefinition for the tool to execute
        args: Tool arguments from LLM (may be overridden for user-scoped params)
        execution_context: Immutable execution context from authentication (tenant_id, user_external_id)
    
    Returns:
        Tool execution result as dict
    
    Raises:
        ValueError: If provider is unknown
    """
    # SECURITY: Pattern validation (defense-in-depth layer 1)
    if execution_context:
        warnings = validate_tool_arguments_pattern(tool_def, args, execution_context)
        if warnings:
            logger.warning(f"Tool argument validation warnings for {tool_def.name}: {warnings}")
    
    # SECURITY: Override user-scoped parameters (deterministic enforcement)
    # LLM-provided values are ignored - execution context is authoritative
    if execution_context:
        args = override_user_scoped_parameters(tool_def, args, execution_context)
    
    provider = tool_def.provider
    
    # Check if this is file_search (abstract tool that maps to multiple providers)
    if tool_def.name == "file_search":
        # Query all enabled providers in parallel
        return await _execute_multi_provider_search(tenant_ctx, tool_def, args)
    
    # Single provider execution
    if provider == "internal_rag":
        return await internal_rag_client.query(tenant_ctx, tool_def, args)
    elif provider == "openai_file":
        return await openai_file_client.search(tenant_ctx, tool_def, args)
    elif provider == "gemini_file":
        return await gemini_file_client.search(tenant_ctx, tool_def, args)
    elif provider == "mcp":
        # Pass execution_context to MCP client for header injection
        return await mcp_client.execute(tenant_ctx, tool_def, args, execution_context=execution_context)
    else:
        raise ValueError(f"Unknown provider: {provider}")


async def _execute_multi_provider_search(
    tenant_ctx: TenantContext,
    tool_def: ToolDefinition,
    args: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Execute file_search across all enabled providers and merge results.
    
    Args:
        tenant_ctx: TenantContext
        tool_def: ToolDefinition (file_search)
        args: Tool arguments
    
    Returns:
        Merged results from all providers
    """
    # Get available provider tools (based on API keys)
    provider_tools = get_provider_tools_for_abstract("file_search")
    
    # Verify which provider tools are actually enabled for this tenant
    from app.infra.database import get_db_session
    from sqlalchemy import text
    
    enabled_provider_tools = []
    with get_db_session(tenant_ctx.tenant_id) as session:
        for provider_tool_name in provider_tools:
            # Check if provider tool is enabled for tenant
            policy = session.execute(
                text("""
                    SELECT ttp.is_enabled
                    FROM tenant_tool_policies ttp
                    JOIN tools t ON ttp.tool_id = t.id
                    WHERE ttp.tenant_id = :tenant_id
                      AND t.name = :tool_name
                      AND ttp.is_enabled = TRUE
                """),
                {"tenant_id": tenant_ctx.tenant_id, "tool_name": provider_tool_name}
            ).fetchone()
            
            if policy:
                enabled_provider_tools.append(provider_tool_name)
    
    # Create tasks for each enabled provider
    tasks = []
    provider_names = []
    
    for provider_tool_name in enabled_provider_tools:
        provider = get_provider_from_tool_name(provider_tool_name)
        if not provider:
            continue
        
        # Create tool definition for this provider
        provider_tool_def = ToolDefinition(
            name=tool_def.name,  # Keep file_search name
            description=tool_def.description,
            parameters_schema=tool_def.parameters_schema,
            provider=provider,
            implementation_ref=tool_def.implementation_ref,
        )
        
        # Create async task
        if provider == "internal_rag":
            tasks.append(internal_rag_client.query(tenant_ctx, provider_tool_def, args))
        elif provider == "openai_file":
            tasks.append(openai_file_client.search(tenant_ctx, provider_tool_def, args))
        elif provider == "gemini_file":
            tasks.append(gemini_file_client.search(tenant_ctx, provider_tool_def, args))
        else:
            continue
        
        provider_names.append(provider)
    
    if not tasks:
        # No providers enabled
        return {
            "results": [],
            "count": 0,
            "providers_queried": [],
            "errors": [{"error": "No file search providers enabled for this tenant"}],
        }
    
    # Execute all providers in parallel
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Merge results
    all_results = []
    errors = []
    
    for i, result in enumerate(results):
        provider = provider_names[i]
        
        if isinstance(result, Exception):
            logger.error(f"Error querying provider {provider}: {result}", exc_info=True)
            errors.append({"provider": provider, "error": str(result)})
            continue
        
        if isinstance(result, dict) and "results" in result:
            # Add provider info to each result
            for item in result.get("results", []):
                if isinstance(item, dict):
                    item["_provider"] = provider
                all_results.append(item)
        elif isinstance(result, dict):
            # Single result
            result["_provider"] = provider
            all_results.append(result)
    
    # Sort by score if available (higher is better)
    if all_results and any("score" in r for r in all_results if isinstance(r, dict)):
        all_results.sort(key=lambda x: x.get("score", 0) if isinstance(x, dict) else 0, reverse=True)
    
    return {
        "results": all_results,
        "count": len(all_results),
        "providers_queried": provider_names,
        "errors": errors if errors else None,
    }

