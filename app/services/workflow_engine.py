"""Workflow engine for multi-step workflow orchestration."""

import asyncio
import logging
from typing import Dict, Any, List, Optional
from app.models.tenant import TenantContext
from app.services.tool_execution_engine import execute_tool_call
from app.services.tool_registry import get_allowed_tools
from app.services.agentic_decider import make_decision

logger = logging.getLogger(__name__)

MAX_PARALLEL_TOOLS = 5


async def execute_workflow(
    tenant_ctx: TenantContext,
    workflow_def: Dict[str, Any],
    initial_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Execute a multi-step workflow with conditional branching and parallel execution.
    
    Args:
        tenant_ctx: TenantContext
        workflow_def: Workflow definition with:
            - steps: List of workflow steps
            - conditions: Optional conditional branching logic
        initial_context: Optional initial context
    
    Returns:
        Dict with execution results
    """
    context = initial_context or {}
    results = []
    step_results = {}
    
    steps = workflow_def.get("steps", [])
    if not steps:
        raise ValueError("Workflow must have at least one step")
    
    # Get available tools
    tools = get_allowed_tools(tenant_ctx)
    tool_map = {t.name: t for t in tools}
    
    i = 0
    while i < len(steps):
        step = steps[i]
        step_type = step.get("type", "tool")
        step_name = step.get("name", f"step_{i}")
        
        try:
            if step_type == "tool":
                # Execute tool step
                tool_name = step.get("tool_name")
                tool_args = step.get("tool_args", {})
                
                if tool_name not in tool_map:
                    raise ValueError(f"Tool {tool_name} not available")
                
                tool_def = tool_map[tool_name]
                result = await execute_tool_call(tenant_ctx, tool_def, tool_args)
                
                step_results[step_name] = result
                results.append({
                    "step": step_name,
                    "type": "tool",
                    "status": "success",
                    "result": result,
                })
                
                # Update context with result
                context[step_name] = result
            
            elif step_type == "condition":
                # Conditional branching
                condition = step.get("condition", {})
                condition_type = condition.get("type", "equals")
                field = condition.get("field")
                value = condition.get("value")
                
                # Evaluate condition
                condition_met = False
                if condition_type == "equals":
                    condition_met = context.get(field) == value
                elif condition_type == "not_equals":
                    condition_met = context.get(field) != value
                elif condition_type == "exists":
                    condition_met = field in context
                
                # Branch based on condition
                if condition_met:
                    # Go to true branch
                    next_step = step.get("true_step")
                    if next_step:
                        # Find step index by name
                        for idx, s in enumerate(steps):
                            if s.get("name") == next_step:
                                i = idx - 1  # Will be incremented
                                break
                else:
                    # Go to false branch
                    next_step = step.get("false_step")
                    if next_step:
                        for idx, s in enumerate(steps):
                            if s.get("name") == next_step:
                                i = idx - 1
                                break
                
                results.append({
                    "step": step_name,
                    "type": "condition",
                    "status": "success",
                    "condition_met": condition_met,
                })
            
            elif step_type == "parallel":
                # Parallel execution
                parallel_steps = step.get("steps", [])
                if len(parallel_steps) > MAX_PARALLEL_TOOLS:
                    parallel_steps = parallel_steps[:MAX_PARALLEL_TOOLS]
                
                # Execute steps in parallel
                tasks = []
                for p_step in parallel_steps:
                    p_tool_name = p_step.get("tool_name")
                    p_tool_args = p_step.get("tool_args", {})
                    
                    if p_tool_name in tool_map:
                        p_tool_def = tool_map[p_tool_name]
                        tasks.append(execute_tool_call(tenant_ctx, p_tool_def, p_tool_args))
                
                if tasks:
                    parallel_results = await asyncio.gather(*tasks, return_exceptions=True)
                    
                    for idx, result in enumerate(parallel_results):
                        p_step_name = parallel_steps[idx].get("name", f"parallel_{idx}")
                        if isinstance(result, Exception):
                            step_results[p_step_name] = {"error": str(result)}
                            results.append({
                                "step": p_step_name,
                                "type": "tool",
                                "status": "failure",
                                "error": str(result),
                            })
                        else:
                            step_results[p_step_name] = result
                            context[p_step_name] = result
                            results.append({
                                "step": p_step_name,
                                "type": "tool",
                                "status": "success",
                                "result": result,
                            })
            
            elif step_type == "decision":
                # Decision point
                options = step.get("options", [])
                constraints = step.get("constraints", [])
                
                decision = await make_decision(tenant_ctx, context, options, constraints)
                
                step_results[step_name] = decision
                context[step_name] = decision
                results.append({
                    "step": step_name,
                    "type": "decision",
                    "status": "success",
                    "decision": decision,
                })
            
            i += 1
            
        except Exception as e:
            logger.error(f"Workflow step {step_name} failed: {str(e)}", exc_info=True)
            results.append({
                "step": step_name,
                "type": step_type,
                "status": "failure",
                "error": str(e),
            })
            
            # Check if workflow should continue on error
            if not step.get("continue_on_error", False):
                break
            
            i += 1
    
    return {
        "status": "completed" if all(r.get("status") == "success" for r in results) else "partial",
        "results": results,
        "step_results": step_results,
        "final_context": context,
    }

