"""Agentic planning service for generating multi-step plans from user goals."""

import json
import logging
import uuid
from typing import Dict, Any, List, Optional
from sqlalchemy import text
from app.models.tenant import TenantContext
from app.models.tool import ToolDefinition
from app.infra.database import get_db_session
from app.adapters.vendor_adapter_openai import call_openai_responses, build_openai_tools
from app.adapters.vendor_adapter_gemini import call_gemini
from app.infra.error_handler import retry_with_backoff
from app.services.cost_calculator import calculate_planning_cost
from app.services.agentic_reflector import get_similar_insights

logger = logging.getLogger(__name__)


PLANNING_PROMPT = """You are an AI planning assistant. Your task is to break down a user's goal into a structured, executable plan.

Given the user's goal and available tools, create a step-by-step plan that:
1. Breaks the goal into clear, actionable steps
2. Identifies which tools are needed for each step
3. Defines dependencies between steps (if any)
4. Specifies success criteria for each step

Available tools:
{tools_list}

User goal: {goal}

Respond with a JSON object in this exact format:
{{
    "steps": [
        {{
            "step_number": 1,
            "description": "Clear description of what this step does",
            "tool_name": "tool_name_here" or null if no tool needed,
            "tool_arguments": {{}} or null,
            "depends_on": [] (list of step numbers this step depends on),
            "success_criteria": "What indicates this step succeeded"
        }}
    ],
    "estimated_steps": <number of steps>,
    "complexity": "low" | "medium" | "high"
}}

Keep the plan focused and actionable. Each step should be specific and measurable."""


async def create_plan(
    tenant_ctx: TenantContext,
    goal: str,
    available_tools: List[ToolDefinition],
    conversation_id: Optional[str] = None,
    message_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Generate a multi-step plan from a user goal.
    
    Args:
        tenant_ctx: TenantContext with LLM configuration
        goal: User's goal/request
        available_tools: List of available tools
        conversation_id: Optional conversation ID
        message_id: Optional message ID
    
    Returns:
        Dict with plan_id, plan_steps, status, and metadata
    
    Raises:
        ValueError: If plan generation fails
    """
    try:
        # Get similar past insights if available
        similar_insights = await get_similar_insights(tenant_ctx, goal, limit=3)
        insights_context = ""
        if similar_insights:
            insights_context = "\n\nPAST SIMILAR TASKS AND OUTCOMES:\n"
            for insight in similar_insights[:2]:  # Use top 2
                insights_context += f"- Goal: {insight.get('goal', 'N/A')}\n"
                insights_context += f"  Outcome: {insight.get('insights', {}).get('final_outcome', 'N/A')}\n"
                if insight.get('recommendations', {}).get('suggestions'):
                    insights_context += f"  Suggestion: {insight['recommendations']['suggestions'][0]}\n"
            insights_context += "\nConsider these insights when creating your plan.\n"
        
        # Build tools list for prompt
        tools_list = []
        for tool in available_tools:
            tools_list.append(f"- {tool.name}: {tool.description}")
        tools_text = "\n".join(tools_list) if tools_list else "No tools available"
        
        # Build planning prompt
        planning_prompt = PLANNING_PROMPT.format(
            goal=goal,
            tools_list=tools_text
        ) + insights_context
        
        # Prepare messages for LLM
        messages = [
            {
                "role": "system",
                "content": "You are a planning assistant. Always respond with valid JSON only, no additional text."
            },
            {
                "role": "user",
                "content": planning_prompt
            }
        ]
        
        # Use a faster/cheaper model for planning if available
        planning_model = tenant_ctx.llm_model
        if tenant_ctx.llm_provider == "openai":
            # Use mini model for planning if main model is not mini
            if "mini" not in planning_model.lower():
                planning_model = "gpt-4o-mini"
        
        # Create a temporary tenant context for planning
        planning_ctx = TenantContext(
            tenant_id=tenant_ctx.tenant_id,
            llm_provider=tenant_ctx.llm_provider,
            llm_model=planning_model,
            allowed_tools=tenant_ctx.allowed_tools,
            kb_configs=tenant_ctx.kb_configs,
            mcp_configs=tenant_ctx.mcp_configs,
            prompt_profile={},  # No custom prompt for planning
            isolation_mode=tenant_ctx.isolation_mode,
            max_tool_steps=tenant_ctx.max_tool_steps,
            planning_enabled=tenant_ctx.planning_enabled,
            plan_timeout_seconds=tenant_ctx.plan_timeout_seconds,
        )
        
        # Call LLM for planning
        async def call_planning_llm():
            if planning_ctx.llm_provider == "openai":
                return await call_openai_responses(planning_ctx, messages, None, None)
            elif planning_ctx.llm_provider == "gemini":
                return await call_gemini(planning_ctx, messages, None, None)
            else:
                raise ValueError(f"Unsupported LLM provider for planning: {planning_ctx.llm_provider}")
        
        # Retry planning up to 2 times
        response = await retry_with_backoff(
            call_planning_llm,
            max_retries=2,
            initial_delay=1.0,
            max_delay=5.0,
        )
        
        # Extract plan from response
        plan_text = ""
        if planning_ctx.llm_provider == "openai":
            if response.get("choices"):
                plan_text = response["choices"][0].get("message", {}).get("content", "")
        elif planning_ctx.llm_provider == "gemini":
            if response.get("candidates"):
                plan_text = response["candidates"][0].get("content", {}).get("parts", [{}])[0].get("text", "")
        
        if not plan_text:
            raise ValueError("Empty response from planning LLM")
        
        # Parse JSON from response (may have markdown code blocks)
        plan_text = plan_text.strip()
        if plan_text.startswith("```"):
            # Extract JSON from code block
            lines = plan_text.split("\n")
            plan_text = "\n".join(lines[1:-1]) if len(lines) > 2 else plan_text
        
        try:
            plan_data = json.loads(plan_text)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse plan JSON: {plan_text[:200]}", exc_info=True)
            raise ValueError(f"Invalid JSON in plan response: {str(e)}")
        
        # Validate plan structure
        if "steps" not in plan_data or not isinstance(plan_data["steps"], list):
            raise ValueError("Plan must have a 'steps' array")
        
        # Validate and normalize steps
        validated_steps = []
        for step in plan_data["steps"]:
            if "step_number" not in step or "description" not in step:
                continue  # Skip invalid steps
            
            validated_step = {
                "step_number": int(step["step_number"]),
                "description": str(step["description"]),
                "tool_name": step.get("tool_name"),
                "tool_arguments": step.get("tool_arguments") or {},
                "depends_on": step.get("depends_on") or [],
                "success_criteria": step.get("success_criteria", ""),
                "status": "pending",
            }
            
            # Validate tool name if provided
            if validated_step["tool_name"]:
                tool_names = [t.name for t in available_tools]
                if validated_step["tool_name"] not in tool_names:
                    logger.warning(f"Tool {validated_step['tool_name']} not in available tools, setting to null")
                    validated_step["tool_name"] = None
            
            validated_steps.append(validated_step)
        
        if not validated_steps:
            raise ValueError("No valid steps in plan")
        
        # Store plan in database
        plan_id = str(uuid.uuid4())
        with get_db_session(tenant_ctx.tenant_id) as session:
            session.execute(
                text("""
                    INSERT INTO agentic_plans (
                        id, tenant_id, conversation_id, message_id,
                        goal, plan_steps, status
                    ) VALUES (
                        :id, :tenant_id, :conversation_id, :message_id,
                        :goal, CAST(:plan_steps AS jsonb), :status
                    )
                """),
                {
                    "id": plan_id,
                    "tenant_id": tenant_ctx.tenant_id,
                    "conversation_id": conversation_id,
                    "message_id": message_id,
                    "goal": goal,
                    "plan_steps": json.dumps(validated_steps),
                    "status": "draft",
                }
            )
            session.commit()
        
        return {
            "plan_id": plan_id,
            "goal": goal,
            "steps": validated_steps,
            "estimated_steps": plan_data.get("estimated_steps", len(validated_steps)),
            "complexity": plan_data.get("complexity", "medium"),
            "status": "draft",
        }
        
    except Exception as e:
        logger.error(f"Failed to create plan: {str(e)}", exc_info=True)
        raise ValueError(f"Plan generation failed: {str(e)}")


async def refine_plan(
    tenant_ctx: TenantContext,
    plan_id: str,
    execution_results: List[Dict[str, Any]],
    current_step: int,
) -> Dict[str, Any]:
    """
    Refine a plan based on intermediate execution results.
    
    Args:
        tenant_ctx: TenantContext
        plan_id: Plan ID to refine
        execution_results: Results from executed steps
        current_step: Current step number
    
    Returns:
        Updated plan with refined steps
    """
    # Load current plan
    with get_db_session(tenant_ctx.tenant_id) as session:
        plan_row = session.execute(
            text("""
                SELECT plan_steps, goal
                FROM agentic_plans
                WHERE id = :plan_id AND tenant_id = :tenant_id
            """),
            {"plan_id": plan_id, "tenant_id": tenant_ctx.tenant_id}
        ).fetchone()
        
        if not plan_row:
            raise ValueError(f"Plan {plan_id} not found")
        
        plan_steps = plan_row.plan_steps
        goal = plan_row.goal
    
    # For now, simple refinement: mark completed steps and update remaining
    # Future: Use LLM to intelligently refine based on results
    updated_steps = []
    for step in plan_steps:
        step_num = step.get("step_number", 0)
        if step_num < current_step:
            step["status"] = "completed"
        elif step_num == current_step:
            step["status"] = "executing"
        else:
            step["status"] = "pending"
        updated_steps.append(step)
    
    # Update plan in database
    with get_db_session(tenant_ctx.tenant_id) as session:
        session.execute(
            text("""
                UPDATE agentic_plans
                SET plan_steps = CAST(:plan_steps AS jsonb),
                    updated_at = now()
                WHERE id = :plan_id AND tenant_id = :tenant_id
            """),
            {
                "plan_id": plan_id,
                "tenant_id": tenant_ctx.tenant_id,
                "plan_steps": json.dumps(updated_steps),
            }
        )
        session.commit()
    
    return {
        "plan_id": plan_id,
        "steps": updated_steps,
        "current_step": current_step,
    }

