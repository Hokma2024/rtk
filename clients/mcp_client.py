from __future__ import annotations

import ast
import json
import sys
import time
import uuid
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from common.config import get_settings
from common.logging import get_logger
from common.metrics import mcp_requests_total

log = get_logger(__name__)

MAX_PREVIEW = 900


def _preview(x: Any, n: int = MAX_PREVIEW) -> str:
    s = repr(x)
    if len(s) > n:
        return s[:n] + "…"
    return s


def _looks_like_json_container(s: str) -> bool:
    s = (s or "").strip()
    return (s.startswith("{") and s.endswith("}")) or (s.startswith("[") and s.endswith("]"))


class MCPClient:
    def __init__(self, server_module: str) -> None:
        self.server_module = server_module
        self._stdio_ctx = None
        self._session: ClientSession | None = None
        self._debug = get_settings().mcp_debug

    async def connect(self) -> None:
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", self.server_module],
        )

        self._stdio_ctx = stdio_client(params)
        read, write = await self._stdio_ctx.__aenter__()

        self._session = ClientSession(read, write)
        await self._session.__aenter__()
        await self._session.initialize()

        if self._debug:
            log.warning("mcp_debug_enabled", server_module=self.server_module)

    async def close(self) -> None:
        if self._session is not None:
            await self._session.__aexit__(None, None, None)
            self._session = None
        if self._stdio_ctx is not None:
            await self._stdio_ctx.__aexit__(None, None, None)
            self._stdio_ctx = None

    async def list_tools(self) -> Any:
        if self._session is None:
            raise RuntimeError("MCPClient is not connected")
        resp = await self._session.list_tools()
        return resp.tools if hasattr(resp, "tools") else resp

    def _decode_text(self, tool: str, raw_text: str, call_id: str) -> Any:
        """Многоступенчатый декодер: JSON (до 3 проходов) → ast.literal_eval → строка как есть."""
        t = (raw_text or "").strip()
        if self._debug:
            log.warning("mcp_decode_raw", call_id=call_id, tool=tool, len=len(t), preview=_preview(t))

        if not t:
            return ""

        # Проходы 1-3: итеративный json.loads (обрабатывает дважды закодированные JSON-строки)
        cur: Any = t
        for i in range(1, 4):
            if not isinstance(cur, str):
                if self._debug:
                    log.warning(
                        "mcp_decode_non_str",
                        call_id=call_id,
                        tool=tool,
                        pass_=i,
                        kind=type(cur).__name__,
                        preview=_preview(cur),
                    )
                return cur
            s = cur.strip()
            try:
                nxt = json.loads(s)
                if self._debug:
                    log.warning(
                        "mcp_decode_json_ok",
                        call_id=call_id,
                        tool=tool,
                        pass_=i,
                        kind=type(nxt).__name__,
                        preview=_preview(nxt),
                    )
                cur = nxt
                # Если результат всё ещё выглядит как JSON-контейнер в строке — продолжаем
                if isinstance(cur, str) and _looks_like_json_container(cur):
                    continue
                return cur
            except (json.JSONDecodeError, ValueError):
                # Намеренный выход: пробуем следующую стратегию декодирования
                if self._debug:
                    log.warning("mcp_decode_json_fail", call_id=call_id, tool=tool, pass_=i)
                break

        # Проход 4: Python-литерал (обрабатывает dict/list с одинарными кавычками)
        try:
            v = ast.literal_eval(t)
            if self._debug:
                log.warning(
                    "mcp_decode_literal_ok", call_id=call_id, tool=tool, kind=type(v).__name__, preview=_preview(v)
                )
            # Если literal_eval вернул строку-JSON-контейнер — пробуем ещё раз json.loads
            if isinstance(v, str) and _looks_like_json_container(v):
                cur2: Any = v
                for j in range(1, 3):
                    try:
                        nxt2 = json.loads(cur2)
                        if self._debug:
                            log.warning(
                                "mcp_decode_json_after_literal_ok",
                                call_id=call_id,
                                tool=tool,
                                pass_=j,
                                kind=type(nxt2).__name__,
                                preview=_preview(nxt2),
                            )
                        cur2 = nxt2
                        if isinstance(cur2, str) and _looks_like_json_container(cur2):
                            continue
                        return cur2
                    except (json.JSONDecodeError, ValueError):
                        # Намеренно: возвращаем результат literal_eval
                        return v
            return v
        except (ValueError, SyntaxError):
            # Намеренно: проваливаемся к возврату исходной строки
            if self._debug:
                log.warning("mcp_decode_literal_fail", call_id=call_id, tool=tool)

        # Финальный запасной вариант: возвращаем сырую строку
        if self._debug:
            log.warning("mcp_decode_fallback_str", call_id=call_id, tool=tool, preview=_preview(t))
        return t

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        if self._session is None:
            raise RuntimeError("MCPClient is not connected")

        call_id = uuid.uuid4().hex[:8]
        t0 = time.perf_counter()

        if self._debug:
            log.warning("mcp_call_start_debug", call_id=call_id, tool=name, args=_preview(arguments))

        status = "error"
        log.info("mcp_call_start", tool=name)
        try:
            result = await self._session.call_tool(name, {"input": arguments})
            status = "ok"
        except Exception:
            log.exception("mcp_call_failed", tool=name)
            raise
        finally:
            mcp_requests_total.labels(tool=name, status=status).inc()
            log.info("mcp_call_end", tool=name, status=status)

        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        content = getattr(result, "content", result)

        if self._debug:
            log.warning(
                "mcp_raw_result",
                call_id=call_id,
                tool=name,
                elapsed_ms=elapsed_ms,
                raw_type=type(content).__name__,
                preview=_preview(content),
            )

        if isinstance(content, list) and content:
            decoded: list[Any] = []
            for idx, item in enumerate(content):
                if hasattr(item, "text"):
                    raw_text = item.text
                    if self._debug:
                        log.warning(
                            "mcp_content_item",
                            call_id=call_id,
                            tool=name,
                            idx=idx,
                            item_type=type(item).__name__,
                            has_text=True,
                            preview=_preview(raw_text),
                        )
                    decoded.append(self._decode_text(name, raw_text, call_id))
                elif isinstance(item, dict) and "text" in item:
                    raw_text = item.get("text")
                    if self._debug:
                        log.warning(
                            "mcp_content_item_dict", call_id=call_id, tool=name, idx=idx, preview=_preview(raw_text)
                        )
                    decoded.append(self._decode_text(name, str(raw_text), call_id))
                else:
                    if self._debug:
                        log.warning(
                            "mcp_content_item_no_text",
                            call_id=call_id,
                            tool=name,
                            idx=idx,
                            item_type=type(item).__name__,
                            preview=_preview(item),
                        )
                    decoded.append(item)

            out = decoded[0] if len(decoded) == 1 else decoded

            if self._debug:
                log.warning("mcp_decoded", call_id=call_id, tool=name, kind=type(out).__name__, preview=_preview(out))
            return out

        if self._debug:
            log.warning(
                "mcp_return_nonlist", call_id=call_id, tool=name, kind=type(content).__name__, preview=_preview(content)
            )
        return content

    @staticmethod
    def to_openai_tools_schema(mcp_tools: Any) -> list[dict[str, Any]]:
        converted: list[dict[str, Any]] = []
        for tool in mcp_tools:
            converted.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description or "",
                        "parameters": tool.inputSchema,
                    },
                }
            )
        return converted
