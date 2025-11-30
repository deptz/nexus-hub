#!/usr/bin/env python3
"""Test script for agentic API endpoints."""

import requests
import json
import sys
import time
from typing import Optional, Dict, Any

BASE_URL = "http://localhost:8000"


def test_health():
    """Test health endpoint."""
    print("\n" + "="*60)
    print("TEST 1: Health Check")
    print("="*60)
    try:
        response = requests.get(f"{BASE_URL}/health", timeout=5)
        print(f"Status: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2)}")
        assert response.status_code == 200
        assert response.json().get("status") == "ok"
        print("✅ Health check passed")
        return True
    except Exception as e:
        print(f"❌ Health check failed: {e}")
        return False


def test_openapi_docs():
    """Test OpenAPI docs endpoint."""
    print("\n" + "="*60)
    print("TEST 2: OpenAPI Documentation")
    print("="*60)
    try:
        response = requests.get(f"{BASE_URL}/docs", timeout=5)
        print(f"Status: {response.status_code}")
        assert response.status_code == 200
        print("✅ OpenAPI docs accessible")
        
        # Check if new endpoints are in OpenAPI spec
        response = requests.get(f"{BASE_URL}/openapi.json", timeout=5)
        spec = response.json()
        paths = spec.get("paths", {})
        
        # Check for new endpoints
        new_endpoints = [
            "/plans/{plan_id}",
            "/plans/{plan_id}/refine",
            "/tasks",
            "/tasks/{task_id}",
            "/tasks/{task_id}/resume",
            "/tasks/{task_id}/cancel",
        ]
        
        found_endpoints = []
        for endpoint in new_endpoints:
            if endpoint in paths:
                found_endpoints.append(endpoint)
                print(f"  ✓ Found endpoint: {endpoint}")
        
        if len(found_endpoints) == len(new_endpoints):
            print(f"✅ All {len(new_endpoints)} new endpoints registered")
        else:
            missing = set(new_endpoints) - set(found_endpoints)
            print(f"⚠️  Missing endpoints: {missing}")
        
        return True
    except Exception as e:
        print(f"❌ OpenAPI docs test failed: {e}")
        return False


def test_plans_endpoint_without_auth():
    """Test plans endpoint without authentication (should fail)."""
    print("\n" + "="*60)
    print("TEST 3: Plans Endpoint (No Auth - Should Fail)")
    print("="*60)
    try:
        response = requests.get(f"{BASE_URL}/plans/test-plan-id", timeout=5)
        print(f"Status: {response.status_code}")
        assert response.status_code == 401
        print("✅ Correctly requires authentication")
        return True
    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False


def test_tasks_endpoint_without_auth():
    """Test tasks endpoint without authentication (should fail)."""
    print("\n" + "="*60)
    print("TEST 4: Tasks Endpoint (No Auth - Should Fail)")
    print("="*60)
    try:
        response = requests.get(f"{BASE_URL}/tasks", timeout=5)
        print(f"Status: {response.status_code}")
        assert response.status_code == 401
        print("✅ Correctly requires authentication")
        return True
    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False


def test_endpoint_structure():
    """Test that endpoints have correct structure."""
    print("\n" + "="*60)
    print("TEST 5: Endpoint Structure Validation")
    print("="*60)
    try:
        response = requests.get(f"{BASE_URL}/openapi.json", timeout=5)
        spec = response.json()
        paths = spec.get("paths", {})
        
        # Check plans endpoints
        plan_get = paths.get("/plans/{plan_id}", {}).get("get")
        if plan_get:
            print("✅ GET /plans/{plan_id} endpoint exists")
            assert "parameters" in plan_get
            assert "responses" in plan_get
        else:
            print("❌ GET /plans/{plan_id} endpoint missing")
            return False
        
        plan_refine = paths.get("/plans/{plan_id}/refine", {}).get("post")
        if plan_refine:
            print("✅ POST /plans/{plan_id}/refine endpoint exists")
            assert "requestBody" in plan_refine
        else:
            print("❌ POST /plans/{plan_id}/refine endpoint missing")
            return False
        
        # Check tasks endpoints
        tasks_post = paths.get("/tasks", {}).get("post")
        if tasks_post:
            print("✅ POST /tasks endpoint exists")
            assert "requestBody" in tasks_post
        else:
            print("❌ POST /tasks endpoint missing")
            return False
        
        tasks_get = paths.get("/tasks/{task_id}", {}).get("get")
        if tasks_get:
            print("✅ GET /tasks/{task_id} endpoint exists")
        else:
            print("❌ GET /tasks/{task_id} endpoint missing")
            return False
        
        tasks_resume = paths.get("/tasks/{task_id}/resume", {}).get("post")
        if tasks_resume:
            print("✅ POST /tasks/{task_id}/resume endpoint exists")
        else:
            print("❌ POST /tasks/{task_id}/resume endpoint missing")
            return False
        
        tasks_cancel = paths.get("/tasks/{task_id}/cancel", {}).get("post")
        if tasks_cancel:
            print("✅ POST /tasks/{task_id}/cancel endpoint exists")
        else:
            print("❌ POST /tasks/{task_id}/cancel endpoint missing")
            return False
        
        print("✅ All endpoint structures validated")
        return True
    except Exception as e:
        print(f"❌ Endpoint structure test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_server_imports():
    """Test that server can import all required modules."""
    print("\n" + "="*60)
    print("TEST 6: Server Module Imports")
    print("="*60)
    try:
        import sys
        sys.path.insert(0, "/Users/pujitriwibowo/Documents/works/ai-spinoff")
        
        # Test critical imports
        from app.services.agentic_planner import create_plan, refine_plan
        print("✅ agentic_planner imports successful")
        
        from app.services.agentic_task_manager import (
            create_task, get_task, update_task_state, 
            resume_task, cancel_task, list_tasks
        )
        print("✅ agentic_task_manager imports successful")
        
        from app.services.agentic_reflector import reflect_on_execution, get_similar_insights
        print("✅ agentic_reflector imports successful")
        
        from app.api.routers import plans, tasks
        print("✅ API routers imports successful")
        
        from app.models.tenant import TenantContext
        print("✅ TenantContext model import successful")
        
        # Verify TenantContext has new fields
        ctx = TenantContext(
            tenant_id="test",
            llm_provider="openai",
            llm_model="gpt-4o-mini",
            allowed_tools=[],
            kb_configs={},
            mcp_configs={},
            prompt_profile={},
            isolation_mode="shared_db"
        )
        assert hasattr(ctx, 'max_tool_steps')
        assert hasattr(ctx, 'planning_enabled')
        assert hasattr(ctx, 'plan_timeout_seconds')
        print("✅ TenantContext has all new planning fields")
        print(f"   - max_tool_steps: {ctx.max_tool_steps}")
        print(f"   - planning_enabled: {ctx.planning_enabled}")
        print(f"   - plan_timeout_seconds: {ctx.plan_timeout_seconds}")
        
        return True
    except Exception as e:
        print(f"❌ Import test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("AGENTIC API TEST SUITE")
    print("="*60)
    print(f"Testing server at: {BASE_URL}")
    print(f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Wait for server to be ready
    print("\nWaiting for server to be ready...")
    for i in range(10):
        try:
            response = requests.get(f"{BASE_URL}/health", timeout=2)
            if response.status_code == 200:
                print("✅ Server is ready")
                break
        except:
            if i < 9:
                print(f"  Waiting... ({i+1}/10)")
                time.sleep(1)
            else:
                print("❌ Server is not responding")
                print("   Make sure the server is running:")
                print("   python -m uvicorn app.main:app --host 0.0.0.0 --port 8000")
                return False
    
    tests = [
        test_health,
        test_openapi_docs,
        test_plans_endpoint_without_auth,
        test_tasks_endpoint_without_auth,
        test_endpoint_structure,
        test_server_imports,
    ]
    
    results = []
    for test in tests:
        try:
            result = test()
            results.append(result)
        except Exception as e:
            print(f"❌ Test {test.__name__} crashed: {e}")
            import traceback
            traceback.print_exc()
            results.append(False)
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    passed = sum(results)
    total = len(results)
    print(f"Passed: {passed}/{total}")
    
    if passed == total:
        print("✅ All tests passed!")
        return 0
    else:
        print(f"❌ {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())

