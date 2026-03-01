from __future__ import annotations

from prometheus_client import Counter, Histogram

agent_requests_total = Counter(
    "agent_requests_total",
    "Total number of requests to the agent API",
    ["endpoint", "status"],
)

tool_calls_total = Counter(
    "tool_calls_total",
    "Total number of MCP tool calls executed",
    ["tool", "ok"],
)

llm_fallback_total = Counter(
    "llm_fallback_total",
    "Total number of LLM fallback activations",
    ["mode"],
)

agent_latency_seconds = Histogram(
    "agent_latency_seconds",
    "Request latency in seconds",
    ["endpoint"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 40, 80),
)
