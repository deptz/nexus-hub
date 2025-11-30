-- Migration: 012_enable_rls_mcp_server_tools.sql
-- Enables Row-Level Security on mcp_server_tools table
-- This ensures tenant isolation for MCP server tools by joining to mcp_servers table

ALTER TABLE mcp_server_tools ENABLE ROW LEVEL SECURITY;

CREATE POLICY mcp_server_tools_tenant_isolation ON mcp_server_tools
USING (
    EXISTS (
        SELECT 1 FROM mcp_servers ms
        WHERE ms.id = mcp_server_tools.mcp_server_id
        AND ms.tenant_id = current_setting('app.current_tenant_id', true)::uuid
    )
);
