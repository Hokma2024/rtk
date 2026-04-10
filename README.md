# II Agent

## Быстрый старт

```bash
cp .env.example .env          # укажите LLM_API_KEY, если используете openrouter
docker-compose up --build
```

Проверка работоспособности:
впрочем они итак переодически в контейнере проверяются

```bash
curl -s http://localhost:8080/health
curl -s http://localhost:8090/health
```

## Стек мониторинга (Prometheus + Grafana + Loki)

```bash
docker-compose --profile monitoring up --build
```

Grafana: http://localhost:3000 (admin/admin), Prometheus: http://localhost:9090

## Запуск тестов

```bash
# Unit- и contract-тесты (внешние сервисы не требуются)
pytest

# Интеграционные тесты (нужен запущенный MCP-сервер в subprocess)
pytest -m integration

# End-to-end тесты (нужен полный стек docker-compose)
pytest -m e2e
```

## Переменные окружения

Полный список поддерживаемых переменных с дефолтами и описаниями — в `.env.example`.

---

## 1. Как это работает

Сервис `agent` принимает OTRS-тикет по HTTP, прогоняет его через пайплайн и обновляет тикет через MCP-инструменты.

Пайплайн:

1. **Precheck** (обязательно): поиск в логах `ORDER_STATUS_DENIED` за последние 30 дней через MCP `search_logs`.
2. **RAG**: отправка объединённого запроса (precheck + subject + annotation + description) в RAG (mock); получение JSON-рекомендаций. Вызывается **один раз за тикет** — повторный запрос после возврата МРФ (шаг 5.4 спеки) намеренно не выполняется как избыточный.
3. **LLM**: выбор и вызов нужных MCP-инструментов (`LLM_MODE=tools` или `LLM_MODE=json`).
4. **МРФ-обход** (шаги 5.1–5.3, детерминированно): `resolve_mrf_queue(region)` → `mrf_process_ticket(ticket_id, order_id, region)` → `list_otrs_comments(ticket_id)`. Результат (`queue`, `verdict`, дословный комментарий МРФ) попадает в финальный комментарий в блок `mrf.*`.
5. **Verify**: опрос финальных статусов через MCP (`get_order_status`, `check_eissd_status`) + recheck логов.
6. **Финальный комментарий**: собирается детерминированно из шаблона в коде (key=value), без генерации через LLM. Содержит блоки `precheck.*`, `mrf.*`, `rag.action.*` (дословные `required_actions` из RAG), `verify.*`, `escalate.*`.
7. **Finalize**: добавление комментария к тикету и обновление тикета (статус `OPEN` = «В работе» в терминах OTRS, `assignee=null`; очередь по умолчанию — `ОЦО.МРФ.Эксплуатация СУЛЗ.{region}`, меняется только при `ALLOW_QUEUE_CHANGE=true`).

## 2. Компоненты и порты

- Agent API: http://localhost:8080
  - Swagger UI: http://localhost:8080/docs
  - Health: http://localhost:8080/health
  - Metrics: http://localhost:8080/metrics

- RAG mock: http://localhost:8090
  - Health: http://localhost:8090/health

- Ollama на хосте: http://localhost:11434 (из контейнера agent: `http://host.docker.internal:11434`)

Примечание: MCP-сервер запускается по stdio как subprocess внутри контейнера agent — отдельный сетевой сервис не нужен.

## 3. Требования

- Docker + Docker Compose
- Ollama на хосте с моделью `qwen3:8b` (или настройте `LLM_PROVIDER=openrouter`)
- Свободные порты: 8080, 8090

## 4. Конфигурация

Скопируйте `.env.example` в `.env` и отредактируйте. Ключевые переменные:

| Переменная                  | По умолчанию (`.env.example`)   | Описание                                                              |
| --------------------------- | ------------------------------- | --------------------------------------------------------------------- |
| `LLM_PROVIDER`              | `ollama`                        | `ollama` (локально, без ключей) или `openrouter`                      |
| `LLM_API_KEY`               | —                               | Обязательно для openrouter                                            |
| `LLM_MODEL_NAME`            | `qwen3:8b`                      | Название модели Ollama/OpenRouter                                     |
| `LLM_MODE`                  | `tools`                         | `tools` (реальная LLM), `json`, `fallback` (без LLM, исполняет RAG-план) |
| `LLM_MAX_ITERATIONS`        | `6`                             | Максимум итераций LLM-цикла                                           |
| `LLM_MAX_STEPS`             | `12`                            | Максимум шагов LLM-фазы                                               |
| `LLM_MAX_TOOL_ERRORS`       | `3`                             | Порог ошибок tool-вызовов до fallback                                 |
| `LLM_TIMEOUT_SECONDS`       | `30`                            | Таймаут одного LLM-запроса                                            |
| `OLLAMA_HOST`               | `http://host.docker.internal:11434` | Endpoint Ollama                                                   |
| `OLLAMA_THINK`              | `0`                             | Qwen3/r1 thinking mode: `0` off, `1` on                               |
| `RAG_BASE_URL`              | `http://rag_mock:8090`          | URL RAG-сервиса                                                       |
| `MCP_SERVER_MODULE`         | `services.mcp_server.mcp_server`| Модуль MCP-сервера для stdio-subprocess                               |
| `REQUEST_TIME_BUDGET_SECONDS` | `90`                          | Общий бюджет времени обработки тикета (в compose — `180`)             |
| `VERIFY_RECHECK_WINDOW_DAYS`| `1`                             | Окно recheck для verify-фазы                                          |
| `ALLOW_QUEUE_CHANGE`        | `false`                         | Разрешить смену очереди МРФ                                           |
| `DEBUG`                     | `false`                         | Включать `actions` в ответ API (в compose — `1`)                      |
| `MCP_DEBUG`                 | `false`                         | Подробные логи MCP                                                    |

## 5. Пример рабочего тикета

Отправка тикета в агент через `POST /tickets/intake`:

```bash
curl -s -X POST http://localhost:8080/tickets/intake \
  -H "Content-Type: application/json" \
  -d '{
    "id": "T-12345",
    "order_id": "O-987654",
    "subject": "Заявка зависла в статусе DENIED",
    "annotation": "Клиент сообщает, что подключение не активируется более суток",
    "description": "Пользователь оформил заявку на подключение интернета. В логах ORDER_STATUS_DENIED за последние сутки. Требуется проверка статуса в СУЛЗ и ЕИССД, при необходимости — повторный запуск.",
    "region": "MSK",
    "queue": "Support::L1",
    "metadata": {"source": "otrs", "priority": "normal"}
  }'
```

Пример успешного ответа (HTTP 200). Поле `summary` в коде — это первая строка `final_comment` (`agent_api/main.py:137`), то есть всегда заголовок формата `RTK_AGENT_FINAL v1`:

```json
{
  "ticket_id": "T-12345",
  "final_comment": "RTK_AGENT_FINAL v1\nticket_id=T-12345\nprecheck.error_found=true\nprecheck.logs_full_count=3\nverify.sulz_db.status=OK\nverify.eissd.status=OK\ndiag.count=0\nnext_step=IN_WORK_WAIT_CONFIRMATION\n",
  "summary": "RTK_AGENT_FINAL v1"
}
```

Поля запроса (`TicketIn`):

| Поле          | Тип    | Обязательно    | Описание                  |
| ------------- | ------ | -------------- | ------------------------- |
| `id`          | string | да             | Идентификатор OTRS-тикета |
| `order_id`    | string | да             | Идентификатор заявки      |
| `subject`     | string | нет            | Тема тикета               |
| `annotation`  | string | нет            | Краткая аннотация         |
| `description` | string | да             | Полное описание проблемы  |
| `region`      | string | нет (`COMMON`) | Регион (например, `MSK`)  |
| `queue`       | string | нет            | Текущая очередь OTRS      |
| `metadata`    | object | нет            | Произвольные метаданные   |

## 6. Диагностика

### Агент не стартует

```bash
docker-compose logs -n 200 agent
# Или перезапуск вручную:
docker-compose exec -T agent uvicorn agent_api.main:app --host 0.0.0.0 --port 8080
# Или пересборка без кэша:
docker-compose down && docker-compose build --no-cache agent && docker-compose up
```

### Проверка доступности Ollama из контейнера

```bash
docker-compose exec -T agent python - <<'PY'
import os, httpx
host = os.getenv("OLLAMA_HOST")
print("OLLAMA_HOST:", host)
r = httpx.get(host + "/api/tags", timeout=5)
print("GET /api/tags:", r.status_code)
print(r.text[:200])
PY
```

### LLM уходит в fallback

Проверьте метрику `llm_fallback_total`:

```bash
curl -s http://localhost:8080/metrics | grep llm_fallback_total
```

Если `tools_fallback` растёт — переключитесь на `LLM_MODE=json` или используйте модель с лучшей поддержкой tool-calling.

### Разбор final_comment

Ключевые поля:

- `precheck.error_found=true|false`
- `precheck.logs_full_count` (непустое число)
- `verify.sulz_db.status`, `verify.eissd.status`
- `diag.count=0` (если не ноль — смотрите `diag.0`, `diag.1` и логи)
- `next_step=IN_WORK_WAIT_CONFIRMATION` (когда ошибка найдена и `actions.ok=true`)

### Включение debug-режима (actions в ответе)

Выставьте `DEBUG=true` в `.env` и перезапустите. Ответ `/tickets/intake` будет содержать `actions[]` с именем инструмента, параметрами, ok/error и `duration_ms`.

### MCP-инструменты не работают

Выставьте `MCP_DEBUG=true` в `.env` и проверьте логи агента.
