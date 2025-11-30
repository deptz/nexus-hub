-- Migration: 004_create_api_keys_table.sql
-- Creates api_keys table for secure API key management with hashed keys

-- Create api_keys table
CREATE TABLE api_keys (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    key_hash            TEXT NOT NULL,                    -- bcrypt hashed API key
    key_prefix          TEXT NOT NULL,                    -- First 8 characters for identification
    name                TEXT,                            -- Human-readable name for the key
    description         TEXT,                             -- Optional description
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    rate_limit_per_minute INTEGER DEFAULT 100,            -- Per-key rate limit
    created_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    expires_at          TIMESTAMP WITH TIME ZONE,        -- Optional expiration
    last_used_at        TIMESTAMP WITH TIME ZONE,        -- Track last usage
    created_by          TEXT,                             -- User/system that created the key
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb -- Additional metadata
);

-- Indexes for efficient lookups
CREATE INDEX idx_api_keys_tenant_id ON api_keys(tenant_id);
CREATE INDEX idx_api_keys_key_prefix ON api_keys(key_prefix);
CREATE INDEX idx_api_keys_key_hash ON api_keys(key_hash);
CREATE INDEX idx_api_keys_active ON api_keys(is_active, expires_at) WHERE is_active = TRUE;

-- Enable RLS for tenant isolation
ALTER TABLE api_keys ENABLE ROW LEVEL SECURITY;

-- RLS Policy: tenants can only see their own API keys
CREATE POLICY api_keys_tenant_isolation ON api_keys
USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- Note: API key verification will be done at application level
-- The key_hash is stored using bcrypt (handled in Python code)
-- PostgreSQL's crypt() function can be used for verification, but we'll use Python's bcrypt


