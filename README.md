# Unified RTK Agent (prototype)

## 1. Что это и как работает

Сервис `agent` принимает тикет (OTRS-поля) по HTTP, выполняет пайплайн и обновляет тикет через MCP-tools.

Пайплайн:

1. Precheck (обязательный): всегда ищет в логах `ORDER_STATUS_DENIED` за 30 дней через MCP tool `search_logs`.
2. RAG: отправляет в RAG (mock) объединённый запрос (precheck + subject + annotation + description), получает JSON-рекомендацию.
3. LLM: выбирает и вызывает нужные MCP-tools (режим `LLM_MODE=tools` или `LLM_MODE=json`).
4. Verify (контроль): делает цикл проверки статусов через MCP (`get_order_status`, `check_eissd_status`).
5. Final comment: формируется детерминированно кодом (шаблон `key=value`), без генерации LLM.
6. Finalize: добавляет комментарий в тикет и обновляет тикет (статус `OPEN`, `assignee=null`; очередь не меняется, если `ALLOW_QUEUE_CHANGE=0`).

## 2. Компоненты и порты

- Agent API: [http://localhost:8080](http://localhost:8080)
  - Swagger UI: [http://localhost:8080/docs](http://localhost:8080/docs)
  - OpenAPI JSON: [http://localhost:8080/openapi.json](http://localhost:8080/openapi.json)
  - Health: [http://localhost:8080/health](http://localhost:8080/health)
  - Metrics: [http://localhost:8080/metrics](http://localhost:8080/metrics)

- RAG mock: [http://localhost:8090](http://localhost:8090)
  - Health: [http://localhost:8090/health](http://localhost:8090/health)

- Ollama на хосте: [http://localhost:11434](http://localhost:11434) (из контейнера agent: `http://host.docker.internal:11434`)

Важно: MCP-server работает по stdio и запускается внутри контейнера agent как subprocess. Отдельный сетевой MCP-сервис не требуется.

## 3. Требования

- Docker + Docker Compose
- Ollama на хосте (модель `qwen3:8b` скачана)
- Свободные порты: 8080, 8090

## 4. Конфигурация (.env)

Создай файл `.env` в корне (или задай переменные в compose). Минимальный набор:

```dotenv
DEBUG=0
REQUEST_TIME_BUDGET_SECONDS=180

MCP_SERVER_MODULE=services.mcp_server.mcp_server
MCP_DEBUG=0

RAG_BASE_URL=http://rag_mock:8090

LLM_MODE=tools
LLM_PROVIDER=ollama
LLM_MODEL_NAME=qwen3:8b
LLM_TIMEOUT_SECONDS=60
LLM_MAX_ITERATIONS=6
OLLAMA_HOST=http://host.docker.internal:11434

ALLOW_QUEUE_CHANGE=0
```

Рекомендуемо для Linux (чтобы `host.docker.internal` работал):

- в `docker-compose.yml` у agent должен быть `extra_hosts: ["host.docker.internal:host-gateway"]`.

## 5. Запуск (Docker)

В корне репозитория:

```bash
docker compose up --build
```

Проверка что сервисы поднялись:

```bash
curl -s http://localhost:8080/health
curl -s http://localhost:8090/health
```

## 6. Важно: agent иногда может не стартовать сам

Иногда контейнер `agent` не хочет поднимаеться.

Что делать:

1. Посмотреть логи или интерфейс docker:

```bash
docker compose logs -n 200 agent
```

2. Если контейнер жив, но сервера нет — запустить вручную внутри контейнера или нажать кнопку запуска в интерфейсе docker:

```bash
docker compose exec -T agent uvicorn agent_api.main:app --host 0.0.0.0 --port 8080
```

1. Если изменения не подхватываются — пересобрать без кэша:

```bash
docker compose down
docker compose build --no-cache agent
docker compose up
```

## 7. Проверка доступности Ollama из контейнера agent

Команда:

```bash
docker compose exec -T agent python - <<'PY'
import os, httpx
host=os.getenv("OLLAMA_HOST")
print("OLLAMA_HOST:", host)
r=httpx.get(host + "/api/tags", timeout=5)
print("GET /api/tags:", r.status_code)
print(r.text[:200])
PY
```

Ожидаемо: `200` и список моделей, включая `qwen3:8b`.

## 8. Как отправить тикет через Swagger UI

1. Открыть: [http://localhost:8080/docs](http://localhost:8080/docs)
2. Найти endpoint `POST /tickets/intake`.
3. Нажать `Try it out`.
4. В поле Request body вставить JSON (пример ниже).
5. Нажать `Execute`.
6. Смотреть:
   - HTTP code (должен быть 200)
   - Response body: `ticket_id`, `final_comment`, `summary` (+ `actions` только при DEBUG=1)

Пример запроса (кейс где precheck должен найти ошибку):

```json
{
  "id": "T-2",
  "order_id": "1800003902272",
  "subject": "Ошибка ORDER_STATUS_DENIED",
  "annotation": "Тест precheck true",
  "description": "ORDER_STATUS_DENIED по заявке 1800003902272",
  "region": "COMMON",
  "queue": "ОЦО.МРФ.Эксплуатация СУЛЗ.COMMON",
  "metadata": {}
}
```

## 9. Как понять, что пайплайн отработал правильно (по final_comment)

В `final_comment` проверить ключевые поля:

- Precheck:
  - `precheck.pattern=ORDER_STATUS_DENIED`
  - `precheck.window_days=30`
  - `precheck.error_found=true|false`
  - `precheck.logs_full_count` (не пустое число)

- RAG:
  - `rag.required_actions_count`

- Verify:
  - `verify.sulz_db.status=...`
  - `verify.eissd.status=...`

- Диагностика:
  - `diag.count=0` (если не 0 — смотреть `diag.0`, `diag.1` и логи)

- Следующий шаг:
  - `next_step=IN_WORK_WAIT_CONFIRMATION` (когда ошибка обнаружена и actions.ok=true)

## 10. Как понять, что LLM реально участвует

1. Логи `agent` должны содержать запросы к Ollama:
   - `POST http://host.docker.internal:11434/api/chat "HTTP/1.1 200 OK"`

2. Метрики:

```bash
curl -s http://localhost:8080/metrics | grep llm_fallback_total
```

Интерпретация:

- `llm_fallback_total{mode="tools_fallback"}` растёт: tools-режим не сработал (LLM не вернула tool_calls / ошибка), пошли в fallback-план.
- `llm_fallback_total{mode="fallback"}` растёт: включён `LLM_MODE=fallback` (LLM не используется).
- Если `llm_fallback_total` не растёт, а время запроса увеличилось и есть `/api/chat` в логах — LLM участвует без fallback.

## 11. Как включить подробности действий (debug)

По умолчанию `/tickets/intake` не возвращает `actions`.

Чтобы вернуть `actions`:

- выставить `DEBUG=1` (в `.env` или env контейнера),
- перезапустить compose.

В ответе появится массив `actions[]`:

- tool name
- params
- ok/error/error_type
- duration_ms

## 12. Типовые проблемы и что смотреть

### 12.1. LLM не работает (нет запросов к /api/chat)

Проверить:

- `OLLAMA_HOST` задан в env контейнера agent
- из контейнера: `/api/tags` возвращает 200 (см. раздел 7)

### 12.2. LLM работает, но падает в fallback

Смотреть:

- `llm_fallback_total`
- логи `agent` (ошибки `LLM call failed` / формат ответа)

Если qwen3:8b не даёт стабильный tool-calling:

- переключить `LLM_MODE=json` (план одним JSON), оставить `fallback` как резерв.

### 12.3. Кэш Docker не подхватил изменения

Решение: `docker compose build --no-cache agent`.

### 12.4. MCP tools не работают

Смотреть `MCP_DEBUG=1` и логи клиента MCP.
