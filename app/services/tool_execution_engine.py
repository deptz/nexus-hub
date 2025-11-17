"""Tool execution engine that dispatches to appropriate providers."""

import asyncio
import logging
from typing import Dict, Any, List
from app.models.tenant import TenantContext
from app.models.tool import ToolDefinition

from app.adapters.internal_rag_client import internal_rag_client
from app.adapters.vendor_adapter_openai import openai_file_client
from app.adapters.vendor_adapter_gemini import gemini_file_client
from app.adapters.mcp_client import mcp_client
from app.services.tool_mapping_service import get_provider_tools_for_abstract, get_provider_from_tool_name

logger = logging.getLogger(__name__)


async def execute_tool_call(
    tenant_ctx: TenantContext,
    tool_def: ToolDefinition,
    args: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Execute a tool call by dispatching to the appropriate provider client.
    
    For abstract tools like file_search, queries all enabled providers in parallel
    and merges results.
    
    Args:
        tenant_ctx: TenantContext for tenant isolation
        tool_def: ToolDefinition for the tool to execute
        args: Tool arguments from LLM
    
    Returns:
        Tool execution result as dict
    
    Raises:
        ValueError: If provider is unknown
    """
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
        return await mcp_client.execute(tenant_ctx, tool_def, args)
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

