"""MCP (Model Context Protocol) client for tool execution."""

import json
import asyncio
import time
from typing import Dict, Any, Optional
import httpx
import websockets
from app.models.tenant import TenantContext
from app.models.tool import ToolDefinition


class MCPClient:
    """Client for MCP server tool execution.
    
    Supports both HTTP and WebSocket transports.
    MCP protocol uses JSON-RPC 2.0 for communication.
    """
    
    async def execute(
        self,
        tenant_ctx: TenantContext,
        tool_def: ToolDefinition,
        args: Dict[str, Any],
        execution_context: Optional[Dict[str, Any]] = None,  # NEW: Immutable execution context
    ) -> Dict[str, Any]:
        """
        Execute an MCP tool for a tenant.
        
        SECURITY: Injects immutable context headers (X-Tenant-ID, X-User-External-ID) from
        execution_context. These headers come from authentication, not from LLM.
        
        Args:
            tenant_ctx: TenantContext with MCP server configs
            tool_def: ToolDefinition with implementation_ref containing mcp_server_name and mcp_tool_name
            args: Tool arguments (user-scoped params should already be overridden)
            execution_context: Immutable execution context from authentication (tenant_id, user_external_id, conversation_id)
        
        Returns:
            Dict with tool execution result
        
        Raises:
            ValueError: If MCP server config not found or tool not found
            RuntimeError: If MCP server connection or execution fails
        """
        # Extract MCP server name from implementation_ref
        impl_ref = tool_def.implementation_ref
        if not isinstance(impl_ref, dict):
            raise ValueError(f"Invalid implementation_ref for MCP tool: {impl_ref}")
        
        mcp_server_name = impl_ref.get("mcp_server_name")
        mcp_tool_name = impl_ref.get("mcp_tool_name") or tool_def.name
        
        if not mcp_server_name:
            raise ValueError(f"MCP server name not found in implementation_ref: {impl_ref}")
        
        # Get MCP server config from tenant context
        mcp_configs = tenant_ctx.mcp_configs or {}
        server_config = mcp_configs.get(mcp_server_name)
        
        if not server_config:
            raise ValueError(f"MCP server '{mcp_server_name}' not found in tenant config")
        
        # SECURITY: Defense-in-depth validation - verify server belongs to tenant
        server_id = server_config.get("server_id")
        if server_id:
            await self._validate_server_ownership(tenant_ctx.tenant_id, server_id)
        
        endpoint = server_config.get("endpoint")
        if not endpoint:
            raise ValueError(f"MCP server '{mcp_server_name}' missing endpoint")
        
        # SECURITY: Validate endpoint to prevent SSRF attacks
        # Block internal/localhost endpoints
        endpoint_lower = endpoint.lower()
        blocked_hosts = [
            "localhost", "127.0.0.1", "0.0.0.0", "::1",
            "169.254.",  # Link-local
            "10.", "172.16.", "172.17.", "172.18.", "172.19.",
            "172.20.", "172.21.", "172.22.", "172.23.", "172.24.",
            "172.25.", "172.26.", "172.27.", "172.28.", "172.29.",
            "172.30.", "172.31.", "192.168.",  # Private IP ranges
        ]
        
        # Parse URL to check host
        from urllib.parse import urlparse
        try:
            parsed = urlparse(endpoint)
            host = parsed.hostname or ""
            
            # Check for blocked hosts
            if any(host.startswith(blocked) or host == blocked for blocked in blocked_hosts):
                raise ValueError(f"MCP endpoint '{endpoint}' points to internal/private network. SSRF protection enabled.")
            
            # Additional validation: must be http/https/ws/wss
            if not endpoint_lower.startswith(("http://", "https://", "ws://", "wss://")):
                raise ValueError(f"Invalid MCP endpoint protocol. Must be http, https, ws, or wss.")
        except Exception as e:
            if isinstance(e, ValueError):
                raise
            raise ValueError(f"Invalid MCP endpoint URL: {str(e)}")
        
        # Get auth config if present
        auth_config = server_config.get("auth_config", {})
        
        # Audit logging: Log MCP tool execution attempt
        start_time = time.time()
        try:
            # Determine transport (HTTP or WebSocket)
            # Pass execution_context for header injection
            if endpoint.startswith("ws://") or endpoint.startswith("wss://"):
                result = await self._execute_websocket(
                    tenant_ctx, mcp_server_name, endpoint, auth_config, mcp_tool_name, args, execution_context
                )
            else:
                result = await self._execute_http(
                    tenant_ctx, mcp_server_name, endpoint, auth_config, mcp_tool_name, args, execution_context
                )
            
            # Audit logging: Log successful execution
            latency_ms = int((time.time() - start_time) * 1000)
            await self._log_mcp_tool_execution(
                tenant_ctx.tenant_id,
                mcp_server_name,
                mcp_tool_name,
                "success",
                latency_ms=latency_ms
            )
            
            return result
            
        except Exception as e:
            # Audit logging: Log failed execution
            latency_ms = int((time.time() - start_time) * 1000)
            await self._log_mcp_tool_execution(
                tenant_ctx.tenant_id,
                mcp_server_name,
                mcp_tool_name,
                "failure",
                error_message=str(e),
                latency_ms=latency_ms
            )
            raise
    
    async def _validate_server_ownership(self, tenant_id: str, server_id: str) -> None:
        """
        Validate that MCP server belongs to the tenant (defense-in-depth).
        
        Args:
            tenant_id: Tenant ID
            server_id: MCP server ID
            
        Raises:
            ValueError: If server does not belong to tenant
        """
        from app.infra.database import get_db_session
        from sqlalchemy import text
        
        with get_db_session(tenant_id) as session:
            row = session.execute(
                text("""
                    SELECT tenant_id FROM mcp_servers
                    WHERE id = :server_id
                """),
                {"server_id": server_id}
            ).fetchone()
            
            if not row or str(row.tenant_id) != tenant_id:
                raise ValueError(f"MCP server '{server_id}' does not belong to tenant '{tenant_id}'")
    
    async def _log_mcp_tool_execution(
        self,
        tenant_id: str,
        server_name: str,
        tool_name: str,
        status: str,
        error_message: Optional[str] = None,
        latency_ms: Optional[int] = None,
    ) -> None:
        """
        Log MCP tool execution for audit purposes.
        
        Args:
            tenant_id: Tenant ID
            server_name: MCP server name
            tool_name: Tool name
            status: 'success' or 'failure'
            error_message: Error message if failed
            latency_ms: Execution latency in milliseconds
        """
        try:
            from app.logging.event_logger import log_event
            
            await log_event(
                tenant_id=tenant_id,
                event_type="mcp_tool_executed",
                provider="mcp",
                status=status,
                latency_ms=latency_ms,
                payload={
                    "server_name": server_name,
                    "tool_name": tool_name,
                    "error": error_message if status == "failure" else None,
                }
            )
        except Exception as e:
            # Don't fail tool execution if logging fails
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to log MCP tool execution: {str(e)}")
    
    async def _execute_http(
        self,
        tenant_ctx: TenantContext,
        server_name: str,
        endpoint: str,
        auth_config: Dict[str, Any],
        tool_name: str,
        args: Dict[str, Any],
        execution_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute MCP tool via HTTP transport."""
        # Build JSON-RPC 2.0 request
        try:
            task = asyncio.current_task()
            task_name = task.get_name() if task else None
        except RuntimeError:
            task_name = None
        request_id = f"mcp_{task_name or 'req'}"
        jsonrpc_request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": args,
            },
        }
        
        # Prepare headers
        headers = {
            "Content-Type": "application/json",
        }
        
        # SECURITY: Add immutable context headers (always included, from execution_context)
        # These headers come from authentication, not from LLM
        if execution_context:
            headers["X-Tenant-ID"] = execution_context.get("tenant_id", tenant_ctx.tenant_id)
            headers["X-User-External-ID"] = execution_context.get("user_external_id", "")
            if execution_context.get("conversation_id"):
                headers["X-Conversation-ID"] = execution_context["conversation_id"]
        
        # Legacy: Add tenant context header if configured (for backward compatibility)
        if auth_config.get("include_tenant_context", False) and "X-Tenant-ID" not in headers:
            headers["X-Tenant-ID"] = tenant_ctx.tenant_id
        
        # Add auth headers if configured
        # SECURITY: Never log secrets or tokens
        auth_type = auth_config.get("type")
        if auth_type == "bearer":
            token = auth_config.get("token") or auth_config.get("vault_secret")
            if token:
                # SECURITY: Get token from vault if it's a reference
                if isinstance(token, str) and token.startswith("vault://"):
                    from app.infra.secrets import get_secret
                    token = get_secret(token)
                if token:
                    headers["Authorization"] = f"Bearer {token}"
        elif auth_type == "api_key":
            api_key = auth_config.get("api_key") or auth_config.get("vault_secret")
            # SECURITY: Get key from vault if it's a reference
            if isinstance(api_key, str) and api_key.startswith("vault://"):
                from app.infra.secrets import get_secret
                api_key = get_secret(api_key)
            key_name = auth_config.get("key_name", "X-API-Key")
            if api_key:
                headers[key_name] = api_key
        
        # Make HTTP request
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.post(
                    endpoint,
                    json=jsonrpc_request,
                    headers=headers,
                )
                response.raise_for_status()
                
                result = response.json()
                
                # Handle JSON-RPC 2.0 response
                if "error" in result:
                    error = result["error"]
                    raise RuntimeError(
                        f"MCP tool execution failed: {error.get('message', 'Unknown error')} "
                        f"(code: {error.get('code', 'unknown')})"
                    )
                
                return result.get("result", {})
                
            except httpx.HTTPError as e:
                raise RuntimeError(f"MCP HTTP request failed: {str(e)}")
    
    async def _execute_websocket(
        self,
        tenant_ctx: TenantContext,
        server_name: str,
        endpoint: str,
        auth_config: Dict[str, Any],
        tool_name: str,
        args: Dict[str, Any],
        execution_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute MCP tool via WebSocket transport."""
        # Build JSON-RPC 2.0 request
        try:
            task = asyncio.current_task()
            task_name = task.get_name() if task else None
        except RuntimeError:
            task_name = None
        request_id = f"mcp_{task_name or 'req'}"
        jsonrpc_request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": args,
            },
        }
        
        # Prepare headers for WebSocket
        headers = {}
        
        # SECURITY: Add immutable context headers (always included, from execution_context)
        # These headers come from authentication, not from LLM
        if execution_context:
            headers["X-Tenant-ID"] = execution_context.get("tenant_id", tenant_ctx.tenant_id)
            headers["X-User-External-ID"] = execution_context.get("user_external_id", "")
            if execution_context.get("conversation_id"):
                headers["X-Conversation-ID"] = execution_context["conversation_id"]
        
        # Legacy: Add tenant context header if configured (for backward compatibility)
        if auth_config.get("include_tenant_context", False) and "X-Tenant-ID" not in headers:
            headers["X-Tenant-ID"] = tenant_ctx.tenant_id
        
        # Add auth headers if configured
        # SECURITY: Never log secrets or tokens
        auth_type = auth_config.get("type")
        if auth_type == "bearer":
            token = auth_config.get("token") or auth_config.get("vault_secret")
            if token:
                # SECURITY: Get token from vault if it's a reference
                if isinstance(token, str) and token.startswith("vault://"):
                    from app.infra.secrets import get_secret
                    token = get_secret(token)
                if token:
                    headers["Authorization"] = f"Bearer {token}"
        elif auth_type == "api_key":
            api_key = auth_config.get("api_key") or auth_config.get("vault_secret")
            # SECURITY: Get key from vault if it's a reference
            if isinstance(api_key, str) and api_key.startswith("vault://"):
                from app.infra.secrets import get_secret
                api_key = get_secret(api_key)
            key_name = auth_config.get("key_name", "X-API-Key")
            if api_key:
                headers[key_name] = api_key
        
        try:
            async with websockets.connect(
                endpoint,
                extra_headers=headers,
                ping_interval=None,  # Disable ping for short-lived connections
            ) as websocket:
                # Send request
                await websocket.send(json.dumps(jsonrpc_request))
                
                # Wait for response (with timeout)
                try:
                    response_text = await asyncio.wait_for(
                        websocket.recv(),
                        timeout=30.0
                    )
                except asyncio.TimeoutError:
                    raise RuntimeError("MCP WebSocket request timed out")
                
                result = json.loads(response_text)
                
                # Handle JSON-RPC 2.0 response
                if "error" in result:
                    error = result["error"]
                    raise RuntimeError(
                        f"MCP tool execution failed: {error.get('message', 'Unknown error')} "
                        f"(code: {error.get('code', 'unknown')})"
                    )
                
                return result.get("result", {})
                
        except websockets.exceptions.WebSocketException as e:
            raise RuntimeError(f"MCP WebSocket connection failed: {str(e)}")
        except json.JSONDecodeError as e:
            raise RuntimeError(f"MCP response parsing failed: {str(e)}")


mcp_client = MCPClient()

