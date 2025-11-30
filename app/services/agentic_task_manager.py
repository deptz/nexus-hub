"""Agentic task manager for state persistence and resumption."""

import json
import logging
import uuid
from typing import Dict, Any, Optional, List
from datetime import datetime
from sqlalchemy import text
from app.models.tenant import TenantContext
from app.infra.database import get_db_session

logger = logging.getLogger(__name__)


async def create_task(
    tenant_ctx: TenantContext,
    goal: str,
    plan_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a new agentic task from a plan.
    
    Args:
        tenant_ctx: TenantContext
        goal: Task goal
        plan_id: Optional plan ID
        conversation_id: Optional conversation ID
    
    Returns:
        Dict with task_id, status, and metadata
    """
    task_id = str(uuid.uuid4())
    with get_db_session(tenant_ctx.tenant_id) as session:
        session.execute(
            text("""
                INSERT INTO agentic_tasks (
                    id, tenant_id, conversation_id, plan_id,
                    goal, current_step, state, status
                ) VALUES (
                    :id, :tenant_id, :conversation_id, :plan_id,
                    :goal, :current_step, CAST(:state AS jsonb), :status
                )
            """),
            {
                "id": task_id,
                "tenant_id": tenant_ctx.tenant_id,
                "conversation_id": conversation_id,
                "plan_id": plan_id,
                "goal": goal,
                "current_step": 0,
                "state": json.dumps({}),
                "status": "planning" if plan_id else "executing",
            }
        )
        session.commit()
    
    return {
        "task_id": task_id,
        "goal": goal,
        "plan_id": plan_id,
        "status": "planning" if plan_id else "executing",
        "current_step": 0,
    }


async def update_task_state(
    tenant_ctx: TenantContext,
    task_id: str,
    current_step: int,
    state: Dict[str, Any],
    status: Optional[str] = None,
) -> None:
    """
    Update task state after a step execution.
    
    Args:
        tenant_ctx: TenantContext
        task_id: Task ID
        current_step: Current step number
        state: Updated state (step results, intermediate data)
        status: Optional status update
    """
    with get_db_session(tenant_ctx.tenant_id) as session:
        update_query = """
            UPDATE agentic_tasks
            SET current_step = :current_step,
                state = CAST(:state AS jsonb),
                updated_at = now()
        """
        params = {
            "task_id": task_id,
            "tenant_id": tenant_ctx.tenant_id,
            "current_step": current_step,
            "state": json.dumps(state),
        }
        
        if status:
            update_query += ", status = :status"
            params["status"] = status
        
        update_query += " WHERE id = :task_id AND tenant_id = :tenant_id"
        
        session.execute(text(update_query), params)
        session.commit()


async def get_task(
    tenant_ctx: TenantContext,
    task_id: str,
) -> Optional[Dict[str, Any]]:
    """
    Get task by ID.
    
    Args:
        tenant_ctx: TenantContext
        task_id: Task ID
    
    Returns:
        Task dict or None if not found
    """
    with get_db_session(tenant_ctx.tenant_id) as session:
        row = session.execute(
            text("""
                SELECT id, tenant_id, conversation_id, plan_id, goal,
                       current_step, state, status, created_at, updated_at, completed_at
                FROM agentic_tasks
                WHERE id = :task_id AND tenant_id = :tenant_id
            """),
            {"task_id": task_id, "tenant_id": tenant_ctx.tenant_id}
        ).fetchone()
        
        if not row:
            return None
        
        return {
            "task_id": str(row.id),
            "tenant_id": str(row.tenant_id),
            "conversation_id": str(row.conversation_id) if row.conversation_id else None,
            "plan_id": str(row.plan_id) if row.plan_id else None,
            "goal": row.goal,
            "current_step": row.current_step,
            "state": row.state if isinstance(row.state, dict) else json.loads(row.state) if row.state else {},
            "status": row.status,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        }


async def resume_task(
    tenant_ctx: TenantContext,
    task_id: str,
) -> Dict[str, Any]:
    """
    Resume an interrupted task.
    
    Args:
        tenant_ctx: TenantContext
        task_id: Task ID
    
    Returns:
        Task dict with updated status
    
    Raises:
        ValueError: If task not found or cannot be resumed
    """
    task = await get_task(tenant_ctx, task_id)
    if not task:
        raise ValueError(f"Task {task_id} not found")
    
    if task["status"] not in ["paused", "failed"]:
        raise ValueError(f"Task {task_id} cannot be resumed from status {task['status']}")
    
    with get_db_session(tenant_ctx.tenant_id) as session:
        session.execute(
            text("""
                UPDATE agentic_tasks
                SET status = 'executing', updated_at = now()
                WHERE id = :task_id AND tenant_id = :tenant_id
            """),
            {"task_id": task_id, "tenant_id": tenant_ctx.tenant_id}
        )
        session.commit()
    
    task["status"] = "executing"
    return task


async def cancel_task(
    tenant_ctx: TenantContext,
    task_id: str,
) -> None:
    """
    Cancel a running task.
    
    Args:
        tenant_ctx: TenantContext
        task_id: Task ID
    
    Raises:
        ValueError: If task not found
    """
    task = await get_task(tenant_ctx, task_id)
    if not task:
        raise ValueError(f"Task {task_id} not found")
    
    if task["status"] in ["completed", "failed"]:
        raise ValueError(f"Task {task_id} is already {task['status']}")
    
    with get_db_session(tenant_ctx.tenant_id) as session:
        session.execute(
            text("""
                UPDATE agentic_tasks
                SET status = 'failed', updated_at = now()
                WHERE id = :task_id AND tenant_id = :tenant_id
            """),
            {"task_id": task_id, "tenant_id": tenant_ctx.tenant_id}
        )
        session.commit()


async def complete_task(
    tenant_ctx: TenantContext,
    task_id: str,
    final_state: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Mark a task as completed.
    
    Args:
        tenant_ctx: TenantContext
        task_id: Task ID
        final_state: Optional final state to store
    """
    with get_db_session(tenant_ctx.tenant_id) as session:
        update_query = """
            UPDATE agentic_tasks
            SET status = 'completed',
                completed_at = now(),
                updated_at = now()
        """
        params = {
            "task_id": task_id,
            "tenant_id": tenant_ctx.tenant_id,
        }
        
        if final_state:
            update_query += ", state = CAST(:state AS jsonb)"
            params["state"] = json.dumps(final_state)
        
        update_query += " WHERE id = :task_id AND tenant_id = :tenant_id"
        
        session.execute(text(update_query), params)
        session.commit()


async def list_tasks(
    tenant_ctx: TenantContext,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """
    List tasks for a tenant.
    
    Args:
        tenant_ctx: TenantContext
        status: Optional status filter
        limit: Maximum number of tasks to return
        offset: Offset for pagination
    
    Returns:
        List of task dicts
    """
    with get_db_session(tenant_ctx.tenant_id) as session:
        query = """
            SELECT id, tenant_id, conversation_id, plan_id, goal,
                   current_step, state, status, created_at, updated_at, completed_at
            FROM agentic_tasks
            WHERE tenant_id = :tenant_id
        """
        params = {"tenant_id": tenant_ctx.tenant_id}
        
        if status:
            query += " AND status = :status"
            params["status"] = status
        
        query += " ORDER BY updated_at DESC LIMIT :limit OFFSET :offset"
        params["limit"] = limit
        params["offset"] = offset
        
        rows = session.execute(text(query), params).fetchall()
        
        tasks = []
        for row in rows:
            tasks.append({
                "task_id": str(row.id),
                "tenant_id": str(row.tenant_id),
                "conversation_id": str(row.conversation_id) if row.conversation_id else None,
                "plan_id": str(row.plan_id) if row.plan_id else None,
                "goal": row.goal,
                "current_step": row.current_step,
                "state": row.state if isinstance(row.state, dict) else json.loads(row.state) if row.state else {},
                "status": row.status,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                "completed_at": row.completed_at.isoformat() if row.completed_at else None,
            })
        
        return tasks

