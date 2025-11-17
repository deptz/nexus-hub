"""Telegram channel adapter for converting Telegram messages to/from CanonicalMessage format."""

import os
import uuid
from datetime import datetime
from typing import Optional, Dict, Any
import httpx
from app.models.message import CanonicalMessage, MessageParty, MessageContent


# Telegram Bot API base URL
TELEGRAM_API_BASE = "https://api.telegram.org/bot"


def get_telegram_bot_token() -> Optional[str]:
    """Get Telegram bot token from environment."""
    return os.getenv("TELEGRAM_BOT_TOKEN")


def telegram_to_canonical(
    telegram_update: Dict[str, Any],
    tenant_id: str,
    conversation_id: Optional[str] = None,
) -> CanonicalMessage:
    """
    Convert a Telegram update to CanonicalMessage format.
    
    Args:
        telegram_update: Telegram webhook update object
        tenant_id: Tenant UUID
        conversation_id: Optional conversation ID (will be created if not provided)
    
    Returns:
        CanonicalMessage object
    """
    # Extract message from update
    message = telegram_update.get("message")
    if not message:
        # Handle edited messages, channel posts, etc.
        message = telegram_update.get("edited_message") or telegram_update.get("channel_post")
        if not message:
            raise ValueError("No message found in Telegram update")
    
    # Extract chat and user info
    chat = message.get("chat", {})
    from_user = message.get("from", {})
    
    # Get message text
    text = message.get("text", "")
    if not text:
        # Handle other message types (photos, documents, etc.)
        if message.get("caption"):
            text = message.get("caption")
        else:
            text = "[Non-text message]"
    
    # Generate IDs
    msg_id = str(uuid.uuid4())
    if not conversation_id:
        conversation_id = str(uuid.uuid4())
    
    # Telegram chat ID as external thread ID
    chat_id = str(chat.get("id"))
    telegram_message_id = str(message.get("message_id"))
    
    # Build canonical message
    return CanonicalMessage(
        id=msg_id,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        channel="telegram",
        direction="inbound",
        source_message_id=telegram_message_id,
        from_=MessageParty(
            type="user",
            external_id=str(from_user.get("id", "")),
            display_name=from_user.get("first_name", "") + " " + (from_user.get("last_name", "") or ""),
        ),
        to=MessageParty(
            type="bot",
            external_id=chat_id,
        ),
        content=MessageContent(
            type="text",
            text=text,
        ),
        metadata={
            "telegram_chat_id": chat_id,
            "telegram_chat_type": chat.get("type"),  # "private", "group", "supergroup", "channel"
            "external_thread_id": chat_id,  # Use chat_id as thread ID for conversation grouping
            "telegram_user": {
                "id": from_user.get("id"),
                "username": from_user.get("username"),
                "first_name": from_user.get("first_name"),
                "last_name": from_user.get("last_name"),
                "language_code": from_user.get("language_code"),
            },
            "raw_telegram_update": telegram_update,
        },
        timestamp=datetime.fromtimestamp(message.get("date", datetime.now().timestamp())).isoformat(),
    )


async def send_telegram_message(
    chat_id: str,
    text: str,
    bot_token: Optional[str] = None,
    reply_to_message_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Send a message to Telegram chat.
    
    Args:
        chat_id: Telegram chat ID
        text: Message text to send
        bot_token: Telegram bot token (if None, reads from env)
        reply_to_message_id: Optional message ID to reply to
    
    Returns:
        Telegram API response
    
    Raises:
        ValueError: If bot token is not available
        httpx.HTTPError: If Telegram API call fails
    """
    if not bot_token:
        bot_token = get_telegram_bot_token()
    
    if not bot_token:
        raise ValueError("Telegram bot token not configured. Set TELEGRAM_BOT_TOKEN environment variable.")
    
    url = f"{TELEGRAM_API_BASE}{bot_token}/sendMessage"
    
    payload = {
        "chat_id": chat_id,
        "text": text,
    }
    
    if reply_to_message_id:
        payload["reply_to_message_id"] = reply_to_message_id
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        return response.json()


def canonical_to_telegram_response(
    canonical_msg: CanonicalMessage,
    chat_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Extract Telegram-specific data from CanonicalMessage for sending response.
    
    Args:
        canonical_msg: CanonicalMessage with outbound response
        chat_id: Optional chat ID override (otherwise extracted from metadata)
    
    Returns:
        Dict with chat_id and text for sending
    """
    # Extract chat_id from metadata or use provided
    if not chat_id:
        chat_id = canonical_msg.metadata.get("telegram_chat_id")
    
    if not chat_id:
        # Fallback: try to extract from 'to' party external_id
        chat_id = canonical_msg.to.external_id
    
    if not chat_id:
        raise ValueError("Cannot determine Telegram chat_id from message")
    
    return {
        "chat_id": chat_id,
        "text": canonical_msg.content.text,
    }

