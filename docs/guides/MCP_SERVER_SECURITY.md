# MCP Server Security Requirements

This document outlines **mandatory security requirements** for tenant MCP servers that integrate with the multi-tenant chatbot platform.

## Overview

When your MCP server receives tool execution requests from the platform, it must enforce strict tenant and user isolation. The platform sends immutable context headers that come from authentication - **never trust tool arguments for user/tenant identification**.

## Mandatory Requirements

### 1. Validate Context Headers (MANDATORY)

Your MCP server **MUST** validate and use the following headers for all tool calls:

- **`X-Tenant-ID`**: Tenant identifier (from API key authentication)
- **`X-User-External-ID`**: User external identifier (from authenticated message)
- **`X-Conversation-ID`**: Conversation identifier (optional, for audit)

**Implementation:**
```python
# Example (Python/FastAPI)
tenant_id = request.headers.get("X-Tenant-ID")
user_external_id = request.headers.get("X-User-External-ID")

if not tenant_id or not user_external_id:
    raise HTTPException(403, "Missing required context headers")

# Validate tenant_id matches your server's expected tenant
if tenant_id != expected_tenant_id:
    raise HTTPException(403, "Tenant ID mismatch")
```

### 2. Override Tool Arguments with Header Context (MANDATORY)

**Never trust user-scoped parameters from tool arguments.** The platform removes user-scoped parameters (like `customer_id`, `user_id`) from tool arguments before sending them to your MCP server. Your server must resolve these from the `X-User-External-ID` header.

**Implementation:**
```python
# Example: get_invoice tool
def get_invoice(invoice_id: str, request: Request):
    # Get user context from header (authoritative)
    user_external_id = request.headers.get("X-User-External-ID")
    tenant_id = request.headers.get("X-Tenant-ID")
    
    # Resolve customer_id from user_external_id
    customer_id = resolve_customer_id(user_external_id, tenant_id)
    
    # IGNORE customer_id if provided in arguments (platform already removed it)
    # Use resolved customer_id instead
    invoice = fetch_invoice(customer_id, invoice_id)
    
    # Verify invoice belongs to this customer
    if invoice.customer_id != customer_id:
        raise HTTPException(403, "Unauthorized access")
    
    return invoice
```

### 3. Per-User Authentication (Recommended)

Implement per-user authentication to ensure the `X-User-External-ID` header corresponds to an authenticated user in your system.

**Implementation:**
```python
# Validate user exists and is active
user = get_user_by_external_id(user_external_id, tenant_id)
if not user or not user.is_active:
    raise HTTPException(403, "User not found or inactive")

# Optional: Validate user has permission for this tenant
if user.tenant_id != tenant_id:
    raise HTTPException(403, "User does not belong to tenant")
```

### 4. Least Privilege Tool Scoping

Each tool should only access data that the authenticated user is authorized to access. Never return data from other users or tenants.

**Implementation:**
```python
# BAD: Returns all invoices
def get_invoices():
    return Invoice.query.all()  # ❌ No user scoping

# GOOD: Scoped to authenticated user
def get_invoices(request: Request):
    user_external_id = request.headers.get("X-User-External-ID")
    customer_id = resolve_customer_id(user_external_id)
    return Invoice.query.filter_by(customer_id=customer_id).all()  # ✅ User-scoped
```

### 5. Security-Conscious Error Handling

Never expose sensitive information in error messages. Use generic errors for users, log detailed errors server-side.

**Implementation:**
```python
try:
    invoice = fetch_invoice(customer_id, invoice_id)
except InvoiceNotFound:
    # Generic error to user
    raise HTTPException(404, "Invoice not found")
except PermissionDenied:
    # Generic error to user
    raise HTTPException(403, "Unable to retrieve data")
except Exception as e:
    # Log detailed error server-side
    logger.error(f"Error fetching invoice: {e}", exc_info=True)
    # Generic error to user
    raise HTTPException(500, "Unable to retrieve data")
```

### 6. Audit Logging

Log all tool executions with context for security auditing:

- Tenant ID
- User External ID
- Tool name
- Arguments (sanitized)
- Status (success/failure)
- Timestamp

**Implementation:**
```python
def log_tool_execution(tenant_id, user_external_id, tool_name, args, status):
    audit_log = {
        "tenant_id": tenant_id,
        "user_external_id": user_external_id,
        "tool_name": tool_name,
        "arguments": sanitize_for_logging(args),  # Remove sensitive data
        "status": status,
        "timestamp": datetime.utcnow().isoformat(),
    }
    # Write to audit log (database, file, etc.)
    write_audit_log(audit_log)
```

## Security Best Practices

### Never Trust Tool Arguments for User/Tenant Context

```python
# ❌ BAD: Trusts tool arguments
def get_invoice(customer_id: str):  # Can be spoofed!
    return Invoice.query.filter_by(customer_id=customer_id).first()

# ✅ GOOD: Uses header context
def get_invoice(invoice_id: str, request: Request):
    user_external_id = request.headers.get("X-User-External-ID")
    customer_id = resolve_customer_id(user_external_id)  # From header
    return Invoice.query.filter_by(customer_id=customer_id, id=invoice_id).first()
```

### Validate All Inputs

```python
# Validate invoice_id format
if not invoice_id or not re.match(r'^INV-\d+$', invoice_id):
    raise HTTPException(400, "Invalid invoice ID format")

# Validate against SQL injection
if any(char in invoice_id for char in ["'", ";", "--", "/*"]):
    raise HTTPException(400, "Invalid characters in invoice ID")
```

### Rate Limiting

Implement rate limiting per user to prevent abuse:

```python
from functools import wraps

def rate_limit_per_user(max_calls=100, window_seconds=60):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            user_external_id = kwargs.get("user_external_id")
            if is_rate_limited(user_external_id, max_calls, window_seconds):
                raise HTTPException(429, "Rate limit exceeded")
            return func(*args, **kwargs)
        return wrapper
    return decorator
```

## Testing Your MCP Server

Test your server with the following scenarios:

1. **Valid Request**: Tool call with correct headers and arguments
2. **Missing Headers**: Request without `X-Tenant-ID` or `X-User-External-ID`
3. **Wrong Tenant**: Request with `X-Tenant-ID` that doesn't match your server
4. **Cross-User Access**: Attempt to access another user's data via tool arguments
5. **Invalid User**: Request with `X-User-External-ID` that doesn't exist
6. **SQL Injection**: Attempt SQL injection via tool arguments
7. **Rate Limiting**: Verify rate limiting works per user

## Example: Complete Secure Tool Implementation

```python
from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel
import re

app = FastAPI()

class InvoiceRequest(BaseModel):
    invoice_id: str

@app.post("/tools/call")
async def execute_tool(request: Request, tool_request: dict):
    # 1. Validate headers (MANDATORY)
    tenant_id = request.headers.get("X-Tenant-ID")
    user_external_id = request.headers.get("X-User-External-ID")
    
    if not tenant_id or not user_external_id:
        raise HTTPException(403, "Missing required context headers")
    
    # 2. Validate tenant
    if tenant_id != expected_tenant_id:
        raise HTTPException(403, "Tenant ID mismatch")
    
    # 3. Resolve user context
    customer_id = resolve_customer_id(user_external_id, tenant_id)
    if not customer_id:
        raise HTTPException(403, "User not found")
    
    # 4. Get tool name and arguments
    tool_name = tool_request.get("name")
    args = tool_request.get("arguments", {})
    
    # 5. Execute tool with user context
    if tool_name == "get_invoice":
        invoice_id = args.get("invoice_id")
        
        # Validate input
        if not invoice_id or not re.match(r'^INV-\d+$', invoice_id):
            raise HTTPException(400, "Invalid invoice ID")
        
        # Fetch invoice (scoped to customer_id from header)
        invoice = fetch_invoice(customer_id, invoice_id)
        
        # 6. Audit log
        log_tool_execution(
            tenant_id=tenant_id,
            user_external_id=user_external_id,
            tool_name=tool_name,
            args={"invoice_id": invoice_id},  # Sanitized
            status="success"
        )
        
        return {"result": invoice}
    
    raise HTTPException(404, "Tool not found")
```

## Summary

**Key Principles:**
1. ✅ Always validate `X-Tenant-ID` and `X-User-External-ID` headers
2. ✅ Never trust user-scoped parameters from tool arguments
3. ✅ Resolve user context from headers, not arguments
4. ✅ Scope all data access to authenticated user
5. ✅ Use generic error messages, log detailed errors server-side
6. ✅ Implement audit logging for all tool executions

**Remember:** The platform removes user-scoped parameters before sending requests. Your server must resolve user context from headers, not from tool arguments.
