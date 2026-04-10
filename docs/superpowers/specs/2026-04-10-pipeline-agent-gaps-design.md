# Дизайн: закрытие расхождений пайплайна агента со спецификацией

**Дата:** 2026-04-10
**Область:** `unified_rtk_v2` — пайплайн агента, MCP-сервер, тесты
**Основание:** расхождения между `agent.txt` / `agent.jpg` (зона «Проект студентов») и текущей реализацией, выявленные при сверке.

## Контекст и цели

Сверка реализации с функциональной спецификацией (`agent.txt`) обнаружила ряд функциональных расхождений в зоне ответственности студентов (скрытая инфраструктура: Kafka, микросервис-посредник — не трогаем):

- **Шаг 5.2** — «назначение инцидента на очередь МРФ/ИС» выполняется только как опциональная смена очереди в финализации, а не как отдельный этап посередине пайплайна.
- **Шаг 5.3** — «после возврата инцидента от МРФ/ИС — анализ комментариев» отсутствует как этап (`list_otrs_comments` существует, но не используется).
- **Шаг 5.5 / 5.6** — `check_edit_order_request` и `update_order_status` доступны только через LLM tool-loop, без гарантии выполнения.
- **Шаг 5.9** — повторный `search_logs` в финальных проверках не выполняется.

Вторая проблема, обнаруженная при проектировании: текущая роль LLM слабо формализована — модель получает большой тулбокс без чёткой ответственности, может пропускать критичные действия, а пайплайн никак не реагирует.

**Цель:** закрыть указанные функциональные расхождения **и** сформулировать границы ответственности между детерминированным скелетом пайплайна и автономной LLM-фазой так, чтобы LLM оставалась полноценным AI-агентом (принимала решения по контексту), а пайплайн обеспечивал безопасность и гарантии финализации.

**Не-цели:**
- Интеграция с реальным OTRS, Kafka, МРФ.
- Замена LLM-провайдера или изменение моделей.
- Рефакторинг `services/llm_service.py` или `pipeline.py`, выходящий за рамки перечисленных изменений.

## Ключевое архитектурное решение

**LLM — автономный агент в ограниченной зоне; пайплайн — тонкий скелет с safety net.**

Финализация тикета, расчёт итогового комментария и финальная верификация остаются в детерминированном коде. Внутри же фазы `plan_and_execute` LLM свободно интерпретирует контекст, принимает решения, адаптирует рекомендации RAG к реальному состоянию заказа и вызывает инструменты.

RAG-рекомендации передаются LLM **как совет экспертной системы, а не как обязательный чек-лист** — это осознанный отказ от enforcement-подхода в пользу агентной автономии. Безопасность обеспечивается не принуждением к конкретным действиям, а:

1. Жёсткими границами доступа (LLM не имеет инструментов финализации).
2. Аудитом всех действий и метриками поведения.
3. Эскалацией при узких признаках провала (нулевая активность при наличии проблемы, исчерпание лимита шагов, повторные ошибки, непройденный финальный recheck).

## Общая архитектура пайплайна (после изменений)

```
POST /tickets/intake
  ↓
1. precheck_logs                 [скелет, без изменений]
  ↓
2. call_rag                      [скелет, без изменений]
  ↓
3. plan_and_execute (LLM-фаза)   [модифицировано — сужен тулбокс, переработан промпт, добавлены метрики]
  ↓
4. _evaluate_llm_outcome         [НОВОЕ — проверка safety-триггеров после LLM-фазы]
  ↓
5. verify_final_status           [модифицировано — добавлен search_logs recheck]
  ↓
6. build_final_comment           [модифицировано — новые поля llm.*, verify.logs_recheck.*, escalate.*]
  ↓
7. finalize                      [скелет, без изменений]
```

## Компоненты

### Компонент A. Мок `mrf_process_ticket` в MCP-сервере

**Назначение:** закрыть шаги 5.2 и 5.3 через эмуляцию синхронного цикла «запрос → обработка МРФ → возврат комментария».

**Вход:**
```
{ticket_id: str, order_id: str, region: str}
```

**Поведение:**
1. Считывает текущее состояние заказа из storage (`storage.py`).
2. Детерминированно выбирает вердикт из фиксированного набора на основе hash от `order_id` и региона. Набор вердиктов:
   - `OK` — обработка завершена, статус синхронизирован.
   - `NEEDS_MANUAL` — требуется ручная проверка.
   - `EDIT_ORDER_PENDING` — обнаружена заявка на редактирование.
   - `ORDER_NOT_FOUND_IN_EISSD` — заказ отсутствует в ЕИССД.
3. Добавляет в storage тикета комментарий от имени МРФ с соответствующим текстом (через тот же механизм, которым работает `add_otrs_comment`, но с меткой `source="mrf_mock"`).
4. Возвращает структурированный ответ:

```json
{
  "mrf_verdict": "OK|NEEDS_MANUAL|EDIT_ORDER_PENDING|ORDER_NOT_FOUND_IN_EISSD",
  "comment_added": true,
  "queue": "<resolved queue name>",
  "details": {
    "order_id": "...",
    "region": "..."
  }
}
```

**Как LLM использует:**
1. Видит признаки необходимости МРФ-обработки в контексте (precheck, ticket, RAG).
2. Вызывает `resolve_mrf_queue(region)` для получения очереди.
3. Вызывает `mrf_process_ticket(ticket_id, order_id, region)`.
4. Вызывает `list_otrs_comments(ticket_id)` и читает свежий комментарий от МРФ.
5. На основании `mrf_verdict` и содержимого комментария решает следующий шаг.

**Детерминизм:** функция хэширования от `order_id` зафиксирована; `MRF_MOCK_SEED` (env) позволяет переопределить, чтобы тесты могли целенаправленно провоцировать нужный вердикт.

### Компонент B. LLM-фаза (`plan_and_execute`) — переработка

**Изменения в системном промпте:**
- Явный блок контекста: `precheck.logs`, поля тикета, `RAG.required_actions` (если не пусто).
- Формулировка про RAG: «Это рекомендации экспертной системы, основанные на похожих кейсах. Оцени их применимость к текущему состоянию. Ты можешь им следовать, адаптировать параметры или отклониться, если состояние показывает, что они неприменимы».
- Разделение tools на read (для диагностики) и write (для исполнения).
- Явное ограничение: «Инструменты финализации тикета тебе недоступны. Финализация выполняется автоматически после твоей фазы».
- Лимит шагов: `LLM_MAX_STEPS` (по умолчанию 12).

**Набор tools, доступных LLM:**
| Класс | Инструменты |
|---|---|
| Read | `search_logs`, `get_order_status`, `check_eissd_status`, `get_otrs_ticket`, `list_otrs_comments` |
| Write | `check_edit_order_request`, `update_order_status`, `resolve_mrf_queue`, `mrf_process_ticket`, `add_otrs_comment` (промежуточные) |
| Недоступно | `update_otrs_ticket` (только пайплайн, в `finalize`) |

**Новые метрики, собираемые за LLM-фазу (кладутся в `context["llm_metrics"]`):**
- `steps_used` — число итераций.
- `rag_followed` — сколько имён инструментов из `RAG.required_actions` встретились в `action_log`.
- `rag_deviated` — сколько required_actions из RAG не встретились (simple name-based).
- `write_calls_total` — число вызовов write-инструментов.
- `loop_exceeded` — true, если упёрлась в `LLM_MAX_STEPS` без `finish`.
- `error_count` — число tool calls, завершившихся ошибкой.

Подсчёт `rag_followed` / `rag_deviated` — по именам инструментов, без строгой проверки параметров. Если LLM вызвала инструмент с адаптированными параметрами — засчитывается как `followed`.

### Компонент C. Safety net (`_evaluate_llm_outcome`)

Новая функция в `pipeline.py`:

```python
def _evaluate_llm_outcome(
    actions: list[ActionLogEntry],
    context: dict[str, Any],
) -> tuple[bool, list[str]]:
    """Возвращает (should_escalate, reasons) по метрикам LLM-фазы."""
```

Вызывается в `intake` после `plan_and_execute` и до `verify_final_status`. Причина вызова до verify — мы ещё не знаем, был ли recheck успешным, но уже знаем, вела ли себя LLM разумно.

**Триггеры до verify:**
1. `precheck.error_found=true` **и** `llm_metrics.write_calls_total == 0` → `llm_no_action_taken`
2. `llm_metrics.loop_exceeded == true` → `llm_loop_exceeded`
3. `llm_metrics.error_count >= LLM_MAX_TOOL_ERRORS` (по умолчанию 3) → `llm_tool_errors_repeated`

**Дополнительный триггер после verify** (применяется в `build_final_comment`):
4. `precheck.error_found=true` **и** `verify.logs_recheck.error_still_present=true` → `error_persists_after_execution`

Список `reasons` сохраняется в context и попадает в final_comment как `escalate.reason.N=<code>`.

### Компонент D. `verify_final_status` — recheck логов

После успешных `get_order_status` + `check_eissd_status` в последней (финальной) итерации цикла backoff добавляется третий вызов:

```python
raw_recheck = await mcp.call_tool(
    "search_logs",
    {
        "order_id": ticket.order_id,
        "pattern": PRECHECK_PATTERN,
        "window_days": VERIFY_RECHECK_WINDOW_DAYS,  # по умолчанию 1
    },
)
resp_recheck, code, fatal = _unwrap_mcp_dict("search_logs", raw_recheck)
# стандартная обработка diag/fatal
results["logs_recheck"] = {
    "pattern": PRECHECK_PATTERN,
    "window_days": VERIFY_RECHECK_WINDOW_DAYS,
    "error_still_present": bool(resp_recheck.get("error_found")) if isinstance(resp_recheck, dict) else None,
    "logs_full_count": len(resp_recheck.get("logs_full") or []) if isinstance(resp_recheck, dict) else None,
}
```

Вызов происходит **один раз** на финальной успешной итерации, не на каждой попытке backoff'а — чтобы не греть MCP лишними запросами.

### Компонент E. `build_final_comment` — новые поля

К существующему шаблону `RTK_AGENT_FINAL v1` добавляются строки:

```
llm.steps_used=N
llm.rag_followed=N
llm.rag_deviated=N
llm.write_calls_total=N
llm.loop_exceeded=true|false
llm.error_count=N
verify.logs_recheck.window_days=N
verify.logs_recheck.error_still_present=true|false|
verify.logs_recheck.logs_full_count=N
escalate.triggered=true|false
escalate.reason.0=<code>
escalate.reason.1=<code>
```

Пустые значения (например, когда LLM-фаза упала или verify.logs_recheck=None) — пустая строка справа от `=`, как уже сделано в существующих полях.

**Обновлённая логика `next_step`:**
1. Любой эскалационный reason → `ESCALATE_L2`.
2. Иначе, если `precheck.error_found=false` → `NO_ERROR_IN_LOGS`.
3. Иначе, если `actions.ok=false` → `ESCALATE_L2` (как сейчас).
4. Иначе → `IN_WORK_WAIT_CONFIRMATION`.

## Данные и поток исполнения

```
Ticket → precheck_logs → context[precheck]
       → call_rag       → context[rag]
       → plan_and_execute → actions[], context[llm_metrics]
       → _evaluate_llm_outcome → context[escalate_reasons_pre_verify]
       → verify_final_status → context[verify] (с logs_recheck)
       → (в build_final_comment): дополнение escalate_reasons по verify
       → final_comment (детерминированный)
       → finalize → действия add_otrs_comment + update_otrs_ticket
```

`context` — обычный `dict`, накапливает данные по шагам, как сейчас.

## Обработка ошибок

- **RAG недоступен:** `call_rag` возвращает `{"rag": None, "rag_error": ...}` (как сейчас). LLM получает в промпте пометку «RAG недоступен, действуй по precheck + тикету». Если `precheck.error_found=true` и LLM ничего не предпримет — сработает триггер `llm_no_action_taken`.
- **MCP-инструмент возвращает ошибку:** как сейчас, через `_unwrap_mcp_dict` и diag-коды. Для LLM ошибки tool calls учитываются в `llm_metrics.error_count`.
- **LLM-провайдер не отвечает:** существующая логика fallback (`llm_fallback_total`) сохраняется. При fallback `loop_exceeded` не выставляется, но `steps_used=0` и `write_calls_total=0` — сработает триггер эскалации.
- **`mrf_process_ticket` падает:** обычная обработка через `_unwrap_mcp_dict`, LLM получит ошибку и решит, что делать (повторить, пропустить, эскалировать).

## Конфигурация

Новые переменные в `.env` / `common/config.py`:

| Переменная | По умолчанию | Описание |
|---|---|---|
| `LLM_MAX_STEPS` | `12` | Лимит итераций tool-loop; превышение → `llm_loop_exceeded` |
| `LLM_MAX_TOOL_ERRORS` | `3` | Порог ошибок tool calls для триггера эскалации |
| `VERIFY_RECHECK_WINDOW_DAYS` | `1` | Окно для `search_logs` recheck в `verify_final_status` |
| `MRF_MOCK_SEED` | `0` | Seed для детерминизма мока `mrf_process_ticket` |

Существующие (`ALLOW_QUEUE_CHANGE`, `RAG_BASE_URL`, `LLM_*`, и т.д.) не меняются.

## Обратная совместимость

- **API `POST /tickets/intake`:** `TicketOut` не меняется (`ticket_id`, `final_comment`, `summary`, `actions`).
- **Формат `final_comment`:** расширяется новыми key=value строками. Новые парсеры должны игнорировать незнакомые ключи. Старые поля сохраняются.
- **Метрики Prometheus:** добавляется шаг `verify_logs_recheck` в `pipeline_steps_total` и новый счётчик `llm_safety_triggers_total{reason="..."}`.
- **Существующие тесты:** сохраняются; обновляются только те, которые зависят от изменённых полей (`build_final_comment` unit-тесты, `verify_final_status` тесты).

## Тестирование

### Unit (`pytest`)

- `test_unit_pipeline.py`:
  - `verify_final_status` с logs_recheck: чистые логи, логи с ошибкой, MCP exception, fatal_type.
  - `_evaluate_llm_outcome`: покрытие всех трёх pre-verify триггеров + нормальный путь.
  - `build_final_comment`: присутствие новых полей; корректность `next_step` для всех комбинаций (`escalate`, `NO_ERROR_IN_LOGS`, `IN_WORK_WAIT_CONFIRMATION`, `ESCALATE_L2` по `actions.ok=false`).
- `test_unit_mrf_mock.py` (новый):
  - Детерминизм: одинаковый `order_id` → одинаковый вердикт.
  - Комментарий добавляется в storage и виден через `list_otrs_comments`.
  - Все варианты вердикта достижимы через разные `order_id`.

### Интеграционные (`pytest -m integration`)

- `test_integration_services.py`:
  - `mrf_process_ticket` через живой subprocess MCP, проверка структуры ответа.
  - `list_otrs_comments` видит комментарий, оставленный `mrf_process_ticket`.

### E2E (`pytest -m e2e`)

- `test_e2e.py`:
  - **Сценарий A (happy path с RAG):** `precheck.error_found=true`, RAG возвращает `required_actions=[check_edit_order_request, update_order_status]`, stub-LLM исполняет оба, `verify.logs_recheck.error_still_present=false`, `next_step=IN_WORK_WAIT_CONFIRMATION`, `llm.rag_followed=2`, `escalate.triggered=false`.
  - **Сценарий B (эскалация, zero actions):** `precheck.error_found=true`, RAG пустой, stub-LLM возвращает finish без tool calls, `llm.write_calls_total=0`, `escalate.triggered=true`, `escalate.reason.0=llm_no_action_taken`, `next_step=ESCALATE_L2`.
  - **Сценарий C (МРФ-цикл):** stub-LLM вызывает `resolve_mrf_queue` → `mrf_process_ticket` → `list_otrs_comments`, получает комментарий от МРФ, принимает решение; `actions[]` содержит все три вызова; `next_step` зависит от вердикта.

### TDD-порядок

Любая доработка: unit (красный) → unit (зелёный) → рефакторинг → интеграционный → e2e. Это фиксируется в плане имплементации.

## Границы ответственности

| Кто | За что отвечает |
|---|---|
| **Пайплайн (код)** | Скелет: precheck, вызов RAG, запуск LLM-фазы, verify, финальный комментарий, финализация тикета. Safety net. Определение `next_step`. |
| **LLM** | Внутри `plan_and_execute`: интерпретация RAG + тикета, выбор и параметризация write-действий, чтение состояния через read-tools, адаптация к edge cases, МРФ-цикл. |
| **RAG** | Даёт рекомендации (`required_actions` + reasoning). Может быть точной или размытой — LLM разберётся. |
| **MCP-сервер** | Инструменты для работы с заказами/OTRS, включая новый мок `mrf_process_ticket`. |

## Открытые вопросы (не блокируют имплементацию)

1. **`llm.rationale` в `final_comment`:** итоговый комментарий OTRS остаётся детерминированным, LLM-рассуждения не включаются. Текстовый rationale, если LLM его вернёт, попадает только в `actions[]` (debug-режим) и в логи.
2. **Точные формулировки комментариев МРФ в моке:** русскоязычные, конкретные тексты подберём при реализации; тесты проверяют структуру, не дословный текст.
3. **Метрики `llm.rag_followed` / `llm.rag_deviated`:** подсчитываются по именам инструментов (name-based), без проверки совпадения параметров. Это осознанное упрощение.

## Что НЕ входит в эту работу

- Интеграция с реальным OTRS / Kafka / МРФ.
- Реализация «возврата от МРФ» через событийную шину (остаётся моком).
- Переписывание `services/llm_service.py` за пределами нового промпта и сужения tool-list.
- Изменение схемы `RagResponse` (`required_actions` остаётся тем же `list[dict]`, схема свободная).
- Изменение формата ответа `POST /tickets/intake`.
