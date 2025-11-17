"""OpenAI vector store service for managing vector stores and files."""

import logging
from typing import Optional, Dict, Any, List
from openai import OpenAI, AsyncOpenAI
from app.infra.config import config

logger = logging.getLogger(__name__)


class VectorStoreService:
    """Service for managing OpenAI vector stores."""
    
    def __init__(self):
        self._client = None
        self._async_client = None
    
    @property
    def client(self) -> OpenAI:
        """Synchronous OpenAI client."""
        if self._client is None:
            if not config.OPENAI_API_KEY:
                raise ValueError("OPENAI_API_KEY not configured")
            self._client = OpenAI(api_key=config.OPENAI_API_KEY)
        return self._client
    
    @property
    def async_client(self) -> AsyncOpenAI:
        """Asynchronous OpenAI client."""
        if self._async_client is None:
            if not config.OPENAI_API_KEY:
                raise ValueError("OPENAI_API_KEY not configured")
            self._async_client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
        return self._async_client
    
    def create_vector_store(self, name: str, tenant_id: str) -> Dict[str, Any]:
        """
        Create a new vector store.
        
        Args:
            name: Vector store name
            tenant_id: Tenant ID for metadata
        
        Returns:
            Dict with vector_store_id and other metadata
        """
        try:
            client = self.client
            
            # Try different API paths
            if hasattr(client.beta, 'vector_stores'):
                vector_store = client.beta.vector_stores.create(
                    name=name,
                    metadata={"tenant_id": tenant_id}
                )
            elif hasattr(client.beta, 'assistants') and hasattr(client.beta.assistants, 'vector_stores'):
                vector_store = client.beta.assistants.vector_stores.create(
                    name=name,
                    metadata={"tenant_id": tenant_id}
                )
            else:
                raise ValueError("Vector stores API not available")
            
            return {
                "vector_store_id": vector_store.id,
                "name": vector_store.name if hasattr(vector_store, 'name') else name,
                "created_at": vector_store.created_at if hasattr(vector_store, 'created_at') else None,
            }
        except Exception as e:
            logger.error(f"Error creating vector store: {e}", exc_info=True)
            raise
    
    def get_vector_store(self, vector_store_id: str) -> Optional[Dict[str, Any]]:
        """
        Get vector store details.
        
        Args:
            vector_store_id: Vector store ID
        
        Returns:
            Dict with vector store details or None if not found
        """
        try:
            client = self.client
            
            if hasattr(client.beta, 'vector_stores'):
                vector_store = client.beta.vector_stores.retrieve(vector_store_id)
            elif hasattr(client.beta, 'assistants') and hasattr(client.beta.assistants, 'vector_stores'):
                vector_store = client.beta.assistants.vector_stores.retrieve(vector_store_id)
            else:
                return None
            
            return {
                "vector_store_id": vector_store.id,
                "name": getattr(vector_store, 'name', None),
                "file_counts": getattr(vector_store, 'file_counts', {}),
                "created_at": getattr(vector_store, 'created_at', None),
            }
        except Exception as e:
            logger.error(f"Error getting vector store {vector_store_id}: {e}", exc_info=True)
            return None
    
    def update_vector_store(self, vector_store_id: str, name: Optional[str] = None) -> bool:
        """
        Update vector store.
        
        Args:
            vector_store_id: Vector store ID
            name: New name (optional)
        
        Returns:
            True if successful
        """
        try:
            client = self.client
            update_params = {}
            if name:
                update_params["name"] = name
            
            if not update_params:
                return True
            
            if hasattr(client.beta, 'vector_stores'):
                client.beta.vector_stores.update(vector_store_id, **update_params)
            elif hasattr(client.beta, 'assistants') and hasattr(client.beta.assistants, 'vector_stores'):
                client.beta.assistants.vector_stores.update(vector_store_id, **update_params)
            else:
                return False
            
            return True
        except Exception as e:
            logger.error(f"Error updating vector store {vector_store_id}: {e}", exc_info=True)
            return False
    
    def delete_vector_store(self, vector_store_id: str) -> bool:
        """
        Delete vector store.
        
        Args:
            vector_store_id: Vector store ID
        
        Returns:
            True if successful
        """
        try:
            client = self.client
            
            if hasattr(client.beta, 'vector_stores'):
                client.beta.vector_stores.delete(vector_store_id)
            elif hasattr(client.beta, 'assistants') and hasattr(client.beta.assistants, 'vector_stores'):
                client.beta.assistants.vector_stores.delete(vector_store_id)
            else:
                return False
            
            return True
        except Exception as e:
            logger.error(f"Error deleting vector store {vector_store_id}: {e}", exc_info=True)
            return False
    
    async def upload_file(self, vector_store_id: str, file_path: str, display_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Upload a file to vector store.
        
        Args:
            vector_store_id: Vector store ID
            file_path: Path to file to upload
            display_name: Optional display name
        
        Returns:
            Dict with file_id and other metadata
        """
        try:
            client = self.async_client
            
            # First, upload the file
            with open(file_path, "rb") as f:
                file = await client.files.create(
                    file=f,
                    purpose="assistants"
                )
            
            # Then add file to vector store
            if hasattr(client.beta, 'vector_stores'):
                await client.beta.vector_stores.files.create(
                    vector_store_id=vector_store_id,
                    file_id=file.id
                )
            elif hasattr(client.beta, 'assistants') and hasattr(client.beta.assistants, 'vector_stores'):
                await client.beta.assistants.vector_stores.files.create(
                    vector_store_id=vector_store_id,
                    file_id=file.id
                )
            else:
                raise ValueError("Vector stores API not available")
            
            return {
                "file_id": file.id,
                "filename": getattr(file, 'filename', display_name),
                "bytes": getattr(file, 'bytes', None),
            }
        except Exception as e:
            logger.error(f"Error uploading file to vector store {vector_store_id}: {e}", exc_info=True)
            raise
    
    async def upload_file_from_content(self, vector_store_id: str, content: bytes, filename: str) -> Dict[str, Any]:
        """
        Upload file content to vector store.
        
        Args:
            vector_store_id: Vector store ID
            content: File content as bytes
            filename: Filename
        
        Returns:
            Dict with file_id and other metadata
        """
        import tempfile
        import os
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(filename)[1]) as tmp_file:
            tmp_file.write(content)
            tmp_path = tmp_file.name
        
        try:
            return await self.upload_file(vector_store_id, tmp_path, filename)
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
    
    async def list_files(self, vector_store_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        """
        List files in vector store.
        
        Args:
            vector_store_id: Vector store ID
            limit: Maximum number of files to return
        
        Returns:
            List of file dicts
        """
        try:
            client = self.async_client
            
            if hasattr(client.beta, 'vector_stores'):
                files = await client.beta.vector_stores.files.list(
                    vector_store_id=vector_store_id,
                    limit=limit
                )
            elif hasattr(client.beta, 'assistants') and hasattr(client.beta.assistants, 'vector_stores'):
                files = await client.beta.assistants.vector_stores.files.list(
                    vector_store_id=vector_store_id,
                    limit=limit
                )
            else:
                return []
            
            return [
                {
                    "file_id": file.id,
                    "status": getattr(file, 'status', None),
                    "created_at": getattr(file, 'created_at', None),
                }
                for file in files.data
            ]
        except Exception as e:
            logger.error(f"Error listing files in vector store {vector_store_id}: {e}", exc_info=True)
            return []
    
    async def delete_file(self, vector_store_id: str, file_id: str) -> bool:
        """
        Delete a file from vector store.
        
        Args:
            vector_store_id: Vector store ID
            file_id: File ID
        
        Returns:
            True if successful
        """
        try:
            client = self.async_client
            
            if hasattr(client.beta, 'vector_stores'):
                await client.beta.vector_stores.files.delete(
                    vector_store_id=vector_store_id,
                    file_id=file_id
                )
            elif hasattr(client.beta, 'assistants') and hasattr(client.beta.assistants, 'vector_stores'):
                await client.beta.assistants.vector_stores.files.delete(
                    vector_store_id=vector_store_id,
                    file_id=file_id
                )
            else:
                return False
            
            return True
        except Exception as e:
            logger.error(f"Error deleting file {file_id} from vector store {vector_store_id}: {e}", exc_info=True)
            return False


# Global instance
vector_store_service = VectorStoreService()

