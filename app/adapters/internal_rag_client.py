"""Internal RAG client with pgvector semantic search."""

from typing import Dict, Any, List
from sqlalchemy.orm import Session
from sqlalchemy import text
import numpy as np
from app.models.tenant import TenantContext
from app.models.tool import ToolDefinition
from app.infra.database import get_db_session
from app.infra.embeddings import embedding_generator


class InternalRAGClient:
    """Client for internal RAG (pgvector) queries."""
    
    async def query(
        self,
        tenant_ctx: TenantContext,
        tool_def: ToolDefinition,
        args: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Query internal RAG for a tenant using pgvector semantic search.
        
        Args:
            tenant_ctx: TenantContext for tenant isolation
            tool_def: ToolDefinition (should have kb_name in implementation_ref)
            args: Tool arguments, should contain 'query' key
        
        Returns:
            Dict with 'results' (list of chunks) and 'count'
        """
        # Extract query from args
        query_text = args.get("query") or args.get("text", "")
        if not query_text:
            return {
                "results": [],
                "count": 0,
                "error": "No query text provided",
            }
        
        # Get KB name from tool definition or args
        kb_name = (
            tool_def.implementation_ref.get("kb_name") or
            args.get("kb_name") or
            "default"  # Fallback to default KB
        )
        
        # SECURITY: Validate kb_name to prevent injection
        # kb_name should be a safe identifier (alphanumeric, underscore, hyphen)
        import re
        if not re.match(r'^[a-zA-Z0-9_-]+$', kb_name):
            return {
                "results": [],
                "count": 0,
                "error": f"Invalid kb_name format: {kb_name}. Must be alphanumeric with underscores/hyphens only.",
            }
        
        # Limit kb_name length
        if len(kb_name) > 64:
            return {
                "results": [],
                "count": 0,
                "error": "kb_name too long (max 64 characters)",
            }
        
        # Limit number of results
        limit = args.get("limit", 5)
        limit = min(limit, 20)  # Cap at 20
        
        # Generate embedding for query
        try:
            query_embedding = await embedding_generator.generate_embedding(query_text)
        except Exception as e:
            return {
                "results": [],
                "count": 0,
                "error": f"Failed to generate embedding: {str(e)}",
            }
        
        # Query rag_chunks with vector similarity
        # RLS is enforced via tenant_id in the query
        with get_db_session(tenant_ctx.tenant_id) as session:
            # Use cosine similarity for vector search
            # pgvector supports <=> operator for cosine distance
            # Convert embedding list to pgvector format: [1,2,3]::vector
            # Validate embedding is a list of numbers
            if not isinstance(query_embedding, (list, np.ndarray)):
                return {
                    "results": [],
                    "count": 0,
                    "error": "Invalid embedding format",
                }
            
            # Validate embedding values are numeric and within reasonable range
            try:
                embedding_array = np.array(query_embedding, dtype=np.float32)
                # Check for NaN or Inf values
                if not np.all(np.isfinite(embedding_array)):
                    return {
                        "results": [],
                        "count": 0,
                        "error": "Invalid embedding values",
                    }
                # Normalize embedding values to reasonable range
                embedding_array = np.clip(embedding_array, -1e6, 1e6)
                embedding_str = "[" + ",".join(map(str, embedding_array.tolist())) + "]"
            except (ValueError, TypeError) as e:
                return {
                    "results": [],
                    "count": 0,
                    "error": f"Invalid embedding format: {str(e)}",
                }
            
            results = session.execute(
                text("""
                    SELECT 
                        rc.id,
                        rc.content,
                        rc.metadata,
                        rc.document_id,
                        rd.title as document_title,
                        1 - (rc.embedding <=> CAST(:query_embedding AS vector)) as similarity_score
                    FROM rag_chunks rc
                    JOIN rag_documents rd ON rc.document_id = rd.id
                    WHERE rc.tenant_id = :tenant_id
                      AND rc.kb_name = :kb_name
                    ORDER BY rc.embedding <=> CAST(:query_embedding AS vector)
                    LIMIT :limit
                """),
                {
                    "tenant_id": tenant_ctx.tenant_id,
                    "kb_name": kb_name,
                    "query_embedding": embedding_str,
                    "limit": limit,
                }
            ).fetchall()
            
            # Format results
            formatted_results = []
            for row in results:
                formatted_results.append({
                    "content": row.content,
                    "metadata": row.metadata or {},
                    "score": float(row.similarity_score),
                    "document_id": str(row.document_id),
                    "document_title": row.document_title,
                })
            
            return {
                "results": formatted_results,
                "count": len(formatted_results),
            }


internal_rag_client = InternalRAGClient()

