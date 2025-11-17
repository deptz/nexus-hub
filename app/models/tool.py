"""Canonical tool definition model."""

from pydantic import BaseModel, Field
from typing import Dict, Any


class ToolDefinition(BaseModel):
    """Canonical tool definition that abstracts provider-specific implementations."""
    name: str = Field(..., description="Canonical tool name")
    description: str = Field(..., description="Tool description")
    parameters_schema: Dict[str, Any] = Field(..., description="JSON Schema for parameters")
    provider: str = Field(
        ...,
        description="Provider: 'internal_rag' | 'openai_file' | 'gemini_file' | 'mcp' | 'custom_http'"
    )
    implementation_ref: Dict[str, Any] = Field(
        ...,
        description="Provider-specific config: e.g. {'vector_store_id': '...'} or {'mcp_server_id': '...', 'mcp_tool_name': '...'}"
    )

