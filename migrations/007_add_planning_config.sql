-- Migration: 007_add_planning_config.sql
-- Adds planning configuration columns to tenants table

ALTER TABLE tenants
ADD COLUMN IF NOT EXISTS max_tool_steps INTEGER DEFAULT 10,
ADD COLUMN IF NOT EXISTS planning_enabled BOOLEAN DEFAULT TRUE,
ADD COLUMN IF NOT EXISTS plan_timeout_seconds INTEGER DEFAULT 300;

-- Add comments
COMMENT ON COLUMN tenants.max_tool_steps IS 'Maximum number of tool execution steps allowed per message';
COMMENT ON COLUMN tenants.planning_enabled IS 'Whether agentic planning is enabled for this tenant';
COMMENT ON COLUMN tenants.plan_timeout_seconds IS 'Maximum time in seconds for plan execution';

