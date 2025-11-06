# router.py
from __future__ import annotations

import asyncio
import json
import time
from typing import Dict, Callable, Optional, Any, Tuple

from .base_tool import BaseTool, ToolResult
from .llm_planner import PlanStep


# -----------------------------
# Адаптеры входов (args -> input)
# -----------------------------
AdaptFn = Callable[[str, dict, dict], str]
# сигнатура: (raw_text, args_from_llm, ctx) -> run_text


def _default_adapter(text: str, args: dict, ctx: dict) -> str:
    """Без изменений передаём исходный текст в инструмент."""
    return text


def _message_adapter(text: str, args: dict, ctx: dict) -> str:
    """Формируем полезную нагрузку для MessageTool."""
    if args.get("text") == "__USE_PREV_RESULT__":
        last_ok = ctx.get("last_ok")
        payload = "Нет результата предыдущих шагов" if last_ok is None else json.dumps(last_ok, ensure_ascii=False)
        return f"сообщение: {payload}"
    if "text" in args:
        return f"сообщение: {args['text']}"
    return "сообщение: (пусто)"


def _weather_adapter(text: str, args: dict, ctx: dict) -> str:
    """Если LLM дала city — используем его, иначе исходный текст."""
    return (args or {}).get("city") or text


# -----------------------------
# Политика вызовов (timeouts, retries, rate-limit)
# -----------------------------

class ToolRouter:
    """
    Продвинутый роутер:
      - хранит инструменты, алиасы и адаптеры входов;
      - исполняет шаги плана с политиками timeout/retry/rate-limit;
      - унифицирует ошибки и даёт хуки для телеметрии.
    """

    def __init__(
        self,
        tools: Dict[str, BaseTool],
        *,
        adapters: Optional[Dict[str, AdaptFn]] = None,
        aliases: Optional[Dict[str, str]] = None,
        timeouts: Optional[Dict[str, float]] = None,            # tool -> seconds
        retries: Optional[Dict[str, Tuple[int, float]]] = None, # tool -> (retries, backoff_sec)
        rate_limits: Optional[Dict[str, float]] = None,         # tool -> min_interval_sec между вызовами
        on_event: Optional[Callable[[str, dict], None]] = None, # hook(event, payload)
    ):
        self.tools: Dict[str, BaseTool] = dict(tools)
        self.adapters: Dict[str, AdaptFn] = {
            "*": _default_adapter,
            "message": _message_adapter,
            "weather": _weather_adapter,
        }
        if adapters:
            self.adapters.update(adapters)

        self.aliases = aliases or {}
        self.timeouts = timeouts or {}
        self.retries = retries or {}
        self.rate_limits = rate_limits or {}
        self._last_call: Dict[str, float] = {}  # tool -> last_ts_monotonic
        self._on_event = on_event

    # -------- Registration --------
    def register(
        self,
        tool: BaseTool,
        *,
        aliases: Tuple[str, ...] = (),
        adapter: Optional[AdaptFn] = None,
        timeout: Optional[float] = None,
        retries: Optional[Tuple[int, float]] = None,
        rate_limit_min_interval: Optional[float] = None,
    ) -> None:
        self.tools[tool.name] = tool
        for a in aliases:
            self.aliases[a] = tool.name
        if adapter:
            self.adapters[tool.name] = adapter
        if timeout is not None:
            self.timeouts[tool.name] = timeout
        if retries is not None:
            self.retries[tool.name] = retries
        if rate_limit_min_interval is not None:
            self.rate_limits[tool.name] = rate_limit_min_interval

    # -------- Helpers --------
    def _emit(self, event: str, **payload: Any) -> None:
        if self._on_event:
            try:
                self._on_event(event, payload)
            except Exception:
                # телеметрия не должна ломать логику
                pass

    def _resolve_name(self, name: str) -> Optional[str]:
        if name in self.tools:
            return name
        return self.aliases.get(name)

    def _adapt(self, tool_name: str, raw_text: str, args: dict, ctx: dict) -> str:
        fn = self.adapters.get(tool_name) or self.adapters["*"]
        return fn(raw_text, args or {}, ctx)

    async def _respect_rate_limit(self, tool_name: str) -> None:
        min_interval = self.rate_limits.get(tool_name)
        if not min_interval:
            return
        now = time.monotonic()
        last = self._last_call.get(tool_name)
        if last is not None:
            delta = now - last
            if delta < min_interval:
                sleep_for = min_interval - delta
                self._emit("rate_limited_wait", tool=tool_name, sleep_for=sleep_for)
                await asyncio.sleep(sleep_for)
        self._last_call[tool_name] = time.monotonic()

    async def _call_with_policy(self, tool: BaseTool, run_text: str) -> ToolResult:
        name = tool.name
        timeout = self.timeouts.get(name)
        retries, backoff = self.retries.get(name, (0, 0.0))

        last_result: Optional[ToolResult] = None
        for attempt in range(retries + 1):
            try:
                self._emit("before_call", tool=name, attempt=attempt)
                if timeout:
                    result = await asyncio.wait_for(tool.run(run_text), timeout=timeout)
                else:
                    result = await tool.run(run_text)
                self._emit("after_call", tool=name, attempt=attempt, status=result.status)
            except asyncio.TimeoutError:
                self._emit("timeout", tool=name, attempt=attempt, timeout=timeout)
                last_result = ToolResult(tool=name, status="error", error=f"Timeout after {timeout}s", duration_ms=0.0)
            except Exception as e:
                self._emit("exception", tool=name, attempt=attempt, error=str(e))
                last_result = ToolResult(tool=name, status="error", error=str(e), duration_ms=0.0)
            else:
                # Если инструмент вернул error и у нас есть попытки — повторим
                if result.status == "error" and attempt < retries:
                    if backoff:
                        await asyncio.sleep(backoff * (2 ** attempt))
                    last_result = result
                    continue
                return result

            # сюда попадём при Timeout/Exception или error с продолжением
            if attempt < retries and backoff:
                await asyncio.sleep(backoff * (2 ** attempt))

        # Если не удалось получить ok
        return last_result or ToolResult(tool=name, status="error", error="Unknown error", duration_ms=0.0)

    # -------- Public API --------
    async def execute_step(self, step: PlanStep, raw_text: str, ctx: dict) -> ToolResult:
        """
        Исполняет ОДИН шаг плана:
          - резолвит алиасы/версии;
          - адаптирует вход (args -> run_text);
          - соблюдает rate-limit;
          - вызывает инструмент с timeout/retry политиками.
        """
        name = self._resolve_name(step.tool) or step.tool
        tool = self.tools.get(name)
        if not tool:
            return ToolResult(tool=name, status="error", error="Инструмент не найден", duration_ms=0.0)

        run_text = self._adapt(name, raw_text, step.args or {}, ctx)
        await self._respect_rate_limit(name)
        return await self._call_with_policy(tool, run_text)

    # Совместимость: примитивный route на случай прямого использования (не рекомендуется)
    async def route(self, text: str) -> ToolResult:
        """
        Для обратной совместимости: роутинг «по ключевым словам».
        Рекомендуется использовать Planner + execute_step.
        """
        text_l = text.lower()
        if "погод" in text_l:
            step = PlanStep(tool="weather", args={})
        elif any(w in text_l for w in ("курс", "доллар", "евро", "юан", "валют")):
            step = PlanStep(tool="currency", args={})
        elif "сообщ" in text_l or "отправ" in text_l:
            step = PlanStep(tool="message", args={})
        else:
            return ToolResult(tool="router", status="error", error="Не удалось определить действие", duration_ms=0.0)

        return await self.execute_step(step, raw_text=text, ctx={})
