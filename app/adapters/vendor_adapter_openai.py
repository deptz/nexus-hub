"""OpenAI vendor adapter for Responses API with file search."""

import json
import uuid
import logging
from typing import List, Dict, Any, Optional
from openai import OpenAI, AsyncOpenAI
from app.models.tenant import TenantContext
from app.models.tool import ToolDefinition
from app.infra.config import config


class OpenAIFileClient:
    """Client for OpenAI file search."""
    
    def __init__(self):
        self._client = None
    
    @property
    def client(self):
        """Lazy initialization of OpenAI client."""
        if self._client is None:
            if not config.OPENAI_API_KEY:
                raise ValueError("OPENAI_API_KEY not configured")
            self._client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
        return self._client
    
    async def search(
        self,
        tenant_ctx: TenantContext,
        tool_def: ToolDefinition,
        args: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Search using OpenAI file search via vector store.
        
        Note: OpenAI file search is typically done through the chat completions API
        with a vector_store_id attached to the assistant. For direct search,
        we use the vector store search API if available, or return a structured
        response indicating the search should be done via chat completions.
        """
        vector_store_id = tool_def.implementation_ref.get("vector_store_id")
        if not vector_store_id:
            # Try to get from KB configs
            kb_name = args.get("kb_name") or tool_def.implementation_ref.get("kb_name")
            if kb_name and kb_name in tenant_ctx.kb_configs:
                kb_config = tenant_ctx.kb_configs[kb_name]
                vector_store_id = kb_config.get("provider_config", {}).get("vector_store_id")
        
        if not vector_store_id:
            return {
                "results": [],
                "error": "No vector_store_id configured for this tool",
            }
        
        # OpenAI file search is typically done through chat completions with
        # vector_store attached. For now, we return a structured response indicating
        # the search should be done via the main chat API.
        # In practice, file search results come back as part of the chat response.
        return {
            "results": [
                {
                    "content": "File search results are returned via chat completions API with vector_store_id attached.",
                    "metadata": {"vector_store_id": vector_store_id, "source": "openai_file"},
                }
            ],
        }


openai_file_client = OpenAIFileClient()


def extract_annotations(response_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extract annotations from Responses API response.
    
    Annotations contain file citations and metadata when file_search is used.
    
    Responses API structure:
    {
        "output": [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": "...",
                        "annotations": [
                            {
                                "type": "file_citation",
                                "file_id": "...",
                                "filename": "...",
                                "index": 123
                            }
                        ]
                    }
                ]
            }
        ]
    }
    
    Args:
        response_data: Response data from Responses API (dict or object)
    
    Returns:
        List of annotation dicts with file citations and metadata
    """
    annotations = []
    
    # Handle dict format (from REST API)
    if isinstance(response_data, dict):
        output = response_data.get('output', [])
        
        if isinstance(output, list):
            for item in output:
                if isinstance(item, dict):
                    # Look for message type items
                    if item.get('type') == 'message':
                        content = item.get('content', [])
                        if isinstance(content, list):
                            for content_item in content:
                                if isinstance(content_item, dict):
                                    # Check for annotations in output_text content items
                                    if content_item.get('type') == 'output_text':
                                        if 'annotations' in content_item:
                                            for ann in content_item['annotations']:
                                                annotation = _parse_annotation(ann)
                                                if annotation:
                                                    annotations.append(annotation)
                    
                    # Legacy: Check for annotations at item level (for backward compatibility)
                    elif 'annotations' in item:
                        for ann in item['annotations']:
                            annotation = _parse_annotation(ann)
                            if annotation:
                                annotations.append(annotation)
                    
                    # Legacy: Check for annotations in text content (for backward compatibility)
                    elif 'text' in item and isinstance(item['text'], dict):
                        if 'annotations' in item['text']:
                            for ann in item['text']['annotations']:
                                annotation = _parse_annotation(ann)
                                if annotation:
                                    annotations.append(annotation)
    
    # Handle object format (from SDK)
    elif hasattr(response_data, 'output'):
        output = response_data.output
        if isinstance(output, list):
            for item in output:
                # Check if it's a message type
                if hasattr(item, 'type') and item.type == 'message':
                    if hasattr(item, 'content'):
                        content = item.content
                        if isinstance(content, list):
                            for content_item in content:
                                if hasattr(content_item, 'type') and content_item.type == 'output_text':
                                    if hasattr(content_item, 'annotations'):
                                        for ann in content_item.annotations:
                                            annotation = _parse_annotation(ann)
                                            if annotation:
                                                annotations.append(annotation)
                # Legacy support
                elif hasattr(item, 'annotations'):
                    for ann in item.annotations:
                        annotation = _parse_annotation(ann)
                        if annotation:
                            annotations.append(annotation)
                elif isinstance(item, dict) and 'annotations' in item:
                    for ann in item['annotations']:
                        annotation = _parse_annotation(ann)
                        if annotation:
                            annotations.append(annotation)
    
    return annotations


def _parse_annotation(ann: Any) -> Optional[Dict[str, Any]]:
    """
    Parse a single annotation object into standardized format.
    
    Responses API annotation format:
    {
        "type": "file_citation",
        "file_id": "file-abc123",
        "filename": "return_policy.txt",
        "index": 169
    }
    
    Args:
        ann: Annotation object (dict or object)
    
    Returns:
        Parsed annotation dict or None if invalid
    """
    try:
        # Handle dict format
        if isinstance(ann, dict):
            annotation = {
                "type": ann.get('type'),
                "text": ann.get('text'),  # May not be present in Responses API format
                "start_index": ann.get('start_index'),
                "end_index": ann.get('end_index'),
                "index": ann.get('index'),  # Responses API uses 'index' instead of start_index/end_index
            }
            
            # Check if it's Responses API format (file_id directly in annotation)
            if ann.get('type') == 'file_citation' and 'file_id' in ann:
                # Responses API format: file_citation has file_id and filename directly
                annotation['file_citation'] = {
                    "file_id": ann.get('file_id'),
                    "quote": ann.get('quote'),  # May not be present
                    "filename": ann.get('filename'),  # Responses API includes filename
                }
                # Use index if start_index/end_index not available
                if annotation.get('index') is not None and annotation.get('start_index') is None:
                    annotation['start_index'] = annotation['index']
                    annotation['end_index'] = annotation['index'] + 1
            
            # Legacy format: file_citation is nested
            elif 'file_citation' in ann:
                file_citation = ann['file_citation']
                if isinstance(file_citation, dict):
                    annotation['file_citation'] = {
                        "file_id": file_citation.get('file_id'),
                        "quote": file_citation.get('quote'),
                        "filename": file_citation.get('filename'),
                    }
                else:
                    # Handle object format
                    annotation['file_citation'] = {
                        "file_id": getattr(file_citation, 'file_id', None),
                        "quote": getattr(file_citation, 'quote', None),
                        "filename": getattr(file_citation, 'filename', None),
                    }
            
            # Extract file path if present
            if 'file_path' in ann:
                file_path = ann['file_path']
                if isinstance(file_path, dict):
                    annotation['file_path'] = {
                        "file_id": file_path.get('file_id'),
                    }
                else:
                    annotation['file_path'] = {
                        "file_id": getattr(file_path, 'file_id', None),
                    }
            
            return annotation if annotation.get('type') else None
        
        # Handle object format
        elif hasattr(ann, 'type'):
            annotation = {
                "type": getattr(ann, 'type', None),
                "text": getattr(ann, 'text', None),
                "start_index": getattr(ann, 'start_index', None),
                "end_index": getattr(ann, 'end_index', None),
                "index": getattr(ann, 'index', None),
            }
            
            # Responses API format
            if getattr(ann, 'type', None) == 'file_citation':
                annotation['file_citation'] = {
                    "file_id": getattr(ann, 'file_id', None),
                    "quote": getattr(ann, 'quote', None),
                    "filename": getattr(ann, 'filename', None),
                }
                if annotation.get('index') is not None and annotation.get('start_index') is None:
                    annotation['start_index'] = annotation['index']
                    annotation['end_index'] = annotation['index'] + 1
            
            elif hasattr(ann, 'file_citation'):
                file_citation = ann.file_citation
                annotation['file_citation'] = {
                    "file_id": getattr(file_citation, 'file_id', None),
                    "quote": getattr(file_citation, 'quote', None),
                    "filename": getattr(file_citation, 'filename', None),
                }
            
            if hasattr(ann, 'file_path'):
                file_path = ann.file_path
                annotation['file_path'] = {
                    "file_id": getattr(file_path, 'file_id', None),
                }
            
            return annotation if annotation.get('type') else None
        
    except Exception as e:
        logger = logging.getLogger("app.adapters.openai")
        logger.warning(f"Error parsing annotation: {e}", exc_info=True)
        return None
    
    return None


def build_openai_tools(tools: List[ToolDefinition]) -> List[Dict[str, Any]]:
    """
    Convert canonical ToolDefinition objects to OpenAI tool schema.
    
    Args:
        tools: List of canonical ToolDefinition objects
    
    Returns:
        List of OpenAI tool dicts in OpenAI format
    """
    openai_tools = []
    for tool in tools:
        openai_tool = {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters_schema or {},
            }
        }
        openai_tools.append(openai_tool)
    return openai_tools


async def call_openai_responses(
    tenant_ctx: TenantContext,
    messages: List[Dict[str, Any]],
    tools: List[ToolDefinition],
    vector_store_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Call OpenAI Responses API or Chat Completions with messages and tools.
    Uses Responses API when vector_store_ids are provided for file_search.
    
    Args:
        tenant_ctx: TenantContext
        messages: List of message dicts
        tools: List of canonical ToolDefinition objects
        vector_store_ids: Optional list of vector store IDs for file search
    
    Returns:
        OpenAI API response with standardized format
    """
    if not config.OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY not configured")
    
    # Convert tools to OpenAI format
    openai_tools = build_openai_tools(tools) if tools else None
    
    try:
        client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
        
        # If vector stores are provided, use Responses API for file_search support
        if vector_store_ids:
            logger = logging.getLogger("app.adapters.openai")
            logger.info(f"Vector store IDs provided: {vector_store_ids}, will use Responses API")
            # Convert messages to input format (Responses API uses "input" instead of "messages")
            input_items = []
            for msg in messages:
                role = msg.get("role")
                content = msg.get("content", "")
                if role in ["system", "user", "assistant"]:
                    input_items.append({
                        "role": role,
                        "content": content
                    })
            
            # Build tools array with file_search
            # Based on errors: API doesn't want nested 'file_search' object
            # Try: just type and vector_store_ids at tool level
            file_search_tool = {
                "type": "file_search",
                "vector_store_ids": vector_store_ids
            }
            response_tools = [file_search_tool]
            if openai_tools:
                # For Responses API, function tools need a top-level 'name' field
                # Copy name from function.name to top level
                for tool in openai_tools:
                    if tool.get("type") == "function" and "function" in tool:
                        tool["name"] = tool["function"].get("name")
                response_tools.extend(openai_tools)
            
            # Use Responses API with file_search
            try:
                import httpx
                logger = logging.getLogger("app.adapters.openai")
                logger.info(f"Calling Responses API with model={tenant_ctx.llm_model}, vector_store_ids={vector_store_ids}")
                
                # Try REST API directly with vector_store_ids embedded in file_search tool
                headers = {
                    "Authorization": f"Bearer {config.OPENAI_API_KEY}",
                    "Content-Type": "application/json"
                }
                
                payload = {
                    "model": tenant_ctx.llm_model,
                    "input": input_items,
                    "tools": response_tools,
                    "tool_choice": "auto"
                }
                
                async with httpx.AsyncClient(timeout=60.0) as http_client:
                    rest_response = await http_client.post(
                        "https://api.openai.com/v1/responses",
                        headers=headers,
                        json=payload
                    )
                    
                    if rest_response.status_code == 200:
                        result_data = rest_response.json()
                        logger.info(f"REST API call successful, response keys: {list(result_data.keys())}")
                        
                        # Convert REST API response to match SDK response object structure
                        # Create a simple object-like structure
                        class ResponseObj:
                            def __init__(self, data):
                                self._data = data
                                for key, value in data.items():
                                    setattr(self, key, value)
                        
                        response_obj = ResponseObj(result_data)
                    else:
                        error_text = rest_response.text
                        logger.warning(f"REST API call failed ({rest_response.status_code}): {error_text}")
                        raise ValueError(f"Responses API error ({rest_response.status_code}): {error_text}")
                
                logger.info(f"Responses API response type: {type(response_obj)}, has output: {hasattr(response_obj, 'output')}")
                
                # Convert Responses API format to standardized format
                # Responses API returns a different structure than Chat Completions
                text_content = ""
                tool_calls = []
                annotations = []
                
                # Handle response - could be dict (from REST) or object (from SDK)
                response_data = response_obj._data if hasattr(response_obj, '_data') else response_obj
                if isinstance(response_data, dict):
                    # REST API response format
                    output = response_data.get('output', [])
                    if isinstance(output, list) and len(output) > 0:
                        # Output is a list of items (file_search_call, message, etc.)
                        for item in output:
                            if isinstance(item, dict):
                                # Responses API format: message type has content array
                                if item.get('type') == 'message':
                                    content = item.get('content', [])
                                    if isinstance(content, list):
                                        for content_item in content:
                                            if isinstance(content_item, dict):
                                                # output_text type has the actual text
                                                if content_item.get('type') == 'output_text':
                                                    text = content_item.get('text', '')
                                                    if text:
                                                        text_content += text
                                
                                # Legacy: Check for text content directly
                                elif 'text' in item:
                                    # Handle both string and dict text formats
                                    if isinstance(item['text'], str):
                                        text_content += item['text']
                                    elif isinstance(item['text'], dict):
                                        # Text might be a dict with value and annotations
                                        if 'value' in item['text']:
                                            text_content += item['text']['value']
                                        elif 'content' in item['text']:
                                            text_content += item['text']['content']
                                
                                # Legacy: Check for content field
                                elif 'content' in item and not item.get('type') == 'message':
                                    if isinstance(item['content'], list):
                                        for content_item in item['content']:
                                            if isinstance(content_item, dict) and 'text' in content_item:
                                                text_content += content_item['text']
                                    elif isinstance(item['content'], str):
                                        text_content += item['content']
                    elif isinstance(output, str):
                        text_content = output
                    
                    # Extract annotations from response
                    try:
                        annotations = extract_annotations(response_data)
                        if annotations:
                            logger.info(f"Extracted {len(annotations)} annotations from Responses API")
                    except Exception as e:
                        logger.warning(f"Error extracting annotations: {e}", exc_info=True)
                        annotations = []
                    
                    # Extract usage info
                    usage_data = response_data.get('usage', {})
                    if not usage_data:
                        # Try alternative keys
                        usage_data = {
                            "prompt_tokens": response_data.get('input_tokens', 0),
                            "completion_tokens": response_data.get('output_tokens', 0),
                            "total_tokens": response_data.get('input_tokens', 0) + response_data.get('output_tokens', 0)
                        }
                    
                    result = {
                        "id": response_data.get('id', 'resp_' + str(uuid.uuid4())),
                        "model": tenant_ctx.llm_model,
                        "choices": [
                            {
                                "index": 0,
                                "message": {
                                    "role": "assistant",
                                    "content": text_content,
                                    "tool_calls": tool_calls if tool_calls else None,
                                    "annotations": annotations if annotations else None,
                                },
                                "finish_reason": response_data.get('finish_reason', 'stop'),
                            }
                        ],
                        "usage": usage_data if usage_data.get('total_tokens') or usage_data.get('prompt_tokens') else None,
                    }
                    return result
                elif hasattr(response_obj, 'output') and response_obj.output:
                    # SDK response object format
                    if isinstance(response_obj.output, list):
                        for item in response_obj.output:
                            if hasattr(item, 'content'):
                                text_content += item.content or ""
                            elif isinstance(item, dict) and 'content' in item:
                                text_content += item.get('content', '')
                    elif hasattr(response_obj.output, 'content'):
                        text_content = response_obj.output.content or ""
                    elif isinstance(response_obj.output, str):
                        text_content = response_obj.output
                    
                    # Extract annotations from SDK response object
                    try:
                        # Convert object to dict-like structure for annotation extraction
                        response_dict = {}
                        if hasattr(response_obj, 'output'):
                            if isinstance(response_obj.output, list):
                                response_dict['output'] = [
                                    item.__dict__ if hasattr(item, '__dict__') else item
                                    for item in response_obj.output
                                ]
                            else:
                                response_dict['output'] = [response_obj.output]
                        annotations = extract_annotations(response_dict)
                        if annotations:
                            logger.info(f"Extracted {len(annotations)} annotations from SDK response")
                    except Exception as e:
                        logger.warning(f"Error extracting annotations from SDK response: {e}", exc_info=True)
                        annotations = []
                    
                    result = {
                        "id": getattr(response_obj, 'id', 'resp_' + str(uuid.uuid4())),
                        "model": tenant_ctx.llm_model,
                        "choices": [
                            {
                                "index": 0,
                                "message": {
                                    "role": "assistant",
                                    "content": text_content,
                                    "tool_calls": tool_calls if tool_calls else None,
                                    "annotations": annotations if annotations else None,
                                },
                                "finish_reason": getattr(response_obj, 'finish_reason', 'stop'),
                            }
                        ],
                        "usage": {
                            "prompt_tokens": getattr(response_obj, 'input_tokens', 0),
                            "completion_tokens": getattr(response_obj, 'output_tokens', 0),
                            "total_tokens": getattr(response_obj, 'input_tokens', 0) + getattr(response_obj, 'output_tokens', 0),
                        } if hasattr(response_obj, 'input_tokens') else None,
                    }
                    return result
                else:
                    # Fallback: if response format is unexpected, try Chat Completions
                    raise ValueError("Unexpected Responses API format, falling back to Chat Completions")
                    
            except Exception as e:
                # If Responses API doesn't work (e.g., model not supported), fall back to Chat Completions
                logger = logging.getLogger("app.adapters.openai")
                logger.error(f"Responses API error for {tenant_ctx.llm_model}: {type(e).__name__}: {str(e)}. Falling back to Chat Completions without file_search.", exc_info=True)
                # Log the full error details for debugging
                logger.error(f"Error details - Model: {tenant_ctx.llm_model}, Vector Store IDs: {vector_store_ids}, Error: {repr(e)}")
                # Continue to Chat Completions fallback below
        
        # No vector stores or Responses API not available - use Chat Completions
        request_params = {
            "model": tenant_ctx.llm_model,
            "messages": messages,
        }
        
        if openai_tools:
            request_params["tools"] = openai_tools
            request_params["tool_choice"] = "auto"
        
        response_obj = await client.chat.completions.create(**request_params)
        result = {
            "id": response_obj.id,
            "model": response_obj.model,
            "choices": [
                {
                    "index": choice.index,
                    "message": {
                        "role": choice.message.role,
                        "content": choice.message.content,
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": tc.type,
                                "function": {
                                    "name": tc.function.name,
                                    "arguments": tc.function.arguments,
                                }
                            }
                            for tc in (choice.message.tool_calls or [])
                        ] if choice.message.tool_calls else None,
                    },
                    "finish_reason": choice.finish_reason,
                }
                for choice in response_obj.choices
            ],
            "usage": {
                "prompt_tokens": response_obj.usage.prompt_tokens,
                "completion_tokens": response_obj.usage.completion_tokens,
                "total_tokens": response_obj.usage.total_tokens,
            } if response_obj.usage else None,
        }
        return result
        
    except Exception as e:
        from app.infra.error_handler import wrap_llm_error
        raise wrap_llm_error(e, "openai")
