#!/bin/bash
# Setup test data for local development

set -e

echo "🚀 Setting up test data for Nexus Hub..."
echo ""

# Check if database exists
if ! psql -lqt | cut -d \| -f 1 | grep -qw nexus_hub; then
    echo "❌ Database 'nexus_hub' does not exist!"
    echo "   Create it first: createdb nexus_hub"
    exit 1
fi

# Check if migrations have been run
if ! psql -d nexus_hub -t -c "SELECT 1 FROM tenants LIMIT 1;" > /dev/null 2>&1; then
    echo "⚠️  Database tables not found. Running migrations..."
    psql -d nexus_hub -f migrations/001_initial_schema.sql > /dev/null 2>&1
    psql -d nexus_hub -f migrations/002_enable_rls.sql > /dev/null 2>&1
    if [ -f migrations/004_create_api_keys_table.sql ]; then
        psql -d nexus_hub -f migrations/004_create_api_keys_table.sql > /dev/null 2>&1
    fi
    echo "✅ Migrations completed"
fi

# Create tenant
echo "📝 Creating test tenant..."
TENANT_ID=$(psql -d nexus_hub -t -c "
  INSERT INTO tenants (id, name, llm_provider, llm_model, isolation_mode, created_at)
  VALUES (gen_random_uuid(), 'Test Company', 'openai', 'gpt-4o-mini', 'shared_db', NOW())
  RETURNING id;
" | xargs)

if [ -z "$TENANT_ID" ]; then
    echo "❌ Failed to create tenant"
    exit 1
fi

echo "✅ Created tenant: $TENANT_ID"

# Create channel
echo "📝 Creating test channel..."
CHANNEL_ID=$(psql -d nexus_hub -t -c "
  INSERT INTO channels (id, tenant_id, channel_type, name, is_active, created_at)
  VALUES (gen_random_uuid(), '$TENANT_ID', 'telegram', 'Telegram Bot', TRUE, NOW())
  RETURNING id;
" | xargs)

if [ -z "$CHANNEL_ID" ]; then
    echo "❌ Failed to create channel"
    exit 1
fi

echo "✅ Created channel: $CHANNEL_ID"

# Create a simple tool (optional)
echo "📝 Creating test tool..."
psql -d nexus_hub -q -c "
  INSERT INTO tools (id, name, provider, description, schema_definition, created_at)
  VALUES (
    gen_random_uuid(),
    'internal_rag_search',
    'internal_rag',
    'Search internal knowledge base',
    '{\"type\": \"object\", \"properties\": {\"query\": {\"type\": \"string\"}, \"kb_name\": {\"type\": \"string\"}}}'::jsonb,
    NOW()
  )
  ON CONFLICT DO NOTHING;
" > /dev/null

echo "✅ Test tool ready"

# Enable tool for tenant
echo "📝 Enabling tool for tenant..."
psql -d nexus_hub -q -c "
  INSERT INTO tenant_tool_policies (tenant_id, tool_name, is_allowed, created_at)
  SELECT '$TENANT_ID', name, TRUE, NOW()
  FROM tools
  WHERE name = 'internal_rag_search'
  ON CONFLICT DO NOTHING;
" > /dev/null

echo "✅ Tool enabled for tenant"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Setup complete!"
echo ""
echo "Add these to your .env file or export them:"
echo ""
echo "export TENANT_ID=\"$TENANT_ID\""
echo "export CHANNEL_ID=\"$CHANNEL_ID\""
echo ""
echo "Or add to .env:"
echo "TENANT_ID=$TENANT_ID"
echo "CHANNEL_ID=$CHANNEL_ID"
echo ""
echo "Next steps:"
echo "1. Set MASTER_API_KEY in .env (for creating API keys)"
echo "2. Start the server: uvicorn app.main:app --reload"
echo "3. Create an API key: curl -X POST http://localhost:8000/tenants/$TENANT_ID/api-keys \\"
echo "     -H \"X-API-Key: \$MASTER_API_KEY\" \\"
echo "     -H \"Content-Type: application/json\" \\"
echo "     -d '{\"name\": \"Test Key\"}'"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

