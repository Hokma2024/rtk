# RTKI Grooming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn `unified_rtk_v2` into a product-grade project: full tests, structured logging, Prometheus metrics + Loki/Grafana stack, and a moderate (level B) grooming pass across all modules.

**Architecture:** Four sequential phases on branch `grooming`. Phase 1 lays observability foundations (both infra and code). Phase 2 ports tests from `diplom/rtk`. Phase 3 is a module-by-module grooming sweep that uses the tests as a safety net. Phase 4 is end-to-end verification.

**Tech stack:** Python 3.11+, FastAPI, pydantic v2, httpx, MCP SDK, `structlog` (new), `prometheus_client`, pytest + pytest-asyncio + pytest-httpx, ruff. Docker Compose for the full stack: ollama, rag_mock, mcp_server, agent_api + prometheus, loki, promtail, grafana.

**Working tree:** `/home/hokma/rtki_project/unified_rtk_v2`. Branch: `grooming` (already created, spec already committed).

**Reference donors (do NOT edit them, only read):**
- `/home/hokma/rtki_project/rtk-feature-monitoring/` — monitoring stack + logging hooks.
- `/home/hokma/rtki_project/diplom/rtk/` — tests.

**Spec file:** `docs/superpowers/specs/2026-04-10-rtki-grooming-design.md`. Read it before starting.

**Global conventions enforced throughout the plan:**
- TDD where applicable: for any *new* code in Phase 1 (logging, metrics helpers), write a failing test first. Phase 2 is porting existing tests, not TDD. Phase 3 runs the full suite after every module.
- Frequent commits: one commit per completed task unless the task explicitly says otherwise.
- Never `--no-verify`, never amend. New commit per fix.
- Never push anywhere unless explicitly told.
- If stuck on a pause-point from the spec (§6), stop and ask the user.

---

## Phase 0: Pre-flight setup

### Task 0.1: Verify branch and baseline

**Files:**
- Read: `unified_rtk_v2/docs/superpowers/specs/2026-04-10-rtki-grooming-design.md`

- [ ] **Step 1: Confirm branch**

Run:
```bash
cd /home/hokma/rtki_project/unified_rtk_v2 && git status && git branch --show-current
```
Expected: `grooming` branch, clean working tree (spec already committed in prior session).

- [ ] **Step 2: Record baseline**

Run:
```bash
cd /home/hokma/rtki_project/unified_rtk_v2
git log --oneline -5
find . -type f -name '*.py' -not -path './venv/*' -not -path './docs/*' | wc -l
```
Expected: `grooming` branch has the spec commit. Record the file count in a scratch note (you will compare at the end).

- [ ] **Step 3: Delete dev artifacts immediately**

These are not product code and would only confuse later tasks:
```bash
cd /home/hokma/rtki_project/unified_rtk_v2
git rm dump_project.py project_dump.txt 2>/dev/null || rm -f dump_project.py project_dump.txt
```

- [ ] **Step 4: Commit**

```bash
cd /home/hokma/rtki_project/unified_rtk_v2
git add -A
git commit -m "chore: remove dev dump artifacts (dump_project.py, project_dump.txt)"
```

### Task 0.2: Add dev-deps and linter config upfront

**Files:**
- Create: `unified_rtk_v2/requirements-dev.txt`
- Create: `unified_rtk_v2/ruff.toml`

- [ ] **Step 1: Create requirements-dev.txt**

```txt
pytest==8.3.3
pytest-asyncio==0.24.0
pytest-httpx==0.34.0
httpx==0.28.1
ruff==0.7.4
structlog==24.4.0
```

Note: `httpx` is already in `requirements.txt` — keep it there too since the app uses it. Version pin must match.

- [ ] **Step 2: Create ruff.toml (minimal)**

```toml
line-length = 120
target-version = "py311"

[lint]
select = ["E", "F", "W", "I", "B", "UP", "SIM", "RUF"]
ignore = ["E501"]  # line length enforced separately if needed

[lint.per-file-ignores]
"tests/**" = ["B", "SIM"]
```

- [ ] **Step 3: Install deps and sanity-check ruff**

Run:
```bash
cd /home/hokma/rtki_project/unified_rtk_v2
source venv/bin/activate
pip install -r requirements-dev.txt
ruff --version
```
Expected: ruff version printed, no install errors.

- [ ] **Step 4: Baseline ruff run (do not fix yet)**

Run:
```bash
cd /home/hokma/rtki_project/unified_rtk_v2
ruff check . --exclude venv --exclude docs 2>&1 | tee /tmp/ruff-baseline.txt | tail -20
```
Record the number of findings. Do not fix them now — that's Phase 3 work.

- [ ] **Step 5: Commit**

```bash
cd /home/hokma/rtki_project/unified_rtk_v2
git add requirements-dev.txt ruff.toml
git commit -m "chore(deps): add pytest, ruff, structlog as dev deps; minimal ruff config"
```

---

## Phase 1: Monitoring & Logging

### Task 1.1: Copy monitoring stack from donor

**Files:**
- Create: `unified_rtk_v2/monitoring/prometheus.yml`
- Create: `unified_rtk_v2/monitoring/loki-config.yaml`
- Create: `unified_rtk_v2/monitoring/promtail-config.yaml`
- Create: `unified_rtk_v2/monitoring/grafana/provisioning/datasources/datasources.yaml`
- Create: `unified_rtk_v2/monitoring/JSON Model.txt` (grafana dashboard)

- [ ] **Step 1: Copy folder as-is**

Run:
```bash
cp -r /home/hokma/rtki_project/rtk-feature-monitoring/monitoring \
      /home/hokma/rtki_project/unified_rtk_v2/monitoring
ls -la /home/hokma/rtki_project/unified_rtk_v2/monitoring
```
Expected: the 5 files above plus the grafana directory tree.

- [ ] **Step 2: Verify no paths inside those files reference the donor**

Run:
```bash
grep -r "rtk-feature-monitoring" /home/hokma/rtki_project/unified_rtk_v2/monitoring/
```
Expected: no output. If any match: edit the file to remove the absolute path.

- [ ] **Step 3: Commit**

```bash
cd /home/hokma/rtki_project/unified_rtk_v2
git add monitoring/
git commit -m "feat(monitoring): add prometheus/loki/promtail/grafana configs"
```

### Task 1.2: Merge docker-compose.yml — add monitoring profile

**Files:**
- Modify: `unified_rtk_v2/docker-compose.yml`

**Reference:** `/home/hokma/rtki_project/rtk-feature-monitoring/docker-compose.yml`

**Goal:** Keep v2's existing services (ollama, rag_mock, mcp_server, agent_api) EXACTLY as they are except:
1. Add `profiles: ["monitoring"]` to each new monitoring service so `docker-compose up` without a profile still works for dev.
2. Add log labels / logging driver settings if the donor uses them, so Promtail can scrape docker logs.
3. Add `SERVICE_NAME` env var to each existing python service (rag_mock, mcp_server, agent_api) — it is required by the new logging module (Task 1.3).

- [ ] **Step 1: Read both files side-by-side**

Run:
```bash
diff -u /home/hokma/rtki_project/unified_rtk_v2/docker-compose.yml \
        /home/hokma/rtki_project/rtk-feature-monitoring/docker-compose.yml | head -200
```
Read the diff carefully. Identify:
- Which new services the donor adds (prometheus, loki, promtail, grafana).
- Whether the donor changes the existing services' log config (labels, driver).
- Whether the donor adds any env vars.

- [ ] **Step 2: Apply the merge**

Edit `unified_rtk_v2/docker-compose.yml`:
1. Append the donor's new services at the bottom.
2. Add `profiles: ["monitoring"]` to each of `prometheus`, `loki`, `promtail`, `grafana`.
3. To each of `rag_mock`, `mcp_server`, `agent_api`, add under `environment:`:
   ```yaml
   SERVICE_NAME: rag_mock   # or mcp_server / agent_api
   LOG_LEVEL: ${LOG_LEVEL:-INFO}
   ```
4. If the donor adds log labels to these services (for promtail scraping), mirror them here.

- [ ] **Step 3: Validate compose syntax**

Run:
```bash
cd /home/hokma/rtki_project/unified_rtk_v2
docker-compose config > /dev/null
docker-compose --profile monitoring config > /dev/null
```
Expected: both succeed silently. If there are errors, fix them.

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml
git commit -m "feat(compose): add monitoring profile (prometheus/loki/promtail/grafana)"
```

### Task 1.3: New logging module — `common/logging.py`

**Files:**
- Create: `unified_rtk_v2/common/logging.py`
- Create: `unified_rtk_v2/tests/common/test_logging.py`
- Modify: `unified_rtk_v2/requirements.txt` (add structlog to runtime deps)

**What this module provides (public API):**
- `configure_logging(service_name: str, level: str = "INFO") -> None` — idempotent, called at startup of each service.
- `get_logger(name: str) -> structlog.BoundLogger` — module-level logger factory.
- `bind_trace_id(trace_id: str) -> None` — binds `trace_id` to contextvars so downstream log calls include it automatically.
- `get_or_create_trace_id(header_value: str | None) -> str` — returns the incoming header if valid UUID, else generates a new one.
- `clear_trace_id() -> None` — clears contextvars (for middleware teardown).

- [ ] **Step 1: Write the failing tests**

```python
# tests/common/test_logging.py
import json
import logging
import uuid

import pytest
import structlog

from common.logging import (
    bind_trace_id,
    clear_trace_id,
    configure_logging,
    get_logger,
    get_or_create_trace_id,
)


@pytest.fixture(autouse=True)
def _reset():
    clear_trace_id()
    yield
    clear_trace_id()


def test_configure_logging_is_idempotent():
    configure_logging("svc-a", "INFO")
    configure_logging("svc-a", "INFO")  # should not raise


def test_get_logger_returns_bound_logger():
    configure_logging("svc-a", "INFO")
    log = get_logger("mymod")
    assert hasattr(log, "info")


def test_get_or_create_trace_id_generates_when_missing():
    tid = get_or_create_trace_id(None)
    uuid.UUID(tid)  # must parse


def test_get_or_create_trace_id_accepts_valid_uuid():
    incoming = str(uuid.uuid4())
    assert get_or_create_trace_id(incoming) == incoming


def test_get_or_create_trace_id_replaces_invalid_input():
    tid = get_or_create_trace_id("not-a-uuid")
    uuid.UUID(tid)
    assert tid != "not-a-uuid"


def test_bind_trace_id_propagates_into_log_record(capsys):
    configure_logging("svc-a", "INFO")
    log = get_logger("mymod")
    tid = str(uuid.uuid4())
    bind_trace_id(tid)
    log.info("hello", foo="bar")
    captured = capsys.readouterr().out.strip()
    record = json.loads(captured.splitlines()[-1])
    assert record["trace_id"] == tid
    assert record["service"] == "svc-a"
    assert record["event"] == "hello"
    assert record["foo"] == "bar"
```

Also create `unified_rtk_v2/tests/__init__.py` and `unified_rtk_v2/tests/common/__init__.py` as empty files.

- [ ] **Step 2: Run the tests — must fail**

Run:
```bash
cd /home/hokma/rtki_project/unified_rtk_v2
source venv/bin/activate
PYTHONPATH=. pytest tests/common/test_logging.py -v
```
Expected: ImportError on `common.logging`.

- [ ] **Step 3: Add structlog to requirements.txt**

Edit `requirements.txt` and add a new section:
```txt
# Structured logging
structlog==24.4.0
```
Then install:
```bash
pip install structlog==24.4.0
```

- [ ] **Step 4: Implement `common/logging.py`**

```python
"""Structured JSON logging for all RTKI services.

All modules get their logger via `get_logger(__name__)`. Each service
calls `configure_logging(service_name)` once at startup. Trace IDs are
propagated via contextvars so downstream log calls include them
automatically without threading a parameter through every function.
"""

from __future__ import annotations

import logging
import sys
import uuid
from contextvars import ContextVar

import structlog

_trace_id_var: ContextVar[str | None] = ContextVar("trace_id", default=None)
_configured: bool = False


def _add_trace_id(_logger, _method, event_dict):
    tid = _trace_id_var.get()
    if tid is not None:
        event_dict["trace_id"] = tid
    return event_dict


def configure_logging(service_name: str, level: str = "INFO") -> None:
    global _configured
    if _configured:
        return

    log_level = getattr(logging, level.upper(), logging.INFO)

    logging.basicConfig(
        stream=sys.stdout,
        level=log_level,
        format="%(message)s",
        force=True,
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _add_trace_id,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Bind service_name globally via contextvars
    structlog.contextvars.bind_contextvars(service=service_name)
    _configured = True


def get_logger(name: str) -> structlog.BoundLogger:
    return structlog.get_logger(name)


def get_or_create_trace_id(header_value: str | None) -> str:
    if header_value:
        try:
            uuid.UUID(header_value)
            return header_value
        except ValueError:
            pass
    return str(uuid.uuid4())


def bind_trace_id(trace_id: str) -> None:
    _trace_id_var.set(trace_id)


def clear_trace_id() -> None:
    _trace_id_var.set(None)
```

- [ ] **Step 5: Run the tests — must pass**

Run:
```bash
cd /home/hokma/rtki_project/unified_rtk_v2
PYTHONPATH=. pytest tests/common/test_logging.py -v
```
Expected: all 6 tests pass.

- [ ] **Step 6: Commit**

```bash
git add common/logging.py tests/common/__init__.py tests/__init__.py tests/common/test_logging.py requirements.txt
git commit -m "feat(logging): structured JSON logging with trace_id via contextvars"
```

### Task 1.4: Rewrite `common/metrics.py` per spec

**Files:**
- Modify: `unified_rtk_v2/common/metrics.py`
- Create: `unified_rtk_v2/tests/common/test_metrics.py`

**Target metrics (from spec §Phase 1):**
- `http_requests_total{service, endpoint, method, status}` — Counter
- `http_request_duration_seconds{service, endpoint}` — Histogram
- `llm_requests_total{provider, model, status}` — Counter
- `llm_request_duration_seconds{provider, model}` — Histogram
- `llm_tokens_total{provider, model, direction}` — Counter
- `rag_requests_total{status}` — Counter
- `mcp_requests_total{tool, status}` — Counter
- `pipeline_steps_total{step, status}` — Counter

**Migration note:** the old file defines `agent_requests_total`, `tool_calls_total`, `llm_fallback_total`, `agent_latency_seconds`. All four are **replaced** by the new set above. Phase 3 grooming will remove any remaining references to the old names.

- [ ] **Step 1: Write the failing test**

```python
# tests/common/test_metrics.py
from prometheus_client import REGISTRY

from common.metrics import (
    http_request_duration_seconds,
    http_requests_total,
    llm_request_duration_seconds,
    llm_requests_total,
    llm_tokens_total,
    mcp_requests_total,
    pipeline_steps_total,
    rag_requests_total,
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
    http_requests_total.labels(
        service="agent_api", endpoint="/chat", method="POST", status="200"
    ).inc()


def test_llm_tokens_direction_label():
    llm_tokens_total.labels(provider="ollama", model="x", direction="input").inc(5)
    llm_tokens_total.labels(provider="ollama", model="x", direction="output").inc(7)


def test_pipeline_steps_label():
    pipeline_steps_total.labels(step="route", status="ok").inc()
```

- [ ] **Step 2: Run test — must fail**

Run:
```bash
PYTHONPATH=. pytest tests/common/test_metrics.py -v
```
Expected: ImportError on missing names.

- [ ] **Step 3: Rewrite `common/metrics.py`**

```python
"""Prometheus metrics shared across services.

All metrics exposed here must be covered by a Grafana dashboard.
Any metric not consumed by a dashboard should be removed.
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
    ["provider", "model", "direction"],  # direction: input|output
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
```

- [ ] **Step 4: Run test — must pass**

Run:
```bash
PYTHONPATH=. pytest tests/common/test_metrics.py -v
```
Expected: all tests pass.

- [ ] **Step 5: Note for Phase 3**

Add a line to `/tmp/grooming-notes.txt` (create if missing):
```
Phase 3: remove dead refs to old metric names (agent_requests_total, tool_calls_total, llm_fallback_total, agent_latency_seconds) from agent_api/main.py, services/llm_service.py, pipeline/pipeline.py
```

- [ ] **Step 6: Commit**

```bash
git add common/metrics.py tests/common/test_metrics.py
git commit -m "feat(metrics): redesign prometheus metric set (http/llm/rag/mcp/pipeline)"
```

### Task 1.5: HTTP middleware — trace_id and `/metrics` in agent_api

**Files:**
- Create: `unified_rtk_v2/common/middleware.py`
- Create: `unified_rtk_v2/tests/common/test_middleware.py`

**What this provides:**
- `TraceIdMiddleware` — FastAPI middleware that reads `X-Trace-Id` header, calls `get_or_create_trace_id`, `bind_trace_id`, clears on teardown, and adds the header to the response.
- `http_metrics_middleware` — increments `http_requests_total` and observes `http_request_duration_seconds` per request.

- [ ] **Step 1: Write failing tests**

```python
# tests/common/test_middleware.py
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

    # Find counter value
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
```

- [ ] **Step 2: Run tests — must fail**

Run:
```bash
PYTHONPATH=. pytest tests/common/test_middleware.py -v
```
Expected: ImportError on `common.middleware`.

- [ ] **Step 3: Implement `common/middleware.py`**

```python
"""FastAPI middleware for trace_id and HTTP metrics."""

from __future__ import annotations

import time

from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from common.logging import bind_trace_id, clear_trace_id, get_or_create_trace_id
from common.metrics import http_request_duration_seconds, http_requests_total

_TRACE_HEADER = "X-Trace-Id"


class TraceIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        incoming = request.headers.get(_TRACE_HEADER)
        trace_id = get_or_create_trace_id(incoming)
        bind_trace_id(trace_id)
        try:
            response = await call_next(request)
        finally:
            clear_trace_id()
        response.headers[_TRACE_HEADER] = trace_id
        return response


def install_http_metrics(app: FastAPI, *, service_name: str) -> None:
    @app.middleware("http")
    async def _metrics(request: Request, call_next):
        start = time.perf_counter()
        status = "500"
        try:
            response = await call_next(request)
            status = str(response.status_code)
            return response
        finally:
            elapsed = time.perf_counter() - start
            endpoint = request.url.path
            http_requests_total.labels(
                service=service_name,
                endpoint=endpoint,
                method=request.method,
                status=status,
            ).inc()
            http_request_duration_seconds.labels(
                service=service_name,
                endpoint=endpoint,
            ).observe(elapsed)
```

- [ ] **Step 4: Run tests — must pass**

Run:
```bash
PYTHONPATH=. pytest tests/common/test_middleware.py -v
```
Expected: all 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add common/middleware.py tests/common/test_middleware.py
git commit -m "feat(logging): TraceIdMiddleware + HTTP metrics middleware"
```

### Task 1.6: Wire logging/metrics into `agent_api/main.py`

**Files:**
- Modify: `unified_rtk_v2/agent_api/main.py`

**Goal:** on FastAPI startup call `configure_logging`, add `TraceIdMiddleware`, call `install_http_metrics`, expose `/metrics` endpoint. Do NOT touch business logic yet.

- [ ] **Step 1: Read current file**

Run:
```bash
cat /home/hokma/rtki_project/unified_rtk_v2/agent_api/main.py
```
Identify: where `FastAPI(...)` is instantiated, whether there is already a `/metrics` endpoint, and any existing logging config.

- [ ] **Step 2: Apply edits**

At the top of the file, after existing imports, add:
```python
import os

from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.responses import Response as _PromResponse

from common.logging import configure_logging, get_logger
from common.middleware import TraceIdMiddleware, install_http_metrics

_SERVICE_NAME = os.getenv("SERVICE_NAME", "agent_api")
_LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
configure_logging(_SERVICE_NAME, _LOG_LEVEL)
log = get_logger(__name__)
```

Right after `app = FastAPI(...)` (or equivalent), add:
```python
app.add_middleware(TraceIdMiddleware)
install_http_metrics(app, service_name=_SERVICE_NAME)


@app.get("/metrics")
def metrics_endpoint() -> _PromResponse:
    return _PromResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.on_event("startup")
async def _log_startup() -> None:
    log.info("service_startup", service=_SERVICE_NAME)


@app.on_event("shutdown")
async def _log_shutdown() -> None:
    log.info("service_shutdown", service=_SERVICE_NAME)
```

If a `/metrics` or `/health` endpoint already exists, do not duplicate — adjust to use the new metrics module instead.

- [ ] **Step 3: Smoke test the module imports**

Run:
```bash
cd /home/hokma/rtki_project/unified_rtk_v2
PYTHONPATH=. python -c "from agent_api.main import app; print('ok')"
```
Expected: `ok`.

- [ ] **Step 4: Commit**

```bash
git add agent_api/main.py
git commit -m "feat(agent_api): wire structured logging, trace_id, and /metrics"
```

### Task 1.7: Wire logging/metrics into `services/rag_mock/main.py` and `services/mcp_server/mcp_server.py`

**Files:**
- Modify: `unified_rtk_v2/services/rag_mock/main.py`
- Modify: `unified_rtk_v2/services/mcp_server/mcp_server.py`

- [ ] **Step 1: rag_mock — apply same pattern as Task 1.6**

Read current file, then add at top:
```python
import os

from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.responses import Response as _PromResponse

from common.logging import configure_logging, get_logger
from common.metrics import rag_requests_total
from common.middleware import TraceIdMiddleware, install_http_metrics

_SERVICE_NAME = os.getenv("SERVICE_NAME", "rag_mock")
configure_logging(_SERVICE_NAME, os.getenv("LOG_LEVEL", "INFO"))
log = get_logger(__name__)
```

After `app = FastAPI(...)`, add the same middleware block and `/metrics` endpoint as in Task 1.6. Then, find each existing RAG endpoint and add on success:
```python
rag_requests_total.labels(status="ok").inc()
```
and on handled exception:
```python
rag_requests_total.labels(status="error").inc()
```

- [ ] **Step 2: mcp_server — similar pattern**

For the MCP server file, the pattern depends on whether it is a FastAPI app, a stdio-based MCP server, or both. Inspect first:
```bash
head -40 services/mcp_server/mcp_server.py
```

**If FastAPI:** same pattern as rag_mock. Use `mcp_requests_total.labels(tool=<name>, status=...)` inside each tool handler.

**If stdio MCP only:** no HTTP middleware. Still call `configure_logging("mcp_server")` at module import, add `get_logger(__name__)`, and wrap each tool handler in try/finally that increments `mcp_requests_total`.

Do not change business logic. Only add observability hooks.

- [ ] **Step 3: Smoke test imports**

```bash
PYTHONPATH=. python -c "from services.rag_mock.main import app; print('rag_mock ok')"
PYTHONPATH=. python -c "import services.mcp_server.mcp_server; print('mcp_server ok')"
```
Expected: both ok.

- [ ] **Step 4: Commit**

```bash
git add services/
git commit -m "feat(services): wire logging, trace_id, metrics in rag_mock and mcp_server"
```

### Task 1.8: LLM + RAG client instrumentation

**Files:**
- Modify: `unified_rtk_v2/services/llm_service.py`
- Modify: `unified_rtk_v2/providers/base.py`
- Modify: `unified_rtk_v2/providers/ollama_provider.py`
- Modify: `unified_rtk_v2/providers/openrouter_provider.py`
- Modify: `unified_rtk_v2/clients/mcp_client.py`

**Goal:** around every outbound LLM call, emit `INFO` start/end logs with duration and status, and update `llm_requests_total`, `llm_request_duration_seconds`, `llm_tokens_total` (if token usage is reported by the provider). Around every MCP tool call in the client, update `mcp_requests_total`. Do not change business logic.

- [ ] **Step 1: Add logger import to every file**

In each file above, add near the top:
```python
from common.logging import get_logger

log = get_logger(__name__)
```

- [ ] **Step 2: Instrument `providers/base.py`**

Read the file first. If it exposes a common `generate()`-like method, wrap it with timing + metric updates. If `base.py` is just a protocol/ABC, move the instrumentation into each concrete provider.

Pattern (concrete provider):
```python
import time

from common.metrics import (
    llm_request_duration_seconds,
    llm_requests_total,
    llm_tokens_total,
)

async def generate(self, prompt: str, ...) -> ...:
    start = time.perf_counter()
    status = "error"
    log.info("llm_call_start", provider="ollama", model=self.model)
    try:
        result = await self._call_upstream(prompt, ...)
        status = "ok"
        # If the provider returns token counts:
        if getattr(result, "prompt_tokens", None) is not None:
            llm_tokens_total.labels(
                provider="ollama", model=self.model, direction="input"
            ).inc(result.prompt_tokens)
        if getattr(result, "completion_tokens", None) is not None:
            llm_tokens_total.labels(
                provider="ollama", model=self.model, direction="output"
            ).inc(result.completion_tokens)
        return result
    except Exception:
        log.exception("llm_call_failed", provider="ollama", model=self.model)
        raise
    finally:
        elapsed = time.perf_counter() - start
        llm_requests_total.labels(
            provider="ollama", model=self.model, status=status
        ).inc()
        llm_request_duration_seconds.labels(
            provider="ollama", model=self.model
        ).observe(elapsed)
        log.info(
            "llm_call_end",
            provider="ollama",
            model=self.model,
            status=status,
            duration_ms=round(elapsed * 1000),
        )
```

Apply the analogous pattern to `openrouter_provider.py` with `provider="openrouter"`.

- [ ] **Step 3: Instrument `services/llm_service.py`**

Read the file. Wherever it picks a provider and invokes it, add:
- Log `INFO` at the start with chosen provider/model.
- On fallback, log `WARNING` with `event="llm_fallback"` and the reason.
- On handled error, log `ERROR` with exception context.
- Do not touch existing control flow.

- [ ] **Step 4: Instrument `clients/mcp_client.py`**

For each outbound tool call, wrap with:
```python
status = "error"
log.info("mcp_call_start", tool=tool_name)
try:
    result = await self._invoke(tool_name, args)
    status = "ok"
    return result
except Exception:
    log.exception("mcp_call_failed", tool=tool_name)
    raise
finally:
    mcp_requests_total.labels(tool=tool_name, status=status).inc()
    log.info("mcp_call_end", tool=tool_name, status=status)
```

- [ ] **Step 5: Smoke test imports**

```bash
PYTHONPATH=. python -c "
from providers.ollama_provider import *
from providers.openrouter_provider import *
from services.llm_service import *
from clients.mcp_client import *
print('ok')
"
```
Expected: `ok`.

- [ ] **Step 6: Commit**

```bash
git add providers/ services/llm_service.py clients/mcp_client.py
git commit -m "feat(logging): instrument providers, llm_service, mcp_client"
```

### Task 1.9: Pipeline instrumentation

**Files:**
- Modify: `unified_rtk_v2/pipeline/pipeline.py`

- [ ] **Step 1: Read the pipeline file and identify "steps"**

The spec calls for `pipeline_steps_total{step, status}`. Read `pipeline/pipeline.py` (461 lines) and enumerate the logical steps the code performs — e.g., `route`, `retrieve`, `plan`, `call_tools`, `generate`, `finalize`. Record the step names you find.

- [ ] **Step 2: Add logger and metric hooks**

At the top:
```python
from common.logging import get_logger
from common.metrics import pipeline_steps_total

log = get_logger(__name__)
```

Around each identified step, add:
```python
try:
    # existing step code
    pipeline_steps_total.labels(step="retrieve", status="ok").inc()
    log.info("pipeline_step", step="retrieve", status="ok")
except Exception:
    pipeline_steps_total.labels(step="retrieve", status="error").inc()
    log.exception("pipeline_step_failed", step="retrieve")
    raise
```

Keep the change surgical. If wrapping every step is too invasive at this phase, factor a tiny helper:
```python
from contextlib import contextmanager

@contextmanager
def _step(name: str):
    try:
        yield
        pipeline_steps_total.labels(step=name, status="ok").inc()
        log.info("pipeline_step", step=name, status="ok")
    except Exception:
        pipeline_steps_total.labels(step=name, status="error").inc()
        log.exception("pipeline_step_failed", step=name)
        raise
```
Then use `with _step("retrieve"):` at each step boundary.

- [ ] **Step 3: Smoke test import**

```bash
PYTHONPATH=. python -c "from pipeline.pipeline import *; print('ok')"
```

- [ ] **Step 4: Commit**

```bash
git add pipeline/pipeline.py
git commit -m "feat(logging): instrument pipeline steps"
```

### Task 1.10: Diff-review surgical merge — handle donor-only business logic changes

**Goal:** The diff between `unified_rtk_v2` and `rtk-feature-monitoring` shows divergence in these files beyond what Tasks 1.3–1.9 cover: `agent_api/main.py`, `clients/mcp_client.py`, `common/config.py`, `pipeline/pipeline.py`, `services/llm_service.py`, `Dockerfile`, `requirements.txt`, `.env`. For each, verify that the only remaining differences (after applying Tasks 1.3–1.9) are acceptable or bring in the donor's logging-only improvements.

- [ ] **Step 1: Produce per-file diffs**

Run for each file:
```bash
for f in agent_api/main.py clients/mcp_client.py common/config.py pipeline/pipeline.py services/llm_service.py Dockerfile requirements.txt; do
  echo "=== $f ==="
  diff -u /home/hokma/rtki_project/unified_rtk_v2/$f \
          /home/hokma/rtki_project/rtk-feature-monitoring/$f || true
done > /tmp/monitoring-diff.txt
wc -l /tmp/monitoring-diff.txt
```

- [ ] **Step 2: Classify each hunk**

Open `/tmp/monitoring-diff.txt`. For each hunk, classify:
- **L = logging/metrics only** (imports, `log.info`, `logger.exception`, metric increments) — already covered by Tasks 1.3–1.9. Skip.
- **O = observability config** (new env vars, config fields related to logging/metrics) — pull into v2 if not already present.
- **B = business logic change** — do NOT merge silently. STOP and ask the user (spec §6 pause point 1).
- **I = irrelevant** (formatting, unrelated docstrings) — skip.

- [ ] **Step 3: Pull in O-class hunks only**

For each O-class hunk, apply it manually to the v2 file.

- [ ] **Step 4: If any B-class hunk exists, STOP and report to user**

Report format:
```
Phase 1, Task 1.10: business-logic divergence found in <file>:<lines>. Donor has:
<code>
v2 has:
<code>
Question: should I merge donor's version, keep v2, or combine?
```

Do not proceed until the user answers.

- [ ] **Step 5: Commit if anything was pulled**

```bash
git add -A
git commit -m "feat(observability): pull config hooks from monitoring donor"
```
If nothing changed, skip the commit.

### Task 1.11: Phase 1 verification — bring the stack up

**Files:** none (runtime check)

- [ ] **Step 1: Build images**

```bash
cd /home/hokma/rtki_project/unified_rtk_v2
docker-compose build
```
Expected: all images build successfully.

- [ ] **Step 2: Up without monitoring profile**

```bash
docker-compose up -d
sleep 10
docker-compose ps
```
Expected: ollama, rag_mock, mcp_server, agent_api all healthy. Monitoring services NOT running.

- [ ] **Step 3: curl agent_api and capture trace_id**

```bash
TID=$(curl -s -D - http://localhost:8000/health 2>/dev/null | grep -i x-trace-id | awk '{print $2}' | tr -d '\r\n')
echo "trace_id=$TID"
```
If the health endpoint doesn't exist yet, curl an existing endpoint (check README or the main.py for the path). Expected: a UUID in the header.

- [ ] **Step 4: Check logs carry the trace_id**

```bash
docker-compose logs agent_api | grep "$TID" | head -3
```
Expected: at least one JSON log line containing that trace_id.

- [ ] **Step 5: Check `/metrics` endpoint**

```bash
curl -s http://localhost:8000/metrics | grep -E "^(http_requests_total|llm_requests_total|pipeline_steps_total)" | head
```
Expected: at least `http_requests_total` has a non-zero value for the path you just called.

- [ ] **Step 6: Bring monitoring profile up**

```bash
docker-compose --profile monitoring up -d
sleep 15
docker-compose --profile monitoring ps
```
Expected: prometheus, loki, promtail, grafana all healthy.

- [ ] **Step 7: Verify prometheus scrapes agent_api**

```bash
curl -s 'http://localhost:9090/api/v1/targets' | python -c "
import json, sys
data = json.load(sys.stdin)
for t in data['data']['activeTargets']:
    print(t['scrapeUrl'], t['health'])
"
```
Expected: at least one target with `health=up` pointing at `agent_api:8000/metrics`.

- [ ] **Step 8: Tear down**

```bash
docker-compose --profile monitoring down
```

- [ ] **Step 9: If anything failed, debug and fix in new commits**

Do not amend earlier commits. Each fix is a new commit on `grooming`.

- [ ] **Step 10: Record verification outcome**

Append to `/tmp/grooming-notes.txt`:
```
Phase 1 verification: PASS / FAIL (reason)
```

---

## Phase 2: Tests port

### Task 2.1: Copy test files from diplom/rtk

**Files:**
- Create: `unified_rtk_v2/tests/conftest.py` (from donor)
- Create: `unified_rtk_v2/tests/test_unit_models.py`
- Create: `unified_rtk_v2/tests/test_unit_pipeline.py`
- Create: `unified_rtk_v2/tests/test_integration_services.py`
- Create: `unified_rtk_v2/tests/test_api_contract.py`
- Create: `unified_rtk_v2/tests/test_e2e.py`
- Create: `unified_rtk_v2/pytest.ini`

- [ ] **Step 1: Copy files**

```bash
cd /home/hokma/rtki_project/unified_rtk_v2
for f in conftest.py test_unit_models.py test_unit_pipeline.py test_integration_services.py test_api_contract.py test_e2e.py; do
  cp /home/hokma/rtki_project/diplom/rtk/tests/$f tests/$f
done
cp /home/hokma/rtki_project/diplom/rtk/pytest.ini .
```

- [ ] **Step 2: Prune pytest.ini markers that reference excluded modules**

Edit `pytest.ini`. The donor's version references `experiments` in `testpaths` and has markers for `exvivo`, `fault`, `overhead`. We do not port experiments. Replace the file with:
```ini
[pytest]
asyncio_mode = auto
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
markers =
    unit: unit tests
    integration: integration tests
    contract: API contract tests
    e2e: end-to-end smoke tests (skipped by default)
    slow: slow running tests
addopts = -m "not e2e"
```

The `addopts = -m "not e2e"` line ensures `pytest` without flags does NOT run e2e. To run e2e: `pytest -m e2e`.

- [ ] **Step 3: Commit (tests may be red at this point — that is expected)**

```bash
git add tests/ pytest.ini
git commit -m "test: port test files from diplom/rtk (adaptations follow)"
```

### Task 2.2: Run tests and categorize failures

- [ ] **Step 1: Run the whole non-e2e suite**

```bash
cd /home/hokma/rtki_project/unified_rtk_v2
PYTHONPATH=. pytest 2>&1 | tee /tmp/phase2-run1.txt | tail -60
```

- [ ] **Step 2: Count and categorize**

For each failure in `/tmp/phase2-run1.txt`:
- **ImportError / ModuleNotFoundError** → fix in Task 2.3 (adapt imports).
- **AttributeError / TypeError (API mismatch)** → fix in Task 2.4 (adapt to v2 API).
- **Test needs fixture from experiments/** → delete the test in Task 2.5.
- **Test hits real Ollama / real OpenRouter** → rewrite with mock in Task 2.6.

Record the per-category counts.

- [ ] **Step 3: Check the 30% threshold**

If `(failed + errored) / total > 0.30`, STOP and report to the user (spec §6 pause point 2). Do not start adaptation until the user decides.

If under 30%, proceed.

### Task 2.3: Fix import paths

**Files:** whichever tests fail with ImportError.

- [ ] **Step 1: For each failing import, map diplom → v2**

Example: if a test does `from rtk.common.models import Foo` and v2 uses `from common.models import Foo`, replace. v2 module names are identical to diplom's (`common`, `providers`, `services`, `pipeline`, `agent_api`, `clients`), so most likely only the top-level prefix differs.

Check what prefix the tests currently use:
```bash
grep -h '^from \|^import ' tests/*.py | sort -u
```

Apply a consistent rewrite.

- [ ] **Step 2: Re-run**

```bash
PYTHONPATH=. pytest 2>&1 | tail -30
```

- [ ] **Step 3: Commit**

```bash
git add tests/
git commit -m "test: adapt imports to v2 module layout"
```

### Task 2.4: Fix API mismatches

For each AttributeError/TypeError failure:
- **The test is wrong (v2 has a better API):** rewrite the test call. v2 is source of truth.
- **The test is right and v2 is buggy:** do NOT change v2 here. Note the bug in `/tmp/grooming-notes.txt` for Phase 3, and mark the test `@pytest.mark.skip(reason="fixed in grooming phase 3")`.

- [ ] **Step 1: Work through each failure**

- [ ] **Step 2: Re-run**

```bash
PYTHONPATH=. pytest 2>&1 | tail -30
```

- [ ] **Step 3: Commit**

```bash
git add tests/
git commit -m "test: adapt call sites to v2 API"
```

### Task 2.5: Delete tests that depend on excluded modules

- [ ] **Step 1: grep for experiments imports**

```bash
grep -rn 'experiments' tests/
```

- [ ] **Step 2: Delete tests/fixtures that reference them**

Delete individual test functions (not entire files) when possible. If a whole file is experiments-only, delete the file.

- [ ] **Step 3: Re-run and commit**

```bash
PYTHONPATH=. pytest 2>&1 | tail -20
git add -A
git commit -m "test: drop tests depending on experiments module (not ported)"
```

### Task 2.6: Mock all real LLM/network calls in unit+integration tests

**Rule:** no unit or integration test may make a real network call. e2e tests are allowed to.

- [ ] **Step 1: Find suspicious calls**

```bash
grep -rn 'httpx\|requests\.\|ollama\|openrouter' tests/ | grep -v mock | grep -v 'respx\|pytest_httpx'
```

- [ ] **Step 2: Rewrite each with `pytest-httpx` mocks**

Pattern:
```python
def test_something(httpx_mock):
    httpx_mock.add_response(
        url="http://localhost:11434/api/chat",
        json={"message": {"content": "mocked"}},
    )
    # ... call code under test
```

For Ollama provider tests, mock at the HTTP level. For OpenRouter, same.

- [ ] **Step 3: Re-run**

```bash
PYTHONPATH=. pytest 2>&1 | tail -20
```
Expected: all unit+integration tests green.

- [ ] **Step 4: Commit**

```bash
git add tests/
git commit -m "test: mock all external LLM/network calls"
```

### Task 2.7: Phase 2 verification

- [ ] **Step 1: Unit run**

```bash
PYTHONPATH=. pytest -q 2>&1 | tail -5
```
Expected: all passing, exit 0.

- [ ] **Step 2: Integration run**

```bash
PYTHONPATH=. pytest -m integration -q 2>&1 | tail -5
```
Expected: passing.

- [ ] **Step 3: e2e run — only if docker stack is up**

```bash
docker-compose up -d
sleep 10
PYTHONPATH=. pytest -m e2e -q 2>&1 | tail -10
docker-compose down
```
If e2e fails, note in `/tmp/grooming-notes.txt` and fix during Phase 3 or Phase 4.

- [ ] **Step 4: Confirm every main module has at least one passing test**

```bash
for mod in providers services pipeline agent_api; do
  n=$(grep -rl "from $mod\|import $mod" tests/ | wc -l)
  echo "$mod: $n test files reference it"
done
```
If any module is at zero, write one trivial unit test for it (e.g. import-and-instantiate) before proceeding.

- [ ] **Step 5: Append to notes**

```
Phase 2 verification: PASS / partial (e2e issues)
```

---

## Phase 3: Grooming pass (level B)

**General loop for every module task below:**

1. Read the module files end-to-end.
2. Apply the per-module checklist (reproduced inline in each task — do not skim across tasks).
3. Run `pytest` (unit + integration). Must be green.
4. Run `ruff check <module_path>`. Must be clean.
5. Commit with message: `refactor(<module>): grooming pass` + a one-line summary of what was removed/changed.

**Hard rules for all Phase 3 tasks:**
- Do not reorganize packages (no moving files between modules, no merging/splitting files).
- Do not change inter-service protocols (HTTP schemas, MCP tool signatures).
- Public function signatures may change if it clearly improves the code — but tests must be updated in the same commit.
- If a module needs a rewrite beyond level B, STOP and report (spec §6 pause point 3).
- Re-use the inline checklist; do not infer it from memory.

**Inline checklist (apply to every module):**

**Remove:**
- Unused imports, functions, classes, constants, fields, parameters, env vars (grep the whole repo + tests).
- Commented-out code.
- `print`, `pdb`, debug dumps.
- Dead references to the OLD metric names (`agent_requests_total`, `tool_calls_total`, `llm_fallback_total`, `agent_latency_seconds`).

**Dangerous spots and weak logic:**
- Narrow bare `except:` / `except Exception:` — add log + specific exception types.
- No silently swallowed errors. Every `except` either re-raises, returns a controlled fallback with a log, or is explicitly a debug-level swallow with a justification comment.
- All file / HTTP / DB resources inside `with`.
- All `requests` / `httpx` calls have explicit timeouts.
- No sync `requests` inside async code — migrate to `httpx.AsyncClient`.
- No hardcoded secrets or URLs — push into `common/config.py`.
- HTTP endpoints validate input via Pydantic models, not hand-rolled checks.
- Audit shared async state for races.
- No string-concatenation SQL or shell commands.

**Simplify / dedupe:**
- Pull repeated "setup client → call → parse → handle error" blocks into a helper.
- Flatten conditional nesting deeper than 3 via early return or extracted function.
- Remove unused config flags.

**Normalize:**
- Type hints on every public function and method.
- 1-line docstrings on public functions/classes; multiline only when non-obvious.
- One consistent error-handling style per module.

**Backfill observability (gap-fill from Phase 1):**
- For every non-trivial public function, verify it has the log points from the spec §Phase 1 policy.
- For every provider/service call, verify a metric is incremented.

### Task 3.1: Groom `common/`

**Files:**
- Modify: `unified_rtk_v2/common/config.py`
- Modify: `unified_rtk_v2/common/models.py`
- Modify: `unified_rtk_v2/common/metrics.py` (light — just verify)
- Modify: `unified_rtk_v2/common/logging.py` (light — just verify)
- Modify: `unified_rtk_v2/common/middleware.py` (light — just verify)

- [ ] **Step 1: Apply checklist to `common/config.py`**

Known issues to check and fix:
- Pydantic v2 deprecation: `Field(..., env="FOO")` is deprecated. Use `model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)` and drop `env=` kwargs (field name alone works with `BaseSettings`).
- The `llm_mode` post-processing in `get_settings()` silently downgrades invalid values. Log a warning instead.
- Audit each field: is it actually referenced? grep the codebase.

- [ ] **Step 2: Apply checklist to `common/models.py`**

Read and apply the checklist. Likely findings: unused imports, unused model fields, missing type hints on helper methods if any.

- [ ] **Step 3: Run tests**

```bash
PYTHONPATH=. pytest 2>&1 | tail -10
```

- [ ] **Step 4: Run ruff**

```bash
ruff check common/
```
Fix any findings.

- [ ] **Step 5: Commit**

```bash
git add common/
git commit -m "refactor(common): grooming pass (config pydantic v2, normalize types)"
```

### Task 3.2: Groom `providers/`

**Files:**
- Modify: `unified_rtk_v2/providers/base.py`
- Modify: `unified_rtk_v2/providers/ollama_provider.py`
- Modify: `unified_rtk_v2/providers/openrouter_provider.py`
- Modify: `unified_rtk_v2/providers/__init__.py`

- [ ] **Step 1: Apply full checklist to each file**

Likely deduplication target: if both `ollama_provider` and `openrouter_provider` share timing+metric+log boilerplate around the outbound call (added in Task 1.8), extract into a method on `BaseProvider` or a helper `providers/_instrumentation.py`. Remove the duplication only if the two providers had *identical* boilerplate; if they differ, leave them.

- [ ] **Step 2: Run tests + ruff**

```bash
PYTHONPATH=. pytest 2>&1 | tail -10
ruff check providers/
```

- [ ] **Step 3: Commit**

```bash
git add providers/
git commit -m "refactor(providers): grooming pass (dedupe instrumentation boilerplate)"
```

### Task 3.3: Groom `clients/`

**Files:**
- Modify: `unified_rtk_v2/clients/mcp_client.py`
- Modify: `unified_rtk_v2/clients/__init__.py`

- [ ] **Step 1: Apply full checklist**

211-line `mcp_client.py`: likely candidates — bare excepts around connection logic, no timeouts on stdio reads, missing type hints on internal helpers.

- [ ] **Step 2: Tests + ruff**

```bash
PYTHONPATH=. pytest 2>&1 | tail -10
ruff check clients/
```

- [ ] **Step 3: Commit**

```bash
git add clients/
git commit -m "refactor(clients): grooming pass"
```

### Task 3.4: Groom `services/rag_mock/` and `services/mcp_server/`

**Files:**
- Modify: `unified_rtk_v2/services/rag_mock/main.py`
- Modify: `unified_rtk_v2/services/mcp_server/mcp_server.py`
- Modify: `unified_rtk_v2/services/mcp_server/models.py`
- Modify: `unified_rtk_v2/services/mcp_server/services.py`
- Modify: `unified_rtk_v2/services/mcp_server/storage.py`

- [ ] **Step 1: Apply full checklist to each**

Known candidate: `services/mcp_server/storage.py` is tiny (33 lines) — verify it isn't trivially replaceable by an inline dict.

- [ ] **Step 2: Tests + ruff**

```bash
PYTHONPATH=. pytest 2>&1 | tail -10
ruff check services/
```

- [ ] **Step 3: Commit**

```bash
git add services/
git commit -m "refactor(services): grooming pass for rag_mock and mcp_server"
```

### Task 3.5: Groom `services/llm_service.py`

**Files:**
- Modify: `unified_rtk_v2/services/llm_service.py`

246 lines — the largest service file. Candidates: fallback handling, retry logic, prompt construction.

- [ ] **Step 1: Apply full checklist**

- [ ] **Step 2: If the file contains retry logic rolled by hand, verify:**
- Retries have an upper bound.
- Backoff is present (even if fixed).
- Each retry logs a `WARNING` with `event="llm_retry"`.
- Final failure logs `ERROR`.

- [ ] **Step 3: Tests + ruff**

```bash
PYTHONPATH=. pytest 2>&1 | tail -10
ruff check services/llm_service.py
```

- [ ] **Step 4: Commit**

```bash
git add services/llm_service.py
git commit -m "refactor(llm_service): grooming pass"
```

### Task 3.6: Groom `pipeline/`

**Files:**
- Modify: `unified_rtk_v2/pipeline/pipeline.py`
- Modify: `unified_rtk_v2/pipeline/rag_models.py`

461 lines. This is the largest file and the most likely candidate for an "escalate to C" pause.

- [ ] **Step 1: Read the file completely**

- [ ] **Step 2: Decide: does it fit level B?**

If the file is one coherent workflow with clearly separable steps — proceed with level B.

If the file is a tangle of intertwined responsibilities that need reorganization — STOP. Report to user with:
```
Phase 3, Task 3.6: pipeline/pipeline.py exceeds level B.
Findings: <bullet list of concerns>
Question: escalate to level C for this module only?
```

- [ ] **Step 3: If proceeding, apply full checklist**

Likely candidates: deeply nested tool-call loops, bare excepts in retry logic, silent fallbacks, long functions that can be split into helpers.

- [ ] **Step 4: Tests + ruff**

```bash
PYTHONPATH=. pytest 2>&1 | tail -10
ruff check pipeline/
```

- [ ] **Step 5: Commit**

```bash
git add pipeline/
git commit -m "refactor(pipeline): grooming pass"
```

### Task 3.7: Groom `agent_api/`

**Files:**
- Modify: `unified_rtk_v2/agent_api/main.py`

147 lines. Should be manageable.

- [ ] **Step 1: Apply full checklist**

- [ ] **Step 2: Tests + ruff**

```bash
PYTHONPATH=. pytest 2>&1 | tail -10
ruff check agent_api/
```

- [ ] **Step 3: Commit**

```bash
git add agent_api/
git commit -m "refactor(agent_api): grooming pass"
```

### Task 3.8: Groom root files

**Files:**
- Modify: `unified_rtk_v2/Dockerfile`
- Modify: `unified_rtk_v2/docker-compose.yml`
- Modify: `unified_rtk_v2/requirements.txt`
- Modify: `unified_rtk_v2/README.md`

- [ ] **Step 1: requirements.txt — prune unused**

For each package in `requirements.txt`:
```bash
pkg="fastapi"
grep -r "import $pkg\|from $pkg" --include='*.py' --exclude-dir=venv --exclude-dir=tests | head -1
```
If grep returns nothing for a runtime dep, delete it. Do NOT delete `uvicorn`, `python-dotenv`, or other runtime-only deps even if not imported — they are executed.

- [ ] **Step 2: Dockerfile — review**

Checklist: single-stage is fine, but verify: (a) pinned base image tag; (b) `requirements.txt` copied and installed *before* the rest, for layer caching; (c) no `apt-get` without `--no-install-recommends`; (d) non-root user if not already.

- [ ] **Step 3: docker-compose.yml — final review**

Verify: (a) all services have `restart: unless-stopped`; (b) healthchecks on every python service; (c) `SERVICE_NAME`/`LOG_LEVEL` env on every python service; (d) monitoring profile still gates the new services.

- [ ] **Step 4: README.md — rewrite the relevant sections**

Ensure the README documents:
- Quickstart: `cp .env.example .env && docker-compose up`.
- Monitoring: `docker-compose --profile monitoring up`.
- Running tests: `pytest` / `pytest -m integration` / `pytest -m e2e`.
- Env var reference (pointing to `.env.example`).

- [ ] **Step 5: Build and run**

```bash
docker-compose build
docker-compose up -d && sleep 8 && docker-compose ps
docker-compose down
```
Expected: all healthy.

- [ ] **Step 6: Commit**

```bash
git add Dockerfile docker-compose.yml requirements.txt README.md
git commit -m "refactor(root): grooming pass for Dockerfile, compose, requirements, README"
```

### Task 3.9: Create `.env.example`

**Files:**
- Create: `unified_rtk_v2/.env.example`
- Modify: `unified_rtk_v2/.gitignore` (ensure `.env` is ignored)

- [ ] **Step 1: Enumerate env vars**

```bash
grep -rhn 'os\.getenv\|Field(.*env=\|BaseSettings' common/ services/ agent_api/ providers/ clients/ pipeline/ 2>/dev/null | grep -oE '[A-Z][A-Z0-9_]{2,}' | sort -u
```

- [ ] **Step 2: Write `.env.example`**

```env
# Service identification (set per-service in docker-compose)
SERVICE_NAME=agent_api
LOG_LEVEL=INFO

# LLM provider selection
LLM_PROVIDER=openrouter          # openrouter | ollama
LLM_MODEL_NAME=qwen2.5:7b-instruct
LLM_API_KEY=                      # required for openrouter
LLM_MODE=tools                    # tools | json | fallback
LLM_MAX_ITERATIONS=6
LLM_TIMEOUT_SECONDS=30

# Ollama endpoint (when LLM_PROVIDER=ollama)
OLLAMA_HOST=http://ollama:11434

# RAG
RAG_BASE_URL=http://rag_mock:8090

# Agent runtime
REQUEST_TIME_BUDGET_SECONDS=90
ALLOW_QUEUE_CHANGE=false

# Debug
DEBUG=false
MCP_DEBUG=false
```

Adjust the list so it matches exactly the vars found in Step 1.

- [ ] **Step 3: Check `.gitignore`**

```bash
grep -E '^\.env$' .gitignore || echo ".env" >> .gitignore
```

- [ ] **Step 4: Commit**

```bash
git add .env.example .gitignore
git commit -m "docs: add .env.example and ensure .env gitignored"
```

### Task 3.10: Final ruff sweep

- [ ] **Step 1: Run ruff on the whole repo**

```bash
ruff check . --exclude venv --exclude docs
```

- [ ] **Step 2: Fix remaining issues**

For each finding, fix in the relevant module. Commit per module.

- [ ] **Step 3: Run ruff format (optional, safe)**

```bash
ruff format . --exclude venv --exclude docs
```
Review the diff. If it is just whitespace / quoting normalization, commit:
```bash
git add -A
git commit -m "style: ruff format"
```

---

## Phase 4: Verification

### Task 4.1: Full local verification

- [ ] **Step 1: Static**

```bash
cd /home/hokma/rtki_project/unified_rtk_v2
ruff check . --exclude venv --exclude docs
find . -name '*.py' -not -path './venv/*' -not -path './docs/*' -exec python -m py_compile {} +
```
Expected: both clean.

- [ ] **Step 2: Tests — unit**

```bash
PYTHONPATH=. pytest -q
```
Expected: green.

- [ ] **Step 3: Tests — integration**

```bash
PYTHONPATH=. pytest -m integration -q
```
Expected: green.

- [ ] **Step 4: Docker build**

```bash
docker-compose build
```
Expected: success.

- [ ] **Step 5: Up without monitoring**

```bash
docker-compose up -d
sleep 10
docker-compose ps
```
Expected: all healthy.

- [ ] **Step 6: Smoke e2e**

```bash
TID=$(uuidgen)
curl -s -H "X-Trace-Id: $TID" -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "hello"}' | head -5
```
(Adjust URL/payload to match actual agent_api schema — read `agent_api/main.py` for the correct endpoint.)

Expected: a valid JSON response.

- [ ] **Step 7: Tests — e2e**

```bash
PYTHONPATH=. pytest -m e2e -q
```
Expected: green.

- [ ] **Step 8: Up with monitoring**

```bash
docker-compose down
docker-compose --profile monitoring up -d
sleep 15
docker-compose --profile monitoring ps
```
Expected: everything healthy.

- [ ] **Step 9: Verify loki has the trace**

```bash
curl -s -G 'http://localhost:3100/loki/api/v1/query_range' \
  --data-urlencode "query={service=\"agent_api\"}" \
  --data-urlencode 'limit=5' | head -c 500
```
Expected: log entries (fall back to `docker-compose logs agent_api | grep "$TID"` if the loki query schema differs).

- [ ] **Step 10: Verify prometheus scrapes**

```bash
curl -s 'http://localhost:9090/api/v1/query?query=http_requests_total' | head -c 500
```
Expected: non-empty result with the new metric.

- [ ] **Step 11: Grafana dashboard check (manual)**

Open `http://localhost:3000` in a browser. Log in (default admin/admin). Verify the dashboard from `JSON Model.txt` is present. If panels are empty, the dashboard references old metric names — update the dashboard JSON to match the new metric set. Commit the fix.

- [ ] **Step 12: Tear down**

```bash
docker-compose --profile monitoring down
```

### Task 4.2: Fresh-clone simulation

- [ ] **Step 1: Clone to a scratch location**

```bash
git -C /home/hokma/rtki_project/unified_rtk_v2 archive grooming | tar -x -C /tmp/rtki-clone-check
```
(Use `git archive` to simulate a clean checkout without touching the real clone.)

- [ ] **Step 2: Build and up**

```bash
cd /tmp/rtki-clone-check
cp .env.example .env
docker-compose build
docker-compose up -d && sleep 10 && docker-compose ps
docker-compose down
rm -rf /tmp/rtki-clone-check
```
Expected: clean bring-up. If anything is missing, fix in `unified_rtk_v2` and commit.

### Task 4.3: Final summary commit

- [ ] **Step 1: Write a summary note**

Append to `/home/hokma/rtki_project/unified_rtk_v2/docs/superpowers/specs/2026-04-10-rtki-grooming-design.md`:

```markdown

---

## Execution summary (filled in at end of Phase 4)

- **Branch:** grooming
- **Commits:** <count> (see `git log master..grooming --oneline`)
- **Lines removed / added:** <from `git diff --shortstat master..grooming`>
- **Tests:** <count passing> unit, <count> integration, <count> e2e
- **Known issues carried over:** <list any skipped tests or deferred fixes>
```

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/specs/2026-04-10-rtki-grooming-design.md
git commit -m "docs: record grooming execution summary"
```

- [ ] **Step 3: Do NOT merge or push**

Report to the user:
```
Grooming complete on branch `grooming`. Nothing pushed.
Diff stat: <paste `git diff --shortstat master..grooming`>
Ready for user review. Merge decision deferred.
```

---

## Pause points (quick reference)

From spec §6 — stop and ask the user if any of these occur:

1. Business-logic divergence between v2 and monitoring donor — Task 1.10.
2. More than 30% of ported tests fail after import adaptation — Task 2.2.
3. A module needs rework beyond level B — Task 3.6 (likely), possibly any Phase 3 task.
4. Anything requiring a move outside the declared out-of-scope list.
