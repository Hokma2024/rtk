from __future__ import annotations

import ast
import json
import logging
import os
import sys
import time
import uuid
from typing import Any, Dict, List, Optional

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

logger = logging.getLogger(__name__)

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
        self._session: Optional[ClientSession] = None

        self._debug = os.getenv("MCP_DEBUG", "").strip().lower() in ("1", "true", "yes", "on")

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
            logger.warning("MCP_DEBUG enabled. server_module=%s", self.server_module)

    async def close(self) -> None:
        if self._session is not None:
            await self._session.__aexit__(None, None, None)
            self._session = None
        if self._stdio_ctx is not None:
            await self._stdio_ctx.__aexit__(None, None, None)
            self._stdio_ctx = None

    async def list_tools(self):
        if self._session is None:
            raise RuntimeError("MCPClient is not connected")
        resp = await self._session.list_tools()
        return resp.tools if hasattr(resp, "tools") else resp

    def _decode_text(self, tool: str, raw_text: str, call_id: str) -> Any:
        """
        Многошаговый декодер с подробным trace в логах.
        Показывает, что именно не распарсилось и почему в итоге получился str.
        """
        t = (raw_text or "").strip()
        if self._debug:
            logger.warning("[MCP:%s:%s] RAW_TEXT type=str len=%d preview=%s", call_id, tool, len(t), _preview(t))

        if not t:
            return ""

        # 1) multi-pass json.loads (“JSON строка внутри JSON”)
        cur: Any = t
        for i in range(1, 4):
            if not isinstance(cur, str):
                if self._debug:
                    logger.warning("[MCP:%s:%s] JSON pass %d -> non-str (%s) preview=%s",
                                   call_id, tool, i, type(cur).__name__, _preview(cur))
                return cur
            s = cur.strip()
            try:
                nxt = json.loads(s)
                if self._debug:
                    logger.warning("[MCP:%s:%s] JSON pass %d OK -> %s preview=%s",
                                   call_id, tool, i, type(nxt).__name__, _preview(nxt))
                cur = nxt
                # если распарсили и получили строку, а она выглядит как JSON — продолжаем
                if isinstance(cur, str) and _looks_like_json_container(cur):
                    continue
                return cur
            except Exception as e:
                if self._debug:
                    logger.warning("[MCP:%s:%s] JSON pass %d FAIL (%s): %s",
                                   call_id, tool, i, e.__class__.__name__, str(e))
                break

        # 2) python literal (ловит "{'a':1}" / "[...]" / "SearchLogsResponse(...)" не поймает)
        try:
            v = ast.literal_eval(t)
            if self._debug:
                logger.warning("[MCP:%s:%s] literal_eval OK -> %s preview=%s",
                               call_id, tool, type(v).__name__, _preview(v))

            # если literal_eval вернул строку — возможно внутри JSON
            if isinstance(v, str) and _looks_like_json_container(v):
                cur2: Any = v
                for j in range(1, 3):
                    try:
                        nxt2 = json.loads(cur2)
                        if self._debug:
                            logger.warning("[MCP:%s:%s] JSON-after-literal pass %d OK -> %s preview=%s",
                                           call_id, tool, j, type(nxt2).__name__, _preview(nxt2))
                        cur2 = nxt2
                        if isinstance(cur2, str) and _looks_like_json_container(cur2):
                            continue
                        return cur2
                    except Exception as e2:
                        if self._debug:
                            logger.warning("[MCP:%s:%s] JSON-after-literal pass %d FAIL (%s): %s",
                                           call_id, tool, j, e2.__class__.__name__, str(e2))
                        return v
            return v
        except Exception as e:
            if self._debug:
                logger.warning("[MCP:%s:%s] literal_eval FAIL (%s): %s",
                               call_id, tool, e.__class__.__name__, str(e))

        # 3) fallback
        if self._debug:
            logger.warning("[MCP:%s:%s] DECODE FALLBACK -> str preview=%s", call_id, tool, _preview(t))
        return t

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        if self._session is None:
            raise RuntimeError("MCPClient is not connected")

        call_id = uuid.uuid4().hex[:8]
        t0 = time.perf_counter()

        if self._debug:
            logger.warning("[MCP:%s] CALL tool=%s args=%s", call_id, name, _preview(arguments))

        result = await self._session.call_tool(name, {"input": arguments})
        elapsed_ms = int((time.perf_counter() - t0) * 1000)

        content = getattr(result, "content", result)

        if self._debug:
            logger.warning("[MCP:%s] RAW_RESULT tool=%s elapsed_ms=%d raw_type=%s preview=%s",
                           call_id, name, elapsed_ms, type(content).__name__, _preview(content))

        # MCP обычно возвращает list content items (TextContent и т.п.)
        if isinstance(content, list) and content:
            decoded: List[Any] = []
            for idx, item in enumerate(content):
                # для разных реализаций MCP: item.text или {"text": "..."}
                if hasattr(item, "text"):
                    raw_text = item.text
                    if self._debug:
                        logger.warning("[MCP:%s:%s] CONTENT[%d] item_type=%s has_text=True text_preview=%s",
                                       call_id, name, idx, type(item).__name__, _preview(raw_text))
                    decoded.append(self._decode_text(name, raw_text, call_id))
                elif isinstance(item, dict) and "text" in item:
                    raw_text = item.get("text")
                    if self._debug:
                        logger.warning("[MCP:%s:%s] CONTENT[%d] item_type=dict has_text=True text_preview=%s",
                                       call_id, name, idx, _preview(raw_text))
                    decoded.append(self._decode_text(name, str(raw_text), call_id))
                else:
                    if self._debug:
                        logger.warning("[MCP:%s:%s] CONTENT[%d] item_type=%s (NO text) preview=%s",
                                       call_id, name, idx, type(item).__name__, _preview(item))
                    decoded.append(item)

            out = decoded[0] if len(decoded) == 1 else decoded

            if self._debug:
                logger.warning("[MCP:%s] DECODED tool=%s type=%s preview=%s",
                               call_id, name, type(out).__name__, _preview(out))

            return out

        if self._debug:
            logger.warning("[MCP:%s] RETURN-NONLIST tool=%s type=%s preview=%s",
                           call_id, name, type(content).__name__, _preview(content))

        return content

    @staticmethod
    def to_openai_tools_schema(mcp_tools) -> List[Dict[str, Any]]:
        converted: List[Dict[str, Any]] = []
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