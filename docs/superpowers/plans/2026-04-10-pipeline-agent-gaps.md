# План имплементации: закрытие расхождений пайплайна агента

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Закрыть функциональные расхождения пайплайна агента со спецификацией `agent.txt` (шаги 5.2, 5.3, 5.5, 5.6, 5.9) и формализовать границы ответственности между детерминированным скелетом и LLM-фазой.

**Architecture:** LLM — автономный агент в сужённой зоне (`plan_and_execute`) с переработанным промптом и метриками; пайплайн — тонкий скелет с safety net (`_evaluate_llm_outcome`), добавленным recheck логов в `verify_final_status`, расширенными полями в `build_final_comment`. В MCP-сервер добавляется мок `mrf_process_ticket` для эмуляции синхронного МРФ-цикла.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2/Settings, pytest (asyncio), Prometheus client, FastMCP, structlog.

**Исходная спецификация:** `docs/superpowers/specs/2026-04-10-pipeline-agent-gaps-design.md`

---

## Обзор задач

Порядок имплементации (TDD: unit → integration → e2e на каждой задаче, где применимо):

1. **Task 1.** Конфигурация: новые переменные в `common/config.py` + `.env.example`
2. **Task 2.** Метрики: `llm_safety_triggers_total` в `common/metrics.py`
3. **Task 3.** MCP-мок `mrf_process_ticket` — модели (`services/mcp_server/models.py`)
4. **Task 4.** MCP-мок `mrf_process_ticket` — сервис (`services/mcp_server/services.py`)
5. **Task 5.** MCP-мок `mrf_process_ticket` — регистрация tool (`services/mcp_server/mcp_server.py`)
6. **Task 6.** Интеграционный тест `mrf_process_ticket` через живой MCP subprocess
7. **Task 7.** `verify_final_status` — добавление `logs_recheck` на финальной итерации
8. **Task 8.** `_evaluate_llm_outcome` — safety net (новая функция в `pipeline.py`)
9. **Task 9.** `build_final_comment` — новые поля `llm.*`, `verify.logs_recheck.*`, `escalate.*` + обновлённый `next_step`
10. **Task 10.** `services/llm_service.py` — переработка промпта, сужение tools, сбор `llm_metrics`
11. **Task 11.** `agent_api/main.py` — интеграция safety net и прокидывание `llm_metrics` в `build_final_comment`
12. **Task 12.** E2E-сценарии (happy path, zero-action escalation, МРФ-цикл)
13. **Task 13.** Финальный прогон всего теста-суита + документация-комментарии

Каждая задача завершается git-коммитом.

---

## Task 1: Новые переменные конфигурации

**Files:**
- Modify: `unified_rtk_v2/common/config.py`
- Modify: `unified_rtk_v2/.env.example`

- [ ] **Step 1: Запустить текущий тест-суит для базового зелёного состояния**

Run: `cd unified_rtk_v2 && pytest -q`
Expected: все существующие тесты проходят (кроме e2e, они по дефолту skip).

- [ ] **Step 2: Добавить поля в Settings**

В `common/config.py` в классе `Settings` после поля `allow_queue_change: bool = False` добавить:

```python
    # LLM safety net / agent loop
    llm_max_steps: int = 12
    llm_max_tool_errors: int = 3

    # Verify recheck
    verify_recheck_window_days: int = 1

    # MRF mock
    mrf_mock_seed: int = 0
```

- [ ] **Step 3: Дополнить `.env.example`**

Добавить в конец файла блок:

```
# --- Новое: безопасность LLM-фазы и recheck ---
LLM_MAX_STEPS=12
LLM_MAX_TOOL_ERRORS=3
VERIFY_RECHECK_WINDOW_DAYS=1
MRF_MOCK_SEED=0
```

- [ ] **Step 4: Проверить импорт и дефолты**

Run:
```bash
cd unified_rtk_v2 && python -c "from common.config import get_settings; s=get_settings(); print(s.llm_max_steps, s.llm_max_tool_errors, s.verify_recheck_window_days, s.mrf_mock_seed)"
```
Expected output: `12 3 1 0`

- [ ] **Step 5: Коммит**

```bash
cd unified_rtk_v2 && git add common/config.py .env.example && git commit -m "feat(config): add LLM safety net and recheck settings"
```

---

## Task 2: Метрика `llm_safety_triggers_total`

**Files:**
- Modify: `unified_rtk_v2/common/metrics.py`

- [ ] **Step 1: Добавить счётчик**

В `common/metrics.py` в конец файла добавить:

```python
llm_safety_triggers_total = Counter(
    "llm_safety_triggers_total",
    "LLM-phase safety net triggers by reason",
    ["reason"],
)
```

- [ ] **Step 2: Проверить импорт**

Run: `cd unified_rtk_v2 && python -c "from common.metrics import llm_safety_triggers_total; print(llm_safety_triggers_total)"`
Expected: объект Counter без ошибок.

- [ ] **Step 3: Коммит**

```bash
cd unified_rtk_v2 && git add common/metrics.py && git commit -m "feat(metrics): add llm_safety_triggers_total counter"
```

---

## Task 3: MCP-модели для `mrf_process_ticket`

**Files:**
- Modify: `unified_rtk_v2/services/mcp_server/models.py`

- [ ] **Step 1: Добавить модели запроса/ответа**

В `services/mcp_server/models.py` после класса `CheckEditOrderResponse` добавить:

```python
class MrfProcessTicketRequest(BaseModel):
    ticket_id: str
    order_id: str
    region: str = Field("COMMON")


class MrfProcessTicketResponse(BaseModel):
    mrf_verdict: str  # OK | NEEDS_MANUAL | EDIT_ORDER_PENDING | ORDER_NOT_FOUND_IN_EISSD
    comment_added: bool
    queue: str
    details: dict[str, Any]
```

- [ ] **Step 2: Проверить импорт**

Run:
```bash
cd unified_rtk_v2 && python -c "from services.mcp_server.models import MrfProcessTicketRequest, MrfProcessTicketResponse; print('ok')"
```
Expected: `ok`

- [ ] **Step 3: Коммит**

```bash
cd unified_rtk_v2 && git add services/mcp_server/models.py && git commit -m "feat(mcp): add MrfProcessTicket request/response models"
```

---

## Task 4: Сервис `mrf_process_ticket` + unit-тесты

**Files:**
- Modify: `unified_rtk_v2/services/mcp_server/services.py`
- Create: `unified_rtk_v2/tests/test_unit_mrf_mock.py`

- [ ] **Step 1: Написать падающий unit-тест**

Создать файл `tests/test_unit_mrf_mock.py`:

```python
"""Unit-тесты мока mrf_process_ticket."""
from __future__ import annotations

import pytest

from services.mcp_server import storage
from services.mcp_server.models import MrfProcessTicketRequest
from services.mcp_server.services import OtrsService


class TestMrfProcessTicket:
    @pytest.mark.unit
    def test_deterministic_same_order_same_verdict(self):
        req = MrfProcessTicketRequest(ticket_id="T1", order_id="1800003902272", region="MSK")
        r1 = OtrsService.mrf_process_ticket(req)
        # очистим комментарии и повторим
        storage.OTRS_COMMENTS.clear()
        r2 = OtrsService.mrf_process_ticket(req)
        assert r1.mrf_verdict == r2.mrf_verdict

    @pytest.mark.unit
    def test_comment_added_to_storage(self):
        req = MrfProcessTicketRequest(ticket_id="T-COMMENT", order_id="1800003902272", region="MSK")
        before = len([c for c in storage.OTRS_COMMENTS if c.get("ticket_id") == "T-COMMENT"])
        resp = OtrsService.mrf_process_ticket(req)
        after = [c for c in storage.OTRS_COMMENTS if c.get("ticket_id") == "T-COMMENT"]
        assert resp.comment_added is True
        assert len(after) == before + 1
        assert after[-1].get("source") == "mrf_mock"

    @pytest.mark.unit
    def test_all_verdicts_reachable(self):
        verdicts = set()
        for i in range(200):
            req = MrfProcessTicketRequest(ticket_id=f"T{i}", order_id=f"ORD{i}", region="MSK")
            r = OtrsService.mrf_process_ticket(req)
            verdicts.add(r.mrf_verdict)
            storage.OTRS_COMMENTS.clear()
        assert verdicts == {"OK", "NEEDS_MANUAL", "EDIT_ORDER_PENDING", "ORDER_NOT_FOUND_IN_EISSD"}

    @pytest.mark.unit
    def test_queue_reflects_region(self):
        req = MrfProcessTicketRequest(ticket_id="T1", order_id="1800003902272", region="SPB")
        resp = OtrsService.mrf_process_ticket(req)
        assert "SPB" in resp.queue
```

- [ ] **Step 2: Запустить — должен упасть**

Run: `cd unified_rtk_v2 && pytest tests/test_unit_mrf_mock.py -v`
Expected: FAIL с `AttributeError: type object 'OtrsService' has no attribute 'mrf_process_ticket'`

- [ ] **Step 3: Реализовать метод**

В `services/mcp_server/services.py` обновить импорт моделей (добавить `MrfProcessTicketRequest`, `MrfProcessTicketResponse`) и в класс `OtrsService` добавить метод:

```python
    @staticmethod
    def mrf_process_ticket(data: MrfProcessTicketRequest) -> MrfProcessTicketResponse:
        from common.config import get_settings

        seed = get_settings().mrf_mock_seed
        verdicts = ["OK", "NEEDS_MANUAL", "EDIT_ORDER_PENDING", "ORDER_NOT_FOUND_IN_EISSD"]
        # Детерминизм: hash от (seed, order_id, region)
        h = abs(hash((seed, data.order_id, (data.region or "COMMON").upper())))
        verdict = verdicts[h % len(verdicts)]

        queue = f"ОЦО.МРФ.Эксплуатация СУЛЗ.{(data.region or 'COMMON').upper()}"

        texts = {
            "OK": "МРФ: обработка завершена, статус синхронизирован.",
            "NEEDS_MANUAL": "МРФ: требуется ручная проверка специалистом.",
            "EDIT_ORDER_PENDING": "МРФ: обнаружена заявка на редактирование заказа.",
            "ORDER_NOT_FOUND_IN_EISSD": "МРФ: заказ отсутствует в ЕИССД.",
        }

        storage.OTRS_COMMENTS.append(
            {
                "ticket_id": data.ticket_id,
                "text": texts[verdict],
                "source": "mrf_mock",
            }
        )

        return MrfProcessTicketResponse(
            mrf_verdict=verdict,
            comment_added=True,
            queue=queue,
            details={"order_id": data.order_id, "region": (data.region or "COMMON").upper()},
        )
```

Также обновить импорт в начале `services.py`:

```python
from .models import (
    AddOtrsCommentRequest,
    AddOtrsCommentResponse,
    CheckEissdStatusRequest,
    CheckEissdStatusResponse,
    GetOrderStatusRequest,
    GetOrderStatusResponse,
    GetOtrsTicketRequest,
    GetOtrsTicketResponse,
    ListOtrsCommentsRequest,
    ListOtrsCommentsResponse,
    MrfProcessTicketRequest,
    MrfProcessTicketResponse,
    OrderStatus,
    ResolveMrfQueueRequest,
    ResolveMrfQueueResponse,
    SearchLogsRequest,
    SearchLogsResponse,
    UpdateOrderStatusRequest,
    UpdateOrderStatusResponse,
    UpdateOtrsTicketRequest,
    UpdateOtrsTicketResponse,
)
```

- [ ] **Step 4: Запустить тесты — должны пройти**

Run: `cd unified_rtk_v2 && pytest tests/test_unit_mrf_mock.py -v`
Expected: 4 passed.

- [ ] **Step 5: Проверить `list_otrs_comments` видит комментарий**

Дополнительный unit-тест в том же файле:

```python
    @pytest.mark.unit
    def test_list_comments_includes_mrf_comment(self):
        from services.mcp_server.models import ListOtrsCommentsRequest
        req = MrfProcessTicketRequest(ticket_id="T-LIST", order_id="1800003902272", region="MSK")
        OtrsService.mrf_process_ticket(req)
        resp = OtrsService.list_comments(ListOtrsCommentsRequest(ticket_id="T-LIST"))
        assert any(c.get("source") == "mrf_mock" for c in resp.comments)
```

Run: `cd unified_rtk_v2 && pytest tests/test_unit_mrf_mock.py -v`
Expected: 5 passed.

- [ ] **Step 6: Коммит**

```bash
cd unified_rtk_v2 && git add services/mcp_server/services.py tests/test_unit_mrf_mock.py && git commit -m "feat(mcp): add OtrsService.mrf_process_ticket deterministic mock"
```

---

## Task 5: Регистрация MCP-tool `mrf_process_ticket`

**Files:**
- Modify: `unified_rtk_v2/services/mcp_server/mcp_server.py`

- [ ] **Step 1: Добавить импорт модели**

В верхней секции импорта `models` в `services/mcp_server/mcp_server.py` добавить `MrfProcessTicketRequest`:

```python
from .models import (
    AddOtrsCommentRequest,
    CheckEditOrderRequest,
    CheckEditOrderResponse,
    CheckEissdStatusRequest,
    GetOrderStatusRequest,
    GetOtrsTicketRequest,
    ListOtrsCommentsRequest,
    MrfProcessTicketRequest,
    ResolveMrfQueueRequest,
    SearchLogsRequest,
    UpdateOrderStatusRequest,
    UpdateOtrsTicketRequest,
)
```

- [ ] **Step 2: Зарегистрировать tool**

В `mcp_server.py` после декоратора `resolve_mrf_queue` (между ним и `add_otrs_comment`) добавить:

```python
@mcp.tool()
def mrf_process_ticket(input: MrfProcessTicketRequest) -> str:
    """Эмулирует синхронный цикл обработки тикета очередью МРФ: возвращает вердикт и добавляет комментарий от МРФ."""
    try:
        result = _to_json_text(OtrsService.mrf_process_ticket(input))
        mcp_requests_total.labels(tool="mrf_process_ticket", status="ok").inc()
        return result
    except Exception:
        log.exception("mcp_tool_error", tool="mrf_process_ticket")
        mcp_requests_total.labels(tool="mrf_process_ticket", status="error").inc()
        raise
```

- [ ] **Step 3: Синтакс-проверка**

Run: `cd unified_rtk_v2 && python -c "from services.mcp_server import mcp_server; print(hasattr(mcp_server, 'mrf_process_ticket'))"`
Expected: `True`

- [ ] **Step 4: Коммит**

```bash
cd unified_rtk_v2 && git add services/mcp_server/mcp_server.py && git commit -m "feat(mcp): register mrf_process_ticket tool"
```

---

## Task 6: Интеграционный тест `mrf_process_ticket` через живой MCP

**Files:**
- Modify: `unified_rtk_v2/tests/test_integration_services.py`

- [ ] **Step 1: Посмотреть существующую фикстуру MCP клиента**

Run: `cd unified_rtk_v2 && head -60 tests/test_integration_services.py`
Цель: увидеть паттерн существующих интеграционных тестов с живым MCP subprocess.

- [ ] **Step 2: Добавить integration-тест**

В `tests/test_integration_services.py` добавить новый класс в конец файла (сохраняя паттерн существующих):

```python
class TestMrfProcessTicketIntegration:
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_mrf_process_ticket_returns_structured_response(self, mcp_client):
        raw = await mcp_client.call_tool(
            "mrf_process_ticket",
            {"ticket_id": "TKT-INT-1", "order_id": "1800003902272", "region": "MSK"},
        )
        # MCP возвращает ответ в форме, совместимой с _unwrap_mcp_dict
        from pipeline.pipeline import _unwrap_mcp_dict
        resp, _code, fatal = _unwrap_mcp_dict("mrf_process_ticket", raw)
        assert fatal is False
        assert isinstance(resp, dict)
        assert resp["mrf_verdict"] in {"OK", "NEEDS_MANUAL", "EDIT_ORDER_PENDING", "ORDER_NOT_FOUND_IN_EISSD"}
        assert resp["comment_added"] is True
        assert "MSK" in resp["queue"]

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_list_otrs_comments_sees_mrf_comment(self, mcp_client):
        await mcp_client.call_tool(
            "mrf_process_ticket",
            {"ticket_id": "TKT-INT-2", "order_id": "1800003902272", "region": "MSK"},
        )
        raw = await mcp_client.call_tool(
            "list_otrs_comments",
            {"ticket_id": "TKT-INT-2"},
        )
        from pipeline.pipeline import _unwrap_mcp_dict
        resp, _code, _fatal = _unwrap_mcp_dict("list_otrs_comments", raw)
        assert isinstance(resp, dict)
        comments = resp.get("comments") or []
        assert any(c.get("source") == "mrf_mock" for c in comments)
```

Примечание: если в существующих тестах fixture называется не `mcp_client`, а иначе — использовать имя из файла.

- [ ] **Step 3: Запустить integration-тесты**

Run: `cd unified_rtk_v2 && pytest tests/test_integration_services.py -m integration -v`
Expected: новые 2 теста passed, существующие тесты не сломались.

- [ ] **Step 4: Коммит**

```bash
cd unified_rtk_v2 && git add tests/test_integration_services.py && git commit -m "test(integration): cover mrf_process_ticket via live MCP subprocess"
```

---

## Task 7: `verify_final_status` — добавление `logs_recheck`

**Files:**
- Modify: `unified_rtk_v2/pipeline/pipeline.py`
- Modify: `unified_rtk_v2/tests/test_unit_pipeline.py`

- [ ] **Step 1: Добавить падающий unit-тест для `logs_recheck`**

В `tests/test_unit_pipeline.py` добавить в конец файла:

```python
class TestVerifyFinalStatusLogsRecheck:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_logs_recheck_populated_on_success(self, ticket):
        from unittest.mock import AsyncMock
        from pipeline.pipeline import verify_final_status

        mcp = AsyncMock()

        async def call_tool(name, args):
            if name == "get_order_status":
                return {"status": "DONE", "raw": {}}
            if name == "check_eissd_status":
                return {"status": "DONE", "raw": {}}
            if name == "search_logs":
                return {"error_found": False, "logs_full": []}
            raise ValueError(f"unexpected tool {name}")

        mcp.call_tool.side_effect = call_tool

        results, logs = await verify_final_status(
            ticket, mcp, deadline=time.monotonic() + 30
        )
        assert "logs_recheck" in results
        lr = results["logs_recheck"]
        assert lr["error_still_present"] is False
        assert lr["logs_full_count"] == 0
        assert lr["window_days"] == 1
        assert lr["pattern"] == "ORDER_STATUS_DENIED"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_logs_recheck_error_still_present(self, ticket):
        from unittest.mock import AsyncMock
        from pipeline.pipeline import verify_final_status

        mcp = AsyncMock()

        async def call_tool(name, args):
            if name == "get_order_status":
                return {"status": "DONE", "raw": {}}
            if name == "check_eissd_status":
                return {"status": "DONE", "raw": {}}
            if name == "search_logs":
                return {
                    "error_found": True,
                    "error_code": "ORDER_STATUS_DENIED",
                    "logs_full": ["l1", "l2"],
                }
            raise ValueError(f"unexpected tool {name}")

        mcp.call_tool.side_effect = call_tool

        results, _logs = await verify_final_status(
            ticket, mcp, deadline=time.monotonic() + 30
        )
        assert results["logs_recheck"]["error_still_present"] is True
        assert results["logs_recheck"]["logs_full_count"] == 2

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_logs_recheck_mcp_exception(self, ticket):
        from unittest.mock import AsyncMock
        from pipeline.pipeline import verify_final_status

        mcp = AsyncMock()

        async def call_tool(name, args):
            if name == "get_order_status":
                return {"status": "DONE", "raw": {}}
            if name == "check_eissd_status":
                return {"status": "DONE", "raw": {}}
            if name == "search_logs":
                raise RuntimeError("mcp down")
            raise ValueError(f"unexpected tool {name}")

        mcp.call_tool.side_effect = call_tool

        results, _logs = await verify_final_status(
            ticket, mcp, deadline=time.monotonic() + 30
        )
        # При исключении recheck-поля остаются, но error_still_present=None
        assert results["logs_recheck"]["error_still_present"] is None
```

- [ ] **Step 2: Запустить — должен упасть**

Run: `cd unified_rtk_v2 && pytest tests/test_unit_pipeline.py::TestVerifyFinalStatusLogsRecheck -v`
Expected: FAIL (нет ключа `logs_recheck`).

- [ ] **Step 3: Реализовать recheck в `verify_final_status`**

В `pipeline/pipeline.py` после строки констант `PRECHECK_PATTERN` / `PRECHECK_WINDOW_DAYS` добавить импорт настроек, если ещё не было (уже есть через `get_settings`).

Переписать цикл `verify_final_status`: добавить третий вызов `search_logs` **на той итерации, на которой цикл `break`-ается как успешный** (т.е. нормализация прошла). Проще всего — вытащить логику в блок после `break` через флаг.

Изменить функцию `verify_final_status` так, чтобы после успешного `break` (после строки `break`) вызвать новый внутренний хелпер:

```python
async def _do_logs_recheck(
    ticket: Ticket, mcp: MCPClient, diag: list[str]
) -> dict[str, Any]:
    settings = get_settings()
    window = settings.verify_recheck_window_days
    result: dict[str, Any] = {
        "pattern": PRECHECK_PATTERN,
        "window_days": window,
        "error_still_present": None,
        "logs_full_count": None,
    }
    try:
        raw = await mcp.call_tool(
            "search_logs",
            {"order_id": ticket.order_id, "pattern": PRECHECK_PATTERN, "window_days": window},
        )
        resp, code, fatal = _unwrap_mcp_dict("search_logs", raw)
        if code:
            diag.append(code)
            if fatal:
                return result
        if isinstance(resp, dict):
            result["error_still_present"] = bool(resp.get("error_found"))
            lf = resp.get("logs_full")
            if isinstance(lf, list):
                result["logs_full_count"] = len(lf)
    except Exception as exc:
        diag.append("mcp.search_logs.recheck_exception")
        log.warning("verify_logs_recheck_failed", error=str(exc))
    return result
```

И в основном цикле заменить логику finalize-ответа, чтобы после успешного `break` выполнить recheck и положить в `results["logs_recheck"]`. Точечно — после строки `results = {"sulz_db": ..., "eissd": ..., "_diag": diag}` и перед `try:` блоком нормализации не добавлять, а выполнить **после** успешного `break` из цикла, перед `pipeline_steps_total.labels(...)`.

Конкретное изменение: после цикла `for i in range(attempts)` и до `pipeline_steps_total.labels(step="verify_final_status"...)` добавить:

```python
    results["logs_recheck"] = await _do_logs_recheck(ticket, mcp, diag)
    results["_diag"] = diag

    pipeline_steps_total.labels(step="verify_logs_recheck", status="ok").inc()
```

Важно: recheck должен вызываться ровно один раз, вне цикла backoff.

- [ ] **Step 4: Запустить тесты — должны пройти**

Run: `cd unified_rtk_v2 && pytest tests/test_unit_pipeline.py -v`
Expected: новые 3 теста passed, старые тесты `TestBuildFinalComment` пока в нормальном состоянии (build_final_comment не менялся).

- [ ] **Step 5: Коммит**

```bash
cd unified_rtk_v2 && git add pipeline/pipeline.py tests/test_unit_pipeline.py && git commit -m "feat(pipeline): add logs_recheck to verify_final_status"
```

---

## Task 8: `_evaluate_llm_outcome` — safety net

**Files:**
- Modify: `unified_rtk_v2/pipeline/pipeline.py`
- Modify: `unified_rtk_v2/tests/test_unit_pipeline.py`

- [ ] **Step 1: Написать падающие unit-тесты**

В `tests/test_unit_pipeline.py` добавить:

```python
class TestEvaluateLlmOutcome:
    @pytest.mark.unit
    def test_no_escalation_when_error_and_actions_taken(self):
        from pipeline.pipeline import _evaluate_llm_outcome
        context = {
            "precheck": {"logs": {"error_found": True}},
            "llm_metrics": {
                "steps_used": 5,
                "write_calls_total": 2,
                "loop_exceeded": False,
                "error_count": 0,
            },
        }
        escalate, reasons = _evaluate_llm_outcome([], context)
        assert escalate is False
        assert reasons == []

    @pytest.mark.unit
    def test_no_action_taken_triggers(self):
        from pipeline.pipeline import _evaluate_llm_outcome
        context = {
            "precheck": {"logs": {"error_found": True}},
            "llm_metrics": {
                "steps_used": 1,
                "write_calls_total": 0,
                "loop_exceeded": False,
                "error_count": 0,
            },
        }
        escalate, reasons = _evaluate_llm_outcome([], context)
        assert escalate is True
        assert "llm_no_action_taken" in reasons

    @pytest.mark.unit
    def test_loop_exceeded_triggers(self):
        from pipeline.pipeline import _evaluate_llm_outcome
        context = {
            "precheck": {"logs": {"error_found": False}},
            "llm_metrics": {
                "steps_used": 12,
                "write_calls_total": 1,
                "loop_exceeded": True,
                "error_count": 0,
            },
        }
        escalate, reasons = _evaluate_llm_outcome([], context)
        assert escalate is True
        assert "llm_loop_exceeded" in reasons

    @pytest.mark.unit
    def test_tool_errors_repeated_triggers(self):
        from pipeline.pipeline import _evaluate_llm_outcome
        context = {
            "precheck": {"logs": {"error_found": True}},
            "llm_metrics": {
                "steps_used": 3,
                "write_calls_total": 1,
                "loop_exceeded": False,
                "error_count": 3,
            },
        }
        escalate, reasons = _evaluate_llm_outcome([], context)
        assert escalate is True
        assert "llm_tool_errors_repeated" in reasons

    @pytest.mark.unit
    def test_no_error_found_and_zero_actions_is_fine(self):
        from pipeline.pipeline import _evaluate_llm_outcome
        context = {
            "precheck": {"logs": {"error_found": False}},
            "llm_metrics": {
                "steps_used": 0,
                "write_calls_total": 0,
                "loop_exceeded": False,
                "error_count": 0,
            },
        }
        escalate, reasons = _evaluate_llm_outcome([], context)
        assert escalate is False
        assert reasons == []
```

- [ ] **Step 2: Запустить — fail**

Run: `cd unified_rtk_v2 && pytest tests/test_unit_pipeline.py::TestEvaluateLlmOutcome -v`
Expected: FAIL с ImportError / AttributeError.

- [ ] **Step 3: Реализовать функцию**

В `pipeline/pipeline.py` после функции `plan_and_execute` добавить:

```python
def _evaluate_llm_outcome(
    actions: list[ActionLogEntry],
    context: dict[str, Any],
) -> tuple[bool, list[str]]:
    """Возвращает (should_escalate, reasons) по метрикам LLM-фазы.

    Вызывается после plan_and_execute и до verify_final_status. Триггеры
    после verify (error_persists_after_execution) добавляются позже
    в build_final_comment.
    """
    from common.metrics import llm_safety_triggers_total

    settings = get_settings()
    metrics = (context or {}).get("llm_metrics") or {}
    precheck = (context or {}).get("precheck") or {}
    pre_logs = precheck.get("logs") if isinstance(precheck, dict) else None
    error_found = bool(pre_logs.get("error_found")) if isinstance(pre_logs, dict) else False

    write_calls = int(metrics.get("write_calls_total") or 0)
    loop_exceeded = bool(metrics.get("loop_exceeded"))
    error_count = int(metrics.get("error_count") or 0)

    reasons: list[str] = []
    if error_found and write_calls == 0:
        reasons.append("llm_no_action_taken")
    if loop_exceeded:
        reasons.append("llm_loop_exceeded")
    if error_count >= settings.llm_max_tool_errors:
        reasons.append("llm_tool_errors_repeated")

    for r in reasons:
        try:
            llm_safety_triggers_total.labels(reason=r).inc()
        except Exception:
            log.warning("metric_inc_failed", metric="llm_safety_triggers_total", reason=r)

    return (len(reasons) > 0, reasons)
```

- [ ] **Step 4: Тесты зелёные**

Run: `cd unified_rtk_v2 && pytest tests/test_unit_pipeline.py::TestEvaluateLlmOutcome -v`
Expected: 5 passed.

- [ ] **Step 5: Коммит**

```bash
cd unified_rtk_v2 && git add pipeline/pipeline.py tests/test_unit_pipeline.py && git commit -m "feat(pipeline): add _evaluate_llm_outcome safety net"
```

---

## Task 9: `build_final_comment` — новые поля и обновлённый `next_step`

**Files:**
- Modify: `unified_rtk_v2/pipeline/pipeline.py`
- Modify: `unified_rtk_v2/tests/test_unit_pipeline.py`

- [ ] **Step 1: Написать падающие тесты**

Добавить в `TestBuildFinalComment` (или новый класс `TestBuildFinalCommentExtended`) в `tests/test_unit_pipeline.py`:

```python
class TestBuildFinalCommentExtended:
    @pytest.mark.unit
    def test_llm_metrics_fields_present(self, ticket):
        comment = build_final_comment(
            ticket,
            precheck={"logs": {"error_found": True, "error_code": "X"}, "_diag": []},
            rag={"required_actions": []},
            actions=[ActionLogEntry(tool="t1", params={}, ok=True)],
            verify={"_diag": [], "logs_recheck": {
                "pattern": "ORDER_STATUS_DENIED",
                "window_days": 1,
                "error_still_present": False,
                "logs_full_count": 0,
            }},
            llm_metrics={
                "steps_used": 5,
                "rag_followed": 1,
                "rag_deviated": 0,
                "write_calls_total": 2,
                "loop_exceeded": False,
                "error_count": 0,
            },
            escalate_reasons=[],
        )
        assert "llm.steps_used=5" in comment
        assert "llm.rag_followed=1" in comment
        assert "llm.rag_deviated=0" in comment
        assert "llm.write_calls_total=2" in comment
        assert "llm.loop_exceeded=false" in comment
        assert "llm.error_count=0" in comment
        assert "verify.logs_recheck.window_days=1" in comment
        assert "verify.logs_recheck.error_still_present=false" in comment
        assert "verify.logs_recheck.logs_full_count=0" in comment
        assert "escalate.triggered=false" in comment

    @pytest.mark.unit
    def test_escalate_reason_appended_from_verify(self, ticket):
        comment = build_final_comment(
            ticket,
            precheck={"logs": {"error_found": True}, "_diag": []},
            rag=None,
            actions=[ActionLogEntry(tool="t1", params={}, ok=True)],
            verify={"_diag": [], "logs_recheck": {
                "pattern": "ORDER_STATUS_DENIED",
                "window_days": 1,
                "error_still_present": True,
                "logs_full_count": 3,
            }},
            llm_metrics={
                "steps_used": 5,
                "rag_followed": 0,
                "rag_deviated": 0,
                "write_calls_total": 2,
                "loop_exceeded": False,
                "error_count": 0,
            },
            escalate_reasons=[],
        )
        assert "escalate.triggered=true" in comment
        assert "escalate.reason.0=error_persists_after_execution" in comment
        assert "next_step=ESCALATE_L2" in comment

    @pytest.mark.unit
    def test_escalate_pre_verify_reason(self, ticket):
        comment = build_final_comment(
            ticket,
            precheck={"logs": {"error_found": True}, "_diag": []},
            rag=None,
            actions=[],
            verify={"_diag": [], "logs_recheck": {
                "pattern": "ORDER_STATUS_DENIED",
                "window_days": 1,
                "error_still_present": False,
                "logs_full_count": 0,
            }},
            llm_metrics={
                "steps_used": 1,
                "rag_followed": 0,
                "rag_deviated": 0,
                "write_calls_total": 0,
                "loop_exceeded": False,
                "error_count": 0,
            },
            escalate_reasons=["llm_no_action_taken"],
        )
        assert "escalate.triggered=true" in comment
        assert "escalate.reason.0=llm_no_action_taken" in comment
        assert "next_step=ESCALATE_L2" in comment

    @pytest.mark.unit
    def test_build_final_comment_backward_compat_optional_args(self, ticket):
        # Когда не переданы llm_metrics / escalate_reasons — поля пустые, next_step работает по старой логике
        comment = build_final_comment(
            ticket,
            precheck={"logs": {"error_found": False}, "_diag": []},
            rag=None,
            actions=[],
            verify={"_diag": []},
        )
        assert "next_step=NO_ERROR_IN_LOGS" in comment
        assert "llm.steps_used=" in comment  # пустая строка справа от =
        assert "escalate.triggered=false" in comment
```

- [ ] **Step 2: Запуск — fail**

Run: `cd unified_rtk_v2 && pytest tests/test_unit_pipeline.py::TestBuildFinalCommentExtended -v`
Expected: FAIL (signature mismatch / отсутствующие поля).

- [ ] **Step 3: Обновить сигнатуру и тело `build_final_comment`**

В `pipeline/pipeline.py` заменить сигнатуру:

```python
def build_final_comment(
    ticket: Ticket,
    *,
    precheck: dict[str, Any],
    rag: dict[str, Any] | None,
    actions: list[ActionLogEntry],
    verify: dict[str, Any],
    llm_metrics: dict[str, Any] | None = None,
    escalate_reasons: list[str] | None = None,
) -> str:
```

Внутри функции перед построением `lines`:

1. Нормализовать `llm_metrics` / `escalate_reasons` к умолчаниям (`{}` / `[]`).
2. Достать из `verify` поле `logs_recheck` (dict или None).
3. Скопировать `escalate_reasons` в локальную переменную `all_reasons`.
4. Добавить post-verify триггер:
   ```python
   lr = verify.get("logs_recheck") if isinstance(verify, dict) else None
   if error_found and isinstance(lr, dict) and lr.get("error_still_present") is True:
       if "error_persists_after_execution" not in all_reasons:
           all_reasons.append("error_persists_after_execution")
   ```

5. Обновить логику `next_step`:
   ```python
   if all_reasons:
       next_step = "ESCALATE_L2"
   elif not error_found:
       next_step = "NO_ERROR_IN_LOGS"
   elif not ok_all:
       next_step = "ESCALATE_L2"
   else:
       next_step = "IN_WORK_WAIT_CONFIRMATION"
   ```

6. В блоке `lines` **после** строки `lines.append(f"actions.ok={'true' if ok_all else 'false'}")` и перед `verify.sulz_db.status` добавить блок `llm.*`:

```python
    def _fmt_int(v: Any) -> str:
        if v is None:
            return ""
        return str(int(v)) if isinstance(v, (int, bool)) else str(v)

    def _fmt_bool(v: Any) -> str:
        if v is None:
            return ""
        return "true" if bool(v) else "false"

    lm = llm_metrics or {}
    lines.append(f"llm.steps_used={_fmt_int(lm.get('steps_used'))}")
    lines.append(f"llm.rag_followed={_fmt_int(lm.get('rag_followed'))}")
    lines.append(f"llm.rag_deviated={_fmt_int(lm.get('rag_deviated'))}")
    lines.append(f"llm.write_calls_total={_fmt_int(lm.get('write_calls_total'))}")
    lines.append(f"llm.loop_exceeded={_fmt_bool(lm.get('loop_exceeded'))}")
    lines.append(f"llm.error_count={_fmt_int(lm.get('error_count'))}")
```

7. После `verify.eissd.status=...` добавить блок `verify.logs_recheck.*`:

```python
    lr_w = lr.get("window_days") if isinstance(lr, dict) else None
    lr_err = lr.get("error_still_present") if isinstance(lr, dict) else None
    lr_cnt = lr.get("logs_full_count") if isinstance(lr, dict) else None
    lines.append(f"verify.logs_recheck.window_days={_fmt_int(lr_w)}")
    lines.append(f"verify.logs_recheck.error_still_present={_fmt_bool(lr_err)}")
    lines.append(f"verify.logs_recheck.logs_full_count={_fmt_int(lr_cnt)}")
```

8. После `diag.*` блока и перед `next_step` добавить:

```python
    lines.append(f"escalate.triggered={'true' if all_reasons else 'false'}")
    for idx, r in enumerate(all_reasons[:5]):
        lines.append(f"escalate.reason.{idx}={r}")
```

- [ ] **Step 4: Запустить все unit-тесты**

Run: `cd unified_rtk_v2 && pytest tests/test_unit_pipeline.py -v`
Expected: все passed, включая старые `TestBuildFinalComment` (они не передают новые kwargs, поэтому проверяют обратную совместимость).

- [ ] **Step 5: Коммит**

```bash
cd unified_rtk_v2 && git add pipeline/pipeline.py tests/test_unit_pipeline.py && git commit -m "feat(pipeline): extend build_final_comment with llm/verify/escalate fields"
```

---

## Task 10: LLM-фаза — новый промпт, сужение tools, метрики

**Files:**
- Modify: `unified_rtk_v2/services/llm_service.py`

- [ ] **Step 1: Расширить `_filter_tools_schema` — убирать также finalize-tool'ы**

В `services/llm_service.py` заменить функцию `_filter_tools_schema` на:

```python
# Инструменты финализации тикета — недоступны LLM, только пайплайну
_FINALIZE_TOOLS = {"update_otrs_ticket"}


def _filter_tools_schema(tools_schema: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Удаляет инструменты финализации — они доступны только в pipeline.finalize."""
    out: list[dict[str, Any]] = []
    for t in tools_schema or []:
        name = (t.get("function") or {}).get("name") if isinstance(t, dict) else None
        if name in _FINALIZE_TOOLS:
            continue
        out.append(t)
    return out
```

Примечание: набор `mrf_process_ticket` остаётся доступным LLM (см. спецификацию, компонент A, "Как LLM использует").

- [ ] **Step 2: Переработать системный промпт**

Заменить блок `system_prompt = (...)` на:

```python
    system_prompt = (
        "Ты — AI-агент техподдержки. Твоя зона ответственности: интерпретация "
        "контекста, выбор и вызов инструментов, принятие решений по состоянию "
        "заказа. Финализация тикета выполняется автоматически после твоей фазы — "
        "инструменты финализации (update_otrs_ticket) тебе недоступны.\n\n"
        "КОНТЕКСТ, доступный тебе:\n"
        "- precheck.logs — результаты поиска ошибок в логах заказа\n"
        "- тикет: ticket_id, order_id, subject, annotation, description, region\n"
        "- rag.required_actions — РЕКОМЕНДАЦИИ экспертной системы, основанные "
        "  на похожих кейсах. Это СОВЕТЫ, а не обязательный чек-лист. Оцени их "
        "  применимость к текущему состоянию. Ты можешь им следовать, адаптировать "
        "  параметры или отклониться, если состояние показывает, что они неприменимы. "
        "  Если RAG недоступен — действуй по precheck + тикету.\n\n"
        "ИНСТРУМЕНТЫ:\n"
        "- read: search_logs, get_order_status, check_eissd_status, get_otrs_ticket, list_otrs_comments\n"
        "- write: check_edit_order_request, update_order_status, resolve_mrf_queue, "
        "  mrf_process_ticket, add_otrs_comment\n"
        "- недоступно: update_otrs_ticket\n\n"
        "ПРАВИЛА:\n"
        "- НЕЛЬЗЯ выдумывать данные — только через tools.\n"
        "- Если нужна очередь МРФ — используй resolve_mrf_queue → mrf_process_ticket → "
        "  list_otrs_comments (прочитай свежий комментарий от МРФ, прими решение).\n"
        "- Когда закончил вызывать tools, верни слово DONE."
    )
```

- [ ] **Step 3: Добавить сбор `llm_metrics`**

В `run_planning_loop` до начала цикла tool-loop добавить:

```python
    rag_required_names: set[str] = set()
    if context:
        rag_payload = context.get("rag") or {}
        if isinstance(rag_payload, dict):
            ra = rag_payload.get("required_actions") or []
            for item in ra:
                if isinstance(item, dict):
                    name = item.get("tool") or item.get("name")
                    if isinstance(name, str) and name:
                        rag_required_names.add(name)

    write_tools = {
        "check_edit_order_request",
        "update_order_status",
        "resolve_mrf_queue",
        "mrf_process_ticket",
        "add_otrs_comment",
    }

    steps_used = 0
    loop_exceeded = False
```

В цикле `for _ in range(settings.llm_max_iterations)` заменить на `for _ in range(settings.llm_max_steps)` (использовать новую переменную из конфига).

Примечание: сохранить обратную совместимость — `llm_max_iterations` больше не используется в этом цикле, но оставим поле в конфиге, чтобы не ломать existing `.env`.

После каждой успешной или неуспешной итерации (на каждую итерацию цикла for) инкрементировать `steps_used += 1`. Если цикл завершился без `break` при tool_calls == 0 — это значит loop_exceeded.

Более надёжный способ — обернуть цикл в `else`:

```python
    for step_idx in range(settings.llm_max_steps):
        steps_used = step_idx + 1
        if time.monotonic() > deadline:
            break

        try:
            text, tool_calls = await call_llm(expect_tools=True)
        except Exception as exc:
            log.error("llm_call_error", exc_type=exc.__class__.__name__, detail=str(exc))
            break

        if tool_calls:
            _append_ollama_assistant_tool_calls(messages, tool_calls)
            for call in tool_calls:
                if time.monotonic() > deadline:
                    break
                name = str(call.get("name") or "")
                params = call.get("arguments", {}) or {}
                if name in _FINALIZE_TOOLS:
                    continue

                entry = ActionLogEntry(tool=name, params=dict(params))
                t0 = time.perf_counter()
                try:
                    result = await mcp_client.call_tool(name, params)
                    entry.ok = True
                    entry.result = result
                    _append_ollama_tool_result(messages, name, result)
                except Exception as exc:
                    log.warning("tool_call_failed", tool=name, exc_type=exc.__class__.__name__, detail=str(exc))
                    entry.ok = False
                    entry.error = str(exc)
                    entry.error_type = exc.__class__.__name__
                entry.duration_ms = int((time.perf_counter() - t0) * 1000)
                actions.append(entry)
            continue

        if (text or "").strip():
            messages.append({"role": "assistant", "content": text})
        break
    else:
        loop_exceeded = True
```

После цикла и после fallback-блока (перед `return actions`) собрать метрики:

```python
    action_tool_names = [a.tool for a in actions]
    error_count = sum(1 for a in actions if not a.ok)
    write_calls_total = sum(1 for a in actions if a.tool in write_tools)

    used_names = set(action_tool_names)
    rag_followed = len(rag_required_names & used_names)
    rag_deviated = len(rag_required_names - used_names)

    if context is not None:
        context["llm_metrics"] = {
            "steps_used": steps_used,
            "rag_followed": rag_followed,
            "rag_deviated": rag_deviated,
            "write_calls_total": write_calls_total,
            "loop_exceeded": loop_exceeded,
            "error_count": error_count,
        }
```

- [ ] **Step 4: Проверить backward-совместимость поля `llm_max_iterations`**

Если `settings.llm_max_steps` не определён — использовался бы `llm_max_iterations`. Мы уже добавили `llm_max_steps` в Task 1, так что всё ок. Оставить поле `llm_max_iterations` в Settings (оно больше не используется в этом цикле, но всё ещё присутствует на всякий случай).

- [ ] **Step 5: Запустить существующие тесты**

Run: `cd unified_rtk_v2 && pytest tests/ -v -m "not e2e"`
Expected: все passed.

- [ ] **Step 6: Коммит**

```bash
cd unified_rtk_v2 && git add services/llm_service.py && git commit -m "feat(llm): rework prompt, narrow tools, collect llm_metrics"
```

---

## Task 11: Интеграция safety net в `agent_api/main.py`

**Files:**
- Modify: `unified_rtk_v2/agent_api/main.py`

- [ ] **Step 1: Обновить импорты**

В `agent_api/main.py` в импорте из `pipeline.pipeline` добавить `_evaluate_llm_outcome`:

```python
from pipeline.pipeline import (
    _evaluate_llm_outcome,
    build_final_comment,
    call_rag,
    finalize,
    plan_and_execute,
    precheck_logs,
    verify_final_status,
)
```

- [ ] **Step 2: Вставить вызов safety net и прокинуть метрики**

В функции `intake` заменить блок между `plan_and_execute` и `build_final_comment` на:

```python
        actions = await plan_and_execute(ticket, ctx, mcp, deadline=deadline)

        escalate_triggered, escalate_reasons = _evaluate_llm_outcome(actions, ctx)
        ctx["escalate_reasons_pre_verify"] = escalate_reasons

        verify, verify_actions = await verify_final_status(ticket, mcp, deadline=deadline)
        actions_all = actions + verify_actions

        final_comment = build_final_comment(
            ticket,
            precheck=ctx.get("precheck") or {},
            rag=ctx.get("rag"),
            actions=actions_all,
            verify=verify,
            llm_metrics=ctx.get("llm_metrics"),
            escalate_reasons=list(escalate_reasons),
        )
```

- [ ] **Step 3: Прогон e2e-тестов (smoke)**

Run: `cd unified_rtk_v2 && pytest tests/test_e2e.py -v -m e2e`
Expected: существующие тесты не сломались (все патчат `_evaluate_llm_outcome` неявно через отсутствие данных — нужно убедиться, что функция толерантна к пустому context).

Если e2e ломаются потому, что `_evaluate_llm_outcome` не может работать с замоканным context — добавить в тест патч или обеспечить толерантность функции к отсутствию `llm_metrics` (уже сделано в Task 8: `metrics = (context or {}).get("llm_metrics") or {}`).

- [ ] **Step 4: Коммит**

```bash
cd unified_rtk_v2 && git add agent_api/main.py && git commit -m "feat(api): wire safety net evaluation into /tickets/intake"
```

---

## Task 12: E2E-сценарии (happy path, zero-action, МРФ-цикл)

**Files:**
- Modify: `unified_rtk_v2/tests/test_e2e.py`

- [ ] **Step 1: Добавить сценарий A (happy path с RAG)**

В `tests/test_e2e.py` в класс `TestTicketIntakeE2E` добавить:

```python
    @pytest.mark.e2e
    def test_happy_path_with_rag(self, client):
        from common.models import ActionLogEntry
        mock_actions = [
            ActionLogEntry(tool="check_edit_order_request", params={"order_id": "O1"}, ok=True),
            ActionLogEntry(tool="update_order_status", params={"order_id": "O1"}, ok=True),
        ]

        def fake_plan(ticket, ctx, mcp, deadline):
            ctx["llm_metrics"] = {
                "steps_used": 3,
                "rag_followed": 2,
                "rag_deviated": 0,
                "write_calls_total": 2,
                "loop_exceeded": False,
                "error_count": 0,
            }
            async def _inner():
                return mock_actions
            return _inner()

        mock_verify = (
            {
                "sulz_db": {"status": "DONE"},
                "eissd": {"status": "DONE"},
                "_diag": [],
                "logs_recheck": {
                    "pattern": "ORDER_STATUS_DENIED",
                    "window_days": 1,
                    "error_still_present": False,
                    "logs_full_count": 0,
                },
            },
            [],
        )

        with (
            patch("agent_api.main.precheck_logs", new_callable=AsyncMock) as m_pre,
            patch("agent_api.main.call_rag", new_callable=AsyncMock) as m_rag,
            patch("agent_api.main.plan_and_execute", side_effect=fake_plan) as m_plan,
            patch("agent_api.main.verify_final_status", new_callable=AsyncMock) as m_verify,
            patch("agent_api.main.finalize", new_callable=AsyncMock) as m_finalize,
        ):
            m_pre.return_value = {
                "precheck": {"logs": {"error_found": True, "error_code": "ORDER_STATUS_DENIED"}, "_diag": []}
            }
            m_rag.return_value = {"rag": {"required_actions": [
                {"tool": "check_edit_order_request"},
                {"tool": "update_order_status"},
            ]}}
            m_verify.return_value = mock_verify
            m_finalize.return_value = []

            resp = client.post(
                "/tickets/intake",
                json={"id": "T-HAPPY", "order_id": "O1", "description": "desc"},
            )
            assert resp.status_code == 200
            body = resp.json()["final_comment"]
            assert "llm.rag_followed=2" in body
            assert "escalate.triggered=false" in body
            assert "next_step=IN_WORK_WAIT_CONFIRMATION" in body
```

- [ ] **Step 2: Сценарий B (zero-action escalation)**

```python
    @pytest.mark.e2e
    def test_zero_action_escalation(self, client):
        def fake_plan(ticket, ctx, mcp, deadline):
            ctx["llm_metrics"] = {
                "steps_used": 1,
                "rag_followed": 0,
                "rag_deviated": 0,
                "write_calls_total": 0,
                "loop_exceeded": False,
                "error_count": 0,
            }
            async def _inner():
                return []
            return _inner()

        mock_verify = (
            {
                "sulz_db": {"status": "DENIED"},
                "eissd": {"status": "IN_PROGRESS"},
                "_diag": [],
                "logs_recheck": {
                    "pattern": "ORDER_STATUS_DENIED",
                    "window_days": 1,
                    "error_still_present": True,
                    "logs_full_count": 1,
                },
            },
            [],
        )

        with (
            patch("agent_api.main.precheck_logs", new_callable=AsyncMock) as m_pre,
            patch("agent_api.main.call_rag", new_callable=AsyncMock) as m_rag,
            patch("agent_api.main.plan_and_execute", side_effect=fake_plan),
            patch("agent_api.main.verify_final_status", new_callable=AsyncMock) as m_verify,
            patch("agent_api.main.finalize", new_callable=AsyncMock) as m_finalize,
        ):
            m_pre.return_value = {
                "precheck": {"logs": {"error_found": True, "error_code": "ORDER_STATUS_DENIED"}, "_diag": []}
            }
            m_rag.return_value = {"rag": None}
            m_verify.return_value = mock_verify
            m_finalize.return_value = []

            resp = client.post(
                "/tickets/intake",
                json={"id": "T-ZERO", "order_id": "O2", "description": "desc"},
            )
            assert resp.status_code == 200
            body = resp.json()["final_comment"]
            assert "llm.write_calls_total=0" in body
            assert "escalate.triggered=true" in body
            assert "escalate.reason.0=llm_no_action_taken" in body
            assert "next_step=ESCALATE_L2" in body
```

- [ ] **Step 3: Сценарий C (МРФ-цикл)**

```python
    @pytest.mark.e2e
    def test_mrf_cycle_via_stub_llm(self, client):
        from common.models import ActionLogEntry
        mock_actions = [
            ActionLogEntry(tool="resolve_mrf_queue", params={"region": "MSK"}, ok=True,
                           result={"queue": "ОЦО.МРФ.Эксплуатация СУЛЗ.MSK"}),
            ActionLogEntry(tool="mrf_process_ticket", params={"ticket_id": "T-MRF", "order_id": "O3", "region": "MSK"}, ok=True,
                           result={"mrf_verdict": "OK", "comment_added": True, "queue": "ОЦО.МРФ.Эксплуатация СУЛЗ.MSK", "details": {}}),
            ActionLogEntry(tool="list_otrs_comments", params={"ticket_id": "T-MRF"}, ok=True,
                           result={"comments": [{"ticket_id": "T-MRF", "text": "МРФ: OK", "source": "mrf_mock"}]}),
        ]

        def fake_plan(ticket, ctx, mcp, deadline):
            ctx["llm_metrics"] = {
                "steps_used": 3,
                "rag_followed": 0,
                "rag_deviated": 0,
                "write_calls_total": 2,  # resolve_mrf_queue + mrf_process_ticket
                "loop_exceeded": False,
                "error_count": 0,
            }
            async def _inner():
                return mock_actions
            return _inner()

        mock_verify = (
            {
                "sulz_db": {"status": "DONE"},
                "eissd": {"status": "DONE"},
                "_diag": [],
                "logs_recheck": {
                    "pattern": "ORDER_STATUS_DENIED",
                    "window_days": 1,
                    "error_still_present": False,
                    "logs_full_count": 0,
                },
            },
            [],
        )

        with (
            patch("agent_api.main.precheck_logs", new_callable=AsyncMock) as m_pre,
            patch("agent_api.main.call_rag", new_callable=AsyncMock) as m_rag,
            patch("agent_api.main.plan_and_execute", side_effect=fake_plan),
            patch("agent_api.main.verify_final_status", new_callable=AsyncMock) as m_verify,
            patch("agent_api.main.finalize", new_callable=AsyncMock) as m_finalize,
        ):
            m_pre.return_value = {
                "precheck": {"logs": {"error_found": True, "error_code": "ORDER_STATUS_DENIED"}, "_diag": []}
            }
            m_rag.return_value = {"rag": None}
            m_verify.return_value = mock_verify
            m_finalize.return_value = []

            resp = client.post(
                "/tickets/intake",
                json={"id": "T-MRF", "order_id": "O3", "description": "desc", "region": "MSK"},
            )
            assert resp.status_code == 200
            body = resp.json()["final_comment"]
            assert "llm.write_calls_total=2" in body
            assert "escalate.triggered=false" in body
            assert "next_step=IN_WORK_WAIT_CONFIRMATION" in body
```

- [ ] **Step 4: Запуск e2e**

Run: `cd unified_rtk_v2 && pytest tests/test_e2e.py -v -m e2e`
Expected: все passed (включая 3 новых сценария).

- [ ] **Step 5: Коммит**

```bash
cd unified_rtk_v2 && git add tests/test_e2e.py && git commit -m "test(e2e): add happy-path/zero-action/mrf-cycle scenarios"
```

---

## Task 13: Полный прогон и финальная проверка

- [ ] **Step 1: Запустить все тесты (unit + integration + e2e)**

Run: `cd unified_rtk_v2 && pytest -v -m "unit or integration or e2e"`
Expected: all green.

- [ ] **Step 2: Прогнать линтеры, если настроены**

Run: `cd unified_rtk_v2 && python -m compileall pipeline services common agent_api tests -q`
Expected: no errors.

- [ ] **Step 3: Вручную проверить формат `final_comment` через smoke-запрос (опционально)**

Run:
```bash
cd unified_rtk_v2 && python -c "
from common.models import Ticket
from datetime import datetime
from pipeline.pipeline import build_final_comment
t = Ticket(id='X', order_id='Y', subject='s', annotation='a', description='d', region='MSK', queue=None, created_at=datetime.utcnow())
print(build_final_comment(t, precheck={'logs': {'error_found': True}, '_diag': []}, rag=None, actions=[], verify={'_diag': [], 'logs_recheck': {'pattern': 'ORDER_STATUS_DENIED', 'window_days': 1, 'error_still_present': True, 'logs_full_count': 2}}, llm_metrics={'steps_used': 2, 'rag_followed': 0, 'rag_deviated': 0, 'write_calls_total': 0, 'loop_exceeded': False, 'error_count': 0}, escalate_reasons=['llm_no_action_taken']))
"
```
Expected: видно все новые поля `llm.*`, `verify.logs_recheck.*`, `escalate.*`, `next_step=ESCALATE_L2`.

- [ ] **Step 4: Финальный коммит (если есть, что коммитить)**

```bash
cd unified_rtk_v2 && git status
```
Если ничего нет — пропустить. Иначе:
```bash
cd unified_rtk_v2 && git add -A && git commit -m "chore: finalize pipeline-agent-gaps implementation"
```

---

## Покрытие спецификации

| Раздел спеки | Задача |
|---|---|
| Компонент A: мок `mrf_process_ticket` | Task 3, 4, 5, 6 |
| Компонент B: LLM-фаза (промпт, tools, метрики) | Task 10 |
| Компонент C: `_evaluate_llm_outcome` | Task 8 |
| Компонент D: `verify_final_status` recheck | Task 7 |
| Компонент E: поля в `build_final_comment` + next_step | Task 9 |
| Конфигурация (`LLM_MAX_STEPS`, `LLM_MAX_TOOL_ERRORS`, `VERIFY_RECHECK_WINDOW_DAYS`, `MRF_MOCK_SEED`) | Task 1 |
| Метрика `llm_safety_triggers_total` | Task 2 |
| Шаг `verify_logs_recheck` в `pipeline_steps_total` | Task 7 (инкремент внутри функции) |
| Интеграция в `POST /tickets/intake` | Task 11 |
| Unit-тесты pipeline | Task 7, 8, 9 |
| Unit-тесты мока MRF | Task 4 |
| Integration-тесты `mrf_process_ticket` + `list_otrs_comments` | Task 6 |
| E2E сценарии A/B/C | Task 12 |

## Что НЕ делаем (из спеки)

- Не трогаем реальный OTRS/Kafka/МРФ.
- Не меняем `POST /tickets/intake` response-схему (`TicketOut`).
- Не переписываем `providers/*`.
- Не меняем `RagResponse` схему.
- Не удаляем `llm_max_iterations` (оставляем для обратной совместимости, хотя `run_planning_loop` переключается на `llm_max_steps`).
