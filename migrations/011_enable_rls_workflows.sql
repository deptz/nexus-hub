-- Migration: 011_enable_rls_workflows.sql
-- Enables Row-Level Security on workflow_definitions table

ALTER TABLE workflow_definitions ENABLE ROW LEVEL SECURITY;

CREATE POLICY workflow_definitions_tenant_isolation ON workflow_definitions
USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

