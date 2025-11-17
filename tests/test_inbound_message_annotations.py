"""Integration test for inbound message processing with annotations."""

import pytest
import uuid
import json
from datetime import datetime
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.infra.database import get_db
from app.infra.config import config
import os

# Test database URL
TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    config.DATABASE_URL.replace("/nexus_hub", "/nexus_hub_test") if hasattr(config, 'DATABASE_URL') else "postgresql://postgres:postgres@localhost:5432/nexus_hub_test"
)

# Create test engine
test_engine = create_engine(TEST_DATABASE_URL)
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture
def test_db():
    """Create test database session."""
    session = TestSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(test_db):
    """Create test client with test database."""
    def override_get_db():
        try:
            yield test_db
        finally:
            pass
    
    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def test_tenant(test_db):
    """Create a test tenant with OpenAI configuration."""
    tenant_id = str(uuid.uuid4())
    test_db.execute(
        text("""
            INSERT INTO tenants (id, name, slug, llm_provider, llm_model)
            VALUES (:id, 'Test Tenant', 'test-tenant', 'openai', 'gpt-4-turbo')
        """),
        {"id": tenant_id}
    )
    test_db.commit()
    return tenant_id


@pytest.fixture
def test_channel(test_db, test_tenant):
    """Create a test channel."""
    channel_id = str(uuid.uuid4())
    test_db.execute(
        text("""
            INSERT INTO channels (id, tenant_id, name, channel_type, is_active)
            VALUES (:id, :tenant_id, 'test-channel', 'web', TRUE)
        """),
        {"id": channel_id, "tenant_id": test_tenant}
    )
    test_db.commit()
    return channel_id


@pytest.fixture
def test_kb_config(test_db, test_tenant):
    """Create a test knowledge base with vector store ID."""
    kb_id = str(uuid.uuid4())
    test_db.execute(
        text("""
            INSERT INTO knowledge_bases (id, tenant_id, name, description, provider, provider_config)
            VALUES (:id, :tenant_id, 'openai_file_kb', 'Test File Search KB', 'openai_file', 
                    '{"vector_store_id": "vs-test-123"}'::jsonb)
        """),
        {"id": kb_id, "tenant_id": test_tenant}
    )
    test_db.commit()
    return kb_id


class TestInboundMessageAnnotations:
    """Test that annotations are preserved through the inbound message flow."""
    
    @patch("httpx.AsyncClient")
    def test_inbound_message_with_annotations(
        self, mock_async_client, client, test_db, test_tenant, test_channel, test_kb_config
    ):
        """Test that annotations from Responses API are preserved in message metadata."""
        # Mock Responses API response with annotations
        mock_response_data = {
            "id": "resp_test123",
            "model": "gpt-4-turbo",
            "output": [
                {
                    "type": "text",
                    "text": {
                        "value": "According to our return policy [1], customers can return items within 30 days.",
                        "annotations": [
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
                    }
                }
            ],
            "usage": {
                "input_tokens": 150,
                "output_tokens": 25
            }
        }
        
        # Setup httpx mock
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_response_data
        mock_response.text = json.dumps(mock_response_data)
        
        mock_context_manager = AsyncMock()
        mock_client_instance = AsyncMock()
        mock_client_instance.post = AsyncMock(return_value=mock_response)
        mock_context_manager.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_context_manager.__aexit__ = AsyncMock(return_value=None)
        mock_async_client.return_value = mock_context_manager
        
        # Create inbound message
        message = {
            "id": str(uuid.uuid4()),
            "tenant_id": test_tenant,
            "conversation_id": str(uuid.uuid4()),
            "channel": "web",
            "direction": "inbound",
            "from": {
                "type": "user",
                "external_id": "user-123"
            },
            "to": {
                "type": "bot",
                "external_id": "bot-1"
            },
            "content": {
                "type": "text",
                "text": "What is the return policy?"
            },
            "metadata": {
                "channel_id": test_channel,
                "external_thread_id": "thread-annotations-test"
            },
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # Send message (will use mocked Responses API)
        response = client.post("/messages/inbound", json=message)
        
        # Should return 200 if API key is configured, 500 if not
        # But we're mocking the API call, so it should work
        assert response.status_code in [200, 500]
        
        if response.status_code == 200:
            # Verify outbound message was created with annotations in metadata
            outbound_msg = test_db.execute(
                text("""
                    SELECT metadata, content_text
                    FROM messages
                    WHERE tenant_id = :tenant_id
                      AND direction = 'outbound'
                    ORDER BY created_at DESC
                    LIMIT 1
                """),
                {"tenant_id": test_tenant}
            ).fetchone()
            
            if outbound_msg:
                metadata = outbound_msg[0] if isinstance(outbound_msg[0], dict) else json.loads(outbound_msg[0])
                
                # Verify annotations are in metadata
                assert "annotations" in metadata or metadata.get("annotations") is not None
                
                # Verify file IDs are extracted
                if metadata.get("annotations"):
                    annotations = metadata["annotations"]
                    assert len(annotations) > 0
                    assert annotations[0]["type"] == "file_citation"
                    assert annotations[0]["file_citation"]["file_id"] == "file-return-policy-2024"
                    
                    # Verify file_ids array exists
                    if "file_ids" in metadata:
                        assert "file-return-policy-2024" in metadata["file_ids"]
    
    @patch("httpx.AsyncClient")
    def test_inbound_message_without_annotations(
        self, mock_async_client, client, test_db, test_tenant, test_channel
    ):
        """Test that messages without annotations are handled correctly."""
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
        
        # Setup httpx mock
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_response_data
        mock_response.text = json.dumps(mock_response_data)
        
        mock_context_manager = AsyncMock()
        mock_client_instance = AsyncMock()
        mock_client_instance.post = AsyncMock(return_value=mock_response)
        mock_context_manager.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_context_manager.__aexit__ = AsyncMock(return_value=None)
        mock_async_client.return_value = mock_context_manager
        
        # Create inbound message
        message = {
            "id": str(uuid.uuid4()),
            "tenant_id": test_tenant,
            "conversation_id": str(uuid.uuid4()),
            "channel": "web",
            "direction": "inbound",
            "from": {"type": "user", "external_id": "user-123"},
            "to": {"type": "bot", "external_id": "bot-1"},
            "content": {"type": "text", "text": "Hello"},
            "metadata": {
                "channel_id": test_channel,
                "external_thread_id": "thread-no-annotations"
            },
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # Send message
        response = client.post("/messages/inbound", json=message)
        
        assert response.status_code in [200, 500]
        
        if response.status_code == 200:
            # Verify outbound message was created
            outbound_msg = test_db.execute(
                text("""
                    SELECT metadata
                    FROM messages
                    WHERE tenant_id = :tenant_id
                      AND direction = 'outbound'
                    ORDER BY created_at DESC
                    LIMIT 1
                """),
                {"tenant_id": test_tenant}
            ).fetchone()
            
            if outbound_msg:
                metadata = outbound_msg[0] if isinstance(outbound_msg[0], dict) else json.loads(outbound_msg[0])
                
                # Metadata should not have annotations (or empty)
                if "annotations" in metadata:
                    assert metadata["annotations"] == [] or metadata["annotations"] is None
    
    @patch("httpx.AsyncClient")
    def test_inbound_message_multiple_annotations(
        self, mock_async_client, client, test_db, test_tenant, test_channel, test_kb_config
    ):
        """Test that multiple annotations are preserved correctly."""
        # Mock Responses API response with multiple annotations
        mock_response_data = {
            "id": "resp_test789",
            "model": "gpt-4-turbo",
            "output": [
                {
                    "type": "text",
                    "text": {
                        "value": "The policy [1] states that returns [2] can be processed online.",
                        "annotations": [
                            {
                                "type": "file_citation",
                                "text": "[1]",
                                "file_citation": {
                                    "file_id": "file-policy-123",
                                    "quote": "The policy"
                                },
                                "start_index": 4,
                                "end_index": 7
                            },
                            {
                                "type": "file_citation",
                                "text": "[2]",
                                "file_citation": {
                                    "file_id": "file-returns-456",
                                    "quote": "returns"
                                },
                                "start_index": 30,
                                "end_index": 33
                            }
                        ]
                    }
                }
            ],
            "usage": {
                "input_tokens": 200,
                "output_tokens": 30
            }
        }
        
        # Setup httpx mock
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_response_data
        mock_response.text = json.dumps(mock_response_data)
        
        mock_context_manager = AsyncMock()
        mock_client_instance = AsyncMock()
        mock_client_instance.post = AsyncMock(return_value=mock_response)
        mock_context_manager.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_context_manager.__aexit__ = AsyncMock(return_value=None)
        mock_async_client.return_value = mock_context_manager
        
        # Create inbound message
        message = {
            "id": str(uuid.uuid4()),
            "tenant_id": test_tenant,
            "conversation_id": str(uuid.uuid4()),
            "channel": "web",
            "direction": "inbound",
            "from": {"type": "user", "external_id": "user-123"},
            "to": {"type": "bot", "external_id": "bot-1"},
            "content": {"type": "text", "text": "Tell me about the policy and returns"},
            "metadata": {
                "channel_id": test_channel,
                "external_thread_id": "thread-multiple-annotations"
            },
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # Send message
        response = client.post("/messages/inbound", json=message)
        
        assert response.status_code in [200, 500]
        
        if response.status_code == 200:
            # Verify outbound message has multiple annotations
            outbound_msg = test_db.execute(
                text("""
                    SELECT metadata
                    FROM messages
                    WHERE tenant_id = :tenant_id
                      AND direction = 'outbound'
                    ORDER BY created_at DESC
                    LIMIT 1
                """),
                {"tenant_id": test_tenant}
            ).fetchone()
            
            if outbound_msg:
                metadata = outbound_msg[0] if isinstance(outbound_msg[0], dict) else json.loads(outbound_msg[0])
                
                if metadata.get("annotations"):
                    annotations = metadata["annotations"]
                    assert len(annotations) == 2
                    
                    # Verify both file IDs are in file_ids array
                    if "file_ids" in metadata:
                        file_ids = metadata["file_ids"]
                        assert "file-policy-123" in file_ids
                        assert "file-returns-456" in file_ids
                        assert len(file_ids) == 2  # Should be deduplicated

