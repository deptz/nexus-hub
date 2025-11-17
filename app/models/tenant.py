"""Tenant context model for runtime tenant configuration."""

from dataclasses import dataclass
from typing import List, Dict, Any


@dataclass
class TenantContext:
    """Runtime context for a tenant with all configuration loaded."""
    tenant_id: str
    llm_provider: str  # "openai" | "gemini"
    llm_model: str  # e.g. "gpt-4.1-mini" / "gemini-2.5-pro"
    allowed_tools: List[str]  # canonical tool names
    kb_configs: Dict[str, Any]  # logical_kb_name -> config
    mcp_configs: Dict[str, Any]  # server_id -> config
    prompt_profile: Dict[str, Any]  # tenant prompt & language prefs
    isolation_mode: str  # "shared_db" | "dedicated_db"

