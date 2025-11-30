#!/bin/bash
# Helper script to create an API key

set -e

# Load environment variables
if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
fi

if [ -z "$TENANT_ID" ]; then
    echo "❌ TENANT_ID not set. Set it in .env or export it."
    exit 1
fi

if [ -z "$MASTER_API_KEY" ]; then
    echo "❌ MASTER_API_KEY not set. Set it in .env:"
    echo "   MASTER_API_KEY=dev-master-key-12345"
    exit 1
fi

BASE_URL="${BASE_URL:-http://localhost:8000}"

echo "🔑 Creating API key for tenant: $TENANT_ID"
echo ""

RESPONSE=$(curl -s -X POST "$BASE_URL/tenants/$TENANT_ID/api-keys" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $MASTER_API_KEY" \
  -d '{
    "name": "Development Key",
    "description": "Key for local development and testing",
    "rate_limit_per_minute": 1000
  }')

echo "$RESPONSE" | jq .

# Extract API key
API_KEY=$(echo "$RESPONSE" | jq -r '.api_key // empty')

if [ -n "$API_KEY" ] && [ "$API_KEY" != "null" ]; then
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "✅ API Key created!"
    echo ""
    echo "⚠️  IMPORTANT: Save this key now - it won't be shown again!"
    echo ""
    echo "API_KEY=$API_KEY"
    echo ""
    echo "Add to .env:"
    echo "echo \"API_KEY=$API_KEY\" >> .env"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
fi


