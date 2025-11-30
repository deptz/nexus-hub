-- Migration: 008_enable_rls_agentic_plans.sql
-- Enables Row-Level Security on agentic_plans table

ALTER TABLE agentic_plans ENABLE ROW LEVEL SECURITY;

CREATE POLICY agentic_plans_tenant_isolation ON agentic_plans
USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

