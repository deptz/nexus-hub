"""Knowledge base sync service - orchestrates multi-provider document syncing."""

import logging
import uuid
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime

from app.infra.database import get_db_session
from app.services.vector_store_service import vector_store_service
from app.services.file_search_store_service import file_search_store_service
from app.services.tool_mapping_service import get_provider_from_tool_name

logger = logging.getLogger(__name__)


class KBSyncService:
    """Service for syncing documents across multiple providers."""
    
    async def ensure_provider_stores(
        self,
        tenant_id: str,
        kb_id: str,
        kb_name: str,
        enabled_providers: List[str],
        db: Session
    ) -> Dict[str, str]:
        """
        Ensure provider stores exist for a knowledge base.
        Creates stores if they don't exist.
        
        Args:
            tenant_id: Tenant ID
            kb_id: Knowledge base ID
            kb_name: Knowledge base name
            enabled_providers: List of provider names to enable
            db: Database session
        
        Returns:
            Dict mapping provider to store_id/store_name
        """
        store_ids = {}
        
        for provider in enabled_providers:
            try:
                # Check if sync record exists
                sync_record = db.execute(
                    text("""
                        SELECT id, store_id, sync_status
                        FROM kb_provider_sync
                        WHERE kb_id = :kb_id AND provider = :provider
                    """),
                    {"kb_id": kb_id, "provider": provider}
                ).fetchone()
                
                if sync_record and sync_record.store_id:
                    # Store already exists
                    store_ids[provider] = sync_record.store_id
                    continue
                
                # Create store based on provider
                if provider == "openai_file":
                    store_info = vector_store_service.create_vector_store(
                        name=f"{kb_name} - {tenant_id[:8]}",
                        tenant_id=tenant_id
                    )
                    store_id = store_info["vector_store_id"]
                    
                elif provider == "gemini_file":
                    store_info = file_search_store_service.create_file_search_store(
                        display_name=f"{kb_name} - {tenant_id[:8]}",
                        tenant_id=tenant_id
                    )
                    store_id = store_info["store_name"]
                    
                elif provider == "internal_rag":
                    # Internal RAG doesn't need a store - it uses our database
                    store_id = None
                else:
                    logger.warning(f"Unknown provider: {provider}")
                    continue
                
                # Create or update sync record
                if sync_record:
                    db.execute(
                        text("""
                            UPDATE kb_provider_sync
                            SET store_id = :store_id,
                                sync_status = 'enabled',
                                is_active = TRUE,
                                updated_at = now()
                            WHERE id = :id
                        """),
                        {"id": sync_record.id, "store_id": store_id}
                    )
                else:
                    sync_id = uuid.uuid4()
                    db.execute(
                        text("""
                            INSERT INTO kb_provider_sync (
                                id, kb_id, provider, is_active, sync_status, store_id
                            ) VALUES (
                                :id, :kb_id, :provider, TRUE, 'enabled', :store_id
                            )
                        """),
                        {
                            "id": sync_id,
                            "kb_id": kb_id,
                            "provider": provider,
                            "store_id": store_id,
                        }
                    )
                
                db.commit()
                store_ids[provider] = store_id
                logger.info(f"Created store for provider {provider}: {store_id}")
                
            except Exception as e:
                logger.error(f"Error ensuring store for provider {provider}: {e}", exc_info=True)
                # Update sync record with error
                if sync_record:
                    db.execute(
                        text("""
                            UPDATE kb_provider_sync
                            SET sync_status = 'error',
                                error_message = :error_message,
                                updated_at = now()
                            WHERE id = :id
                        """),
                        {"id": sync_record.id, "error_message": str(e)}
                    )
                else:
                    sync_id = uuid.uuid4()
                    db.execute(
                        text("""
                            INSERT INTO kb_provider_sync (
                                id, kb_id, provider, is_active, sync_status, error_message
                            ) VALUES (
                                :id, :kb_id, :provider, FALSE, 'error', :error_message
                            )
                        """),
                        {
                            "id": sync_id,
                            "kb_id": kb_id,
                            "provider": provider,
                            "error_message": str(e),
                        }
                    )
                db.commit()
        
        return store_ids
    
    async def sync_document_to_providers(
        self,
        tenant_id: str,
        kb_id: str,
        kb_name: str,
        document_id: str,
        content: str,
        title: Optional[str] = None,
        db: Optional[Session] = None
    ) -> Dict[str, Any]:
        """
        Sync a document to all active providers.
        
        Args:
            tenant_id: Tenant ID
            kb_id: Knowledge base ID
            kb_name: Knowledge base name
            document_id: Document ID
            content: Document content
            title: Document title (optional)
            db: Database session (optional, will create if not provided)
        
        Returns:
            Dict with sync results per provider
        """
        if db is None:
            with get_db_session(tenant_id) as session:
                return await self._sync_document_impl(
                    tenant_id, kb_id, kb_name, document_id, content, title, session
                )
        else:
            return await self._sync_document_impl(
                tenant_id, kb_id, kb_name, document_id, content, title, db
            )
    
    async def _sync_document_impl(
        self,
        tenant_id: str,
        kb_id: str,
        kb_name: str,
        document_id: str,
        content: str,
        title: Optional[str],
        db: Session
    ) -> Dict[str, Any]:
        """Internal implementation of document sync."""
        results = {}
        
        # Get active providers for this KB
        active_providers = db.execute(
            text("""
                SELECT provider, store_id, sync_status
                FROM kb_provider_sync
                WHERE kb_id = :kb_id AND is_active = TRUE AND sync_status = 'enabled'
            """),
            {"kb_id": kb_id}
        ).fetchall()
        
        for provider_row in active_providers:
            provider = provider_row.provider
            store_id = provider_row.store_id
            
            if not store_id:
                continue
            
            try:
                # Convert content to bytes
                content_bytes = content.encode('utf-8')
                filename = f"{title or document_id}.txt"
                
                if provider == "openai_file":
                    file_info = await vector_store_service.upload_file_from_content(
                        vector_store_id=store_id,
                        content=content_bytes,
                        filename=filename
                    )
                    results[provider] = {
                        "status": "success",
                        "file_id": file_info.get("file_id"),
                    }
                    
                elif provider == "gemini_file":
                    file_info = await file_search_store_service.upload_file_from_content(
                        store_name=store_id,
                        content=content_bytes,
                        filename=filename
                    )
                    results[provider] = {
                        "status": "success",
                        "file_name": file_info.get("file_name"),
                    }
                    
                elif provider == "internal_rag":
                    # Internal RAG is already stored in our database
                    results[provider] = {
                        "status": "success",
                        "note": "Already stored in internal_rag database",
                    }
                
                # Update last_sync_at
                db.execute(
                    text("""
                        UPDATE kb_provider_sync
                        SET last_sync_at = now(),
                            error_message = NULL,
                            updated_at = now()
                        WHERE kb_id = :kb_id AND provider = :provider
                    """),
                    {"kb_id": kb_id, "provider": provider}
                )
                db.commit()
                
            except Exception as e:
                logger.error(f"Error syncing document to {provider}: {e}", exc_info=True)
                results[provider] = {
                    "status": "error",
                    "error": str(e),
                }
                
                # Update sync record with error
                db.execute(
                    text("""
                        UPDATE kb_provider_sync
                        SET sync_status = 'error',
                            error_message = :error_message,
                            updated_at = now()
                        WHERE kb_id = :kb_id AND provider = :provider
                    """),
                    {
                        "kb_id": kb_id,
                        "provider": provider,
                        "error_message": str(e),
                    }
                )
                db.commit()
        
        return results
    
    async def sync_all_documents(
        self,
        tenant_id: str,
        kb_id: str,
        providers: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Sync all documents in a knowledge base to specified providers.
        
        Args:
            tenant_id: Tenant ID
            kb_id: Knowledge base ID
            providers: Optional list of providers to sync. If None, syncs all active providers.
        
        Returns:
            Dict with sync results
        """
        with get_db_session(tenant_id) as db:
            # Get KB info
            kb = db.execute(
                text("""
                    SELECT id, tenant_id, name
                    FROM knowledge_bases
                    WHERE id = :kb_id AND tenant_id = :tenant_id
                """),
                {"kb_id": kb_id, "tenant_id": tenant_id}
            ).fetchone()
            
            if not kb:
                raise ValueError(f"Knowledge base {kb_id} not found")
            
            kb_name = kb.name
            
            # Get documents
            documents = db.execute(
                text("""
                    SELECT id, title, content
                    FROM rag_documents
                    WHERE tenant_id = :tenant_id
                      AND kb_name = :kb_name
                """),
                {"tenant_id": tenant_id, "kb_name": kb_name}
            ).fetchall()
            
            # Get providers to sync
            if providers:
                provider_filter = "AND provider = ANY(:providers)"
                params = {"kb_id": kb_id, "providers": providers}
            else:
                provider_filter = ""
                params = {"kb_id": kb_id}
            
            active_providers = db.execute(
                text(f"""
                    SELECT provider
                    FROM kb_provider_sync
                    WHERE kb_id = :kb_id AND is_active = TRUE AND sync_status = 'enabled'
                    {provider_filter}
                """),
                params
            ).fetchall()
            
            provider_list = [p.provider for p in active_providers]
            
            # Sync each document
            total_docs = len(documents)
            synced_docs = 0
            failed_docs = 0
            results = {}
            
            for doc in documents:
                try:
                    doc_results = await self.sync_document_to_providers(
                        tenant_id=tenant_id,
                        kb_id=kb_id,
                        kb_name=kb_name,
                        document_id=str(doc.id),
                        content=doc.content,
                        title=doc.title,
                        db=db
                    )
                    
                    # Aggregate results
                    for provider, result in doc_results.items():
                        if provider not in results:
                            results[provider] = {"success": 0, "failed": 0}
                        
                        if result.get("status") == "success":
                            results[provider]["success"] += 1
                            synced_docs += 1
                        else:
                            results[provider]["failed"] += 1
                            failed_docs += 1
                            
                except Exception as e:
                    logger.error(f"Error syncing document {doc.id}: {e}", exc_info=True)
                    failed_docs += 1
            
            return {
                "status": "completed",
                "results": results,
                "total_documents": total_docs,
                "synced_documents": synced_docs,
                "failed_documents": failed_docs,
            }


# Global instance
kb_sync_service = KBSyncService()

