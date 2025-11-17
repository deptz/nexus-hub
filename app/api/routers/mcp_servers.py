"""MCP Servers API router."""

import json
import uuid
from typing import Optional
from urllib.parse import urlparse
from fastapi import APIRouter, HTTPException, Depends, Security, Query
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.infra.database import get_db
from app.infra.auth import verify_api_key, require_tenant_access
from app.infra.validation import validate_tenant_id
from app.api.models import (
    CreateMCPServerRequest,
    UpdateMCPServerRequest,
    MCPServerResponse,
    MCPServerToolResponse,
    CreateMCPServerToolRequest,
)

router = APIRouter()


@router.post("/tenants/{tenant_id}/mcp-servers", tags=["MCP Servers"], response_model=MCPServerResponse)
async def create_mcp_server(
    tenant_id: str,
    request: CreateMCPServerRequest,
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """
    Create a new MCP (Model Context Protocol) server for a tenant.
    
    Requires API key authentication. MCP servers enable integration with external
    services via the Model Context Protocol.
    
    **Endpoint Validation:**
    - Must be http, https, ws, or wss protocol
    - Cannot point to internal/private networks (SSRF protection)
    
    **Example Request:**
    ```json
    {
        "name": "crm_server",
        "endpoint": "https://mcp.example.com/api",
        "auth_config": {
            "type": "api_key",
            "key": "secret_key_here"
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
    
    # Validate endpoint
    endpoint_lower = request.endpoint.lower()
    if not endpoint_lower.startswith(("http://", "https://", "ws://", "wss://")):
        raise HTTPException(
            status_code=400,
            detail="Invalid endpoint protocol. Must be http, https, ws, or wss."
        )
    
    # SSRF protection: block internal/private networks
    try:
        parsed = urlparse(request.endpoint)
        host = parsed.hostname or ""
        
        blocked_hosts = [
            "localhost", "127.0.0.1", "0.0.0.0", "::1",
            "169.254.",  # Link-local
            "10.", "172.16.", "172.17.", "172.18.", "172.19.",
            "172.20.", "172.21.", "172.22.", "172.23.", "172.24.",
            "172.25.", "172.26.", "172.27.", "172.28.", "172.29.",
            "172.30.", "172.31.", "192.168.",  # Private IP ranges
        ]
        
        if any(host.startswith(blocked) or host == blocked for blocked in blocked_hosts):
            raise HTTPException(
                status_code=400,
                detail="Endpoint cannot point to internal/private network. SSRF protection enabled."
            )
    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(status_code=400, detail=f"Invalid endpoint URL: {str(e)}")
    
    # Set tenant context for DB operations
    db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
    db.commit()
    
    # Check if name already exists
    existing = db.execute(
        text("""
            SELECT id FROM mcp_servers
            WHERE tenant_id = :tenant_id AND name = :name
        """),
        {"tenant_id": tenant_id, "name": request.name}
    ).fetchone()
    
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"MCP server with name '{request.name}' already exists for this tenant"
        )
    
    # Create MCP server
    server_id = uuid.uuid4()
    db.execute(
        text("""
            INSERT INTO mcp_servers (
                id, tenant_id, name, endpoint, auth_config, is_active
            ) VALUES (
                :id, :tenant_id, :name, :endpoint, CAST(:auth_config AS jsonb), TRUE
            )
        """),
        {
            "id": server_id,
            "tenant_id": tenant_id,
            "name": request.name,
            "endpoint": request.endpoint,
            "auth_config": json.dumps(request.auth_config),
        }
    )
    db.commit()
    
    # Fetch created server
    row = db.execute(
        text("""
            SELECT id, tenant_id, name, endpoint, auth_config, is_active, created_at, updated_at
            FROM mcp_servers
            WHERE id = :id
        """),
        {"id": server_id}
    ).fetchone()
    
    return MCPServerResponse(
        id=str(row.id),
        tenant_id=str(row.tenant_id),
        name=row.name,
        endpoint=row.endpoint,
        auth_config=row.auth_config,
        is_active=row.is_active,
        created_at=row.created_at.isoformat(),
        updated_at=row.updated_at.isoformat(),
    )


@router.get("/tenants/{tenant_id}/mcp-servers", tags=["MCP Servers"])
async def list_mcp_servers(
    tenant_id: str,
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """
    List all MCP servers for a tenant.
    
    Requires API key authentication. Supports optional filtering by active status.
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
    
    # Build query
    query = """
        SELECT id, tenant_id, name, endpoint, auth_config, is_active, created_at, updated_at
        FROM mcp_servers
        WHERE tenant_id = :tenant_id
    """
    params = {"tenant_id": tenant_id}
    
    if is_active is not None:
        query += " AND is_active = :is_active"
        params["is_active"] = is_active
    
    query += " ORDER BY created_at DESC"
    
    rows = db.execute(text(query), params).fetchall()
    
    return {
        "items": [
            {
                "id": str(row.id),
                "tenant_id": str(row.tenant_id),
                "name": row.name,
                "endpoint": row.endpoint,
                "auth_config": row.auth_config,
                "is_active": row.is_active,
                "created_at": row.created_at.isoformat(),
                "updated_at": row.updated_at.isoformat(),
            }
            for row in rows
        ],
        "count": len(rows),
    }


@router.get("/tenants/{tenant_id}/mcp-servers/{server_id}", tags=["MCP Servers"], response_model=MCPServerResponse)
async def get_mcp_server(
    tenant_id: str,
    server_id: str,
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """
    Get MCP server details by ID.
    
    Requires API key authentication. Returns 404 if not found.
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
    
    row = db.execute(
        text("""
            SELECT id, tenant_id, name, endpoint, auth_config, is_active, created_at, updated_at
            FROM mcp_servers
            WHERE id = :server_id AND tenant_id = :tenant_id
        """),
        {"server_id": server_id, "tenant_id": tenant_id}
    ).fetchone()
    
    if not row:
        raise HTTPException(status_code=404, detail="MCP server not found")
    
    return MCPServerResponse(
        id=str(row.id),
        tenant_id=str(row.tenant_id),
        name=row.name,
        endpoint=row.endpoint,
        auth_config=row.auth_config,
        is_active=row.is_active,
        created_at=row.created_at.isoformat(),
        updated_at=row.updated_at.isoformat(),
    )


@router.put("/tenants/{tenant_id}/mcp-servers/{server_id}", tags=["MCP Servers"], response_model=MCPServerResponse)
async def update_mcp_server(
    tenant_id: str,
    server_id: str,
    request: UpdateMCPServerRequest,
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """
    Update MCP server configuration.
    
    Requires API key authentication. Only provided fields will be updated.
    Endpoint validation (SSRF protection) applies if endpoint is updated.
    """
    # SECURITY: Validate tenant_id format
    try:
        validate_tenant_id(tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    # Verify tenant access
    require_tenant_access(tenant_id, api_tenant_id)
    
    # Validate endpoint if provided
    if request.endpoint:
        endpoint_lower = request.endpoint.lower()
        if not endpoint_lower.startswith(("http://", "https://", "ws://", "wss://")):
            raise HTTPException(
                status_code=400,
                detail="Invalid endpoint protocol. Must be http, https, ws, or wss."
            )
        
        # SSRF protection
        try:
            parsed = urlparse(request.endpoint)
            host = parsed.hostname or ""
            
            blocked_hosts = [
                "localhost", "127.0.0.1", "0.0.0.0", "::1",
                "169.254.", "10.", "172.16.", "172.17.", "172.18.", "172.19.",
                "172.20.", "172.21.", "172.22.", "172.23.", "172.24.",
                "172.25.", "172.26.", "172.27.", "172.28.", "172.29.",
                "172.30.", "172.31.", "192.168.",
            ]
            
            if any(host.startswith(blocked) or host == blocked for blocked in blocked_hosts):
                raise HTTPException(
                    status_code=400,
                    detail="Endpoint cannot point to internal/private network. SSRF protection enabled."
                )
        except Exception as e:
            if isinstance(e, HTTPException):
                raise
            raise HTTPException(status_code=400, detail=f"Invalid endpoint URL: {str(e)}")
    
    # Set tenant context for DB operations
    db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
    db.commit()
    
    # Check if server exists
    existing = db.execute(
        text("""
            SELECT id FROM mcp_servers
            WHERE id = :server_id AND tenant_id = :tenant_id
        """),
        {"server_id": server_id, "tenant_id": tenant_id}
    ).fetchone()
    
    if not existing:
        raise HTTPException(status_code=404, detail="MCP server not found")
    
    # Build update query
    updates = []
    params = {"server_id": server_id, "tenant_id": tenant_id}
    
    if request.endpoint is not None:
        updates.append("endpoint = :endpoint")
        params["endpoint"] = request.endpoint
    
    if request.auth_config is not None:
        updates.append("auth_config = CAST(:auth_config AS jsonb)")
        params["auth_config"] = json.dumps(request.auth_config)
    
    if request.is_active is not None:
        updates.append("is_active = :is_active")
        params["is_active"] = request.is_active
    
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    
    updates.append("updated_at = now()")
    
    db.execute(
        text(f"""
            UPDATE mcp_servers
            SET {', '.join(updates)}
            WHERE id = :server_id AND tenant_id = :tenant_id
        """),
        params
    )
    db.commit()
    
    # Fetch updated server
    row = db.execute(
        text("""
            SELECT id, tenant_id, name, endpoint, auth_config, is_active, created_at, updated_at
            FROM mcp_servers
            WHERE id = :server_id
        """),
        {"server_id": server_id}
    ).fetchone()
    
    return MCPServerResponse(
        id=str(row.id),
        tenant_id=str(row.tenant_id),
        name=row.name,
        endpoint=row.endpoint,
        auth_config=row.auth_config,
        is_active=row.is_active,
        created_at=row.created_at.isoformat(),
        updated_at=row.updated_at.isoformat(),
    )


@router.delete("/tenants/{tenant_id}/mcp-servers/{server_id}", tags=["MCP Servers"])
async def delete_mcp_server(
    tenant_id: str,
    server_id: str,
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """
    Delete an MCP server.
    
    Requires API key authentication. Permanently deletes the MCP server and all associated tools.
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
    
    result = db.execute(
        text("""
            DELETE FROM mcp_servers
            WHERE id = :server_id AND tenant_id = :tenant_id
        """),
        {"server_id": server_id, "tenant_id": tenant_id}
    )
    db.commit()
    
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="MCP server not found")
    
    return {
        "status": "deleted",
        "message": "MCP server deleted successfully"
    }


@router.get("/tenants/{tenant_id}/mcp-servers/{server_id}/tools", tags=["MCP Servers"])
async def list_mcp_server_tools(
    tenant_id: str,
    server_id: str,
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """
    List all tools for an MCP server.
    
    Requires API key authentication. Returns tools registered for the specified MCP server.
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
    
    # Verify server exists and belongs to tenant
    server = db.execute(
        text("""
            SELECT id FROM mcp_servers
            WHERE id = :server_id AND tenant_id = :tenant_id
        """),
        {"server_id": server_id, "tenant_id": tenant_id}
    ).fetchone()
    
    if not server:
        raise HTTPException(status_code=404, detail="MCP server not found")
    
    # Get tools
    rows = db.execute(
        text("""
            SELECT id, mcp_server_id, tool_name, description, schema, created_at, updated_at
            FROM mcp_server_tools
            WHERE mcp_server_id = :server_id
            ORDER BY tool_name
        """),
        {"server_id": server_id}
    ).fetchall()
    
    return {
        "items": [
            {
                "id": str(row.id),
                "mcp_server_id": str(row.mcp_server_id),
                "tool_name": row.tool_name,
                "description": row.description,
                "schema": row.schema,
                "created_at": row.created_at.isoformat(),
                "updated_at": row.updated_at.isoformat(),
            }
            for row in rows
        ],
        "count": len(rows),
    }


@router.post("/tenants/{tenant_id}/mcp-servers/{server_id}/tools", tags=["MCP Servers"], response_model=MCPServerToolResponse)
async def create_mcp_server_tool(
    tenant_id: str,
    server_id: str,
    request: CreateMCPServerToolRequest,
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """
    Create or update a tool for an MCP server.
    
    Requires API key authentication. If a tool with the same name exists, it will be updated.
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
    
    # Verify server exists and belongs to tenant
    server = db.execute(
        text("""
            SELECT id FROM mcp_servers
            WHERE id = :server_id AND tenant_id = :tenant_id
        """),
        {"server_id": server_id, "tenant_id": tenant_id}
    ).fetchone()
    
    if not server:
        raise HTTPException(status_code=404, detail="MCP server not found")
    
    # Check if tool exists
    existing = db.execute(
        text("""
            SELECT id FROM mcp_server_tools
            WHERE mcp_server_id = :server_id AND tool_name = :tool_name
        """),
        {"server_id": server_id, "tool_name": request.tool_name}
    ).fetchone()
    
    if existing:
        # Update existing tool
        db.execute(
            text("""
                UPDATE mcp_server_tools
                SET description = :description,
                    schema = CAST(:schema AS jsonb),
                    updated_at = now()
                WHERE id = :id
            """),
            {
                "id": existing.id,
                "description": request.description,
                "schema": json.dumps(request.schema),
            }
        )
        tool_id = existing.id
    else:
        # Create new tool
        tool_id = uuid.uuid4()
        db.execute(
            text("""
                INSERT INTO mcp_server_tools (
                    id, mcp_server_id, tool_name, description, schema
                ) VALUES (
                    :id, :server_id, :tool_name, :description, CAST(:schema AS jsonb)
                )
            """),
            {
                "id": tool_id,
                "server_id": server_id,
                "tool_name": request.tool_name,
                "description": request.description,
                "schema": json.dumps(request.schema),
            }
        )
    
    db.commit()
    
    # Fetch tool
    row = db.execute(
        text("""
            SELECT id, mcp_server_id, tool_name, description, schema, created_at, updated_at
            FROM mcp_server_tools
            WHERE id = :id
        """),
        {"id": tool_id}
    ).fetchone()
    
    return MCPServerToolResponse(
        id=str(row.id),
        mcp_server_id=str(row.mcp_server_id),
        tool_name=row.tool_name,
        description=row.description,
        schema=row.schema,
        created_at=row.created_at.isoformat(),
        updated_at=row.updated_at.isoformat(),
    )


@router.delete("/tenants/{tenant_id}/mcp-servers/{server_id}/tools/{tool_name}", tags=["MCP Servers"])
async def delete_mcp_server_tool(
    tenant_id: str,
    server_id: str,
    tool_name: str,
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """
    Delete a tool from an MCP server.
    
    Requires API key authentication. Permanently removes the tool registration.
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
    
    # Verify server exists and belongs to tenant
    server = db.execute(
        text("""
            SELECT id FROM mcp_servers
            WHERE id = :server_id AND tenant_id = :tenant_id
        """),
        {"server_id": server_id, "tenant_id": tenant_id}
    ).fetchone()
    
    if not server:
        raise HTTPException(status_code=404, detail="MCP server not found")
    
    # Delete tool
    result = db.execute(
        text("""
            DELETE FROM mcp_server_tools
            WHERE mcp_server_id = :server_id AND tool_name = :tool_name
        """),
        {"server_id": server_id, "tool_name": tool_name}
    )
    db.commit()
    
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="MCP server tool not found")
    
    return {
        "status": "deleted",
        "message": f"MCP server tool '{tool_name}' deleted successfully"
    }
