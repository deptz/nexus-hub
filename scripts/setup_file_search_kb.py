#!/usr/bin/env python3
"""Setup OpenAI and Gemini file search knowledge bases."""

import asyncio
import sys
import os
import tempfile
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from openai import OpenAI, AsyncOpenAI
import google.generativeai as genai
from sqlalchemy import create_engine, text
from app.infra.config import config

# Test documents for OpenAI
openai_docs = [
    {
        "name": "openai_company_policy.txt",
        "content": """Company Policy on Remote Work

Our company allows employees to work remotely up to 3 days per week. 
Remote work days must be approved by your manager in advance. 
All remote workers must have a stable internet connection and a dedicated workspace.

Remote work benefits:
- Better work-life balance
- Reduced commute time
- Increased productivity for many roles

Requirements:
- Manager approval required
- Minimum 2 days in office per week
- Reliable internet connection
- Dedicated workspace at home"""
    },
    {
        "name": "openai_product_returns.txt",
        "content": """Product Return Policy

Customers can return products within 30 days of purchase for a full refund. 
Items must be in original condition with tags attached. 
Returns can be processed online or at any retail location.

Return Process:
1. Contact customer service or visit a store
2. Provide proof of purchase
3. Items must be unused and in original packaging
4. Refund processed within 5-7 business days

Exceptions:
- Customized items cannot be returned
- Software licenses are non-refundable
- Sale items may have different return policies"""
    }
]

# Test documents for Gemini
gemini_docs = [
    {
        "name": "gemini_api_auth.txt",
        "content": """API Authentication Guide

All API requests require authentication using an API key in the X-API-Key header. 
API keys can be generated from the developer dashboard. 
Rate limits are 1000 requests per minute per key.

Authentication Methods:
1. Header-based: X-API-Key: your-api-key
2. Query parameter: ?api_key=your-api-key
3. Bearer token: Authorization: Bearer your-api-key

Security Best Practices:
- Never commit API keys to version control
- Rotate keys regularly
- Use different keys for different environments
- Monitor key usage for anomalies"""
    },
    {
        "name": "gemini_deployment.txt",
        "content": """Deployment Guide

To deploy the application:
1. Ensure all dependencies are installed: pip install -r requirements.txt
2. Run database migrations: alembic upgrade head
3. Set environment variables for API keys
4. Start the server: uvicorn app.main:app --host 0.0.0.0 --port 8000

Environment Variables Required:
- DATABASE_URL
- OPENAI_API_KEY (if using OpenAI)
- GEMINI_API_KEY (if using Gemini)
- MASTER_API_KEY

Production Checklist:
- Enable SSL/TLS
- Configure firewall rules
- Set up monitoring and logging
- Configure backup strategy
- Set up CI/CD pipeline"""
    }
]

def setup_openai_file_search(tenant_id):
    """Create OpenAI vector store and upload files."""
    if not config.OPENAI_API_KEY:
        print("⚠️  OPENAI_API_KEY not configured, skipping OpenAI file search setup")
        return None
    
    client = OpenAI(api_key=config.OPENAI_API_KEY)
    
    print("📦 Creating OpenAI vector store...")
    try:
        # Try different API paths
        if hasattr(client.beta, 'vector_stores'):
            vector_store = client.beta.vector_stores.create(
                name=f"Test Knowledge Base - {tenant_id[:8]}"
            )
        elif hasattr(client.beta, 'assistants') and hasattr(client.beta.assistants, 'vector_stores'):
            vector_store = client.beta.assistants.vector_stores.create(
                name=f"Test Knowledge Base - {tenant_id[:8]}"
            )
        else:
            # Create via assistant with file search
            print("⚠️  Vector stores API not available, creating assistant with file search...")
            # Upload files first
            file_ids = []
            with tempfile.TemporaryDirectory() as tmpdir:
                for doc in openai_docs:
                    file_path = os.path.join(tmpdir, doc["name"])
                    with open(file_path, "w") as f:
                        f.write(doc["content"])
                    
                    print(f"📄 Uploading {doc['name']}...")
                    with open(file_path, "rb") as f:
                        file = client.files.create(
                            file=f,
                            purpose="assistants"
                        )
                    file_ids.append(file.id)
                    print(f"✅ File {file.id} uploaded")
            
            # Create assistant with file search tool (requires gpt-4-turbo or later)
            assistant = client.beta.assistants.create(
                name=f"KB Assistant - {tenant_id[:8]}",
                model="gpt-4-turbo-preview",
                tools=[{"type": "file_search"}],
                tool_resources={
                    "file_search": {
                        "vector_store_ids": []  # Will be created automatically
                    }
                }
            )
            print(f"⚠️  Created assistant {assistant.id} - vector stores created automatically")
            print("⚠️  Note: You'll need to manually add vector_store_id to knowledge base")
            return None
        
        vector_store_id = vector_store.id
        print(f"✅ Vector store created: {vector_store_id}")
        
        # Upload files
        file_ids = []
        with tempfile.TemporaryDirectory() as tmpdir:
            for doc in openai_docs:
                file_path = os.path.join(tmpdir, doc["name"])
                with open(file_path, "w") as f:
                    f.write(doc["content"])
                
                print(f"📄 Uploading {doc['name']}...")
                with open(file_path, "rb") as f:
                    file = client.files.create(
                        file=f,
                        purpose="assistants"
                    )
                
                # Add file to vector store
                try:
                    if hasattr(client.beta, 'vector_stores'):
                        client.beta.vector_stores.files.create(
                            vector_store_id=vector_store_id,
                            file_id=file.id
                        )
                    elif hasattr(client.beta, 'assistants') and hasattr(client.beta.assistants, 'vector_stores'):
                        client.beta.assistants.vector_stores.files.create(
                            vector_store_id=vector_store_id,
                            file_id=file.id
                        )
                    file_ids.append(file.id)
                    print(f"✅ File {file.id} added to vector store")
                except Exception as e:
                    print(f"⚠️  Error adding file to vector store: {e}")
        
        print(f"✅ OpenAI file search setup complete: {vector_store_id}")
        return vector_store_id
        
    except Exception as e:
        print(f"❌ Error setting up OpenAI file search: {e}")
        print("⚠️  You may need to create vector stores manually via OpenAI Platform")
        return None

def setup_gemini_file_search(tenant_id):
    """Create Gemini File Search Store and upload files using new SDK."""
    if not config.GEMINI_API_KEY:
        print("⚠️  GEMINI_API_KEY not configured, skipping Gemini file search setup")
        return None
    
    try:
        from google import genai
        import time
    except ImportError:
        print("❌ google-genai SDK not installed")
        print("   Install with: pip install google-genai")
        print("   Or update requirements.txt and run: pip install -r requirements.txt")
        return None
    
    print("📦 Creating Gemini File Search Store...")
    try:
        # Initialize client with new SDK
        client = genai.Client(api_key=config.GEMINI_API_KEY)
        
        # Create File Search Store
        file_search_store = client.file_search_stores.create(
            config={'display_name': f"Test Knowledge Base - {tenant_id[:8]}"}
        )
        store_name = file_search_store.name  # Format: "fileSearchStores/xxxxxxx"
        
        print(f"✅ File Search Store created: {store_name}")
        
        # Upload files to the store
        with tempfile.TemporaryDirectory() as tmpdir:
            for doc in gemini_docs:
                file_path = os.path.join(tmpdir, doc["name"])
                with open(file_path, "w") as f:
                    f.write(doc["content"])
                
                print(f"📄 Uploading {doc['name']}...")
                try:
                    # Upload and import file using new SDK
                    operation = client.file_search_stores.upload_to_file_search_store(
                        file=file_path,
                        file_search_store_name=store_name,
                        config={'display_name': doc["name"]}
                    )
                    
                    # Wait for operation to complete
                    max_wait = 300  # 5 minutes max
                    wait_time = 0
                    while wait_time < max_wait:
                        if operation.done:
                            print(f"✅ File {doc['name']} uploaded and indexed")
                            break
                        
                        time.sleep(5)
                        wait_time += 5
                        operation = client.operations.get(operation)
                        
                        if wait_time % 30 == 0:  # Print progress every 30 seconds
                            print(f"   ⏳ Still indexing... ({wait_time}s)")
                    else:
                        if not operation.done:
                            print(f"⚠️  File {doc['name']} upload timed out, but may still be processing")
                        else:
                            print(f"✅ File {doc['name']} uploaded and indexed")
                        
                except Exception as e:
                    print(f"⚠️  Error uploading file {doc['name']}: {e}")
                    import traceback
                    traceback.print_exc()
        
        print(f"✅ Gemini file search setup complete: {store_name}")
        return store_name
        
    except Exception as e:
        print(f"❌ Error setting up Gemini file search: {e}")
        import traceback
        traceback.print_exc()
        return None

def configure_knowledge_bases(openai_tenant_id, gemini_tenant_id, openai_vector_store_id, gemini_store_name):
    """Configure knowledge bases in database."""
    engine = create_engine(config.DATABASE_URL)
    
    with engine.connect() as conn:
        # OpenAI knowledge base
        if openai_vector_store_id:
            print("\n📝 Configuring OpenAI knowledge base...")
            result = conn.execute(
                text("""
                    INSERT INTO knowledge_bases (tenant_id, name, description, provider, provider_config, is_active)
                    VALUES (:tenant_id, 'openai_file_kb', 'OpenAI File Search Knowledge Base', 'openai_file', 
                            jsonb_build_object('vector_store_id', :vector_store_id), TRUE)
                    ON CONFLICT (tenant_id, name) DO UPDATE SET
                        provider_config = jsonb_build_object('vector_store_id', :vector_store_id),
                        is_active = TRUE
                    RETURNING id, name
                """),
                {
                    "tenant_id": openai_tenant_id,
                    "vector_store_id": openai_vector_store_id
                }
            ).fetchone()
            if result:
                print(f"✅ OpenAI KB configured: {result[1]}")
        
        # Gemini knowledge base
        if gemini_store_name:
            print("\n📝 Configuring Gemini knowledge base...")
            result = conn.execute(
                text("""
                    INSERT INTO knowledge_bases (tenant_id, name, description, provider, provider_config, is_active)
                    VALUES (:tenant_id, 'gemini_file_kb', 'Gemini File Search Knowledge Base', 'gemini_file',
                            jsonb_build_object('file_search_store_name', :store_name), TRUE)
                    ON CONFLICT (tenant_id, name) DO UPDATE SET
                        provider_config = jsonb_build_object('file_search_store_name', :store_name),
                        is_active = TRUE
                    RETURNING id, name
                """),
                {
                    "tenant_id": gemini_tenant_id,
                    "store_name": gemini_store_name
                }
            ).fetchone()
            if result:
                print(f"✅ Gemini KB configured: {result[1]}")
        
        conn.commit()

def create_and_enable_tools(openai_tenant_id, gemini_tenant_id):
    """Create and enable file search tools."""
    engine = create_engine(config.DATABASE_URL)
    
    with engine.connect() as conn:
        # OpenAI file search tool
        print("\n🔧 Creating OpenAI file search tool...")
        conn.execute(
            text("""
                INSERT INTO tools (name, description, provider, parameters_schema, implementation_ref, is_global)
                VALUES (
                    'openai_file_search',
                    'Search documents using OpenAI file search',
                    'openai_file',
                    '{
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "The search query text"
                            }
                        },
                        "required": ["query"]
                    }'::jsonb,
                    '{"kb_name": "openai_file_kb"}'::jsonb,
                    TRUE
                )
                ON CONFLICT (name) DO UPDATE SET
                    description = EXCLUDED.description,
                    parameters_schema = EXCLUDED.parameters_schema,
                    implementation_ref = EXCLUDED.implementation_ref
            """)
        )
        
        # Enable for OpenAI tenant
        conn.execute(
            text("""
                INSERT INTO tenant_tool_policies (tenant_id, tool_id, is_enabled)
                SELECT :tenant_id, t.id, TRUE
                FROM tools t
                WHERE t.name = 'openai_file_search'
                ON CONFLICT (tenant_id, tool_id) DO UPDATE SET is_enabled = TRUE
            """),
            {"tenant_id": openai_tenant_id}
        )
        print("✅ OpenAI file search tool enabled")
        
        # Gemini file search tool
        print("\n🔧 Creating Gemini file search tool...")
        conn.execute(
            text("""
                INSERT INTO tools (name, description, provider, parameters_schema, implementation_ref, is_global)
                VALUES (
                    'gemini_file_search',
                    'Search documents using Gemini file search',
                    'gemini_file',
                    '{
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "The search query text"
                            }
                        },
                        "required": ["query"]
                    }'::jsonb,
                    '{"kb_name": "gemini_file_kb"}'::jsonb,
                    TRUE
                )
                ON CONFLICT (name) DO UPDATE SET
                    description = EXCLUDED.description,
                    parameters_schema = EXCLUDED.parameters_schema,
                    implementation_ref = EXCLUDED.implementation_ref
            """)
        )
        
        # Enable for Gemini tenant
        conn.execute(
            text("""
                INSERT INTO tenant_tool_policies (tenant_id, tool_id, is_enabled)
                SELECT :tenant_id, t.id, TRUE
                FROM tools t
                WHERE t.name = 'gemini_file_search'
                ON CONFLICT (tenant_id, tool_id) DO UPDATE SET is_enabled = TRUE
            """),
            {"tenant_id": gemini_tenant_id}
        )
        print("✅ Gemini file search tool enabled")
        
        conn.commit()

async def main():
    # Get tenant IDs
    engine = create_engine(config.DATABASE_URL)
    with engine.connect() as conn:
        openai_tenant_result = conn.execute(
            text("SELECT id FROM tenants WHERE slug = 'test-company' LIMIT 1")
        ).fetchone()
        gemini_tenant_result = conn.execute(
            text("SELECT id FROM tenants WHERE slug = 'test-company-gemini' LIMIT 1")
        ).fetchone()
    
    if not openai_tenant_result or not gemini_tenant_result:
        print("❌ Tenants not found. Please create test tenants first.")
        return
    
    openai_tenant_id = str(openai_tenant_result[0])
    gemini_tenant_id = str(gemini_tenant_result[0])
    
    print("🚀 Setting up file search knowledge bases...\n")
    print(f"OpenAI Tenant: {openai_tenant_id[:8]}...")
    print(f"Gemini Tenant: {gemini_tenant_id[:8]}...\n")
    
    # Setup OpenAI (synchronous)
    openai_vector_store_id = setup_openai_file_search(openai_tenant_id)
    
    # Setup Gemini (synchronous)
    gemini_store_name = setup_gemini_file_search(gemini_tenant_id)
    
    # Configure in database
    if openai_vector_store_id or gemini_store_name:
        configure_knowledge_bases(
            openai_tenant_id, 
            gemini_tenant_id, 
            openai_vector_store_id, 
            gemini_store_name
        )
    
    # Create and enable tools
    create_and_enable_tools(openai_tenant_id, gemini_tenant_id)
    
    print("\n✅ File search knowledge bases setup complete!")
    print("\n📋 Summary:")
    if openai_vector_store_id:
        print(f"  OpenAI Vector Store: {openai_vector_store_id}")
    if gemini_store_name:
        print(f"  Gemini File Search Store: {gemini_store_name}")

if __name__ == "__main__":
    asyncio.run(main())

