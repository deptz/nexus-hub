"""Tool mapping service - maps abstract tools to provider-specific tools."""

from typing import List, Dict, Any, Optional
from app.infra.config import config


# Mapping of abstract tools to provider tools
ABSTRACT_TO_PROVIDER_TOOLS = {
    "file_search": {
        "openai_file": "openai_file_search",
        "gemini_file": "gemini_file_search",
        "internal_rag": "internal_rag_search",
    }
}


def get_provider_tools_for_abstract(abstract_tool_name: str) -> List[str]:
    """
    Get list of provider-specific tools for an abstract tool.
    
    Args:
        abstract_tool_name: Abstract tool name (e.g., "file_search")
    
    Returns:
        List of provider tool names that should be enabled
    """
    if abstract_tool_name not in ABSTRACT_TO_PROVIDER_TOOLS:
        return []
    
    provider_mapping = ABSTRACT_TO_PROVIDER_TOOLS[abstract_tool_name]
    enabled_tools = []
    
    # Check which providers are available based on API keys
    if config.OPENAI_API_KEY and "openai_file" in provider_mapping:
        enabled_tools.append(provider_mapping["openai_file"])
    
    if config.GEMINI_API_KEY and "gemini_file" in provider_mapping:
        enabled_tools.append(provider_mapping["gemini_file"])
    
    # Always include internal_rag (our database)
    if "internal_rag" in provider_mapping:
        enabled_tools.append(provider_mapping["internal_rag"])
    
    return enabled_tools


def is_internal_tool(tool_name: str) -> bool:
    """
    Check if a tool is internal (deprecated from user-facing API).
    
    Args:
        tool_name: Tool name to check
    
    Returns:
        True if tool is internal-only
    """
    internal_tools = ["openai_file_search", "gemini_file_search"]
    return tool_name in internal_tools


def is_abstract_tool(tool_name: str) -> bool:
    """
    Check if a tool is an abstract tool.
    
    Args:
        tool_name: Tool name to check
    
    Returns:
        True if tool is abstract
    """
    return tool_name in ABSTRACT_TO_PROVIDER_TOOLS


def get_provider_from_tool_name(tool_name: str) -> Optional[str]:
    """
    Get provider name from tool name.
    
    Args:
        tool_name: Tool name (e.g., "openai_file_search")
    
    Returns:
        Provider name (e.g., "openai_file") or None
    """
    if tool_name == "openai_file_search":
        return "openai_file"
    elif tool_name == "gemini_file_search":
        return "gemini_file"
    elif tool_name == "internal_rag_search":
        return "internal_rag"
    return None


def get_provider_tool_name(provider: str) -> Optional[str]:
    """
    Get provider-specific tool name from provider.
    
    Args:
        provider: Provider name (e.g., "openai_file")
    
    Returns:
        Tool name (e.g., "openai_file_search") or None
    """
    mapping = {
        "openai_file": "openai_file_search",
        "gemini_file": "gemini_file_search",
        "internal_rag": "internal_rag_search",
    }
    return mapping.get(provider)

