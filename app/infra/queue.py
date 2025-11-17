"""Message queue system for async task processing."""

import os
import json
from typing import Optional, Dict, Any, Callable
from redis import Redis
from rq import Queue
from rq.job import Job, JobStatus
from app.infra.config import config

# Initialize Redis connection
redis_conn = Redis.from_url(config.REDIS_URL, decode_responses=True)

# Create queues
default_queue = Queue("default", connection=redis_conn)
high_priority_queue = Queue("high_priority", connection=redis_conn)
low_priority_queue = Queue("low_priority", connection=redis_conn)


def enqueue_message_processing(
    message_data: Dict[str, Any],
    priority: str = "default",
) -> str:
    """
    Enqueue a message for async processing.
    
    Args:
        message_data: CanonicalMessage as dict
        priority: 'high', 'default', or 'low'
    
    Returns:
        Job ID for tracking
    """
    from app.workers.message_processor import process_inbound_message
    
    # Select queue based on priority
    queue = {
        "high": high_priority_queue,
        "low": low_priority_queue,
        "default": default_queue,
    }.get(priority, default_queue)
    
    # Enqueue job
    job = queue.enqueue(
        process_inbound_message,
        message_data,
        job_timeout=300,  # 5 minutes timeout
        result_ttl=3600,  # Keep result for 1 hour
    )
    
    return job.id


def get_job_status(job_id: str) -> Dict[str, Any]:
    """
    Get status of a queued job.
    
    Args:
        job_id: Job ID returned from enqueue
    
    Returns:
        Dict with status, result (if completed), error (if failed)
    """
    try:
        job = Job.fetch(job_id, connection=redis_conn)
        
        status_info = {
            "job_id": job_id,
            "status": job.get_status(),
            "created_at": job.created_at.isoformat() if job.created_at else None,
        }
        
        if job.is_finished:
            status_info["result"] = job.result
            status_info["ended_at"] = job.ended_at.isoformat() if job.ended_at else None
        elif job.is_failed:
            status_info["error"] = str(job.exc_info) if job.exc_info else "Unknown error"
            status_info["ended_at"] = job.ended_at.isoformat() if job.ended_at else None
        elif job.is_started:
            status_info["started_at"] = job.started_at.isoformat() if job.started_at else None
        
        return status_info
    except Exception as e:
        return {
            "job_id": job_id,
            "status": "not_found",
            "error": str(e),
        }


def cancel_job(job_id: str) -> bool:
    """
    Cancel a queued job.
    
    Args:
        job_id: Job ID to cancel
    
    Returns:
        True if cancelled, False if not found or already completed
    """
    try:
        job = Job.fetch(job_id, connection=redis_conn)
        if job.get_status() in [JobStatus.QUEUED, JobStatus.STARTED]:
            job.cancel()
            return True
        return False
    except Exception:
        return False

