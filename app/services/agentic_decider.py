"""Agentic decision framework for making informed decisions with confidence scoring."""

import logging
from typing import Dict, Any, List, Optional
from app.models.tenant import TenantContext

logger = logging.getLogger(__name__)


async def make_decision(
    tenant_ctx: TenantContext,
    context: Dict[str, Any],
    options: List[Dict[str, Any]],
    constraints: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Make an informed decision with confidence scoring.
    
    Args:
        tenant_ctx: TenantContext
        context: Current context/situation
        options: List of decision options, each with:
            - name: Option name
            - description: Option description
            - expected_outcome: Expected outcome
            - risks: List of risks
        constraints: Optional list of constraints to consider
    
    Returns:
        Dict with:
            - decision: Selected option
            - confidence: Confidence score (0.0-1.0)
            - reasoning: Explanation
            - alternatives: Other considered options
    """
    if not options:
        raise ValueError("No options provided for decision")
    
    # Simple decision logic: evaluate each option
    # Future: Use LLM for more sophisticated decision making
    scored_options = []
    for option in options:
        score = 0.5  # Base score
        
        # Adjust score based on risks
        risks = option.get("risks", [])
        if not risks:
            score += 0.2  # Lower risk = higher score
        
        # Adjust score based on expected outcome
        expected_outcome = option.get("expected_outcome", "")
        if "success" in expected_outcome.lower() or "positive" in expected_outcome.lower():
            score += 0.2
        
        # Check constraints
        if constraints:
            constraint_violations = 0
            for constraint in constraints:
                if constraint.get("type") == "must_have":
                    required = constraint.get("value")
                    if required not in option.get("description", "").lower():
                        constraint_violations += 1
            
            if constraint_violations > 0:
                score -= constraint_violations * 0.3
        
        score = max(0.0, min(1.0, score))  # Clamp to 0-1
        scored_options.append({
            "option": option,
            "score": score,
        })
    
    # Sort by score (highest first)
    scored_options.sort(key=lambda x: x["score"], reverse=True)
    
    best_option = scored_options[0]
    confidence = best_option["score"]
    
    return {
        "decision": best_option["option"],
        "confidence": confidence,
        "reasoning": f"Selected '{best_option['option'].get('name')}' with confidence {confidence:.2f} based on risk assessment and constraints",
        "alternatives": [opt["option"] for opt in scored_options[1:3]],  # Top 2 alternatives
        "all_scores": {opt["option"]["name"]: opt["score"] for opt in scored_options},
    }

