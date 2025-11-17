# API Key Management Implementation

## Overview

This document describes the implementation of secure API key management with hashed keys, replacing the previous insecure method that accepted tenant_id as API keys.

## Security Features

### ✅ Secure Key Generation
- Uses `secrets.token_urlsafe()` to generate cryptographically secure random keys
- Keys are 64 characters long (48 bytes of entropy)
- URL-safe base64 encoding

### ✅ Secure Key Storage
- API keys are hashed using bcrypt (cost factor 12)
- Only key hashes are stored in the database
- Plain text keys are never stored
- Key prefix (first 8 characters) stored for identification

### ✅ Key Verification
- Uses bcrypt password verification
- Efficient lookup using key prefix before expensive hash verification
- Automatic last_used_at timestamp updates

### ✅ Tenant Isolation
- Row-Level Security (RLS) enabled on api_keys table
- Tenants can only see/manage their own API keys
- Master key support for admin operations

### ✅ Key Lifecycle Management
- Optional expiration dates
- Revocation (deactivation) support
- Permanent deletion support
- Usage tracking (last_used_at)

## Database Schema

### api_keys Table

```sql
CREATE TABLE api_keys (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    key_hash            TEXT NOT NULL,                    -- bcrypt hashed API key
    key_prefix          TEXT NOT NULL,                    -- First 8 characters
    name                TEXT,                            -- Human-readable name
    description         TEXT,                            -- Optional description
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    rate_limit_per_minute INTEGER DEFAULT 100,
    created_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    expires_at          TIMESTAMP WITH TIME ZONE,        -- Optional expiration
    last_used_at        TIMESTAMP WITH TIME ZONE,        -- Track last usage
    created_by          TEXT,                            -- User/system that created
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb
);
```

### Indexes
- `idx_api_keys_tenant_id` - Fast tenant lookups
- `idx_api_keys_key_prefix` - Fast prefix lookups for verification
- `idx_api_keys_key_hash` - Hash lookups (rare, but indexed)
- `idx_api_keys_active` - Filter active keys efficiently

### RLS Policy
```sql
CREATE POLICY api_keys_tenant_isolation ON api_keys
USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);
```

## API Endpoints

### Create API Key
```http
POST /tenants/{tenant_id}/api-keys
Authorization: X-API-Key: <existing_key>

{
  "name": "Production Key",
  "description": "Key for production environment",
  "expires_in_days": 365,
  "rate_limit_per_minute": 100,
  "metadata": {}
}
```

**Response:**
```json
{
  "api_key": "abc123...xyz789",  // ⚠️ Only shown once!
  "key_id": "uuid-here",
  "key_prefix": "abc12345",
  "name": "Production Key",
  "expires_at": "2026-01-16T00:00:00Z",
  "created_at": "2025-01-16T00:00:00Z",
  "rate_limit_per_minute": 100
}
```

**⚠️ WARNING**: The plain text API key is only returned once. Store it securely immediately!

### List API Keys
```http
GET /tenants/{tenant_id}/api-keys?include_inactive=false
Authorization: X-API-Key: <existing_key>
```

**Response:**
```json
{
  "keys": [
    {
      "key_id": "uuid-here",
      "key_prefix": "abc12345",
      "name": "Production Key",
      "is_active": true,
      "expires_at": "2026-01-16T00:00:00Z",
      "last_used_at": "2025-01-16T10:30:00Z",
      "rate_limit_per_minute": 100
    }
  ],
  "count": 1
}
```

**Note**: The actual API keys are never returned in list operations.

### Revoke API Key
```http
DELETE /tenants/{tenant_id}/api-keys/{key_id}?permanent=false
Authorization: X-API-Key: <existing_key>
```

**Response:**
```json
{
  "status": "revoked",
  "message": "API key revoked"
}
```

Set `permanent=true` to permanently delete the key.

## Migration Guide

### Step 1: Run Migration

```bash
# Apply the migration
psql -d nexus_hub -f migrations/004_create_api_keys_table.sql

# Or using Alembic
alembic upgrade head
```

### Step 2: Install Dependencies

```bash
pip install -r requirements.txt  # Includes bcrypt==4.2.0
```

### Step 3: Create API Keys for Existing Tenants

For each tenant, create a new API key:

```bash
curl -X POST http://localhost:8000/tenants/{tenant_id}/api-keys \
  -H "X-API-Key: <master_key>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Initial Key",
    "description": "Migration from tenant_id-based auth"
  }'
```

**⚠️ IMPORTANT**: Store the returned `api_key` securely. It will not be shown again.

### Step 4: Update Client Applications

Update all client applications to use the new API keys instead of tenant_id:

**Before:**
```bash
curl -H "X-API-Key: <tenant_id>" ...
```

**After:**
```bash
curl -H "X-API-Key: <api_key_from_step_3>" ...
```

### Step 5: Revoke Old Access

After all clients are migrated, the old tenant_id-based authentication will automatically fail (as it's now disabled in the code).

## Service Functions

### `generate_api_key() -> str`
Generates a secure random API key (64 characters).

### `hash_api_key(api_key: str) -> str`
Hashes an API key using bcrypt.

### `verify_api_key(api_key: str, key_hash: str) -> bool`
Verifies an API key against its hash.

### `create_api_key(...) -> Dict`
Creates a new API key and returns it (only time the plain key is shown).

### `list_api_keys(tenant_id: str, include_inactive: bool) -> List[Dict]`
Lists all API keys for a tenant (without the actual keys).

### `revoke_api_key(tenant_id: str, key_id: str) -> bool`
Deactivates an API key.

### `delete_api_key(tenant_id: str, key_id: str) -> bool`
Permanently deletes an API key.

### `verify_and_get_tenant_id(api_key: str, db: Session) -> Optional[str]`
Verifies an API key and returns the tenant_id. Used by authentication middleware.

## Security Considerations

### ✅ What's Secure
- Keys are hashed with bcrypt (cost factor 12)
- Plain text keys never stored in database
- Keys only shown once during creation
- Tenant isolation via RLS
- Key expiration support
- Usage tracking

### ⚠️ Best Practices
1. **Store keys securely**: Use a secrets manager (Vault, AWS Secrets Manager)
2. **Rotate keys regularly**: Create new keys and revoke old ones
3. **Set expiration dates**: Don't create keys that never expire
4. **Monitor usage**: Check `last_used_at` to identify unused keys
5. **Use descriptive names**: Name keys by environment/purpose
6. **Limit rate limits**: Set appropriate `rate_limit_per_minute` per key

### 🔒 Security Notes
- Master key still supported for admin operations (from `MASTER_API_KEY` env var)
- Old tenant_id-based authentication is **disabled** (raises 401)
- Key prefix lookup is used for efficiency (bcrypt is slow)
- Multiple keys can have the same prefix (rare but handled)

## Testing

### Manual Testing

1. **Create a key:**
```bash
curl -X POST http://localhost:8000/tenants/{tenant_id}/api-keys \
  -H "X-API-Key: <master_key>" \
  -H "Content-Type: application/json" \
  -d '{"name": "Test Key"}'
```

2. **Use the key:**
```bash
curl -X POST http://localhost:8000/messages/inbound \
  -H "X-API-Key: <new_key_from_step_1>" \
  -H "Content-Type: application/json" \
  -d '{...}'
```

3. **List keys:**
```bash
curl http://localhost:8000/tenants/{tenant_id}/api-keys \
  -H "X-API-Key: <master_key>"
```

4. **Revoke key:**
```bash
curl -X DELETE "http://localhost:8000/tenants/{tenant_id}/api-keys/{key_id}" \
  -H "X-API-Key: <master_key>"
```

5. **Verify revocation:**
```bash
# This should now fail with 401
curl -X POST http://localhost:8000/messages/inbound \
  -H "X-API-Key: <revoked_key>" \
  -H "Content-Type: application/json" \
  -d '{...}'
```

## Troubleshooting

### "Invalid API key format"
- Key must be at least 16 characters
- Check that you're using the full API key (64 characters)

### "Invalid API key"
- Key may be revoked or expired
- Check key status via list endpoint
- Verify you're using the correct key

### "API key verification failed"
- Database table may not exist (run migration)
- Check database connection
- Verify bcrypt is installed

### Migration Issues
- If migration fails, check that `pgcrypto` extension is enabled
- Ensure `tenants` table exists before creating `api_keys`
- Check RLS is enabled on the table

## Future Enhancements

1. **Key Rotation**: Automatic key rotation before expiration
2. **Key Scopes**: Limit keys to specific endpoints/operations
3. **Key Analytics**: Track usage patterns, rate limit violations
4. **Key Templates**: Pre-configured key settings for common use cases
5. **Webhook Notifications**: Alert on key creation/revocation
6. **Key Sharing**: Secure key sharing between team members (encrypted)

