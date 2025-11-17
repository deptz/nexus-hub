-- Migration: 005_add_provider_sync_status.sql
-- Adds provider sync status tracking for knowledge bases

CREATE TABLE IF NOT EXISTS kb_provider_sync (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  kb_id UUID NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
  provider VARCHAR(50) NOT NULL, -- 'openai_file', 'gemini_file', 'internal_rag'
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  sync_status VARCHAR(20) NOT NULL DEFAULT 'enabled', -- 'enabled', 'disabled', 'syncing', 'error'
  store_id VARCHAR(255), -- vector_store_id or file_search_store_name
  last_sync_at TIMESTAMP WITH TIME ZONE,
  error_message TEXT,
  created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
  updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
  UNIQUE(kb_id, provider)
);

CREATE INDEX kb_provider_sync_kb_id_idx ON kb_provider_sync(kb_id);
CREATE INDEX kb_provider_sync_provider_idx ON kb_provider_sync(provider);
CREATE INDEX kb_provider_sync_status_idx ON kb_provider_sync(sync_status);

-- Add RLS policy (will be enabled in 002_enable_rls.sql if RLS is used)
-- For now, rely on application-level tenant isolation

