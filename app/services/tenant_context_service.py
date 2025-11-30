"""Service to load TenantContext from database."""

from typing import Dict, Any, List
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.models.tenant import TenantContext
from app.infra.database import get_db_session


def get_tenant_context(tenant_id: str) -> TenantContext:
    """
    Load complete TenantContext for a tenant.
    
    Loads:
    - Tenant base settings (llm_provider, llm_model, isolation_mode)
    - Tenant prompts
    - Tenant tool policies + tools
    - Knowledge bases
    - MCP servers
    """
    with get_db_session(tenant_id) as session:
        # Load tenant base settings
        tenant_row = session.execute(
            text("""
                SELECT id, llm_provider, llm_model, isolation_mode,
                       COALESCE(max_tool_steps, 10) as max_tool_steps,
                       COALESCE(planning_enabled, TRUE) as planning_enabled,
                       COALESCE(plan_timeout_seconds, 300) as plan_timeout_seconds
                FROM tenants
                WHERE id = :tenant_id
            """),
            {"tenant_id": tenant_id}
        ).fetchone()
        
        if not tenant_row:
            raise ValueError(f"Tenant {tenant_id} not found")
        
        llm_provider = tenant_row.llm_provider
        llm_model = tenant_row.llm_model
        isolation_mode = tenant_row.isolation_mode
        max_tool_steps = tenant_row.max_tool_steps
        planning_enabled = tenant_row.planning_enabled
        plan_timeout_seconds = tenant_row.plan_timeout_seconds
        
        # Load tenant prompt profile
        prompt_row = session.execute(
            text("""
                SELECT custom_system_prompt, override_mode, language_preference, tone_profile
                FROM tenant_prompts
                WHERE tenant_id = :tenant_id
            """),
            {"tenant_id": tenant_id}
        ).fetchone()
        
        prompt_profile: Dict[str, Any] = {}
        if prompt_row:
            prompt_profile = {
                "custom_system_prompt": prompt_row.custom_system_prompt,
                "override_mode": prompt_row.override_mode,
                "language_preference": prompt_row.language_preference,
                "tone_profile": prompt_row.tone_profile or {},
            }
        
        # Load allowed tools (from tenant_tool_policies)
        tool_policies = session.execute(
            text("""
                SELECT t.id, t.name, t.description, t.provider, t.parameters_schema, 
                       t.implementation_ref, ttp.config_override
                FROM tenant_tool_policies ttp
                JOIN tools t ON ttp.tool_id = t.id
                WHERE ttp.tenant_id = :tenant_id AND ttp.is_enabled = TRUE
            """),
            {"tenant_id": tenant_id}
        ).fetchall()
        
        allowed_tools: List[str] = [row.name for row in tool_policies]
        
        # Load knowledge bases
        kb_rows = session.execute(
            text("""
                SELECT name, provider, provider_config
                FROM knowledge_bases
                WHERE tenant_id = :tenant_id AND is_active = TRUE
            """),
            {"tenant_id": tenant_id}
        ).fetchall()
        
        kb_configs: Dict[str, Any] = {}
        for row in kb_rows:
            kb_configs[row.name] = {
                "provider": row.provider,
                "provider_config": row.provider_config,
            }
        
        # Load MCP servers
        mcp_rows = session.execute(
            text("""
                SELECT id, name, endpoint, auth_config
                FROM mcp_servers
                WHERE tenant_id = :tenant_id AND is_active = TRUE
            """),
            {"tenant_id": tenant_id}
        ).fetchall()
        
        mcp_configs: Dict[str, Any] = {}
        for row in mcp_rows:
            mcp_configs[row.name] = {
                "server_id": str(row.id),
                "endpoint": row.endpoint,
                "auth_config": row.auth_config,
            }
        
        return TenantContext(
            tenant_id=tenant_id,
            llm_provider=llm_provider,
            llm_model=llm_model,
            allowed_tools=allowed_tools,
            kb_configs=kb_configs,
            mcp_configs=mcp_configs,
            prompt_profile=prompt_profile,
            isolation_mode=isolation_mode,
            max_tool_steps=max_tool_steps,
            planning_enabled=planning_enabled,
            plan_timeout_seconds=plan_timeout_seconds,
        )


