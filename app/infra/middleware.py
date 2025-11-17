"""Request middleware for tracking, CORS, and other cross-cutting concerns."""

import uuid
import time
from typing import Callable
from fastapi import Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Middleware to add request ID to all requests."""
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Generate or get request ID
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        
        # Add to request state
        request.state.request_id = request_id
        
        # Process request
        response = await call_next(request)
        
        # Add request ID to response headers
        response.headers["X-Request-ID"] = request_id
        
        return response


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware to log request/response details."""
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        import logging
        logger = logging.getLogger("app.request")
        
        # Get request ID
        request_id = getattr(request.state, "request_id", "unknown")
        
        # Log request
        start_time = time.time()
        logger.info(
            "Request started",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "client": request.client.host if request.client else None,
            }
        )
        
        try:
            response = await call_next(request)
            duration_ms = int((time.time() - start_time) * 1000)
            
            # Log response
            logger.info(
                "Request completed",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                }
            )
            
            # Add timing header
            response.headers["X-Response-Time-Ms"] = str(duration_ms)
            
            return response
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error(
                "Request failed",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "error": str(e),
                    "duration_ms": duration_ms,
                },
                exc_info=True,
            )
            raise


def setup_cors(app):
    """Setup CORS middleware."""
    import os
    from app.infra.config import config
    
    # Get allowed origins from config
    cors_origins_env = os.getenv("CORS_ORIGINS", "")
    if cors_origins_env:
        # SECURITY: Never use wildcard in production
        allowed_origins = [origin.strip() for origin in cors_origins_env.split(",") if origin.strip()]
        # Filter out wildcards in production
        if config.APP_ENV != "development":
            allowed_origins = [origin for origin in allowed_origins if origin != "*"]
    elif config.APP_ENV == "development":
        # Only allow wildcard in development
        allowed_origins = ["*"]
    else:
        # Production default: no CORS unless explicitly configured
        allowed_origins = []
    
    # SECURITY: In production, restrict methods and headers
    if config.APP_ENV == "production":
        allowed_methods = ["GET", "POST", "PUT", "DELETE", "OPTIONS"]
        allowed_headers = [
            "Content-Type",
            "Authorization",
            "X-API-Key",
            "X-Request-ID",
        ]
    else:
        allowed_methods = ["*"]
        allowed_headers = ["*"]
    
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=allowed_methods,
        allow_headers=allowed_headers,
        expose_headers=["X-Request-ID", "X-Response-Time-Ms", "X-RateLimit-*"],
    )

