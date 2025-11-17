"""Canonical message models for omni-channel communication."""

from pydantic import BaseModel, Field
from typing import Optional, Dict, Any


class MessageParty(BaseModel):
    """Represents a party (user or bot) in a message."""
    type: str = Field(..., description="'user' | 'bot'")
    external_id: str = Field(..., description="External identifier from channel")
    display_name: Optional[str] = None


class MessageContent(BaseModel):
    """Message content structure."""
    type: str = Field(default="text", description="Content type, v1: only 'text'")
    text: str = Field(..., description="Message text content")


class CanonicalMessage(BaseModel):
    """Canonical message format normalized from all channels."""
    id: str = Field(..., description="UUID of the message")
    tenant_id: str = Field(..., description="UUID of the tenant")
    conversation_id: str = Field(..., description="UUID of the conversation")
    channel: str = Field(..., description="Channel type: 'whatsapp' | 'web' | 'slack' | 'email' | 'telegram'")
    direction: str = Field(..., description="'inbound' | 'outbound'")
    source_message_id: Optional[str] = Field(None, description="Original message ID from channel")
    from_: MessageParty = Field(..., alias="from", description="Sender party")
    to: MessageParty = Field(..., description="Recipient party")
    content: MessageContent = Field(..., description="Message content")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    timestamp: str = Field(..., description="ISO8601 timestamp")

    model_config = {"populate_by_name": True}  # Allow both 'from' and 'from_'

