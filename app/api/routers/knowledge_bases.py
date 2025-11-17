"""Knowledge Bases API router."""

import json
import uuid
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Security, Query
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.infra.database import get_db
from app.infra.auth import verify_api_key, require_tenant_access
from app.infra.validation import validate_tenant_id
from app.api.models import (
    CreateKnowledgeBaseRequest,
    UpdateKnowledgeBaseRequest,
    KnowledgeBaseResponse,
    KnowledgeBasesListResponse,
    ProviderSyncStatus,
    SyncKnowledgeBaseRequest,
    SyncStatusResponse,
)
from app.services.kb_sync_service import kb_sync_service
from app.services.tool_mapping_service import get_provider_tools_for_abstract
from app.services.vector_store_service import vector_store_service
from app.services.file_search_store_service import file_search_store_service

router = APIRouter()
import logging

logger = logging.getLogger(__name__)


async def _get_kb_with_sync_status(db: Session, kb_id: uuid.UUID, tenant_id: str) -> KnowledgeBaseResponse:
    """Helper to get KB with sync status."""
    # Get KB
    row = db.execute(
        text("""
            SELECT id, tenant_id, name, description, provider, provider_config, is_active, created_at, updated_at
            FROM knowledge_bases
            WHERE id = :kb_id AND tenant_id = :tenant_id
        """),
        {"kb_id": kb_id, "tenant_id": tenant_id}
    ).fetchone()
    
    if not row:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    
    # Get sync status
    sync_rows = db.execute(
        text("""
            SELECT provider, is_active, sync_status, store_id, last_sync_at, error_message
            FROM kb_provider_sync
            WHERE kb_id = :kb_id
            ORDER BY provider
        """),
        {"kb_id": kb_id}
    ).fetchall()
    
    provider_sync_status = [
        ProviderSyncStatus(
            provider=row.provider,
            is_active=row.is_active,
            sync_status=row.sync_status,
            store_id=row.store_id,
            last_sync_at=row.last_sync_at.isoformat() if row.last_sync_at else None,
            error_message=row.error_message,
        )
        for row in sync_rows
    ]
    
    return KnowledgeBaseResponse(
        id=str(row.id),
        tenant_id=str(row.tenant_id),
        name=row.name,
        description=row.description,
        provider=row.provider,
        provider_config=row.provider_config,
        is_active=row.is_active,
        provider_sync_status=provider_sync_status,
        created_at=row.created_at.isoformat(),
        updated_at=row.updated_at.isoformat(),
    )


@router.post("/tenants/{tenant_id}/knowledge-bases", tags=["Knowledge Bases"], response_model=KnowledgeBaseResponse)
async def create_knowledge_base(
    tenant_id: str,
    request: CreateKnowledgeBaseRequest,
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """
    Create a new knowledge base for a tenant.
    
    Requires API key authentication. Automatically syncs to all enabled providers.
    No need to specify provider or provider_config - system auto-detects enabled tools.
    
    **Example Request:**
    ```json
    {
        "name": "support_faq",
        "description": "Support FAQ knowledge base"
    }
    ```
    """
    # SECURITY: Validate tenant_id format
    try:
        validate_tenant_id(tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    # Verify tenant access
    require_tenant_access(tenant_id, api_tenant_id)
    
    # Set tenant context for DB operations
    db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
    db.commit()
    
    # Check if name already exists
    existing = db.execute(
        text("""
            SELECT id FROM knowledge_bases
            WHERE tenant_id = :tenant_id AND name = :name
        """),
        {"tenant_id": tenant_id, "name": request.name}
    ).fetchone()
    
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Knowledge base with name '{request.name}' already exists for this tenant"
        )
    
    # Check if file_search tool is enabled for tenant
    file_search_enabled = db.execute(
        text("""
            SELECT ttp.is_enabled
            FROM tenant_tool_policies ttp
            JOIN tools t ON ttp.tool_id = t.id
            WHERE ttp.tenant_id = :tenant_id
              AND t.name = 'file_search'
              AND ttp.is_enabled = TRUE
        """),
        {"tenant_id": tenant_id}
    ).fetchone()
    
    if not file_search_enabled:
        raise HTTPException(
            status_code=400,
            detail="file_search tool must be enabled for this tenant. Please enable it first using /tenants/{tenant_id}/tools endpoint."
        )
    
    # Determine which providers to enable
    # If providers specified, use those; otherwise use all available from file_search
    if request.providers:
        enabled_providers = request.providers
    else:
        # Get provider tools for file_search
        provider_tools = get_provider_tools_for_abstract("file_search")
        # Map tool names to provider names
        from app.services.tool_mapping_service import get_provider_from_tool_name
        enabled_providers = []
        for tool_name in provider_tools:
            provider = get_provider_from_tool_name(tool_name)
            if provider:
                enabled_providers.append(provider)
        # Always include internal_rag
        if "internal_rag" not in enabled_providers:
            enabled_providers.append("internal_rag")
    
    # Create knowledge base with default provider (for backward compatibility)
    kb_id = uuid.uuid4()
    default_provider = "internal_rag"  # Default to internal_rag
    db.execute(
        text("""
            INSERT INTO knowledge_bases (
                id, tenant_id, name, description, provider, provider_config, is_active
            ) VALUES (
                :id, :tenant_id, :name, :description, :provider, '{}'::jsonb, TRUE
            )
        """),
        {
            "id": kb_id,
            "tenant_id": tenant_id,
            "name": request.name,
            "description": request.description,
            "provider": default_provider,
        }
    )
    db.commit()
    
    # Create provider stores and sync records
    try:
        store_ids = await kb_sync_service.ensure_provider_stores(
            tenant_id=tenant_id,
            kb_id=str(kb_id),
            kb_name=request.name,
            enabled_providers=enabled_providers,
            db=db
        )
    except Exception as e:
        # If store creation fails, still return KB but with error status
        logger.error(f"Error creating provider stores: {e}", exc_info=True)
    
    # Fetch created KB with sync status
    return await _get_kb_with_sync_status(db, kb_id, tenant_id)


@router.get("/tenants/{tenant_id}/knowledge-bases", tags=["Knowledge Bases"], response_model=KnowledgeBasesListResponse)
async def list_knowledge_bases(
    tenant_id: str,
    provider: Optional[str] = Query(None, description="Filter by provider"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """
    List all knowledge bases for a tenant.
    
    Requires API key authentication. Supports optional filtering by provider and active status.
    """
    # SECURITY: Validate tenant_id format
    try:
        validate_tenant_id(tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    # Verify tenant access
    require_tenant_access(tenant_id, api_tenant_id)
    
    # Set tenant context for DB operations
    db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
    db.commit()
    
    # Build query
    query = """
        SELECT id, tenant_id, name, description, provider, provider_config, is_active, created_at, updated_at
        FROM knowledge_bases
        WHERE tenant_id = :tenant_id
    """
    params = {"tenant_id": tenant_id}
    
    if provider:
        query += " AND provider = :provider"
        params["provider"] = provider
    
    if is_active is not None:
        query += " AND is_active = :is_active"
        params["is_active"] = is_active
    
    query += " ORDER BY created_at DESC"
    
    rows = db.execute(text(query), params).fetchall()
    
    items = []
    for row in rows:
        # Get sync status for each KB
        sync_rows = db.execute(
            text("""
                SELECT provider, is_active, sync_status, store_id, last_sync_at, error_message
                FROM kb_provider_sync
                WHERE kb_id = :kb_id
                ORDER BY provider
            """),
            {"kb_id": row.id}
        ).fetchall()
        
        provider_sync_status = [
            ProviderSyncStatus(
                provider=sync_row.provider,
                is_active=sync_row.is_active,
                sync_status=sync_row.sync_status,
                store_id=sync_row.store_id,
                last_sync_at=sync_row.last_sync_at.isoformat() if sync_row.last_sync_at else None,
                error_message=sync_row.error_message,
            )
            for sync_row in sync_rows
        ]
        
        items.append(
            KnowledgeBaseResponse(
                id=str(row.id),
                tenant_id=str(row.tenant_id),
                name=row.name,
                description=row.description,
                provider=row.provider,
                provider_config=row.provider_config,
                is_active=row.is_active,
                provider_sync_status=provider_sync_status,
                created_at=row.created_at.isoformat(),
                updated_at=row.updated_at.isoformat(),
            )
        )
    
    return KnowledgeBasesListResponse(items=items, count=len(items))


@router.get("/tenants/{tenant_id}/knowledge-bases/{kb_id}", tags=["Knowledge Bases"], response_model=KnowledgeBaseResponse)
async def get_knowledge_base(
    tenant_id: str,
    kb_id: str,
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """
    Get knowledge base details by ID.
    
    Requires API key authentication. Returns 404 if not found.
    """
    # SECURITY: Validate tenant_id format
    try:
        validate_tenant_id(tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    # Verify tenant access
    require_tenant_access(tenant_id, api_tenant_id)
    
    # Set tenant context for DB operations
    db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
    db.commit()
    
    return await _get_kb_with_sync_status(db, uuid.UUID(kb_id), tenant_id)


@router.put("/tenants/{tenant_id}/knowledge-bases/{kb_id}", tags=["Knowledge Bases"], response_model=KnowledgeBaseResponse)
async def update_knowledge_base(
    tenant_id: str,
    kb_id: str,
    request: UpdateKnowledgeBaseRequest,
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """
    Update knowledge base configuration.
    
    Requires API key authentication. Only provided fields will be updated.
    """
    # SECURITY: Validate tenant_id format
    try:
        validate_tenant_id(tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    # Verify tenant access
    require_tenant_access(tenant_id, api_tenant_id)
    
    # Set tenant context for DB operations
    db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
    db.commit()
    
    # Check if KB exists
    existing = db.execute(
        text("""
            SELECT id, provider FROM knowledge_bases
            WHERE id = :kb_id AND tenant_id = :tenant_id
        """),
        {"kb_id": kb_id, "tenant_id": tenant_id}
    ).fetchone()
    
    if not existing:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    
    # Build update query
    updates = []
    params = {"kb_id": kb_id, "tenant_id": tenant_id}
    
    if request.description is not None:
        updates.append("description = :description")
        params["description"] = request.description
    
    if request.provider_config is not None:
        updates.append("provider_config = CAST(:provider_config AS jsonb)")
        params["provider_config"] = json.dumps(request.provider_config)
    
    if request.is_active is not None:
        updates.append("is_active = :is_active")
        params["is_active"] = request.is_active
    
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    
    updates.append("updated_at = now()")
    
    db.execute(
        text(f"""
            UPDATE knowledge_bases
            SET {', '.join(updates)}
            WHERE id = :kb_id AND tenant_id = :tenant_id
        """),
        params
    )
    db.commit()
    
    # Fetch updated KB
    row = db.execute(
        text("""
            SELECT id, tenant_id, name, description, provider, provider_config, is_active, created_at, updated_at
            FROM knowledge_bases
            WHERE id = :kb_id
        """),
        {"kb_id": kb_id}
    ).fetchone()
    
    return KnowledgeBaseResponse(
        id=str(row.id),
        tenant_id=str(row.tenant_id),
        name=row.name,
        description=row.description,
        provider=row.provider,
        provider_config=row.provider_config,
        is_active=row.is_active,
        created_at=row.created_at.isoformat(),
        updated_at=row.updated_at.isoformat(),
    )


@router.delete("/tenants/{tenant_id}/knowledge-bases/{kb_id}", tags=["Knowledge Bases"])
async def delete_knowledge_base(
    tenant_id: str,
    kb_id: str,
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """
    Delete or deactivate a knowledge base.
    
    Requires API key authentication. Permanently deletes the knowledge base.
    """
    # SECURITY: Validate tenant_id format
    try:
        validate_tenant_id(tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    # Verify tenant access
    require_tenant_access(tenant_id, api_tenant_id)
    
    # Set tenant context for DB operations
    db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
    db.commit()
    
    result = db.execute(
        text("""
            DELETE FROM knowledge_bases
            WHERE id = :kb_id AND tenant_id = :tenant_id
        """),
        {"kb_id": kb_id, "tenant_id": tenant_id}
    )
    db.commit()
    
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    
    return {
        "status": "deleted",
        "message": "Knowledge base deleted successfully"
    }


@router.post("/tenants/{tenant_id}/knowledge-bases/{kb_id}/sync", tags=["Knowledge Bases"], response_model=SyncStatusResponse)
async def sync_knowledge_base(
    tenant_id: str,
    kb_id: str,
    provider: Optional[str] = Query(None, description="Optional provider to sync. If not specified, syncs all providers."),
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """
    Manually sync all documents in a knowledge base to specified provider(s).
    
    Requires API key authentication. Syncs all documents to the specified provider,
    or all active providers if no provider is specified.
    """
    # SECURITY: Validate tenant_id format
    try:
        validate_tenant_id(tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    # Verify tenant access
    require_tenant_access(tenant_id, api_tenant_id)
    
    # Set tenant context for DB operations
    db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
    db.commit()
    
    # Verify KB exists
    kb = db.execute(
        text("""
            SELECT id FROM knowledge_bases
            WHERE id = :kb_id AND tenant_id = :tenant_id
        """),
        {"kb_id": kb_id, "tenant_id": tenant_id}
    ).fetchone()
    
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    
    # Sync documents
    providers_list = [provider] if provider else None
    result = await kb_sync_service.sync_all_documents(
        tenant_id=tenant_id,
        kb_id=kb_id,
        providers=providers_list
    )
    
    return SyncStatusResponse(
        status=result["status"],
        results=result["results"],
        total_documents=result["total_documents"],
        synced_documents=result["synced_documents"],
        failed_documents=result["failed_documents"],
    )


@router.get("/tenants/{tenant_id}/knowledge-bases/{kb_id}/sync-status", tags=["Knowledge Bases"])
async def get_sync_status(
    tenant_id: str,
    kb_id: str,
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """
    Get sync status for all providers in a knowledge base.
    
    Requires API key authentication. Returns sync status per provider.
    """
    # SECURITY: Validate tenant_id format
    try:
        validate_tenant_id(tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    # Verify tenant access
    require_tenant_access(tenant_id, api_tenant_id)
    
    # Set tenant context for DB operations
    db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
    db.commit()
    
    # Verify KB exists
    kb = db.execute(
        text("""
            SELECT id FROM knowledge_bases
            WHERE id = :kb_id AND tenant_id = :tenant_id
        """),
        {"kb_id": kb_id, "tenant_id": tenant_id}
    ).fetchone()
    
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    
    # Get sync status
    sync_rows = db.execute(
        text("""
            SELECT provider, is_active, sync_status, store_id, last_sync_at, error_message
            FROM kb_provider_sync
            WHERE kb_id = :kb_id
            ORDER BY provider
        """),
        {"kb_id": kb_id}
    ).fetchall()
    
    return {
        "kb_id": kb_id,
        "providers": [
            {
                "provider": row.provider,
                "is_active": row.is_active,
                "sync_status": row.sync_status,
                "store_id": row.store_id,
                "last_sync_at": row.last_sync_at.isoformat() if row.last_sync_at else None,
                "error_message": row.error_message,
            }
            for row in sync_rows
        ]
    }


@router.delete("/tenants/{tenant_id}/knowledge-bases/{kb_id}/providers/{provider}", tags=["Knowledge Bases"])
async def disable_provider(
    tenant_id: str,
    kb_id: str,
    provider: str,
    delete_data: bool = Query(False, description="If true, delete data from provider store"),
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """
    Disable a provider for a knowledge base and optionally cleanup data.
    
    Requires API key authentication. Soft disables the provider (keeps data unless delete_data=true).
    """
    # SECURITY: Validate tenant_id format
    try:
        validate_tenant_id(tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    # Verify tenant access
    require_tenant_access(tenant_id, api_tenant_id)
    
    # Set tenant context for DB operations
    db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
    db.commit()
    
    # Verify KB exists
    kb = db.execute(
        text("""
            SELECT id FROM knowledge_bases
            WHERE id = :kb_id AND tenant_id = :tenant_id
        """),
        {"kb_id": kb_id, "tenant_id": tenant_id}
    ).fetchone()
    
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    
    # Get sync record
    sync_record = db.execute(
        text("""
            SELECT id, store_id FROM kb_provider_sync
            WHERE kb_id = :kb_id AND provider = :provider
        """),
        {"kb_id": kb_id, "provider": provider}
    ).fetchone()
    
    if not sync_record:
        raise HTTPException(status_code=404, detail=f"Provider {provider} not found for this knowledge base")
    
    # If delete_data is true, delete from provider
    if delete_data and sync_record.store_id:
        try:
            if provider == "openai_file":
                vector_store_service.delete_vector_store(sync_record.store_id)
            elif provider == "gemini_file":
                file_search_store_service.delete_file_search_store(sync_record.store_id)
        except Exception as e:
            logger.error(f"Error deleting provider store: {e}", exc_info=True)
            # Continue with disable even if delete fails
    
    # Update sync record
    if delete_data:
        # Delete the sync record
        db.execute(
            text("""
                DELETE FROM kb_provider_sync
                WHERE id = :id
            """),
            {"id": sync_record.id}
        )
    else:
        # Soft disable
        db.execute(
            text("""
                UPDATE kb_provider_sync
                SET is_active = FALSE,
                    sync_status = 'disabled',
                    updated_at = now()
                WHERE id = :id
            """),
            {"id": sync_record.id}
        )
    
    db.commit()
    
    return {
        "status": "disabled" if not delete_data else "deleted",
        "message": f"Provider {provider} {'deleted' if delete_data else 'disabled'} successfully"
    }
