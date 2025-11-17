"""Test annotation flow through message processing pipeline."""

import pytest
import json
from unittest.mock import patch, MagicMock
from app.adapters.vendor_adapter_openai import call_openai_responses, extract_annotations
from app.models.tenant import TenantContext


class TestMessageAnnotationsFlow:
    """Test that annotations flow correctly through the message processing pipeline."""
    
    @pytest.mark.asyncio
    async def test_annotations_extracted_from_response(self):
        """Test that annotations are extracted from Responses API response."""
        # Mock response with annotations
        mock_response_data = {
            "id": "resp_test",
            "model": "gpt-4-turbo",
            "output": [
                {
                    "type": "text",
                    "text": {
                        "value": "The return policy [1] allows returns.",
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
            "usage": {"input_tokens": 100, "output_tokens": 20}
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
            from unittest.mock import AsyncMock
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = mock_response_data
            mock_response.text = json.dumps(mock_response_data)
            
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
        
        # Verify annotations are in the response
        assert "choices" in result
        message = result["choices"][0]["message"]
        assert "annotations" in message
        assert message["annotations"] is not None
        assert len(message["annotations"]) == 1
        
        annotation = message["annotations"][0]
        assert annotation["type"] == "file_citation"
        assert annotation["file_citation"]["file_id"] == "file-test-123"
    
    def test_annotations_in_message_metadata_format(self):
        """Test the format of annotations that should be stored in message metadata."""
        # Simulate annotations from response
        annotations = [
            {
                "type": "file_citation",
                "text": "[1]",
                "file_citation": {
                    "file_id": "file-return-policy-2024",
                    "quote": "return policy"
                },
                "start_index": 28,
                "end_index": 31
            }
        ]
        
        # Simulate what happens in main.py (lines 724-750)
        outbound_metadata = {}
        if annotations:
            outbound_metadata["annotations"] = annotations
            # Extract file IDs for easy access
            file_ids = []
            for ann in annotations:
                if ann.get("file_citation"):
                    file_ids.append(ann["file_citation"].get("file_id"))
                elif ann.get("file_path"):
                    file_ids.append(ann["file_path"].get("file_id"))
            if file_ids:
                outbound_metadata["file_ids"] = list(set(file_ids))  # Deduplicate
        
        # Verify metadata structure
        assert "annotations" in outbound_metadata
        assert len(outbound_metadata["annotations"]) == 1
        assert "file_ids" in outbound_metadata
        assert "file-return-policy-2024" in outbound_metadata["file_ids"]
        assert len(outbound_metadata["file_ids"]) == 1
    
    def test_multiple_annotations_file_ids_deduplication(self):
        """Test that file IDs are properly deduplicated in metadata."""
        annotations = [
            {
                "type": "file_citation",
                "file_citation": {"file_id": "file-123"}
            },
            {
                "type": "file_citation",
                "file_citation": {"file_id": "file-456"}
            },
            {
                "type": "file_citation",
                "file_citation": {"file_id": "file-123"}  # Duplicate
            }
        ]
        
        # Simulate metadata creation
        outbound_metadata = {}
        if annotations:
            outbound_metadata["annotations"] = annotations
            file_ids = []
            for ann in annotations:
                if ann.get("file_citation"):
                    file_ids.append(ann["file_citation"].get("file_id"))
            if file_ids:
                outbound_metadata["file_ids"] = list(set(file_ids))
        
        # Verify deduplication
        assert len(outbound_metadata["file_ids"]) == 2
        assert "file-123" in outbound_metadata["file_ids"]
        assert "file-456" in outbound_metadata["file_ids"]
    
    def test_annotations_with_file_path(self):
        """Test annotations with file_path type."""
        annotations = [
            {
                "type": "file_path",
                "text": "[2]",
                "file_path": {
                    "file_id": "file-xyz789"
                },
                "start_index": 10,
                "end_index": 13
            }
        ]
        
        # Simulate metadata creation
        outbound_metadata = {}
        if annotations:
            outbound_metadata["annotations"] = annotations
            file_ids = []
            for ann in annotations:
                if ann.get("file_citation"):
                    file_ids.append(ann["file_citation"].get("file_id"))
                elif ann.get("file_path"):
                    file_ids.append(ann["file_path"].get("file_id"))
            if file_ids:
                outbound_metadata["file_ids"] = list(set(file_ids))
        
        # Verify file_path handling
        assert "file_ids" in outbound_metadata
        assert "file-xyz789" in outbound_metadata["file_ids"]
    
    def test_empty_annotations_handling(self):
        """Test that empty annotations are handled correctly."""
        annotations = []
        
        # Simulate metadata creation (as in main.py)
        outbound_metadata = {}
        if annotations:
            outbound_metadata["annotations"] = annotations
            file_ids = []
            for ann in annotations:
                if ann.get("file_citation"):
                    file_ids.append(ann["file_citation"].get("file_id"))
            if file_ids:
                outbound_metadata["file_ids"] = list(set(file_ids))
        
        # Verify empty annotations don't create metadata
        assert "annotations" not in outbound_metadata or outbound_metadata.get("annotations") == []
        assert "file_ids" not in outbound_metadata

