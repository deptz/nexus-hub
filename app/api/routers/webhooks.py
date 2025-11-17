"""Webhooks API router."""

from typing import Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.orm import Session
import uuid

from app.infra.database import get_db
from app.models.message import CanonicalMessage, MessageParty, MessageContent
from app.api.models import TelegramWebhookResponse
from app.api.utils import handle_inbound_message_sync
from app.adapters.telegram_adapter import telegram_to_canonical, send_telegram_message
from app.logging.event_logger import log_event
import os

router = APIRouter()


@router.post("/webhooks/telegram", tags=["Webhooks"], response_model=TelegramWebhookResponse)
async def handle_telegram_webhook(
    update: Dict[str, Any],
    tenant_id: Optional[str] = Query(None, description="Tenant ID (or set TELEGRAM_DEFAULT_TENANT_ID env var)"),
    db: Session = Depends(get_db),
):
    """Handle Telegram webhook updates."""
    import time
    start_time = time.time()
    
    try:
        # Resolve tenant_id
        if not tenant_id:
            tenant_id = os.getenv("TELEGRAM_DEFAULT_TENANT_ID")
            if not tenant_id:
                raise HTTPException(
                    status_code=400,
                    detail="tenant_id is required (provide via query param or TELEGRAM_DEFAULT_TENANT_ID env var)"
                )
        
        # Convert Telegram update to CanonicalMessage
        canonical_msg = telegram_to_canonical(update, tenant_id)
        
        # Extract chat_id from metadata for later use
        chat_id = canonical_msg.metadata.get("telegram_chat_id")
        
        # Process message
        result = await handle_inbound_message_sync(canonical_msg, db)
        
        # Send response to Telegram
        if result.get("status") == "success" and result.get("message"):
            response_text = result["message"].get("content", {}).get("text", "")
            if response_text:
                try:
                    await send_telegram_message(chat_id=chat_id, text=response_text)
                except Exception as e:
                    await log_event(
                        tenant_id=tenant_id,
                        event_type="telegram_send_error",
                        status="failure",
                        payload={"error": str(e), "chat_id": chat_id},
                    )
        
        latency_ms = int((time.time() - start_time) * 1000)
        
        return TelegramWebhookResponse(
            status="success",
            message="Message processed and sent to Telegram",
            latency_ms=latency_ms,
        )
    
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        error_id = str(uuid.uuid4())
        await log_event(
            tenant_id=tenant_id or "unknown",
            event_type="telegram_webhook_error",
            status="failure",
            payload={"error": str(e), "error_id": error_id},
        )
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error. Error ID: {error_id}"
        )

