-- Migration: 010_enable_rls_agentic_insights.sql
-- Enables Row-Level Security on agentic_insights table

ALTER TABLE agentic_insights ENABLE ROW LEVEL SECURITY;

CREATE POLICY agentic_insights_tenant_isolation ON agentic_insights
USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

