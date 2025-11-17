"""Channels API router."""

import json
import uuid
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Security, Query
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.infra.database import get_db
from app.infra.auth import verify_api_key, require_tenant_access
from app.infra.validation import validate_tenant_id
from app.api.models import (
    CreateChannelRequest, UpdateChannelRequest,
    ChannelResponse, ChannelListResponse
)

router = APIRouter()


@router.get("/tenants/{tenant_id}/channels", tags=["Tenant Management"], response_model=ChannelListResponse)
async def list_channels(
    tenant_id: str,
    channel_type: Optional[str] = Query(None, description="Filter by channel type"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """
    List all channels for a tenant.
    
    Requires API key authentication. Returns all channels configured for the tenant.
    """
    try:
        validate_tenant_id(tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    require_tenant_access(tenant_id, api_tenant_id)
    
    db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
    db.commit()
    
    query = """
        SELECT id, tenant_id, name, channel_type, external_id, config, is_active, created_at, updated_at
        FROM channels
        WHERE tenant_id = :tenant_id
    """
    params = {"tenant_id": tenant_id}
    
    if channel_type:
        query += " AND channel_type = :channel_type"
        params["channel_type"] = channel_type
    
    if is_active is not None:
        query += " AND is_active = :is_active"
        params["is_active"] = is_active
    
    query += " ORDER BY created_at DESC"
    
    rows = db.execute(text(query), params).fetchall()
    
    items = [
        ChannelResponse(
            id=str(row.id),
            tenant_id=str(row.tenant_id),
            name=row.name,
            channel_type=row.channel_type,
            external_id=row.external_id,
            config=row.config or {},
            is_active=row.is_active,
            created_at=row.created_at.isoformat(),
            updated_at=row.updated_at.isoformat(),
        )
        for row in rows
    ]
    
    return ChannelListResponse(items=items, count=len(items))


@router.get("/tenants/{tenant_id}/channels/{channel_id}", tags=["Tenant Management"], response_model=ChannelResponse)
async def get_channel(
    tenant_id: str,
    channel_id: str,
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """
    Get channel details by ID.
    
    Requires API key authentication. Returns 404 if not found.
    """
    try:
        validate_tenant_id(tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    require_tenant_access(tenant_id, api_tenant_id)
    
    db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
    db.commit()
    
    row = db.execute(
        text("""
            SELECT id, tenant_id, name, channel_type, external_id, config, is_active, created_at, updated_at
            FROM channels
            WHERE id = :channel_id AND tenant_id = :tenant_id
        """),
        {"channel_id": channel_id, "tenant_id": tenant_id}
    ).fetchone()
    
    if not row:
        raise HTTPException(status_code=404, detail="Channel not found")
    
    return ChannelResponse(
        id=str(row.id),
        tenant_id=str(row.tenant_id),
        name=row.name,
        channel_type=row.channel_type,
        external_id=row.external_id,
        config=row.config or {},
        is_active=row.is_active,
        created_at=row.created_at.isoformat(),
        updated_at=row.updated_at.isoformat(),
    )


@router.post("/tenants/{tenant_id}/channels", tags=["Tenant Management"], response_model=ChannelResponse)
async def create_channel(
    tenant_id: str,
    request: CreateChannelRequest,
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """
    Create a new channel for a tenant.
    
    Requires API key authentication. Creates a new channel configuration.
    
    **Example Request:**
    ```json
    {
        "name": "whatsapp-main",
        "channel_type": "whatsapp",
        "external_id": "+1234567890",
        "config": {
            "webhook_url": "https://example.com/webhook"
        },
        "is_active": true
    }
    ```
    """
    try:
        validate_tenant_id(tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    require_tenant_access(tenant_id, api_tenant_id)
    
    db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
    db.commit()
    
    # Check if name already exists for this tenant
    existing = db.execute(
        text("SELECT id FROM channels WHERE tenant_id = :tenant_id AND name = :name"),
        {"tenant_id": tenant_id, "name": request.name}
    ).fetchone()
    
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Channel with name '{request.name}' already exists for this tenant"
        )
    
    # Create channel
    channel_id = uuid.uuid4()
    db.execute(
        text("""
            INSERT INTO channels (
                id, tenant_id, name, channel_type, external_id, config, is_active
            ) VALUES (
                :id, :tenant_id, :name, :channel_type, :external_id, CAST(:config AS jsonb), :is_active
            )
        """),
        {
            "id": channel_id,
            "tenant_id": tenant_id,
            "name": request.name,
            "channel_type": request.channel_type,
            "external_id": request.external_id,
            "config": json.dumps(request.config or {}),
            "is_active": request.is_active,
        }
    )
    db.commit()
    
    # Fetch created channel
    row = db.execute(
        text("""
            SELECT id, tenant_id, name, channel_type, external_id, config, is_active, created_at, updated_at
            FROM channels
            WHERE id = :id
        """),
        {"id": channel_id}
    ).fetchone()
    
    return ChannelResponse(
        id=str(row.id),
        tenant_id=str(row.tenant_id),
        name=row.name,
        channel_type=row.channel_type,
        external_id=row.external_id,
        config=row.config or {},
        is_active=row.is_active,
        created_at=row.created_at.isoformat(),
        updated_at=row.updated_at.isoformat(),
    )


@router.put("/tenants/{tenant_id}/channels/{channel_id}", tags=["Tenant Management"], response_model=ChannelResponse)
async def update_channel(
    tenant_id: str,
    channel_id: str,
    request: UpdateChannelRequest,
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """
    Update channel configuration.
    
    Requires API key authentication. Only provided fields will be updated.
    """
    try:
        validate_tenant_id(tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    require_tenant_access(tenant_id, api_tenant_id)
    
    db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
    db.commit()
    
    # Check if channel exists
    existing = db.execute(
        text("SELECT id FROM channels WHERE id = :channel_id AND tenant_id = :tenant_id"),
        {"channel_id": channel_id, "tenant_id": tenant_id}
    ).fetchone()
    
    if not existing:
        raise HTTPException(status_code=404, detail="Channel not found")
    
    # Check if name conflict (if updating name)
    if request.name:
        name_conflict = db.execute(
            text("""
                SELECT id FROM channels
                WHERE tenant_id = :tenant_id AND name = :name AND id != :channel_id
            """),
            {"tenant_id": tenant_id, "name": request.name, "channel_id": channel_id}
        ).fetchone()
        
        if name_conflict:
            raise HTTPException(
                status_code=409,
                detail=f"Channel with name '{request.name}' already exists for this tenant"
            )
    
    # Build update query
    updates = []
    params = {"channel_id": channel_id, "tenant_id": tenant_id}
    
    if request.name is not None:
        updates.append("name = :name")
        params["name"] = request.name
    
    if request.channel_type is not None:
        updates.append("channel_type = :channel_type")
        params["channel_type"] = request.channel_type
    
    if request.external_id is not None:
        updates.append("external_id = :external_id")
        params["external_id"] = request.external_id
    
    if request.config is not None:
        updates.append("config = CAST(:config AS jsonb)")
        params["config"] = json.dumps(request.config)
    
    if request.is_active is not None:
        updates.append("is_active = :is_active")
        params["is_active"] = request.is_active
    
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    
    updates.append("updated_at = now()")
    
    db.execute(
        text(f"""
            UPDATE channels
            SET {', '.join(updates)}
            WHERE id = :channel_id AND tenant_id = :tenant_id
        """),
        params
    )
    db.commit()
    
    # Fetch updated channel
    row = db.execute(
        text("""
            SELECT id, tenant_id, name, channel_type, external_id, config, is_active, created_at, updated_at
            FROM channels
            WHERE id = :channel_id
        """),
        {"channel_id": channel_id}
    ).fetchone()
    
    return ChannelResponse(
        id=str(row.id),
        tenant_id=str(row.tenant_id),
        name=row.name,
        channel_type=row.channel_type,
        external_id=row.external_id,
        config=row.config or {},
        is_active=row.is_active,
        created_at=row.created_at.isoformat(),
        updated_at=row.updated_at.isoformat(),
    )


@router.delete("/tenants/{tenant_id}/channels/{channel_id}", tags=["Tenant Management"])
async def delete_channel(
    tenant_id: str,
    channel_id: str,
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """
    Delete or deactivate a channel.
    
    Requires API key authentication. Permanently deletes the channel.
    Note: This will set channel_id to NULL in related conversations and messages (due to ON DELETE SET NULL).
    """
    try:
        validate_tenant_id(tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    require_tenant_access(tenant_id, api_tenant_id)
    
    db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
    db.commit()
    
    result = db.execute(
        text("DELETE FROM channels WHERE id = :channel_id AND tenant_id = :tenant_id"),
        {"channel_id": channel_id, "tenant_id": tenant_id}
    )
    db.commit()
    
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Channel not found")
    
    return {
        "status": "deleted",
        "message": "Channel deleted successfully"
    }

