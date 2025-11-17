# Nexus Hub

A Python-based orchestrator for multi-tenant AI conversations across multiple channels (WhatsApp, Web, Slack, Email, Telegram) with support for OpenAI, Gemini, internal RAG, and MCP tools.

## Frontend Admin Dashboard

**Nexus Hub Admin** - A Vue.js admin dashboard for managing Nexus Hub is available at [https://github.com/deptz/nexus-hub-fe](https://github.com/deptz/nexus-hub-fe). The admin dashboard provides a user-friendly interface for managing tenants, API keys, messages, and more.

## Architecture

This system implements:
- **Canonical message format** for omni-channel communication
- **Strict tenant isolation** via PostgreSQL Row-Level Security (RLS)
- **Layered prompt architecture** with core guardrails, global system prompts, and tenant custom prompts
- **Tool abstraction layer** supporting internal RAG, OpenAI file search, Gemini file search, and MCP tools
- **Event logging** for observability and reporting

## Prerequisites

- Python 3.11+ (recommended for latest package versions)
- PostgreSQL 15+ with `pgvector` extension
- (Optional) OpenAI API key for OpenAI integration
- (Optional) Gemini API key for Gemini integration
- (Optional) Redis for rate limiting and message queue

## Quick Start

**New to the project?** See [docs/guides/KICKSTART_GUIDE.md](docs/guides/KICKSTART_GUIDE.md) for a step-by-step guide to get started in 5 minutes!

## Setup

### 1. Create Virtual Environment

```bash
# Create venv with Python 3.11 (or 3.12 if available)
python3.11 -m venv venv

# Activate venv
source venv/bin/activate  # On macOS/Linux
# or
venv\Scripts\activate  # On Windows
```

### 2. Install Dependencies

```bash
# Make sure venv is activated (you should see (venv) in your prompt)
pip install --upgrade pip
pip install -r requirements.txt
```

**Note**: We use Python 3.11+ to ensure compatibility with all latest package versions:
- NumPy 2.3.4 (requires Python 3.11+)
- pytest 9.0.1 (requires Python 3.10+)
- pytest-asyncio 1.3.0 (requires Python 3.10+)
- Alembic 1.17.2 (requires Python 3.10+)

### 3. Database Setup

Create a PostgreSQL database:

```bash
createdb nexus_hub
```

Or using psql:

```sql
CREATE DATABASE nexus_hub;
```

### 4. Run Migrations

Apply the database migrations:

```bash
psql -d nexus_hub -f migrations/001_initial_schema.sql
psql -d nexus_hub -f migrations/002_enable_rls.sql
```

### 5. Environment Variables

Create a `.env` file from the example template:

```bash
cp .env.example .env
```

Then edit `.env` and fill in your configuration values. See `.env.example` for all available options and documentation.

### 6. Start the API

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Or using Python:

```bash
python -m app.main
```

   The API will be available at `http://localhost:8000`
   
   **Note:** The application automatically loads environment variables from `.env` file in the project root. Make sure you've created `.env` from `.env.example` before starting.

6. **Start RQ workers (optional, for async message processing):**
   ```bash
   # Start a worker for the default queue
   python scripts/start_worker.py --queue default
   
   # Or start multiple workers in separate terminals
   python scripts/start_worker.py --queue high_priority
   python scripts/start_worker.py --queue low_priority
   
   # Run in burst mode (exit when queue is empty)
   python scripts/start_worker.py --queue default --burst
   ```.

## Usage

### Health Check

```bash
curl http://localhost:8000/health
```

### Admin API: Update Tenant Prompt

```bash
curl -X PUT http://localhost:8000/tenants/{tenant_id}/prompt \
  -H "Content-Type: application/json" \
  -d '{
    "custom_system_prompt": "You are Q-Assistant, the official support assistant for ACME Corp.",
    "override_mode": "append"
  }'
```

The prompt will be validated before storage. Invalid prompts (e.g., containing "ignore previous instructions") will return 400 with validation errors.

### Send an Inbound Message

```bash
curl -X POST http://localhost:8000/messages/inbound \
  -H "Content-Type: application/json" \
  -d '{
    "id": "msg-123",
    "tenant_id": "your-tenant-uuid",
    "conversation_id": "conv-123",
    "channel": "web",
    "direction": "inbound",
    "from": {
      "type": "user",
      "external_id": "user-123"
    },
    "to": {
      "type": "bot",
      "external_id": "bot-1"
    },
    "content": {
      "type": "text",
      "text": "Hello, how can you help me?"
    },
    "metadata": {},
    "timestamp": "2025-01-16T10:00:00Z"
  }'
```

## Database Schema

The system uses the following key tables:

- `tenants` - Tenant configuration
- `channels` - Channel configurations per tenant
- `tenant_prompts` - Tenant custom system prompts (validated)
- `tools` - Canonical tool registry
- `tenant_tool_policies` - Tool allow-list per tenant
- `knowledge_bases` - Knowledge base configurations per tenant
- `mcp_servers` - MCP server configurations per tenant
- `conversations` - Conversation threads
- `messages` - All messages (inbound/outbound)
- `event_logs` - Event logging
- `tool_call_logs` - Tool execution logs
- `rag_documents` / `rag_chunks` - Internal RAG storage

All tenant-owned tables have Row-Level Security (RLS) enabled for strict tenant isolation.

## Project Structure

```
nexus-hub/
├── app/
│   ├── models/          # Domain models (CanonicalMessage, TenantContext, ToolDefinition)
│   ├── services/         # Business logic (tenant context, prompt builder, tool registry)
│   ├── adapters/         # Vendor adapters (OpenAI, Gemini, RAG, MCP)
│   ├── logging/          # Event logging
│   ├── infra/            # Infrastructure (database, config)
│   └── main.py           # FastAPI application
├── migrations/           # SQL migration files
├── tests/                # Test files
└── requirements.txt      # Python dependencies
```

## Key Features

### Tenant Isolation

- All database queries are scoped by `tenant_id`
- RLS policies enforce isolation at the database level
- `TenantContext` is mandatory for all operations

### Prompt Architecture

The system uses a strict layered prompt stack:

1. **Core Guardrails** (immutable, platform-controlled)
2. **Global System Prompt** (default behavior)
3. **Tenant Custom Prompt** (validated, tenant-specific)
4. **Conversation History** (truncated)
5. **Current User Message**

### Tool Execution

Tools are abstracted through a canonical `ToolDefinition` interface and executed via provider-specific clients:
- `internal_rag` - Internal RAG (pgvector) semantic search
- `openai_file` - OpenAI file search via vector stores
- `gemini_file` - Gemini file search via File Search Stores
- `mcp` - MCP server tools

### Event Logging

All major operations emit events to `event_logs` and `tool_call_logs` tables for observability and reporting.

## Development Status

### Fully Implemented ✅

- ✅ Database schema with RLS
- ✅ Core domain models
- ✅ Tenant context service
- ✅ Prompt builder with layered stack and **token-based history truncation**
- ✅ Prompt validator
- ✅ Tool registry and execution engine
- ✅ FastAPI orchestrator with `/messages/inbound` endpoint
- ✅ Event logging and tool call logging
- ✅ Database middleware for tenant isolation
- ✅ **OpenAI API integration** with tool calling and file search support
- ✅ **Gemini API integration** with function calling and file search support
- ✅ **Internal RAG with pgvector** semantic search
- ✅ **OpenAI File Search** via Vector Stores (Responses API)
- ✅ **Gemini File Search** via File Search Stores (REST API)
- ✅ **Unified Knowledge Base API** - Single interface for all three providers
- ✅ **Embedding generation** (OpenAI or sentence-transformers fallback)
- ✅ **Admin API** (`PUT /tenants/{tenant_id}/prompt`) with validation
- ✅ **LLM trace storage** (full request/response payloads)
- ✅ **Conversation stats computation** (message count, tool calls, resolution)
- ✅ **Cost calculation** from token usage (OpenAI and Gemini)
- ✅ **Rate limiting** (per-tenant and per-channel)
- ✅ **Channel ID resolution** from message metadata
- ✅ **Tool argument parsing** (handles JSON strings from OpenAI)
- ✅ **Comprehensive test suite** (unit tests, integration tests, E2E tests, RLS isolation tests)
- ✅ **Enhanced error handling** (retry logic, granular error types, exponential backoff)

### Knowledge Base Management ✅

Nexus Hub provides a unified knowledge base system supporting three providers:

- **Internal RAG** (`internal_rag`) - Uses PostgreSQL with pgvector for semantic search
  - Documents are stored in `rag_documents` and `rag_chunks` tables
  - Supports embedding generation via OpenAI or sentence-transformers
  - Fully tenant-isolated with RLS policies

- **OpenAI File Search** (`openai_file`) - Uses OpenAI Vector Stores
  - Integrated via OpenAI Responses API with `file_search` tool
  - Vector stores are created and managed via the API
  - Files are uploaded to vector stores and automatically indexed
  - See [docs/guides/KICKSTART_GUIDE.md](docs/guides/KICKSTART_GUIDE.md) for setup instructions

- **Gemini File Search** (`gemini_file`) - Uses Google Gemini File Search Stores
  - Integrated via Gemini REST API with `file_search` tool
  - File Search Stores are created and managed via the API
  - Files are uploaded to stores and automatically indexed
  - See [docs/guides/KICKSTART_GUIDE.md](docs/guides/KICKSTART_GUIDE.md) for setup instructions

All knowledge bases are managed through the unified `/knowledge-bases` API endpoints and stored in the `knowledge_bases` table with tenant isolation.

### Additional Features ✅

- ✅ **MCP client** - Fully implemented with HTTP/WebSocket support and JSON-RPC 2.0 protocol
- ✅ **Tenant KPI snapshots computation** - Script available, run as cron job (see `scripts/compute_kpi_snapshots.py`)
- ✅ **Vector index for RAG** - Migration ready, see `docs/guides/VECTOR_INDEX_SETUP.md` for setup guide
- ✅ **Redis-based rate limiting** - Implemented with automatic fallback to in-memory

## Running Tests

```bash
# Install test dependencies
pip install -r requirements.txt

# Run all tests
pytest tests/ -v

# Run unit tests only
pytest tests/test_prompt_validator.py tests/test_prompt_builder.py tests/test_tenant_context.py -v

# Run integration tests (requires test database)
export TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/nexus_hub_test
pytest tests/test_integration_e2e.py tests/test_integration_rls.py tests/test_admin_api.py -v

# Run with coverage
pytest tests/ --cov=app --cov-report=html

# Run MCP-specific tests
pytest tests/test_mcp_client.py tests/test_mcp_integration.py -v

# See tests/README.md for detailed test documentation
# See docs/guides/MCP_TESTING.md for MCP testing guide
```

## Knowledge Base Setup

### Internal RAG Setup

Internal RAG uses PostgreSQL with pgvector. Documents are stored directly in the database:

```bash
# Documents are added via the API
curl -X POST http://localhost:8000/tenants/{tenant_id}/rag/documents \
  -H "X-API-Key: {api_key}" \
  -H "Content-Type: application/json" \
  -d '{
    "kb_name": "my_kb",
    "title": "Document Title",
    "content": "Document content here...",
    "metadata": {}
  }'
```

### OpenAI File Search Setup

1. Create a vector store in OpenAI (via API or dashboard)
2. Upload files to the vector store
3. Create a knowledge base in Nexus Hub with the `vector_store_id`:

```bash
curl -X POST http://localhost:8000/tenants/{tenant_id}/knowledge-bases \
  -H "X-API-Key: {api_key}" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "openai_kb",
    "description": "OpenAI File Search KB",
    "provider": "openai_file",
    "provider_config": {
      "vector_store_id": "vs_xxxxx"
    }
  }'
```

### Gemini File Search Setup

1. Create a File Search Store in Google AI Studio or via API
2. Upload files to the File Search Store
3. Create a knowledge base in Nexus Hub with the `file_search_store_name`:

```bash
curl -X POST http://localhost:8000/tenants/{tenant_id}/knowledge-bases \
  -H "X-API-Key: {api_key}" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "gemini_kb",
    "description": "Gemini File Search KB",
    "provider": "gemini_file",
    "provider_config": {
      "file_search_store_name": "fileSearchStores/xxxxx"
    }
  }'
```

For detailed setup instructions, see [docs/guides/KICKSTART_GUIDE.md](docs/guides/KICKSTART_GUIDE.md).

## Telegram Adapter (Testing)

A Telegram adapter is available for testing the orchestrator. It allows you to interact with the system through Telegram bots.

**Quick Setup:**
1. Get a bot token from [@BotFather](https://t.me/botfather)
2. Set `TELEGRAM_BOT_TOKEN` in your `.env` file
3. Set up webhook: `POST /webhooks/telegram`
4. Send messages to your bot!

For detailed setup instructions, see [docs/guides/TELEGRAM_SETUP.md](docs/guides/TELEGRAM_SETUP.md).

## API Documentation

Once the server is running, visit:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on how to contribute to this project.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

