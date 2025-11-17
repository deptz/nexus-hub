"""RAG Documents API router."""

import json
import uuid
import numpy as np
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Depends, Security, Query
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.infra.database import get_db
from app.infra.auth import verify_api_key, require_tenant_access
from app.infra.validation import validate_tenant_id
from app.infra.embeddings import embedding_generator
from app.services.kb_sync_service import kb_sync_service
import logging

logger = logging.getLogger(__name__)
from app.api.models import (
    CreateRAGDocumentRequest, UpdateRAGDocumentRequest,
    RAGDocumentResponse, RAGDocumentListResponse,
    RAGChunkResponse, RAGChunkListResponse
)

router = APIRouter()


def chunk_text(text: str, chunk_size: int = 1000, chunk_overlap: int = 200) -> List[str]:
    """
    Split text into chunks with overlap.
    
    Args:
        text: Text to chunk
        chunk_size: Maximum characters per chunk
        chunk_overlap: Characters to overlap between chunks
    
    Returns:
        List of text chunks
    """
    if len(text) <= chunk_size:
        return [text]
    
    chunks = []
    start = 0
    
    while start < len(text):
        end = start + chunk_size
        
        # Try to break at paragraph or sentence boundary
        if end < len(text):
            # Look for paragraph break first
            para_break = text.rfind('\n\n', start, end)
            if para_break > start:
                end = para_break + 2
            else:
                # Look for sentence break
                sentence_break = max(
                    text.rfind('. ', start, end),
                    text.rfind('! ', start, end),
                    text.rfind('? ', start, end)
                )
                if sentence_break > start:
                    end = sentence_break + 2
        
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        
        # Move start position with overlap
        start = end - chunk_overlap
        if start >= len(text):
            break
    
    return chunks


@router.get("/tenants/{tenant_id}/rag/documents", tags=["Knowledge Bases"], response_model=RAGDocumentListResponse)
async def list_rag_documents(
    tenant_id: str,
    kb_name: Optional[str] = Query(None, description="Filter by knowledge base name"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """
    List RAG documents for a tenant.
    
    Requires API key authentication. Returns all RAG documents for the tenant,
    optionally filtered by knowledge base name.
    """
    try:
        validate_tenant_id(tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    require_tenant_access(tenant_id, api_tenant_id)
    
    db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
    db.commit()
    
    query = """
        SELECT id, tenant_id, kb_name, external_id, title, content, metadata, created_at, updated_at
        FROM rag_documents
        WHERE tenant_id = :tenant_id
    """
    params = {"tenant_id": tenant_id}
    
    if kb_name:
        query += " AND kb_name = :kb_name"
        params["kb_name"] = kb_name
    
    query += " ORDER BY created_at DESC"
    query += " LIMIT :limit OFFSET :offset"
    params["limit"] = limit + 1
    params["offset"] = offset
    
    rows = db.execute(text(query), params).fetchall()
    
    has_more = len(rows) > limit
    if has_more:
        rows = rows[:limit]
    
    items = [
        RAGDocumentResponse(
            id=str(row.id),
            tenant_id=str(row.tenant_id),
            kb_name=row.kb_name,
            external_id=row.external_id,
            title=row.title,
            content=row.content,
            metadata=row.metadata or {},
            created_at=row.created_at.isoformat(),
            updated_at=row.updated_at.isoformat(),
        )
        for row in rows
    ]
    
    return RAGDocumentListResponse(
        items=items,
        count=len(items),
        has_more=has_more,
        next_offset=offset + limit if has_more else None,
    )


@router.get("/tenants/{tenant_id}/rag/documents/{doc_id}", tags=["Knowledge Bases"], response_model=RAGDocumentResponse)
async def get_rag_document(
    tenant_id: str,
    doc_id: str,
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """
    Get RAG document details by ID.
    
    Requires API key authentication. Returns 404 if not found.
    """
    try:
        validate_tenant_id(tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    require_tenant_access(tenant_id, api_tenant_id)
    
    db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
    db.commit()
    
    row = db.execute(
        text("""
            SELECT id, tenant_id, kb_name, external_id, title, content, metadata, created_at, updated_at
            FROM rag_documents
            WHERE id = :doc_id AND tenant_id = :tenant_id
        """),
        {"doc_id": doc_id, "tenant_id": tenant_id}
    ).fetchone()
    
    if not row:
        raise HTTPException(status_code=404, detail="RAG document not found")
    
    return RAGDocumentResponse(
        id=str(row.id),
        tenant_id=str(row.tenant_id),
        kb_name=row.kb_name,
        external_id=row.external_id,
        title=row.title,
        content=row.content,
        metadata=row.metadata or {},
        created_at=row.created_at.isoformat(),
        updated_at=row.updated_at.isoformat(),
    )


@router.post("/tenants/{tenant_id}/rag/documents", tags=["Knowledge Bases"], response_model=RAGDocumentResponse)
async def create_rag_document(
    tenant_id: str,
    request: CreateRAGDocumentRequest,
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """
    Create a new RAG document with automatic chunking and embedding.
    
    Requires API key authentication. Creates a document, splits it into chunks,
    generates embeddings for each chunk, and stores them in the database.
    
    **Example Request:**
    ```json
    {
        "kb_name": "support_faq",
        "title": "FAQ: Getting Started",
        "content": "This is a long document that will be chunked...",
        "metadata": {"source": "website"},
        "chunk_size": 1000,
        "chunk_overlap": 200
    }
    ```
    """
    try:
        validate_tenant_id(tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    require_tenant_access(tenant_id, api_tenant_id)
    
    # Validate kb_name format (security)
    import re
    if not re.match(r'^[a-zA-Z0-9_-]+$', request.kb_name):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid kb_name format. Must be alphanumeric with underscores/hyphens only."
        )
    
    if len(request.kb_name) > 64:
        raise HTTPException(status_code=400, detail="kb_name too long (max 64 characters)")
    
    db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
    db.commit()
    
    # Verify knowledge base exists
    kb = db.execute(
        text("SELECT id, name FROM knowledge_bases WHERE tenant_id = :tenant_id AND name = :kb_name"),
        {"tenant_id": tenant_id, "kb_name": request.kb_name}
    ).fetchone()
    
    if not kb:
        raise HTTPException(
            status_code=404,
            detail=f"Knowledge base '{request.kb_name}' not found. Create it first using /knowledge-bases endpoint."
        )
    
    # Create document
    doc_id = uuid.uuid4()
    db.execute(
        text("""
            INSERT INTO rag_documents (
                id, tenant_id, kb_name, external_id, title, content, metadata
            ) VALUES (
                :id, :tenant_id, :kb_name, :external_id, :title, :content, CAST(:metadata AS jsonb)
            )
        """),
        {
            "id": doc_id,
            "tenant_id": tenant_id,
            "kb_name": request.kb_name,
            "external_id": request.external_id,
            "title": request.title,
            "content": request.content,
            "metadata": json.dumps(request.metadata or {}),
        }
    )
    db.commit()
    
    # Chunk the document
    chunks = chunk_text(request.content, request.chunk_size, request.chunk_overlap)
    
    # Generate embeddings for chunks
    try:
        embeddings = await embedding_generator.generate_embeddings_batch(chunks)
    except Exception as e:
        # If embedding generation fails, delete the document and return error
        db.execute(
            text("DELETE FROM rag_documents WHERE id = :doc_id"),
            {"doc_id": doc_id}
        )
        db.commit()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate embeddings: {str(e)}"
        )
    
    # Insert chunks with embeddings
    for idx, (chunk_content, embedding) in enumerate(zip(chunks, embeddings)):
        chunk_id = uuid.uuid4()
        
        # Validate and format embedding
        try:
            embedding_array = np.array(embedding, dtype=np.float32)
            if not np.all(np.isfinite(embedding_array)):
                raise ValueError("Invalid embedding values")
            embedding_array = np.clip(embedding_array, -1e6, 1e6)
            embedding_str = "[" + ",".join(map(str, embedding_array.tolist())) + "]"
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to format embedding for chunk {idx}: {str(e)}"
            )
        
        db.execute(
            text("""
                INSERT INTO rag_chunks (
                    id, tenant_id, kb_name, document_id, chunk_index, content, embedding, metadata
                ) VALUES (
                    :id, :tenant_id, :kb_name, :document_id, :chunk_index, :content,
                    CAST(:embedding AS vector), CAST(:metadata AS jsonb)
                )
            """),
            {
                "id": chunk_id,
                "tenant_id": tenant_id,
                "kb_name": request.kb_name,
                "document_id": doc_id,
                "chunk_index": idx,
                "content": chunk_content,
                "embedding": embedding_str,
                "metadata": json.dumps({}),
            }
        )
    
    db.commit()
    
    # Auto-sync document to all active providers (non-blocking)
    try:
        await kb_sync_service.sync_document_to_providers(
            tenant_id=tenant_id,
            kb_id=str(kb.id),
            kb_name=kb.name,
            document_id=str(doc_id),
            content=request.content,
            title=request.title,
            db=db
        )
    except Exception as e:
        # Log error but don't fail document creation
        logger.error(f"Error auto-syncing document {doc_id} to providers: {e}", exc_info=True)
    
    # Fetch created document
    row = db.execute(
        text("""
            SELECT id, tenant_id, kb_name, external_id, title, content, metadata, created_at, updated_at
            FROM rag_documents
            WHERE id = :id
        """),
        {"id": doc_id}
    ).fetchone()
    
    return RAGDocumentResponse(
        id=str(row.id),
        tenant_id=str(row.tenant_id),
        kb_name=row.kb_name,
        external_id=row.external_id,
        title=row.title,
        content=row.content,
        metadata=row.metadata or {},
        created_at=row.created_at.isoformat(),
        updated_at=row.updated_at.isoformat(),
    )


@router.put("/tenants/{tenant_id}/rag/documents/{doc_id}", tags=["Knowledge Bases"], response_model=RAGDocumentResponse)
async def update_rag_document(
    tenant_id: str,
    doc_id: str,
    request: UpdateRAGDocumentRequest,
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """
    Update RAG document.
    
    Requires API key authentication. Only provided fields will be updated.
    Note: Updating content does NOT automatically reindex chunks. Use /reindex endpoint for that.
    """
    try:
        validate_tenant_id(tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    require_tenant_access(tenant_id, api_tenant_id)
    
    db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
    db.commit()
    
    # Check if document exists
    existing = db.execute(
        text("SELECT id, kb_name FROM rag_documents WHERE id = :doc_id AND tenant_id = :tenant_id"),
        {"doc_id": doc_id, "tenant_id": tenant_id}
    ).fetchone()
    
    if not existing:
        raise HTTPException(status_code=404, detail="RAG document not found")
    
    # Build update query
    updates = []
    params = {"doc_id": doc_id, "tenant_id": tenant_id}
    
    if request.title is not None:
        updates.append("title = :title")
        params["title"] = request.title
    
    if request.content is not None:
        updates.append("content = :content")
        params["content"] = request.content
    
    if request.metadata is not None:
        updates.append("metadata = CAST(:metadata AS jsonb)")
        params["metadata"] = json.dumps(request.metadata)
    
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    
    updates.append("updated_at = now()")
    
    db.execute(
        text(f"""
            UPDATE rag_documents
            SET {', '.join(updates)}
            WHERE id = :doc_id AND tenant_id = :tenant_id
        """),
        params
    )
    db.commit()
    
    # Fetch updated document
    row = db.execute(
        text("""
            SELECT id, tenant_id, kb_name, external_id, title, content, metadata, created_at, updated_at
            FROM rag_documents
            WHERE id = :doc_id
        """),
        {"doc_id": doc_id}
    ).fetchone()
    
    return RAGDocumentResponse(
        id=str(row.id),
        tenant_id=str(row.tenant_id),
        kb_name=row.kb_name,
        external_id=row.external_id,
        title=row.title,
        content=row.content,
        metadata=row.metadata or {},
        created_at=row.created_at.isoformat(),
        updated_at=row.updated_at.isoformat(),
    )


@router.delete("/tenants/{tenant_id}/rag/documents/{doc_id}", tags=["Knowledge Bases"])
async def delete_rag_document(
    tenant_id: str,
    doc_id: str,
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """
    Delete a RAG document and all its chunks.
    
    Requires API key authentication. Permanently deletes the document and all associated chunks.
    """
    try:
        validate_tenant_id(tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    require_tenant_access(tenant_id, api_tenant_id)
    
    db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
    db.commit()
    
    # Check if document exists
    existing = db.execute(
        text("SELECT id FROM rag_documents WHERE id = :doc_id AND tenant_id = :tenant_id"),
        {"doc_id": doc_id, "tenant_id": tenant_id}
    ).fetchone()
    
    if not existing:
        raise HTTPException(status_code=404, detail="RAG document not found")
    
    # Delete document (chunks will be deleted via CASCADE)
    result = db.execute(
        text("DELETE FROM rag_documents WHERE id = :doc_id AND tenant_id = :tenant_id"),
        {"doc_id": doc_id, "tenant_id": tenant_id}
    )
    db.commit()
    
    return {
        "status": "deleted",
        "message": "RAG document and all chunks deleted successfully"
    }


@router.post("/tenants/{tenant_id}/rag/documents/{doc_id}/reindex", tags=["Knowledge Bases"])
async def reindex_rag_document(
    tenant_id: str,
    doc_id: str,
    chunk_size: int = Query(1000, ge=100, le=10000, description="Character count per chunk"),
    chunk_overlap: int = Query(200, ge=0, le=500, description="Character overlap between chunks"),
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """
    Reindex a RAG document (rechunk and regenerate embeddings).
    
    Requires API key authentication. Deletes existing chunks and recreates them
    with new chunking parameters and fresh embeddings.
    
    Useful when:
    - Document content was updated
    - Chunking parameters need to change
    - Embeddings need to be regenerated
    """
    try:
        validate_tenant_id(tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    require_tenant_access(tenant_id, api_tenant_id)
    
    db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
    db.commit()
    
    # Get document
    doc = db.execute(
        text("""
            SELECT id, tenant_id, kb_name, content
            FROM rag_documents
            WHERE id = :doc_id AND tenant_id = :tenant_id
        """),
        {"doc_id": doc_id, "tenant_id": tenant_id}
    ).fetchone()
    
    if not doc:
        raise HTTPException(status_code=404, detail="RAG document not found")
    
    # Delete existing chunks
    db.execute(
        text("DELETE FROM rag_chunks WHERE document_id = :doc_id AND tenant_id = :tenant_id"),
        {"doc_id": doc_id, "tenant_id": tenant_id}
    )
    db.commit()
    
    # Rechunk the document
    chunks = chunk_text(doc.content, chunk_size, chunk_overlap)
    
    # Generate embeddings for chunks
    try:
        embeddings = await embedding_generator.generate_embeddings_batch(chunks)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate embeddings: {str(e)}"
        )
    
    # Insert new chunks with embeddings
    for idx, (chunk_content, embedding) in enumerate(zip(chunks, embeddings)):
        chunk_id = uuid.uuid4()
        
        # Validate and format embedding
        try:
            embedding_array = np.array(embedding, dtype=np.float32)
            if not np.all(np.isfinite(embedding_array)):
                raise ValueError("Invalid embedding values")
            embedding_array = np.clip(embedding_array, -1e6, 1e6)
            embedding_str = "[" + ",".join(map(str, embedding_array.tolist())) + "]"
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to format embedding for chunk {idx}: {str(e)}"
            )
        
        db.execute(
            text("""
                INSERT INTO rag_chunks (
                    id, tenant_id, kb_name, document_id, chunk_index, content, embedding, metadata
                ) VALUES (
                    :id, :tenant_id, :kb_name, :document_id, :chunk_index, :content,
                    CAST(:embedding AS vector), CAST(:metadata AS jsonb)
                )
            """),
            {
                "id": chunk_id,
                "tenant_id": doc.tenant_id,
                "kb_name": doc.kb_name,
                "document_id": doc_id,
                "chunk_index": idx,
                "content": chunk_content,
                "embedding": embedding_str,
                "metadata": json.dumps({}),
            }
        )
    
    db.commit()
    
    return {
        "status": "completed",
        "message": f"Document reindexed successfully with {len(chunks)} chunks",
        "chunks_created": len(chunks),
    }


@router.get("/tenants/{tenant_id}/rag/documents/{doc_id}/chunks", tags=["Knowledge Bases"], response_model=RAGChunkListResponse)
async def list_rag_document_chunks(
    tenant_id: str,
    doc_id: str,
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    db: Session = Depends(get_db),
    api_tenant_id: str = Security(verify_api_key),
):
    """
    List all chunks for a RAG document.
    
    Requires API key authentication. Returns all chunks associated with the document,
    ordered by chunk_index.
    """
    try:
        validate_tenant_id(tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    require_tenant_access(tenant_id, api_tenant_id)
    
    db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
    db.commit()
    
    # Verify document exists
    doc = db.execute(
        text("SELECT id FROM rag_documents WHERE id = :doc_id AND tenant_id = :tenant_id"),
        {"doc_id": doc_id, "tenant_id": tenant_id}
    ).fetchone()
    
    if not doc:
        raise HTTPException(status_code=404, detail="RAG document not found")
    
    rows = db.execute(
        text("""
            SELECT id, tenant_id, kb_name, document_id, chunk_index, content, metadata, created_at
            FROM rag_chunks
            WHERE document_id = :doc_id AND tenant_id = :tenant_id
            ORDER BY chunk_index
            LIMIT :limit OFFSET :offset
        """),
        {"doc_id": doc_id, "tenant_id": tenant_id, "limit": limit, "offset": offset}
    ).fetchall()
    
    items = [
        RAGChunkResponse(
            id=str(row.id),
            tenant_id=str(row.tenant_id),
            kb_name=row.kb_name,
            document_id=str(row.document_id),
            chunk_index=row.chunk_index,
            content=row.content,
            metadata=row.metadata or {},
            created_at=row.created_at.isoformat(),
        )
        for row in rows
    ]
    
    return RAGChunkListResponse(items=items, count=len(items))

