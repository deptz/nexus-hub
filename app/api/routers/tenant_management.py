"""Tenant Management API router."""

import json
import uuid
from datetime import datetime
from typing import Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Depends, Security, Query
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.infra.database import get_db
from app.infra.auth import verify_api_key, require_tenant_access
from app.infra.validation import validate_tenant_id
from app.services.tool_mapping_service import (
    is_internal_tool,
    is_abstract_tool,
    get_provider_tools_for_abstract,
    get_provider_from_tool_name,
)
from app.services.kb_sync_service import kb_sync_service
import logging

logger = logging.getLogger(__name__)
from app.api.models import (
    UpdatePromptRequest,
    GetPromptResponse,
    PromptUpdateResponse,
    EnableToolRequest,
    UpdateToolPolicyRequest,
    TenantToolResponse,
    TenantToolsListResponse,
    CreateAPIKeyRequest,
)

router = APIRouter()


# ============================================================================
# Prompt Management Endpoints
# ============================================================================

@router.put("/tenants/{tenant_id}/prompt", tags=["Tenant Management"], response_model=PromptUpdateResponse)
async def update_tenant_prompt(
    tenant_id: str,
    request: UpdatePromptRequest,
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """
    Update tenant system prompt with validation.
    
    Requires API key authentication. Only the tenant owner or master key can update prompts.
    
    The prompt will be validated for security (e.g., no meta-instruction attempts).
    If validation fails, a 400 error is returned with details.
    
    **Example Request:**
    ```json
    {
        "custom_system_prompt": "You are a helpful assistant for ACME Corp.",
        "override_mode": "append"
    }
    ```
    """
    from app.services.admin_api import update_tenant_prompt
    
    # SECURITY: Validate tenant_id format before processing
    try:
        validate_tenant_id(tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    # Verify tenant access
    require_tenant_access(tenant_id, api_tenant_id)
    
    # Validate prompt content
    try:
        request.custom_system_prompt = validate_prompt_content(request.custom_system_prompt)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    # Set tenant context for DB operations
    db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
    db.commit()
    
    try:
        result = await update_tenant_prompt(
            tenant_id,
            request.custom_system_prompt,
            request.override_mode
        )
        return PromptUpdateResponse(**result)
    except ValueError as e:
        # Validation failed
        error_data = e.args[0] if e.args else {"error": "PROMPT_VALIDATION_FAILED"}
        raise HTTPException(status_code=400, detail=error_data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tenants/{tenant_id}/prompt", tags=["Tenant Management"], response_model=GetPromptResponse)
async def get_tenant_prompt(
    tenant_id: str,
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """
    Get current tenant prompt configuration.
    
    Requires API key authentication. Returns the current custom system prompt,
    override mode, and timestamps.
    
    Returns 404 if no prompt has been configured for this tenant.
    """
    # SECURITY: Validate tenant_id format
    try:
        validate_tenant_id(tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    # Verify tenant access
    require_tenant_access(tenant_id, api_tenant_id)
    
    # Set tenant context for DB operations
    db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
    db.commit()
    
    # Query prompt
    row = db.execute(
        text("""
            SELECT custom_system_prompt, override_mode, created_at, updated_at
            FROM tenant_prompts
            WHERE tenant_id = :tenant_id
        """),
        {"tenant_id": tenant_id}
    ).fetchone()
    
    if not row:
        raise HTTPException(status_code=404, detail="No prompt configured for this tenant")
    
    return GetPromptResponse(
        custom_system_prompt=row.custom_system_prompt,
        override_mode=row.override_mode,
        created_at=row.created_at.isoformat(),
        updated_at=row.updated_at.isoformat(),
    )


@router.delete("/tenants/{tenant_id}/prompt", tags=["Tenant Management"])
async def delete_tenant_prompt(
    tenant_id: str,
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """
    Delete/remove tenant prompt (revert to default).
    
    Requires API key authentication. Permanently removes the custom prompt
    for this tenant, reverting to default behavior.
    
    Returns success even if no prompt exists (idempotent).
    """
    # SECURITY: Validate tenant_id format
    try:
        validate_tenant_id(tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    # Verify tenant access
    require_tenant_access(tenant_id, api_tenant_id)
    
    # Set tenant context for DB operations
    db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
    db.commit()
    
    # Delete prompt
    result = db.execute(
        text("""
            DELETE FROM tenant_prompts
            WHERE tenant_id = :tenant_id
        """),
        {"tenant_id": tenant_id}
    )
    db.commit()
    
    return {
        "status": "deleted",
        "message": "Tenant prompt deleted successfully"
    }


# ============================================================================
# Tenant Tool Management Endpoints
# ============================================================================

@router.get("/tenants/{tenant_id}/tools", tags=["Tenant Management"], response_model=TenantToolsListResponse)
async def list_tenant_tools(
    tenant_id: str,
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
    include_disabled: bool = Query(default=False, description="Include disabled tools in the response"),
):
    """
    List all tools enabled for a tenant.
    
    Requires API key authentication. Returns all tools that have been configured
    for this tenant, including their enabled/disabled status and configuration overrides.
    
    By default, only enabled tools are returned. Set `include_disabled=true` to see all tools.
    
    **Example Response:**
    ```json
    {
        "items": [
            {
                "tool_id": "uuid",
                "tool_name": "openai_file_search",
                "description": "Search documents using OpenAI file search",
                "provider": "openai_file",
                "is_enabled": true,
                "config_override": {},
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:00Z"
            }
        ],
        "count": 1
    }
    ```
    """
    # SECURITY: Validate tenant_id format
    try:
        validate_tenant_id(tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    # Verify tenant access
    require_tenant_access(tenant_id, api_tenant_id)
    
    # Set tenant context for DB operations
    db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
    db.commit()
    
    # Query tenant tool policies
    # Filter out internal tools from user-facing list
    # Build query condition safely (no SQL injection - include_disabled is boolean)
    if include_disabled:
        rows = db.execute(
            text("""
                SELECT t.id, t.name, t.description, t.provider,
                       ttp.is_enabled, ttp.config_override,
                       ttp.created_at, ttp.updated_at
                FROM tenant_tool_policies ttp
                JOIN tools t ON ttp.tool_id = t.id
                WHERE ttp.tenant_id = :tenant_id
                  AND (t.is_internal IS NULL OR t.is_internal = FALSE)
                ORDER BY t.name
            """),
            {"tenant_id": tenant_id}
        ).fetchall()
    else:
        rows = db.execute(
            text("""
                SELECT t.id, t.name, t.description, t.provider,
                       ttp.is_enabled, ttp.config_override,
                       ttp.created_at, ttp.updated_at
                FROM tenant_tool_policies ttp
                JOIN tools t ON ttp.tool_id = t.id
                WHERE ttp.tenant_id = :tenant_id 
                  AND ttp.is_enabled = TRUE
                  AND (t.is_internal IS NULL OR t.is_internal = FALSE)
                ORDER BY t.name
            """),
            {"tenant_id": tenant_id}
        ).fetchall()
    
    items = [
        TenantToolResponse(
            tool_id=str(row.id),
            tool_name=row.name,
            description=row.description,
            provider=row.provider,
            is_enabled=row.is_enabled,
            config_override=row.config_override or {},
            created_at=row.created_at.isoformat(),
            updated_at=row.updated_at.isoformat(),
        )
        for row in rows
    ]
    
    return TenantToolsListResponse(items=items, count=len(items))


@router.post("/tenants/{tenant_id}/tools", tags=["Tenant Management"], response_model=TenantToolResponse)
async def enable_tool_for_tenant(
    tenant_id: str,
    request: EnableToolRequest,
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """
    Enable a tool for a tenant.
    
    Requires API key authentication. Enables a tool for the specified tenant.
    If the tool is already enabled, updates the configuration override.
    
    The tool must exist in the `tools` table. You can enable multiple tools per tenant.
    
    **Example Request:**
    ```json
    {
        "tool_name": "openai_file_search",
        "config_override": {
            "kb_name": "custom_kb"
        }
    }
    ```
    
    **Example Response:**
    ```json
    {
        "tool_id": "uuid",
        "tool_name": "openai_file_search",
        "description": "Search documents using OpenAI file search",
        "provider": "openai_file",
        "is_enabled": true,
        "config_override": {"kb_name": "custom_kb"},
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z"
    }
    ```
    """
    # SECURITY: Validate tenant_id format
    try:
        validate_tenant_id(tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    # Verify tenant access
    require_tenant_access(tenant_id, api_tenant_id)
    
    # Set tenant context for DB operations
    db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
    db.commit()
    
    # Check if tool is internal (deprecated)
    if is_internal_tool(request.tool_name):
        raise HTTPException(
            status_code=400,
            detail=f"This tool is managed automatically. Please enable 'file_search' instead."
        )
    
    # Verify tool exists
    tool = db.execute(
        text("""
            SELECT id, name, description, provider, is_internal
            FROM tools
            WHERE name = :tool_name
        """),
        {"tool_name": request.tool_name}
    ).fetchone()
    
    if not tool:
        raise HTTPException(
            status_code=404,
            detail=f"Tool '{request.tool_name}' not found. Available tools must be created first."
        )
    
    # Double-check if tool is internal (from DB)
    if tool.is_internal:
        raise HTTPException(
            status_code=400,
            detail=f"This tool is managed automatically. Please enable 'file_search' instead."
        )
    
    # Check if policy already exists
    existing = db.execute(
        text("""
            SELECT ttp.id, ttp.is_enabled, ttp.config_override, ttp.created_at, ttp.updated_at
            FROM tenant_tool_policies ttp
            WHERE ttp.tenant_id = :tenant_id AND ttp.tool_id = :tool_id
        """),
        {"tenant_id": tenant_id, "tool_id": tool.id}
    ).fetchone()
    
    if existing:
        # Update existing policy
        db.execute(
            text("""
                UPDATE tenant_tool_policies
                SET is_enabled = TRUE,
                    config_override = CAST(:config_override AS jsonb),
                    updated_at = now()
                WHERE id = :id
            """),
            {
                "id": existing.id,
                "config_override": json.dumps(request.config_override or {}),
            }
        )
        created_at = existing.created_at
    else:
        # Create new policy
        policy_id = uuid.uuid4()
        db.execute(
            text("""
                INSERT INTO tenant_tool_policies (
                    id, tenant_id, tool_id, is_enabled, config_override
                ) VALUES (
                    :id, :tenant_id, :tool_id, TRUE, CAST(:config_override AS jsonb)
                )
            """),
            {
                "id": policy_id,
                "tenant_id": tenant_id,
                "tool_id": tool.id,
                "config_override": json.dumps(request.config_override or {}),
            }
        )
        created_at = datetime.now()
    
    db.commit()
    
    # Fetch updated policy
    row = db.execute(
        text("""
            SELECT ttp.is_enabled, ttp.config_override, ttp.created_at, ttp.updated_at
            FROM tenant_tool_policies ttp
            WHERE ttp.tenant_id = :tenant_id AND ttp.tool_id = :tool_id
        """),
        {"tenant_id": tenant_id, "tool_id": tool.id}
    ).fetchone()
    
    return TenantToolResponse(
        tool_id=str(tool.id),
        tool_name=tool.name,
        description=tool.description,
        provider=tool.provider,
        is_enabled=row.is_enabled,
        config_override=row.config_override or {},
        created_at=row.created_at.isoformat(),
        updated_at=row.updated_at.isoformat(),
    )


@router.put("/tenants/{tenant_id}/tools/{tool_name}", tags=["Tenant Management"], response_model=TenantToolResponse)
async def update_tool_policy(
    tenant_id: str,
    tool_name: str,
    request: UpdateToolPolicyRequest,
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """
    Update a tool policy for a tenant (enable/disable or update config).
    
    Requires API key authentication. Updates the tool policy for the specified tenant.
    You can enable/disable the tool or update its configuration override.
    
    **Example Request:**
    ```json
    {
        "is_enabled": false,
        "config_override": {
            "kb_name": "updated_kb"
        }
    }
    ```
    """
    # SECURITY: Validate tenant_id format
    try:
        validate_tenant_id(tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    # Verify tenant access
    require_tenant_access(tenant_id, api_tenant_id)
    
    # Set tenant context for DB operations
    db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
    db.commit()
    
    # Check if tool is internal (deprecated)
    if is_internal_tool(tool_name):
        raise HTTPException(
            status_code=400,
            detail=f"This tool is managed automatically. Please update 'file_search' instead."
        )
    
    # Verify tool exists
    tool = db.execute(
        text("""
            SELECT id, name, description, provider, is_internal
            FROM tools
            WHERE name = :tool_name
        """),
        {"tool_name": tool_name}
    ).fetchone()
    
    if not tool:
        raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found")
    
    # Double-check if tool is internal (from DB)
    if tool.is_internal:
        raise HTTPException(
            status_code=400,
            detail=f"This tool is managed automatically. Please update 'file_search' instead."
        )
    
    # Verify policy exists
    policy = db.execute(
        text("""
            SELECT id, is_enabled, config_override, created_at, updated_at
            FROM tenant_tool_policies
            WHERE tenant_id = :tenant_id AND tool_id = :tool_id
        """),
        {"tenant_id": tenant_id, "tool_id": tool.id}
    ).fetchone()
    
    if not policy:
        raise HTTPException(
            status_code=404,
            detail=f"Tool '{tool_name}' is not configured for this tenant. Use POST to enable it first."
        )
    
    # Build update query dynamically based on what's provided
    # Use safe parameterized queries - only boolean and JSON fields are updated
    if request.is_enabled is None and request.config_override is None:
        raise HTTPException(status_code=400, detail="No fields to update. Provide is_enabled or config_override.")
    
    # Build safe update query
    set_clauses = []
    params = {"id": policy.id}
    
    if request.is_enabled is not None:
        set_clauses.append("is_enabled = :is_enabled")
        params["is_enabled"] = request.is_enabled
    
    if request.config_override is not None:
        set_clauses.append("config_override = CAST(:config_override AS jsonb)")
        params["config_override"] = json.dumps(request.config_override)
    
    set_clauses.append("updated_at = now()")
    
    # Use parameterized query - set_clauses only contains safe field names
    query = f"UPDATE tenant_tool_policies SET {', '.join(set_clauses)} WHERE id = :id"
    db.execute(text(query), params)
    db.commit()
    
    # Fetch updated policy
    row = db.execute(
        text("""
            SELECT ttp.is_enabled, ttp.config_override, ttp.created_at, ttp.updated_at
            FROM tenant_tool_policies ttp
            WHERE ttp.tenant_id = :tenant_id AND ttp.tool_id = :tool_id
        """),
        {"tenant_id": tenant_id, "tool_id": tool.id}
    ).fetchone()
    
    return TenantToolResponse(
        tool_id=str(tool.id),
        tool_name=tool.name,
        description=tool.description,
        provider=tool.provider,
        is_enabled=row.is_enabled,
        config_override=row.config_override or {},
        created_at=row.created_at.isoformat(),
        updated_at=row.updated_at.isoformat(),
    )


@router.delete("/tenants/{tenant_id}/tools/{tool_name}", tags=["Tenant Management"])
async def disable_tool_for_tenant(
    tenant_id: str,
    tool_name: str,
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """
    Disable a tool for a tenant (or delete the policy).
    
    Requires API key authentication. Permanently removes the tool policy for this tenant,
    effectively disabling the tool. The tool itself remains in the system.
    
    Returns success even if the tool is not enabled for this tenant (idempotent).
    """
    # SECURITY: Validate tenant_id format
    try:
        validate_tenant_id(tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    # Verify tenant access
    require_tenant_access(tenant_id, api_tenant_id)
    
    # Set tenant context for DB operations
    db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
    db.commit()
    
    # Check if tool is internal (deprecated)
    if is_internal_tool(tool_name):
        raise HTTPException(
            status_code=400,
            detail=f"This tool is managed automatically. Please disable 'file_search' instead."
        )
    
    # Verify tool exists
    tool = db.execute(
        text("""
            SELECT id, is_internal FROM tools
            WHERE name = :tool_name
        """),
        {"tool_name": tool_name}
    ).fetchone()
    
    if not tool:
        raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found")
    
    # Double-check if tool is internal (from DB)
    if tool.is_internal:
        raise HTTPException(
            status_code=400,
            detail=f"This tool is managed automatically. Please disable 'file_search' instead."
        )
    
    # Delete policy
    result = db.execute(
        text("""
            DELETE FROM tenant_tool_policies
            WHERE tenant_id = :tenant_id AND tool_id = :tool_id
        """),
        {"tenant_id": tenant_id, "tool_id": tool.id}
    )
    db.commit()
    
    # If abstract tool (file_search), auto-disable provider tools
    if is_abstract_tool(tool_name):
        provider_tools = get_provider_tools_for_abstract(tool_name)
        
        for provider_tool_name in provider_tools:
            try:
                # Get provider tool
                provider_tool = db.execute(
                    text("""
                        SELECT id FROM tools WHERE name = :tool_name
                    """),
                    {"tool_name": provider_tool_name}
                ).fetchone()
                
                if not provider_tool:
                    continue
                
                # Disable provider tool internally
                db.execute(
                    text("""
                        DELETE FROM tenant_tool_policies
                        WHERE tenant_id = :tenant_id AND tool_id = :tool_id
                    """),
                    {
                        "tenant_id": tenant_id,
                        "tool_id": provider_tool.id,
                    }
                )
                
                # Update all KBs for tenant - disable provider sync
                provider = get_provider_from_tool_name(provider_tool_name)
                if provider:
                    # Get all KBs for tenant
                    kbs = db.execute(
                        text("""
                            SELECT id FROM knowledge_bases
                            WHERE tenant_id = :tenant_id
                        """),
                        {"tenant_id": tenant_id}
                    ).fetchall()
                    
                    for kb in kbs:
                        # Soft disable provider (keep data)
                        db.execute(
                            text("""
                                UPDATE kb_provider_sync
                                SET is_active = FALSE,
                                    sync_status = 'disabled',
                                    updated_at = now()
                                WHERE kb_id = :kb_id AND provider = :provider
                            """),
                            {
                                "kb_id": kb.id,
                                "provider": provider,
                            }
                        )
                
            except Exception as e:
                logger.error(f"Error disabling provider tool {provider_tool_name}: {e}", exc_info=True)
        
        db.commit()
    
    if result.rowcount == 0:
        # Idempotent - return success even if not found
        return {
            "status": "deleted",
            "message": f"Tool '{tool_name}' was not enabled for this tenant (or already disabled)"
        }
    
    return {
        "status": "deleted",
        "message": f"Tool '{tool_name}' disabled for tenant successfully"
    }


# ============================================================================
# API Key Management Endpoints
# ============================================================================

@router.post("/tenants/{tenant_id}/api-keys", tags=["Tenant Management"])
async def create_api_key_endpoint(
    tenant_id: str,
    request: CreateAPIKeyRequest,
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """
    Create a new API key for a tenant.
    
    Requires API key authentication. Only the tenant owner or master key can create API keys.
    
    **WARNING**: The API key is only returned once in the response. Store it securely!
    
    Returns:
        API key object with the plain text key (shown only once)
    """
    from app.services.api_key_service import create_api_key as create_api_key_service
    
    # SECURITY: Validate tenant_id format
    try:
        validate_tenant_id(tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    # Verify tenant access
    require_tenant_access(tenant_id, api_tenant_id)
    
    try:
        result = await create_api_key_service(
            tenant_id=tenant_id,
            name=request.name,
            description=request.description,
            expires_in_days=request.expires_in_days,
            rate_limit_per_minute=request.rate_limit_per_minute,
            created_by=api_tenant_id if api_tenant_id != "master" else "system",
            metadata=request.metadata,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create API key: {str(e)}")


@router.get("/tenants/{tenant_id}/api-keys", tags=["Tenant Management"])
async def list_api_keys_endpoint(
    tenant_id: str,
    include_inactive: bool = Query(default=False, description="Include inactive/expired keys"),
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """
    List all API keys for a tenant.
    
    Requires API key authentication. Only the tenant owner or master key can list API keys.
    
    Args:
        tenant_id: Tenant ID
        include_inactive: Whether to include inactive/expired keys
    
    Returns:
        List of API key info (without the actual keys)
    """
    from app.services.api_key_service import list_api_keys as list_api_keys_service
    
    # SECURITY: Validate tenant_id format
    try:
        validate_tenant_id(tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    # Verify tenant access
    require_tenant_access(tenant_id, api_tenant_id)
    
    try:
        keys = await list_api_keys_service(tenant_id, include_inactive=include_inactive)
        return {"keys": keys, "count": len(keys)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list API keys: {str(e)}")


@router.delete("/tenants/{tenant_id}/api-keys/{key_id}", tags=["Tenant Management"])
async def revoke_api_key_endpoint(
    tenant_id: str,
    key_id: str,
    permanent: bool = Query(default=False, description="If True, permanently delete the key. If False, just deactivate it."),
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """
    Revoke or delete an API key.
    
    Requires API key authentication. Only the tenant owner or master key can revoke API keys.
    
    Args:
        tenant_id: Tenant ID
        key_id: API key ID to revoke
        permanent: If True, permanently delete the key. If False, just deactivate it.
    
    Returns:
        Success message
    """
    from app.services.api_key_service import revoke_api_key as revoke_api_key_service
    
    # SECURITY: Validate tenant_id format
    try:
        validate_tenant_id(tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    # Verify tenant access
    require_tenant_access(tenant_id, api_tenant_id)
    
    try:
        await revoke_api_key_service(tenant_id=tenant_id, key_id=key_id, permanent=permanent)
        return {
            "status": "revoked" if not permanent else "deleted",
            "message": f"API key {key_id} {'deleted' if permanent else 'revoked'} successfully"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to revoke API key: {str(e)}")
