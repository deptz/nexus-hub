"""Conversation stats computation and updates."""

from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.infra.database import get_db_session


async def update_conversation_stats(
    tenant_id: str,
    conversation_id: str,
    total_messages: Optional[int] = None,
    tool_calls: Optional[int] = None,
    resolved: Optional[bool] = None,
) -> None:
    """
    Update conversation stats.
    
    Args:
        tenant_id: Tenant ID
        conversation_id: Conversation ID
        total_messages: Optional message count (will be computed if None)
        tool_calls: Optional tool call count (will be computed if None)
        resolved: Optional resolved status
    """
    with get_db_session(tenant_id) as session:
        # Get current stats or create new
        stats_row = session.execute(
            text("""
                SELECT id, total_messages, tool_calls, resolved
                FROM conversation_stats
                WHERE tenant_id = :tenant_id AND conversation_id = :conversation_id
            """),
            {
                "tenant_id": tenant_id,
                "conversation_id": conversation_id,
            }
        ).fetchone()
        
        # Compute values if not provided
        if total_messages is None:
            msg_count = session.execute(
                text("""
                    SELECT COUNT(*) FROM messages
                    WHERE tenant_id = :tenant_id AND conversation_id = :conversation_id
                """),
                {
                    "tenant_id": tenant_id,
                    "conversation_id": conversation_id,
                }
            ).scalar()
            total_messages = msg_count or 0
        
        if tool_calls is None:
            tool_count = session.execute(
                text("""
                    SELECT COUNT(*) FROM tool_call_logs
                    WHERE tenant_id = :tenant_id AND conversation_id = :conversation_id
                """),
                {
                    "tenant_id": tenant_id,
                    "conversation_id": conversation_id,
                }
            ).scalar()
            tool_calls = tool_count or 0
        
        if stats_row:
            # Update existing
            update_fields = {
                "tenant_id": tenant_id,
                "conversation_id": conversation_id,
                "total_messages": total_messages,
                "tool_calls": tool_calls,
                "updated_at": "now()",
            }
            
            if resolved is not None:
                update_fields["resolved"] = resolved
            
            session.execute(
                text("""
                    UPDATE conversation_stats
                    SET total_messages = :total_messages,
                        tool_calls = :tool_calls,
                        resolved = COALESCE(:resolved, resolved),
                        updated_at = now()
                    WHERE tenant_id = :tenant_id AND conversation_id = :conversation_id
                """),
                {
                    "tenant_id": tenant_id,
                    "conversation_id": conversation_id,
                    "total_messages": total_messages,
                    "tool_calls": tool_calls,
                    "resolved": resolved,
                }
            )
        else:
            # Insert new
            session.execute(
                text("""
                    INSERT INTO conversation_stats (
                        tenant_id, conversation_id, total_messages, tool_calls, resolved
                    ) VALUES (
                        :tenant_id, :conversation_id, :total_messages, :tool_calls, :resolved
                    )
                """),
                {
                    "tenant_id": tenant_id,
                    "conversation_id": conversation_id,
                    "total_messages": total_messages,
                    "tool_calls": tool_calls,
                    "resolved": resolved or False,
                }
            )
        
        session.commit()


