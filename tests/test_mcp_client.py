"""Unit tests for MCP client."""

import pytest
import json
from unittest.mock import AsyncMock, patch, MagicMock
from app.adapters.mcp_client import MCPClient
from app.models.tenant import TenantContext
from app.models.tool import ToolDefinition


class TestMCPClient:
    """Test MCP client functionality."""
    
    @pytest.fixture
    def mcp_client(self):
        """Create MCP client instance."""
        return MCPClient()
    
    @pytest.fixture
    def tenant_ctx(self):
        """Create test tenant context with MCP config."""
        return TenantContext(
            tenant_id="test-tenant",
            llm_provider="openai",
            llm_model="gpt-4o-mini",
            allowed_tools=[],
            kb_configs={},
            mcp_configs={
                "test_server": {
                    "endpoint": "https://mcp.example.com/api",
                    "auth_config": {
                        "type": "bearer",
                        "token": "test-token-123"
                    }
                }
            },
            prompt_profile={},
            isolation_mode="shared_db"
        )
    
    @pytest.fixture
    def tool_def(self):
        """Create test tool definition."""
        return ToolDefinition(
            name="test_tool",
            description="Test MCP tool",
            parameters_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"}
                }
            },
            provider="mcp",
            implementation_ref={
                "mcp_server_name": "test_server",
                "mcp_tool_name": "get_data"
            }
        )
    
    @pytest.mark.asyncio
    async def test_execute_http_success(self, mcp_client, tenant_ctx, tool_def):
        """Test successful HTTP MCP tool execution."""
        mock_response = {
            "jsonrpc": "2.0",
            "id": "mcp_req",
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": "Test result"
                    }
                ]
            }
        }
        
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response_obj = MagicMock()
            mock_response_obj.json.return_value = mock_response
            mock_response_obj.raise_for_status = MagicMock()
            mock_client.post = AsyncMock(return_value=mock_response_obj)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client
            
            result = await mcp_client.execute(
                tenant_ctx,
                tool_def,
                {"query": "test"}
            )
            
            assert result == mock_response["result"]
            mock_client.post.assert_called_once()
            call_args = mock_client.post.call_args
            assert call_args[0][0] == "https://mcp.example.com/api"
            assert "Authorization" in call_args[1]["headers"]
            assert call_args[1]["headers"]["Authorization"] == "Bearer test-token-123"
    
    @pytest.mark.asyncio
    async def test_execute_http_error_response(self, mcp_client, tenant_ctx, tool_def):
        """Test HTTP MCP tool execution with JSON-RPC error."""
        mock_response = {
            "jsonrpc": "2.0",
            "id": "mcp_req",
            "error": {
                "code": -32603,
                "message": "Internal error"
            }
        }
        
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response_obj = MagicMock()
            mock_response_obj.json.return_value = mock_response
            mock_response_obj.raise_for_status = MagicMock()
            mock_client.post = AsyncMock(return_value=mock_response_obj)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client
            
            with pytest.raises(RuntimeError) as exc_info:
                await mcp_client.execute(tenant_ctx, tool_def, {"query": "test"})
            
            assert "MCP tool execution failed" in str(exc_info.value)
            assert "Internal error" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_execute_websocket_success(self, mcp_client, tenant_ctx, tool_def):
        """Test successful WebSocket MCP tool execution."""
        # Update tenant context to use WebSocket endpoint
        tenant_ctx.mcp_configs["test_server"]["endpoint"] = "wss://mcp.example.com/ws"
        
        mock_response = {
            "jsonrpc": "2.0",
            "id": "mcp_req",
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": "WebSocket result"
                    }
                ]
            }
        }
        
        with patch("websockets.connect") as mock_connect:
            mock_websocket = AsyncMock()
            mock_websocket.send = AsyncMock()
            mock_websocket.recv = AsyncMock(return_value=json.dumps(mock_response))
            mock_websocket.__aenter__ = AsyncMock(return_value=mock_websocket)
            mock_websocket.__aexit__ = AsyncMock(return_value=None)
            mock_connect.return_value = mock_websocket
            
            result = await mcp_client.execute(
                tenant_ctx,
                tool_def,
                {"query": "test"}
            )
            
            assert result == mock_response["result"]
            mock_websocket.send.assert_called_once()
            sent_data = json.loads(mock_websocket.send.call_args[0][0])
            assert sent_data["method"] == "tools/call"
            assert sent_data["params"]["name"] == "get_data"
            assert sent_data["params"]["arguments"] == {"query": "test"}
    
    @pytest.mark.asyncio
    async def test_execute_websocket_timeout(self, mcp_client, tenant_ctx, tool_def):
        """Test WebSocket MCP tool execution timeout."""
        tenant_ctx.mcp_configs["test_server"]["endpoint"] = "wss://mcp.example.com/ws"
        
        with patch("websockets.connect") as mock_connect:
            mock_websocket = AsyncMock()
            mock_websocket.send = AsyncMock()
            mock_websocket.recv = AsyncMock()
            # Simulate timeout
            import asyncio
            mock_websocket.recv.side_effect = asyncio.TimeoutError()
            mock_websocket.__aenter__ = AsyncMock(return_value=mock_websocket)
            mock_websocket.__aexit__ = AsyncMock(return_value=None)
            mock_connect.return_value = mock_websocket
            
            with pytest.raises(RuntimeError) as exc_info:
                await mcp_client.execute(tenant_ctx, tool_def, {"query": "test"})
            
            assert "timed out" in str(exc_info.value).lower()
    
    @pytest.mark.asyncio
    async def test_execute_missing_server_config(self, mcp_client, tenant_ctx, tool_def):
        """Test execution with missing MCP server config."""
        tenant_ctx.mcp_configs = {}
        
        with pytest.raises(ValueError) as exc_info:
            await mcp_client.execute(tenant_ctx, tool_def, {"query": "test"})
        
        assert "not found in tenant config" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_execute_missing_endpoint(self, mcp_client, tenant_ctx, tool_def):
        """Test execution with missing endpoint."""
        tenant_ctx.mcp_configs["test_server"] = {"auth_config": {}}
        
        with pytest.raises(ValueError) as exc_info:
            await mcp_client.execute(tenant_ctx, tool_def, {"query": "test"})
        
        assert "missing endpoint" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_execute_invalid_implementation_ref(self, mcp_client, tenant_ctx):
        """Test execution with invalid implementation_ref (not a dict)."""
        # Pydantic validates at model creation, so we need to bypass validation
        # or test with a dict that doesn't have the required fields
        tool_def = ToolDefinition(
            name="test_tool",
            description="Test tool",
            parameters_schema={},
            provider="mcp",
            implementation_ref={}  # Empty dict - missing mcp_server_name
        )
        
        # Manually set invalid type to test runtime validation
        tool_def.implementation_ref = "invalid"
        
        with pytest.raises(ValueError) as exc_info:
            await mcp_client.execute(tenant_ctx, tool_def, {})
        
        assert "Invalid implementation_ref" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_execute_missing_server_name(self, mcp_client, tenant_ctx):
        """Test execution with missing mcp_server_name."""
        tool_def = ToolDefinition(
            name="test_tool",
            description="Test tool",
            parameters_schema={},
            provider="mcp",
            implementation_ref={"mcp_tool_name": "get_data"}  # Missing mcp_server_name
        )
        
        with pytest.raises(ValueError) as exc_info:
            await mcp_client.execute(tenant_ctx, tool_def, {})
        
        assert "MCP server name not found" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_execute_ssrf_protection_localhost(self, mcp_client, tenant_ctx, tool_def):
        """Test SSRF protection blocks localhost endpoints."""
        tenant_ctx.mcp_configs["test_server"]["endpoint"] = "http://localhost:8080/api"
        
        with pytest.raises(ValueError) as exc_info:
            await mcp_client.execute(tenant_ctx, tool_def, {"query": "test"})
        
        assert "SSRF protection" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_execute_ssrf_protection_private_ip(self, mcp_client, tenant_ctx, tool_def):
        """Test SSRF protection blocks private IP ranges."""
        tenant_ctx.mcp_configs["test_server"]["endpoint"] = "http://192.168.1.1/api"
        
        with pytest.raises(ValueError) as exc_info:
            await mcp_client.execute(tenant_ctx, tool_def, {"query": "test"})
        
        assert "SSRF protection" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_execute_invalid_protocol(self, mcp_client, tenant_ctx, tool_def):
        """Test execution with invalid protocol."""
        tenant_ctx.mcp_configs["test_server"]["endpoint"] = "ftp://example.com/api"
        
        with pytest.raises(ValueError) as exc_info:
            await mcp_client.execute(tenant_ctx, tool_def, {"query": "test"})
        
        assert "Invalid MCP endpoint protocol" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_execute_api_key_auth(self, mcp_client, tenant_ctx, tool_def):
        """Test HTTP execution with API key authentication."""
        tenant_ctx.mcp_configs["test_server"]["auth_config"] = {
            "type": "api_key",
            "api_key": "test-api-key-456",
            "key_name": "X-API-Key"
        }
        
        mock_response = {
            "jsonrpc": "2.0",
            "id": "mcp_req",
            "result": {"success": True}
        }
        
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response_obj = MagicMock()
            mock_response_obj.json.return_value = mock_response
            mock_response_obj.raise_for_status = MagicMock()
            mock_client.post = AsyncMock(return_value=mock_response_obj)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client
            
            await mcp_client.execute(tenant_ctx, tool_def, {"query": "test"})
            
            call_args = mock_client.post.call_args
            assert "X-API-Key" in call_args[1]["headers"]
            assert call_args[1]["headers"]["X-API-Key"] == "test-api-key-456"
    
    @pytest.mark.asyncio
    async def test_execute_tool_name_fallback(self, mcp_client, tenant_ctx):
        """Test that tool name falls back to tool_def.name if mcp_tool_name not provided."""
        tool_def = ToolDefinition(
            name="fallback_tool",
            description="Test tool",
            parameters_schema={},
            provider="mcp",
            implementation_ref={
                "mcp_server_name": "test_server"
                # mcp_tool_name not provided, should use "fallback_tool"
            }
        )
        
        mock_response = {
            "jsonrpc": "2.0",
            "id": "mcp_req",
            "result": {"success": True}
        }
        
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response_obj = MagicMock()
            mock_response_obj.json.return_value = mock_response
            mock_response_obj.raise_for_status = MagicMock()
            mock_client.post = AsyncMock(return_value=mock_response_obj)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client
            
            await mcp_client.execute(tenant_ctx, tool_def, {"query": "test"})
            
            call_args = mock_client.post.call_args
            request_data = call_args[1]["json"]
            assert request_data["params"]["name"] == "fallback_tool"

