"""Общие Prometheus-метрики для всех сервисов.

Любая объявленная здесь метрика обязана быть покрыта дашбордом Grafana.
Метрики, не используемые ни одним дашбордом, должны быть удалены.
"""

from __future__ import annotations

from prometheus_client import Counter, Histogram

_DURATION_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 40, 80)

http_requests_total = Counter(
    "http_requests_total",
    "HTTP requests handled by a service",
    ["service", "endpoint", "method", "status"],
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration by endpoint",
    ["service", "endpoint"],
    buckets=_DURATION_BUCKETS,
)

llm_requests_total = Counter(
    "llm_requests_total",
    "LLM provider calls",
    ["provider", "model", "status"],
)

llm_request_duration_seconds = Histogram(
    "llm_request_duration_seconds",
    "LLM request duration",
    ["provider", "model"],
    buckets=_DURATION_BUCKETS,
)

llm_tokens_total = Counter(
    "llm_tokens_total",
    "LLM tokens processed",
    ["provider", "model", "direction"],
)

rag_requests_total = Counter(
    "rag_requests_total",
    "RAG retrieval requests",
    ["status"],
)

mcp_requests_total = Counter(
    "mcp_requests_total",
    "MCP tool invocations",
    ["tool", "status"],
)

pipeline_steps_total = Counter(
    "pipeline_steps_total",
    "Pipeline step executions",
    ["step", "status"],
)

llm_safety_triggers_total = Counter(
    "llm_safety_triggers_total",
    "LLM-phase safety net triggers by reason",
    ["reason"],
)
