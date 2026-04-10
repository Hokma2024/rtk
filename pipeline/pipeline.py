from __future__ import annotations

import asyncio
import time
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

import httpx

from clients.mcp_client import MCPClient
from common.config import get_settings
from common.logging import get_logger
from common.metrics import pipeline_steps_total
from common.models import ActionLogEntry, Ticket, normalize_order_status
from pipeline.rag_models import RagRequest, RagResponse
from services.llm_service import run_planning_loop

log = get_logger(__name__)


@contextmanager
def _step(name: str) -> Generator[None, None, None]:
    try:
        yield
        pipeline_steps_total.labels(step=name, status="ok").inc()
        log.info("pipeline_step", step=name, status="ok")
    except Exception:
        pipeline_steps_total.labels(step=name, status="error").inc()
        log.exception("pipeline_step_failed", step=name)
        raise


PRECHECK_PATTERN = "ORDER_STATUS_DENIED"
PRECHECK_WINDOW_DAYS = 30


def _now() -> float:
    return time.monotonic()


def _ensure_budget(deadline: float) -> None:
    if _now() > deadline:
        raise TimeoutError("Request time budget exceeded")


def _unwrap_mcp_dict(tool: str, resp: Any) -> tuple[Any, str | None, bool]:
    """Нормализует форму ответа MCP и возвращает (значение, код_диагностики, фатально_ли)."""
    if isinstance(resp, dict):
        return resp, None, False

    if isinstance(resp, list):
        dict_items = [it for it in resp if isinstance(it, dict)]
        if len(dict_items) == 1:
            return dict_items[0], f"mcp.{tool}.wrap=list_to_dict", False
        if len(dict_items) > 1:
            return dict_items[0], f"mcp.{tool}.wrap=list_multi_dicts", False
        return resp, f"mcp.{tool}.bad_type=list_no_dict", True

    return resp, f"mcp.{tool}.bad_type={type(resp).__name__}", True


def _as_error_dict(tool: str, resp: Any, diag_code: str) -> dict[str, Any]:
    """Возвращает детерминированный словарь-ошибку для неожиданного ответа MCP."""
    return {
        "error": "UNEXPECTED_MCP_RESPONSE",
        "tool": tool,
        "diag": diag_code,
        "raw_type": type(resp).__name__,
        "raw_preview": str(resp)[:500],
    }


async def precheck_logs(ticket: Ticket, mcp: MCPClient, *, deadline: float) -> dict[str, Any]:
    """Поиск логов ORDER_STATUS_DENIED за последние 30 дней (обязательный шаг 2)."""
    _ensure_budget(deadline)

    diag: list[str] = []
    try:
        raw = await mcp.call_tool(
            "search_logs",
            {"order_id": ticket.order_id, "pattern": PRECHECK_PATTERN, "window_days": PRECHECK_WINDOW_DAYS},
        )

        resp, code, fatal = _unwrap_mcp_dict("search_logs", raw)
        if code:
            diag.append(code)
            if fatal:
                log.error("mcp_unexpected_type", tool="search_logs", code=code)
                resp = _as_error_dict("search_logs", raw, code)
            else:
                log.warning("mcp_wrapped_response", tool="search_logs", code=code)

        if isinstance(resp, dict) and ("error_found" not in resp or "logs_full" not in resp):
            diag.append("mcp.search_logs.schema_missing_fields")
            log.warning("mcp_missing_fields", tool="search_logs", expected="error_found,logs_full")

        pipeline_steps_total.labels(step="precheck_logs", status="ok").inc()
        log.info("pipeline_step", step="precheck_logs", status="ok")
        return {
            "precheck": {
                "pattern": PRECHECK_PATTERN,
                "window_days": PRECHECK_WINDOW_DAYS,
                "logs": resp,
                "_diag": diag,
            }
        }

    except Exception as exc:
        pipeline_steps_total.labels(step="precheck_logs", status="error").inc()
        log.exception("pipeline_step_failed", step="precheck_logs", error=str(exc))
        return {
            "precheck": {
                "pattern": PRECHECK_PATTERN,
                "window_days": PRECHECK_WINDOW_DAYS,
                "logs": {"error": str(exc), "error_type": exc.__class__.__name__},
                "_diag": ["mcp.search_logs.exception"],
            }
        }


async def call_rag(ticket: Ticket, context: dict[str, Any], *, deadline: float) -> dict[str, Any]:
    """Отправляет контекст precheck+тикета в RAG и возвращает валидированный RagResponse (шаг 3)."""
    _ensure_budget(deadline)
    settings = get_settings()
    if not settings.rag_base_url:
        pipeline_steps_total.labels(step="retrieve", status="ok").inc()
        log.info("pipeline_step", step="retrieve", status="ok")
        return {"rag": None}

    url = settings.rag_base_url.rstrip("/") + "/query"
    precheck = (context or {}).get("precheck") or {}
    payload = RagRequest(
        ticket_id=ticket.id,
        order_id=ticket.order_id,
        subject=ticket.subject,
        annotation=ticket.annotation,
        description=ticket.description,
        region=ticket.region or "COMMON",
        precheck=precheck,
    ).model_dump()

    timeout = min(settings.llm_timeout_seconds, max(5, int(deadline - _now())))
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            rag = RagResponse.model_validate(data)
            pipeline_steps_total.labels(step="retrieve", status="ok").inc()
            log.info("pipeline_step", step="retrieve", status="ok")
            return {"rag": rag.model_dump()}
        except Exception as exc:
            pipeline_steps_total.labels(step="retrieve", status="error").inc()
            log.exception("pipeline_step_failed", step="retrieve", error=str(exc))
            return {"rag": None, "rag_error": str(exc)}


async def plan_and_execute(
    ticket: Ticket, context: dict[str, Any], mcp: MCPClient, *, deadline: float
) -> list[ActionLogEntry]:
    """Запускает цикл LLM/tool-loop для выбора и исполнения инструментов (шаги 4-5)."""
    with _step("plan"):
        _ensure_budget(deadline)
        return await run_planning_loop(ticket, mcp, context=context, deadline=deadline)


async def mrf_roundtrip(
    ticket: Ticket, mcp: MCPClient, *, deadline: float
) -> tuple[dict[str, Any], list[ActionLogEntry]]:
    """Детерминированный цикл взаимодействия с МРФ (шаги 5.1–5.3 спецификации).

    1. resolve_mrf_queue(region) — получает имя очереди МРФ/ИС по региону.
    2. mrf_process_ticket(ticket_id, order_id, region) — эмулирует назначение
       тикета в очередь МРФ, обработку и возврат с вердиктом.
    3. list_otrs_comments(ticket_id) — собирает комментарии тикета (в т.ч.
       добавленные МРФ при обработке) для включения в финальный журнал.

    Повторный запрос в RAG по результату МРФ (шаг 5.4 спеки) намеренно не
    выполняется: спецификация явно помечает его как избыточный.
    """
    _ensure_budget(deadline)

    mrf_ctx: dict[str, Any] = {
        "queue": None,
        "verdict": None,
        "comments_count": None,
        "mrf_comment": None,
    }
    logs: list[ActionLogEntry] = []
    diag: list[str] = []

    # 5.1 resolve_mrf_queue
    entry1 = ActionLogEntry(tool="resolve_mrf_queue", params={"region": ticket.region})
    t0 = _now()
    try:
        raw = await mcp.call_tool("resolve_mrf_queue", {"region": ticket.region})
        resp, code, fatal = _unwrap_mcp_dict("resolve_mrf_queue", raw)
        if code:
            diag.append(code)
            if fatal:
                log.error("mcp_unexpected_type", tool="resolve_mrf_queue", code=code)
                resp = _as_error_dict("resolve_mrf_queue", raw, code)
        entry1.ok = not (isinstance(resp, dict) and resp.get("error"))
        entry1.result = resp
        if isinstance(resp, dict) and resp.get("queue"):
            mrf_ctx["queue"] = str(resp["queue"])
    except Exception as exc:
        entry1.ok = False
        entry1.error = str(exc)
        entry1.error_type = exc.__class__.__name__
        log.exception("mcp_tool_failed", tool="resolve_mrf_queue", error=str(exc))
    entry1.duration_ms = int((_now() - t0) * 1000)
    logs.append(entry1)

    _ensure_budget(deadline)

    # 5.2 mrf_process_ticket (эмуляция назначения в очередь МРФ и возврата)
    entry2 = ActionLogEntry(
        tool="mrf_process_ticket",
        params={"ticket_id": ticket.id, "order_id": ticket.order_id, "region": ticket.region},
    )
    t0 = _now()
    try:
        raw = await mcp.call_tool(
            "mrf_process_ticket",
            {"ticket_id": ticket.id, "order_id": ticket.order_id, "region": ticket.region},
        )
        resp, code, fatal = _unwrap_mcp_dict("mrf_process_ticket", raw)
        if code:
            diag.append(code)
            if fatal:
                log.error("mcp_unexpected_type", tool="mrf_process_ticket", code=code)
                resp = _as_error_dict("mrf_process_ticket", raw, code)
        entry2.ok = not (isinstance(resp, dict) and resp.get("error"))
        entry2.result = resp
        if isinstance(resp, dict):
            mrf_ctx["verdict"] = resp.get("mrf_verdict")
            if resp.get("queue") and not mrf_ctx["queue"]:
                mrf_ctx["queue"] = str(resp["queue"])
    except Exception as exc:
        entry2.ok = False
        entry2.error = str(exc)
        entry2.error_type = exc.__class__.__name__
        log.exception("mcp_tool_failed", tool="mrf_process_ticket", error=str(exc))
    entry2.duration_ms = int((_now() - t0) * 1000)
    logs.append(entry2)

    _ensure_budget(deadline)

    # 5.3 list_otrs_comments — анализ комментариев после возврата от МРФ
    entry3 = ActionLogEntry(tool="list_otrs_comments", params={"ticket_id": ticket.id})
    t0 = _now()
    try:
        raw = await mcp.call_tool("list_otrs_comments", {"ticket_id": ticket.id})
        resp, code, fatal = _unwrap_mcp_dict("list_otrs_comments", raw)
        if code:
            diag.append(code)
            if fatal:
                log.error("mcp_unexpected_type", tool="list_otrs_comments", code=code)
                resp = _as_error_dict("list_otrs_comments", raw, code)
        entry3.ok = not (isinstance(resp, dict) and resp.get("error"))
        entry3.result = resp
        if isinstance(resp, dict):
            comments = resp.get("comments")
            if isinstance(comments, list):
                mrf_ctx["comments_count"] = len(comments)
                for c in reversed(comments):
                    if isinstance(c, dict) and c.get("source") == "mrf_mock":
                        mrf_ctx["mrf_comment"] = str(c.get("text") or "")
                        break
    except Exception as exc:
        entry3.ok = False
        entry3.error = str(exc)
        entry3.error_type = exc.__class__.__name__
        log.exception("mcp_tool_failed", tool="list_otrs_comments", error=str(exc))
    entry3.duration_ms = int((_now() - t0) * 1000)
    logs.append(entry3)

    mrf_ctx["_diag"] = diag
    pipeline_steps_total.labels(step="mrf_roundtrip", status="ok").inc()
    log.info("pipeline_step", step="mrf_roundtrip", status="ok")
    return mrf_ctx, logs


def _evaluate_llm_outcome(
    actions: list[ActionLogEntry],
    context: dict[str, Any],
) -> tuple[bool, list[str]]:
    """Возвращает (should_escalate, reasons) по метрикам LLM-фазы.

    Вызывается после plan_and_execute и до verify_final_status.
    Post-verify триггер (error_persists_after_execution) применяется
    позже в build_final_comment.
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
            val = resp.get("error_found")
            result["error_still_present"] = bool(val) if val is not None else None
            lf = resp.get("logs_full")
            if isinstance(lf, list):
                result["logs_full_count"] = len(lf)
    except Exception as exc:
        diag.append("mcp.search_logs.recheck_exception")
        log.warning("verify_logs_recheck_failed", error=str(exc))
    return result


async def verify_final_status(
    ticket: Ticket, mcp: MCPClient, *, deadline: float, attempts: int = 3, base_sleep: float = 0.6
) -> tuple[dict[str, Any], list[ActionLogEntry]]:
    """Опрашивает get_order_status и check_eissd_status с backoff-ом (политика агента, не LLM)."""
    results: dict[str, Any] = {}
    logs: list[ActionLogEntry] = []
    diag: list[str] = []

    for i in range(attempts):
        _ensure_budget(deadline)

        r1: Any = None
        r2: Any = None

        entry1 = ActionLogEntry(tool="get_order_status", params={"order_id": ticket.order_id})
        t0 = _now()
        try:
            raw1 = await mcp.call_tool("get_order_status", {"order_id": ticket.order_id})
            resp1, code1, fatal1 = _unwrap_mcp_dict("get_order_status", raw1)
            if code1:
                diag.append(code1)
                if fatal1:
                    log.error("mcp_unexpected_type", tool="get_order_status", code=code1)
                    resp1 = _as_error_dict("get_order_status", raw1, code1)
                else:
                    log.warning("mcp_wrapped_response", tool="get_order_status", code=code1)
            r1 = resp1
            entry1.ok = True
            entry1.result = resp1
        except Exception as exc:
            entry1.ok = False
            entry1.error = str(exc)
            entry1.error_type = exc.__class__.__name__
        entry1.duration_ms = int((_now() - t0) * 1000)
        logs.append(entry1)

        entry2 = ActionLogEntry(tool="check_eissd_status", params={"order_id": ticket.order_id})
        t0 = _now()
        try:
            raw2 = await mcp.call_tool("check_eissd_status", {"order_id": ticket.order_id})
            resp2, code2, fatal2 = _unwrap_mcp_dict("check_eissd_status", raw2)
            if code2:
                diag.append(code2)
                if fatal2:
                    log.error("mcp_unexpected_type", tool="check_eissd_status", code=code2)
                    resp2 = _as_error_dict("check_eissd_status", raw2, code2)
                else:
                    log.warning("mcp_wrapped_response", tool="check_eissd_status", code=code2)
            r2 = resp2
            entry2.ok = True
            entry2.result = resp2
        except Exception as exc:
            entry2.ok = False
            entry2.error = str(exc)
            entry2.error_type = exc.__class__.__name__
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
        except ValueError as exc:
            log.warning("verify_status_normalise_failed", attempt=i, error=str(exc))

        sleep_s = base_sleep * (2**i)
        if _now() + sleep_s > deadline:
            break
        await asyncio.sleep(sleep_s)

    results["logs_recheck"] = await _do_logs_recheck(ticket, mcp, diag)
    results["_diag"] = diag
    pipeline_steps_total.labels(step="verify_logs_recheck", status="ok").inc()

    pipeline_steps_total.labels(step="verify_final_status", status="ok").inc()
    log.info("pipeline_step", step="verify_final_status", status="ok")
    return results, logs


def build_final_comment(
    ticket: Ticket,
    *,
    precheck: dict[str, Any],
    rag: dict[str, Any] | None,
    actions: list[ActionLogEntry],
    verify: dict[str, Any],
    llm_metrics: dict[str, Any] | None = None,
    escalate_reasons: list[str] | None = None,
    mrf: dict[str, Any] | None = None,
) -> str:
    """Собирает детерминированный финальный комментарий в формате key=value без участия LLM (шаг 6).

    Согласно спеке в комментарий включаются: журнал действий (key=value), итог МРФ-обхода
    (блок mrf.*), рекомендации RAG в дословном виде (блок rag.action.*) — без LLM-генерации.
    """
    import json as _json

    def _fmt_int(v: Any) -> str:
        if v is None:
            return ""
        if isinstance(v, bool):
            return str(int(v))
        try:
            return str(int(v))
        except (TypeError, ValueError):
            return str(v)

    def _fmt_bool(v: Any) -> str:
        if v is None:
            return ""
        return "true" if bool(v) else "false"

    with _step("generate"):
        pre_logs_raw = (precheck or {}).get("logs") or {}
        pre_diag = (precheck or {}).get("_diag") or []
        if not isinstance(pre_diag, list):
            pre_diag = ["precheck.diag_bad_type"]

        pre_logs, code, fatal = _unwrap_mcp_dict("search_logs", pre_logs_raw)
        diag: list[str] = list(pre_diag)
        if code and code not in diag:
            diag.append(code)

        if fatal:
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

        # Build escalate reasons: start with caller-supplied list, then append post-verify trigger
        all_reasons: list[str] = list(escalate_reasons) if escalate_reasons else []
        logs_recheck = verify.get("logs_recheck") if isinstance(verify, dict) else None
        if isinstance(logs_recheck, dict):
            if error_found and logs_recheck.get("error_still_present") is True:
                trigger = "error_persists_after_execution"
                if trigger not in all_reasons:
                    all_reasons.append(trigger)

        # New next_step logic
        if all_reasons:
            next_step = "ESCALATE_L2"
        elif not error_found:
            next_step = "NO_ERROR_IN_LOGS"
        elif not ok_all:
            next_step = "ESCALATE_L2"
        else:
            next_step = "IN_WORK_WAIT_CONFIRMATION"

        lines: list[str] = []
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

        # llm.* block
        m = llm_metrics or {}
        lines.append(f"llm.steps_used={_fmt_int(m.get('steps_used'))}")
        lines.append(f"llm.rag_followed={_fmt_int(m.get('rag_followed'))}")
        lines.append(f"llm.rag_deviated={_fmt_int(m.get('rag_deviated'))}")
        lines.append(f"llm.write_calls_total={_fmt_int(m.get('write_calls_total'))}")
        lines.append(f"llm.loop_exceeded={_fmt_bool(m.get('loop_exceeded')) if llm_metrics is not None else ''}")
        lines.append(f"llm.error_count={_fmt_int(m.get('error_count'))}")

        lines.append(f"verify.sulz_db.status={sulz_status}")
        lines.append(f"verify.eissd.status={eissd_status}")

        # verify.logs_recheck.* block
        lr = logs_recheck or {}
        lines.append(f"verify.logs_recheck.window_days={_fmt_int(lr.get('window_days')) if isinstance(lr, dict) else ''}")
        lines.append(f"verify.logs_recheck.error_still_present={_fmt_bool(lr.get('error_still_present')) if isinstance(lr, dict) and lr.get('error_still_present') is not None else ''}")
        lines.append(f"verify.logs_recheck.logs_full_count={_fmt_int(lr.get('logs_full_count')) if isinstance(lr, dict) else ''}")

        # mrf.* block (итог МРФ-обхода, шаги 5.1-5.3)
        mrf_ctx = mrf or {}
        mrf_queue = mrf_ctx.get("queue") if isinstance(mrf_ctx, dict) else None
        mrf_verdict = mrf_ctx.get("verdict") if isinstance(mrf_ctx, dict) else None
        mrf_cc = mrf_ctx.get("comments_count") if isinstance(mrf_ctx, dict) else None
        mrf_comment_text = mrf_ctx.get("mrf_comment") if isinstance(mrf_ctx, dict) else None
        lines.append(f"mrf.queue={mrf_queue or ''}")
        lines.append(f"mrf.verdict={mrf_verdict or ''}")
        lines.append(f"mrf.comments_count={'' if mrf_cc is None else mrf_cc}")
        if mrf_comment_text:
            # Дословная формулировка от МРФ (однострочно, чтобы не ломать key=value)
            first_line = str(mrf_comment_text).splitlines()[0] if mrf_comment_text else ""
            lines.append(f"mrf.comment={first_line}")

        if isinstance(mrf_ctx, dict):
            for d in mrf_ctx.get("_diag") or []:
                if d not in diag:
                    diag.append(d)

        # rag.action.* block — дословные required_actions из RAG без LLM-генерации
        rag_actions = []
        if isinstance(rag, dict):
            ra = rag.get("required_actions")
            if isinstance(ra, list):
                rag_actions = ra
        lines.append(f"rag.action.count={len(rag_actions)}")
        for idx, act in enumerate(rag_actions[:5]):
            if not isinstance(act, dict):
                lines.append(f"rag.action.{idx}={str(act)[:200]}")
                continue
            tool_name = act.get("tool") or act.get("name") or ""
            lines.append(f"rag.action.{idx}.tool={tool_name}")
            params = act.get("params") or act.get("parameters")
            if params is not None:
                try:
                    params_s = _json.dumps(params, ensure_ascii=False, separators=(",", ":"))
                except (TypeError, ValueError):
                    params_s = str(params)
                lines.append(f"rag.action.{idx}.params={params_s[:300]}")

        lines.append(f"diag.count={len(diag)}")
        for idx, entry in enumerate(diag[:5]):
            lines.append(f"diag.{idx}={entry}")

        # escalate.* block
        lines.append(f"escalate.triggered={'true' if all_reasons else 'false'}")
        for idx, reason in enumerate(all_reasons[:5]):
            lines.append(f"escalate.reason.{idx}={reason}")

        lines.append(f"next_step={next_step}")

        return "\n".join(lines) + "\n"


async def finalize(ticket: Ticket, final_comment: str, mcp: MCPClient, *, deadline: float) -> list[ActionLogEntry]:
    """Финализирует тикет: добавляет комментарий, при необходимости определяет очередь и переводит статус в OPEN (шаг 7)."""
    _ensure_budget(deadline)
    settings = get_settings()

    logs: list[ActionLogEntry] = []

    entry = ActionLogEntry(tool="add_otrs_comment", params={"ticket_id": ticket.id, "text_len": len(final_comment)})
    t0 = _now()
    try:
        r = await mcp.call_tool("add_otrs_comment", {"ticket_id": ticket.id, "text": final_comment})
        entry.ok = True
        entry.result = r
    except Exception as exc:
        entry.ok = False
        entry.error = str(exc)
        entry.error_type = exc.__class__.__name__
        log.exception("mcp_tool_failed", tool="add_otrs_comment", error=str(exc))
    entry.duration_ms = int((_now() - t0) * 1000)
    logs.append(entry)

    desired_queue = ticket.queue
    if not desired_queue:
        desired_queue = f"ОЦО.МРФ.Эксплуатация СУЛЗ.{ticket.region}" if ticket.region else "ОЦО.МРФ.Эксплуатация СУЛЗ"

    if settings.allow_queue_change:
        entry2 = ActionLogEntry(tool="resolve_mrf_queue", params={"region": ticket.region})
        t0 = _now()
        try:
            queue_resp = await mcp.call_tool("resolve_mrf_queue", {"region": ticket.region})
            q, code, fatal = _unwrap_mcp_dict("resolve_mrf_queue", queue_resp)
            if code:
                if fatal:
                    log.error("mcp_unexpected_type", tool="resolve_mrf_queue", code=code)
                else:
                    log.warning("mcp_wrapped_response", tool="resolve_mrf_queue", code=code)
            entry2.ok = True
            entry2.result = q
            if isinstance(q, dict) and q.get("queue"):
                desired_queue = str(q["queue"])
        except Exception as exc:
            entry2.ok = False
            entry2.error = str(exc)
            entry2.error_type = exc.__class__.__name__
            log.exception("mcp_tool_failed", tool="resolve_mrf_queue", error=str(exc))
        entry2.duration_ms = int((_now() - t0) * 1000)
        logs.append(entry2)

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
    except Exception as exc:
        entry3.ok = False
        entry3.error = str(exc)
        entry3.error_type = exc.__class__.__name__
        log.exception("mcp_tool_failed", tool="update_otrs_ticket", error=str(exc))
    entry3.duration_ms = int((_now() - t0) * 1000)
    logs.append(entry3)

    pipeline_steps_total.labels(step="finalize", status="ok").inc()
    log.info("pipeline_step", step="finalize", status="ok")
    return logs
