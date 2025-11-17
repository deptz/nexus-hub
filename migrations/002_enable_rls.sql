-- Migration: 002_enable_rls.sql
-- Enables Row-Level Security (RLS) on all tenant-owned tables
-- Sets up policies to enforce tenant isolation

-- Function to set tenant context (called by application middleware)
-- This is a helper, but the actual setting happens via SET app.current_tenant_id

-- Enable RLS on all tenant-owned tables
ALTER TABLE channels ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenant_prompts ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenant_tool_policies ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_bases ENABLE ROW LEVEL SECURITY;
ALTER TABLE mcp_servers ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE event_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE tool_call_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversation_stats ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenant_kpi_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE llm_traces ENABLE ROW LEVEL SECURITY;
ALTER TABLE rag_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE rag_chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE api_keys ENABLE ROW LEVEL SECURITY;

-- Create RLS policies for each table
-- Pattern: tenant_id must match current_setting('app.current_tenant_id')::uuid

CREATE POLICY channels_tenant_isolation ON channels
USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

CREATE POLICY tenant_prompts_tenant_isolation ON tenant_prompts
USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

CREATE POLICY tenant_tool_policies_tenant_isolation ON tenant_tool_policies
USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

CREATE POLICY knowledge_bases_tenant_isolation ON knowledge_bases
USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

CREATE POLICY mcp_servers_tenant_isolation ON mcp_servers
USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

CREATE POLICY conversations_tenant_isolation ON conversations
USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

CREATE POLICY messages_tenant_isolation ON messages
USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

CREATE POLICY event_logs_tenant_isolation ON event_logs
USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

CREATE POLICY tool_call_logs_tenant_isolation ON tool_call_logs
USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

CREATE POLICY conversation_stats_tenant_isolation ON conversation_stats
USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

CREATE POLICY tenant_kpi_snapshots_tenant_isolation ON tenant_kpi_snapshots
USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

CREATE POLICY llm_traces_tenant_isolation ON llm_traces
USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

CREATE POLICY rag_documents_tenant_isolation ON rag_documents
USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

CREATE POLICY rag_chunks_tenant_isolation ON rag_chunks
USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

CREATE POLICY api_keys_tenant_isolation ON api_keys
USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- Note: The 'tenants' table itself does NOT have RLS
-- as it's the root isolation boundary

