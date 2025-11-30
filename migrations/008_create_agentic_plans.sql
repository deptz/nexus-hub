-- Migration: 008_create_agentic_plans.sql
-- Creates agentic_plans table for storing generated plans

CREATE TABLE agentic_plans (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    conversation_id     UUID REFERENCES conversations(id) ON DELETE SET NULL,
    message_id          UUID REFERENCES messages(id) ON DELETE SET NULL,
    goal                TEXT NOT NULL,
    plan_steps          JSONB NOT NULL DEFAULT '[]'::jsonb,
    status              VARCHAR(50) NOT NULL DEFAULT 'draft',
    created_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

-- Indexes
CREATE INDEX agentic_plans_tenant_id_idx ON agentic_plans(tenant_id);
CREATE INDEX agentic_plans_conversation_id_idx ON agentic_plans(conversation_id);
CREATE INDEX agentic_plans_tenant_conversation_created_idx ON agentic_plans(tenant_id, conversation_id, created_at);
CREATE INDEX agentic_plans_status_idx ON agentic_plans(status);

-- Comments
COMMENT ON TABLE agentic_plans IS 'Stores generated agentic plans with steps and dependencies';
COMMENT ON COLUMN agentic_plans.plan_steps IS 'JSONB array of plan steps with dependencies, tools, and success criteria';
COMMENT ON COLUMN agentic_plans.status IS 'Plan status: draft, executing, completed, failed';

