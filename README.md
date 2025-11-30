# Nexus Hub

A Python-based orchestrator for multi-tenant AI conversations across multiple channels (WhatsApp, Web, Slack, Email, Telegram) with support for OpenAI, Gemini, internal RAG, and MCP tools.

## Frontend Admin Dashboard

**Nexus Hub Admin** - A Vue.js admin dashboard for managing Nexus Hub is available at [https://github.com/deptz/nexus-hub-fe](https://github.com/deptz/nexus-hub-fe). The admin dashboard provides a user-friendly interface for managing tenants, API keys, messages, and more.

## Quick Start

**New to the project?** See [docs/guides/KICKSTART_GUIDE.md](docs/guides/KICKSTART_GUIDE.md) for a step-by-step guide to get started in 5 minutes!

## Features

- **Multi-channel support** - WhatsApp, Web, Slack, Email, Telegram
- **Multi-LLM support** - OpenAI, Gemini with unified interface
- **Knowledge bases** - Internal RAG (pgvector), OpenAI File Search, Gemini File Search
- **MCP integration** - Model Context Protocol server support
- **Tenant isolation** - Strict Row-Level Security (RLS) enforcement
- **Layered prompts** - Core guardrails, global system prompts, tenant custom prompts
- **Tool abstraction** - Unified tool execution engine
- **Event logging** - Comprehensive observability and reporting
- **Agentic planning** - Proactive planning and task management

## Prerequisites

- Python 3.11+ (recommended for latest package versions)
- PostgreSQL 15+ with `pgvector` extension
- (Optional) OpenAI API key for OpenAI integration
- (Optional) Gemini API key for Gemini integration
- (Optional) Redis for rate limiting and message queue

## Installation

### 1. Clone and Setup

```bash
# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate  # On macOS/Linux
# or
venv\Scripts\activate  # On Windows

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

### 2. Database Setup

```bash
# Create database
createdb nexus_hub

# Enable pgvector extension
psql -d nexus_hub -c "CREATE EXTENSION IF NOT EXISTS vector;"

# Run migrations
psql -d nexus_hub -f migrations/001_initial_schema.sql
psql -d nexus_hub -f migrations/002_enable_rls.sql
```

### 3. Environment Configuration

```bash
# Copy example environment file
cp .env.example .env

# Edit .env with your configuration values
# Minimum required: DATABASE_URL
```

### 4. Start the Server

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at `http://localhost:8000`

## Usage

### Health Check

```bash
curl http://localhost:8000/health
```

### Send a Message

```bash
curl -X POST http://localhost:8000/messages/inbound \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "your-tenant-uuid",
    "channel": "web",
    "direction": "inbound",
    "from": {"type": "user", "external_id": "user-123"},
    "to": {"type": "bot", "external_id": "bot-1"},
    "content": {"type": "text", "text": "Hello, how can you help me?"},
    "metadata": {},
    "timestamp": "2025-01-16T10:00:00Z"
  }'
```

## Documentation

- **[Getting Started Guide](docs/guides/KICKSTART_GUIDE.md)** - Complete setup and testing guide
- **[System Architecture](docs/technical/SYSTEM_ARCHITECTURE.md)** - System design and architecture
- **[Agentic Message Flow](docs/technical/AGENTIC_MESSAGE_FLOW.md)** - How agentic planning works
- **[Prompt Management](docs/technical/PROMPT_MANAGEMENT.md)** - Prompt architecture and validation
- **[API Key Implementation](docs/technical/API_KEY_IMPLEMENTATION.md)** - Secure API key management
- **[MCP Server Security](docs/guides/MCP_SERVER_SECURITY.md)** - Security requirements for MCP servers
- **[Telegram Setup](docs/guides/TELEGRAM_SETUP.md)** - Telegram adapter configuration
- **[Contributing](CONTRIBUTING.md)** - Contribution guidelines
- **[Full Documentation Index](docs/README.md)** - Complete documentation index

## API Documentation

Once the server is running:
- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`

## Project Structure

```
nexus-hub/
├── app/
│   ├── models/          # Domain models
│   ├── services/        # Business logic
│   ├── adapters/        # Vendor adapters (OpenAI, Gemini, RAG, MCP)
│   ├── api/             # FastAPI routes
│   ├── infra/           # Infrastructure (database, config, auth)
│   └── main.py          # FastAPI application
├── migrations/          # SQL migration files
├── docs/                # Documentation
│   ├── guides/         # User guides
│   ├── technical/      # Technical documentation
│   └── development/    # Development docs
├── tests/              # Test suite
└── scripts/            # Utility scripts
```

## Key Features

### Tenant Isolation

- All database queries are scoped by `tenant_id`
- RLS policies enforce isolation at the database level
- `TenantContext` is mandatory for all operations

### Prompt Architecture

Layered prompt stack:
1. **Core Guardrails** (immutable, platform-controlled)
2. **Global System Prompt** (default behavior)
3. **Tenant Custom Prompt** (validated, tenant-specific)
4. **Conversation History** (token-truncated)
5. **Current User Message**

### Tool Execution

Unified tool abstraction supporting:
- `internal_rag` - Internal RAG (pgvector) semantic search
- `openai_file` - OpenAI file search via vector stores
- `gemini_file` - Gemini file search via File Search Stores
- `mcp` - MCP server tools

## Testing

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=app --cov-report=html

# See tests/README.md for detailed test documentation
```

## Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
