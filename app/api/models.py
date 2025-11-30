"""API request/response models."""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


# ============================================================================
# Messages Models
# ============================================================================

class InboundMessageResponse(BaseModel):
    """Response model for inbound message processing."""
    status: str = Field(..., example="success")
    message: Dict[str, Any] = Field(..., description="Outbound message details")
    latency_ms: int = Field(..., description="Total processing latency in milliseconds")
    tool_calls_executed: int = Field(default=0, description="Number of tool calls executed")


class TelegramWebhookResponse(BaseModel):
    """Response model for Telegram webhook."""
    status: str = Field(..., example="success")
    message: str = Field(..., example="Message processed and sent to Telegram")
    latency_ms: Optional[int] = None


class MessageResponse(BaseModel):
    """Response model for message."""
    id: str
    tenant_id: str
    conversation_id: str
    channel_id: Optional[str]
    direction: str
    source_message_id: Optional[str]
    from_type: str
    from_external_id: Optional[str]
    from_display_name: Optional[str]
    content_type: str
    content_text: str
    metadata: Dict[str, Any]
    created_at: str


class MessageListResponse(BaseModel):
    """Response model for listing messages."""
    items: List[MessageResponse]
    count: int
    has_more: bool = False
    next_offset: Optional[int] = None


# ============================================================================
# Conversations Models
# ============================================================================

class ConversationResponse(BaseModel):
    """Response model for conversation."""
    id: str
    tenant_id: str
    channel_id: Optional[str]
    external_thread_id: Optional[str]
    subject: Optional[str]
    status: str
    created_at: str
    updated_at: str


class ConversationListResponse(BaseModel):
    """Response model for listing conversations."""
    items: List[ConversationResponse]
    count: int
    has_more: bool = False
    next_offset: Optional[int] = None


class UpdateConversationRequest(BaseModel):
    """Request model for updating a conversation."""
    subject: Optional[str] = None
    status: Optional[str] = Field(None, description="Status: 'open', 'closed', 'archived'", example="closed")


class ConversationStatsResponse(BaseModel):
    """Response model for conversation statistics."""
    conversation_id: str
    tenant_id: str
    resolved: bool
    resolution_time_ms: Optional[int]
    total_messages: int
    tool_calls: int
    risk_flags: int
    last_event_at: Optional[str]
    updated_at: str


# ============================================================================
# Tenant Management Models
# ============================================================================

class UpdatePromptRequest(BaseModel):
    """Request model for tenant prompt update."""
    custom_system_prompt: str = Field(..., description="Custom system prompt text", example="You are a helpful assistant for ACME Corp.")
    override_mode: str = Field(default="append", description="Override mode: 'append' or 'replace_behavior'", example="append")


class GetPromptResponse(BaseModel):
    """Response model for getting tenant prompt."""
    custom_system_prompt: str
    override_mode: str
    created_at: str
    updated_at: str
    validation_status: Optional[str] = None
    effective_prompt: Optional[str] = None


class PromptUpdateResponse(BaseModel):
    """Response model for prompt update."""
    status: str
    effective_prompt: str
    validation_status: str
    issues: List[Dict[str, Any]] = []


class EnableToolRequest(BaseModel):
    """Request model for enabling a tool for a tenant."""
    tool_name: str = Field(..., description="Canonical tool name", example="openai_file_search")
    config_override: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Optional configuration override for this tenant", example={})


class UpdateToolPolicyRequest(BaseModel):
    """Request model for updating a tool policy."""
    is_enabled: Optional[bool] = Field(None, description="Enable or disable the tool", example=True)
    config_override: Optional[Dict[str, Any]] = Field(None, description="Configuration override for this tenant", example={})


class TenantToolResponse(BaseModel):
    """Response model for tenant tool policy."""
    tool_id: str
    tool_name: str
    description: str
    provider: str
    is_enabled: bool
    config_override: Dict[str, Any]
    created_at: str
    updated_at: str


class TenantToolsListResponse(BaseModel):
    """Response model for listing tenant tools."""
    items: List[TenantToolResponse]
    count: int


class CreateAPIKeyRequest(BaseModel):
    """Request model for creating an API key."""
    name: Optional[str] = None
    description: Optional[str] = None
    expires_in_days: Optional[int] = None
    rate_limit_per_minute: int = 100
    metadata: Optional[Dict[str, Any]] = None


# ============================================================================
# Knowledge Bases Models
# ============================================================================

class CreateKnowledgeBaseRequest(BaseModel):
    """Request model for creating a knowledge base."""
    name: str = Field(..., description="Knowledge base name (unique per tenant)", example="support_faq")
    description: Optional[str] = Field(None, description="Knowledge base description", example="Support FAQ knowledge base")
    providers: Optional[List[str]] = Field(None, description="Optional list of providers to enable. Defaults to all enabled tools.", example=["internal_rag", "openai_file", "gemini_file"])


class UpdateKnowledgeBaseRequest(BaseModel):
    """Request model for updating a knowledge base."""
    description: Optional[str] = None
    provider_config: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None


class ProviderSyncStatus(BaseModel):
    """Response model for provider sync status."""
    provider: str = Field(..., description="Provider name", example="openai_file")
    is_active: bool = Field(..., description="Whether provider is active")
    sync_status: str = Field(..., description="Sync status: 'enabled', 'disabled', 'syncing', 'error'", example="enabled")
    store_id: Optional[str] = Field(None, description="Store ID (vector_store_id or file_search_store_name)")
    last_sync_at: Optional[str] = Field(None, description="Last sync timestamp")
    error_message: Optional[str] = Field(None, description="Error message if sync failed")


class KnowledgeBaseResponse(BaseModel):
    """Response model for knowledge base."""
    id: str
    tenant_id: str
    name: str
    description: Optional[str]
    provider: str  # Keep for backward compatibility (legacy field)
    provider_config: Dict[str, Any]  # Keep for backward compatibility (legacy field)
    is_active: bool
    provider_sync_status: Optional[List[ProviderSyncStatus]] = Field(None, description="Sync status per provider")
    created_at: str
    updated_at: str


class KnowledgeBasesListResponse(BaseModel):
    """Response model for listing knowledge bases."""
    items: List[KnowledgeBaseResponse]
    count: int


class SyncKnowledgeBaseRequest(BaseModel):
    """Request model for syncing knowledge base."""
    provider: Optional[str] = Field(None, description="Optional provider to sync. If not specified, syncs all providers.", example="openai_file")


class SyncStatusResponse(BaseModel):
    """Response model for sync status."""
    status: str = Field(..., description="Overall sync status", example="completed")
    results: Dict[str, Dict[str, Any]] = Field(..., description="Sync results per provider")
    total_documents: int = Field(..., description="Total documents processed")
    synced_documents: int = Field(..., description="Number of documents successfully synced")
    failed_documents: int = Field(..., description="Number of documents that failed to sync")


# ============================================================================
# MCP Servers Models
# ============================================================================

class CreateMCPServerRequest(BaseModel):
    """Request model for creating an MCP server."""
    name: str = Field(..., description="MCP server name (unique per tenant)", example="crm_server")
    endpoint: str = Field(..., description="MCP server endpoint (http/https/ws/wss)", example="https://mcp.example.com/api")
    auth_config: Dict[str, Any] = Field(..., description="Authentication configuration (JSONB)", example={"type": "api_key", "key": "secret"})


class UpdateMCPServerRequest(BaseModel):
    """Request model for updating an MCP server."""
    endpoint: Optional[str] = None
    auth_config: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None


class MCPServerResponse(BaseModel):
    """Response model for MCP server."""
    id: str
    tenant_id: str
    name: str
    endpoint: str
    auth_config: Dict[str, Any]
    is_active: bool
    created_at: str
    updated_at: str


class MCPServerToolResponse(BaseModel):
    """Response model for MCP server tool."""
    id: str
    mcp_server_id: str
    tool_name: str
    description: Optional[str]
    json_schema: Dict[str, Any] = Field(..., alias="schema", description="Tool schema (JSON Schema)")
    created_at: str
    updated_at: str
    
    class Config:
        populate_by_name = True  # Allow both 'schema' and 'json_schema' in API


class CreateMCPServerToolRequest(BaseModel):
    """Request model for creating/updating an MCP server tool."""
    tool_name: str = Field(..., description="Tool name as exposed by MCP server", example="get_customer")
    description: Optional[str] = Field(None, description="Tool description", example="Get customer information by ID")
    json_schema: Dict[str, Any] = Field(default_factory=dict, alias="schema", description="Tool schema (JSON Schema)", example={"type": "object", "properties": {}})
    
    class Config:
        populate_by_name = True  # Allow both 'schema' and 'json_schema' in API


# ============================================================================
# Analytics Models
# ============================================================================

class ConversationAnalyticsResponse(BaseModel):
    """Response model for conversation analytics."""
    total_conversations: int
    open_conversations: int
    closed_conversations: int
    archived_conversations: int
    resolved_conversations: int
    resolution_rate: float
    avg_messages_per_conversation: float
    avg_tool_calls_per_conversation: float
    period_start: Optional[str] = None
    period_end: Optional[str] = None


class UsageStatisticsResponse(BaseModel):
    """Response model for usage statistics."""
    total_messages: int
    total_conversations: int
    total_tool_calls: int
    total_llm_calls: int
    active_conversations: int
    period_start: Optional[str] = None
    period_end: Optional[str] = None


class KPISnapshotResponse(BaseModel):
    """Response model for KPI snapshot."""
    tenant_id: str
    period_type: str
    period_start: str
    period_end: str
    metric_name: str
    metric_value: float
    created_at: str


class KPISnapshotsListResponse(BaseModel):
    """Response model for listing KPI snapshots."""
    items: List[KPISnapshotResponse]
    count: int


# ============================================================================
# Costs Models
# ============================================================================

class CostSummaryResponse(BaseModel):
    """Response model for cost summary."""
    total_cost: float
    llm_cost: float
    tool_cost: float
    period_start: Optional[str] = None
    period_end: Optional[str] = None
    currency: str = "USD"


class CostBreakdownResponse(BaseModel):
    """Response model for detailed cost breakdown."""
    total_cost: float
    llm_cost: float
    tool_cost: float
    by_provider: Dict[str, float]
    by_model: Dict[str, float]
    by_tool: Dict[str, float]
    period_start: Optional[str] = None
    period_end: Optional[str] = None
    currency: str = "USD"


class CostByPeriodResponse(BaseModel):
    """Response model for costs by time period."""
    items: List[Dict[str, Any]]
    total_cost: float
    period_type: str
    period_start: str
    period_end: str


class CostByConversationResponse(BaseModel):
    """Response model for costs per conversation."""
    items: List[Dict[str, Any]]
    total_cost: float
    count: int


class CostEstimateRequest(BaseModel):
    """Request model for cost estimation."""
    provider: str = Field(..., description="LLM provider: 'openai' or 'gemini'")
    model: str = Field(..., description="Model name")
    estimated_prompt_tokens: Optional[int] = Field(None, description="Estimated prompt tokens")
    estimated_completion_tokens: Optional[int] = Field(None, description="Estimated completion tokens")
    estimated_total_tokens: Optional[int] = Field(None, description="Estimated total tokens (if prompt/completion not available)")


class CostEstimateResponse(BaseModel):
    """Response model for cost estimation."""
    estimated_cost: float
    provider: str
    model: str
    currency: str = "USD"
    breakdown: Dict[str, Any]


# ============================================================================
# Logs Models
# ============================================================================

class LogQueryResponse(BaseModel):
    """Response model for log queries."""
    items: List[Dict[str, Any]]
    total: int
    limit: int
    offset: int
    has_more: bool


# ============================================================================
# LLM Traces Models
# ============================================================================

class LLMTraceResponse(BaseModel):
    """Response model for LLM trace."""
    id: str
    tenant_id: str
    conversation_id: Optional[str]
    message_id: Optional[str]
    provider: str
    model: str
    request_payload: Dict[str, Any]
    response_payload: Dict[str, Any]
    created_at: str


class LLMTraceListResponse(BaseModel):
    """Response model for listing LLM traces."""
    items: List[LLMTraceResponse]
    count: int
    has_more: bool = False
    next_offset: Optional[int] = None


# ============================================================================
# Channels Models
# ============================================================================

class CreateChannelRequest(BaseModel):
    """Request model for creating a channel."""
    name: str = Field(..., description="Channel name (unique per tenant)", example="whatsapp-main")
    channel_type: str = Field(..., description="Channel type: 'whatsapp', 'web', 'slack', 'telegram', etc.", example="whatsapp")
    external_id: Optional[str] = Field(None, description="External channel ID (e.g., WhatsApp number, Slack app ID)", example="+1234567890")
    config: Dict[str, Any] = Field(default_factory=dict, description="Channel-specific configuration (JSONB)", example={})
    is_active: bool = Field(default=True, description="Whether the channel is active")


class UpdateChannelRequest(BaseModel):
    """Request model for updating a channel."""
    name: Optional[str] = None
    channel_type: Optional[str] = None
    external_id: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None


class ChannelResponse(BaseModel):
    """Response model for channel."""
    id: str
    tenant_id: str
    name: str
    channel_type: str
    external_id: Optional[str]
    config: Dict[str, Any]
    is_active: bool
    created_at: str
    updated_at: str


class ChannelListResponse(BaseModel):
    """Response model for listing channels."""
    items: List[ChannelResponse]
    count: int


# ============================================================================
# RAG Documents Models
# ============================================================================

class CreateRAGDocumentRequest(BaseModel):
    """Request model for creating a RAG document."""
    kb_name: str = Field(..., description="Knowledge base name (must exist)", example="support_faq")
    external_id: Optional[str] = Field(None, description="External document ID (file ID, URL, etc.)", example="doc-123")
    title: Optional[str] = Field(None, description="Document title", example="FAQ: Getting Started")
    content: str = Field(..., description="Document content text", example="This is the document content...")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Document metadata (JSONB)", example={})
    chunk_size: int = Field(default=1000, ge=100, le=10000, description="Character count per chunk")
    chunk_overlap: int = Field(default=200, ge=0, le=500, description="Character overlap between chunks")


class UpdateRAGDocumentRequest(BaseModel):
    """Request model for updating a RAG document."""
    title: Optional[str] = None
    content: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class RAGDocumentResponse(BaseModel):
    """Response model for RAG document."""
    id: str
    tenant_id: str
    kb_name: str
    external_id: Optional[str]
    title: Optional[str]
    content: str
    metadata: Dict[str, Any]
    created_at: str
    updated_at: str


class RAGDocumentListResponse(BaseModel):
    """Response model for listing RAG documents."""
    items: List[RAGDocumentResponse]
    count: int
    has_more: bool = False
    next_offset: Optional[int] = None


class RAGChunkResponse(BaseModel):
    """Response model for RAG chunk."""
    id: str
    tenant_id: str
    kb_name: str
    document_id: str
    chunk_index: int
    content: str
    metadata: Dict[str, Any]
    created_at: str


class RAGChunkListResponse(BaseModel):
    """Response model for listing RAG chunks."""
    items: List[RAGChunkResponse]
    count: int
