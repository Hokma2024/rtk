import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

from common.logging import configure_logging
from common.middleware import TraceIdMiddleware, install_http_metrics


def _make_app(service_name: str) -> FastAPI:
    configure_logging(service_name, "INFO")
    app = FastAPI()
    app.add_middleware(TraceIdMiddleware)
    install_http_metrics(app, service_name=service_name)

    @app.get("/ping")
    def ping():
        return {"ok": True}

    return app


def test_trace_id_generated_when_missing():
    client = TestClient(_make_app("svc-x"))
    r = client.get("/ping")
    assert r.status_code == 200
    tid = r.headers["x-trace-id"]
    uuid.UUID(tid)


def test_trace_id_propagated_from_header():
    client = TestClient(_make_app("svc-x"))
    tid = str(uuid.uuid4())
    r = client.get("/ping", headers={"X-Trace-Id": tid})
    assert r.headers["x-trace-id"] == tid


def test_http_metrics_incremented():
    client = TestClient(_make_app("svc-y"))
    client.get("/ping")

    total = 0.0
    for metric in REGISTRY.collect():
        if metric.name == "http_requests":
            for sample in metric.samples:
                if (
                    sample.name == "http_requests_total"
                    and sample.labels.get("service") == "svc-y"
                    and sample.labels.get("endpoint") == "/ping"
                ):
                    total += sample.value
    assert total >= 1.0
