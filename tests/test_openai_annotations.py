"""Tests for OpenAI file search annotation extraction."""

import pytest
from app.adapters.vendor_adapter_openai import extract_annotations, _parse_annotation


class TestAnnotationExtraction:
    """Test annotation extraction from Responses API responses."""
    
    def test_extract_annotations_with_file_citations(self):
        """Test extraction of annotations with file citations (Responses API format)."""
        response_data = {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "The return policy states that returns can be processed online or at any retail location.",
                            "annotations": [
                                {
                                    "type": "file_citation",
                                    "file_id": "file-abc123",
                                    "filename": "return_policy.txt",
                                    "index": 25
                                }
                            ]
                        }
                    ]
                }
            ]
        }
        
        annotations = extract_annotations(response_data)
        
        assert len(annotations) == 1
        assert annotations[0]["type"] == "file_citation"
        assert annotations[0]["file_citation"]["file_id"] == "file-abc123"
        assert annotations[0]["file_citation"]["filename"] == "return_policy.txt"
        assert annotations[0]["index"] == 25
    
    def test_extract_annotations_legacy_format(self):
        """Test extraction of annotations with legacy nested format."""
        response_data = {
            "output": [
                {
                    "type": "text",
                    "text": "The return policy states that returns can be processed online or at any retail location.",
                    "annotations": [
                        {
                            "type": "file_citation",
                            "text": "[1]",
                            "file_citation": {
                                "file_id": "file-abc123",
                                "quote": "Returns can be processed online or at any retail location"
                            },
                            "start_index": 25,
                            "end_index": 28
                        }
                    ]
                }
            ]
        }
        
        annotations = extract_annotations(response_data)
        
        assert len(annotations) == 1
        assert annotations[0]["type"] == "file_citation"
        assert annotations[0]["text"] == "[1]"
        assert annotations[0]["file_citation"]["file_id"] == "file-abc123"
        assert annotations[0]["file_citation"]["quote"] == "Returns can be processed online or at any retail location"
        assert annotations[0]["start_index"] == 25
        assert annotations[0]["end_index"] == 28
    
    def test_extract_annotations_with_file_path(self):
        """Test extraction of annotations with file paths."""
        response_data = {
            "output": [
                {
                    "type": "text",
                    "text": "See the attached document for details.",
                    "annotations": [
                        {
                            "type": "file_path",
                            "text": "[2]",
                            "file_path": {
                                "file_id": "file-xyz789"
                            },
                            "start_index": 4,
                            "end_index": 7
                        }
                    ]
                }
            ]
        }
        
        annotations = extract_annotations(response_data)
        
        assert len(annotations) == 1
        assert annotations[0]["type"] == "file_path"
        assert annotations[0]["text"] == "[2]"
        assert annotations[0]["file_path"]["file_id"] == "file-xyz789"
        assert annotations[0]["start_index"] == 4
        assert annotations[0]["end_index"] == 7
    
    def test_extract_annotations_multiple(self):
        """Test extraction of multiple annotations."""
        response_data = {
            "output": [
                {
                    "type": "text",
                    "text": "The policy [1] states that returns [2] can be processed online.",
                    "annotations": [
                        {
                            "type": "file_citation",
                            "text": "[1]",
                            "file_citation": {
                                "file_id": "file-abc123",
                                "quote": "The policy"
                            },
                            "start_index": 4,
                            "end_index": 7
                        },
                        {
                            "type": "file_citation",
                            "text": "[2]",
                            "file_citation": {
                                "file_id": "file-def456",
                                "quote": "returns"
                            },
                            "start_index": 30,
                            "end_index": 33
                        }
                    ]
                }
            ]
        }
        
        annotations = extract_annotations(response_data)
        
        assert len(annotations) == 2
        assert annotations[0]["file_citation"]["file_id"] == "file-abc123"
        assert annotations[1]["file_citation"]["file_id"] == "file-def456"
    
    def test_extract_annotations_nested_text(self):
        """Test extraction when annotations are nested in text dict."""
        response_data = {
            "output": [
                {
                    "type": "text",
                    "text": {
                        "value": "The return policy states...",
                        "annotations": [
                            {
                                "type": "file_citation",
                                "text": "[1]",
                                "file_citation": {
                                    "file_id": "file-abc123",
                                    "quote": "return policy"
                                },
                                "start_index": 4,
                                "end_index": 7
                            }
                        ]
                    }
                }
            ]
        }
        
        annotations = extract_annotations(response_data)
        
        assert len(annotations) == 1
        assert annotations[0]["type"] == "file_citation"
        assert annotations[0]["file_citation"]["file_id"] == "file-abc123"
    
    def test_extract_annotations_empty_output(self):
        """Test extraction with empty output."""
        response_data = {
            "output": []
        }
        
        annotations = extract_annotations(response_data)
        
        assert len(annotations) == 0
    
    def test_extract_annotations_no_annotations(self):
        """Test extraction when no annotations are present."""
        response_data = {
            "output": [
                {
                    "type": "text",
                    "text": "This is a regular response without annotations."
                }
            ]
        }
        
        annotations = extract_annotations(response_data)
        
        assert len(annotations) == 0
    
    def test_extract_annotations_missing_output(self):
        """Test extraction when output field is missing."""
        response_data = {}
        
        annotations = extract_annotations(response_data)
        
        assert len(annotations) == 0
    
    def test_parse_annotation_file_citation(self):
        """Test parsing a file citation annotation."""
        ann = {
            "type": "file_citation",
            "text": "[1]",
            "file_citation": {
                "file_id": "file-abc123",
                "quote": "quoted text"
            },
            "start_index": 0,
            "end_index": 3
        }
        
        result = _parse_annotation(ann)
        
        assert result is not None
        assert result["type"] == "file_citation"
        assert result["text"] == "[1]"
        assert result["file_citation"]["file_id"] == "file-abc123"
        assert result["file_citation"]["quote"] == "quoted text"
        assert result["start_index"] == 0
        assert result["end_index"] == 3
    
    def test_parse_annotation_file_path(self):
        """Test parsing a file path annotation."""
        ann = {
            "type": "file_path",
            "text": "[2]",
            "file_path": {
                "file_id": "file-xyz789"
            },
            "start_index": 10,
            "end_index": 13
        }
        
        result = _parse_annotation(ann)
        
        assert result is not None
        assert result["type"] == "file_path"
        assert result["text"] == "[2]"
        assert result["file_path"]["file_id"] == "file-xyz789"
        assert result["start_index"] == 10
        assert result["end_index"] == 13
    
    def test_parse_annotation_invalid(self):
        """Test parsing an invalid annotation."""
        ann = {
            "text": "[1]",
            # Missing type
        }
        
        result = _parse_annotation(ann)
        
        assert result is None
    
    def test_parse_annotation_malformed(self):
        """Test parsing a malformed annotation."""
        ann = "not a dict"
        
        result = _parse_annotation(ann)
        
        assert result is None
    
    def test_extract_annotations_real_world_format(self):
        """Test extraction with a realistic Responses API format."""
        response_data = {
            "id": "resp_abc123",
            "model": "gpt-4-turbo",
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "According to our return policy, customers can return items within 30 days.",
                            "annotations": [
                                {
                                    "type": "file_citation",
                                    "file_id": "file-return-policy-2024",
                                    "filename": "return_policy.txt",
                                    "index": 28
                                }
                            ]
                        }
                    ]
                }
            ],
            "usage": {
                "input_tokens": 150,
                "output_tokens": 25
            }
        }
        
        annotations = extract_annotations(response_data)
        
        assert len(annotations) == 1
        assert annotations[0]["type"] == "file_citation"
        assert annotations[0]["file_citation"]["file_id"] == "file-return-policy-2024"
        assert annotations[0]["file_citation"]["filename"] == "return_policy.txt"
        assert annotations[0]["index"] == 28
    
    def test_extract_annotations_string_output(self):
        """Test extraction when output is a string (no annotations possible)."""
        response_data = {
            "output": "Simple string response"
        }
        
        annotations = extract_annotations(response_data)
        
        assert len(annotations) == 0

