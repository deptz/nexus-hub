"""RLS (Row-Level Security) isolation tests."""

import pytest
import uuid
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import os
try:
    from app.infra.config import config
except ImportError:
    # Fallback if config not available
    class Config:
        DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/nexus_hub")
    config = Config()

# Test database URL
TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    config.DATABASE_URL.replace("/nexus_hub", "/nexus_hub_test") if hasattr(config, 'DATABASE_URL') else "postgresql://postgres:postgres@localhost:5432/nexus_hub_test"
)

test_engine = create_engine(TEST_DATABASE_URL)
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture
def test_db():
    """Create test database session with cleanup."""
    session = TestSessionLocal()
    try:
        yield session
    finally:
        # Clean up all test data after each test
        try:
            # Delete in reverse order of dependencies to avoid foreign key constraints
            # Note: CASCADE deletes will handle dependent rows, but explicit order is safer
            session.execute(text("DELETE FROM event_logs"))
            session.execute(text("DELETE FROM messages"))
            session.execute(text("DELETE FROM conversations"))
            session.execute(text("DELETE FROM api_keys"))
            session.execute(text("DELETE FROM tenants"))
            session.commit()
        except Exception as e:
            # If cleanup fails, rollback and continue
            session.rollback()
            print(f"Warning: Cleanup failed: {e}")
        finally:
            # Session close will clear any session variables
            session.close()


@pytest.fixture
def tenant1(test_db):
    """Create tenant 1."""
    tenant_id = str(uuid.uuid4())
    slug = f"tenant-1-{tenant_id[:8]}"  # Unique slug per test
    test_db.execute(
        text("""
            INSERT INTO tenants (id, name, slug, llm_provider, llm_model)
            VALUES (:id, 'Tenant 1', :slug, 'openai', 'gpt-4o-mini')
        """),
        {"id": tenant_id, "slug": slug}
    )
    test_db.commit()
    return tenant_id


@pytest.fixture
def tenant2(test_db):
    """Create tenant 2."""
    tenant_id = str(uuid.uuid4())
    slug = f"tenant-2-{tenant_id[:8]}"  # Unique slug per test
    test_db.execute(
        text("""
            INSERT INTO tenants (id, name, slug, llm_provider, llm_model)
            VALUES (:id, 'Tenant 2', :slug, 'openai', 'gpt-4o-mini')
        """),
        {"id": tenant_id, "slug": slug}
    )
    test_db.commit()
    return tenant_id


class TestRLSIsolation:
    """Test Row-Level Security isolation between tenants."""
    
    def test_messages_isolation(self, test_db, tenant1, tenant2):
        """Test that tenants cannot see each other's messages."""
        # Create messages for tenant1 (set tenant context for RLS)
        test_db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant1})
        test_db.commit()
        msg1_id = str(uuid.uuid4())
        conv1_id = str(uuid.uuid4())
        test_db.execute(
            text("""
                INSERT INTO conversations (id, tenant_id, status)
                VALUES (:id, :tenant_id, 'open')
            """),
            {"id": conv1_id, "tenant_id": tenant1}
        )
        test_db.execute(
            text("""
                INSERT INTO messages (id, tenant_id, conversation_id, direction, from_type, content_text)
                VALUES (:id, :tenant_id, :conv_id, 'inbound', 'user', 'Tenant 1 message')
            """),
            {"id": msg1_id, "tenant_id": tenant1, "conv_id": conv1_id}
        )
        
        # Create messages for tenant2 (set tenant context for RLS)
        test_db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant2})
        test_db.commit()
        msg2_id = str(uuid.uuid4())
        conv2_id = str(uuid.uuid4())
        test_db.execute(
            text("""
                INSERT INTO conversations (id, tenant_id, status)
                VALUES (:id, :tenant_id, 'open')
            """),
            {"id": conv2_id, "tenant_id": tenant2}
        )
        test_db.execute(
            text("""
                INSERT INTO messages (id, tenant_id, conversation_id, direction, from_type, content_text)
                VALUES (:id, :tenant_id, :conv_id, 'inbound', 'user', 'Tenant 2 message')
            """),
            {"id": msg2_id, "tenant_id": tenant2, "conv_id": conv2_id}
        )
        test_db.commit()
        
        # Set tenant context for tenant1
        test_db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant1})
        test_db.commit()
        
        # Query messages as tenant1
        messages = test_db.execute(
            text("SELECT id, content_text FROM messages")
        ).fetchall()
        
        # Should only see tenant1's messages
        assert len(messages) == 1
        assert messages[0].content_text == "Tenant 1 message"
        
        # Set tenant context for tenant2
        test_db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant2})
        test_db.commit()
        
        # Query messages as tenant2
        messages = test_db.execute(
            text("SELECT id, content_text FROM messages")
        ).fetchall()
        
        # Should only see tenant2's messages
        assert len(messages) == 1
        assert messages[0].content_text == "Tenant 2 message"
    
    def test_conversations_isolation(self, test_db, tenant1, tenant2):
        """Test that tenants cannot see each other's conversations."""
        # Create conversations for tenant1
        test_db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant1})
        test_db.commit()
        conv1_id = str(uuid.uuid4())
        test_db.execute(
            text("""
                INSERT INTO conversations (id, tenant_id, status)
                VALUES (:id, :tenant_id, 'open')
            """),
            {"id": conv1_id, "tenant_id": tenant1}
        )
        
        # Create conversations for tenant2
        test_db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant2})
        test_db.commit()
        conv2_id = str(uuid.uuid4())
        test_db.execute(
            text("""
                INSERT INTO conversations (id, tenant_id, status)
                VALUES (:id, :tenant_id, 'open')
            """),
            {"id": conv2_id, "tenant_id": tenant2}
        )
        test_db.commit()
        
        # Query as tenant1
        test_db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant1})
        test_db.commit()
        
        conversations = test_db.execute(
            text("SELECT id FROM conversations")
        ).fetchall()
        
        assert len(conversations) == 1
        assert str(conversations[0].id) == conv1_id
    
    def test_event_logs_isolation(self, test_db, tenant1, tenant2):
        """Test that event logs are isolated."""
        # Create event logs for tenant1
        test_db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant1})
        test_db.commit()
        test_db.execute(
            text("""
                INSERT INTO event_logs (id, tenant_id, event_type, status)
                VALUES (gen_random_uuid(), :tenant_id, 'test_event', 'success')
            """),
            {"tenant_id": tenant1}
        )
        
        # Create event logs for tenant2
        test_db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant2})
        test_db.commit()
        test_db.execute(
            text("""
                INSERT INTO event_logs (id, tenant_id, event_type, status)
                VALUES (gen_random_uuid(), :tenant_id, 'test_event', 'success')
            """),
            {"tenant_id": tenant2}
        )
        test_db.commit()
        
        # Query as tenant1
        test_db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant1})
        test_db.commit()
        
        events = test_db.execute(
            text("SELECT COUNT(*) FROM event_logs")
        ).scalar()
        
        assert events == 1
    
    def test_cross_tenant_access_blocked(self, test_db, tenant1, tenant2):
        """Test that direct cross-tenant access is blocked by RLS."""
        # Create message for tenant1 (set tenant context for RLS)
        test_db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant1})
        test_db.commit()
        msg_id = str(uuid.uuid4())
        conv_id = str(uuid.uuid4())
        test_db.execute(
            text("""
                INSERT INTO conversations (id, tenant_id, status)
                VALUES (:id, :tenant_id, 'open')
            """),
            {"id": conv_id, "tenant_id": tenant1}
        )
        test_db.execute(
            text("""
                INSERT INTO messages (id, tenant_id, conversation_id, direction, from_type, content_text)
                VALUES (:id, :tenant_id, :conv_id, 'inbound', 'user', 'Secret message')
            """),
            {"id": msg_id, "tenant_id": tenant1, "conv_id": conv_id}
        )
        test_db.commit()
        
        # Try to access as tenant2
        test_db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant2})
        test_db.commit()
        
        # Should not be able to see tenant1's message
        messages = test_db.execute(
            text("SELECT id FROM messages WHERE id = :msg_id"),
            {"msg_id": msg_id}
        ).fetchall()
        
        assert len(messages) == 0  # RLS should block access

