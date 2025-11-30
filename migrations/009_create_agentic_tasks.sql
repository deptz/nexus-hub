-- Migration: 009_create_agentic_tasks.sql
-- Creates agentic_tasks table for long-running task state management

CREATE TABLE agentic_tasks (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    conversation_id     UUID REFERENCES conversations(id) ON DELETE SET NULL,
    plan_id             UUID REFERENCES agentic_plans(id) ON DELETE SET NULL,
    goal                TEXT NOT NULL,
    current_step        INTEGER NOT NULL DEFAULT 0,
    state               JSONB NOT NULL DEFAULT '{}'::jsonb,
    status              VARCHAR(50) NOT NULL DEFAULT 'planning',
    created_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    completed_at        TIMESTAMP WITH TIME ZONE
);

-- Indexes
CREATE INDEX agentic_tasks_tenant_id_idx ON agentic_tasks(tenant_id);
CREATE INDEX agentic_tasks_plan_id_idx ON agentic_tasks(plan_id);
CREATE INDEX agentic_tasks_tenant_status_updated_idx ON agentic_tasks(tenant_id, status, updated_at);
CREATE INDEX agentic_tasks_status_idx ON agentic_tasks(status);

-- Comments
COMMENT ON TABLE agentic_tasks IS 'Stores long-running agentic task state for resumption';
COMMENT ON COLUMN agentic_tasks.state IS 'JSONB object with step results and intermediate data';
COMMENT ON COLUMN agentic_tasks.status IS 'Task status: planning, executing, paused, completed, failed';

