# System Architecture Diagram

This document contains a visual representation of the Nexus Hub system architecture.

## Architecture Overview

The system follows a **microservices architecture** with clear separation of concerns:

- **Nexus Hub Service**: 
  - **FastAPI Application Layer**: HTTP API endpoints (e.g., `POST /messages/inbound`), middleware, authentication, rate limiting
  - **Message Processing Core**: Business logic for message processing, LLM orchestration, and tool execution (separate from API layer)
- **Channel Adapter Services**: Separate services that handle channel-specific protocols and convert to/from the canonical message format
  - **Telegram Adapter**: Currently implemented for testing/development purposes only
  - **Web/API Adapter**: Direct API clients
  - **Other Adapters**: Slack, Email, etc. (future implementations)

All channel adapters communicate with the orchestrator via the standard `POST /messages/inbound` API endpoint (part of the FastAPI application layer), which then delegates to the message processing core. This ensures the orchestrator remains channel-agnostic and the API layer is separated from core business logic.

## High-Level System Flow

```mermaid
graph TB
    subgraph "External Channels"
        TG[Telegram Bot API]
        WEB[Web/API Clients]
        SLACK[Slack API]
        EMAIL[Email Service]
    end

    subgraph "Channel Adapters (Separate Services)"
        TG_ADAPTER[Telegram Adapter Service<br/>Testing/Development Only]
        WEB_ADAPTER[Web Adapter]
        SLACK_ADAPTER[Slack Adapter]
        EMAIL_ADAPTER[Email Adapter]
    end

    subgraph "Nexus Hub Service"
        subgraph "FastAPI Application"
            API[FastAPI Main App]
            INBOUND[POST /messages/inbound<br/>API Endpoint]
            MW[Middleware Layer<br/>- Request ID<br/>- Logging<br/>- Timeout<br/>- CORS<br/>- Size Limits]
            AUTH[Auth Middleware<br/>API Key Verification]
            RL[Rate Limiter<br/>Redis/In-Memory]
        end

        subgraph "Message Processing Core"
            VALIDATE[Message Validator]
            TENANT_CTX[Tenant Context Service]
            CONV[Conversation Manager]
            MSG_PERSIST[Message Persistence]
            PROMPT_BUILDER[Prompt Builder<br/>- Core Guardrails<br/>- Global System Prompt<br/>- Tenant Custom Prompt<br/>- Conversation History]
            TOOL_REG[Tool Registry<br/>- Get Allowed Tools]
            LLM_CALL[LLM Call Handler<br/>- OpenAI/Gemini<br/>- Retry Logic<br/>- Circuit Breaker<br/>- Timeout]
            TOOL_EXEC[Tool Execution Engine]
        end

        subgraph "Tool Providers"
            RAG[Internal RAG Client<br/>pgvector Semantic Search]
            OPENAI_FILE[OpenAI File Search<br/>Vector Stores]
            GEMINI_FILE[Gemini File Search<br/>Corpus-based]
            MCP[MCP Client<br/>HTTP/WebSocket<br/>JSON-RPC 2.0]
        end
    end

    subgraph "Infrastructure"
        DB[(PostgreSQL<br/>- RLS Enabled<br/>- pgvector)]
        REDIS[(Redis<br/>Rate Limiting<br/>Queue)]
        CB[Circuit Breakers<br/>- OpenAI<br/>- Gemini]
        METRICS[Prometheus Metrics]
        LOGGER[Event Logger]
    end

    subgraph "Output"
        OUTBOUND[Outbound Message]
        RESPONSE[Response to Channel]
    end

    %% External Channels to Adapters
    TG --> TG_ADAPTER
    WEB --> WEB_ADAPTER
    SLACK --> SLACK_ADAPTER
    EMAIL --> EMAIL_ADAPTER

    %% Adapters to Orchestrator API
    TG_ADAPTER -->|HTTP POST /messages/inbound| INBOUND
    WEB_ADAPTER -->|HTTP POST /messages/inbound| INBOUND
    SLACK_ADAPTER -->|HTTP POST /messages/inbound| INBOUND
    EMAIL_ADAPTER -->|HTTP POST /messages/inbound| INBOUND

    %% FastAPI Application Layer
    INBOUND --> API
    API --> MW
    MW --> AUTH
    AUTH --> RL
    RL --> INBOUND

    %% API Endpoint to Core Processing
    INBOUND --> VALIDATE

    %% Message Processing Core Flow
    VALIDATE --> TENANT_CTX
    TENANT_CTX --> CONV
    CONV --> MSG_PERSIST
    MSG_PERSIST --> PROMPT_BUILDER
    PROMPT_BUILDER --> TOOL_REG
    TOOL_REG --> LLM_CALL
    LLM_CALL --> TOOL_EXEC
    TOOL_EXEC --> RAG
    TOOL_EXEC --> OPENAI_FILE
    TOOL_EXEC --> GEMINI_FILE
    TOOL_EXEC --> MCP

    %% Tool Results Back
    RAG --> LLM_CALL
    OPENAI_FILE --> LLM_CALL
    GEMINI_FILE --> LLM_CALL
    MCP --> LLM_CALL

    %% Infrastructure Connections
    TENANT_CTX --> DB
    CONV --> DB
    MSG_PERSIST --> DB
    RL --> REDIS
    LLM_CALL --> CB
    LLM_CALL --> METRICS
    LLM_CALL --> LOGGER
    TOOL_EXEC --> LOGGER
    LOGGER --> DB

    %% Output Flow (Core to API)
    LLM_CALL --> OUTBOUND
    OUTBOUND --> MSG_PERSIST
    MSG_PERSIST --> INBOUND
    INBOUND --> RESPONSE
    RESPONSE --> TG_ADAPTER
    RESPONSE --> WEB_ADAPTER
    RESPONSE --> SLACK_ADAPTER
    RESPONSE --> EMAIL_ADAPTER
    TG_ADAPTER --> TG
    WEB_ADAPTER --> WEB
    SLACK_ADAPTER --> SLACK
    EMAIL_ADAPTER --> EMAIL

    style API fill:#e1f5ff
    style INBOUND fill:#e1f5ff
    style LLM_CALL fill:#fff4e1
    style TOOL_EXEC fill:#e8f5e9
    style DB fill:#f3e5f5
    style REDIS fill:#ffebee
    style TG_ADAPTER fill:#fff9c4
```

## Component Interaction Sequence

```mermaid
sequenceDiagram
    participant Channel as External Channel<br/>(Telegram, Web, etc.)
    participant Adapter as Channel Adapter Service<br/>(Telegram Adapter, etc.)
    participant FastAPI as FastAPI Application
    participant Endpoint as POST /messages/inbound<br/>API Endpoint
    participant Auth as Auth Middleware
    participant RL as Rate Limiter
    participant Core as Message Processing Core
    participant Validator as Message Validator
    participant TenantCtx as Tenant Context Service
    participant Conv as Conversation Manager
    participant Prompt as Prompt Builder
    participant ToolReg as Tool Registry
    participant LLM as LLM Adapter
    participant ToolExec as Tool Execution Engine
    participant Tool as Tool Provider
    participant DB as PostgreSQL
    participant Logger as Event Logger

    Channel->>Adapter: Webhook/Message
    Note over Adapter: Convert to CanonicalMessage
    Adapter->>Endpoint: HTTP POST /messages/inbound<br/>(CanonicalMessage + API Key)
    Endpoint->>FastAPI: Route Request
    FastAPI->>Auth: Verify API Key
    Auth->>RL: Check Rate Limit
    RL->>DB: Query/Update Rate Limits
    RL-->>FastAPI: Rate Limit OK
    FastAPI->>Endpoint: Request Authorized
    Endpoint->>Core: Process Message
    Core->>Validator: Validate Message
    Validator-->>Core: Validation OK
    Core->>TenantCtx: Load Tenant Context
    TenantCtx->>DB: Load Tenant Config, Tools, KBs, MCPs
    DB-->>TenantCtx: Tenant Context
    TenantCtx-->>Core: Tenant Context
    Core->>Conv: Get/Create Conversation
    Conv->>DB: Query/Create Conversation
    DB-->>Conv: Conversation ID
    Conv-->>Core: Conversation ID
    Core->>DB: Persist Inbound Message
    Core->>Prompt: Build Prompt Stack
    Prompt->>DB: Load Conversation History
    DB-->>Prompt: History
    Prompt-->>Core: LLM Messages
    Core->>ToolReg: Get Allowed Tools
    ToolReg-->>Core: Tool Definitions
    Core->>LLM: Call LLM with Tools
    LLM->>Tool: Execute Tool Call
    Tool->>ToolExec: Execute Tool
    ToolExec->>Tool: Call Provider Client
    Tool-->>ToolExec: Tool Result
    ToolExec-->>LLM: Tool Result
    LLM-->>Core: LLM Response
    Core->>DB: Store LLM Trace
    Core->>Logger: Log LLM Call
    Logger->>DB: Store Event
    Core->>DB: Persist Outbound Message
    Core->>Logger: Log Outbound Message
    Core-->>Endpoint: Outbound CanonicalMessage
    Endpoint-->>Adapter: HTTP Response<br/>Outbound CanonicalMessage
    Note over Adapter: Convert to Channel Format
    Adapter->>Channel: Send Response
```

## Data Flow Architecture

```mermaid
graph LR
    subgraph "Channel Layer"
        C1[Telegram]
        C2[Web/API]
        C3[Slack]
        C4[Email]
    end

    subgraph "Adapter Layer (Separate Services)"
        A1[Telegram Adapter<br/>Testing Only]
        A2[Web Adapter]
        A3[Slack Adapter]
        A4[Email Adapter]
    end

    subgraph "Orchestrator Service"
        subgraph "FastAPI Application Layer"
            API_EP[POST /messages/inbound<br/>API Endpoint]
        end

        subgraph "Message Processing Core"
            subgraph "Normalization Layer"
                N1[CanonicalMessage Format]
            end

            subgraph "Tenant Isolation Layer"
                T1[Tenant Context]
                T2[RLS Policies]
                T3[Tool Allow-List]
            end

            subgraph "Processing Layer"
                P1[Prompt Building]
                P2[LLM Orchestration]
                P3[Tool Execution]
            end

            subgraph "Tool Layer"
                TL1[Internal RAG]
                TL2[OpenAI File Search]
                TL3[Gemini File Search]
                TL4[MCP Tools]
            end

            subgraph "Output Layer"
                O1[Outbound CanonicalMessage]
            end
        end
    end

    subgraph "Observability Layer"
        OB1[Event Logs]
        OB2[Tool Call Logs]
        OB3[LLM Traces]
        OB4[Metrics]
    end

    C1 --> A1
    C2 --> A2
    C3 --> A3
    C4 --> A4
    A1 -->|HTTP POST| API_EP
    A2 -->|HTTP POST| API_EP
    A3 -->|HTTP POST| API_EP
    A4 -->|HTTP POST| API_EP
    API_EP --> N1
    N1 --> T1
    T1 --> T2
    T1 --> T3
    T2 --> P1
    T3 --> P2
    P1 --> P2
    P2 --> P3
    P3 --> TL1
    P3 --> TL2
    P3 --> TL3
    P3 --> TL4
    TL1 --> P2
    TL2 --> P2
    TL3 --> P2
    TL4 --> P2
    P2 --> O1
    O1 --> API_EP
    API_EP -->|HTTP Response| A1
    API_EP -->|HTTP Response| A2
    API_EP -->|HTTP Response| A3
    API_EP -->|HTTP Response| A4
    A1 --> C1
    A2 --> C2
    A3 --> C3
    A4 --> C4
    P2 --> OB1
    P3 --> OB2
    P2 --> OB3
    P2 --> OB4

    style API_EP fill:#e1f5ff
    style T1 fill:#e1f5ff
    style T2 fill:#e1f5ff
    style P2 fill:#fff4e1
    style OB1 fill:#e8f5e9
    style A1 fill:#fff9c4
```

## Infrastructure Components

```mermaid
graph TB
    subgraph "Application Layer"
        APP[FastAPI Application]
    end

    subgraph "Middleware Services"
        MW1[Request ID Middleware]
        MW2[Logging Middleware]
        MW3[Timeout Middleware]
        MW4[CORS Middleware]
        MW5[Size Limit Middleware]
    end

    subgraph "Security & Access Control"
        AUTH1[API Key Authentication]
        AUTH2[Tenant Access Verification]
        RLS[Row-Level Security]
    end

    subgraph "Resilience"
        CB1[OpenAI Circuit Breaker]
        CB2[Gemini Circuit Breaker]
        RETRY[Retry with Backoff]
        TIMEOUT[Request Timeout]
    end

    subgraph "Rate Limiting"
        RL1[Redis Rate Limiter]
        RL2[In-Memory Fallback]
    end

    subgraph "Data Storage"
        DB1[(PostgreSQL<br/>- Tenants<br/>- Messages<br/>- Conversations<br/>- Tools<br/>- KBs<br/>- MCPs)]
        DB2[(pgvector<br/>- RAG Documents<br/>- Embeddings)]
        REDIS1[(Redis<br/>- Rate Limits<br/>- Job Queue)]
    end

    subgraph "Observability"
        METRICS1[Prometheus Metrics]
        LOGS1[Event Logs]
        LOGS2[Tool Call Logs]
        TRACES1[LLM Traces]
    end

    APP --> MW1
    MW1 --> MW2
    MW2 --> MW3
    MW3 --> MW4
    MW4 --> MW5
    MW5 --> AUTH1
    AUTH1 --> AUTH2
    AUTH2 --> RLS
    RLS --> CB1
    RLS --> CB2
    CB1 --> RETRY
    CB2 --> RETRY
    RETRY --> TIMEOUT
    AUTH1 --> RL1
    RL1 --> RL2
    RL1 --> REDIS1
    APP --> DB1
    APP --> DB2
    APP --> REDIS1
    APP --> METRICS1
    APP --> LOGS1
    APP --> LOGS2
    APP --> TRACES1
    LOGS1 --> DB1
    LOGS2 --> DB1
    TRACES1 --> DB1

    style APP fill:#e1f5ff
    style RLS fill:#fff4e1
    style DB1 fill:#f3e5f5
    style REDIS1 fill:#ffebee
```

## Tool Execution Flow

```mermaid
graph TD
    START[LLM Requests Tool]
    START --> TOOL_REG[Tool Registry<br/>Get Tool Definition]
    TOOL_REG --> CHECK[Check Tenant<br/>Tool Allow-List]
    CHECK -->|Allowed| EXEC[Tool Execution Engine]
    CHECK -->|Not Allowed| ERROR[Error: Tool Not Allowed]
    
    EXEC --> PROVIDER{Provider Type}
    
    PROVIDER -->|internal_rag| RAG[Internal RAG Client]
    PROVIDER -->|openai_file| OPENAI[OpenAI File Client]
    PROVIDER -->|gemini_file| GEMINI[Gemini File Client]
    PROVIDER -->|mcp| MCP[MCP Client]
    
    RAG --> RAG_IMPL[pgvector Query<br/>Semantic Search]
    OPENAI --> OPENAI_IMPL[OpenAI Vector Store<br/>File Search]
    GEMINI --> GEMINI_IMPL[Gemini Corpus<br/>File Search]
    MCP --> MCP_IMPL[HTTP/WebSocket<br/>JSON-RPC 2.0]
    
    RAG_IMPL --> RESULT[Tool Result]
    OPENAI_IMPL --> RESULT
    GEMINI_IMPL --> RESULT
    MCP_IMPL --> RESULT
    
    RESULT --> LOG[Log Tool Call]
    LOG --> RETURN[Return to LLM]
    RETURN --> LLM_CONTINUE[LLM Continues Processing]
    
    ERROR --> LOG_ERROR[Log Error]
    
    style START fill:#e1f5ff
    style EXEC fill:#fff4e1
    style RESULT fill:#e8f5e9
    style ERROR fill:#ffebee
```

## Database Schema Relationships

```mermaid
erDiagram
    TENANTS ||--o{ CHANNELS : "has"
    TENANTS ||--o| TENANT_PROMPTS : "has"
    TENANTS ||--o{ TENANT_TOOL_POLICIES : "has"
    TENANTS ||--o{ KNOWLEDGE_BASES : "has"
    TENANTS ||--o{ MCP_SERVERS : "has"
    TENANTS ||--o{ CONVERSATIONS : "has"
    TENANTS ||--o{ MESSAGES : "has"
    TENANTS ||--o{ EVENT_LOGS : "has"
    TENANTS ||--o{ TOOL_CALL_LOGS : "has"
    TENANTS ||--o{ LLM_TRACES : "has"
    TENANTS ||--o{ API_KEYS : "has"
    
    CHANNELS ||--o{ CONVERSATIONS : "has"
    CONVERSATIONS ||--o{ MESSAGES : "contains"
    
    TOOLS ||--o{ TENANT_TOOL_POLICIES : "referenced_by"
    
    TENANTS {
        uuid id PK
        string llm_provider
        string llm_model
        string isolation_mode
    }
    
    CHANNELS {
        uuid id PK
        uuid tenant_id FK
        string channel_type
        boolean is_active
    }
    
    CONVERSATIONS {
        uuid id PK
        uuid tenant_id FK
        uuid channel_id FK
        string external_thread_id
        string status
    }
    
    MESSAGES {
        uuid id PK
        uuid tenant_id FK
        uuid conversation_id FK
        string direction
        jsonb content_text
        jsonb metadata
    }
    
    TOOLS {
        uuid id PK
        string name
        string provider
        jsonb parameters_schema
    }
    
    TENANT_TOOL_POLICIES {
        uuid id PK
        uuid tenant_id FK
        uuid tool_id FK
        boolean is_enabled
        jsonb config_override
    }
```

## Channel Adapter Architecture

```mermaid
graph TB
    subgraph "External Channel APIs"
        TG_API[Telegram Bot API]
        SLACK_API[Slack API]
        EMAIL_SVC[Email Service]
    end

    subgraph "Channel Adapter Services (Separate Services)"
        TG_ADAPTER[Telegram Adapter Service<br/>- Receives Telegram webhooks<br/>- Converts to CanonicalMessage<br/>- Calls Orchestrator API<br/>- Converts response back to Telegram format<br/>Status: Testing/Development Only]
        SLACK_ADAPTER[Slack Adapter Service<br/>Future Implementation]
        EMAIL_ADAPTER[Email Adapter Service<br/>Future Implementation]
    end

    subgraph "Nexus Hub Service"
        subgraph "FastAPI Application"
            ORCH_API[POST /messages/inbound<br/>API Endpoint]
        end
        subgraph "Message Processing Core"
            ORCH_CORE[Orchestration Core<br/>- Message Processing<br/>- LLM Calls<br/>- Tool Execution]
        end
    end

    TG_API -->|Webhook| TG_ADAPTER
    SLACK_API -->|Webhook| SLACK_ADAPTER
    EMAIL_SVC -->|SMTP/IMAP| EMAIL_ADAPTER

    TG_ADAPTER -->|HTTP POST<br/>CanonicalMessage + API Key| ORCH_API
    SLACK_ADAPTER -->|HTTP POST<br/>CanonicalMessage + API Key| ORCH_API
    EMAIL_ADAPTER -->|HTTP POST<br/>CanonicalMessage + API Key| ORCH_API

    ORCH_API --> ORCH_CORE
    ORCH_CORE -->|Outbound CanonicalMessage| ORCH_API

    ORCH_API -->|HTTP Response<br/>Outbound CanonicalMessage| TG_ADAPTER
    ORCH_API -->|HTTP Response<br/>Outbound CanonicalMessage| SLACK_ADAPTER
    ORCH_API -->|HTTP Response<br/>Outbound CanonicalMessage| EMAIL_ADAPTER

    TG_ADAPTER -->|Send Message| TG_API
    SLACK_ADAPTER -->|Send Message| SLACK_API
    EMAIL_ADAPTER -->|Send Email| EMAIL_SVC

    style TG_ADAPTER fill:#fff9c4
    style ORCH_API fill:#e1f5ff
    style ORCH_CORE fill:#fff4e1
```

### Channel Adapter Responsibilities

Channel adapters are **separate services** that:

1. **Receive channel-specific messages** (webhooks, API calls, etc.)
2. **Transform to CanonicalMessage format** (normalize channel-specific data)
3. **Call Orchestrator API** (`POST /messages/inbound`) with API key authentication
4. **Receive outbound CanonicalMessage** from orchestrator
5. **Transform back to channel format** and send response

### Key Design Principles

- **Separation of Concerns**: Channel-specific logic stays in adapters, not in orchestrator
- **Channel Agnostic**: Orchestrator only knows about `CanonicalMessage`, not channel specifics
- **Standardized Interface**: All adapters use the same `POST /messages/inbound` endpoint
- **Independent Deployment**: Adapters can be deployed, scaled, and updated independently
- **Testing Support**: Telegram adapter currently serves as a testing/development tool

