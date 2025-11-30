-- Migration: 011_create_workflows.sql
-- Creates workflow_definitions table for reusable workflow templates

CREATE TABLE workflow_definitions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name                VARCHAR(255) NOT NULL,
    definition          JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, name)
);

-- Indexes
CREATE INDEX workflow_definitions_tenant_id_idx ON workflow_definitions(tenant_id);
CREATE INDEX workflow_definitions_tenant_active_idx ON workflow_definitions(tenant_id, is_active);

-- Comments
COMMENT ON TABLE workflow_definitions IS 'Stores reusable workflow definitions for agentic execution';
COMMENT ON COLUMN workflow_definitions.definition IS 'JSONB object with workflow structure (steps, conditions, etc.)';

