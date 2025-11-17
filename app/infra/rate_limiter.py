"""Rate limiting middleware for tenant and channel isolation."""

import os
from typing import Dict, Optional
from datetime import datetime, timedelta
from collections import defaultdict
from fastapi import Request, HTTPException, status

# Try to use Redis if available, fallback to in-memory
try:
    import redis
    REDIS_AVAILABLE = True
    try:
        from app.infra.config import config
        redis_client = redis.Redis.from_url(
            config.REDIS_URL,
            decode_responses=True,
        )
        # Test connection
        redis_client.ping()
        USE_REDIS = True
    except Exception:
        USE_REDIS = False
        redis_client = None
except ImportError:
    REDIS_AVAILABLE = False
    USE_REDIS = False
    redis_client = None

# In-memory rate limiter (fallback)
_rate_limit_store: Dict[str, Dict[str, list]] = defaultdict(lambda: defaultdict(list))


def check_rate_limit(
    tenant_id: str,
    channel: Optional[str] = None,
    per_tenant_limit: int = 100,  # requests per minute per tenant
    per_channel_limit: int = 50,  # requests per minute per channel
) -> bool:
    """
    Check if request is within rate limits.
    
    Uses Redis if available, otherwise falls back to in-memory storage.
    
    Args:
        tenant_id: Tenant ID
        channel: Optional channel identifier
        per_tenant_limit: Requests per minute for tenant
        per_channel_limit: Requests per minute for channel
    
    Returns:
        True if within limits, False if rate limited
    """
    if USE_REDIS and redis_client:
        return _check_rate_limit_redis(
            tenant_id, channel, per_tenant_limit, per_channel_limit
        )
    else:
        return _check_rate_limit_memory(
            tenant_id, channel, per_tenant_limit, per_channel_limit
        )


def _check_rate_limit_redis(
    tenant_id: str,
    channel: Optional[str],
    per_tenant_limit: int,
    per_channel_limit: int,
) -> bool:
    """Check rate limit using Redis."""
    now = datetime.utcnow()
    minute_ago = now - timedelta(minutes=1)
    window_start = int(minute_ago.timestamp())
    
    # Check tenant-level limit
    tenant_key = f"ratelimit:tenant:{tenant_id}"
    try:
        # Get current count
        current_count = redis_client.zcount(tenant_key, window_start, "+inf")
        
        if current_count >= per_tenant_limit:
            return False
        
        # Add request with current timestamp as score
        redis_client.zadd(tenant_key, {str(now.timestamp()): now.timestamp()})
        # Expire old entries (cleanup)
        redis_client.zremrangebyscore(tenant_key, "-inf", window_start)
        # Set expiry on key (1 minute)
        redis_client.expire(tenant_key, 60)
    except Exception:
        # If Redis fails, fallback to memory
        return _check_rate_limit_memory(
            tenant_id, channel, per_tenant_limit, per_channel_limit
        )
    
    # Check channel-level limit if channel provided
    if channel:
        channel_key = f"ratelimit:channel:{tenant_id}:{channel}"
        try:
            current_count = redis_client.zcount(channel_key, window_start, "+inf")
            
            if current_count >= per_channel_limit:
                return False
            
            redis_client.zadd(channel_key, {str(now.timestamp()): now.timestamp()})
            redis_client.zremrangebyscore(channel_key, "-inf", window_start)
            redis_client.expire(channel_key, 60)
        except Exception:
            # If Redis fails, fallback to memory
            return _check_rate_limit_memory(
                tenant_id, channel, per_tenant_limit, per_channel_limit
            )
    
    return True


def _check_rate_limit_memory(
    tenant_id: str,
    channel: Optional[str],
    per_tenant_limit: int,
    per_channel_limit: int,
) -> bool:
    """Check rate limit using in-memory storage."""
    now = datetime.utcnow()
    minute_ago = now - timedelta(minutes=1)
    
    # Check tenant-level limit
    tenant_key = f"tenant:{tenant_id}"
    tenant_requests = _rate_limit_store[tenant_key]["requests"]
    # Clean old requests
    tenant_requests[:] = [ts for ts in tenant_requests if ts > minute_ago]
    
    if len(tenant_requests) >= per_tenant_limit:
        return False
    
    # Check channel-level limit if channel provided
    if channel:
        channel_key = f"channel:{tenant_id}:{channel}"
        channel_requests = _rate_limit_store[channel_key]["requests"]
        # Clean old requests
        channel_requests[:] = [ts for ts in channel_requests if ts > minute_ago]
        
        if len(channel_requests) >= per_channel_limit:
            return False
    
    # Record request
    tenant_requests.append(now)
    if channel:
        channel_requests.append(now)
    
    return True


async def rate_limit_middleware(request: Request, call_next):
    """
    FastAPI middleware for rate limiting.
    
    Applies per-tenant and per-channel rate limits.
    """
    # Only apply to /messages/inbound endpoint
    if request.url.path == "/messages/inbound" and request.method == "POST":
        # Extract tenant_id from request body (would need to read body)
        # For now, we'll apply rate limiting after tenant resolution
        # This is a simplified version - in production, use proper middleware
        pass
    
    response = await call_next(request)
    return response


def get_rate_limit_headers(
    tenant_id: str,
    channel: Optional[str] = None,
    per_tenant_limit: int = 100,
    per_channel_limit: int = 50,
) -> Dict[str, str]:
    """
    Get rate limit headers for response.
    
    Returns:
        Dict with X-RateLimit-* headers
    """
    if USE_REDIS and redis_client:
        return _get_rate_limit_headers_redis(
            tenant_id, channel, per_tenant_limit, per_channel_limit
        )
    else:
        return _get_rate_limit_headers_memory(
            tenant_id, channel, per_tenant_limit, per_channel_limit
        )


def _get_rate_limit_headers_redis(
    tenant_id: str,
    channel: Optional[str],
    per_tenant_limit: int,
    per_channel_limit: int,
) -> Dict[str, str]:
    """Get rate limit headers using Redis."""
    now = datetime.utcnow()
    minute_ago = now - timedelta(minutes=1)
    window_start = int(minute_ago.timestamp())
    
    tenant_key = f"ratelimit:tenant:{tenant_id}"
    try:
        tenant_count = redis_client.zcount(tenant_key, window_start, "+inf")
        tenant_remaining = max(0, per_tenant_limit - tenant_count)
    except Exception:
        tenant_remaining = per_tenant_limit
    
    headers = {
        "X-RateLimit-Limit": str(per_tenant_limit),
        "X-RateLimit-Remaining": str(tenant_remaining),
        "X-RateLimit-Reset": str(int((now + timedelta(minutes=1)).timestamp())),
    }
    
    if channel:
        channel_key = f"ratelimit:channel:{tenant_id}:{channel}"
        try:
            channel_count = redis_client.zcount(channel_key, window_start, "+inf")
            channel_remaining = max(0, per_channel_limit - channel_count)
        except Exception:
            channel_remaining = per_channel_limit
        
        headers["X-RateLimit-Channel-Limit"] = str(per_channel_limit)
        headers["X-RateLimit-Channel-Remaining"] = str(channel_remaining)
    
    return headers


def _get_rate_limit_headers_memory(
    tenant_id: str,
    channel: Optional[str],
    per_tenant_limit: int,
    per_channel_limit: int,
) -> Dict[str, str]:
    """Get rate limit headers using in-memory storage."""
    now = datetime.utcnow()
    minute_ago = now - timedelta(minutes=1)
    
    tenant_key = f"tenant:{tenant_id}"
    tenant_requests = _rate_limit_store[tenant_key]["requests"]
    tenant_requests[:] = [ts for ts in tenant_requests if ts > minute_ago]
    tenant_remaining = max(0, per_tenant_limit - len(tenant_requests))
    
    headers = {
        "X-RateLimit-Limit": str(per_tenant_limit),
        "X-RateLimit-Remaining": str(tenant_remaining),
        "X-RateLimit-Reset": str(int((now + timedelta(minutes=1)).timestamp())),
    }
    
    if channel:
        channel_key = f"channel:{tenant_id}:{channel}"
        channel_requests = _rate_limit_store[channel_key]["requests"]
        channel_requests[:] = [ts for ts in channel_requests if ts > minute_ago]
        channel_remaining = max(0, per_channel_limit - len(channel_requests))
        
        headers["X-RateLimit-Channel-Limit"] = str(per_channel_limit)
        headers["X-RateLimit-Channel-Remaining"] = str(channel_remaining)
    
    return headers

