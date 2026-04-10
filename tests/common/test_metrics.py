from prometheus_client import REGISTRY

from common.metrics import (
    http_requests_total,
    llm_tokens_total,
    pipeline_steps_total,
)


def _names():
    return {m.name for m in REGISTRY.collect()}


def test_all_metrics_registered():
    names = _names()
    for expected in [
        "http_requests",
        "http_request_duration_seconds",
        "llm_requests",
        "llm_request_duration_seconds",
        "llm_tokens",
        "rag_requests",
        "mcp_requests",
        "pipeline_steps",
    ]:
        assert expected in names, f"missing metric: {expected}"


def test_http_requests_total_accepts_labels():
    http_requests_total.labels(service="agent_api", endpoint="/chat", method="POST", status="200").inc()


def test_llm_tokens_direction_label():
    llm_tokens_total.labels(provider="ollama", model="x", direction="input").inc(5)
    llm_tokens_total.labels(provider="ollama", model="x", direction="output").inc(7)


def test_pipeline_steps_label():
    pipeline_steps_total.labels(step="route", status="ok").inc()
