"""Analytics API router."""

from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Security, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime

from app.infra.database import get_db
from app.infra.auth import verify_api_key, require_tenant_access
from app.infra.validation import validate_tenant_id
from app.api.models import (
    ConversationAnalyticsResponse, UsageStatisticsResponse,
    KPISnapshotResponse, KPISnapshotsListResponse, CostSummaryResponse
)
from app.services.kpi_computation import compute_tenant_kpi_snapshots

router = APIRouter()


@router.get("/tenants/{tenant_id}/analytics/conversations", tags=["Analytics"], response_model=ConversationAnalyticsResponse)
async def get_conversation_analytics(
    tenant_id: str,
    start_date: Optional[str] = Query(None, description="Start date (ISO8601 timestamp)"),
    end_date: Optional[str] = Query(None, description="End date (ISO8601 timestamp)"),
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """Get conversation analytics for a tenant."""
    try:
        validate_tenant_id(tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    require_tenant_access(tenant_id, api_tenant_id)
    
    db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
    db.commit()
    
    date_filter = ""
    params = {"tenant_id": tenant_id}
    if start_date:
        date_filter += " AND created_at >= :start_date"
        params["start_date"] = start_date
    if end_date:
        date_filter += " AND created_at <= :end_date"
        params["end_date"] = end_date
    
    status_counts = db.execute(
        text(f"SELECT status, COUNT(*) as count FROM conversations WHERE tenant_id = :tenant_id {date_filter} GROUP BY status"),
        params
    ).fetchall()
    
    status_map = {row.status: row.count for row in status_counts}
    
    total = db.execute(
        text(f"SELECT COUNT(*) FROM conversations WHERE tenant_id = :tenant_id {date_filter}"),
        params
    ).scalar() or 0
    
    resolved = db.execute(
        text(f"""
            SELECT COUNT(*) FROM conversation_stats
            WHERE tenant_id = :tenant_id AND resolved = TRUE
            {date_filter.replace('created_at', 'updated_at') if date_filter else ''}
        """),
        params
    ).scalar() or 0
    
    avg_messages = db.execute(
        text(f"""
            SELECT AVG(total_messages) FROM conversation_stats
            WHERE tenant_id = :tenant_id
            {date_filter.replace('created_at', 'updated_at') if date_filter else ''}
        """),
        params
    ).scalar() or 0.0
    
    avg_tool_calls = db.execute(
        text(f"""
            SELECT AVG(tool_calls) FROM conversation_stats
            WHERE tenant_id = :tenant_id
            {date_filter.replace('created_at', 'updated_at') if date_filter else ''}
        """),
        params
    ).scalar() or 0.0
    
    resolution_rate = (resolved / total * 100) if total > 0 else 0.0
    
    return ConversationAnalyticsResponse(
        total_conversations=total,
        open_conversations=status_map.get("open", 0),
        closed_conversations=status_map.get("closed", 0),
        archived_conversations=status_map.get("archived", 0),
        resolved_conversations=resolved,
        resolution_rate=round(resolution_rate, 2),
        avg_messages_per_conversation=round(float(avg_messages), 2),
        avg_tool_calls_per_conversation=round(float(avg_tool_calls), 2),
        period_start=start_date,
        period_end=end_date,
    )


@router.get("/tenants/{tenant_id}/analytics/costs", tags=["Analytics"], response_model=CostSummaryResponse)
async def get_cost_analytics(
    tenant_id: str,
    start_date: Optional[str] = Query(None, description="Start date (ISO8601 timestamp)"),
    end_date: Optional[str] = Query(None, description="End date (ISO8601 timestamp)"),
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """Get cost analytics summary for a tenant."""
    try:
        validate_tenant_id(tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    require_tenant_access(tenant_id, api_tenant_id)
    
    db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
    db.commit()
    
    date_filter = ""
    params = {"tenant_id": tenant_id}
    if start_date:
        date_filter += " AND created_at >= :start_date"
        params["start_date"] = start_date
    if end_date:
        date_filter += " AND created_at <= :end_date"
        params["end_date"] = end_date
    
    llm_cost = db.execute(
        text(f"""
            SELECT COALESCE(SUM(cost), 0) FROM event_logs
            WHERE tenant_id = :tenant_id AND provider IN ('openai', 'gemini') AND cost IS NOT NULL
            {date_filter}
        """),
        params
    ).scalar() or 0.0
    
    tool_cost = db.execute(
        text(f"""
            SELECT COALESCE(SUM(cost), 0) FROM tool_call_logs
            WHERE tenant_id = :tenant_id AND cost IS NOT NULL
            {date_filter}
        """),
        params
    ).scalar() or 0.0
    
    total_cost = float(llm_cost) + float(tool_cost)
    
    return CostSummaryResponse(
        total_cost=round(total_cost, 6),
        llm_cost=round(float(llm_cost), 6),
        tool_cost=round(float(tool_cost), 6),
        period_start=start_date,
        period_end=end_date,
        currency="USD",
    )


@router.get("/tenants/{tenant_id}/analytics/kpis", tags=["Analytics"], response_model=KPISnapshotsListResponse)
async def list_kpi_snapshots(
    tenant_id: str,
    period_type: Optional[str] = Query(None, description="Filter by period type: 'daily', 'weekly', 'monthly'"),
    start_date: Optional[str] = Query(None, description="Start date (ISO8601 date)"),
    end_date: Optional[str] = Query(None, description="End date (ISO8601 date)"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """List KPI snapshots for a tenant."""
    try:
        validate_tenant_id(tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    require_tenant_access(tenant_id, api_tenant_id)
    
    db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
    db.commit()
    
    query = """
        SELECT tenant_id, period_type, period_start, period_end, metric_name, metric_value, created_at
        FROM tenant_kpi_snapshots
        WHERE tenant_id = :tenant_id
    """
    params = {"tenant_id": tenant_id}
    
    if period_type:
        valid_periods = ["daily", "weekly", "monthly"]
        if period_type not in valid_periods:
            raise HTTPException(status_code=400, detail=f"Invalid period_type. Must be one of: {valid_periods}")
        query += " AND period_type = :period_type"
        params["period_type"] = period_type
    
    if start_date:
        query += " AND period_start >= :start_date"
        params["start_date"] = start_date
    
    if end_date:
        query += " AND period_end <= :end_date"
        params["end_date"] = end_date
    
    query += " ORDER BY period_start DESC, metric_name"
    query += " LIMIT :limit OFFSET :offset"
    params["limit"] = limit
    params["offset"] = offset
    
    rows = db.execute(text(query), params).fetchall()
    
    items = [
        KPISnapshotResponse(
            tenant_id=str(row.tenant_id),
            period_type=row.period_type,
            period_start=row.period_start.isoformat(),
            period_end=row.period_end.isoformat(),
            metric_name=row.metric_name,
            metric_value=float(row.metric_value),
            created_at=row.created_at.isoformat(),
        )
        for row in rows
    ]
    
    return KPISnapshotsListResponse(items=items, count=len(items))


@router.get("/tenants/{tenant_id}/analytics/kpis/{period_type}", tags=["Analytics"], response_model=KPISnapshotsListResponse)
async def get_kpis_by_period(
    tenant_id: str,
    period_type: str,
    period_start: Optional[str] = Query(None, description="Period start date (ISO8601 date)"),
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """Get KPI snapshots for a specific period."""
    try:
        validate_tenant_id(tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    require_tenant_access(tenant_id, api_tenant_id)
    
    valid_periods = ["daily", "weekly", "monthly"]
    if period_type not in valid_periods:
        raise HTTPException(status_code=400, detail=f"Invalid period_type. Must be one of: {valid_periods}")
    
    db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
    db.commit()
    
    if period_start:
        rows = db.execute(
            text("""
                SELECT tenant_id, period_type, period_start, period_end, metric_name, metric_value, created_at
                FROM tenant_kpi_snapshots
                WHERE tenant_id = :tenant_id AND period_type = :period_type AND period_start = :period_start
                ORDER BY metric_name
            """),
            {"tenant_id": tenant_id, "period_type": period_type, "period_start": period_start}
        ).fetchall()
    else:
        rows = db.execute(
            text("""
                SELECT tenant_id, period_type, period_start, period_end, metric_name, metric_value, created_at
                FROM tenant_kpi_snapshots
                WHERE tenant_id = :tenant_id AND period_type = :period_type
                  AND period_start = (
                      SELECT MAX(period_start) FROM tenant_kpi_snapshots
                      WHERE tenant_id = :tenant_id AND period_type = :period_type
                  )
                ORDER BY metric_name
            """),
            {"tenant_id": tenant_id, "period_type": period_type}
        ).fetchall()
    
    items = [
        KPISnapshotResponse(
            tenant_id=str(row.tenant_id),
            period_type=row.period_type,
            period_start=row.period_start.isoformat(),
            period_end=row.period_end.isoformat(),
            metric_name=row.metric_name,
            metric_value=float(row.metric_value),
            created_at=row.created_at.isoformat(),
        )
        for row in rows
    ]
    
    return KPISnapshotsListResponse(items=items, count=len(items))


@router.post("/tenants/{tenant_id}/analytics/kpis/compute", tags=["Analytics"])
async def compute_kpis(
    tenant_id: str,
    period_type: str = Query("daily", description="Period type: 'daily', 'weekly', 'monthly'"),
    period_start: Optional[str] = Query(None, description="Period start date (ISO8601 date)"),
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """Trigger KPI computation for a tenant."""
    try:
        validate_tenant_id(tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    require_tenant_access(tenant_id, api_tenant_id)
    
    valid_periods = ["daily", "weekly", "monthly"]
    if period_type not in valid_periods:
        raise HTTPException(status_code=400, detail=f"Invalid period_type. Must be one of: {valid_periods}")
    
    period_start_dt = None
    if period_start:
        try:
            period_start_dt = datetime.fromisoformat(period_start.replace('Z', '+00:00'))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid period_start format. Use ISO8601 date format.")
    
    try:
        await compute_tenant_kpi_snapshots(
            tenant_id=tenant_id,
            period_type=period_type,
            period_start=period_start_dt,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to compute KPIs: {str(e)}")
    
    return {
        "status": "completed",
        "message": f"KPI computation completed for {period_type} period",
        "tenant_id": tenant_id,
        "period_type": period_type,
    }


@router.get("/tenants/{tenant_id}/analytics/usage", tags=["Analytics"], response_model=UsageStatisticsResponse)
async def get_usage_statistics(
    tenant_id: str,
    start_date: Optional[str] = Query(None, description="Start date (ISO8601 timestamp)"),
    end_date: Optional[str] = Query(None, description="End date (ISO8601 timestamp)"),
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """Get usage statistics for a tenant."""
    try:
        validate_tenant_id(tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    require_tenant_access(tenant_id, api_tenant_id)
    
    db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
    db.commit()
    
    date_filter = ""
    params = {"tenant_id": tenant_id}
    if start_date:
        date_filter += " AND created_at >= :start_date"
        params["start_date"] = start_date
    if end_date:
        date_filter += " AND created_at <= :end_date"
        params["end_date"] = end_date
    
    total_messages = db.execute(
        text(f"SELECT COUNT(*) FROM messages WHERE tenant_id = :tenant_id {date_filter}"),
        params
    ).scalar() or 0
    
    total_conversations = db.execute(
        text(f"SELECT COUNT(DISTINCT conversation_id) FROM messages WHERE tenant_id = :tenant_id {date_filter}"),
        params
    ).scalar() or 0
    
    total_tool_calls = db.execute(
        text(f"SELECT COUNT(*) FROM tool_call_logs WHERE tenant_id = :tenant_id {date_filter}"),
        params
    ).scalar() or 0
    
    total_llm_calls = db.execute(
        text(f"""
            SELECT COUNT(*) FROM event_logs
            WHERE tenant_id = :tenant_id AND provider IN ('openai', 'gemini')
            {date_filter}
        """),
        params
    ).scalar() or 0
    
    active_conversations = db.execute(
        text(f"""
            SELECT COUNT(*) FROM conversations
            WHERE tenant_id = :tenant_id AND status = 'open'
            {date_filter.replace('created_at', 'updated_at') if date_filter else ''}
        """),
        params
    ).scalar() or 0
    
    return UsageStatisticsResponse(
        total_messages=total_messages,
        total_conversations=total_conversations,
        total_tool_calls=total_tool_calls,
        total_llm_calls=total_llm_calls,
        active_conversations=active_conversations,
        period_start=start_date,
        period_end=end_date,
    )

