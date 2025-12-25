import json
import re
from typing import Optional, List, Dict, Any, Tuple

import httpx
from fastapi import FastAPI
from pydantic import BaseModel


app = FastAPI(title="SULZ Agent (Prototype)")


# ==============================
# HARDCODED CONFIG (как просил)
# ==============================
# В docker-compose эти имена резолвятся по сети compose:
MCP_BASE_URL = "http://mcp-server:8002"
RAG_BASE_URL = "http://rag-mock:8001"

# LLM живёт на хосте (ollama). В docker-compose должен быть extra_hosts host.docker.internal
LLM_BASE_URL = "http://host.docker.internal:11434/v1"
LLM_MODEL = "qwen2.5:7b-instruct"

# Базовая очередь и финальный статус тикета (как в ТЗ)
FINAL_QUEUE = "ОЦО.МРФ.Эксплуатация СУЛЗ."
FINAL_STATUS = "В работе"
FINAL_ASSIGNEE = None

# Всегда проверяем логи по этой ошибке ДО обращения к RAG (как просили)
LOG_PRECHECK_PATTERN = "ORDER_STATUS_DENIED"
LOG_WINDOW_DAYS = 30


# ==============================
# In-memory storage (demo)
# ==============================

class Ticket(BaseModel):
    ticket_id: str
    region: Optional[str] = None
    subject: str
    description: str
    annotation: Optional[str] = None
    error_text: Optional[str] = None

    status: str = "new"  # new -> in_progress
    log_error_found: Optional[bool] = None
    log_error_name: Optional[str] = None


class ActionLogEntry(BaseModel):
    step_index: int
    tool: str
    params: Dict[str, Any]
    result: Dict[str, Any]


class TicketIntakeRequest(BaseModel):
    ticket_id: str
    region: Optional[str] = None
    subject: str
    description: str
    annotation: Optional[str] = None
    error_text: Optional[str] = None


class TicketProcessResult(BaseModel):
    ticket: Ticket
    actions: List[ActionLogEntry]
    rag_answer: str
    llm_plan: Dict[str, Any]
    final_comment: str


TICKETS: Dict[str, Ticket] = {}
ACTIONS_LOG: Dict[str, List[ActionLogEntry]] = {}


# ==============================
# HTTP helpers (safe)
# ==============================

async def safe_post_json(url: str, payload: Dict[str, Any], timeout: float = 20.0) -> Dict[str, Any]:
    """
    Никогда не бросает исключение наружу.
    Возвращает либо JSON, либо структуру ошибки (error=True).
    """
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code >= 400:
                return {
                    "error": True,
                    "status_code": resp.status_code,
                    "detail": resp.text,
                    "url": url,
                }
            # try json
            try:
                return resp.json()
            except Exception:
                return {"error": True, "status_code": 500, "detail": "non-json response", "raw": resp.text}
    except Exception as e:
        return {"error": True, "status_code": 0, "detail": str(e), "url": url}


async def mcp_call(tool: str, params: Dict[str, Any]) -> Dict[str, Any]:
    return await safe_post_json(f"{MCP_BASE_URL}/mcp/{tool}", params, timeout=20.0)


async def rag_solve(payload: Dict[str, Any]) -> Dict[str, Any]:
    return await safe_post_json(f"{RAG_BASE_URL}/rag/solve_ticket", payload, timeout=20.0)


# ==============================
# LLM planner (Ollama OpenAI-compatible)
# ==============================

ALLOWED_PLAN_TOOLS = {
    "check_eissd_status",
    "update_order_status",
    "resolve_mrf_queue",
    "check_edit_order_request",
    "add_otrs_comment",
    "update_otrs_ticket",
}

# ВАЖНО: search_logs НЕ входит в план — он выполняется детерминированно первым шагом (как в ТЗ)


def _strip_code_fences(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    return s.strip()


def extract_json_obj(text: str) -> Optional[Dict[str, Any]]:
    """
    Пытаемся достать JSON-объект из ответа LLM.
    """
    text = _strip_code_fences(text)
    # 1) если это уже JSON
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    # 2) ищем первую { ... } и парсим
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    chunk = m.group(0)
    try:
        obj = json.loads(chunk)
        if isinstance(obj, dict):
            return obj
    except Exception:
        return None
    return None


async def llm_plan_actions(ticket: Ticket, rag_answer: str, log_precheck: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Возвращает (plan, raw_llm_response).
    plan:
      {
        "summary": "...",
        "actions": [
           {"tool":"check_eissd_status","params":{"order_id":"..."}},
           ...
        ]
      }
    """
    system = (
        "Ты — мозг ИИ-агента для обработки инцидентов. "
        "У тебя УЖЕ выполнен pre-check логов (search_logs), его повторять НЕ НУЖНО. "
        "Твоя задача: на основе тикета, результата pre-check и текста рекомендации RAG "
        "сформировать исполнимый план действий как JSON.\n\n"
        "ЖЁСТКИЕ ПРАВИЛА:\n"
        "1) Отвечай ТОЛЬКО JSON-объектом, без текста вокруг.\n"
        "2) Каждый шаг: {\"tool\": \"...\", \"params\": {...}}.\n"
        "3) Разрешённые tools: "
        + ", ".join(sorted(ALLOWED_PLAN_TOOLS))
        + ".\n"
        "4) Параметры:\n"
        "   - check_eissd_status: {order_id}\n"
        "   - update_order_status: {order_id, new_status}\n"
        "   - resolve_mrf_queue: {region}\n"
        "   - check_edit_order_request: {order_id}\n"
        "   - add_otrs_comment: {ticket_id, text} (не финальный, если надо промежуточно)\n"
        "   - update_otrs_ticket: {ticket_id, queue, status, assignee}\n"
        "5) Если не уверен — всё равно сделай разумный план минимум из 2-3 шагов.\n"
    )

    user = {
        "ticket": ticket.dict(),
        "log_precheck_result": log_precheck,
        "rag_recommendation_text": rag_answer,
        "note": "Сформируй план так, чтобы его можно было выполнить MCP-инструментами. "
                "Если RAG говорит 'проверить логи' — логи уже проверены, не повторяй.",
    }

    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
        ],
        "temperature": 0.25,
        "max_tokens": 700,
    }

    raw = await safe_post_json(f"{LLM_BASE_URL}/chat/completions", payload, timeout=60.0)
    if raw.get("error"):
        # LLM недоступна — вернём дефолтный план (но это уже "аварийный режим")
        plan = {
            "summary": "LLM недоступна, использован безопасный минимальный план.",
            "actions": [
                {"tool": "check_eissd_status", "params": {"order_id": ticket.ticket_id}},
                {"tool": "update_order_status", "params": {"order_id": ticket.ticket_id, "new_status": "IN_PROGRESS"}},
                {"tool": "update_otrs_ticket", "params": {"ticket_id": ticket.ticket_id, "queue": FINAL_QUEUE, "status": FINAL_STATUS, "assignee": FINAL_ASSIGNEE}},
            ],
        }
        return plan, raw

    content = raw.get("choices", [{}])[0].get("message", {}).get("content", "")
    obj = extract_json_obj(content)
    if not obj:
        plan = {
            "summary": "LLM вернула некорректный JSON, использован безопасный минимальный план.",
            "actions": [
                {"tool": "check_eissd_status", "params": {"order_id": ticket.ticket_id}},
                {"tool": "update_order_status", "params": {"order_id": ticket.ticket_id, "new_status": "IN_PROGRESS"}},
                {"tool": "update_otrs_ticket", "params": {"ticket_id": ticket.ticket_id, "queue": FINAL_QUEUE, "status": FINAL_STATUS, "assignee": FINAL_ASSIGNEE}},
            ],
        }
        return plan, raw

    # мягкая валидация структуры
    actions = obj.get("actions", [])
    if not isinstance(actions, list):
        actions = []

    plan = {
        "summary": str(obj.get("summary", "")).strip() or "План действий сформирован LLM.",
        "actions": actions,
    }
    return plan, raw


def normalize_action(tool: str, params: Dict[str, Any], ticket: Ticket, context: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """
    Приводим params к ожидаемому формату MCP.
    Главное: никогда не отправлять пустой order_id, и не забывать обязательные поля.
    """
    tool = str(tool).strip()

    if tool not in ALLOWED_PLAN_TOOLS:
        return tool, params

    p = dict(params or {})

    # Универсальные подстановки
    if "order_id" in p and (p["order_id"] is None or str(p["order_id"]).strip() == ""):
        p["order_id"] = ticket.ticket_id

    # Конкретные схемы
    if tool == "check_eissd_status":
        p = {"order_id": str(p.get("order_id") or ticket.ticket_id)}

    elif tool == "check_edit_order_request":
        p = {"order_id": str(p.get("order_id") or ticket.ticket_id)}

    elif tool == "resolve_mrf_queue":
        p = {"region": str(p.get("region") or ticket.region or "COMMON")}

    elif tool == "update_order_status":
        order_id = str(p.get("order_id") or ticket.ticket_id)
        new_status = p.get("new_status")
        if new_status is None or str(new_status).strip() == "":
            # Если LLM не дала — берём "разумный" дефолт
            # (можно подтянуть из EISSD, если уже знаем)
            eissd_status = context.get("eissd_status")
            new_status = eissd_status or "IN_PROGRESS"
        p = {"order_id": order_id, "new_status": str(new_status)}

    elif tool == "add_otrs_comment":
        # MCP ожидает ticket_id + text
        ticket_id = str(p.get("ticket_id") or ticket.ticket_id)
        text = p.get("text")
        if text is None:
            # если LLM дала "comment" — переложим
            text = p.get("comment") or ""
        p = {"ticket_id": ticket_id, "text": str(text)}

    elif tool == "update_otrs_ticket":
        p = {
            "ticket_id": str(p.get("ticket_id") or ticket.ticket_id),
            "queue": str(p.get("queue") or FINAL_QUEUE),
            "status": str(p.get("status") or FINAL_STATUS),
            "assignee": p.get("assignee", FINAL_ASSIGNEE),
        }

    return tool, p


def build_final_comment(
    ticket: Ticket,
    actions: List[ActionLogEntry],
    rag_answer: str,
    llm_summary: str,
) -> str:
    lines: List[str] = []

    lines.append(f"Тикет {ticket.ticket_id}. Статус агента: {ticket.status}.")
    lines.append("Проведённые проверки и действия:")

    for a in actions:
        lines.append(f"{a.step_index}. tool={a.tool}, params={a.params}, result={a.result}")

    if ticket.log_error_found is not None:
        if ticket.log_error_found:
            lines.append(f"Проверка логов: ошибка {ticket.log_error_name} обнаружена.")
        else:
            lines.append(f"Проверка логов: ошибка {LOG_PRECHECK_PATTERN} не обнаружена.")

    lines.append(f"Сводка (LLM): {llm_summary}")
    lines.append("Рекомендация RAG:")
    lines.append(rag_answer.strip() if rag_answer else "(пусто)")

    # как в ТЗ — явное указание
    lines.append("Требуется анализ от инженера.")

    return "\n".join(lines)


# ==============================
# Core pipeline (как просили)
# ==============================

async def process_ticket(ticket: Ticket) -> TicketProcessResult:
    actions_log: List[ActionLogEntry] = []
    step_index = 1

    # STEP 2 (по ТЗ) — диагностика логов ДО RAG
    search_payload = {
        "order_id": ticket.ticket_id,
        "pattern": LOG_PRECHECK_PATTERN,
        "window_days": LOG_WINDOW_DAYS,
    }
    search_result = await mcp_call("search_logs", search_payload)

    # Заполняем поля тикета
    if not search_result.get("error"):
        ticket.log_error_found = bool(search_result.get("error_found", False))
        ticket.log_error_name = search_result.get("error_code")
    else:
        ticket.log_error_found = False
        ticket.log_error_name = None

    actions_log.append(ActionLogEntry(
        step_index=step_index,
        tool="search_logs",
        params=search_payload,
        result=search_result,
    ))
    step_index += 1

    # STEP 3 — запрос в RAG (мок по примерам)
    rag_req = {
        "ticket_id": ticket.ticket_id,
        "log_error_found": bool(ticket.log_error_found),
        "log_error_name": ticket.log_error_name,
        "subject": ticket.subject,
        "description": ticket.description,
        "annotation": ticket.annotation,
        "error_text": ticket.error_text,
    }
    rag_resp = await rag_solve(rag_req)

    rag_answer = ""
    if rag_resp.get("error"):
        rag_answer = f"(RAG error) {rag_resp.get('detail', '')}"
    else:
        rag_answer = str(rag_resp.get("answer_text", "")).strip()

    # STEP 4 — LLM строит план действий по RAG + контексту
    llm_plan, llm_raw = await llm_plan_actions(ticket, rag_answer, search_result)

    # STEP 5 — исполнение MCP tools по плану (с нормализацией)
    context: Dict[str, Any] = {}

    planned_actions = llm_plan.get("actions", [])
    if not isinstance(planned_actions, list):
        planned_actions = []

    for act in planned_actions:
        tool = str((act or {}).get("tool", "")).strip()
        params = (act or {}).get("params", {}) or {}

        # запрещаем LLM повторять search_logs
        if tool == "search_logs":
            actions_log.append(ActionLogEntry(
                step_index=step_index,
                tool="search_logs",
                params=params if isinstance(params, dict) else {},
                result={"skipped": True, "reason": "search_logs is pre-check step and already executed"},
            ))
            step_index += 1
            continue

        # базовая защита от мусора
        if tool not in ALLOWED_PLAN_TOOLS:
            actions_log.append(ActionLogEntry(
                step_index=step_index,
                tool=tool,
                params=params if isinstance(params, dict) else {},
                result={"skipped": True, "reason": f"tool not allowed: {tool}"},
            ))
            step_index += 1
            continue

        tool, norm_params = normalize_action(tool, params if isinstance(params, dict) else {}, ticket, context)

        # add_otrs_comment не вызываем в середине (чтобы не спамить), только в конце
        if tool == "add_otrs_comment":
            actions_log.append(ActionLogEntry(
                step_index=step_index,
                tool=tool,
                params=norm_params,
                result={"skipped": True, "reason": "comments are sent once with final_comment"},
            ))
            step_index += 1
            continue

        # update_otrs_ticket логично делать в конце, но если LLM вставила — тоже не страшно
        res = await mcp_call(tool, norm_params)

        # сохраняем важные штуки в контекст
        if tool == "check_eissd_status" and not res.get("error"):
            context["eissd_status"] = res.get("status")

        actions_log.append(ActionLogEntry(
            step_index=step_index,
            tool=tool,
            params=norm_params,
            result=res,
        ))
        step_index += 1

    # STEP 7 — финальный статус тикета (по ТЗ)
    ticket.status = "in_progress"

    # Формируем финальный комментарий (как просили: без “болтовни”, но с логом шагов)
    llm_summary = str(llm_plan.get("summary", "")).strip() or "План действий сформирован."
    # STEP 6
    final_comment = build_final_comment(ticket, actions_log, rag_answer, llm_summary)

    # Добавляем комментарий в OTRS через MCP
    await mcp_call("add_otrs_comment", {"ticket_id": ticket.ticket_id, "text": final_comment})

    # Обновляем “состояние тикета” (эмуляция робота-интегратора с OTRS)
    await mcp_call("update_otrs_ticket", {
        "ticket_id": ticket.ticket_id,
        "queue": FINAL_QUEUE,
        "status": FINAL_STATUS,
        "assignee": FINAL_ASSIGNEE,
    })

    # сохраняем в память демо
    TICKETS[ticket.ticket_id] = ticket
    ACTIONS_LOG[ticket.ticket_id] = actions_log

    return TicketProcessResult(
        ticket=ticket,
        actions=actions_log,
        rag_answer=rag_answer,
        llm_plan=llm_plan,
        final_comment=final_comment,
    )


# ==============================
# API
# ==============================

@app.post("/tickets/intake", response_model=TicketProcessResult)
async def intake_ticket(req: TicketIntakeRequest):
    # Демо-friendly: можно отправлять один и тот же ticket_id много раз — будет перерасчёт
    ticket = Ticket(
        ticket_id=req.ticket_id,
        region=req.region,
        subject=req.subject,
        description=req.description,
        annotation=req.annotation,
        error_text=req.error_text,
        status="new",
    )
    return await process_ticket(ticket)


@app.get("/tickets/{ticket_id}", response_model=Ticket)
async def get_ticket(ticket_id: str):
    return TICKETS.get(ticket_id) or Ticket(
        ticket_id=ticket_id,
        subject="(not found)",
        description="(not found)",
        status="not_found",
    )


@app.get("/tickets/{ticket_id}/actions", response_model=List[ActionLogEntry])
async def get_ticket_actions(ticket_id: str):
    return ACTIONS_LOG.get(ticket_id, [])
