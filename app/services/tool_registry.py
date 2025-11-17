"""Tool registry for canonical tools."""

from typing import List
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.models.tenant import TenantContext
from app.models.tool import ToolDefinition
from app.infra.database import get_db_session
from app.services.tool_mapping_service import (
    is_abstract_tool,
    get_provider_tools_for_abstract,
    get_provider_from_tool_name,
)


def get_allowed_tools(tenant_ctx: TenantContext) -> List[ToolDefinition]:
    """
    Get allowed tools for a tenant based on tenant_tool_policies.
    Expands abstract tools (like file_search) to provider-specific tools.
    
    Returns canonical ToolDefinition objects that the tenant is allowed to use.
    """
    with get_db_session(tenant_ctx.tenant_id) as session:
        # Load tools from tenant_tool_policies (excluding internal tools)
        tool_rows = session.execute(
            text("""
                SELECT t.id, t.name, t.description, t.provider, 
                       t.parameters_schema, t.implementation_ref, ttp.config_override
                FROM tenant_tool_policies ttp
                JOIN tools t ON ttp.tool_id = t.id
                WHERE ttp.tenant_id = :tenant_id 
                  AND ttp.is_enabled = TRUE
                  AND (t.is_internal IS NULL OR t.is_internal = FALSE)
            """),
            {"tenant_id": tenant_ctx.tenant_id}
        ).fetchall()
        
        tools = []
        for row in tool_rows:
            # For abstract tools, return the abstract tool itself
            # tool_execution_engine will handle multi-provider expansion
            implementation_ref = row.implementation_ref.copy()
            if row.config_override:
                implementation_ref.update(row.config_override)
            
            tool_def = ToolDefinition(
                name=row.name,
                description=row.description,
                parameters_schema=row.parameters_schema,
                provider=row.provider,  # For abstract tools, this is the base provider (internal_rag)
                implementation_ref=implementation_ref,
            )
            tools.append(tool_def)
        
        return tools

