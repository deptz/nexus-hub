"""Tests for prompt builder."""

import pytest
from app.models.message import CanonicalMessage, MessageParty, MessageContent
from app.models.tenant import TenantContext
from app.services.prompt_builder import build_messages, CORE_GUARDRAILS_PROMPT, GLOBAL_SYSTEM_PROMPT


class TestPromptBuilder:
    """Test prompt builder layered stack."""
    
    def test_prompt_stack_order(self):
        """Test that prompt stack is in correct order."""
        tenant_ctx = TenantContext(
            tenant_id="test-tenant",
            llm_provider="openai",
            llm_model="gpt-4",
            allowed_tools=[],
            kb_configs={},
            mcp_configs={},
            prompt_profile={
                "custom_system_prompt": "TENANT",
            },
            isolation_mode="shared_db",
        )
        
        history = [
            CanonicalMessage(
                id="msg-1",
                tenant_id="test-tenant",
                conversation_id="conv-1",
                channel="web",
                direction="inbound",
                source_message_id="ext-1",
                from_=MessageParty(type="user", external_id="user-1"),
                to=MessageParty(type="bot", external_id="bot-1"),
                content=MessageContent(type="text", text="history"),
                metadata={},
                timestamp="2025-01-16T10:00:00Z",
            )
        ]
        
        user_msg = CanonicalMessage(
            id="msg-2",
            tenant_id="test-tenant",
            conversation_id="conv-1",
            channel="web",
            direction="inbound",
            source_message_id="ext-2",
            from_=MessageParty(type="user", external_id="user-1"),
            to=MessageParty(type="bot", external_id="bot-1"),
            content=MessageContent(type="text", text="user msg"),
            metadata={},
            timestamp="2025-01-16T10:01:00Z",
        )
        
        messages = build_messages(tenant_ctx, history, user_msg)
        
        # Check order: CORE -> GLOBAL -> TENANT -> history -> user
        assert len(messages) >= 4
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == CORE_GUARDRAILS_PROMPT
        assert messages[1]["role"] == "system"
        assert messages[1]["content"] == GLOBAL_SYSTEM_PROMPT
        assert messages[2]["role"] == "system"
        assert messages[2]["content"] == "TENANT"
        
        # History and user messages
        assert any(msg["content"] == "history" for msg in messages)
        assert any(msg["content"] == "user msg" for msg in messages)
    
    def test_no_tenant_prompt(self):
        """Test prompt builder without tenant custom prompt."""
        tenant_ctx = TenantContext(
            tenant_id="test-tenant",
            llm_provider="openai",
            llm_model="gpt-4",
            allowed_tools=[],
            kb_configs={},
            mcp_configs={},
            prompt_profile={},  # No custom prompt
            isolation_mode="shared_db",
        )
        
        user_msg = CanonicalMessage(
            id="msg-1",
            tenant_id="test-tenant",
            conversation_id="conv-1",
            channel="web",
            direction="inbound",
            source_message_id="ext-1",
            from_=MessageParty(type="user", external_id="user-1"),
            to=MessageParty(type="bot", external_id="bot-1"),
            content=MessageContent(type="text", text="user msg"),
            metadata={},
            timestamp="2025-01-16T10:00:00Z",
        )
        
        messages = build_messages(tenant_ctx, [], user_msg)
        
        # Should have CORE, GLOBAL, and user message, but no tenant prompt
        assert len(messages) >= 3
        assert messages[0]["content"] == CORE_GUARDRAILS_PROMPT
        assert messages[1]["content"] == GLOBAL_SYSTEM_PROMPT
        # No tenant prompt in between
        assert not any(
            msg["role"] == "system" and msg["content"] not in [CORE_GUARDRAILS_PROMPT, GLOBAL_SYSTEM_PROMPT]
            for msg in messages[:2]
        )
    
    def test_history_truncation(self):
        """Test that history is truncated (simple limit for now)."""
        tenant_ctx = TenantContext(
            tenant_id="test-tenant",
            llm_provider="openai",
            llm_model="gpt-4",
            allowed_tools=[],
            kb_configs={},
            mcp_configs={},
            prompt_profile={},
            isolation_mode="shared_db",
        )
        
        # Create 15 history messages
        history = []
        for i in range(15):
            history.append(
                CanonicalMessage(
                    id=f"msg-{i}",
                    tenant_id="test-tenant",
                    conversation_id="conv-1",
                    channel="web",
                    direction="inbound" if i % 2 == 0 else "outbound",
                    source_message_id=f"ext-{i}",
                    from_=MessageParty(
                        type="user" if i % 2 == 0 else "bot",
                        external_id=f"user-{i}" if i % 2 == 0 else "bot-1"
                    ),
                    to=MessageParty(type="bot" if i % 2 == 0 else "user", external_id="bot-1" if i % 2 == 0 else "user-1"),
                    content=MessageContent(type="text", text=f"message {i}"),
                    metadata={},
                    timestamp=f"2025-01-16T10:{i:02d}:00Z",
                )
            )
        
        user_msg = CanonicalMessage(
            id="msg-15",
            tenant_id="test-tenant",
            conversation_id="conv-1",
            channel="web",
            direction="inbound",
            source_message_id="ext-15",
            from_=MessageParty(type="user", external_id="user-1"),
            to=MessageParty(type="bot", external_id="bot-1"),
            content=MessageContent(type="text", text="user msg"),
            metadata={},
            timestamp="2025-01-16T10:15:00Z",
        )
        
        messages = build_messages(tenant_ctx, history, user_msg)
        
        # Should have CORE, GLOBAL, last 10 history messages, and user message
        # Total should be 2 (system) + 10 (history) + 1 (user) = 13
        assert len(messages) <= 13  # May be less if some are filtered

