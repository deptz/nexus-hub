"""Event logging service."""

import json
import time
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.infra.database import get_db_session


async def log_event(
    tenant_id: str,
    event_type: str,
    provider: Optional[str] = None,
    status: str = "success",
    latency_ms: Optional[int] = None,
    cost: Optional[float] = None,
    payload: Optional[Dict[str, Any]] = None,
    conversation_id: Optional[str] = None,
    message_id: Optional[str] = None,
) -> None:
    """
    Log an event to event_logs table.
    
    Args:
        tenant_id: Tenant ID
        event_type: Event type (e.g., 'inbound_message', 'llm_call_started', 'tool_call_completed')
        provider: Provider name (e.g., 'openai', 'gemini', 'internal_rag')
        status: 'success' | 'failure'
        latency_ms: Latency in milliseconds
        cost: Cost in dollars
        payload: Additional payload (will be stored as JSONB)
        conversation_id: Optional conversation ID
        message_id: Optional message ID
    """
    with get_db_session(tenant_id) as session:
        session.execute(
            text("""
                INSERT INTO event_logs (
                    tenant_id, conversation_id, message_id, event_type, provider,
                    status, latency_ms, cost, payload
                ) VALUES (
                    :tenant_id, :conversation_id, :message_id, :event_type, :provider,
                    :status, :latency_ms, :cost, CAST(:payload AS jsonb)
                )
            """),
            {
                "tenant_id": tenant_id,
                "conversation_id": conversation_id,
                "message_id": message_id,
                "event_type": event_type,
                "provider": provider,
                "status": status,
                "latency_ms": latency_ms,
                "cost": cost,
                "payload": json.dumps(payload or {}),
            }
        )


async def log_tool_call(
    tenant_id: str,
    tool_name: str,
    provider: str,
    arguments: Dict[str, Any],
    result_summary: Dict[str, Any],
    status: str = "success",
    error_message: Optional[str] = None,
    latency_ms: Optional[int] = None,
    cost: Optional[float] = None,
    conversation_id: Optional[str] = None,
    message_id: Optional[str] = None,
    tool_id: Optional[str] = None,
    execution_context: Optional[Dict[str, Any]] = None,  # NEW: For security audit
    argument_overrides: Optional[list] = None,  # NEW: Parameter overrides applied
    validation_warnings: Optional[list] = None,  # NEW: Validation warnings
    rejection_reason: Optional[str] = None,  # NEW: Why tool call was rejected
) -> None:
    """
    Log a tool call to tool_call_logs table with enhanced security audit fields.
    
    Args:
        tenant_id: Tenant ID
        tool_name: Canonical tool name
        provider: Tool provider
        arguments: Tool arguments (sanitized, after overrides)
        result_summary: Tool result summary (may be trimmed)
        status: 'success' | 'failure'
        error_message: Error message if status is 'failure' (sanitized)
        latency_ms: Latency in milliseconds
        cost: Cost in dollars
        conversation_id: Optional conversation ID
        message_id: Optional message ID
        tool_id: Optional tool ID from tools table
        execution_context: Immutable execution context (for audit)
        argument_overrides: List of parameter overrides applied
        validation_warnings: List of validation warnings
        rejection_reason: Reason for rejection if status is 'failure'
    """
    # Build enhanced payload for security audit
    audit_payload = {}
    if execution_context:
        # Only log non-sensitive context fields
        audit_payload["user_external_id"] = execution_context.get("user_external_id")
        audit_payload["conversation_id"] = execution_context.get("conversation_id")
        audit_payload["channel"] = execution_context.get("channel")
    if argument_overrides:
        audit_payload["argument_overrides"] = argument_overrides
    if validation_warnings:
        audit_payload["validation_warnings"] = validation_warnings
    if rejection_reason:
        audit_payload["rejection_reason"] = rejection_reason
    
    # Sanitize error message to prevent information disclosure
    sanitized_error = None
    if error_message:
        # Generic error messages for users, detailed errors logged server-side
        if any(keyword in error_message.lower() for keyword in ["tenant", "user", "customer", "id", "unauthorized", "forbidden"]):
            sanitized_error = "Unable to retrieve data"  # Generic error
        else:
            sanitized_error = error_message[:200]  # Truncate long errors
    
    with get_db_session(tenant_id) as session:
        # Check if tool_call_logs table has audit fields (for backward compatibility)
        # If not, store audit data in result_summary payload
        try:
            session.execute(
                text("""
                    INSERT INTO tool_call_logs (
                        tenant_id, conversation_id, message_id, tool_id, tool_name, provider,
                        arguments, result_summary, status, error_message, latency_ms, cost
                    ) VALUES (
                        :tenant_id, :conversation_id, :message_id, :tool_id, :tool_name, :provider,
                        CAST(:arguments AS jsonb), CAST(:result_summary AS jsonb), :status, :error_message,
                        :latency_ms, :cost
                    )
                """),
                {
                    "tenant_id": tenant_id,
                    "conversation_id": conversation_id,
                    "message_id": message_id,
                    "tool_id": tool_id,
                    "tool_name": tool_name,
                    "provider": provider,
                    "arguments": json.dumps(arguments or {}),
                    "result_summary": json.dumps({
                        **(result_summary or {}),
                        "_audit": audit_payload  # Store audit data in result_summary
                    }),
                    "status": status,
                    "error_message": sanitized_error,
                    "latency_ms": latency_ms,
                    "cost": cost,
                }
            )
        except Exception as e:
            # Fallback: if table doesn't exist or schema mismatch, log to event_logs
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to log tool call to tool_call_logs: {e}")
            # Log to event_logs as fallback
            await log_event(
                tenant_id=tenant_id,
                event_type="tool_call",
                provider=provider,
                status=status,
                latency_ms=latency_ms,
                cost=cost,
                payload={
                    "tool_name": tool_name,
                    "arguments": arguments,
                    "result_summary": result_summary,
                    "error_message": sanitized_error,
                    **audit_payload,
                },
                conversation_id=conversation_id,
                message_id=message_id,
            )

