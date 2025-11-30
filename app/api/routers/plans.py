"""Plan management API endpoints."""

from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Security, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from app.infra.database import get_db
from app.infra.auth import verify_api_key
from app.services.agentic_planner import refine_plan
from app.services.tenant_context_service import get_tenant_context
from app.infra.database import get_db_session
from sqlalchemy import text

router = APIRouter(prefix="/plans", tags=["Plans"])


class PlanResponse(BaseModel):
    """Plan response model."""
    plan_id: str = Field(..., description="Unique plan identifier", example="550e8400-e29b-41d4-a716-446655440000")
    goal: str = Field(..., description="The goal this plan aims to achieve", example="Research and summarize the latest AI trends")
    steps: list = Field(..., description="List of plan steps with execution details")
    estimated_steps: int = Field(..., description="Estimated number of steps to complete", example=5)
    complexity: str = Field(..., description="Plan complexity level", example="medium")
    status: str = Field(..., description="Current plan status", example="executing")


class RefinePlanRequest(BaseModel):
    """Request to refine a plan based on execution results."""
    execution_results: list = Field(
        ..., 
        description="Results from executed steps",
        example=[
            {"step_number": 1, "tool_name": "search", "status": "success", "result": "Found 10 articles"}
        ]
    )
    current_step: int = Field(..., description="Current step number being executed", example=2)


@router.get("/{plan_id}", response_model=PlanResponse)
async def get_plan_details(
    plan_id: str,
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """
    Get plan details.
    
    Returns the plan structure, steps, and current status.
    """
    tenant_ctx = get_tenant_context(api_tenant_id)
    
    with get_db_session(api_tenant_id) as session:
        row = session.execute(
            text("""
                SELECT id, goal, plan_steps, status
                FROM agentic_plans
                WHERE id = :plan_id AND tenant_id = :tenant_id
            """),
            {"plan_id": plan_id, "tenant_id": api_tenant_id}
        ).fetchone()
        
        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Plan {plan_id} not found"
            )
        
        plan_steps = row.plan_steps if isinstance(row.plan_steps, list) else []
        
        return PlanResponse(
            plan_id=str(row.id),
            goal=row.goal,
            steps=plan_steps,
            estimated_steps=len(plan_steps),
            complexity="medium",  # Could be stored in plan
            status=row.status,
        )


@router.post("/{plan_id}/refine", response_model=PlanResponse)
async def refine_plan_endpoint(
    plan_id: str,
    request: RefinePlanRequest,
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """
    Refine a plan based on intermediate execution results.
    
    Updates the plan based on what has been executed so far,
    allowing for dynamic plan adjustment.
    """
    tenant_ctx = get_tenant_context(api_tenant_id)
    
    try:
        refined_plan = await refine_plan(
            tenant_ctx=tenant_ctx,
            plan_id=plan_id,
            execution_results=request.execution_results,
            current_step=request.current_step,
        )
        
        # Get updated plan details
        with get_db_session(api_tenant_id) as session:
            row = session.execute(
                text("""
                    SELECT id, goal, plan_steps, status
                    FROM agentic_plans
                    WHERE id = :plan_id AND tenant_id = :tenant_id
                """),
                {"plan_id": plan_id, "tenant_id": api_tenant_id}
            ).fetchone()
            
            if not row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Plan {plan_id} not found"
                )
            
            plan_steps = row.plan_steps if isinstance(row.plan_steps, list) else []
            
            return PlanResponse(
                plan_id=str(row.id),
                goal=row.goal,
                steps=plan_steps,
                estimated_steps=len(plan_steps),
                complexity="medium",
                status=row.status,
            )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to refine plan: {str(e)}"
        )

