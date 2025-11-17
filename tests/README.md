# Test Suite Documentation

## Test Structure

### Unit Tests
- `test_prompt_validator.py` - Prompt validation logic
- `test_prompt_builder.py` - Prompt building with layered stack
- `test_tenant_context.py` - TenantContext model validation

### Integration Tests
- `test_admin_api.py` - Admin API endpoint tests
- `test_integration_e2e.py` - End-to-end message processing flow
- `test_integration_rls.py` - Row-Level Security isolation tests

## Running Tests

### All Tests
```bash
pytest tests/ -v
```

### Specific Test Files
```bash
# Unit tests
pytest tests/test_prompt_validator.py -v
pytest tests/test_prompt_builder.py -v

# Integration tests
pytest tests/test_admin_api.py -v
pytest tests/test_integration_e2e.py -v
pytest tests/test_integration_rls.py -v
```

### With Coverage
```bash
pytest tests/ --cov=app --cov-report=html
```

## Test Database Setup

Integration tests require a separate test database:

```bash
# Create test database
createdb nexus_hub_test

# Run migrations on test database
psql -d nexus_hub_test -f migrations/001_initial_schema.sql
psql -d nexus_hub_test -f migrations/002_enable_rls.sql

# Set test database URL
export TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/nexus_hub_test
```

## Test Fixtures

### `test_db`
Provides a database session for tests. Requires test database to be set up.

### `test_tenant`
Creates a test tenant in the database.

### `test_channel`
Creates a test channel for a tenant.

### `client`
FastAPI TestClient with test database dependency override.

## RLS Isolation Tests

The RLS isolation tests verify that:
1. Tenants cannot see each other's data
2. RLS policies are enforced correctly
3. Cross-tenant access is blocked

These tests require RLS to be enabled on the test database.

## End-to-End Tests

The E2E tests verify:
1. Complete message processing flow
2. Conversation creation
3. Event logging
4. Conversation stats updates

Note: These tests may return 500 if LLM API keys are not configured, which is expected.

## Skipping Tests

To skip tests that require external services:

```bash
# Skip integration tests
pytest tests/ -v -k "not integration"

# Skip E2E tests
pytest tests/ -v -k "not e2e"
```

