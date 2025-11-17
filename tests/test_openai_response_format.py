"""Tests for OpenAI response format with annotations."""

import pytest
from app.adapters.vendor_adapter_openai import call_openai_responses, extract_annotations
from app.models.tenant import TenantContext
from unittest.mock import AsyncMock, patch, MagicMock
import json


class TestOpenAIResponseFormat:
    """Test that annotations are properly included in standardized response format."""
    
    @pytest.mark.asyncio
    async def test_response_includes_annotations(self):
        """Test that annotations are included in the standardized response format."""
        # Mock Responses API response with annotations
        mock_response_data = {
            "id": "resp_test123",
            "model": "gpt-4-turbo",
            "output": [
                {
                    "type": "text",
                    "text": {
                        "value": "The return policy [1] allows returns within 30 days.",
                        "annotations": [
                            {
                                "type": "file_citation",
                                "text": "[1]",
                                "file_citation": {
                                    "file_id": "file-test-123",
                                    "quote": "return policy"
                                },
                                "start_index": 18,
                                "end_index": 21
                            }
                        ]
                    }
                }
            ],
            "usage": {
                "input_tokens": 100,
                "output_tokens": 20
            }
        }
        
        # Create mock tenant context
        tenant_ctx = TenantContext(
            tenant_id="test-tenant",
            llm_provider="openai",
            llm_model="gpt-4-turbo",
            allowed_tools=[],
            kb_configs={},
            mcp_configs={},
            prompt_profile={},
            isolation_mode="shared_db"
        )
        
        # Mock the httpx client - httpx is imported inside the function
        with patch("httpx.AsyncClient") as mock_async_client_class:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = mock_response_data
            mock_response.text = json.dumps(mock_response_data)
            
            # Create a context manager mock
            mock_context_manager = AsyncMock()
            mock_client_instance = AsyncMock()
            mock_client_instance.post = AsyncMock(return_value=mock_response)
            mock_context_manager.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_context_manager.__aexit__ = AsyncMock(return_value=None)
            mock_async_client_class.return_value = mock_context_manager
            
            # Call the function
            result = await call_openai_responses(
                tenant_ctx=tenant_ctx,
                messages=[{"role": "user", "content": "What is the return policy?"}],
                tools=[],
                vector_store_ids=["vs-test-123"]
            )
        
        # Verify response structure
        assert "choices" in result
        assert len(result["choices"]) > 0
        
        message = result["choices"][0]["message"]
        
        # Verify annotations are present
        assert "annotations" in message
        assert message["annotations"] is not None
        assert len(message["annotations"]) == 1
        
        # Verify annotation structure
        annotation = message["annotations"][0]
        assert annotation["type"] == "file_citation"
        assert annotation["file_citation"]["file_id"] == "file-test-123"
        assert annotation["file_citation"]["quote"] == "return policy"
        assert annotation["start_index"] == 18
        assert annotation["end_index"] == 21
    
    @pytest.mark.asyncio
    async def test_response_without_annotations(self):
        """Test that response handles missing annotations gracefully."""
        # Mock Responses API response without annotations
        mock_response_data = {
            "id": "resp_test456",
            "model": "gpt-4-turbo",
            "output": [
                {
                    "type": "text",
                    "text": "This is a regular response without file search."
                }
            ],
            "usage": {
                "input_tokens": 50,
                "output_tokens": 10
            }
        }
        
        tenant_ctx = TenantContext(
            tenant_id="test-tenant",
            llm_provider="openai",
            llm_model="gpt-4-turbo",
            allowed_tools=[],
            kb_configs={},
            mcp_configs={},
            prompt_profile={},
            isolation_mode="shared_db"
        )
        
        with patch("httpx.AsyncClient") as mock_async_client_class:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = mock_response_data
            mock_response.text = json.dumps(mock_response_data)
            
            # Create a context manager mock
            mock_context_manager = AsyncMock()
            mock_client_instance = AsyncMock()
            mock_client_instance.post = AsyncMock(return_value=mock_response)
            mock_context_manager.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_context_manager.__aexit__ = AsyncMock(return_value=None)
            mock_async_client_class.return_value = mock_context_manager
            
            result = await call_openai_responses(
                tenant_ctx=tenant_ctx,
                messages=[{"role": "user", "content": "Hello"}],
                tools=[],
                vector_store_ids=["vs-test-123"]
            )
        
        # Verify response structure
        message = result["choices"][0]["message"]
        
        # Annotations should be None (not empty list) when not present
        assert "annotations" in message
        assert message["annotations"] is None or len(message["annotations"]) == 0
    
    def test_extract_annotations_edge_cases(self):
        """Test annotation extraction with various edge cases."""
        # Test with empty annotations array
        response1 = {
            "output": [
                {
                    "type": "text",
                    "text": "No citations here",
                    "annotations": []
                }
            ]
        }
        assert len(extract_annotations(response1)) == 0
        
        # Test with None annotations
        response2 = {
            "output": [
                {
                    "type": "text",
                    "text": "No citations here"
                }
            ]
        }
        assert len(extract_annotations(response2)) == 0
        
        # Test with malformed annotation (missing type)
        response3 = {
            "output": [
                {
                    "type": "text",
                    "text": "Text",
                    "annotations": [
                        {
                            "text": "[1]",
                            # Missing type
                        }
                    ]
                }
            ]
        }
        annotations = extract_annotations(response3)
        assert len(annotations) == 0  # Invalid annotations should be filtered out

