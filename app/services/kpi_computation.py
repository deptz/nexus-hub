"""Tenant KPI snapshots computation for reporting."""

from datetime import datetime, timedelta
from typing import List, Optional
from sqlalchemy import text
from app.infra.database import get_db_session


async def compute_tenant_kpi_snapshots(
    tenant_id: Optional[str] = None,
    period_type: str = "daily",
    period_start: Optional[datetime] = None,
) -> None:
    """
    Compute and store KPI snapshots for tenants.
    
    Args:
        tenant_id: Optional tenant ID to compute for specific tenant (None = all tenants)
        period_type: 'daily', 'weekly', or 'monthly'
        period_start: Start of period (defaults to yesterday for daily, last week for weekly, last month for monthly)
    """
    if period_start is None:
        if period_type == "daily":
            period_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
        elif period_type == "weekly":
            # Start of last week (Monday)
            today = datetime.utcnow()
            days_since_monday = (today.weekday()) % 7
            last_monday = today - timedelta(days=days_since_monday + 7)
            period_start = last_monday.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period_type == "monthly":
            # Start of last month
            today = datetime.utcnow()
            first_day_this_month = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            period_start = (first_day_this_month - timedelta(days=1)).replace(day=1)
        else:
            raise ValueError(f"Invalid period_type: {period_type}")
    
    # Calculate period_end
    if period_type == "daily":
        period_end = period_start + timedelta(days=1)
    elif period_type == "weekly":
        period_end = period_start + timedelta(days=7)
    elif period_type == "monthly":
        # Add one month
        if period_start.month == 12:
            period_end = period_start.replace(year=period_start.year + 1, month=1)
        else:
            period_end = period_start.replace(month=period_start.month + 1)
    else:
        raise ValueError(f"Invalid period_type: {period_type}")
    
    # Get list of tenants to process
    if tenant_id:
        tenant_ids = [tenant_id]
    else:
        # SECURITY: RLS bypass is only allowed for system/admin operations
        # This function should only be called from:
        # 1. Scheduled background jobs (cron/worker)
        # 2. Admin endpoints with proper authorization
        # 3. Internal system operations
        # 
        # NEVER expose this function directly to tenant users via API
        # 
        # Get all active tenants
        with get_db_session(None) as session:  # No tenant context for querying all tenants
            # SECURITY: Temporarily disable RLS ONLY for this specific query
            # This is scoped to the transaction and automatically re-enabled
            # The SET LOCAL ensures it only affects this transaction
            try:
                session.execute(text("SET LOCAL row_security = off"))
                tenants = session.execute(
                    text("SELECT id FROM tenants")
                ).fetchall()
                tenant_ids = [str(t.id) for t in tenants]
                # RLS is automatically re-enabled when transaction ends
                # But we explicitly re-enable it for clarity
                session.execute(text("SET LOCAL row_security = on"))
            except Exception as e:
                # Ensure RLS is re-enabled even on error
                try:
                    session.execute(text("SET LOCAL row_security = on"))
                except:
                    pass
                raise
    
    # Compute KPIs for each tenant
    for tid in tenant_ids:
        await _compute_tenant_kpis(
            tid,
            period_type,
            period_start.date(),
            period_end.date(),
        )


async def _compute_tenant_kpis(
    tenant_id: str,
    period_type: str,
    period_start: datetime.date,
    period_end: datetime.date,
) -> None:
    """Compute KPIs for a single tenant and store in snapshots."""
    with get_db_session(tenant_id) as session:
        # 1. Conversations resolved
        resolved_count = session.execute(
            text("""
                SELECT COUNT(*) FROM conversation_stats
                WHERE tenant_id = :tenant_id
                  AND resolved = TRUE
                  AND updated_at >= :period_start
                  AND updated_at < :period_end
            """),
            {
                "tenant_id": tenant_id,
                "period_start": period_start,
                "period_end": period_end,
            }
        ).scalar() or 0
        
        # 2. Total conversations
        total_conversations = session.execute(
            text("""
                SELECT COUNT(DISTINCT conversation_id) FROM messages
                WHERE tenant_id = :tenant_id
                  AND created_at >= :period_start
                  AND created_at < :period_end
            """),
            {
                "tenant_id": tenant_id,
                "period_start": period_start,
                "period_end": period_end,
            }
        ).scalar() or 0
        
        # 3. Resolution rate
        resolution_rate = (resolved_count / total_conversations * 100) if total_conversations > 0 else 0.0
        
        # 4. Average messages per conversation
        avg_messages = session.execute(
            text("""
                SELECT AVG(total_messages) FROM conversation_stats
                WHERE tenant_id = :tenant_id
                  AND updated_at >= :period_start
                  AND updated_at < :period_end
            """),
            {
                "tenant_id": tenant_id,
                "period_start": period_start,
                "period_end": period_end,
            }
        ).scalar() or 0.0
        
        # 5. Tool call success rate
        tool_calls_total = session.execute(
            text("""
                SELECT COUNT(*) FROM tool_call_logs
                WHERE tenant_id = :tenant_id
                  AND created_at >= :period_start
                  AND created_at < :period_end
            """),
            {
                "tenant_id": tenant_id,
                "period_start": period_start,
                "period_end": period_end,
            }
        ).scalar() or 0
        
        tool_calls_success = session.execute(
            text("""
                SELECT COUNT(*) FROM tool_call_logs
                WHERE tenant_id = :tenant_id
                  AND status = 'success'
                  AND created_at >= :period_start
                  AND created_at < :period_end
            """),
            {
                "tenant_id": tenant_id,
                "period_start": period_start,
                "period_end": period_end,
            }
        ).scalar() or 0
        
        tool_success_rate = (tool_calls_success / tool_calls_total * 100) if tool_calls_total > 0 else 0.0
        
        # 6. Average cost per conversation
        total_cost = session.execute(
            text("""
                SELECT COALESCE(SUM(cost), 0) FROM event_logs
                WHERE tenant_id = :tenant_id
                  AND event_type IN ('llm_call_completed', 'tool_call_completed')
                  AND created_at >= :period_start
                  AND created_at < :period_end
            """),
            {
                "tenant_id": tenant_id,
                "period_start": period_start,
                "period_end": period_end,
            }
        ).scalar() or 0.0
        
        avg_cost_per_conv = (total_cost / total_conversations) if total_conversations > 0 else 0.0
        
        # 7. Average latency
        avg_latency = session.execute(
            text("""
                SELECT AVG(latency_ms) FROM event_logs
                WHERE tenant_id = :tenant_id
                  AND event_type = 'llm_call_completed'
                  AND created_at >= :period_start
                  AND created_at < :period_end
            """),
            {
                "tenant_id": tenant_id,
                "period_start": period_start,
                "period_end": period_end,
            }
        ).scalar() or 0.0
        
        # 8. DAU/WAU (for daily/weekly periods)
        if period_type == "daily":
            dau = session.execute(
                text("""
                    SELECT COUNT(DISTINCT from_external_id) FROM messages
                    WHERE tenant_id = :tenant_id
                      AND from_type = 'user'
                      AND created_at >= :period_start
                      AND created_at < :period_end
                """),
                {
                    "tenant_id": tenant_id,
                    "period_start": period_start,
                    "period_end": period_end,
                }
            ).scalar() or 0
            
            _store_kpi_snapshot(session, tenant_id, period_type, period_start, period_end, "dau", float(dau))
        
        if period_type == "weekly":
            wau = session.execute(
                text("""
                    SELECT COUNT(DISTINCT from_external_id) FROM messages
                    WHERE tenant_id = :tenant_id
                      AND from_type = 'user'
                      AND created_at >= :period_start
                      AND created_at < :period_end
                """),
                {
                    "tenant_id": tenant_id,
                    "period_start": period_start,
                    "period_end": period_end,
                }
            ).scalar() or 0
            
            _store_kpi_snapshot(session, tenant_id, period_type, period_start, period_end, "wau", float(wau))
        
        # Store all computed metrics
        _store_kpi_snapshot(session, tenant_id, period_type, period_start, period_end, "conversations_resolved", float(resolved_count))
        _store_kpi_snapshot(session, tenant_id, period_type, period_start, period_end, "conversations_total", float(total_conversations))
        _store_kpi_snapshot(session, tenant_id, period_type, period_start, period_end, "resolution_rate", resolution_rate)
        _store_kpi_snapshot(session, tenant_id, period_type, period_start, period_end, "avg_messages_per_conv", avg_messages)
        _store_kpi_snapshot(session, tenant_id, period_type, period_start, period_end, "tool_call_success_rate", tool_success_rate)
        _store_kpi_snapshot(session, tenant_id, period_type, period_start, period_end, "avg_cost_per_conv", avg_cost_per_conv)
        _store_kpi_snapshot(session, tenant_id, period_type, period_start, period_end, "avg_latency_ms", avg_latency)
        
        session.commit()


def _store_kpi_snapshot(
    session,
    tenant_id: str,
    period_type: str,
    period_start: datetime.date,
    period_end: datetime.date,
    metric_name: str,
    metric_value: float,
) -> None:
    """Store a single KPI snapshot (upsert)."""
    session.execute(
        text("""
            INSERT INTO tenant_kpi_snapshots (
                tenant_id, period_type, period_start, period_end, metric_name, metric_value
            ) VALUES (
                :tenant_id, :period_type, :period_start, :period_end, :metric_name, :metric_value
            )
            ON CONFLICT (tenant_id, period_type, period_start, metric_name)
            DO UPDATE SET metric_value = EXCLUDED.metric_value
        """),
        {
            "tenant_id": tenant_id,
            "period_type": period_type,
            "period_start": period_start,
            "period_end": period_end,
            "metric_name": metric_name,
            "metric_value": metric_value,
        }
    )

