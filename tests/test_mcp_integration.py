"""Integration tests for MCP tool execution through tool execution engine."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.services.tool_execution_engine import execute_tool_call
from app.models.tenant import TenantContext
from app.models.tool import ToolDefinition


class TestMCPIntegration:
    """Test MCP integration through tool execution engine."""
    
    @pytest.fixture
    def tenant_ctx(self):
        """Create test tenant context with MCP config."""
        return TenantContext(
            tenant_id="test-tenant",
            llm_provider="openai",
            llm_model="gpt-4o-mini",
            allowed_tools=["mcp_tool"],
            kb_configs={},
            mcp_configs={
                "crm_server": {
                    "endpoint": "https://mcp.example.com/api",
                    "auth_config": {
                        "type": "bearer",
                        "token": "test-token"
                    }
                }
            },
            prompt_profile={},
            isolation_mode="shared_db"
        )
    
    @pytest.fixture
    def mcp_tool_def(self):
        """Create MCP tool definition."""
        return ToolDefinition(
            name="get_customer",
            description="Get customer data from CRM",
            parameters_schema={
                "type": "object",
                "properties": {
                    "customer_id": {"type": "string"}
                },
                "required": ["customer_id"]
            },
            provider="mcp",
            implementation_ref={
                "mcp_server_name": "crm_server",
                "mcp_tool_name": "get_customer"
            }
        )
    
    @pytest.mark.asyncio
    async def test_execute_mcp_tool_through_engine(self, tenant_ctx, mcp_tool_def):
        """Test MCP tool execution through tool execution engine."""
        mock_response = {
            "jsonrpc": "2.0",
            "id": "mcp_req",
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": '{"id": "123", "name": "John Doe"}'
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
            
            result = await execute_tool_call(
                tenant_ctx,
                mcp_tool_def,
                {"customer_id": "123"}
            )
            
            assert result == mock_response["result"]
            # Verify the request was made correctly
            call_args = mock_client.post.call_args
            request_data = call_args[1]["json"]
            assert request_data["method"] == "tools/call"
            assert request_data["params"]["name"] == "get_customer"
            assert request_data["params"]["arguments"]["customer_id"] == "123"
    
    @pytest.mark.asyncio
    async def test_execute_mcp_tool_error_handling(self, tenant_ctx, mcp_tool_def):
        """Test error handling in MCP tool execution."""
        mock_response = {
            "jsonrpc": "2.0",
            "id": "mcp_req",
            "error": {
                "code": -32602,
                "message": "Invalid params"
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
                await execute_tool_call(
                    tenant_ctx,
                    mcp_tool_def,
                    {"customer_id": "invalid"}
                )
            
            assert "MCP tool execution failed" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_execute_mcp_tool_websocket(self, tenant_ctx, mcp_tool_def):
        """Test MCP tool execution via WebSocket through engine."""
        tenant_ctx.mcp_configs["crm_server"]["endpoint"] = "wss://mcp.example.com/ws"
        
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
        
        import json
        with patch("websockets.connect") as mock_connect:
            mock_websocket = AsyncMock()
            mock_websocket.send = AsyncMock()
            mock_websocket.recv = AsyncMock(return_value=json.dumps(mock_response))
            mock_websocket.__aenter__ = AsyncMock(return_value=mock_websocket)
            mock_websocket.__aexit__ = AsyncMock(return_value=None)
            mock_connect.return_value = mock_websocket
            
            result = await execute_tool_call(
                tenant_ctx,
                mcp_tool_def,
                {"customer_id": "123"}
            )
            
            assert result == mock_response["result"]
            mock_websocket.send.assert_called_once()

