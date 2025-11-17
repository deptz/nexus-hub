"""Cost calculation for LLM API calls."""

from typing import Dict, Any, Optional


# Pricing per 1M tokens (as of 2025-01, adjust as needed)
PRICING = {
    "openai": {
        "gpt-4o": {"input": 2.50, "output": 10.00},
        "gpt-4o-mini": {"input": 0.15, "output": 0.60},
        "gpt-4-turbo": {"input": 10.00, "output": 30.00},
        "gpt-4": {"input": 30.00, "output": 60.00},
        "gpt-3.5-turbo": {"input": 0.50, "output": 1.50},
        # Default fallback
        "default": {"input": 0.50, "output": 1.50},
    },
    "gemini": {
        "gemini-2.0-flash-exp": {"input": 0.00, "output": 0.00},  # Free tier
        "gemini-1.5-pro": {"input": 1.25, "output": 5.00},
        "gemini-1.5-flash": {"input": 0.075, "output": 0.30},
        # Default fallback
        "default": {"input": 0.50, "output": 1.50},
    },
}


def calculate_llm_cost(
    provider: str,
    model: str,
    prompt_tokens: Optional[int] = None,
    completion_tokens: Optional[int] = None,
    total_tokens: Optional[int] = None,
) -> float:
    """
    Calculate cost for LLM API call.
    
    Args:
        provider: 'openai' or 'gemini'
        model: Model name
        prompt_tokens: Input tokens
        completion_tokens: Output tokens
        total_tokens: Total tokens (if prompt/completion not available)
    
    Returns:
        Cost in USD
    """
    provider_pricing = PRICING.get(provider, {})
    model_pricing = provider_pricing.get(model, provider_pricing.get("default", {"input": 0.50, "output": 1.50}))
    
    if prompt_tokens is not None and completion_tokens is not None:
        input_cost = (prompt_tokens / 1_000_000) * model_pricing["input"]
        output_cost = (completion_tokens / 1_000_000) * model_pricing["output"]
        return input_cost + output_cost
    elif total_tokens is not None:
        # Estimate: 70% input, 30% output (rough approximation)
        input_tokens = int(total_tokens * 0.7)
        output_tokens = int(total_tokens * 0.3)
        input_cost = (input_tokens / 1_000_000) * model_pricing["input"]
        output_cost = (output_tokens / 1_000_000) * model_pricing["output"]
        return input_cost + output_cost
    
    return 0.0


def calculate_tool_cost(
    provider: str,
    tool_name: str,
    latency_ms: Optional[int] = None,
) -> float:
    """
    Calculate cost for tool execution.
    
    Most tools are free, but some may have costs (e.g., external API calls).
    For now, return 0.0 for most tools.
    
    Args:
        provider: Tool provider
        tool_name: Tool name
        latency_ms: Execution latency
    
    Returns:
        Cost in USD
    """
    # Most tools are free
    # Add pricing for specific tools if needed
    return 0.0

