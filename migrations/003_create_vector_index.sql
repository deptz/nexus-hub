-- Migration: 003_create_vector_index.sql
-- Creates vector index for RAG chunks semantic search
-- Run this after you have some data in rag_chunks table for optimal performance

-- Note: Adjust the 'lists' parameter based on your data size:
-- - Small datasets (< 10k vectors): lists = 10-50
-- - Medium datasets (10k-100k): lists = 50-100
-- - Large datasets (> 100k): lists = 100-200
-- Rule of thumb: lists ≈ sqrt(total_vectors)

-- Check if table exists and has data before creating index
DO $$
DECLARE
    table_exists BOOLEAN;
    vector_count INTEGER;
    lists_param INTEGER;
    index_sql TEXT;
BEGIN
    -- Check if rag_chunks table exists
    SELECT EXISTS (
        SELECT FROM information_schema.tables 
        WHERE table_schema = 'public' 
        AND table_name = 'rag_chunks'
    ) INTO table_exists;
    
    IF NOT table_exists THEN
        RAISE NOTICE 'Table rag_chunks does not exist yet. Run migration 001_initial_schema.sql first.';
        RETURN;
    END IF;
    
    -- Check if we have data
    SELECT COUNT(*) INTO vector_count FROM rag_chunks WHERE embedding IS NOT NULL;
    
    IF vector_count > 0 THEN
        -- Calculate lists parameter: between 10 and 100, roughly vector_count / 1000
        lists_param := LEAST(100, GREATEST(10, vector_count / 1000));
        
        -- Build dynamic SQL for CREATE INDEX (WITH clause doesn't accept expressions)
        index_sql := format(
            'CREATE INDEX IF NOT EXISTS rag_chunks_embedding_idx ON rag_chunks ' ||
            'USING ivfflat (embedding vector_cosine_ops) ' ||
            'WITH (lists = %s)',
            lists_param
        );
        
        -- Execute the dynamic SQL
        EXECUTE index_sql;
        
        RAISE NOTICE 'Vector index created with lists parameter: %', lists_param;
    ELSE
        RAISE NOTICE 'No vectors found in rag_chunks. Create index manually after loading data:';
        RAISE NOTICE 'CREATE INDEX rag_chunks_embedding_idx ON rag_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);';
    END IF;
END $$;

-- Alternative: HNSW index (better for very large datasets, but slower to build)
-- CREATE INDEX rag_chunks_embedding_hnsw_idx ON rag_chunks
-- USING hnsw (embedding vector_cosine_ops)
-- WITH (m = 16, ef_construction = 64);

