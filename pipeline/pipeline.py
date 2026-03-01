from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

from common.config import get_settings
from common.models import ActionLogEntry, Ticket, normalize_order_status
from common.metrics import tool_calls_total
from clients.mcp_client import MCPClient
from pipeline.rag_models import RagRequest, RagResponse
from services.llm_service import run_planning_loop

logger = logging.getLogger(__name__)

PRECHECK_PATTERN = "ORDER_STATUS_DENIED"
PRECHECK_WINDOW_DAYS = 30


def _now() -> float:
    return time.monotonic()


def _ensure_budget(deadline: float) -> None:
    if _now() > deadline:
        raise TimeoutError("Request time budget exceeded")


def _unwrap_mcp_dict(tool: str, resp: Any) -> Tuple[Any, Optional[str], bool]:
    """
    Возвращает (value, diag_code, is_fatal)

    - Если пришёл dict -> ok
    - Если пришёл list и внутри есть dict -> берём первый dict, diag_code фиксируем
    - Если list без dict или вообще другой тип -> это проблема: diag_code + is_fatal=True
    """
    if isinstance(resp, dict):
        return resp, None, False

    if isinstance(resp, list):
        dict_items = [it for it in resp if isinstance(it, dict)]
        if len(dict_items) == 1:
            return dict_items[0], f"mcp.{tool}.wrap=list_to_dict", False
        if len(dict_items) > 1:
            return dict_items[0], f"mcp.{tool}.wrap=list_multi_dicts", False
        # list, но словарей нет
        return resp, f"mcp.{tool}.bad_type=list_no_dict", True

    # неожиданный тип
    return resp, f"mcp.{tool}.bad_type={type(resp).__name__}", True


def _as_error_dict(tool: str, resp: Any, diag_code: str) -> Dict[str, Any]:
    # Важно: финал детерминированный
    return {
        "error": "UNEXPECTED_MCP_RESPONSE",
        "tool": tool,
        "diag": diag_code,
        "raw_type": type(resp).__name__,
        "raw_preview": str(resp)[:500],
    }


async def precheck_logs(ticket: Ticket, mcp: MCPClient, *, deadline: float) -> Dict[str, Any]:
    """
    Шаг 2 (жёстко): всегда ищем ORDER_STATUS_DENIED за 30 дней.
    MCP search_logs должен вернуть dict:
      - logs_full: все строки окна (без лимита)
      - matched_samples: лимитированные матчи (для LLM/контекста)
    """
    _ensure_budget(deadline)

    diag: List[str] = []
    try:
        raw = await mcp.call_tool(
            "search_logs",
            {"order_id": ticket.order_id, "pattern": PRECHECK_PATTERN, "window_days": PRECHECK_WINDOW_DAYS},
        )
        tool_calls_total.labels(tool="search_logs", ok="true").inc()

        resp, code, fatal = _unwrap_mcp_dict("search_logs", raw)
        if code:
            diag.append(code)
            # fatal = тип неожиданный
            if fatal:
                logger.error("MCP tool search_logs returned unexpected type: %s", code)
                resp = _as_error_dict("search_logs", raw, code)
            else:
                logger.warning("MCP tool search_logs response wrapped/unexpected shape: %s", code)

        if isinstance(resp, dict):
            if "error_found" not in resp or "logs_full" not in resp:
                diag.append("mcp.search_logs.schema_missing_fields")
                logger.warning("MCP tool search_logs dict missing expected fields (error_found/logs_full)")

        return {
            "precheck": {
                "pattern": PRECHECK_PATTERN,
                "window_days": PRECHECK_WINDOW_DAYS,
                "logs": resp,
                "_diag": diag,
            }
        }

    except Exception as exc:
        tool_calls_total.labels(tool="search_logs", ok="false").inc()
        logger.exception("precheck_logs failed: %s", exc)
        return {
            "precheck": {
                "pattern": PRECHECK_PATTERN,
                "window_days": PRECHECK_WINDOW_DAYS,
                "logs": {"error": str(exc), "error_type": exc.__class__.__name__},
                "_diag": ["mcp.search_logs.exception"],
            }
        }


async def call_rag(ticket: Ticket, context: Dict[str, Any], *, deadline: float) -> Dict[str, Any]:
    """
    Шаг 3: запрос в RAG по требованиям:
      precheck(ошибка обнаружена/нет + имя ошибки) + annotation + description + subject
    Шаг 3-4: фиксируем schema ответа (RagResponse) и валидируем.
    """
    _ensure_budget(deadline)
    settings = get_settings()
    if not settings.rag_base_url:
        return {"rag": None}

    url = settings.rag_base_url.rstrip("/") + "/query"
    precheck = (context or {}).get("precheck") or {}
    payload = RagRequest(
        ticket_id=ticket.id,
        order_id=ticket.order_id,
        subject=ticket.subject,
        annotation=ticket.annotation,
        description=ticket.description,
        precheck=precheck,
    ).model_dump()

    timeout = min(settings.llm_timeout_seconds, max(5, int(deadline - _now())))
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            rag = RagResponse.model_validate(data)
            return {"rag": rag.model_dump()}
        except Exception as exc:
            logger.exception("call_rag failed: %s", exc)
            return {"rag": None, "rag_error": str(exc)}


async def plan_and_execute(
    ticket: Ticket, context: Dict[str, Any], mcp: MCPClient, *, deadline: float
) -> List[ActionLogEntry]:
    """
    Шаг 4-5: LLM/tool-loop выбирает tools, используя RAG JSON как контекст.
    Важно: final_comment НЕ генерируется LLM.
    """
    _ensure_budget(deadline)
    return await run_planning_loop(ticket, mcp, context=context, deadline=deadline)


async def verify_final_status(
    ticket: Ticket, mcp: MCPClient, *, deadline: float, attempts: int = 3, base_sleep: float = 0.6
) -> Tuple[Dict[str, Any], List[ActionLogEntry]]:
    """
    Политика цикла проверки финального статуса:
    2-3 попытки с backoff в агенте, НЕ в LLM.

    + Диагностика типов MCP-ответов: если вместо dict прилетел list и т.п. — логируем и пишем _diag.
    """
    results: Dict[str, Any] = {}
    logs: List[ActionLogEntry] = []
    diag: List[str] = []

    for i in range(attempts):
        _ensure_budget(deadline)

        r1: Any = None
        r2: Any = None

        # 1) get_order_status (БД СУЛЗ mock)
        entry1 = ActionLogEntry(tool="get_order_status", params={"order_id": ticket.order_id})
        t0 = _now()
        try:
            raw1 = await mcp.call_tool("get_order_status", {"order_id": ticket.order_id})
            resp1, code1, fatal1 = _unwrap_mcp_dict("get_order_status", raw1)
            if code1:
                diag.append(code1)
                if fatal1:
                    logger.error("MCP tool get_order_status returned unexpected type: %s", code1)
                    resp1 = _as_error_dict("get_order_status", raw1, code1)
                else:
                    logger.warning("MCP tool get_order_status response wrapped/unexpected shape: %s", code1)

            r1 = resp1
            entry1.ok = True
            entry1.result = resp1
            tool_calls_total.labels(tool="get_order_status", ok="true").inc()
        except Exception as exc:
            entry1.ok = False
            entry1.error = str(exc)
            entry1.error_type = exc.__class__.__name__
            tool_calls_total.labels(tool="get_order_status", ok="false").inc()
        entry1.duration_ms = int((_now() - t0) * 1000)
        logs.append(entry1)

        # 2) check_eissd_status
        entry2 = ActionLogEntry(tool="check_eissd_status", params={"order_id": ticket.order_id})
        t0 = _now()
        try:
            raw2 = await mcp.call_tool("check_eissd_status", {"order_id": ticket.order_id})
            resp2, code2, fatal2 = _unwrap_mcp_dict("check_eissd_status", raw2)
            if code2:
                diag.append(code2)
                if fatal2:
                    logger.error("MCP tool check_eissd_status returned unexpected type: %s", code2)
                    resp2 = _as_error_dict("check_eissd_status", raw2, code2)
                else:
                    logger.warning("MCP tool check_eissd_status response wrapped/unexpected shape: %s", code2)

            r2 = resp2
            entry2.ok = True
            entry2.result = resp2
            tool_calls_total.labels(tool="check_eissd_status", ok="true").inc()
        except Exception as exc:
            entry2.ok = False
            entry2.error = str(exc)
            entry2.error_type = exc.__class__.__name__
            tool_calls_total.labels(tool="check_eissd_status", ok="false").inc()
        entry2.duration_ms = int((_now() - t0) * 1000)
        logs.append(entry2)

        results = {
            "sulz_db": r1 if entry1.ok else None,
            "eissd": r2 if entry2.ok else None,
            "_diag": diag,
        }

        try:
            if entry1.ok and isinstance(r1, dict) and "status" in r1:
                normalize_order_status(str(r1["status"]))
            if entry2.ok and isinstance(r2, dict) and "status" in r2:
                normalize_order_status(str(r2["status"]))
            break
        except Exception:
            pass

        sleep_s = base_sleep * (2 ** i)
        if _now() + sleep_s > deadline:
            break
        await asyncio.sleep(sleep_s)

    return results, logs


def build_final_comment(
    ticket: Ticket,
    *,
    precheck: Dict[str, Any],
    rag: Optional[Dict[str, Any]],
    actions: List[ActionLogEntry],
    verify: Dict[str, Any],
) -> str:
    """
    Шаг 6: детерминированный финальный комментарий (без генерации).
    Формат: строгий шаблон key=value.

    + Диагностика: если MCP где-то вернул неожиданный тип (list вместо dict),
      это будет отражено в diag.* полях, а также уйдёт в логи через logger.
    """
    pre_logs_raw = (precheck or {}).get("logs") or {}
    pre_diag = (precheck or {}).get("_diag") or []
    if not isinstance(pre_diag, list):
        pre_diag = ["precheck.diag_bad_type"]

    # Если внезапно logs пришёл list
    pre_logs, code, fatal = _unwrap_mcp_dict("search_logs", pre_logs_raw)
    diag: List[str] = list(pre_diag)
    if code and code not in diag:
        diag.append(code)

    if fatal:
        # тип ответа был плохой
        pre_logs = _as_error_dict("search_logs", pre_logs_raw, code or "mcp.search_logs.bad_type")

    error_found = bool(pre_logs.get("error_found")) if isinstance(pre_logs, dict) else False
    error_code = pre_logs.get("error_code") if isinstance(pre_logs, dict) else None

    logs_full_cnt = None
    matched_cnt = None
    if isinstance(pre_logs, dict):
        lf = pre_logs.get("logs_full")
        ms = pre_logs.get("matched_samples") or pre_logs.get("samples")
        if isinstance(lf, list):
            logs_full_cnt = len(lf)
        if isinstance(ms, list):
            matched_cnt = len(ms)

    rag_required_cnt = 0
    if isinstance(rag, dict):
        ra = rag.get("required_actions")
        if isinstance(ra, list):
            rag_required_cnt = len(ra)

    ok_all = all(a.ok for a in actions)

    # агрегаты verify
    verify_diag = []
    if isinstance(verify, dict) and isinstance(verify.get("_diag"), list):
        verify_diag = verify["_diag"]

    for d in verify_diag:
        if d not in diag:
            diag.append(d)

    sulz_status = ""
    eissd_status = ""
    if isinstance(verify, dict):
        sulz = verify.get("sulz_db")
        eissd = verify.get("eissd")
        if isinstance(sulz, dict):
            sulz_status = str(sulz.get("status") or "")
        if isinstance(eissd, dict):
            eissd_status = str(eissd.get("status") or "")

    # next step строго по правилам
    if not error_found:
        next_step = "NO_ERROR_IN_LOGS"
    elif not ok_all:
        next_step = "ESCALATE_L2"
    else:
        next_step = "IN_WORK_WAIT_CONFIRMATION"

    lines: List[str] = []
    lines.append("RTK_AGENT_FINAL v1")
    lines.append(f"ticket_id={ticket.id}")
    lines.append(f"order_id={ticket.order_id}")
    lines.append(f"subject={ticket.subject}")
    lines.append(f"region={ticket.region}")
    lines.append(f"queue={(ticket.queue or '')}")

    lines.append(f"precheck.pattern={PRECHECK_PATTERN}")
    lines.append(f"precheck.window_days={PRECHECK_WINDOW_DAYS}")
    lines.append(f"precheck.error_found={'true' if error_found else 'false'}")
    lines.append(f"precheck.error_code={error_code or ''}")
    lines.append(f"precheck.logs_full_count={'' if logs_full_cnt is None else logs_full_cnt}")
    lines.append(f"precheck.matched_samples_count={'' if matched_cnt is None else matched_cnt}")

    lines.append(f"rag.required_actions_count={rag_required_cnt}")

    lines.append(f"actions.count={len(actions)}")
    lines.append(f"actions.ok={'true' if ok_all else 'false'}")

    lines.append(f"verify.sulz_db.status={sulz_status}")
    lines.append(f"verify.eissd.status={eissd_status}")

    # 5, чтобы комментарий не раздувался.
    lines.append(f"diag.count={len(diag)}")
    for idx, code in enumerate(diag[:5]):
        lines.append(f"diag.{idx}={code}")

    lines.append(f"next_step={next_step}")

    return "\n".join(lines) + "\n"


async def finalize(
    ticket: Ticket, final_comment: str, mcp: MCPClient, *, deadline: float
) -> List[ActionLogEntry]:
    """
    Шаг 7: финальное состояние тикета:
      - по умолчанию НЕ меняем очередь
      - статус: OPEN (в работе)
      - assignee=None всегда
      - менять очередь можно только при ALLOW_QUEUE_CHANGE=true

    Возвращает ActionLogEntry[] ТОЛЬКО для дебага (API наружу их показывает лишь при DEBUG=1).
    """
    _ensure_budget(deadline)
    settings = get_settings()

    logs: List[ActionLogEntry] = []

    # 1) add comment
    entry = ActionLogEntry(tool="add_otrs_comment", params={"ticket_id": ticket.id, "text_len": len(final_comment)})
    t0 = _now()
    try:
        r = await mcp.call_tool("add_otrs_comment", {"ticket_id": ticket.id, "text": final_comment})
        entry.ok = True
        entry.result = r
        tool_calls_total.labels(tool="add_otrs_comment", ok="true").inc()
    except Exception as exc:
        entry.ok = False
        entry.error = str(exc)
        entry.error_type = exc.__class__.__name__
        tool_calls_total.labels(tool="add_otrs_comment", ok="false").inc()
        logger.exception("add_otrs_comment failed: %s", exc)
    entry.duration_ms = int((_now() - t0) * 1000)
    logs.append(entry)

    # 2) decide queue
    desired_queue = ticket.queue
    if not desired_queue:
        desired_queue = f"ОЦО.МРФ.Эксплуатация СУЛЗ.{ticket.region}" if ticket.region else "ОЦО.МРФ.Эксплуатация СУЛЗ"

    if settings.allow_queue_change:
        entry2 = ActionLogEntry(tool="resolve_mrf_queue", params={"region": ticket.region})
        t0 = _now()
        try:
            queue_resp = await mcp.call_tool("resolve_mrf_queue", {"region": ticket.region})
            # ВАЖНО: тоже может прилететь list
            q, code, fatal = _unwrap_mcp_dict("resolve_mrf_queue", queue_resp)
            if code:
                if fatal:
                    logger.error("MCP tool resolve_mrf_queue returned unexpected type: %s", code)
                else:
                    logger.warning("MCP tool resolve_mrf_queue response wrapped/unexpected shape: %s", code)

            entry2.ok = True
            entry2.result = q
            tool_calls_total.labels(tool="resolve_mrf_queue", ok="true").inc()

            if isinstance(q, dict) and q.get("queue"):
                desired_queue = str(q["queue"])
        except Exception as exc:
            entry2.ok = False
            entry2.error = str(exc)
            entry2.error_type = exc.__class__.__name__
            tool_calls_total.labels(tool="resolve_mrf_queue", ok="false").inc()
            logger.exception("resolve_mrf_queue failed: %s", exc)
        entry2.duration_ms = int((_now() - t0) * 1000)
        logs.append(entry2)

    # 3) update ticket status (в работе)
    entry3 = ActionLogEntry(
        tool="update_otrs_ticket",
        params={"ticket_id": ticket.id, "queue": desired_queue, "status": "OPEN", "assignee": None},
    )
    t0 = _now()
    try:
        r = await mcp.call_tool(
            "update_otrs_ticket",
            {"ticket_id": ticket.id, "queue": desired_queue, "status": "OPEN", "assignee": None},
        )
        entry3.ok = True
        entry3.result = r
        tool_calls_total.labels(tool="update_otrs_ticket", ok="true").inc()
    except Exception as exc:
        entry3.ok = False
        entry3.error = str(exc)
        entry3.error_type = exc.__class__.__name__
        tool_calls_total.labels(tool="update_otrs_ticket", ok="false").inc()
        logger.exception("update_otrs_ticket failed: %s", exc)
    entry3.duration_ms = int((_now() - t0) * 1000)
    logs.append(entry3)

    return logs