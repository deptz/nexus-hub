"""FastAPI orchestrator main application."""

import json
import time
import uuid
from datetime import datetime
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, HTTPException, Depends, Request, Security, status, Query
from fastapi.openapi.utils import get_openapi
from fastapi.security import APIKeyHeader, APIKeyQuery
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import text

# Core imports for app setup
from app.infra.database import get_db
from app.infra.metrics import get_metrics_response
from app.infra.auth import verify_api_key, require_tenant_access
from app.infra.validation import validate_tenant_id, validate_prompt_content

# Graceful shutdown handlers
import signal
import asyncio
from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown."""
    # Startup
    from app.infra.logging import app_logger
    app_logger.info("Application starting up")
    
    yield
    
    # Shutdown
    app_logger.info("Application shutting down")
    
    # Close database connections
    from app.infra.database import engine
    engine.dispose()
    
    # Close Redis connections
    try:
        from app.infra.rate_limiter import redis_client
        if redis_client:
            redis_client.close()
    except:
        pass


# Check for test mode
import os
SWAGGER_TEST_MODE = os.getenv("SWAGGER_TEST_MODE", "false").lower() == "true"
APP_ENV = os.getenv("APP_ENV", "development")

# Create app with lifespan
app = FastAPI(
    title="Nexus Hub API",
    description="""
    Nexus Hub API provides a unified interface for managing multi-tenant AI conversations,
    knowledge bases, prompts, and tools across multiple LLM providers (OpenAI, Gemini).
    
    ## Features
    
    - **Message Processing**: Send and receive messages through various channels (web, telegram, etc.)
    - **Knowledge Base Management**: Create and manage knowledge bases for RAG (Retrieval Augmented Generation)
    - **Prompt Management**: Configure and update tenant-specific system prompts
    - **Logging & Debugging**: View event logs and tool call logs for debugging
    - **API Key Management**: Create and manage API keys for tenant access
    
    ## Authentication
    
    Most endpoints require API key authentication via:
    - Header: `X-API-Key: <your-api-key>`
    - Query parameter: `?api_key=<your-api-key>`
    
    **Test Mode**: When `SWAGGER_TEST_MODE=true` is set in non-production environments, 
    authentication may be bypassed for testing purposes.
    """,
    version="1.0.0",
    lifespan=lifespan,
    tags_metadata=[
        {
            "name": "Messages",
            "description": "Send and receive messages, check message status",
        },
        {
            "name": "Conversations",
            "description": "Manage conversations, view conversation history and statistics",
        },
        {
            "name": "Analytics",
            "description": "Analytics, KPIs, and usage statistics for reporting and dashboards",
        },
        {
            "name": "Costs",
            "description": "Cost calculation, breakdown, and estimation endpoints",
        },
        {
            "name": "Knowledge Bases",
            "description": "Manage knowledge bases (CRUD operations)",
        },
        {
            "name": "Logs",
            "description": "View event logs and tool call logs for debugging",
        },
        {
            "name": "Tenant Management",
            "description": "Manage tenant prompts, API keys, tools, and configuration",
        },
        {
            "name": "Webhooks",
            "description": "Webhook endpoints for external services (Telegram, etc.)",
        },
        {
            "name": "MCP Servers",
            "description": "Manage MCP (Model Context Protocol) servers and tools",
        },
        {
            "name": "Plans",
            "description": "Agentic planning endpoints for creating, viewing, and refining multi-step execution plans",
        },
        {
            "name": "Tasks",
            "description": "Agentic task management endpoints for long-running operations, state persistence, and task resumption",
        },
        {
            "name": "Health",
            "description": "Health check and monitoring endpoints",
        },
    ],
)

# Setup middleware
from app.infra.middleware import RequestIDMiddleware, RequestLoggingMiddleware, setup_cors
from app.infra.timeout import TimeoutMiddleware, REQUEST_TIMEOUT

app.add_middleware(RequestIDMiddleware)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(TimeoutMiddleware, timeout=REQUEST_TIMEOUT)
setup_cors(app)

# Import and register routers
from app.api.routers import (
    messages,
    conversations,
    analytics,
    costs,
    logs,
    webhooks,
    health,
    tenant_management,
    knowledge_bases,
    mcp_servers,
    channels,
    rag_documents,
    tasks,
    plans,
)

# Register routers
app.include_router(messages.router)
app.include_router(conversations.router)
app.include_router(analytics.router)
app.include_router(costs.router)
app.include_router(logs.router)
app.include_router(webhooks.router)
app.include_router(health.router)
app.include_router(tenant_management.router)
app.include_router(knowledge_bases.router)
app.include_router(mcp_servers.router)
app.include_router(channels.router)
app.include_router(rag_documents.router)
app.include_router(tasks.router)
app.include_router(plans.router)

# Configure OpenAPI security schemes
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    
    # Add security scheme
    if "components" not in openapi_schema:
        openapi_schema["components"] = {}
    if "securitySchemes" not in openapi_schema["components"]:
        openapi_schema["components"]["securitySchemes"] = {}
    
    openapi_schema["components"]["securitySchemes"]["ApiKeyAuth"] = {
        "type": "apiKey",
        "in": "header",
        "name": "X-API-Key",
        "description": "API Key authentication. Provide your API key in the X-API-Key header or as api_key query parameter."
    }
    
    # Add test mode info if enabled
    if SWAGGER_TEST_MODE and APP_ENV != "production":
        openapi_schema["info"]["description"] += f"\n\n⚠️ **TEST MODE ENABLED**: Authentication is bypassed for testing purposes. Set `SWAGGER_TEST_MODE=true` in non-production environments."
    
    # Apply security to all paths except health checks and webhooks (they have their own auth or none)
    # FastAPI automatically adds security requirements based on Security() dependencies in route handlers
    # But we can add global security as default
    if not SWAGGER_TEST_MODE or APP_ENV == "production":
        # Only add global security requirement if not in test mode
        # Individual endpoints with Security() will override this
        pass
    
    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi

# Request size limits
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

MAX_REQUEST_SIZE = 1024 * 1024  # 1MB

# Request/Response Models have been moved to app/api/models.py
# Import them from there when needed
from app.api.models import InboundMessageResponse, TelegramWebhookResponse

@app.middleware("http")
async def request_size_limit_middleware(request: Request, call_next):
    """Enforce request size limits."""
    content_length = request.headers.get("content-length")
    if content_length:
        size = int(content_length)
        if size > MAX_REQUEST_SIZE:
            raise HTTPException(
                status_code=413,
                detail=f"Request too large. Maximum size: {MAX_REQUEST_SIZE} bytes"
            )
    return await call_next(request)

# Utility functions have been moved to app/api/utils.py
# MAX_TOOL_STEPS and helper functions are now in app/api/utils.py

# Error handlers
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle request validation errors."""
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors(), "body": exc.body},
    )

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Handle HTTP exceptions."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle all other exceptions."""
    error_id = str(uuid.uuid4())
    from app.infra.logging import app_logger
    app_logger.error(f"Unhandled exception: {exc}", exc_info=True, extra={"error_id": error_id})
    return JSONResponse(
        status_code=500,
        content={"detail": f"Internal server error. Error ID: {error_id}"},
    )


if __name__ == "__main__":
    import uvicorn
    
    # Setup signal handlers for graceful shutdown
    def signal_handler(sig, frame):
        print("\nShutting down gracefully...")
        # Uvicorn handles shutdown automatically
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        timeout_keep_alive=30,
        timeout_graceful_shutdown=30,
    )

