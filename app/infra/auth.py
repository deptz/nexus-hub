"""API authentication and authorization."""

import os
from typing import Optional
from fastapi import HTTPException, Security, Depends, status
from fastapi.security import APIKeyHeader, APIKeyQuery
from sqlalchemy.orm import Session
from sqlalchemy import text

# API key header
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
api_key_query = APIKeyQuery(name="api_key", auto_error=False)


async def verify_api_key(
    api_key: Optional[str] = Security(api_key_header),
    api_key_query_param: Optional[str] = Security(api_key_query),
    db: Session = Depends(lambda: None),
) -> str:
    """
    Verify API key and return tenant_id.
    
    Supports both header (X-API-Key) and query parameter (api_key).
    
    Args:
        api_key: API key from header
        api_key_query_param: API key from query parameter
        db: Database session (injected by FastAPI)
    
    Returns:
        tenant_id associated with the API key
    
    Raises:
        HTTPException: If API key is invalid or missing
    """
    # Get API key from header or query parameter
    key = api_key or api_key_query_param
    
    if not key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key required. Provide X-API-Key header or api_key query parameter.",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    
    # Look up API key in database
    # Note: In production, you'd have an api_keys table
    # For now, we'll check if it's a valid tenant_id or use a mapping
    if not db:
        from app.infra.database import get_db
        db_gen = get_db()
        db = next(db_gen)
        try:
            return await _verify_key_in_db(key, db)
        finally:
            db.close()
            try:
                next(db_gen, None)
            except:
                pass
    else:
        return await _verify_key_in_db(key, db)


async def _verify_key_in_db(api_key: str, db: Session) -> str:
    """Verify API key in database and return tenant_id."""
    # SECURITY: Never accept tenant_id as API key - this is a critical vulnerability
    # All API keys must be stored in a dedicated api_keys table with proper hashing
    
    # Validate API key format (should be a secure token, not a tenant_id)
    if not api_key or len(api_key) < 16:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key format",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    
    # Master key for admin operations (from env)
    # Master key bypasses the api_keys table for admin operations
    master_key = os.getenv("MASTER_API_KEY")
    if master_key and api_key == master_key:
        # Master key allows access but needs explicit tenant_id
        return "master"  # Special tenant_id for master key
    
    # Verify API key using the api_keys table
    try:
        from app.services.api_key_service import verify_and_get_tenant_id
        tenant_id = await verify_and_get_tenant_id(api_key, db)
        
        if tenant_id:
            return tenant_id
    except Exception as e:
        # If table doesn't exist yet, log and continue to error
        # In production, the table should exist
        import logging
        logger = logging.getLogger("app.auth")
        logger.warning(f"API key verification failed: {str(e)}")
    
    # SECURITY: Do NOT accept tenant_id as API key
    # This is a critical security vulnerability
    # Raise unauthorized instead
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid API key",
        headers={"WWW-Authenticate": "ApiKey"},
    )


def require_tenant_access(
    tenant_id: str,
    api_tenant_id: str,
) -> None:
    """
    Verify that the API key's tenant has access to the requested tenant_id.
    
    Args:
        tenant_id: Tenant ID from request
        api_tenant_id: Tenant ID from API key
    
    Raises:
        HTTPException: If access is denied
    """
    # Master key can access any tenant
    if api_tenant_id == "master":
        return
    
    # Otherwise, must match
    if api_tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: API key does not have access to this tenant",
        )

