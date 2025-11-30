"""Embedding generation utility for RAG."""

from typing import List
import numpy as np
from app.infra.config import config

# Try to use OpenAI embeddings by default, fallback to sentence-transformers
try:
    from openai import AsyncOpenAI
    USE_OPENAI_EMBEDDINGS = True
except ImportError:
    USE_OPENAI_EMBEDDINGS = False

try:
    from sentence_transformers import SentenceTransformer
    USE_SENTENCE_TRANSFORMERS = True
except ImportError:
    USE_SENTENCE_TRANSFORMERS = False


class EmbeddingGenerator:
    """Generates embeddings for text queries."""
    
    def __init__(self):
        self._openai_client = None
        self._sentence_model = None
        self.embedding_dim = 1536  # OpenAI text-embedding-3-small default
    
    @property
    def openai_client(self):
        """Lazy initialization of OpenAI client."""
        if self._openai_client is None and config.OPENAI_API_KEY:
            self._openai_client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
        return self._openai_client
    
    @property
    def sentence_model(self):
        """Lazy initialization of sentence transformer model."""
        if self._sentence_model is None and USE_SENTENCE_TRANSFORMERS:
            # Use a model that produces 1536-dim embeddings or adjust dimension
            # all-MiniLM-L6-v2 produces 384-dim, so we'll use a larger model
            try:
                self._sentence_model = SentenceTransformer('sentence-transformers/all-mpnet-base-v2')
                self.embedding_dim = 768  # all-mpnet-base-v2 dimension
            except Exception:
                # Fallback to smaller model
                self._sentence_model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
                self.embedding_dim = 384
        return self._sentence_model
    
    async def generate_embedding(self, text: str) -> List[float]:
        """
        Generate embedding for a text string.
        
        Args:
            text: Text to embed
        
        Returns:
            List of floats representing the embedding vector
        """
        # Try OpenAI first if available
        if USE_OPENAI_EMBEDDINGS and self.openai_client:
            try:
                response = await self.openai_client.embeddings.create(
                    model="text-embedding-3-small",
                    input=text,
                )
                return response.data[0].embedding
            except Exception:
                # Fall back to sentence transformers
                pass
        
        # Use sentence transformers as fallback
        if USE_SENTENCE_TRANSFORMERS and self.sentence_model:
            embedding = self.sentence_model.encode(text, convert_to_numpy=True)
            return embedding.tolist()
        
        # Last resort: return zero vector (should not happen in production)
        raise RuntimeError(
            "No embedding model available. Install sentence-transformers or configure OPENAI_API_KEY"
        )
    
    async def generate_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """
        Generate embeddings for multiple texts (more efficient).
        
        Args:
            texts: List of texts to embed
        
        Returns:
            List of embedding vectors
        """
        # Try OpenAI first if available
        if USE_OPENAI_EMBEDDINGS and self.openai_client:
            try:
                response = await self.openai_client.embeddings.create(
                    model="text-embedding-3-small",
                    input=texts,
                )
                return [item.embedding for item in response.data]
            except Exception:
                pass
        
        # Use sentence transformers as fallback
        if USE_SENTENCE_TRANSFORMERS and self.sentence_model:
            embeddings = self.sentence_model.encode(texts, convert_to_numpy=True)
            return embeddings.tolist()
        
        raise RuntimeError(
            "No embedding model available. Install sentence-transformers or configure OPENAI_API_KEY"
        )


# Global instance
embedding_generator = EmbeddingGenerator()


