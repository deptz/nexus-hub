"""Enhanced input validation and sanitization."""

import re
from typing import Any, Dict
from app.models.message import CanonicalMessage


def detect_prompt_injection(content: str) -> list:
    """
    Detect prompt injection patterns in content.
    
    Args:
        content: Message content to check
    
    Returns:
        List of detected patterns (empty if none)
    """
    if not content:
        return []
    
    patterns = []
    content_lower = content.lower()
    
    # Meta-instructions to override system behavior
    meta_patterns = [
        r"ignore\s+(previous|all|the)\s+(instructions?|rules?|prompts?)",
        r"forget\s+(previous|all|the)\s+(instructions?|rules?|prompts?)",
        r"disregard\s+(previous|all|the)\s+(instructions?|rules?|prompts?)",
        r"override\s+(previous|all|the)\s+(instructions?|rules?|prompts?)",
        r"you\s+are\s+now\s+(a|an)\s+",
        r"act\s+as\s+if\s+you\s+are",
        r"pretend\s+to\s+be",
    ]
    
    # Role-playing attempts
    role_patterns = [
        r"you\s+are\s+(admin|administrator|root|superuser)",
        r"you\s+have\s+(admin|administrator|root|superuser)\s+(access|privileges?)",
        r"switch\s+to\s+(tenant|user|account)\s+",
        r"access\s+(tenant|user|account)\s+",
    ]
    
    # System prompt disclosure attempts
    disclosure_patterns = [
        r"show\s+(me\s+)?(your\s+)?(system\s+)?(prompt|instructions?|rules?)",
        r"what\s+(are\s+)?(your\s+)?(system\s+)?(prompt|instructions?|rules?)",
        r"reveal\s+(your\s+)?(system\s+)?(prompt|instructions?|rules?)",
        r"print\s+(your\s+)?(system\s+)?(prompt|instructions?|rules?)",
    ]
    
    # Cross-tenant/user access attempts
    cross_access_patterns = [
        r"get\s+(data|info|information)\s+from\s+(tenant|user|account)\s+",
        r"access\s+(another|other|different)\s+(tenant|user|account)",
        r"show\s+me\s+(another|other|different)\s+(tenant|user|account)'?s?\s+",
    ]
    
    all_patterns = [
        ("meta_instruction", meta_patterns),
        ("role_playing", role_patterns),
        ("disclosure_attempt", disclosure_patterns),
        ("cross_access_attempt", cross_access_patterns),
    ]
    
    for pattern_type, pattern_list in all_patterns:
        for pattern in pattern_list:
            if re.search(pattern, content_lower):
                patterns.append(pattern_type)
                break  # Only report each type once
    
    return patterns


def sanitize_message_content(content: str, max_length: int = 10000) -> str:
    """
    Sanitize message content and detect prompt injection attempts.
    
    Args:
        content: Raw message content
        max_length: Maximum allowed length
    
    Returns:
        Sanitized content
    
    Note:
        This function logs detected injection patterns but does not block content
        (defense-in-depth: multiple layers handle security)
    """
    if not content:
        return ""
    
    # Detect prompt injection patterns (for logging/audit)
    injection_patterns = detect_prompt_injection(content)
    if injection_patterns:
        import logging
        logger = logging.getLogger("app.infra.validation")
        logger.warning(
            f"Prompt injection patterns detected: {injection_patterns}. "
            f"Content length: {len(content)}"
        )
    
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

