-- Migration: 010_create_agentic_insights.sql
-- Creates agentic_insights table for reflection and learning

CREATE TABLE agentic_insights (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    plan_id             UUID REFERENCES agentic_plans(id) ON DELETE SET NULL,
    task_id             UUID REFERENCES agentic_tasks(id) ON DELETE SET NULL,
    insights            JSONB NOT NULL DEFAULT '{}'::jsonb,
    recommendations     JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

-- Indexes
CREATE INDEX agentic_insights_tenant_id_idx ON agentic_insights(tenant_id);
CREATE INDEX agentic_insights_plan_id_idx ON agentic_insights(plan_id);
CREATE INDEX agentic_insights_task_id_idx ON agentic_insights(task_id);
CREATE INDEX agentic_insights_tenant_created_idx ON agentic_insights(tenant_id, created_at);

-- Comments
COMMENT ON TABLE agentic_insights IS 'Stores reflection insights and recommendations from plan execution';
COMMENT ON COLUMN agentic_insights.insights IS 'JSONB object with what worked and what failed';
COMMENT ON COLUMN agentic_insights.recommendations IS 'JSONB object with suggestions for future similar tasks';

