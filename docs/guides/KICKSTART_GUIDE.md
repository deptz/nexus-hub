# 🚀 Kickstart Guide - Local Development

This guide will help you get Nexus Hub running locally and test it with real data.

## 📋 Prerequisites

- **Python 3.11+** (check with `python3 --version`)
- **PostgreSQL 15+** with `pgvector` extension
- **Redis** (optional, for rate limiting and message queue)
- **Git** (to clone the repository)

## 🏁 Quick Start (5 minutes)

### Step 1: Clone and Setup

```bash
# Clone the repository (if not already done)
git clone https://github.com/deptz/nexus-hub.git
cd nexus-hub

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

### Step 2: Configure Environment

```bash
# Copy example environment file
cp .env.example .env

# Edit .env with your settings
# Minimum required:
# DATABASE_URL=postgresql://postgres:postgres@localhost:5432/nexus_hub
#
# Optional (for Telegram testing):
# TELEGRAM_BOT_TOKEN=your_bot_token_here
# TELEGRAM_DEFAULT_TENANT_ID=your_tenant_uuid_here
```

### Step 3: Setup Database

```bash
# Create database
createdb nexus_hub

# Or using psql:
psql -U postgres -c "CREATE DATABASE nexus_hub;"

# Enable pgvector extension
psql -U postgres -d nexus_hub -c "CREATE EXTENSION IF NOT EXISTS vector;"

# Run migrations
psql -d nexus_hub -f migrations/001_initial_schema.sql
psql -d nexus_hub -f migrations/002_enable_rls.sql

# Run API keys table migration (if exists)
if [ -f migrations/004_create_api_keys_table.sql ]; then
    psql -d nexus_hub -f migrations/004_create_api_keys_table.sql
fi
```

### Step 4: Start Redis (Optional)

```bash
# Using Docker
docker run -d -p 6379:6379 redis:latest

# Or using Homebrew (macOS)
brew services start redis

# Verify Redis is running
redis-cli ping  # Should return "PONG"
```

### Step 5: Start the Server

```bash
# Make sure venv is activated
source venv/bin/activate

# Start the API server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

You should see:
```
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     Started reloader process
INFO:     Started server process
INFO:     Waiting for application startup.
INFO:     Application startup complete.
```

### Step 6: Verify Server is Running

```bash
# Health check
curl http://localhost:8000/health

# Should return:
# {"status":"ok","service":"nexus-hub","version":"1.0.0"}
```

## 🧪 Testing with Real Data

### Step 1: Create a Test Tenant

First, you need to create a tenant in the database:

```bash
# Connect to database
psql -d nexus_hub

# Insert a test tenant
INSERT INTO tenants (id, name, llm_provider, llm_model, isolation_mode, created_at)
VALUES (
    gen_random_uuid(),
    'Test Company',
    'openai',
    'gpt-4o-mini',
    'shared_db',
    NOW()
)
RETURNING id, name;
```

**Save the tenant ID** - you'll need it for API calls!

Example output:
```
                  id                  |     name      
--------------------------------------+---------------
 123e4567-e89b-12d3-a456-426614174000 | Test Company
```

### Step 2: Create a Channel

```sql
-- Still in psql
-- Replace <tenant_id> with your actual tenant ID
INSERT INTO channels (id, tenant_id, channel_type, name, is_active, created_at)
VALUES (
    gen_random_uuid(),
    '<tenant_id>',
    'web',
    'Web Chat',
    TRUE,
    NOW()
)
RETURNING id;
```

**Or use the setup script** (recommended):
```bash
./scripts/setup_test_data.sh
```
This will create both tenant and channel automatically.

### Step 3: Create an API Key

**Using the API (Recommended)**

```bash
# First, set a master API key in .env
echo "MASTER_API_KEY=dev-master-key-12345" >> .env

# Restart the server if it's running

# Create an API key for your tenant (replace <tenant_id> with your tenant ID)
curl -X POST "http://localhost:8000/tenants/<tenant_id>/api-keys" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: dev-master-key-12345" \
  -d '{
    "name": "Test API Key",
    "description": "Key for testing",
    "rate_limit_per_minute": 100
  }' | jq .
```

**⚠️ IMPORTANT: Save the API key from the response!** It's only shown once and cannot be retrieved later.

**Or use the helper script:**

```bash
# Make sure TENANT_ID and MASTER_API_KEY are set in .env
./scripts/create_api_key.sh
```

### Step 4: Test the API

#### 4.1: Health Check

```bash
curl http://localhost:8000/health
```

#### 4.2: Readiness Check

```bash
curl http://localhost:8000/health/ready
```

#### 4.3: Send a Test Message

```bash
# Replace <tenant_id> and <api_key> with your values
curl -X POST "http://localhost:8000/messages/inbound" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: <api_key>" \
  -d '{
    "tenant_id": "<tenant_id>",
    "channel": "telegram",
    "direction": "inbound",
    "from": {
      "type": "user",
      "external_id": "user-123",
      "display_name": "Test User"
    },
    "to": {
      "type": "bot",
      "external_id": ""
    },
    "content": {
      "type": "text",
      "text": "Hello, how are you?"
    },
    "metadata": {
      "channel_id": "<channel_id>"
    },
    "timestamp": "2025-01-16T10:00:00Z"
  }'
```

#### 4.4: Check Metrics

```bash
curl http://localhost:8000/metrics
```

## 📝 Complete Test Workflow

### 1. Setup Script

The setup script is already created at `scripts/setup_test_data.sh`. Just run it:

```bash
./scripts/setup_test_data.sh
```

This will create:
- A test tenant
- A Telegram channel (for direct Telegram testing)
- A test tool (internal_rag_search)
- Enable the tool for the tenant

The script will output the `TENANT_ID` and `CHANNEL_ID` - save these!

### 2. Create API Key via API

```bash
# Set master key
export MASTER_KEY="dev-master-key-12345"

# Create API key
curl -X POST "http://localhost:8000/tenants/$TENANT_ID/api-keys" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $MASTER_KEY" \
  -d '{
    "name": "Development Key",
    "description": "Key for local development",
    "rate_limit_per_minute": 1000
  }' | jq .
```

### 3. Test Message Flow

```bash
# Load from .env or set manually
export API_KEY="<your-api-key-from-step-2>"
export TENANT_ID="<your-tenant-id>"
export CHANNEL_ID="<your-channel-id>"

# Send a message
curl -X POST "http://localhost:8000/messages/inbound" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d "{
    \"tenant_id\": \"$TENANT_ID\",
    \"channel\": \"telegram\",
    \"direction\": \"inbound\",
    \"from\": {
      \"type\": \"user\",
      \"external_id\": \"user-123\",
      \"display_name\": \"Test User\"
    },
    \"to\": {
      \"type\": \"bot\",
      \"external_id\": \"\"
    },
    \"content\": {
      \"type\": \"text\",
      \"text\": \"What is the weather today?\"
    },
    \"metadata\": {
      \"channel_id\": \"$CHANNEL_ID\"
    },
    \"timestamp\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"
  }" | jq .
```

### 4. Test Async Processing

```bash
# Send message with async_processing=true
curl -X POST "http://localhost:8000/messages/inbound?async_processing=true" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d "{
    \"tenant_id\": \"$TENANT_ID\",
    \"channel\": \"telegram\",
    \"direction\": \"inbound\",
    \"from\": {
      \"type\": \"user\",
      \"external_id\": \"user-123\"
    },
    \"to\": {
      \"type\": \"bot\",
      \"external_id\": \"\"
    },
    \"content\": {
      \"type\": \"text\",
      \"text\": \"Hello\"
    },
    \"metadata\": {
      \"channel_id\": \"$CHANNEL_ID\"
    }
  }" | jq .

# Get job status (use job_id from response)
curl "http://localhost:8000/messages/status/<job_id>" | jq .
```

### 5. Start Worker (for async processing)

In a separate terminal:

```bash
source venv/bin/activate
python scripts/start_worker.py --queue default
```

## 🔍 Verify Data in Database

### Check Messages

```sql
-- Connect to database
psql -d nexus_hub

-- View recent messages
SELECT 
    id,
    tenant_id,
    direction,
    content_text,
    created_at
FROM messages
ORDER BY created_at DESC
LIMIT 10;
```

### Check Conversations

```sql
SELECT 
    id,
    tenant_id,
    channel_id,
    external_thread_id,
    created_at
FROM conversations
ORDER BY created_at DESC
LIMIT 10;
```

### Check Event Logs

```sql
SELECT 
    event_type,
    provider,
    status,
    created_at
FROM event_logs
ORDER BY created_at DESC
LIMIT 20;
```

### Check API Keys

```sql
SELECT 
    id,
    tenant_id,
    name,
    is_active,
    expires_at,
    created_at
FROM api_keys
WHERE tenant_id = '<your-tenant-id>';
```

## 🧪 Testing Different Scenarios

### Test 1: Basic Conversation

```bash
# First message
curl -X POST "http://localhost:8000/messages/inbound" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d "{
    \"tenant_id\": \"$TENANT_ID\",
    \"channel\": \"telegram\",
    \"direction\": \"inbound\",
    \"from\": {\"type\": \"user\", \"external_id\": \"user-123\"},
    \"to\": {\"type\": \"bot\", \"external_id\": \"\"},
    \"content\": {\"type\": \"text\", \"text\": \"Hello\"},
    \"metadata\": {\"channel_id\": \"$CHANNEL_ID\", \"external_thread_id\": \"thread-123\"}
  }" | jq .

# Follow-up message (same thread)
curl -X POST "http://localhost:8000/messages/inbound" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d "{
    \"tenant_id\": \"$TENANT_ID\",
    \"channel\": \"telegram\",
    \"direction\": \"inbound\",
    \"from\": {\"type\": \"user\", \"external_id\": \"user-123\"},
    \"to\": {\"type\": \"bot\", \"external_id\": \"\"},
    \"content\": {\"type\": \"text\", \"text\": \"What did I just say?\"},
    \"metadata\": {\"channel_id\": \"$CHANNEL_ID\", \"external_thread_id\": \"thread-123\"}
  }" | jq .
```

### Test 2: Update Tenant Prompt

```bash
curl -X PUT "http://localhost:8000/tenants/$TENANT_ID/prompt" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{
    "custom_system_prompt": "You are a helpful customer support assistant for Test Company. Be friendly and professional.",
    "override_mode": "append"
  }' | jq .
```

### Test 3: List API Keys

```bash
curl -X GET "http://localhost:8000/tenants/$TENANT_ID/api-keys" \
  -H "X-API-Key: $API_KEY" | jq .
```

### Test 4: Revoke API Key

```bash
# Get key ID from list
KEY_ID="<key-id-from-list>"

curl -X DELETE "http://localhost:8000/tenants/$TENANT_ID/api-keys/$KEY_ID?permanent=false" \
  -H "X-API-Key: $API_KEY" | jq .
```

## 🐛 Troubleshooting

### Issue: "Database connection failed"

```bash
# Check PostgreSQL is running
pg_isready

# Check connection string in .env
cat .env | grep DATABASE_URL

# Test connection
psql -d nexus_hub -c "SELECT 1;"
```

### Issue: "Redis connection failed"

```bash
# Check Redis is running
redis-cli ping

# The app will fall back to in-memory rate limiting if Redis is unavailable
# This is fine for development
```

### Issue: "Import errors"

```bash
# Make sure venv is activated
which python  # Should show venv path

# Reinstall dependencies
pip install -r requirements.txt --force-reinstall
```

### Issue: "RLS policy violation"

```bash
# Make sure you're setting tenant context in your queries
# Check that tenant_id matches in your API calls
```

### Issue: "API key authentication failed"

```bash
# Check API key is correct
echo $API_KEY

# Verify API key exists in database
psql -d nexus_hub -c "
  SELECT id, tenant_id, name, is_active 
  FROM api_keys 
  WHERE is_active = TRUE;
"

# Check master key is set (for creating API keys)
cat .env | grep MASTER_API_KEY
```

## 📊 Monitoring

### View Logs

The server logs are printed to console. For structured JSON logs, check the console output.

### Check Metrics

```bash
# Prometheus metrics
curl http://localhost:8000/metrics | grep -E "(http_requests|llm_calls|tool_calls)"
```

### Database Stats

```sql
-- Message count per tenant
SELECT tenant_id, COUNT(*) as message_count
FROM messages
GROUP BY tenant_id;

-- Conversation stats
SELECT 
    tenant_id,
    COUNT(*) as conversation_count,
    AVG(total_messages) as avg_messages
FROM conversation_stats
GROUP BY tenant_id;
```

## 📱 Testing with Telegram (Optional)

The orchestrator includes a Telegram adapter for easy testing via Telegram bots.

### Quick Setup

1. **Get a Telegram Bot Token:**
   - Open Telegram and search for [@BotFather](https://t.me/botfather)
   - Send `/newbot` and follow instructions
   - Copy the bot token (format: `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`)

2. **Configure Environment:**
   ```bash
   # Add to .env
   TELEGRAM_BOT_TOKEN=your_bot_token_here
   TELEGRAM_DEFAULT_TENANT_ID=your_tenant_uuid_here  # Optional
   ```

3. **Set Up Webhook (for local testing with ngrok):**
   ```bash
   # Install ngrok if needed
   # Start ngrok tunnel
   ngrok http 8000
   
   # You'll get a URL like: https://abc123.ngrok.io
   # Register webhook with Telegram
   curl -X POST "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook" \
     -H "Content-Type: application/json" \
     -d '{
       "url": "https://abc123.ngrok.io/webhooks/telegram?tenant_id=YOUR_TENANT_ID"
     }'
   ```

4. **Test:**
   - Start the server: `uvicorn app.main:app --reload`
   - Send a message to your bot on Telegram
   - The bot should respond through the orchestrator!

**Note:** If you set `TELEGRAM_DEFAULT_TENANT_ID` in `.env`, you can omit the `tenant_id` query parameter.

For detailed setup instructions, see [docs/guides/TELEGRAM_SETUP.md](docs/guides/TELEGRAM_SETUP.md).

## 🔍 Setting Up OpenAI File Search

OpenAI file search uses vector stores to enable semantic search over your documents. Here's how to set it up:

### Step 1: Get Your OpenAI API Key

1. Go to [OpenAI Platform](https://platform.openai.com/)
2. Navigate to API Keys section
3. Create a new API key
4. Add it to your `.env` file:
   ```bash
   OPENAI_API_KEY=sk-your-key-here
   ```

### Step 2: Create a Vector Store in OpenAI

You need to create a vector store in OpenAI and upload files to it. This can be done via the OpenAI API:

```bash
# Install OpenAI CLI if needed
pip install openai

# Create a vector store
python3 << EOF
from openai import OpenAI
import os

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Create vector store
vector_store = client.beta.vector_stores.create(
    name="My Knowledge Base"
)

print(f"Vector Store ID: {vector_store.id}")
print(f"Save this ID - you'll need it for the knowledge base configuration!")
EOF
```

**Save the Vector Store ID** - you'll need it in the next step.

### Step 3: Upload Files to Vector Store (Optional)

```bash
# Upload a file
python3 << EOF
from openai import OpenAI
import os

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
VECTOR_STORE_ID = "vs_your_vector_store_id_here"

# Upload file
file = client.files.create(
    file=open("path/to/your/document.pdf", "rb"),
    purpose="assistants"
)

# Add file to vector store
client.beta.vector_stores.files.create(
    vector_store_id=VECTOR_STORE_ID,
    file_id=file.id
)

print(f"File {file.id} uploaded to vector store {VECTOR_STORE_ID}")
EOF
```

### Step 4: Configure Knowledge Base in Database

Insert the knowledge base configuration into your database:

```sql
-- Connect to database
psql -d nexus_hub

-- Insert OpenAI file search knowledge base
-- Replace <tenant_id> with your actual tenant ID
-- Replace <vector_store_id> with the ID from Step 2
INSERT INTO knowledge_bases (
    id,
    tenant_id,
    name,
    description,
    provider,
    provider_config,
    is_active
)
VALUES (
    gen_random_uuid(),
    '<tenant_id>',
    'openai_kb',
    'OpenAI File Search Knowledge Base',
    'openai_file',
    jsonb_build_object(
        'vector_store_id', '<vector_store_id>'
    ),
    TRUE
)
RETURNING id, name;
```

### Step 5: Create and Enable a Tool (Optional)

If you want to use file search as a tool that can be called explicitly:

```sql
-- Create a tool for OpenAI file search
INSERT INTO tools (
    id,
    name,
    description,
    provider,
    implementation_ref
)
VALUES (
    gen_random_uuid(),
    'openai_file_search',
    'Search documents using OpenAI file search',
    'openai_file',
    jsonb_build_object(
        'kb_name', 'openai_kb'
    )
)
RETURNING id;

-- Enable the tool for your tenant
-- Replace <tenant_id> and <tool_id> with your actual IDs
INSERT INTO tenant_tool_policies (
    tenant_id,
    tool_id,
    is_enabled
)
VALUES (
    '<tenant_id>',
    '<tool_id>',
    TRUE
);
```

### Step 6: Test OpenAI File Search

Once configured, OpenAI file search will automatically be used when:
- Your tenant uses `llm_provider = 'openai'`
- The knowledge base is active
- The vector store ID is valid

The system will automatically attach the vector store to chat completions, enabling file search in responses.

---

## 🔍 Setting Up Gemini File Search

Gemini file search uses corpora to enable semantic search over your documents. Here's how to set it up:

### Step 1: Get Your Gemini API Key

1. Go to [Google AI Studio](https://makersuite.google.com/app/apikey)
2. Create a new API key
3. Add it to your `.env` file:
   ```bash
   GEMINI_API_KEY=your-key-here
   ```

### Step 2: Create a Corpus in Gemini

You need to create a corpus in Gemini and upload files to it. This is done via the Gemini API:

```bash
# Install Google Generative AI SDK if needed
pip install google-generativeai

# Create a corpus
python3 << EOF
import google.generativeai as genai
import os

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# Create a corpus
corpus = genai.create_corpus(
    name="My Knowledge Base"
)

print(f"Corpus ID: {corpus.name}")
print(f"Save this ID - you'll need it for the knowledge base configuration!")
EOF
```

**Save the Corpus ID** - you'll need it in the next step.

### Step 3: Upload Files to Corpus (Optional)

```bash
# Upload a file to the corpus
python3 << EOF
import google.generativeai as genai
import os

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
CORPUS_ID = "corpora/your_corpus_id_here"

# Upload file
file = genai.upload_file(
    path="path/to/your/document.pdf",
    display_name="My Document"
)

# Add file to corpus
genai.create_file_in_corpus(
    corpus_name=CORPUS_ID,
    file=file
)

print(f"File {file.name} uploaded to corpus {CORPUS_ID}")
EOF
```

### Step 4: Configure Knowledge Base in Database

Insert the knowledge base configuration into your database:

```sql
-- Connect to database
psql -d nexus_hub

-- Insert Gemini file search knowledge base
-- Replace <tenant_id> with your actual tenant ID
-- Replace <corpus_id> with the ID from Step 2 (format: "corpora/...")
INSERT INTO knowledge_bases (
    id,
    tenant_id,
    name,
    description,
    provider,
    provider_config,
    is_active
)
VALUES (
    gen_random_uuid(),
    '<tenant_id>',
    'gemini_kb',
    'Gemini File Search Knowledge Base',
    'gemini_file',
    jsonb_build_object(
        'corpus_id', '<corpus_id>'
    ),
    TRUE
)
RETURNING id, name;
```

### Step 5: Create and Enable a Tool (Optional)

If you want to use file search as a tool that can be called explicitly:

```sql
-- Create a tool for Gemini file search
INSERT INTO tools (
    id,
    name,
    description,
    provider,
    implementation_ref
)
VALUES (
    gen_random_uuid(),
    'gemini_file_search',
    'Search documents using Gemini file search',
    'gemini_file',
    jsonb_build_object(
        'kb_name', 'gemini_kb'
    )
)
RETURNING id;

-- Enable the tool for your tenant
-- Replace <tenant_id> and <tool_id> with your actual IDs
INSERT INTO tenant_tool_policies (
    tenant_id,
    tool_id,
    is_enabled
)
VALUES (
    '<tenant_id>',
    '<tool_id>',
    TRUE
);
```

### Step 6: Test Gemini File Search

Once configured, Gemini file search will automatically be used when:
- Your tenant uses `llm_provider = 'gemini'`
- The knowledge base is active
- The corpus ID is valid

The system will automatically attach the corpus to the GenerativeModel, enabling file search in responses.

---

## 🎯 Next Steps

1. **Set up OpenAI File Search** (see section above)

2. **Set up Gemini File Search** (see section above)

3. **Set up Telegram bot** (see above or `docs/guides/TELEGRAM_SETUP.md`)

4. **Set up RAG** (see `docs/guides/VECTOR_INDEX_SETUP.md`)

5. **Configure tools** in the database

6. **Set up monitoring** (Prometheus, Grafana)

7. **Read full documentation**:
   - `README.md` - Overview
   - `docs/guides/QUICK_REFERENCE.md` - Quick command reference
   - `docs/guides/LOCAL_DEVELOPMENT.md` - Detailed dev guide
   - `docs/guides/TELEGRAM_SETUP.md` - Telegram adapter setup
   - `docs/audit/PRODUCTION_READINESS.md` - Production checklist

## 📚 Additional Resources

- **Swagger UI**: http://localhost:8000/docs (Interactive API testing)
- **ReDoc**: http://localhost:8000/redoc (API documentation)
- **Health Check**: http://localhost:8000/health
- **Metrics**: http://localhost:8000/metrics
- **Telegram Webhook**: http://localhost:8000/webhooks/telegram (for Telegram bot testing)

## 💡 Tips

- **Use jq for pretty JSON**: `curl ... | jq .`
- **Save responses**: `curl ... > response.json`
- **Watch logs**: Keep server terminal visible
- **Test incrementally**: Start with health checks, then simple messages
- **Use Swagger UI**: Visit `http://localhost:8000/docs` for interactive API testing

## 🆘 Quick Reference

```bash
# Start server
source venv/bin/activate
uvicorn app.main:app --reload

# Start worker (separate terminal)
source venv/bin/activate
python scripts/start_worker.py --queue default

# Setup test data
./scripts/setup_test_data.sh

# Create API key
./scripts/create_api_key.sh

# Test API (send a test message)
curl -X POST "http://localhost:8000/messages/inbound" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{
    "id": "msg-test-1",
    "tenant_id": "'"$TENANT_ID"'",
    "conversation_id": "conv-test-1",
    "channel": "web",
    "direction": "inbound",
    "from": {"type": "user", "external_id": "user-1"},
    "to": {"type": "bot", "external_id": "bot-1"},
    "content": {"type": "text", "text": "Hello, how can you help me?"},
    "metadata": {},
    "timestamp": "'"$(date -u +"%Y-%m-%dT%H:%M:%SZ")"'"
  }'

# Health check
curl http://localhost:8000/health

# Readiness check
curl http://localhost:8000/health/ready

# Metrics
curl http://localhost:8000/metrics

# API docs
open http://localhost:8000/docs
```

## 📋 Complete Example Workflow

Here's a complete example from scratch:

```bash
# 1. Setup
source venv/bin/activate
cp .env.example .env
# Edit .env with DATABASE_URL

# 2. Database
createdb nexus_hub
psql -d nexus_hub -f migrations/001_initial_schema.sql
psql -d nexus_hub -f migrations/002_enable_rls.sql
# Run API keys migration if it exists
[ -f migrations/004_create_api_keys_table.sql ] && psql -d nexus_hub -f migrations/004_create_api_keys_table.sql

# 3. Create test data
./scripts/setup_test_data.sh
# Copy TENANT_ID and CHANNEL_ID to .env

# 4. Set master key
echo "MASTER_API_KEY=dev-master-key-12345" >> .env

# 5. Start server
uvicorn app.main:app --reload

# 6. In another terminal, create API key
source venv/bin/activate
./scripts/create_api_key.sh
# Copy API_KEY to .env

# 7. Test (send a test message)
curl -X POST "http://localhost:8000/messages/inbound" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{
    "id": "msg-test-1",
    "tenant_id": "'"$TENANT_ID"'",
    "conversation_id": "conv-test-1",
    "channel": "web",
    "direction": "inbound",
    "from": {"type": "user", "external_id": "user-1"},
    "to": {"type": "bot", "external_id": "bot-1"},
    "content": {"type": "text", "text": "Hello, how can you help me?"},
    "metadata": {},
    "timestamp": "'"$(date -u +"%Y-%m-%dT%H:%M:%SZ")"'"
  }'

# 8. Send a message manually
curl -X POST "http://localhost:8000/messages/inbound" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $(grep API_KEY .env | cut -d= -f2)" \
  -d "{
    \"tenant_id\": \"$(grep TENANT_ID .env | cut -d= -f2)\",
    \"channel\": \"telegram\",
    \"direction\": \"inbound\",
    \"from\": {\"type\": \"user\", \"external_id\": \"user-123\"},
    \"to\": {\"type\": \"bot\", \"external_id\": \"\"},
    \"content\": {\"type\": \"text\", \"text\": \"Hello!\"},
    \"metadata\": {}
  }" | jq .
```

Happy coding! 🚀

