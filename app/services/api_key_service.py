"""API key management service with secure key generation and hashing."""

import secrets
import bcrypt
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.infra.database import get_db_session


def generate_api_key() -> str:
    """
    Generate a secure random API key.
    
    Returns:
        A secure random API key string (64 characters, URL-safe)
    """
    # Generate 48 bytes (384 bits) of random data
    # Encode as base64 URL-safe string (64 characters)
    return secrets.token_urlsafe(48)


def hash_api_key(api_key: str) -> str:
    """
    Hash an API key using bcrypt.
    
    Args:
        api_key: Plain text API key
    
    Returns:
        Bcrypt hashed key
    """
    # Generate salt and hash the key
    # Use bcrypt with cost factor 12 (good balance of security and performance)
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(api_key.encode('utf-8'), salt)
    return hashed.decode('utf-8')


def verify_api_key(api_key: str, key_hash: str) -> bool:
    """
    Verify an API key against its hash.
    
    Args:
        api_key: Plain text API key to verify
        key_hash: Bcrypt hash to verify against
    
    Returns:
        True if key matches hash, False otherwise
    """
    try:
        return bcrypt.checkpw(
            api_key.encode('utf-8'),
            key_hash.encode('utf-8')
        )
    except Exception:
        return False


def get_key_prefix(api_key: str) -> str:
    """
    Get the prefix of an API key for identification.
    
    Args:
        api_key: Full API key
    
    Returns:
        First 8 characters of the key (for display/identification)
    """
    return api_key[:8] if len(api_key) >= 8 else api_key


async def create_api_key(
    tenant_id: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
    expires_in_days: Optional[int] = None,
    rate_limit_per_minute: int = 100,
    created_by: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Create a new API key for a tenant.
    
    Args:
        tenant_id: Tenant ID
        name: Optional human-readable name
        description: Optional description
        expires_in_days: Optional expiration in days (None = no expiration)
        rate_limit_per_minute: Rate limit for this key
        created_by: User/system that created the key
        metadata: Additional metadata
    
    Returns:
        Dict with:
            - api_key: The plain text key (only shown once!)
            - key_id: The key ID
            - key_prefix: First 8 characters for identification
            - expires_at: Expiration timestamp (if set)
    """
    # Generate new API key
    api_key = generate_api_key()
    key_hash = hash_api_key(api_key)
    key_prefix = get_key_prefix(api_key)
    
    # Calculate expiration
    expires_at = None
    if expires_in_days:
        expires_at = datetime.utcnow() + timedelta(days=expires_in_days)
    
    # Store in database
    import json
    with get_db_session(tenant_id) as session:
        result = session.execute(
            text("""
                INSERT INTO api_keys (
                    tenant_id, key_hash, key_prefix, name, description,
                    is_active, rate_limit_per_minute, expires_at,
                    created_by, metadata
                ) VALUES (
                    :tenant_id, :key_hash, :key_prefix, :name, :description,
                    TRUE, :rate_limit_per_minute, :expires_at,
                    :created_by, CAST(:metadata AS jsonb)
                )
                RETURNING id, created_at
            """),
            {
                "tenant_id": tenant_id,
                "key_hash": key_hash,
                "key_prefix": key_prefix,
                "name": name,
                "description": description,
                "rate_limit_per_minute": rate_limit_per_minute,
                "expires_at": expires_at,
                "created_by": created_by,
                "metadata": json.dumps(metadata or {}),
            }
        )
        row = result.fetchone()
        key_id = str(row.id)
        created_at = row.created_at
    
    return {
        "api_key": api_key,  # Only shown once - caller should store this securely
        "key_id": key_id,
        "key_prefix": key_prefix,
        "name": name,
        "description": description,
        "expires_at": expires_at.isoformat() if expires_at else None,
        "created_at": created_at.isoformat(),
        "rate_limit_per_minute": rate_limit_per_minute,
    }


async def list_api_keys(
    tenant_id: str,
    include_inactive: bool = False,
) -> List[Dict[str, Any]]:
    """
    List all API keys for a tenant.
    
    Args:
        tenant_id: Tenant ID
        include_inactive: Whether to include inactive keys
    
    Returns:
        List of API key info (without the actual keys)
    """
    with get_db_session(tenant_id) as session:
        if include_inactive:
            rows = session.execute(
                text("""
                    SELECT 
                        id, key_prefix, name, description, is_active,
                        rate_limit_per_minute, created_at, expires_at,
                        last_used_at, created_by, metadata
                    FROM api_keys
                    WHERE tenant_id = :tenant_id
                    ORDER BY created_at DESC
                """),
                {"tenant_id": tenant_id}
            ).fetchall()
        else:
            rows = session.execute(
                text("""
                    SELECT 
                        id, key_prefix, name, description, is_active,
                        rate_limit_per_minute, created_at, expires_at,
                        last_used_at, created_by, metadata
                    FROM api_keys
                    WHERE tenant_id = :tenant_id
                      AND is_active = TRUE
                      AND (expires_at IS NULL OR expires_at > NOW())
                    ORDER BY created_at DESC
                """),
                {"tenant_id": tenant_id}
            ).fetchall()
        
        keys = []
        for row in rows:
            keys.append({
                "key_id": str(row.id),
                "key_prefix": row.key_prefix,
                "name": row.name,
                "description": row.description,
                "is_active": row.is_active,
                "rate_limit_per_minute": row.rate_limit_per_minute,
                "created_at": row.created_at.isoformat(),
                "expires_at": row.expires_at.isoformat() if row.expires_at else None,
                "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
                "created_by": row.created_by,
                "metadata": row.metadata or {},
            })
        
        return keys


async def revoke_api_key(tenant_id: str, key_id: str) -> bool:
    """
    Revoke (deactivate) an API key.
    
    Args:
        tenant_id: Tenant ID
        key_id: API key ID to revoke
    
    Returns:
        True if key was revoked, False if not found
    """
    with get_db_session(tenant_id) as session:
        result = session.execute(
            text("""
                UPDATE api_keys
                SET is_active = FALSE
                WHERE id = :key_id
                  AND tenant_id = :tenant_id
                RETURNING id
            """),
            {
                "key_id": key_id,
                "tenant_id": tenant_id,
            }
        )
        row = result.fetchone()
        session.commit()
        
        return row is not None


async def delete_api_key(tenant_id: str, key_id: str) -> bool:
    """
    Permanently delete an API key.
    
    Args:
        tenant_id: Tenant ID
        key_id: API key ID to delete
    
    Returns:
        True if key was deleted, False if not found
    """
    with get_db_session(tenant_id) as session:
        result = session.execute(
            text("""
                DELETE FROM api_keys
                WHERE id = :key_id
                  AND tenant_id = :tenant_id
                RETURNING id
            """),
            {
                "key_id": key_id,
                "tenant_id": tenant_id,
            }
        )
        row = result.fetchone()
        session.commit()
        
        return row is not None


async def verify_and_get_tenant_id(api_key: str, db: Session) -> Optional[str]:
    """
    Verify an API key and return the associated tenant_id.
    
    This function is used by the authentication middleware.
    
    Args:
        api_key: Plain text API key to verify
        db: Database session
    
    Returns:
        Tenant ID if key is valid, None otherwise
    """
    # Get key prefix for efficient lookup
    key_prefix = get_key_prefix(api_key)
    
    # Look up keys with matching prefix (bcrypt hashes are slow, so we filter by prefix first)
    rows = db.execute(
        text("""
            SELECT id, tenant_id, key_hash, is_active, expires_at
            FROM api_keys
            WHERE key_prefix = :key_prefix
              AND is_active = TRUE
              AND (expires_at IS NULL OR expires_at > NOW())
        """),
        {"key_prefix": key_prefix}
    ).fetchall()
    
    # Verify against each matching key (should be very few due to prefix)
    for row in rows:
        if verify_api_key(api_key, row.key_hash):
            # Update last_used_at
            db.execute(
                text("""
                    UPDATE api_keys
                    SET last_used_at = NOW()
                    WHERE id = :key_id
                """),
                {"key_id": row.id}
            )
            db.commit()
            
            return str(row.tenant_id)
    
    return None


async def update_api_key_usage(tenant_id: str, key_id: str) -> None:
    """
    Update the last_used_at timestamp for an API key.
    
    Args:
        tenant_id: Tenant ID
        key_id: API key ID
    """
    with get_db_session(tenant_id) as session:
        session.execute(
            text("""
                UPDATE api_keys
                SET last_used_at = NOW()
                WHERE id = :key_id
                  AND tenant_id = :tenant_id
            """),
            {
                "key_id": key_id,
                "tenant_id": tenant_id,
            }
        )
        session.commit()

