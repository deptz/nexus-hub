"""Worker function for processing messages from queue."""

import asyncio
from typing import Dict, Any
from app.models.message import CanonicalMessage
from app.main import handle_inbound_message_sync


def process_inbound_message(message_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Process an inbound message (called by RQ worker).
    
    This is a synchronous wrapper around the async handler.
    
    Args:
        message_data: CanonicalMessage as dict
    
    Returns:
        Result dict with status and response
    """
    # Convert dict to CanonicalMessage
    message = CanonicalMessage(**message_data)
    
    # Run async handler in event loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        # Import here to avoid circular imports
        from app.infra.database import get_db
        from sqlalchemy.orm import Session
        
        # Create a DB session for this worker
        db_gen = get_db()
        db = next(db_gen)
        
        try:
            result = loop.run_until_complete(
                handle_inbound_message_sync(message, db)
            )
            return result
        finally:
            db.close()
            try:
                next(db_gen, None)  # Clean up generator
            except:
                pass
    finally:
        loop.close()


