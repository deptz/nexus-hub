"""Costs API router."""

from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Security, Query
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.infra.database import get_db
from app.infra.auth import verify_api_key, require_tenant_access
from app.infra.validation import validate_tenant_id
from app.api.models import (
    CostSummaryResponse, CostBreakdownResponse,
    CostByPeriodResponse, CostByConversationResponse,
    CostEstimateRequest, CostEstimateResponse
)
from app.api.routers.analytics import get_cost_analytics
from app.services.cost_calculator import calculate_llm_cost

router = APIRouter()


@router.get("/tenants/{tenant_id}/costs", tags=["Costs"], response_model=CostSummaryResponse)
async def get_cost_summary(
    tenant_id: str,
    start_date: Optional[str] = Query(None, description="Start date (ISO8601 timestamp)"),
    end_date: Optional[str] = Query(None, description="End date (ISO8601 timestamp)"),
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """Get cost summary for a tenant. Alias for /analytics/costs."""
    return await get_cost_analytics(tenant_id, start_date, end_date, db, api_tenant_id)


@router.get("/tenants/{tenant_id}/costs/breakdown", tags=["Costs"], response_model=CostBreakdownResponse)
async def get_cost_breakdown(
    tenant_id: str,
    start_date: Optional[str] = Query(None, description="Start date (ISO8601 timestamp)"),
    end_date: Optional[str] = Query(None, description="End date (ISO8601 timestamp)"),
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """Get detailed cost breakdown for a tenant."""
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
    
    provider_costs = db.execute(
        text(f"""
            SELECT provider, COALESCE(SUM(cost), 0) as total_cost
            FROM event_logs
            WHERE tenant_id = :tenant_id AND provider IN ('openai', 'gemini') AND cost IS NOT NULL
            {date_filter}
            GROUP BY provider
        """),
        params
    ).fetchall()
    
    by_provider = {row.provider: float(row.total_cost) for row in provider_costs}
    
    model_costs = db.execute(
        text(f"""
            SELECT COALESCE(lt.model, 'unknown') as model, COALESCE(SUM(el.cost), 0) as total_cost
            FROM event_logs el
            LEFT JOIN llm_traces lt ON el.message_id = lt.message_id
            WHERE el.tenant_id = :tenant_id AND el.provider IN ('openai', 'gemini') AND el.cost IS NOT NULL
            {date_filter}
            GROUP BY lt.model
        """),
        params
    ).fetchall()
    
    by_model = {row.model: float(row.total_cost) for row in model_costs if row.model}
    
    tool_costs = db.execute(
        text(f"""
            SELECT tool_name, COALESCE(SUM(cost), 0) as total_cost
            FROM tool_call_logs
            WHERE tenant_id = :tenant_id AND cost IS NOT NULL
            {date_filter}
            GROUP BY tool_name
        """),
        params
    ).fetchall()
    
    by_tool = {row.tool_name: float(row.total_cost) for row in tool_costs}
    
    llm_cost = sum(by_provider.values())
    tool_cost = sum(by_tool.values())
    total_cost = llm_cost + tool_cost
    
    return CostBreakdownResponse(
        total_cost=round(total_cost, 6),
        llm_cost=round(llm_cost, 6),
        tool_cost=round(tool_cost, 6),
        by_provider=by_provider,
        by_model=by_model,
        by_tool=by_tool,
        period_start=start_date,
        period_end=end_date,
        currency="USD",
    )


@router.get("/tenants/{tenant_id}/costs/by-period", tags=["Costs"], response_model=CostByPeriodResponse)
async def get_costs_by_period(
    tenant_id: str,
    period_type: str = Query("daily", description="Period type: 'daily', 'weekly', 'monthly'"),
    start_date: Optional[str] = Query(None, description="Start date (ISO8601 date)"),
    end_date: Optional[str] = Query(None, description="End date (ISO8601 date)"),
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """Get costs grouped by time period."""
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
    
    date_filter = ""
    params = {"tenant_id": tenant_id}
    if start_date:
        date_filter += " AND created_at >= :start_date"
        params["start_date"] = start_date
    if end_date:
        date_filter += " AND created_at <= :end_date"
        params["end_date"] = end_date
    
    if period_type == "daily":
        group_by = "DATE(created_at)"
    elif period_type == "weekly":
        group_by = "DATE_TRUNC('week', created_at)"
    else:  # monthly
        group_by = "DATE_TRUNC('month', created_at)"
    
    rows = db.execute(
        text(f"""
            SELECT {group_by} as period, COALESCE(SUM(cost), 0) as total_cost
            FROM event_logs
            WHERE tenant_id = :tenant_id AND cost IS NOT NULL
            {date_filter}
            GROUP BY {group_by}
            ORDER BY period DESC
        """),
        params
    ).fetchall()
    
    items = [
        {
            "period": row.period.isoformat() if hasattr(row.period, 'isoformat') else str(row.period),
            "cost": round(float(row.total_cost), 6),
        }
        for row in rows
    ]
    
    total_cost = sum(item["cost"] for item in items)
    
    return CostByPeriodResponse(
        items=items,
        total_cost=round(total_cost, 6),
        period_type=period_type,
        period_start=start_date or "all",
        period_end=end_date or "all",
    )


@router.get("/tenants/{tenant_id}/costs/by-conversation", tags=["Costs"], response_model=CostByConversationResponse)
async def get_costs_by_conversation(
    tenant_id: str,
    start_date: Optional[str] = Query(None, description="Start date (ISO8601 timestamp)"),
    end_date: Optional[str] = Query(None, description="End date (ISO8601 timestamp)"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """Get costs per conversation."""
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
    
    rows = db.execute(
        text(f"""
            SELECT conversation_id, COALESCE(SUM(cost), 0) as total_cost
            FROM (
                SELECT conversation_id, cost, created_at FROM event_logs
                WHERE tenant_id = :tenant_id AND cost IS NOT NULL
                UNION ALL
                SELECT conversation_id, cost, created_at FROM tool_call_logs
                WHERE tenant_id = :tenant_id AND cost IS NOT NULL
            ) combined
            WHERE conversation_id IS NOT NULL {date_filter}
            GROUP BY conversation_id
            ORDER BY total_cost DESC
            LIMIT :limit OFFSET :offset
        """),
        {**params, "limit": limit, "offset": offset}
    ).fetchall()
    
    items = [
        {"conversation_id": str(row.conversation_id), "cost": round(float(row.total_cost), 6)}
        for row in rows
    ]
    
    total_cost_row = db.execute(
        text(f"""
            SELECT COALESCE(SUM(cost), 0) as total_cost
            FROM (
                SELECT cost, created_at FROM event_logs WHERE tenant_id = :tenant_id AND cost IS NOT NULL
                UNION ALL
                SELECT cost, created_at FROM tool_call_logs WHERE tenant_id = :tenant_id AND cost IS NOT NULL
            ) combined
            WHERE 1=1 {date_filter}
        """),
        params
    ).fetchone()
    
    total_cost = float(total_cost_row.total_cost) if total_cost_row else 0.0
    
    return CostByConversationResponse(
        items=items,
        total_cost=round(total_cost, 6),
        count=len(items),
    )


@router.post("/tenants/{tenant_id}/costs/estimate", tags=["Costs"], response_model=CostEstimateResponse)
async def estimate_cost(
    tenant_id: str,
    request: CostEstimateRequest,
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """Estimate cost for an LLM API call."""
    try:
        validate_tenant_id(tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    require_tenant_access(tenant_id, api_tenant_id)
    
    valid_providers = ["openai", "gemini"]
    if request.provider not in valid_providers:
        raise HTTPException(status_code=400, detail=f"Invalid provider. Must be one of: {valid_providers}")
    
    try:
        estimated_cost = calculate_llm_cost(
            provider=request.provider,
            model=request.model,
            prompt_tokens=request.estimated_prompt_tokens,
            completion_tokens=request.estimated_completion_tokens,
            total_tokens=request.estimated_total_tokens,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to calculate cost: {str(e)}")
    
    breakdown = {}
    if request.estimated_prompt_tokens and request.estimated_completion_tokens:
        breakdown = {
            "prompt_tokens": request.estimated_prompt_tokens,
            "completion_tokens": request.estimated_completion_tokens,
            "total_tokens": request.estimated_prompt_tokens + request.estimated_completion_tokens,
        }
    elif request.estimated_total_tokens:
        breakdown = {
            "total_tokens": request.estimated_total_tokens,
            "estimated_prompt_tokens": int(request.estimated_total_tokens * 0.7),
            "estimated_completion_tokens": int(request.estimated_total_tokens * 0.3),
        }
    
    return CostEstimateResponse(
        estimated_cost=round(estimated_cost, 6),
        provider=request.provider,
        model=request.model,
        currency="USD",
        breakdown=breakdown,
    )

