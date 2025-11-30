"""Task management API endpoints."""

from typing import List, Optional
from fastapi import APIRouter, HTTPException, Depends, Security, Query, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from app.infra.database import get_db
from app.infra.auth import verify_api_key
from app.services.agentic_task_manager import (
    create_task,
    get_task,
    resume_task,
    cancel_task,
    list_tasks,
)
from app.infra.metrics import tasks_created_total, tasks_resumed_total
from app.services.tenant_context_service import get_tenant_context
from app.models.tenant import TenantContext

router = APIRouter(prefix="/tasks", tags=["Tasks"])


class CreateTaskRequest(BaseModel):
    """Request to create a new agentic task."""
    goal: str = Field(..., description="Task goal or objective", example="Process 100 customer support tickets")
    plan_id: Optional[str] = Field(None, description="Optional plan ID this task is associated with", example="550e8400-e29b-41d4-a716-446655440000")
    conversation_id: Optional[str] = Field(None, description="Optional conversation ID this task belongs to", example="660e8400-e29b-41d4-a716-446655440000")


class TaskResponse(BaseModel):
    """Task response model with current state and progress."""
    task_id: str = Field(..., description="Unique task identifier", example="770e8400-e29b-41d4-a716-446655440000")
    goal: str = Field(..., description="Task goal", example="Process 100 customer support tickets")
    plan_id: Optional[str] = Field(None, description="Associated plan ID", example="550e8400-e29b-41d4-a716-446655440000")
    conversation_id: Optional[str] = Field(None, description="Associated conversation ID", example="660e8400-e29b-41d4-a716-446655440000")
    status: str = Field(..., description="Task status: planning, executing, completed, failed, cancelled", example="executing")
    current_step: int = Field(..., description="Current step number (0-indexed)", example=3)
    state: dict = Field(..., description="Task state including step results and intermediate data", example={"step_results": []})
    created_at: Optional[str] = Field(None, description="Task creation timestamp", example="2024-01-01T00:00:00Z")
    updated_at: Optional[str] = Field(None, description="Last update timestamp", example="2024-01-01T00:05:00Z")
    completed_at: Optional[str] = Field(None, description="Task completion timestamp (null if not completed)", example=None)


@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_new_task(
    request: CreateTaskRequest,
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """
    Create a new agentic task.
    
    Tasks are used for long-running operations that may need to be resumed
    after interruptions.
    """
    tenant_ctx = get_tenant_context(api_tenant_id)
    
    try:
        task = await create_task(
            tenant_ctx=tenant_ctx,
            goal=request.goal,
            plan_id=request.plan_id,
            conversation_id=request.conversation_id,
        )
        tasks_created_total.labels(tenant_id=api_tenant_id, status="success").inc()
        return TaskResponse(**task)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create task: {str(e)}"
        )


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task_status(
    task_id: str,
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """
    Get task status and state.
    
    Returns the current state of a task including its progress and intermediate data.
    """
    tenant_ctx = get_tenant_context(api_tenant_id)
    
    task = await get_task(tenant_ctx, task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {task_id} not found"
        )
    
    return TaskResponse(**task)


@router.post("/{task_id}/resume", response_model=TaskResponse)
async def resume_interrupted_task(
    task_id: str,
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """
    Resume an interrupted task.
    
    Resumes a task that was paused or failed, continuing from the last successful step.
    """
    tenant_ctx = get_tenant_context(api_tenant_id)
    
    try:
        task = await resume_task(tenant_ctx, task_id)
        tasks_resumed_total.labels(tenant_id=api_tenant_id).inc()
        return TaskResponse(**task)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to resume task: {str(e)}"
        )


@router.post("/{task_id}/cancel", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_running_task(
    task_id: str,
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """
    Cancel a running task.
    
    Marks a task as failed and stops further execution.
    """
    tenant_ctx = get_tenant_context(api_tenant_id)
    
    try:
        await cancel_task(tenant_ctx, task_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to cancel task: {str(e)}"
        )


@router.get("", response_model=List[TaskResponse])
async def list_tenant_tasks(
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=100, description="Maximum number of tasks to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """
    List tasks for the tenant.
    
    Returns a paginated list of tasks, optionally filtered by status.
    """
    tenant_ctx = get_tenant_context(api_tenant_id)
    
    try:
        tasks = await list_tasks(tenant_ctx, status=status, limit=limit, offset=offset)
        return [TaskResponse(**task) for task in tasks]
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list tasks: {str(e)}"
        )

