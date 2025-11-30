-- Migration: 009_enable_rls_agentic_tasks.sql
-- Enables Row-Level Security on agentic_tasks table

ALTER TABLE agentic_tasks ENABLE ROW LEVEL SECURITY;

CREATE POLICY agentic_tasks_tenant_isolation ON agentic_tasks
USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

