from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

from common.config import get_settings
from common.metrics import llm_fallback_total, tool_calls_total
from common.models import ActionLogEntry, Ticket
from clients.mcp_client import MCPClient
from providers import get_provider

logger = logging.getLogger(__name__)


def _safe_json_dumps(obj: Any) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False)
    except Exception:
        return json.dumps(str(obj), ensure_ascii=False)


def _filter_tools_schema(tools_schema: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Жёсткое правило: не даём LLM инструмент update_otrs_ticket (только finalize)."""
    out: List[Dict[str, Any]] = []
    for t in tools_schema or []:
        name = None
        try:
            name = t.get("function", {}).get("name")
        except Exception:
            pass
        if name == "update_otrs_ticket":
            continue
        out.append(t)
    return out


def _append_ollama_assistant_tool_calls(messages: List[Dict[str, Any]], tool_calls: List[Dict[str, Any]]) -> None:
    raw = [c.get("raw") for c in tool_calls if c.get("raw")]
    if raw:
        messages.append({"role": "assistant", "content": "", "tool_calls": raw})


def _append_ollama_tool_result(messages: List[Dict[str, Any]], tool_name: str, result: Any) -> None:
    messages.append({"role": "tool", "tool_name": tool_name, "content": _safe_json_dumps(result)})


def _remaining_seconds(deadline: float, fallback: int = 5) -> int:
    left = int(deadline - time.monotonic())
    return max(fallback, left)


async def _execute_tools_from_plan(
    mcp_client: MCPClient,
    plan: List[Dict[str, Any]],
    *,
    messages: Optional[List[Dict[str, Any]]] = None,
) -> List[ActionLogEntry]:
    actions: List[ActionLogEntry] = []
    for item in plan:
        name = str(item.get("tool") or item.get("name") or "")
        params = item.get("arguments") or item.get("params") or {}
        if name == "update_otrs_ticket":
            continue

        entry = ActionLogEntry(tool=name, params=dict(params))
        t0 = time.perf_counter()
        try:
            result = await mcp_client.call_tool(name, params)
            entry.ok = True
            entry.result = result
            tool_calls_total.labels(tool=name, ok="true").inc()
            if messages is not None:
                _append_ollama_tool_result(messages, name, result)
        except Exception as exc:
            entry.ok = False
            entry.error = str(exc)
            entry.error_type = exc.__class__.__name__
            tool_calls_total.labels(tool=name, ok="false").inc()
        entry.duration_ms = int((time.perf_counter() - t0) * 1000)
        actions.append(entry)
    return actions


async def run_planning_loop(
    ticket: Ticket,
    mcp_client: MCPClient,
    *,
    context: Optional[Dict[str, Any]] = None,
    deadline: float,
) -> List[ActionLogEntry]:
    """
    LLM/tool-loop:
      - LLM выбирает tools, используя CONTEXT (включая RAG JSON)
      - LLM НЕ пишет финальный текст
      - остановка: нет tool_calls ИЛИ лимит итераций/бюджета

    Режимы:
      - tools: tool-calling loop, затем stop (если надо, fallback JSON-plan)
      - json: просим один JSON-plan, исполняем
      - fallback: вообще не зовём LLM, исполняем детерминированный план из RAG (если есть)
    """
    settings = get_settings()
    mode = settings.llm_mode

    # Tools schema из MCP
    mcp_tools_resp = await mcp_client.list_tools()
    mcp_tools = mcp_tools_resp.tools if hasattr(mcp_tools_resp, "tools") else mcp_tools_resp
    tools_schema = MCPClient.to_openai_tools_schema(mcp_tools)
    tools_schema = _filter_tools_schema(tools_schema)

    # fallback mode
    if mode == "fallback":
        llm_fallback_total.labels(mode="fallback").inc()
        rag = (context or {}).get("rag") or {}
        plan = []
        if isinstance(rag, dict):
            ra = rag.get("required_actions")
            if isinstance(ra, list):
                plan = [x for x in ra if isinstance(x, dict)]
        if not plan:
            plan = [
                {"tool": "check_eissd_status", "arguments": {"order_id": ticket.order_id}},
                {"tool": "get_order_status", "arguments": {"order_id": ticket.order_id}},
                {"tool": "check_edit_order_request", "arguments": {"order_id": ticket.order_id}},
            ]
        return await _execute_tools_from_plan(mcp_client, plan)

    provider = get_provider(settings.llm_provider, api_key=settings.llm_api_key, model=settings.llm_model_name)

    system_prompt = (
    "Ты агент поддержки. Твоя задача: вызвать нужные tools и собрать факты.\n"
    "НЕЛЬЗЯ: выдумывать данные.\n"
    "НЕЛЬЗЯ: update_otrs_ticket.\n"
    "Когда закончил вызывать tools, верни слово DONE."
)

    if context:
        system_prompt += "\n\nCONTEXT:\n" + _safe_json_dumps(context)

    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": (
                f"Ticket ID: {ticket.id}\n"
                f"Order ID: {ticket.order_id}\n"
                f"Subject: {ticket.subject}\n"
                f"Annotation: {ticket.annotation}\n"
                f"Description: {ticket.description}"
            ),
        },
    ]

    actions: List[ActionLogEntry] = []

    async def call_llm(expect_tools: bool) -> tuple[str, List[Dict[str, Any]]]:
        timeout = min(settings.llm_timeout_seconds, _remaining_seconds(deadline))
        return await provider.acall(messages, tools_schema if expect_tools else [], timeout=timeout)

    # json mode
    if mode == "json":
        llm_fallback_total.labels(mode="json").inc()
        messages.append(
            {
                "role": "user",
                "content": (
                    "Верни ТОЛЬКО JSON-массив действий:\n"
                    '[{"tool":"<name>","arguments":{...}}, ...]\n'
                    "Используй только доступные tools. update_otrs_ticket запрещён."
                ),
            }
        )
        plan_text, _ = await call_llm(expect_tools=False)
        plan = json.loads(plan_text)
        if not isinstance(plan, list):
            raise ValueError("LLM json mode: response is not a JSON array")
        actions.extend(await _execute_tools_from_plan(mcp_client, plan, messages=messages))
        return actions

    # tools mode
    for _ in range(settings.llm_max_iterations):
        if time.monotonic() > deadline:
            break

        try:
            text, tool_calls = await call_llm(expect_tools=True)
        except Exception as exc:
            logger.exception("LLM call failed: %s", exc)
            break

        if tool_calls:
            _append_ollama_assistant_tool_calls(messages, tool_calls)
            for call in tool_calls:
                if time.monotonic() > deadline:
                    break
                name = str(call.get("name") or "")
                params = call.get("arguments", {}) or {}
                if name == "update_otrs_ticket":
                    continue

                entry = ActionLogEntry(tool=name, params=dict(params))
                t0 = time.perf_counter()
                try:
                    result = await mcp_client.call_tool(name, params)
                    entry.ok = True
                    entry.result = result
                    tool_calls_total.labels(tool=name, ok="true").inc()
                    _append_ollama_tool_result(messages, name, result)
                except Exception as exc:
                    entry.ok = False
                    entry.error = str(exc)
                    entry.error_type = exc.__class__.__name__
                    tool_calls_total.labels(tool=name, ok="false").inc()
                entry.duration_ms = int((time.perf_counter() - t0) * 1000)
                actions.append(entry)
            continue

        if (text or "").strip():
            messages.append({"role": "assistant", "content": text})
        break

    # fallback JSON-plan
    if not actions:
        llm_fallback_total.labels(mode="tools_fallback").inc()
        messages.append(
            {
                "role": "user",
                "content": (
                    "Tools mode не дал вызовов tools. Верни ТОЛЬКО JSON-массив действий:\n"
                    '[{"tool":"<name>","arguments":{...}}, ...]\n'
                    "Используй только доступные tools. update_otrs_ticket запрещён."
                ),
            }
        )
        try:
            plan_text, _ = await call_llm(expect_tools=False)
            plan = json.loads(plan_text)
            if not isinstance(plan, list):
                raise ValueError("Fallback plan is not a JSON array")
            actions.extend(await _execute_tools_from_plan(mcp_client, plan, messages=messages))
        except Exception as exc:
            logger.error("Fallback JSON plan failed: %s", exc)

    return actions
