"""Database session management with tenant isolation."""

from contextlib import contextmanager
from typing import Generator, Optional
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import QueuePool

from app.infra.config import config


# Create engine with connection pooling
engine = create_engine(
    config.DATABASE_URL,
    poolclass=QueuePool,
    pool_size=10,  # Number of connections to maintain
    max_overflow=20,  # Max connections beyond pool_size
    pool_timeout=30,  # Seconds to wait for connection from pool
    pool_recycle=3600,  # Recycle connections after 1 hour
    pool_pre_ping=True,  # Verify connections before using
    echo=config.DEBUG,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@contextmanager
def get_db_session(tenant_id: Optional[str] = None) -> Generator[Session, None, None]:
    """
    Get a database session with tenant isolation.
    
    Sets app.current_tenant_id for RLS enforcement.
    Must be called with tenant_id for tenant-scoped operations.
    """
    session = SessionLocal()
    try:
        if tenant_id:
            # Set tenant context for RLS
            session.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
            session.commit()  # Commit the SET statement
        
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Generator[Session, None, None]:
    """
    Dependency for FastAPI routes.
    Note: tenant_id should be set via middleware before using this.
    """
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()

