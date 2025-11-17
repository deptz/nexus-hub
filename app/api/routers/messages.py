"""Messages API router."""

from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Security, Query
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.infra.database import get_db
from app.infra.auth import verify_api_key, require_tenant_access
from app.infra.validation import validate_message, validate_tenant_id
from app.models.message import CanonicalMessage
from app.api.models import InboundMessageResponse, MessageResponse, MessageListResponse
from app.api.utils import handle_inbound_message_sync
from app.infra.queue import enqueue_message_processing, get_job_status

router = APIRouter()


@router.post("/messages/inbound", tags=["Messages"], response_model=InboundMessageResponse)
async def handle_inbound_message(
    message: CanonicalMessage,
    db: Session = Depends(get_db),
    async_processing: bool = Query(False, description="If True, queue for async processing"),
    api_tenant_id: str = Security(verify_api_key),
):
    """
    Handle inbound canonical message.
    
    Requires API key authentication via X-API-Key header or api_key query parameter.
    
    Processes an inbound message through the orchestrator pipeline:
    1. Resolves tenant context
    2. Gets/creates conversation
    3. Persists inbound message
    4. Builds prompts with conversation history
    5. Calls LLM with tools
    6. Executes tool calls if needed
    7. Generates and persists outbound message
    8. Returns response with latency and tool call count
    
    **Example Request:**
    ```json
    {
        "tenant_id": "uuid",
        "channel": "web",
        "direction": "inbound",
        "from": {"type": "user", "external_id": "user-123"},
        "to": {"type": "bot", "external_id": ""},
        "content": {"type": "text", "text": "Hello"}
    }
    ```
    
    **Query Parameters:**
    - `async_processing`: If True, queues message for background processing and returns job ID
    """
    # Verify tenant access
    require_tenant_access(message.tenant_id, api_tenant_id)
    
    # Validate message
    try:
        validate_message(message)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    # Check if async processing is requested
    if async_processing:
        job_id = enqueue_message_processing(message.dict(), priority="default")
        return {
            "status": "queued",
            "job_id": job_id,
            "message": "Message queued for processing",
        }
    
    # Synchronous processing
    result = await handle_inbound_message_sync(message, db)
    return InboundMessageResponse(**result)


@router.get("/messages/status/{job_id}", tags=["Messages"])
async def get_message_status(job_id: str):
    """
    Get status of a queued message processing job.
    
    Returns the current status of an asynchronously processed message.
    Status can be: 'queued', 'processing', 'completed', or 'failed'.
    
    **Returns:**
    - If completed: Full response with outbound message
    - If failed: Error details
    - If queued/processing: Current status
    """
    return get_job_status(job_id)


@router.get("/tenants/{tenant_id}/messages", tags=["Messages"], response_model=MessageListResponse)
async def list_messages(
    tenant_id: str,
    conversation_id: Optional[str] = Query(None, description="Filter by conversation ID"),
    direction: Optional[str] = Query(None, description="Filter by direction: 'inbound' or 'outbound'"),
    content_type: Optional[str] = Query(None, description="Filter by content type"),
    start_date: Optional[str] = Query(None, description="Start date (ISO8601 timestamp)"),
    end_date: Optional[str] = Query(None, description="End date (ISO8601 timestamp)"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    sort_by: str = Query("created_at", description="Sort field: 'created_at'"),
    sort_order: str = Query("desc", description="Sort order: 'asc' or 'desc'"),
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """List all messages for a tenant."""
    from typing import Optional
    
    try:
        validate_tenant_id(tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    require_tenant_access(tenant_id, api_tenant_id)
    
    db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
    db.commit()
    
    if sort_by not in ["created_at"]:
        raise HTTPException(status_code=400, detail="Invalid sort_by. Must be 'created_at'")
    
    if sort_order not in ["asc", "desc"]:
        raise HTTPException(status_code=400, detail="Invalid sort_order. Must be 'asc' or 'desc'")
    
    query = """
        SELECT id, tenant_id, conversation_id, channel_id, direction, source_message_id,
               from_type, from_external_id, from_display_name, content_type, content_text, metadata, created_at
        FROM messages
        WHERE tenant_id = :tenant_id
    """
    params = {"tenant_id": tenant_id}
    
    if conversation_id:
        query += " AND conversation_id = :conversation_id"
        params["conversation_id"] = conversation_id
    
    if direction:
        if direction not in ["inbound", "outbound"]:
            raise HTTPException(status_code=400, detail="Invalid direction. Must be 'inbound' or 'outbound'")
        query += " AND direction = :direction"
        params["direction"] = direction
    
    if content_type:
        query += " AND content_type = :content_type"
        params["content_type"] = content_type
    
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


@router.get("/tenants/{tenant_id}/messages/{message_id}", tags=["Messages"], response_model=MessageResponse)
async def get_message(
    tenant_id: str,
    message_id: str,
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """Get message details by ID."""
    try:
        validate_tenant_id(tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    require_tenant_access(tenant_id, api_tenant_id)
    
    db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
    db.commit()
    
    row = db.execute(
        text("""
            SELECT id, tenant_id, conversation_id, channel_id, direction, source_message_id,
                   from_type, from_external_id, from_display_name, content_type, content_text, metadata, created_at
            FROM messages
            WHERE id = :message_id AND tenant_id = :tenant_id
        """),
        {"message_id": message_id, "tenant_id": tenant_id}
    ).fetchone()
    
    if not row:
        raise HTTPException(status_code=404, detail="Message not found")
    
    return MessageResponse(
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

