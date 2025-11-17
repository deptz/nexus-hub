"""Logs API router."""

from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Security, Query
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.infra.database import get_db
from app.infra.auth import verify_api_key, require_tenant_access
from app.infra.validation import validate_tenant_id
from app.api.models import LogQueryResponse, LLMTraceResponse, LLMTraceListResponse

router = APIRouter()


@router.get("/tenants/{tenant_id}/logs/events", tags=["Logs"], response_model=LogQueryResponse)
async def get_event_logs(
    tenant_id: str,
    conversation_id: Optional[str] = Query(None, description="Filter by conversation ID"),
    event_type: Optional[str] = Query(None, description="Filter by event type"),
    provider: Optional[str] = Query(None, description="Filter by provider"),
    start_date: Optional[str] = Query(None, description="Start date (ISO8601 timestamp)"),
    end_date: Optional[str] = Query(None, description="End date (ISO8601 timestamp)"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """Get event logs for a tenant."""
    try:
        validate_tenant_id(tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    require_tenant_access(tenant_id, api_tenant_id)
    
    db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
    db.commit()
    
    query = """
        SELECT id, tenant_id, event_type, provider, status, conversation_id, message_id,
               latency_ms, cost, payload, created_at
        FROM event_logs
        WHERE tenant_id = :tenant_id
    """
    params = {"tenant_id": tenant_id}
    
    if conversation_id:
        query += " AND conversation_id = :conversation_id"
        params["conversation_id"] = conversation_id
    
    if event_type:
        query += " AND event_type = :event_type"
        params["event_type"] = event_type
    
    if provider:
        query += " AND provider = :provider"
        params["provider"] = provider
    
    if start_date:
        query += " AND created_at >= :start_date"
        params["start_date"] = start_date
    
    if end_date:
        query += " AND created_at <= :end_date"
        params["end_date"] = end_date
    
    query += " ORDER BY created_at DESC"
    query += " LIMIT :limit OFFSET :offset"
    params["limit"] = limit + 1
    params["offset"] = offset
    
    rows = db.execute(text(query), params).fetchall()
    
    has_more = len(rows) > limit
    if has_more:
        rows = rows[:limit]
    
    items = [
        {
            "id": str(row.id),
            "tenant_id": str(row.tenant_id),
            "event_type": row.event_type,
            "provider": row.provider,
            "status": row.status,
            "conversation_id": str(row.conversation_id) if row.conversation_id else None,
            "message_id": str(row.message_id) if row.message_id else None,
            "latency_ms": row.latency_ms,
            "cost": float(row.cost) if row.cost else None,
            "payload": row.payload or {},
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]
    
    return LogQueryResponse(
        items=items,
        total=len(items),
        limit=limit,
        offset=offset,
        has_more=has_more
    )


@router.get("/tenants/{tenant_id}/logs/tool-calls", tags=["Logs"], response_model=LogQueryResponse)
async def get_tool_call_logs(
    tenant_id: str,
    conversation_id: Optional[str] = Query(None, description="Filter by conversation ID"),
    tool_name: Optional[str] = Query(None, description="Filter by tool name"),
    status: Optional[str] = Query(None, description="Filter by status: 'success' or 'failure'"),
    start_date: Optional[str] = Query(None, description="Start date (ISO8601 timestamp)"),
    end_date: Optional[str] = Query(None, description="End date (ISO8601 timestamp)"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """Get tool call logs for a tenant."""
    try:
        validate_tenant_id(tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    require_tenant_access(tenant_id, api_tenant_id)
    
    db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
    db.commit()
    
    query = """
        SELECT id, tenant_id, tool_name, provider, conversation_id, message_id,
               arguments, result_summary, status, error_message, latency_ms, cost, created_at
        FROM tool_call_logs
        WHERE tenant_id = :tenant_id
    """
    params = {"tenant_id": tenant_id}
    
    if conversation_id:
        query += " AND conversation_id = :conversation_id"
        params["conversation_id"] = conversation_id
    
    if tool_name:
        query += " AND tool_name = :tool_name"
        params["tool_name"] = tool_name
    
    if status:
        query += " AND status = :status"
        params["status"] = status
    
    if start_date:
        query += " AND created_at >= :start_date"
        params["start_date"] = start_date
    
    if end_date:
        query += " AND created_at <= :end_date"
        params["end_date"] = end_date
    
    query += " ORDER BY created_at DESC"
    query += " LIMIT :limit OFFSET :offset"
    params["limit"] = limit + 1
    params["offset"] = offset
    
    rows = db.execute(text(query), params).fetchall()
    
    has_more = len(rows) > limit
    if has_more:
        rows = rows[:limit]
    
    items = [
        {
            "id": str(row.id),
            "tenant_id": str(row.tenant_id),
            "tool_name": row.tool_name,
            "provider": row.provider,
            "conversation_id": str(row.conversation_id) if row.conversation_id else None,
            "message_id": str(row.message_id) if row.message_id else None,
            "arguments": row.arguments or {},
            "result_summary": row.result_summary or {},
            "status": row.status,
            "error_message": row.error_message,
            "latency_ms": row.latency_ms,
            "cost": float(row.cost) if row.cost else None,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]
    
    return LogQueryResponse(
        items=items,
        total=len(items),
        limit=limit,
        offset=offset,
        has_more=has_more
    )


# ============================================================================
# LLM Traces Endpoints
# ============================================================================

@router.get("/tenants/{tenant_id}/traces/llm", tags=["Logs"], response_model=LLMTraceListResponse)
async def list_llm_traces(
    tenant_id: str,
    conversation_id: Optional[str] = Query(None, description="Filter by conversation ID"),
    message_id: Optional[str] = Query(None, description="Filter by message ID"),
    provider: Optional[str] = Query(None, description="Filter by provider: 'openai' or 'gemini'"),
    model: Optional[str] = Query(None, description="Filter by model name"),
    start_date: Optional[str] = Query(None, description="Start date (ISO8601 timestamp)"),
    end_date: Optional[str] = Query(None, description="End date (ISO8601 timestamp)"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """
    List LLM traces for a tenant.
    
    Requires API key authentication. Returns full request/response payloads for LLM API calls.
    Useful for debugging, prompt engineering, and audit trails.
    
    **Security Note**: These traces may contain sensitive data. Access should be restricted.
    """
    try:
        validate_tenant_id(tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    require_tenant_access(tenant_id, api_tenant_id)
    
    db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
    db.commit()
    
    query = """
        SELECT id, tenant_id, conversation_id, message_id, provider, model,
               request_payload, response_payload, created_at
        FROM llm_traces
        WHERE tenant_id = :tenant_id
    """
    params = {"tenant_id": tenant_id}
    
    if conversation_id:
        query += " AND conversation_id = :conversation_id"
        params["conversation_id"] = conversation_id
    
    if message_id:
        query += " AND message_id = :message_id"
        params["message_id"] = message_id
    
    if provider:
        valid_providers = ["openai", "gemini"]
        if provider not in valid_providers:
            raise HTTPException(status_code=400, detail=f"Invalid provider. Must be one of: {valid_providers}")
        query += " AND provider = :provider"
        params["provider"] = provider
    
    if model:
        query += " AND model = :model"
        params["model"] = model
    
    if start_date:
        query += " AND created_at >= :start_date"
        params["start_date"] = start_date
    
    if end_date:
        query += " AND created_at <= :end_date"
        params["end_date"] = end_date
    
    query += " ORDER BY created_at DESC"
    query += " LIMIT :limit OFFSET :offset"
    params["limit"] = limit + 1
    params["offset"] = offset
    
    rows = db.execute(text(query), params).fetchall()
    
    has_more = len(rows) > limit
    if has_more:
        rows = rows[:limit]
    
    items = [
        LLMTraceResponse(
            id=str(row.id),
            tenant_id=str(row.tenant_id),
            conversation_id=str(row.conversation_id) if row.conversation_id else None,
            message_id=str(row.message_id) if row.message_id else None,
            provider=row.provider,
            model=row.model,
            request_payload=row.request_payload or {},
            response_payload=row.response_payload or {},
            created_at=row.created_at.isoformat(),
        )
        for row in rows
    ]
    
    return LLMTraceListResponse(
        items=items,
        count=len(items),
        has_more=has_more,
        next_offset=offset + limit if has_more else None,
    )


@router.get("/tenants/{tenant_id}/traces/llm/{trace_id}", tags=["Logs"], response_model=LLMTraceResponse)
async def get_llm_trace(
    tenant_id: str,
    trace_id: str,
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """
    Get LLM trace details by ID.
    
    Requires API key authentication. Returns full request/response payload for a specific LLM trace.
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
            SELECT id, tenant_id, conversation_id, message_id, provider, model,
                   request_payload, response_payload, created_at
            FROM llm_traces
            WHERE id = :trace_id AND tenant_id = :tenant_id
        """),
        {"trace_id": trace_id, "tenant_id": tenant_id}
    ).fetchone()
    
    if not row:
        raise HTTPException(status_code=404, detail="LLM trace not found")
    
    return LLMTraceResponse(
        id=str(row.id),
        tenant_id=str(row.tenant_id),
        conversation_id=str(row.conversation_id) if row.conversation_id else None,
        message_id=str(row.message_id) if row.message_id else None,
        provider=row.provider,
        model=row.model,
        request_payload=row.request_payload or {},
        response_payload=row.response_payload or {},
        created_at=row.created_at.isoformat(),
    )


@router.get("/tenants/{tenant_id}/conversations/{conversation_id}/traces", tags=["Logs"], response_model=LLMTraceListResponse)
async def get_conversation_traces(
    tenant_id: str,
    conversation_id: str,
    provider: Optional[str] = Query(None, description="Filter by provider: 'openai' or 'gemini'"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """
    Get all LLM traces for a conversation.
    
    Requires API key authentication. Returns all LLM traces associated with a specific conversation.
    Useful for debugging conversation flows and understanding LLM interactions.
    """
    try:
        validate_tenant_id(tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    require_tenant_access(tenant_id, api_tenant_id)
    
    db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
    db.commit()
    
    # Verify conversation exists
    conv = db.execute(
        text("SELECT id FROM conversations WHERE id = :conversation_id AND tenant_id = :tenant_id"),
        {"conversation_id": conversation_id, "tenant_id": tenant_id}
    ).fetchone()
    
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    query = """
        SELECT id, tenant_id, conversation_id, message_id, provider, model,
               request_payload, response_payload, created_at
        FROM llm_traces
        WHERE tenant_id = :tenant_id AND conversation_id = :conversation_id
    """
    params = {"tenant_id": tenant_id, "conversation_id": conversation_id}
    
    if provider:
        valid_providers = ["openai", "gemini"]
        if provider not in valid_providers:
            raise HTTPException(status_code=400, detail=f"Invalid provider. Must be one of: {valid_providers}")
        query += " AND provider = :provider"
        params["provider"] = provider
    
    query += " ORDER BY created_at DESC"
    query += " LIMIT :limit OFFSET :offset"
    params["limit"] = limit + 1
    params["offset"] = offset
    
    rows = db.execute(text(query), params).fetchall()
    
    has_more = len(rows) > limit
    if has_more:
        rows = rows[:limit]
    
    items = [
        LLMTraceResponse(
            id=str(row.id),
            tenant_id=str(row.tenant_id),
            conversation_id=str(row.conversation_id) if row.conversation_id else None,
            message_id=str(row.message_id) if row.message_id else None,
            provider=row.provider,
            model=row.model,
            request_payload=row.request_payload or {},
            response_payload=row.response_payload or {},
            created_at=row.created_at.isoformat(),
        )
        for row in rows
    ]
    
    return LLMTraceListResponse(
        items=items,
        count=len(items),
        has_more=has_more,
        next_offset=offset + limit if has_more else None,
    )


@router.get("/tenants/{tenant_id}/messages/{message_id}/trace", tags=["Logs"], response_model=LLMTraceResponse)
async def get_message_trace(
    tenant_id: str,
    message_id: str,
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """
    Get LLM trace for a specific message.
    
    Requires API key authentication. Returns the LLM trace associated with a specific message.
    Useful for understanding how a particular message was processed.
    """
    try:
        validate_tenant_id(tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    require_tenant_access(tenant_id, api_tenant_id)
    
    db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
    db.commit()
    
    # Verify message exists
    msg = db.execute(
        text("SELECT id FROM messages WHERE id = :message_id AND tenant_id = :tenant_id"),
        {"message_id": message_id, "tenant_id": tenant_id}
    ).fetchone()
    
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    
    row = db.execute(
        text("""
            SELECT id, tenant_id, conversation_id, message_id, provider, model,
                   request_payload, response_payload, created_at
            FROM llm_traces
            WHERE tenant_id = :tenant_id AND message_id = :message_id
            ORDER BY created_at DESC
            LIMIT 1
        """),
        {"tenant_id": tenant_id, "message_id": message_id}
    ).fetchone()
    
    if not row:
        raise HTTPException(status_code=404, detail="LLM trace not found for this message")
    
    return LLMTraceResponse(
        id=str(row.id),
        tenant_id=str(row.tenant_id),
        conversation_id=str(row.conversation_id) if row.conversation_id else None,
        message_id=str(row.message_id) if row.message_id else None,
        provider=row.provider,
        model=row.model,
        request_payload=row.request_payload or {},
        response_payload=row.response_payload or {},
        created_at=row.created_at.isoformat(),
    )
