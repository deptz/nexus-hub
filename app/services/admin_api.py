"""Admin API services for tenant management."""

from typing import Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.services.prompt_validator import (
    validate_tenant_system_prompt,
    PromptValidationStatus,
)
from app.infra.database import get_db_session


async def update_tenant_prompt(
    tenant_id: str,
    custom_system_prompt: str,
    override_mode: str = "append",
) -> Dict[str, Any]:
    """
    Update tenant system prompt with validation.
    
    Args:
        tenant_id: Tenant ID
        custom_system_prompt: Raw prompt text to validate
        override_mode: 'append' or 'replace_behavior'
    
    Returns:
        Dict with status, effective_prompt, validation_status, issues
    
    Raises:
        ValueError: If validation fails (REJECTED status)
    """
    # Validate prompt
    validation_result = validate_tenant_system_prompt(custom_system_prompt)
    
    if validation_result.status == PromptValidationStatus.REJECTED:
        # Convert issues to dict format for API response
        issues = [
            {
                "code": issue.code,
                "message": issue.message,
                "span_start": issue.span_start,
                "span_end": issue.span_end,
            }
            for issue in validation_result.issues
        ]
        error_dict = {
            "error": "PROMPT_VALIDATION_FAILED",
            "issues": issues,
        }
        raise ValueError(str(error_dict))
    
    # Store sanitized prompt in DB
    with get_db_session(tenant_id) as session:
        # Check if prompt exists
        existing = session.execute(
            text("""
                SELECT id FROM tenant_prompts
                WHERE tenant_id = :tenant_id
            """),
            {"tenant_id": tenant_id}
        ).fetchone()
        
        if existing:
            # Update existing
            session.execute(
                text("""
                    UPDATE tenant_prompts
                    SET custom_system_prompt = :prompt,
                        override_mode = :override_mode,
                        updated_at = now()
                    WHERE tenant_id = :tenant_id
                """),
                {
                    "tenant_id": tenant_id,
                    "prompt": validation_result.sanitized_prompt,
                    "override_mode": override_mode,
                }
            )
        else:
            # Insert new
            session.execute(
                text("""
                    INSERT INTO tenant_prompts (
                        tenant_id, custom_system_prompt, override_mode
                    ) VALUES (
                        :tenant_id, :prompt, :override_mode
                    )
                """),
                {
                    "tenant_id": tenant_id,
                    "prompt": validation_result.sanitized_prompt,
                    "override_mode": override_mode,
                }
            )
        session.commit()
    
    # Return response
    return {
        "status": "ok",
        "effective_prompt": validation_result.sanitized_prompt,
        "validation_status": validation_result.status.value,
        "issues": [
            {
                "code": issue.code,
                "message": issue.message,
                "span_start": issue.span_start,
                "span_end": issue.span_end,
            }
            for issue in validation_result.issues
        ],
    }

