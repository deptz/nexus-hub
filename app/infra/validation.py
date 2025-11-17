"""Enhanced input validation and sanitization."""

import re
from typing import Any, Dict
from app.models.message import CanonicalMessage


def sanitize_message_content(content: str, max_length: int = 10000) -> str:
    """
    Sanitize message content.
    
    Args:
        content: Raw message content
        max_length: Maximum allowed length
    
    Returns:
        Sanitized content
    """
    if not content:
        return ""
    
    # Truncate if too long
    if len(content) > max_length:
        content = content[:max_length] + "... [truncated]"
    
    # Remove null bytes
    content = content.replace("\x00", "")
    
    # Remove control characters except newlines and tabs
    content = re.sub(r'[\x00-\x08\x0B-\x0C\x0E-\x1F\x7F]', '', content)
    
    return content


def validate_tenant_id(tenant_id: str) -> None:
    """
    Validate tenant_id format (UUID) with security constraints.
    
    Args:
        tenant_id: Tenant ID to validate
    
    Raises:
        ValueError: If validation fails
    """
    import uuid
    import re
    
    if not tenant_id:
        raise ValueError("tenant_id cannot be empty")
    
    # Validate UUID format
    try:
        uuid.UUID(tenant_id)
    except ValueError:
        raise ValueError(f"Invalid tenant_id format (must be UUID): {tenant_id}")
    
    # Additional security: prevent injection attempts
    # Check for SQL injection patterns
    sql_injection_patterns = [
        r"[';]",
        r"--",
        r"/\*",
        r"\*/",
        r"xp_",
        r"exec\s*\(",
        r"union\s+select",
    ]
    for pattern in sql_injection_patterns:
        if re.search(pattern, tenant_id, re.IGNORECASE):
            raise ValueError("Invalid tenant_id: contains suspicious characters")
    
    # Check length (UUIDs are 36 chars, but allow some buffer)
    if len(tenant_id) > 128:
        raise ValueError("tenant_id too long")


def validate_message(message: CanonicalMessage) -> None:
    """
    Validate canonical message with enhanced checks.
    
    Raises:
        ValueError: If validation fails
    """
    # Validate tenant_id format (UUID) with security checks
    validate_tenant_id(message.tenant_id)
    
    # Validate content
    if message.content.type == "text":
        if not message.content.text:
            raise ValueError("Text content cannot be empty")
        
        # Sanitize content
        message.content.text = sanitize_message_content(message.content.text)
    
    # Validate channel
    valid_channels = ["web", "whatsapp", "slack", "email"]
    if message.channel not in valid_channels:
        raise ValueError(f"Invalid channel. Must be one of: {', '.join(valid_channels)}")
    
    # Validate direction
    if message.direction not in ["inbound", "outbound"]:
        raise ValueError("Direction must be 'inbound' or 'outbound'")
    
    # Validate from/to types
    valid_party_types = ["user", "bot"]
    if message.from_.type not in valid_party_types:
        raise ValueError(f"Invalid from.type. Must be one of: {', '.join(valid_party_types)}")
    if message.to.type not in valid_party_types:
        raise ValueError(f"Invalid to.type. Must be one of: {', '.join(valid_party_types)}")


def validate_prompt_content(prompt: str, max_length: int = 5000) -> str:
    """
    Validate and sanitize prompt content.
    
    Args:
        prompt: Raw prompt text
        max_length: Maximum allowed length
    
    Returns:
        Sanitized prompt
    
    Raises:
        ValueError: If validation fails
    """
    if not prompt:
        raise ValueError("Prompt cannot be empty")
    
    if len(prompt) > max_length:
        raise ValueError(f"Prompt too long. Maximum length: {max_length} characters")
    
    # Sanitize
    prompt = sanitize_message_content(prompt, max_length)
    
    return prompt

