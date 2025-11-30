# Agentic AI Message Flow

## Overview

This document explains how an inbound message triggers the agentic AI system, from message receipt through planning, execution, reflection, and response generation.

## Entry Points

Messages can enter the system through multiple channels:

1. **REST API**: `POST /messages/inbound`
2. **Webhooks**: `POST /webhooks/telegram` (and other webhook endpoints)
3. **Async Queue**: Messages can be queued for background processing

All entry points eventually call `handle_inbound_message_sync()` in `app/api/utils.py`.

## Complete Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. MESSAGE RECEIVED                                               │
│    POST /messages/inbound or /webhooks/telegram                   │
│    → CanonicalMessage object created                              │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 2. AUTHENTICATION & VALIDATION                                    │
│    - Verify API key                                               │
│    - Validate tenant access                                      │
│    - Validate message structure                                   │
│    - Check rate limits                                            │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 3. TENANT CONTEXT LOADING                                        │
│    get_tenant_context(tenant_id)                                  │
│    → Loads:                                                       │
│      - LLM provider & model                                      │
│      - Planning config (planning_enabled, max_tool_steps)        │
│      - Prompt profile                                             │
│      - Allowed tools                                              │
│      - Knowledge bases                                            │
│      - MCP servers                                                │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 4. CONVERSATION MANAGEMENT                                        │
│    - Get or create conversation                                  │
│    - Persist inbound message to database                         │
│    - Load conversation history (token-based truncation)           │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 5. PLANNING PHASE (if planning_enabled = true)                   │
│                                                                   │
│    ┌─────────────────────────────────────────────────────────┐ │
│    │ create_plan()                                            │ │
│    │   - Extract goal from message.content.text                │ │
│    │   - Get available tools                                  │ │
│    │   - Query past insights (get_similar_insights)           │ │
│    │   - Call LLM with PLANNING_PROMPT                         │ │
│    │   - Parse JSON plan response                              │ │
│    │   - Validate plan structure                               │ │
│    │   - Store plan in agentic_plans table                    │ │
│    │   - Return plan_id, steps, complexity                    │ │
│    └─────────────────────────────────────────────────────────┘ │
│                            ↓                                     │
│    ┌─────────────────────────────────────────────────────────┐ │
│    │ Plan Created Successfully                                │ │
│    │   - Log "plan_created" event                             │ │
│    │   - Record metrics (plans_created_total)                  │ │
│    │   - Update plan status to "executing"                    │ │
│    └─────────────────────────────────────────────────────────┘ │
│                            ↓                                     │
│    ┌─────────────────────────────────────────────────────────┐ │
│    │ create_task()                                            │ │
│    │   - Create task in agentic_tasks table                   │ │
│    │   - Link to plan_id and conversation_id                  │ │
│    │   - Set status to "planning" or "executing"              │ │
│    │   - Return task_id                                       │ │
│    └─────────────────────────────────────────────────────────┘ │
│                                                                   │
│    If planning fails:                                             │
│    → Log error, record metrics, continue with reactive execution │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 6. PROMPT BUILDING                                                │
│    build_messages(tenant_ctx, history, message)                 │
│                                                                   │
│    Layered Prompt Stack:                                         │
│    1. CORE_GUARDRAILS_PROMPT (immutable)                         │
│    2. GLOBAL_SYSTEM_PROMPT                                       │
│    3. Tenant custom prompt (if exists)                           │
│    4. Conversation history (token-truncated)                     │
│    5. Current user message                                       │
│                                                                   │
│    If plan exists:                                               │
│    → Inject plan context into system message:                    │
│       "EXECUTION PLAN:                                            │
│        Goal: [goal]                                              │
│        Steps: [step descriptions]                                │
│        Follow this plan when executing tools..."                  │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 7. TOOL EXECUTION LOOP (up to max_tool_steps iterations)         │
│                                                                   │
│    for step in range(max_tool_steps):                            │
│                                                                   │
│      ┌───────────────────────────────────────────────────────┐   │
│      │ Call LLM with messages + tools                       │   │
│      │   - Include plan context (if plan exists)             │   │
│      │   - Include conversation history                      │   │
│      │   - Include available tools                           │   │
│      └───────────────────────────────────────────────────────┘   │
│                        ↓                                           │
│      ┌───────────────────────────────────────────────────────┐   │
│      │ LLM Response                                           │   │
│      │   - Extract response_text                              │   │
│      │   - Extract tool_calls (if any)                        │   │
│      │   - Calculate cost & latency                           │   │
│      │   - Log LLM trace                                      │   │
│      └───────────────────────────────────────────────────────┘   │
│                        ↓                                           │
│      ┌───────────────────────────────────────────────────────┐   │
│      │ If tool_calls exist:                                   │   │
│      │   For each tool_call:                                  │   │
│      │     - Find tool definition                             │   │
│      │     - Execute tool (execute_tool_call)                 │   │
│      │     - Log tool call                                    │   │
│      │     - Calculate tool cost                              │   │
│      │     - Record metrics                                   │   │
│      │     - Add tool result to messages                      │   │
│      │     - Track in execution_results[]                    │   │
│      │                                                         │   │
│      │   If task_id exists:                                   │   │
│      │     - update_task_state()                              │   │
│      │       * Update current_step                           │   │
│      │       * Update state with step_results                 │   │
│      │                                                         │   │
│      │ If no tool_calls:                                      │   │
│      │   → Break loop (execution complete)                    │   │
│      └───────────────────────────────────────────────────────┘   │
│                                                                   │
│    execution_results[] contains:                                  │
│      - step_number                                               │
│      - tool_name                                                  │
│      - status (success/failure)                                   │
│      - result/error                                               │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 8. PLAN COMPLETION & REFLECTION                                   │
│                                                                   │
│    If plan_id exists:                                             │
│                                                                   │
│      ┌───────────────────────────────────────────────────────┐   │
│      │ Update Plan Status                                     │   │
│      │   - Set status to "completed" or "failed"             │   │
│      │   - Log "plan_execution_completed" event               │   │
│      └───────────────────────────────────────────────────────┘   │
│                        ↓                                           │
│      ┌───────────────────────────────────────────────────────┐   │
│      │ reflect_on_execution()                                │   │
│      │   - Analyze execution_results                         │   │
│      │   - Call LLM to generate insights                     │   │
│      │   - Store insights in agentic_insights table          │   │
│      │   - Link to plan_id and task_id                       │   │
│      │   - Insights used for future plan generation          │   │
│      └───────────────────────────────────────────────────────┘   │
│                        ↓                                           │
│      ┌───────────────────────────────────────────────────────┐   │
│      │ complete_task()                                        │   │
│      │   - Update task status to "completed" or "failed"       │   │
│      │   - Set completed_at timestamp                         │   │
│      │   - Store final_state with execution_results           │   │
│      └───────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 9. RESPONSE GENERATION                                            │
│    - Create outbound CanonicalMessage                            │
│    - Include plan_id and task_id in metadata (if exists)        │
│    - Persist to database                                         │
│    - Log "outbound_message" event                                │
│    - Update conversation stats                                   │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 10. RETURN RESPONSE                                               │
│     InboundMessageResponse:                                       │
│       - status: "success"                                         │
│       - message: {outbound message details}                     │
│       - latency_ms: total processing time                        │
│       - tool_calls_executed: count                                │
│       - metadata: {plan_id, task_id} (if exists)               │
└─────────────────────────────────────────────────────────────────┘
```

## Key Components

### 1. Planning Service (`app/services/agentic_planner.py`)

**Function**: `create_plan()`

- **Input**: Goal (message text), available tools, conversation context
- **Process**:
  1. Query past insights for similar goals
  2. Build planning prompt with tools list and insights
  3. Call LLM (typically cheaper model like `gpt-4o-mini`)
  4. Parse JSON plan response
  5. Validate plan structure
  6. Store in `agentic_plans` table
- **Output**: Plan with steps, dependencies, success criteria

**Planning Prompt Structure**:
```
You are an AI planning assistant. Break down the user's goal into steps:
- Identify tools needed for each step
- Define dependencies between steps
- Specify success criteria
- Estimate complexity
```

### 2. Task Management (`app/services/agentic_task_manager.py`)

**Functions**:
- `create_task()`: Create task for long-running operations
- `update_task_state()`: Update progress after each tool execution
- `complete_task()`: Mark task as completed with final state
- `resume_task()`: Resume interrupted tasks

**Purpose**: Enable state persistence for operations that may need to be resumed.

### 3. Tool Execution Loop

**Location**: `app/api/utils.py` lines 366-780

**Flow**:
1. Loop up to `max_tool_steps` (default: 10, configurable per tenant)
2. Call LLM with current messages + tools
3. If LLM returns tool calls:
   - Execute each tool
   - Add results to messages
   - Track in `execution_results[]`
   - Update task state (if task exists)
4. If no tool calls:
   - Break loop
   - Use final response text

**Tool Execution**:
- `execute_tool_call()` in `app/services/tool_execution_engine.py`
- Supports multiple providers: RAG, OpenAI, Gemini, MCP
- Logs all tool calls for observability
- Calculates costs per tool

### 4. Reflection Service (`app/services/agentic_reflector.py`)

**Function**: `reflect_on_execution()`

- **Input**: Plan ID, task ID, execution results, final outcome
- **Process**:
  1. Analyze execution results
  2. Call LLM to generate insights
  3. Store insights in `agentic_insights` table
- **Output**: Insights and recommendations for future planning

**Purpose**: Learn from past executions to improve future plans.

## Configuration

### Tenant-Level Configuration

Stored in `tenants` table:
- `planning_enabled` (BOOLEAN, default: TRUE)
- `max_tool_steps` (INTEGER, default: 10)
- `plan_timeout_seconds` (INTEGER, default: 300)

### How Planning is Triggered

```python
# In handle_inbound_message_sync()
if tenant_ctx.planning_enabled:
    plan = await create_plan(...)
    # Plan is created and stored
    # Plan context is injected into LLM messages
    # Task is created for state tracking
```

### Fallback Behavior

If planning fails:
- Error is logged
- Metrics are recorded
- System continues with **reactive execution** (no plan)
- LLM still receives tools and can call them reactively

## Example Flow

**User Message**: "Research the latest AI trends and create a summary"

1. **Planning Phase**:
   - Goal extracted: "Research the latest AI trends and create a summary"
   - Plan generated:
     ```
     Step 1: Search for recent AI trend articles (tool: search)
     Step 2: Analyze and extract key trends (tool: analyze)
     Step 3: Generate summary document (tool: generate_document)
     ```
   - Plan stored with `plan_id: "abc-123"`
   - Task created with `task_id: "xyz-789"`

2. **Execution Phase**:
   - LLM receives plan context in system message
   - LLM calls `search` tool → Results added to messages
   - Task state updated: `current_step: 1`
   - LLM calls `analyze` tool → Results added to messages
   - Task state updated: `current_step: 2`
   - LLM calls `generate_document` tool → Summary created
   - Task state updated: `current_step: 3`
   - LLM returns final response text

3. **Reflection Phase**:
   - Execution results analyzed
   - Insights generated: "Search tool returned 10 articles, analysis took 2s, summary generation successful"
   - Insights stored for future similar requests

4. **Completion**:
   - Plan status: "completed"
   - Task status: "completed"
   - Response returned with `plan_id` and `task_id` in metadata

## Observability

All steps are logged and tracked:

- **Events**: `plan_created`, `plan_execution_completed`, `task_created`, etc.
- **Metrics**: `plans_created_total`, `plan_execution_duration`, `tasks_created_total`
- **Traces**: LLM traces include `plan_id` in payload
- **Tool Calls**: All tool executions logged with results

## API Response

The response includes agentic metadata:

```json
{
  "status": "success",
  "message": {
    "id": "...",
    "content": {"text": "Here's your summary..."},
    "metadata": {
      "plan_id": "abc-123",
      "task_id": "xyz-789"
    }
  },
  "latency_ms": 5000,
  "tool_calls_executed": 3
}
```

## Benefits of Agentic Approach

1. **Proactive Planning**: System thinks ahead before executing
2. **State Persistence**: Long-running tasks can be resumed
3. **Learning**: System learns from past executions
4. **Observability**: Full visibility into planning and execution
5. **Flexibility**: Falls back to reactive execution if planning fails

