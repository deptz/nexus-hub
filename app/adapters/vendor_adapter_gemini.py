"""Gemini vendor adapter for File Search."""

import json
from typing import List, Dict, Any, Optional
import google.generativeai as genai
from app.models.tenant import TenantContext
from app.models.tool import ToolDefinition
from app.infra.config import config


class GeminiFileClient:
    """Client for Gemini file search."""
    
    def __init__(self):
        self._configured = False
    
    def _ensure_configured(self):
        """Ensure Gemini is configured."""
        if not self._configured:
            if not config.GEMINI_API_KEY:
                raise ValueError("GEMINI_API_KEY not configured")
            genai.configure(api_key=config.GEMINI_API_KEY)
            self._configured = True
    
    async def search(
        self,
        tenant_ctx: TenantContext,
        tool_def: ToolDefinition,
        args: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Search using Gemini file search via File Search Store.
        
        Note: Gemini file search is done through the GenerativeModel API
        with file search tool configured. For direct search, we return a structured
        response indicating the search should be done via the main API.
        """
        self._ensure_configured()
        
        file_search_store_name = tool_def.implementation_ref.get("file_search_store_name")
        if not file_search_store_name:
            # Try to get from KB configs
            kb_name = args.get("kb_name") or tool_def.implementation_ref.get("kb_name")
            if kb_name and kb_name in tenant_ctx.kb_configs:
                kb_config = tenant_ctx.kb_configs[kb_name]
                file_search_store_name = kb_config.get("provider_config", {}).get("file_search_store_name")
        
        if not file_search_store_name:
            return {
                "results": [],
                "error": "No file_search_store_name configured for this tool",
            }
        
        # Gemini file search results come back as part of the chat response
        # when file search tool is configured
        return {
            "results": [
                {
                    "content": "File search results are returned via GenerativeModel API with file search tool configured.",
                    "metadata": {"file_search_store_name": file_search_store_name, "source": "gemini_file"},
                }
            ],
        }


gemini_file_client = GeminiFileClient()


async def call_gemini(
    tenant_ctx: TenantContext,
    messages: List[Dict[str, Any]],
    tools: List[ToolDefinition],
    file_search_store_names: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Call Gemini API with messages and file search support.
    
    Args:
        tenant_ctx: TenantContext
        messages: List of message dicts (converted to Gemini format)
        tools: List of canonical ToolDefinition objects (not used for file search)
        file_search_store_names: Optional list of File Search Store names for file search
    
    Returns:
        Gemini API response with standardized format
    """
    if not config.GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY not configured")
    
    genai.configure(api_key=config.GEMINI_API_KEY)
    
    # Convert messages to Gemini format
    # Gemini uses Content objects with role and parts
    gemini_contents = []
    system_parts = []
    
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content", "")
        
        if role == "system":
            # Collect system messages to prepend to first user message
            system_parts.append(content)
        elif role == "user":
            # Prepend all system messages to first user message
            if system_parts:
                combined_content = "\n\n".join(system_parts) + "\n\n" + content
                system_parts = []  # Clear after using
            else:
                combined_content = content
            gemini_contents.append({"role": "user", "parts": [{"text": combined_content}]})
        elif role == "assistant":
            gemini_contents.append({"role": "model", "parts": [{"text": content}]})
        elif role == "tool":
            # Gemini handles tool responses differently
            # For now, we'll add as text in user message
            tool_content = f"Tool result: {content}"
            gemini_contents.append({"role": "user", "parts": [{"text": tool_content}]})
    
    try:
        import logging
        import httpx
        logger = logging.getLogger("app.adapters.gemini")
        
        # Build tools array - only file search, no function calling
        gemini_tools = []
        
        # Add file search tool if stores are provided
        if file_search_store_names:
            logger.info(f"Gemini file_search: Using File Search Stores: {file_search_store_names}")
            gemini_tools.append({
                "file_search": {
                    "file_search_store_names": file_search_store_names
                }
            })
        
        # Use REST API for file search support
        # The google-generativeai SDK may not fully support file search stores yet
        # So we'll use REST API directly
        model_name = tenant_ctx.llm_model
        
        # Build request payload
        payload = {
            "contents": gemini_contents,
        }
        
        # Add tools if file search is enabled
        if gemini_tools:
            payload["tools"] = gemini_tools
        
        # Call REST API
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": config.GEMINI_API_KEY,
        }
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            result = response.json()
        
        # Extract response data
        if not result.get("candidates"):
            raise ValueError("No response from Gemini")
        
        candidate = result["candidates"][0]
        content = candidate.get("content", {})
        parts = content.get("parts", [])
        
        # Extract text
        text_parts = []
        for part in parts:
            if isinstance(part, dict) and "text" in part:
                text_parts.append(part["text"])
        
        # Extract grounding metadata for citations
        grounding_metadata = candidate.get("groundingMetadata") or candidate.get("grounding_metadata")
        
        # Extract usage metadata
        usage_metadata = result.get("usageMetadata") or result.get("usage_metadata", {})
        
        # Convert to standardized format
        standardized_result = {
            "candidates": [
                {
                    "index": 0,
                    "content": {
                        "parts": [
                            {"text": " ".join(text_parts)} if text_parts else {"text": ""}
                        ],
                        "function_calls": None,  # File search only, no function calling
                    },
                    "finish_reason": candidate.get("finishReason") or candidate.get("finish_reason"),
                    "grounding_metadata": grounding_metadata,  # Include citations
                }
            ],
            "usage_metadata": usage_metadata,
        }
        
        return standardized_result
        
    except Exception as e:
        from app.infra.error_handler import wrap_llm_error
        raise wrap_llm_error(e, "gemini")

