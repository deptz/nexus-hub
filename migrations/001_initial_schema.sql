-- Migration: 001_initial_schema.sql
-- Creates all tables, types, and indexes
-- RLS will be enabled in 002_enable_rls.sql

-- Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "vector"; -- for pgvector

-- Enums
CREATE TYPE prompt_override_mode AS ENUM ('append', 'replace_behavior');
CREATE TYPE tool_provider AS ENUM (
    'internal_rag',
    'openai_file',
    'gemini_file',
    'mcp',
    'custom_http'
);
CREATE TYPE kb_provider AS ENUM (
    'internal_rag',
    'openai_file',
    'gemini_file'
);
CREATE TYPE message_direction AS ENUM ('inbound', 'outbound');
CREATE TYPE kpi_period AS ENUM ('daily', 'weekly', 'monthly');

-- 1. Core: Tenants & Channels
CREATE TABLE tenants (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name                TEXT NOT NULL,
    slug                TEXT UNIQUE NOT NULL,
    isolation_mode      TEXT NOT NULL DEFAULT 'shared_db',
    llm_provider        TEXT NOT NULL DEFAULT 'openai',
    llm_model           TEXT NOT NULL DEFAULT 'gpt-4.1-mini',
    created_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX tenants_slug_idx ON tenants(slug);

CREATE TABLE channels (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name                TEXT NOT NULL,
    channel_type        TEXT NOT NULL,
    external_id         TEXT,
    config              JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

CREATE INDEX channels_tenant_id_idx ON channels(tenant_id);
CREATE INDEX channels_tenant_channel_type_idx ON channels(tenant_id, channel_type);

-- 2. Prompts & Tenant Profiles
CREATE TABLE tenant_prompts (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id               UUID NOT NULL UNIQUE REFERENCES tenants(id) ON DELETE CASCADE,
    custom_system_prompt    TEXT NOT NULL,
    override_mode           prompt_override_mode NOT NULL DEFAULT 'append',
    language_preference     TEXT DEFAULT 'auto',
    tone_profile            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at              TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

-- 3. Tools & Knowledge Base Configuration
CREATE TABLE tools (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name                TEXT NOT NULL UNIQUE,
    description         TEXT NOT NULL,
    provider            tool_provider NOT NULL,
    parameters_schema   JSONB NOT NULL,
    implementation_ref  JSONB NOT NULL,
    is_global           BOOLEAN NOT NULL DEFAULT FALSE,
    created_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

CREATE TABLE tenant_tool_policies (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    tool_id             UUID NOT NULL REFERENCES tools(id) ON DELETE CASCADE,
    is_enabled          BOOLEAN NOT NULL DEFAULT TRUE,
    config_override     JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, tool_id)
);

CREATE INDEX tenant_tool_policies_tenant_id_idx ON tenant_tool_policies(tenant_id);

CREATE TABLE knowledge_bases (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name                TEXT NOT NULL,
    description         TEXT,
    provider            kb_provider NOT NULL,
    provider_config     JSONB NOT NULL,
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, name)
);

CREATE INDEX knowledge_bases_tenant_id_idx ON knowledge_bases(tenant_id);

-- 4. MCP Configuration
CREATE TABLE mcp_servers (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name                TEXT NOT NULL,
    endpoint            TEXT NOT NULL,
    auth_config         JSONB NOT NULL,
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, name)
);

CREATE INDEX mcp_servers_tenant_id_idx ON mcp_servers(tenant_id);

CREATE TABLE mcp_server_tools (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mcp_server_id       UUID NOT NULL REFERENCES mcp_servers(id) ON DELETE CASCADE,
    tool_name           TEXT NOT NULL,
    description         TEXT,
    schema              JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    UNIQUE (mcp_server_id, tool_name)
);

-- 5. Conversations & Messages
CREATE TABLE conversations (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    channel_id          UUID REFERENCES channels(id) ON DELETE SET NULL,
    external_thread_id  TEXT,
    subject             TEXT,
    status              TEXT NOT NULL DEFAULT 'open',
    created_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, channel_id, external_thread_id)
);

CREATE INDEX conversations_tenant_id_idx ON conversations(tenant_id);
CREATE INDEX conversations_tenant_status_idx ON conversations(tenant_id, status);

CREATE TABLE messages (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    conversation_id     UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    channel_id          UUID REFERENCES channels(id) ON DELETE SET NULL,
    direction           message_direction NOT NULL,
    source_message_id   TEXT,
    from_type           TEXT NOT NULL,
    from_external_id    TEXT,
    from_display_name   TEXT,
    content_type        TEXT NOT NULL DEFAULT 'text',
    content_text        TEXT NOT NULL,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

CREATE INDEX messages_tenant_id_idx ON messages(tenant_id);
CREATE INDEX messages_conversation_id_idx ON messages(conversation_id);
CREATE INDEX messages_tenant_conv_created_at_idx ON messages(tenant_id, conversation_id, created_at);

-- 6. Events, Tool Calls & Reporting
CREATE TABLE event_logs (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    conversation_id     UUID REFERENCES conversations(id) ON DELETE SET NULL,
    message_id          UUID REFERENCES messages(id) ON DELETE SET NULL,
    event_type          TEXT NOT NULL,
    provider            TEXT,
    status              TEXT NOT NULL DEFAULT 'success',
    latency_ms          INTEGER,
    cost                NUMERIC(12,6),
    payload             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

CREATE INDEX event_logs_tenant_id_idx ON event_logs(tenant_id);
CREATE INDEX event_logs_conversation_id_idx ON event_logs(conversation_id);
CREATE INDEX event_logs_event_type_idx ON event_logs(event_type);
CREATE INDEX event_logs_created_at_idx ON event_logs(created_at);

CREATE TABLE tool_call_logs (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    conversation_id     UUID REFERENCES conversations(id) ON DELETE SET NULL,
    message_id          UUID REFERENCES messages(id) ON DELETE SET NULL,
    tool_id             UUID REFERENCES tools(id) ON DELETE SET NULL,
    tool_name           TEXT NOT NULL,
    provider            tool_provider NOT NULL,
    arguments           JSONB NOT NULL DEFAULT '{}'::jsonb,
    result_summary      JSONB NOT NULL DEFAULT '{}'::jsonb,
    status              TEXT NOT NULL DEFAULT 'success',
    error_message       TEXT,
    latency_ms          INTEGER,
    cost                NUMERIC(12,6),
    created_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

CREATE INDEX tool_call_logs_tenant_id_idx ON tool_call_logs(tenant_id);
CREATE INDEX tool_call_logs_conversation_id_idx ON tool_call_logs(conversation_id);

CREATE TABLE conversation_stats (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    conversation_id     UUID NOT NULL UNIQUE REFERENCES conversations(id) ON DELETE CASCADE,
    resolved            BOOLEAN NOT NULL DEFAULT FALSE,
    resolution_time_ms  INTEGER,
    total_messages      INTEGER NOT NULL DEFAULT 0,
    tool_calls          INTEGER NOT NULL DEFAULT 0,
    risk_flags          INTEGER NOT NULL DEFAULT 0,
    last_event_at       TIMESTAMP WITH TIME ZONE,
    updated_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

CREATE INDEX conversation_stats_tenant_id_idx ON conversation_stats(tenant_id);

CREATE TABLE tenant_kpi_snapshots (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    period_type         kpi_period NOT NULL,
    period_start        DATE NOT NULL,
    period_end          DATE NOT NULL,
    metric_name         TEXT NOT NULL,
    metric_value        NUMERIC(18,6) NOT NULL,
    created_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, period_type, period_start, metric_name)
);

CREATE INDEX tenant_kpi_snapshots_tenant_id_idx ON tenant_kpi_snapshots(tenant_id);

-- 7. LLM Traces
CREATE TABLE llm_traces (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    conversation_id     UUID REFERENCES conversations(id) ON DELETE SET NULL,
    message_id          UUID REFERENCES messages(id) ON DELETE SET NULL,
    provider            TEXT NOT NULL,
    model               TEXT NOT NULL,
    request_payload     JSONB NOT NULL,
    response_payload    JSONB NOT NULL,
    created_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

CREATE INDEX llm_traces_tenant_id_idx ON llm_traces(tenant_id);
CREATE INDEX llm_traces_conversation_id_idx ON llm_traces(conversation_id);

-- 8. Internal RAG DB Schema
CREATE TABLE rag_documents (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    kb_name             TEXT NOT NULL,
    external_id         TEXT,
    title               TEXT,
    content             TEXT NOT NULL,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

CREATE INDEX rag_documents_tenant_kb_idx ON rag_documents(tenant_id, kb_name);

CREATE TABLE rag_chunks (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    kb_name             TEXT NOT NULL,
    document_id         UUID NOT NULL REFERENCES rag_documents(id) ON DELETE CASCADE,
    chunk_index         INTEGER NOT NULL,
    content             TEXT NOT NULL,
    embedding           VECTOR(1536),
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

CREATE INDEX rag_chunks_tenant_kb_idx ON rag_chunks(tenant_id, kb_name);
CREATE INDEX rag_chunks_document_idx ON rag_chunks(document_id);

-- Vector index for semantic search (adjust lists parameter based on data size)
-- CREATE INDEX rag_chunks_embedding_idx ON rag_chunks
-- USING ivfflat (embedding vector_cosine_ops)
-- WITH (lists = 100);


