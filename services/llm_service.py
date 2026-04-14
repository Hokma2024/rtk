"""Цикл планирования LLM: управляет итерациями вызова инструментов и fallback-стратегиями."""

from __future__ import annotations

import json
import time
from typing import Any

from clients.mcp_client import MCPClient
from common.config import get_settings
from common.logging import get_logger
from common.models import ActionLogEntry, Ticket
from providers import get_provider

log = get_logger(__name__)


def _safe_json_dumps(obj: Any) -> str:
    """Сериализует *obj* в JSON, при TypeError откатывается к str()."""
    try:
        return json.dumps(obj, ensure_ascii=False)
    except TypeError:
        return json.dumps(str(obj), ensure_ascii=False)


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


def _append_ollama_assistant_tool_calls(
    messages: list[dict[str, Any]],
    tool_calls: list[dict[str, Any]],
) -> None:
    raw = [c.get("raw") for c in tool_calls if c.get("raw")]
    if raw:
        messages.append({"role": "assistant", "content": "", "tool_calls": raw})


def _append_ollama_tool_result(
    messages: list[dict[str, Any]],
    tool_name: str,
    result: Any,
) -> None:
    messages.append({"role": "tool", "tool_name": tool_name, "content": _safe_json_dumps(result)})


def _remaining_seconds(deadline: float, fallback: int = 5) -> int:
    """Возвращает число секунд до *deadline*, с нижней границей *fallback*."""
    left = int(deadline - time.monotonic())
    return max(fallback, left)


def _precheck_error_found(context: dict[str, Any] | None) -> bool:
    """Извлекает флаг ``precheck.logs.error_found`` из контекста пайплайна.

    Возвращает ``False`` при отсутствии данных или любом невалидном значении —
    консервативный default: без подтверждённой ошибки не запускаем write-ветки.
    """
    if not context:
        return False
    precheck = context.get("precheck")
    if not isinstance(precheck, dict):
        return False
    logs = precheck.get("logs")
    if not isinstance(logs, dict):
        return False
    return bool(logs.get("error_found", False))


_RAG_RELEVANCE_HINTS: dict[str, str] = {
    "direct": (
        "RAG нашёл похожий кейс напрямую по текущему order_id. Используй этот "
        "текст как подсказку — он описывает конкретное действие по этой заявке, "
        "но всё равно сверяй решение с реальным состоянием через tools."
    ),
    "batch_historical": (
        "ВНИМАНИЕ: RAG вернул пакет похожих исторических кейсов по ДРУГИМ order_id. "
        "Чужие order_id заменены плейсхолдером <other_order> — НИ В КОЕМ СЛУЧАЕ не "
        "подставляй их в параметры tools. Используй этот блок только как общий "
        "шаблон действий; конкретные значения бери из текущего тикета."
    ),
    "general_guidance": (
        "RAG вернул общие рекомендации по процессу без привязки к конкретному "
        "order_id. Оцени применимость к текущему состоянию, проверь реальные "
        "статусы через tools."
    ),
}


def _build_rag_context_block(context: dict[str, Any] | None) -> str:
    """Собирает блок с текстом реального RAG для инъекции в system prompt.

    Возвращает пустую строку, если:

    - контекста нет;
    - ``rag.answer_text`` пустой/отсутствует (это случай documentation/empty —
      адаптер уже отфильтровал текст, агент работает по precheck + тикету);
    - секция ``rag`` имеет невалидный тип.

    Блок включает:

    - метку ``rag_relevance`` (direct / batch_historical / general_guidance);
    - подсказку, как трактовать этот тип ответа (особенно важно для
      ``batch_historical``, чтобы LLM не утащила чужие order_id в параметры);
    - собственно отфильтрованный ``answer_text`` как справочный материал.
    """
    if not context:
        return ""
    rag = context.get("rag")
    if not isinstance(rag, dict):
        return ""

    answer_text = rag.get("answer_text")
    if not isinstance(answer_text, str) or not answer_text.strip():
        return ""

    params = rag.get("parameters") if isinstance(rag.get("parameters"), dict) else {}
    conditions = rag.get("conditions") if isinstance(rag.get("conditions"), dict) else {}
    relevance = (
        params.get("rag_relevance")
        or conditions.get("rag_relevance")
        or "unknown"
    )
    relevance = str(relevance)

    hint = _RAG_RELEVANCE_HINTS.get(
        relevance,
        "RAG вернул текстовую подсказку — используй как справочный материал.",
    )

    return (
        f"RAG_CONTEXT (relevance={relevance}):\n"
        f"{hint}\n"
        f"---\n"
        f"{answer_text.strip()}\n"
        f"---"
    )


def build_precheck_fallback_plan(
    ticket: Ticket,
    context: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Собирает детерминированный план инструментов на основании precheck.

    Используется в двух местах:

    - ``mode == "fallback"``, когда LLM отключён и в RAG нет готового
      ``required_actions`` (например, реальный RAG через rag_adapter возвращает
      только текст в ``answer_text``).
    - Аварийный откат в tools-режиме, когда LLM не сгенерировала ни одного
      tool-call и не смогла вернуть валидный JSON-план.

    Логика:

    - ``precheck.logs.error_found = True`` — в логах есть подтверждённая ошибка,
      нужно расширенное обследование: статус в ЕИССД + СУЛЗ + наличие
      обрабатываемой заявки на редактирование (write-tool). Дальнейшую
      маршрутизацию в МРФ выполняет детерминированный ``mrf_roundtrip``
      пайплайна — дублировать его здесь не нужно.
    - ``error_found = False`` — только чтение: сверяем статусы, чтобы не
      тревожить боевые write-инструменты без подтверждённого основания.
    """
    order_id = ticket.order_id
    read_plan: list[dict[str, Any]] = [
        {"tool": "check_eissd_status", "arguments": {"order_id": order_id}},
        {"tool": "get_order_status", "arguments": {"order_id": order_id}},
    ]
    if _precheck_error_found(context):
        read_plan.append(
            {"tool": "check_edit_order_request", "arguments": {"order_id": order_id}}
        )
    return read_plan


async def _execute_tools_from_plan(
    mcp_client: MCPClient,
    plan: list[dict[str, Any]],
    *,
    messages: list[dict[str, Any]] | None = None,
) -> list[ActionLogEntry]:
    """Исполняет детерминированный план инструментов и возвращает записи журнала действий."""
    actions: list[ActionLogEntry] = []
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
            if messages is not None:
                _append_ollama_tool_result(messages, name, result)
        except Exception as exc:
            log.warning("tool_exec_failed", tool=name, exc_type=exc.__class__.__name__, detail=str(exc))
            entry.ok = False
            entry.error = str(exc)
            entry.error_type = exc.__class__.__name__
        entry.duration_ms = int((time.perf_counter() - t0) * 1000)
        actions.append(entry)
    return actions


async def run_planning_loop(
    ticket: Ticket,
    mcp_client: MCPClient,
    *,
    context: dict[str, Any] | None = None,
    deadline: float,
) -> list[ActionLogEntry]:
    """Крутит цикл LLM/инструментов до завершения, исчерпания бюджета или лимита итераций.

    Режимы:
      - tools: цикл tool-calling; при отсутствии действий откатывается к JSON-плану
      - json: запрашивает у LLM единственный JSON-план и исполняет его
      - fallback: полностью пропускает LLM и исполняет план из контекста RAG
    """
    settings = get_settings()
    mode = settings.llm_mode

    mcp_tools_resp = await mcp_client.list_tools()
    mcp_tools = mcp_tools_resp.tools if hasattr(mcp_tools_resp, "tools") else mcp_tools_resp
    tools_schema = _filter_tools_schema(MCPClient.to_openai_tools_schema(mcp_tools))

    if mode == "fallback":
        rag = (context or {}).get("rag") or {}
        plan: list[dict[str, Any]] = []
        if isinstance(rag, dict):
            ra = rag.get("required_actions")
            if isinstance(ra, list):
                plan = [x for x in ra if isinstance(x, dict)]
        if not plan:
            plan = build_precheck_fallback_plan(ticket, context)
        return await _execute_tools_from_plan(mcp_client, plan)

    log.info("llm_provider_selected", provider=settings.llm_provider, model=settings.llm_model_name)
    provider = get_provider(settings.llm_provider, api_key=settings.llm_api_key, model=settings.llm_model_name)

    system_prompt = (
        "Ты — AI-агент техподдержки. Твоя зона ответственности: интерпретация "
        "контекста, выбор и вызов инструментов, принятие решений по состоянию "
        "заказа. Финализация тикета выполняется автоматически после твоей фазы — "
        "инструменты финализации (update_otrs_ticket) тебе недоступны.\n\n"
        "КОНТЕКСТ, доступный тебе:\n"
        "- precheck.logs — результаты поиска ошибок в логах заказа\n"
        "- тикет: ticket_id, order_id, subject, annotation, description, region\n"
        "- rag.required_actions — РЕКОМЕНДАЦИИ экспертной системы, основанные "
        "на похожих кейсах. Это СОВЕТЫ, а не обязательный чек-лист. Оцени их "
        "применимость к текущему состоянию. Ты можешь им следовать, адаптировать "
        "параметры или отклониться, если состояние показывает, что они неприменимы. "
        "Если RAG недоступен — действуй по precheck + тикету.\n\n"
        "ИНСТРУМЕНТЫ:\n"
        "- read: search_logs, get_order_status, check_eissd_status, get_otrs_ticket, list_otrs_comments\n"
        "- write: check_edit_order_request, update_order_status, resolve_mrf_queue, "
        "mrf_process_ticket, add_otrs_comment\n"
        "- недоступно: update_otrs_ticket\n\n"
        "ПРАВИЛА:\n"
        "- НЕЛЬЗЯ выдумывать данные — только через tools.\n"
        "- Если нужна очередь МРФ — используй resolve_mrf_queue → mrf_process_ticket → "
        "list_otrs_comments (прочитай свежий комментарий от МРФ, прими решение).\n"
        "- Когда закончил вызывать tools, верни слово DONE."
    )

    rag_block = _build_rag_context_block(context)
    if rag_block:
        system_prompt += "\n\n" + rag_block

    if context:
        system_prompt += "\n\nCONTEXT:\n" + _safe_json_dumps(context)

    messages: list[dict[str, Any]] = [
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

    actions: list[ActionLogEntry] = []

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

    async def call_llm(expect_tools: bool) -> tuple[str, list[dict[str, Any]]]:
        timeout = min(settings.llm_timeout_seconds, _remaining_seconds(deadline))
        return await provider.acall(messages, tools_schema if expect_tools else [], timeout=timeout)

    def _collect_metrics() -> None:
        if context is None:
            return
        error_count = sum(1 for a in actions if not a.ok)
        write_calls_total = sum(1 for a in actions if a.tool in write_tools)
        used_names = {a.tool for a in actions}
        context["llm_metrics"] = {
            "steps_used": steps_used,
            "rag_followed": len(rag_required_names & used_names),
            "rag_deviated": len(rag_required_names - used_names),
            "write_calls_total": write_calls_total,
            "loop_exceeded": loop_exceeded,
            "error_count": error_count,
        }

    # режим json: одноразовый JSON-план
    if mode == "json":
        log.warning("llm_fallback", reason="mode=json")
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
        _collect_metrics()
        return actions

    # режим tools: итеративный цикл tool-calling
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

    # Резервный JSON-план, если цикл tools не произвёл ни одного действия
    if not actions:
        log.warning("llm_fallback", reason="tools_loop_produced_no_actions")
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
        except (json.JSONDecodeError, ValueError) as exc:
            log.error(
                "llm_fallback_error", exc_type=exc.__class__.__name__, detail=str(exc)
            )
        except Exception as exc:
            log.error(
                "llm_fallback_error", exc_type=exc.__class__.__name__, detail=str(exc)
            )

        # Если и LLM-fallback ничего не породил — детерминированный precheck-план.
        # Никогда не оставляем тикет без единого действия: pipeline ожидает
        # хотя бы попытку сверки статусов для формирования финального отчёта.
        if not actions:
            log.warning("llm_fallback", reason="precheck_based_deterministic_plan")
            precheck_plan = build_precheck_fallback_plan(ticket, context)
            actions.extend(await _execute_tools_from_plan(mcp_client, precheck_plan))

    _collect_metrics()
    return actions
