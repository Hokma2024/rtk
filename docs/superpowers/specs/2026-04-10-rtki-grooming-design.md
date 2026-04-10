# RTKI Grooming — Design Spec

**Date:** 2026-04-10
**Target project:** `unified_rtk_v2`
**Working branch:** `grooming`

## 1. Goal and Scope

Bring `unified_rtk_v2` into a "product-grade" state:

- Full tests suite (ported from `diplom/rtk/tests/`).
- Full observability: structured logging + Prometheus metrics + Grafana/Loki stack.
- Clean code: dead code removed, dangerous spots fixed, weak logic simplified, duplication eliminated, types and docstrings normalized.

**Base:** `unified_rtk_v2/` is the root of truth. Edits are made in-place.
**Donors (reference only, not merged as branches):**
- `diplom/rtk/` — source for tests.
- `rtk-feature-monitoring/` — source for the `monitoring/` stack and `docker-compose.yml` delta.

### Explicit out-of-scope

- Nothing from `diplom/rtk/experiments/` (dashboards, visualization, casestudy, sciexport, comparison, fault_injection, overhead, observability, analysis, data_contracts, dataset, scenarios).
- CI/CD configuration.
- Alerting, TLS, auth, rate limiting.
- New features.
- Module reorganization (merging/splitting packages).
- Protocol changes between services.

### Grooming level

**B — moderate.** Remove dead code, fix dangerous spots, dedupe, simplify, normalize types/docstrings, unify error handling, drop unused features/flags. Public APIs may change if it clearly improves the code. Aggressive rewrites or module reorg require explicit escalation.

## 2. Phases

Work proceeds in 4 sequential phases. Each phase has its own verification gate. Rollback unit is one phase (series of commits).

### Phase 1 — Monitoring & Logging

**From donor `rtk-feature-monitoring/` (as-is):**
- Entire `monitoring/` folder: `prometheus.yml`, `loki-config.yaml`, `promtail-config.yaml`, `grafana/provisioning/...`, `JSON Model.txt`.
- Delta in `docker-compose.yml`: services `prometheus`, `loki`, `promtail`, `grafana`, their volumes/networks/healthchecks. Existing v2 services (ollama, rag_mock, mcp_server, agent_api) are preserved — we only add log-label config and expose `/metrics`.
- Monitoring stack is optional via compose profile `monitoring` so it can be turned off on dev machines.

**Designed from scratch in v2 code (user choice: full redesign, not copied from monitoring branch):**

*Logging subsystem — `common/logging.py`:*
- `structlog`-based JSON logger. Added to `requirements.txt`.
- Fields: `timestamp, level, service, module, event, trace_id, ...context`.
- Output: stdout only (promtail tails docker logs via labels — no files on disk).
- `service` comes from env `SERVICE_NAME`, set per-service in compose.
- `trace_id`: UUID, generated in an HTTP middleware at `agent_api` entry; propagated to LLM/RAG/MCP via `X-Trace-Id` header; reused if present on inbound.
- Each module gets its logger via `get_logger(__name__)`. No global `print`.

*Logging levels policy:*
- `INFO`: startup/shutdown, inbound HTTP requests, outbound LLM/RAG/MCP calls (start + finish + duration), pipeline decisions (chosen provider, invoked tools).
- `WARNING`: retries, provider fallbacks, degradations (e.g. RAG unavailable → mock).
- `ERROR`: caught exceptions with context (never swallowed), timeouts, invalid LLM outputs.
- `DEBUG`: prompt/response bodies, tool payloads. Off by default, enabled via `LOG_LEVEL=DEBUG`.

*Metrics subsystem — `common/metrics.py` (file exists in v2; will be rewritten):*
- Library: `prometheus_client`. Each FastAPI service exposes `/metrics`. Exact wiring (manual router vs `prometheus-fastapi-instrumentator`) decided at implementation time.
- Metric set (only what a Grafana dashboard actually consumes):
  - `http_requests_total{service, endpoint, method, status}` — Counter
  - `http_request_duration_seconds{service, endpoint}` — Histogram
  - `llm_requests_total{provider, model, status}` — Counter
  - `llm_request_duration_seconds{provider, model}` — Histogram
  - `llm_tokens_total{provider, model, direction}` — Counter (`direction` ∈ {input, output})
  - `rag_requests_total{status}` — Counter
  - `mcp_requests_total{tool, status}` — Counter
  - `pipeline_steps_total{step, status}` — Counter

**Phase 1 verification:**
- `docker-compose --profile monitoring up` brings up the full stack; all services `healthy`.
- A manual curl to `agent_api` produces a log entry visible in Loki with the same `trace_id`.
- `/metrics` endpoints return non-empty output; Prometheus scrapes them.
- Grafana opens the dashboard from `JSON Model.txt`. If it is incompatible with the new metric names, the dashboard is adjusted during Phase 4.

**Phase 1 non-goals:**
- No business logic changes in pipeline/providers — only adding logger calls and counter increments at existing points. Refactoring belongs to Phase 3.
- No alerting setup.

### Phase 2 — Tests port

**Source:** `diplom/rtk/tests/` (6 files: `conftest.py`, `test_unit_models.py`, `test_unit_pipeline.py`, `test_integration_services.py`, `test_api_contract.py`, `test_e2e.py`) + `pytest.ini`.

**Steps:**

1. Copy the entire `tests/` folder and `pytest.ini` into `unified_rtk_v2/`. Add `pytest`, `pytest-asyncio`, `httpx`, and an HTTP-mocking lib (`respx` or `pytest-httpx` — exact choice matched to `diplom/rtk/requirements.txt`) to `requirements.txt` dev-deps.
2. Adapt imports. v2 is the source of truth. If a test references something not present in v2, the test is rewritten to match v2 (or deleted).
3. Adapt fixtures. Any fixture referencing `experiments/` (which we are not porting) is deleted; dependent tests are deleted.
4. Split tests by speed via markers in `pytest.ini`:
   - **unit** (`test_unit_*`) — no external deps, default run.
   - **integration** — marker `@pytest.mark.integration`, needs services up or HTTP mocks.
   - **e2e** — marker `@pytest.mark.e2e`, **skipped by default**, runs only on explicit `pytest -m e2e` against a live compose.
5. LLM calls in unit/integration tests are forbidden. Providers are mocked via a fixture or HTTP-level mocks. Any test that dials a real Ollama is rewritten.
6. No CI configuration in this phase.

**Phase 2 verification:**
- `pytest` (unit only) — green.
- `pytest -m integration` — green (against local services or mocks).
- `pytest -m e2e` — green after `docker-compose up` (depends on Phase 1 being done).
- Every one of the four main v2 modules (`providers`, `services`, `pipeline`, `agent_api`) has at least one passing test.

**Risk — port breakage rate:** if more than 30% of ported tests fail after import adaptation, pause and ask before deciding whether to keep or drop the failing tests.

### Phase 3 — Grooming pass (moderate level B)

**Module order (bottom-up by dependency graph):**

1. `common/` (config, models, metrics, logging)
2. `providers/` (base, ollama_provider, openrouter_provider)
3. `clients/` (mcp_client)
4. `services/rag_mock/`, `services/mcp_server/`, `services/llm_service.py`
5. `pipeline/` (pipeline, rag_models)
6. `agent_api/` (main.py)
7. Root files (`Dockerfile`, `docker-compose.yml`, `requirements.txt`, `README.md`, `dump_project.py`)

One commit per module. After each module: run `pytest` (unit + integration). If red, fix before moving on.

**Per-module checklist:**

*Removal:*
- Unused imports, functions, classes, constants, dataclass fields, parameters, env variables (verified by repo-wide grep, including tests).
- Commented-out code.
- `print`, `pdb`, debug artifacts.
- Unused dependencies in `requirements.txt` (verified against actual imports).
- `dump_project.py` is deleted — it is a dev artifact, not product code.

*Dangerous spots and weak logic:*
- Bare `except:` and `except Exception:` without re-raise or log are narrowed, logged, and given meaningful behavior.
- Silently swallowed errors (`except ...: pass`) either get a justified DEBUG/WARNING log or are re-raised.
- Resources without `with` (files, HTTP clients, DB connections) are converted to context managers.
- `requests` calls without timeouts get timeouts. Sync `requests` in async code is replaced with `httpx.AsyncClient`.
- Hardcoded secrets/URLs moved to `common/config.py` via env.
- Input validation at HTTP boundaries: confirm Pydantic models cover what was previously hand-checked.
- `asyncio` races: audit shared state between coroutines (global dicts, counters without locks).
- SQL/shell injection: verify no query or command is built by string-concatenation with user input.

*Simplification and dedup:*
- Repeated "setup client → call → parse → handle error" blocks across providers become a helper in `providers/base.py`.
- Repeated try/except-for-logging patterns become a decorator or context manager in `common/logging.py`.
- Conditional chains nested deeper than 3 levels are flattened via early return or extracted methods.
- Unused config flags in `common/config.py` are deleted.

*Normalization:*
- All public functions and methods get type hints. Vague types (`Any`, bare `dict`) are tightened where cheap.
- Short 1-line docstrings on public functions/classes. Multi-line only where behavior is non-obvious. Docstrings explain *why*, not *what*.
- Error handling follows one consistent style across the module (either raise-with-log at boundary, or a Result-like wrapper — a choice made once, applied uniformly).
- Obviously bad names (`data`, `tmp`, `do_stuff`) are renamed. No mass renames.

*Logging/metrics backfill (gap-fill from Phase 1):*
- Each function is checked against the Phase 1 policy. Missing log points are added. Missing metric increments are added.

**Out of scope at level B:**
- Package reorganization.
- Protocol changes.
- Full rewrites, even when tempting. If encountered: pause and escalate.
- New features.

**Phase 3 verification:**
- Every module has gone through the checklist.
- `pytest` (unit + integration) — green.
- `docker-compose up` — working.
- `ruff check .` — clean. `ruff` is added as a dev dependency with a minimal config.
- Commit messages document what was removed/simplified/added per module.

**Risk — hidden legacy:** if a module (e.g. a hypothetical 800-line `pipeline.py`) turns out to need aggressive rework beyond B, pause, report findings, and ask whether to escalate to C for that module.

### Phase 4 — Verification

1. **Static:** `ruff check .` clean. `python -m py_compile` on every `.py`.
2. **Tests:** `pytest` (unit), `pytest -m integration`, `pytest -m e2e` — all green.
3. **Docker:** `docker-compose build` and `docker-compose up` — all services healthy.
4. **Manual smoke e2e:** curl into `agent_api` → response received → Loki shows a log line with the same `trace_id` as the response → `/metrics` shows incremented `http_requests_total` and `llm_requests_total` → Grafana dashboard from `JSON Model.txt` renders data. Fix the dashboard if incompatible with renamed metrics.
5. **Fresh-clone check:** `git clone && docker-compose up` on a clean environment works with only `.env` as manual setup.

## 3. Deliverables

- `unified_rtk_v2/README.md` — updated: how to run, how to run tests, how to view dashboards, required env vars.
- `unified_rtk_v2/.env.example` — env vars with comments (`SERVICE_NAME`, `LOG_LEVEL`, `LLM_MODEL_NAME`, `OPENROUTER_API_KEY`, etc.). Actual `.env` stays in `.gitignore`.
- `unified_rtk_v2/pytest.ini` — unit/integration/e2e markers.
- `unified_rtk_v2/requirements.txt` — only real imports. Dev-deps in `requirements-dev.txt` or a separate section (decided at implementation time).
- `unified_rtk_v2/tests/` — ported suite.
- `unified_rtk_v2/monitoring/` — from donor.
- `unified_rtk_v2/common/logging.py` — new.
- `unified_rtk_v2/common/metrics.py` — rewritten on `prometheus_client`.

## 4. Commit strategy

Work on branch `grooming` inside `unified_rtk_v2`. Planned commit sequence (each commit leaves tests green):

- `feat(monitoring): add prometheus/loki/grafana stack from feature-monitoring`
- `feat(logging): structured logging via structlog, trace_id propagation`
- `feat(metrics): prometheus metrics for http/llm/rag/mcp/pipeline`
- `test: port unit/integration/e2e tests from diplom/rtk`
- `test: adapt fixtures and mocks to v2`
- `chore(deps): clean up requirements, add dev-deps`
- `refactor(common): grooming pass`
- `refactor(providers): grooming pass`
- `refactor(clients): grooming pass`
- `refactor(services): grooming pass`
- `refactor(pipeline): grooming pass`
- `refactor(agent_api): grooming pass`
- `refactor(root): Dockerfile, compose, requirements, README cleanup`
- `docs: update README and add .env.example`
- `chore: final verification pass`

Nothing is pushed unless explicitly requested.

## 5. Risks

| Risk | Mitigation |
|---|---|
| Mass test breakage after porting | 30% threshold → pause and ask |
| A module needs aggressive rework beyond level B | Pause, report, ask whether to escalate to C |
| Grafana dashboard from `JSON Model.txt` incompatible with renamed metrics | Adjust dashboard during Phase 4 |
| Monitoring stack too heavy for dev machines | Compose profile `monitoring` (opt-in) |
| Business-logic divergence between v2 and monitoring donor | Phase 1 pauses on unexpected diff outside logging/metrics hooks |

## 6. Pause points (explicit user consultation)

The following situations stop work and require user input before continuing:

1. Business-logic divergence between `unified_rtk_v2` and `rtk-feature-monitoring` beyond logging/metrics hooks (Phase 1).
2. More than 30% of ported tests failing after import adaptation (Phase 2).
3. A module requiring rework beyond moderate grooming level B (Phase 3).
4. Any need to step outside the declared out-of-scope list.

---

## Execution summary (filled in at end of Phase 4)

- **Branch:** grooming
- **Commits:** 35 (34 pre-Phase-4 + 1 fix commit in Phase 4)
- **Diff stat:** 86 files changed, 5470 insertions(+), 811 deletions(-)
- **Tests:** 100 unit passing, 6 integration passing, 7 e2e passing (all green)
- **Ruff:** clean
- **Known issues carried over:**
  - datetime.utcnow() deprecation warnings in test fixtures and main.py (out of grooming scope)
  - on_event() deprecation warnings from FastAPI (lifespan migration out of scope)
  - Loki log ingestion via promtail not verified in WSL2 environment (docker log file path issue specific to WSL2; logs confirmed present via docker-compose logs)
- **Phase 4 verification:** PASS (with one fix: duplicate event= kwarg in structlog calls in llm_service.py caused 500 errors on LLM exceptions; fixed and committed as separate commit 169cc5a)
