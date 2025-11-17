"""Prometheus metrics export."""

from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from fastapi import Response

# Request metrics
request_count = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"],
)

request_duration = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "endpoint"],
)

# LLM metrics
llm_calls_total = Counter(
    "llm_calls_total",
    "Total LLM API calls",
    ["provider", "model", "status"],
)

llm_call_duration = Histogram(
    "llm_call_duration_seconds",
    "LLM API call duration in seconds",
    ["provider", "model"],
)

llm_tokens_total = Counter(
    "llm_tokens_total",
    "Total LLM tokens",
    ["provider", "model", "type"],  # type: prompt or completion
)

llm_cost_total = Counter(
    "llm_cost_total",
    "Total LLM cost in USD",
    ["provider", "model"],
)

# Tool metrics
tool_calls_total = Counter(
    "tool_calls_total",
    "Total tool calls",
    ["tool_name", "provider", "status"],
)

tool_call_duration = Histogram(
    "tool_call_duration_seconds",
    "Tool call duration in seconds",
    ["tool_name", "provider"],
)

# Queue metrics
queue_jobs_total = Counter(
    "queue_jobs_total",
    "Total queued jobs",
    ["queue", "status"],
)

queue_job_duration = Histogram(
    "queue_job_duration_seconds",
    "Queue job duration in seconds",
    ["queue"],
)

# Active connections
active_connections = Gauge(
    "active_connections",
    "Number of active database connections",
)

# Circuit breaker metrics
circuit_breaker_state = Gauge(
    "circuit_breaker_state",
    "Circuit breaker state (0=closed, 1=half_open, 2=open)",
    ["service"],
)


def get_metrics_response() -> Response:
    """Get Prometheus metrics as HTTP response."""
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )

