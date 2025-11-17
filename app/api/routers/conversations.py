"""Conversations API router."""

from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Security, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime

from app.infra.database import get_db
from app.infra.auth import verify_api_key, require_tenant_access
from app.infra.validation import validate_tenant_id
from app.api.models import (
    ConversationResponse, ConversationListResponse,
    UpdateConversationRequest, ConversationStatsResponse,
    MessageResponse, MessageListResponse
)
from app.services.conversation_stats import update_conversation_stats

router = APIRouter()


@router.get("/tenants/{tenant_id}/conversations", tags=["Conversations"], response_model=ConversationListResponse)
async def list_conversations(
    tenant_id: str,
    status: Optional[str] = Query(None, description="Filter by status: 'open', 'closed', 'archived'"),
    channel_id: Optional[str] = Query(None, description="Filter by channel ID"),
    start_date: Optional[str] = Query(None, description="Start date (ISO8601 timestamp)"),
    end_date: Optional[str] = Query(None, description="End date (ISO8601 timestamp)"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    sort_by: str = Query("created_at", description="Sort field: 'created_at', 'updated_at'"),
    sort_order: str = Query("desc", description="Sort order: 'asc' or 'desc'"),
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """List all conversations for a tenant."""
    try:
        validate_tenant_id(tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    require_tenant_access(tenant_id, api_tenant_id)
    
    db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
    db.commit()
    
    valid_sort_fields = ["created_at", "updated_at"]
    if sort_by not in valid_sort_fields:
        raise HTTPException(status_code=400, detail=f"Invalid sort_by. Must be one of: {valid_sort_fields}")
    
    if sort_order not in ["asc", "desc"]:
        raise HTTPException(status_code=400, detail="Invalid sort_order. Must be 'asc' or 'desc'")
    
    query = """
        SELECT id, tenant_id, channel_id, external_thread_id, subject, status, created_at, updated_at
        FROM conversations
        WHERE tenant_id = :tenant_id
    """
    params = {"tenant_id": tenant_id}
    
    if status:
        valid_statuses = ["open", "closed", "archived"]
        if status not in valid_statuses:
            raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {valid_statuses}")
        query += " AND status = :status"
        params["status"] = status
    
    if channel_id:
        query += " AND channel_id = :channel_id"
        params["channel_id"] = channel_id
    
    if start_date:
        query += " AND created_at >= :start_date"
        params["start_date"] = start_date
    
    if end_date:
        query += " AND created_at <= :end_date"
        params["end_date"] = end_date
    
    query += f" ORDER BY {sort_by} {sort_order.upper()}"
    query += " LIMIT :limit OFFSET :offset"
    params["limit"] = limit + 1
    params["offset"] = offset
    
    rows = db.execute(text(query), params).fetchall()
    
    has_more = len(rows) > limit
    if has_more:
        rows = rows[:limit]
    
    items = [
        ConversationResponse(
            id=str(row.id),
            tenant_id=str(row.tenant_id),
            channel_id=str(row.channel_id) if row.channel_id else None,
            external_thread_id=row.external_thread_id,
            subject=row.subject,
            status=row.status,
            created_at=row.created_at.isoformat(),
            updated_at=row.updated_at.isoformat(),
        )
        for row in rows
    ]
    
    return ConversationListResponse(
        items=items,
        count=len(items),
        has_more=has_more,
        next_offset=offset + limit if has_more else None,
    )


@router.get("/tenants/{tenant_id}/conversations/{conversation_id}", tags=["Conversations"], response_model=ConversationResponse)
async def get_conversation(
    tenant_id: str,
    conversation_id: str,
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """Get conversation details by ID."""
    try:
        validate_tenant_id(tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    require_tenant_access(tenant_id, api_tenant_id)
    
    db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
    db.commit()
    
    row = db.execute(
        text("""
            SELECT id, tenant_id, channel_id, external_thread_id, subject, status, created_at, updated_at
            FROM conversations
            WHERE id = :conversation_id AND tenant_id = :tenant_id
        """),
        {"conversation_id": conversation_id, "tenant_id": tenant_id}
    ).fetchone()
    
    if not row:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    return ConversationResponse(
        id=str(row.id),
        tenant_id=str(row.tenant_id),
        channel_id=str(row.channel_id) if row.channel_id else None,
        external_thread_id=row.external_thread_id,
        subject=row.subject,
        status=row.status,
        created_at=row.created_at.isoformat(),
        updated_at=row.updated_at.isoformat(),
    )


@router.put("/tenants/{tenant_id}/conversations/{conversation_id}", tags=["Conversations"], response_model=ConversationResponse)
async def update_conversation(
    tenant_id: str,
    conversation_id: str,
    request: UpdateConversationRequest,
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """Update conversation (subject, status)."""
    try:
        validate_tenant_id(tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    require_tenant_access(tenant_id, api_tenant_id)
    
    db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
    db.commit()
    
    existing = db.execute(
        text("SELECT id FROM conversations WHERE id = :conversation_id AND tenant_id = :tenant_id"),
        {"conversation_id": conversation_id, "tenant_id": tenant_id}
    ).fetchone()
    
    if not existing:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    if request.status:
        valid_statuses = ["open", "closed", "archived"]
        if request.status not in valid_statuses:
            raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {valid_statuses}")
    
    updates = []
    params = {"conversation_id": conversation_id, "tenant_id": tenant_id}
    
    if request.subject is not None:
        updates.append("subject = :subject")
        params["subject"] = request.subject
    
    if request.status is not None:
        updates.append("status = :status")
        params["status"] = request.status
    
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update. Provide subject or status.")
    
    updates.append("updated_at = now()")
    
    db.execute(
        text(f"UPDATE conversations SET {', '.join(updates)} WHERE id = :conversation_id AND tenant_id = :tenant_id"),
        params
    )
    db.commit()
    
    row = db.execute(
        text("""
            SELECT id, tenant_id, channel_id, external_thread_id, subject, status, created_at, updated_at
            FROM conversations
            WHERE id = :conversation_id AND tenant_id = :tenant_id
        """),
        {"conversation_id": conversation_id, "tenant_id": tenant_id}
    ).fetchone()
    
    return ConversationResponse(
        id=str(row.id),
        tenant_id=str(row.tenant_id),
        channel_id=str(row.channel_id) if row.channel_id else None,
        external_thread_id=row.external_thread_id,
        subject=row.subject,
        status=row.status,
        created_at=row.created_at.isoformat(),
        updated_at=row.updated_at.isoformat(),
    )


@router.delete("/tenants/{tenant_id}/conversations/{conversation_id}", tags=["Conversations"])
async def delete_conversation(
    tenant_id: str,
    conversation_id: str,
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """Delete/archive a conversation."""
    try:
        validate_tenant_id(tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    require_tenant_access(tenant_id, api_tenant_id)
    
    db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
    db.commit()
    
    result = db.execute(
        text("DELETE FROM conversations WHERE id = :conversation_id AND tenant_id = :tenant_id"),
        {"conversation_id": conversation_id, "tenant_id": tenant_id}
    )
    db.commit()
    
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    return {"status": "deleted", "message": f"Conversation '{conversation_id}' deleted successfully"}


@router.get("/tenants/{tenant_id}/conversations/{conversation_id}/stats", tags=["Conversations"], response_model=ConversationStatsResponse)
async def get_conversation_stats(
    tenant_id: str,
    conversation_id: str,
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """Get conversation statistics."""
    try:
        validate_tenant_id(tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    require_tenant_access(tenant_id, api_tenant_id)
    
    db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
    db.commit()
    
    conv = db.execute(
        text("SELECT id FROM conversations WHERE id = :conversation_id AND tenant_id = :tenant_id"),
        {"conversation_id": conversation_id, "tenant_id": tenant_id}
    ).fetchone()
    
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    row = db.execute(
        text("""
            SELECT conversation_id, tenant_id, resolved, resolution_time_ms,
                   total_messages, tool_calls, risk_flags, last_event_at, updated_at
            FROM conversation_stats
            WHERE conversation_id = :conversation_id AND tenant_id = :tenant_id
        """),
        {"conversation_id": conversation_id, "tenant_id": tenant_id}
    ).fetchone()
    
    if not row:
        return ConversationStatsResponse(
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            resolved=False,
            resolution_time_ms=None,
            total_messages=0,
            tool_calls=0,
            risk_flags=0,
            last_event_at=None,
            updated_at=datetime.now().isoformat(),
        )
    
    return ConversationStatsResponse(
        conversation_id=str(row.conversation_id),
        tenant_id=str(row.tenant_id),
        resolved=row.resolved,
        resolution_time_ms=row.resolution_time_ms,
        total_messages=row.total_messages,
        tool_calls=row.tool_calls,
        risk_flags=row.risk_flags,
        last_event_at=row.last_event_at.isoformat() if row.last_event_at else None,
        updated_at=row.updated_at.isoformat(),
    )


@router.put("/tenants/{tenant_id}/conversations/{conversation_id}/resolve", tags=["Conversations"])
async def resolve_conversation(
    tenant_id: str,
    conversation_id: str,
    resolved: bool = Query(True, description="Set resolved status"),
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """Mark conversation as resolved or unresolved."""
    try:
        validate_tenant_id(tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    require_tenant_access(tenant_id, api_tenant_id)
    
    db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
    db.commit()
    
    conv = db.execute(
        text("SELECT id FROM conversations WHERE id = :conversation_id AND tenant_id = :tenant_id"),
        {"conversation_id": conversation_id, "tenant_id": tenant_id}
    ).fetchone()
    
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    await update_conversation_stats(tenant_id, conversation_id, resolved=resolved)
    
    return {
        "status": "updated",
        "message": f"Conversation '{conversation_id}' marked as {'resolved' if resolved else 'unresolved'}",
        "resolved": resolved,
    }


@router.get("/tenants/{tenant_id}/conversations/{conversation_id}/messages", tags=["Messages"], response_model=MessageListResponse)
async def list_conversation_messages(
    tenant_id: str,
    conversation_id: str,
    direction: Optional[str] = Query(None, description="Filter by direction: 'inbound' or 'outbound'"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    sort_order: str = Query("asc", description="Sort order: 'asc' (chronological) or 'desc'"),
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """List all messages in a conversation."""
    try:
        validate_tenant_id(tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    require_tenant_access(tenant_id, api_tenant_id)
    
    db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
    db.commit()
    
    conv = db.execute(
        text("SELECT id FROM conversations WHERE id = :conversation_id AND tenant_id = :tenant_id"),
        {"conversation_id": conversation_id, "tenant_id": tenant_id}
    ).fetchone()
    
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    if sort_order not in ["asc", "desc"]:
        raise HTTPException(status_code=400, detail="Invalid sort_order. Must be 'asc' or 'desc'")
    
    query = """
        SELECT id, tenant_id, conversation_id, channel_id, direction, source_message_id,
               from_type, from_external_id, from_display_name, content_type, content_text, metadata, created_at
        FROM messages
        WHERE tenant_id = :tenant_id AND conversation_id = :conversation_id
    """
    params = {"tenant_id": tenant_id, "conversation_id": conversation_id}
    
    if direction:
        if direction not in ["inbound", "outbound"]:
            raise HTTPException(status_code=400, detail="Invalid direction. Must be 'inbound' or 'outbound'")
        query += " AND direction = :direction"
        params["direction"] = direction
    
    query += f" ORDER BY created_at {sort_order.upper()}"
    query += " LIMIT :limit OFFSET :offset"
    params["limit"] = limit + 1
    params["offset"] = offset
    
    rows = db.execute(text(query), params).fetchall()
    
    has_more = len(rows) > limit
    if has_more:
        rows = rows[:limit]
    
    items = [
        MessageResponse(
            id=str(row.id),
            tenant_id=str(row.tenant_id),
            conversation_id=str(row.conversation_id),
            channel_id=str(row.channel_id) if row.channel_id else None,
            direction=row.direction,
            source_message_id=row.source_message_id,
            from_type=row.from_type,
            from_external_id=row.from_external_id,
            from_display_name=row.from_display_name,
            content_type=row.content_type,
            content_text=row.content_text,
            metadata=row.metadata or {},
            created_at=row.created_at.isoformat(),
        )
        for row in rows
    ]
    
    return MessageListResponse(
        items=items,
        count=len(items),
        has_more=has_more,
        next_offset=offset + limit if has_more else None,
    )

