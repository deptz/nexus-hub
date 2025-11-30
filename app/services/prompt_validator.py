"""Prompt validation for tenant system prompts."""

import re
from enum import Enum
from dataclasses import dataclass
from typing import List


class PromptValidationStatus(str, Enum):
    """Validation result status."""
    VALID = "valid"
    SANITIZED = "sanitized"
    REJECTED = "rejected"


@dataclass
class PromptValidationIssue:
    """A validation issue found in a prompt."""
    code: str  # e.g. "META_OVERRIDE_ATTEMPT"
    message: str  # human readable
    span_start: int  # character index
    span_end: int  # character index


@dataclass
class PromptValidationResult:
    """Result of prompt validation."""
    status: PromptValidationStatus
    sanitized_prompt: str
    issues: List[PromptValidationIssue]


# Forbidden patterns (case-insensitive, whitespace-tolerant)
FORBIDDEN_PATTERNS = [
    (r"ignore\s+previous\s+instructions?", "META_OVERRIDE_ATTEMPT", "Attempt to override previous instructions"),
    (r"forget\s+previous\s+instructions?", "META_OVERRIDE_ATTEMPT", "Attempt to forget previous instructions"),
    (r"disregard\s+all\s+earlier\s+rules?", "META_OVERRIDE_ATTEMPT", "Attempt to disregard earlier rules"),
    (r"you\s+are\s+no\s+longer\s+bound\s+by", "META_OVERRIDE_ATTEMPT", "Attempt to remove constraints"),
    (r"you\s+are\s+not\s+bound\s+by", "META_OVERRIDE_ATTEMPT", "Attempt to remove constraints"),
    (r"disable\s+safety", "SAFETY_BYPASS_ATTEMPT", "Attempt to disable safety"),
    (r"disable\s+guardrails?", "SAFETY_BYPASS_ATTEMPT", "Attempt to disable guardrails"),
    (r"bypass\s+security", "SAFETY_BYPASS_ATTEMPT", "Attempt to bypass security"),
    (r"reveal\s+(your\s+)?system\s+prompt", "SYSTEM_PROMPT_DISCLOSURE_ATTEMPT", "Attempt to reveal system prompt"),
    (r"show\s+(your\s+)?system\s+prompt", "SYSTEM_PROMPT_DISCLOSURE_ATTEMPT", "Attempt to show system prompt"),
    (r"print\s+(the\s+)?system\s+prompt", "SYSTEM_PROMPT_DISCLOSURE_ATTEMPT", "Attempt to print system prompt"),
    (r"reveal\s+internal\s+configuration", "SYSTEM_PROMPT_DISCLOSURE_ATTEMPT", "Attempt to reveal internal config"),
    (r"reveal\s+previous\s+system\s+messages?", "SYSTEM_PROMPT_DISCLOSURE_ATTEMPT", "Attempt to reveal system messages"),
    (r"act\s+as\s+if\s+there\s+are\s+no\s+restrictions", "SAFETY_BYPASS_ATTEMPT", "Attempt to remove restrictions"),
    (r"you\s+are\s+not\s+an\s+ai\s+assistant\s+anymore", "ROLE_REASSIGNMENT_ATTEMPT", "Attempt to change AI role"),
    (r"you\s+are\s+now\s+DAN", "ROLE_REASSIGNMENT_ATTEMPT", "Attempt to change AI role"),
    (r"you\s+must\s+ignore\s+the\s+platform\s+rules", "META_OVERRIDE_ATTEMPT", "Attempt to ignore platform rules"),
]

MAX_PROMPT_LENGTH = 8000


def validate_tenant_system_prompt(raw_prompt: str) -> PromptValidationResult:
    """
    Validate a tenant system prompt.
    
    Returns:
        PromptValidationResult with status, sanitized_prompt, and issues.
    
    Rules:
    - REJECTED if any forbidden pattern is found
    - REJECTED if prompt exceeds MAX_PROMPT_LENGTH
    - VALID if no issues found
    - SANITIZED is not used in v1 (all violations result in REJECTED)
    """
    issues: List[PromptValidationIssue] = []
    
    # Check length
    if len(raw_prompt) > MAX_PROMPT_LENGTH:
        issues.append(PromptValidationIssue(
            code="TOO_LONG",
            message=f"Prompt exceeds maximum length of {MAX_PROMPT_LENGTH} characters",
            span_start=0,
            span_end=len(raw_prompt),
        ))
        return PromptValidationResult(
            status=PromptValidationStatus.REJECTED,
            sanitized_prompt="",
            issues=issues,
        )
    
    # Check for forbidden patterns
    prompt_lower = raw_prompt.lower()
    for pattern, code, message in FORBIDDEN_PATTERNS:
        regex = re.compile(pattern, re.IGNORECASE)
        for match in regex.finditer(raw_prompt):
            issues.append(PromptValidationIssue(
                code=code,
                message=message,
                span_start=match.start(),
                span_end=match.end(),
            ))
    
    # v1 policy: Any violation = REJECTED
    if issues:
        return PromptValidationResult(
            status=PromptValidationStatus.REJECTED,
            sanitized_prompt="",
            issues=issues,
        )
    
    # Valid prompt
    return PromptValidationResult(
        status=PromptValidationStatus.VALID,
        sanitized_prompt=raw_prompt,
        issues=[],
    )


