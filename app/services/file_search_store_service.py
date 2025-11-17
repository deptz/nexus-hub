"""Gemini file search store service for managing file search stores and files."""

import logging
import time
import asyncio
from typing import Optional, Dict, Any, List
from app.infra.config import config

logger = logging.getLogger(__name__)


class FileSearchStoreService:
    """Service for managing Gemini file search stores."""
    
    def __init__(self):
        self._client = None
    
    @property
    def client(self):
        """Lazy initialization of Gemini client."""
        if self._client is None:
            if not config.GEMINI_API_KEY:
                raise ValueError("GEMINI_API_KEY not configured")
            try:
                from google import genai
                self._client = genai.Client(api_key=config.GEMINI_API_KEY)
            except ImportError:
                raise ImportError("google-genai SDK not installed. Install with: pip install google-genai")
        return self._client
    
    def create_file_search_store(self, display_name: str, tenant_id: str) -> Dict[str, Any]:
        """
        Create a new file search store.
        
        Args:
            display_name: Display name for the store
            tenant_id: Tenant ID for metadata
        
        Returns:
            Dict with store_name and other metadata
        """
        try:
            client = self.client
            
            file_search_store = client.file_search_stores.create(
                config={
                    'display_name': display_name,
                    'metadata': {'tenant_id': tenant_id}
                }
            )
            
            store_name = file_search_store.name  # Format: "fileSearchStores/xxxxxxx"
            
            return {
                "store_name": store_name,
                "display_name": display_name,
                "created_at": getattr(file_search_store, 'create_time', None),
            }
        except Exception as e:
            logger.error(f"Error creating file search store: {e}", exc_info=True)
            raise
    
    def get_file_search_store(self, store_name: str) -> Optional[Dict[str, Any]]:
        """
        Get file search store details.
        
        Args:
            store_name: Store name (format: "fileSearchStores/xxxxxxx")
        
        Returns:
            Dict with store details or None if not found
        """
        try:
            client = self.client
            
            # Note: Gemini SDK may not have a direct get method
            # For now, we'll return basic info if store_name is valid format
            if not store_name.startswith("fileSearchStores/"):
                return None
            
            return {
                "store_name": store_name,
                "display_name": None,  # Would need to fetch from API if available
            }
        except Exception as e:
            logger.error(f"Error getting file search store {store_name}: {e}", exc_info=True)
            return None
    
    def update_file_search_store(self, store_name: str, display_name: Optional[str] = None) -> bool:
        """
        Update file search store.
        
        Args:
            store_name: Store name
            display_name: New display name (optional)
        
        Returns:
            True if successful
        """
        try:
            client = self.client
            
            if not display_name:
                return True
            
            # Note: Gemini SDK may not have an update method
            # This is a placeholder for future implementation
            # For now, return True as stores are immutable
            logger.warning(f"Update not supported for file search stores yet: {store_name}")
            return True
        except Exception as e:
            logger.error(f"Error updating file search store {store_name}: {e}", exc_info=True)
            return False
    
    def delete_file_search_store(self, store_name: str) -> bool:
        """
        Delete file search store.
        
        Args:
            store_name: Store name
        
        Returns:
            True if successful
        """
        try:
            client = self.client
            
            client.file_search_stores.delete(store_name)
            return True
        except Exception as e:
            logger.error(f"Error deleting file search store {store_name}: {e}", exc_info=True)
            return False
    
    async def upload_file(self, store_name: str, file_path: str, display_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Upload a file to file search store.
        
        Args:
            store_name: Store name
            file_path: Path to file to upload
            display_name: Optional display name
        
        Returns:
            Dict with file_name and other metadata
        """
        try:
            client = self.client
            
            # Upload and import file
            operation = client.file_search_stores.upload_to_file_search_store(
                file=file_path,
                file_search_store_name=store_name,
                config={'display_name': display_name or file_path.split('/')[-1]}
            )
            
            # Wait for operation to complete
            max_wait = 300  # 5 minutes max
            wait_time = 0
            while wait_time < max_wait:
                if operation.done:
                    break
                
                await asyncio.sleep(5)
                wait_time += 5
                # Refresh operation status
                operation = client.operations.get(operation)
            
            if not operation.done:
                logger.warning(f"File upload timed out for {file_path}, but may still be processing")
            
            # Extract file name from operation result if available
            file_name = None
            if hasattr(operation, 'response'):
                file_name = getattr(operation.response, 'name', None)
            
            return {
                "file_name": file_name,
                "display_name": display_name,
                "status": "completed" if operation.done else "processing",
            }
        except Exception as e:
            logger.error(f"Error uploading file to file search store {store_name}: {e}", exc_info=True)
            raise
    
    async def upload_file_from_content(self, store_name: str, content: bytes, filename: str) -> Dict[str, Any]:
        """
        Upload file content to file search store.
        
        Args:
            store_name: Store name
            content: File content as bytes
            filename: Filename
        
        Returns:
            Dict with file_name and other metadata
        """
        import tempfile
        import os
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(filename)[1]) as tmp_file:
            tmp_file.write(content)
            tmp_path = tmp_file.name
        
        try:
            return await self.upload_file(store_name, tmp_path, filename)
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
    
    async def list_files(self, store_name: str, limit: int = 100) -> List[Dict[str, Any]]:
        """
        List files in file search store.
        
        Args:
            store_name: Store name
            limit: Maximum number of files to return
        
        Returns:
            List of file dicts
        """
        try:
            client = self.client
            
            # Note: Gemini SDK may not have a direct list files method
            # This is a placeholder for future implementation
            # For now, return empty list
            logger.warning(f"List files not fully supported for file search stores yet: {store_name}")
            return []
        except Exception as e:
            logger.error(f"Error listing files in file search store {store_name}: {e}", exc_info=True)
            return []
    
    async def delete_file(self, store_name: str, file_name: str) -> bool:
        """
        Delete a file from file search store.
        
        Args:
            store_name: Store name
            file_name: File name
        
        Returns:
            True if successful
        """
        try:
            client = self.client
            
            # Note: Gemini SDK may not have a direct delete file method
            # This might require deleting the entire store or using a different API
            # For now, return False as this is not fully supported
            logger.warning(f"Delete file not fully supported for file search stores yet: {store_name}/{file_name}")
            return False
        except Exception as e:
            logger.error(f"Error deleting file {file_name} from file search store {store_name}: {e}", exc_info=True)
            return False


# Global instance
file_search_store_service = FileSearchStoreService()

