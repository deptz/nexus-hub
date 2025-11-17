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
) -> None:
    """
    Log a tool call to tool_call_logs table.
    
    Args:
        tenant_id: Tenant ID
        tool_name: Canonical tool name
        provider: Tool provider
        arguments: Tool arguments
        result_summary: Tool result summary (may be trimmed)
        status: 'success' | 'failure'
        error_message: Error message if status is 'failure'
        latency_ms: Latency in milliseconds
        cost: Cost in dollars
        conversation_id: Optional conversation ID
        message_id: Optional message ID
        tool_id: Optional tool ID from tools table
    """
    with get_db_session(tenant_id) as session:
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
                "result_summary": json.dumps(result_summary or {}),
                "status": status,
                "error_message": error_message,
                "latency_ms": latency_ms,
                "cost": cost,
            }
        )

