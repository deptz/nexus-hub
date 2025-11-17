"""Request timeout configuration and middleware."""

import asyncio
from typing import Optional
from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware


class TimeoutMiddleware(BaseHTTPMiddleware):
    """Middleware to enforce request timeouts."""
    
    def __init__(self, app, timeout: int = 60):
        """
        Initialize timeout middleware.
        
        Args:
            app: FastAPI application
            timeout: Request timeout in seconds (default: 60)
        """
        super().__init__(app)
        self.timeout = timeout
    
    async def dispatch(self, request: Request, call_next):
        """Process request with timeout."""
        try:
            response = await asyncio.wait_for(
                call_next(request),
                timeout=self.timeout
            )
            return response
        except asyncio.TimeoutError:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail=f"Request timeout after {self.timeout} seconds"
            )


# Timeout configurations
REQUEST_TIMEOUT = 60  # 60 seconds for general requests
LLM_CALL_TIMEOUT = 120  # 2 minutes for LLM calls
TOOL_EXECUTION_TIMEOUT = 30  # 30 seconds for tool execution
DATABASE_QUERY_TIMEOUT = 10  # 10 seconds for DB queries

