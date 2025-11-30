"""Agentic reflection service for analyzing execution and generating insights."""

import json
import logging
import uuid
from typing import Dict, Any, Optional, List
from sqlalchemy import text
from app.models.tenant import TenantContext
from app.infra.database import get_db_session

logger = logging.getLogger(__name__)


async def reflect_on_execution(
    tenant_ctx: TenantContext,
    plan_id: str,
    task_id: Optional[str],
    execution_results: List[Dict[str, Any]],
    final_outcome: str,
) -> Dict[str, Any]:
    """
    Analyze plan execution and generate insights.
    
    Args:
        tenant_ctx: TenantContext
        plan_id: Plan ID
        task_id: Optional task ID
        execution_results: List of step execution results
        final_outcome: Final outcome (success, partial, failed)
    
    Returns:
        Dict with insights and recommendations
    """
    # Analyze execution results
    successful_steps = []
    failed_steps = []
    tool_usage = {}
    
    for result in execution_results:
        step_num = result.get("step_number", 0)
        status = result.get("status", "unknown")
        tool_name = result.get("tool_name")
        
        if status == "success":
            successful_steps.append(step_num)
            if tool_name:
                tool_usage[tool_name] = tool_usage.get(tool_name, 0) + 1
        else:
            failed_steps.append({
                "step_number": step_num,
                "error": result.get("error", "Unknown error"),
                "tool_name": tool_name,
            })
    
    # Generate insights
    insights = {
        "final_outcome": final_outcome,
        "total_steps": len(execution_results),
        "successful_steps": len(successful_steps),
        "failed_steps": len(failed_steps),
        "success_rate": len(successful_steps) / len(execution_results) if execution_results else 0,
        "successful_step_numbers": successful_steps,
        "failed_step_details": failed_steps,
        "tool_usage": tool_usage,
        "most_used_tool": max(tool_usage.items(), key=lambda x: x[1])[0] if tool_usage else None,
    }
    
    # Generate recommendations
    recommendations = {
        "suggestions": [],
        "improvements": [],
    }
    
    if failed_steps:
        recommendations["suggestions"].append(
            f"Review {len(failed_steps)} failed steps and consider alternative approaches"
        )
        recommendations["improvements"].append(
            "Add error handling for common failure patterns"
        )
    
    if len(successful_steps) == len(execution_results):
        recommendations["suggestions"].append(
            "Plan executed successfully - consider caching similar plans"
        )
    
    if tool_usage:
        most_used = max(tool_usage.items(), key=lambda x: x[1])
        recommendations["suggestions"].append(
            f"Tool '{most_used[0]}' was used {most_used[1]} times - consider optimizing its usage"
        )
    
    # Store insights
    insight_id = str(uuid.uuid4())
    with get_db_session(tenant_ctx.tenant_id) as session:
        session.execute(
            text("""
                INSERT INTO agentic_insights (
                    id, tenant_id, plan_id, task_id,
                    insights, recommendations
                ) VALUES (
                    :id, :tenant_id, :plan_id, :task_id,
                    CAST(:insights AS jsonb), CAST(:recommendations AS jsonb)
                )
            """),
            {
                "id": insight_id,
                "tenant_id": tenant_ctx.tenant_id,
                "plan_id": plan_id,
                "task_id": task_id,
                "insights": json.dumps(insights),
                "recommendations": json.dumps(recommendations),
            }
        )
        session.commit()
    
    return {
        "insight_id": insight_id,
        "insights": insights,
        "recommendations": recommendations,
    }


async def get_similar_insights(
    tenant_ctx: TenantContext,
    goal: str,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """
    Get similar past insights for a goal.
    
    Args:
        tenant_ctx: TenantContext
        goal: Goal to find similar insights for
        limit: Maximum number of insights to return
    
    Returns:
        List of insight dicts
    """
    # For now, return recent insights
    # Future: Use semantic search or similarity matching
    with get_db_session(tenant_ctx.tenant_id) as session:
        rows = session.execute(
            text("""
                SELECT i.id, i.plan_id, i.task_id, i.insights, i.recommendations, i.created_at,
                       p.goal
                FROM agentic_insights i
                LEFT JOIN agentic_plans p ON i.plan_id = p.id
                WHERE i.tenant_id = :tenant_id
                ORDER BY i.created_at DESC
                LIMIT :limit
            """),
            {"tenant_id": tenant_ctx.tenant_id, "limit": limit}
        ).fetchall()
        
        insights = []
        for row in rows:
            insights.append({
                "insight_id": str(row.id),
                "plan_id": str(row.plan_id) if row.plan_id else None,
                "task_id": str(row.task_id) if row.task_id else None,
                "goal": row.goal,
                "insights": row.insights if isinstance(row.insights, dict) else json.loads(row.insights) if row.insights else {},
                "recommendations": row.recommendations if isinstance(row.recommendations, dict) else json.loads(row.recommendations) if row.recommendations else {},
                "created_at": row.created_at.isoformat() if row.created_at else None,
            })
        
        return insights

