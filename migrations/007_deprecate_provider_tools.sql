-- Migration: 007_deprecate_provider_tools.sql
-- Deprecates provider-specific tools and creates abstract file_search tool

-- Add is_internal flag to tools table
ALTER TABLE tools ADD COLUMN IF NOT EXISTS is_internal BOOLEAN NOT NULL DEFAULT FALSE;

-- Mark provider-specific tools as internal (deprecated from user-facing API)
UPDATE tools SET is_internal = TRUE WHERE name IN ('openai_file_search', 'gemini_file_search');

-- Create abstract file_search tool if it doesn't exist
INSERT INTO tools (name, description, provider, parameters_schema, implementation_ref, is_global, is_internal)
VALUES (
  'file_search',
  'Search documents using file search (automatically uses all available providers)',
  'internal_rag', -- Use internal_rag as base provider, but maps to all
  '{"type": "object", "properties": {"query": {"type": "string", "description": "The search query text"}}, "required": ["query"]}'::jsonb,
  '{}'::jsonb,
  TRUE,
  FALSE -- User-facing tool
)
ON CONFLICT (name) DO NOTHING;

-- Migration: Enable file_search for tenants with provider tools enabled
-- This ensures backward compatibility - existing users get file_search enabled automatically
INSERT INTO tenant_tool_policies (tenant_id, tool_id, is_enabled)
SELECT DISTINCT ttp.tenant_id, t.id, TRUE
FROM tenant_tool_policies ttp
JOIN tools t_old ON ttp.tool_id = t_old.id
JOIN tools t ON t.name = 'file_search'
WHERE t_old.name IN ('openai_file_search', 'gemini_file_search')
  AND ttp.is_enabled = TRUE
ON CONFLICT (tenant_id, tool_id) DO NOTHING;

