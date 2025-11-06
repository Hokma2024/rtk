# planner.py
import re
import json
from typing import List

from .router import ToolRouter
from .base_tool import ToolResult
from .llm_planner import llm_plan, PlanStep

# Явная форма полезной нагрузки для message: сообщение: "текст"
MSG_PAYLOAD_RE = re.compile(r"сообщение\s*:\s*['\"]?(.*?)['\"]?$", re.IGNORECASE | re.DOTALL)


def extract_explicit_message(text: str) -> str | None:
    """
    Достаём payload для message без изменения регистра/символов.
    ВАЖНО: сюда подаем исходный текст, а не lower()-версию.
    """
    m = MSG_PAYLOAD_RE.search(text)
    return m.group(1).strip() if m else None


class Planner:
    """
    Продвинутый планировщик:
    - LLM-план с безопасным фоллбэком на rule-based.
    - Guardrails: гарантируем шаг message, если пользователь просит «отправить».
    - Дедупликация одинаковых соседних шагов, ограничение на количество шагов.
    - Оркестрация выполнения через Router (который адаптирует args и применяет политику таймаутов/ретраев).
    """

    def __init__(self, router: ToolRouter, *, max_steps: int = 6, error_budget: int = 2):
        self.router = router
        self.max_steps = max_steps          # верхняя граница длины плана
        self.error_budget = error_budget    # сколько подряд ошибок позволяем, прежде чем остановиться

    async def _rule_based(self, text: str, text_l: str) -> List[PlanStep]:
        """
        Простейшие правила на случай, если LLM-план пустой или недоступен.
        text_l — нижний регистр для поиска ключевых слов,
        text — исходный текст для извлечения payload сообщения (без порчи регистра).
        """
        steps: list[PlanStep] = []
        if "погод" in text_l:
            steps.append(PlanStep(tool="weather", args={}))
        if "курс" in text_l:
            steps.append(PlanStep(tool="currency", args={}))
        if "сообщ" in text_l or "отправ" in text_l:
            explicit = extract_explicit_message(text)  # используем ОРИГИНАЛЬНЫЙ текст
            if explicit:
                steps.append(PlanStep(tool="message", args={"text": explicit}))
            else:
                steps.append(PlanStep(tool="message", args={"text": "__USE_PREV_RESULT__"}))
        return steps

    def _guardrails(self, text: str, text_l: str, steps: List[PlanStep]) -> List[PlanStep]:
        """
        Мини-санитайзер плана:
        - гарантирует шаг message, если его нет, а пользователь просит отправить;
        - удаляет соседние дубликаты шагов;
        - обрезает план до max_steps.
        """
        # 1) Добавим message, если явно просили, но его нет в плане
        needs_message = ("сообщ" in text_l) or ("отправ" in text_l)
        has_message = any(s.tool == "message" for s in steps)
        if needs_message and not has_message:
            explicit = extract_explicit_message(text)
            payload = {"text": explicit if explicit else "__USE_PREV_RESULT__"}
            steps.append(PlanStep(tool="message", args=payload))

        # 2) Уберём соседние дубликаты (tool + args)
        deduped: list[PlanStep] = []
        prev_sig: str | None = None
        for s in steps:
            sig = f"{s.tool}:{json.dumps(s.args or {}, ensure_ascii=False, sort_keys=True)}"
            if sig != prev_sig:
                deduped.append(s)
            prev_sig = sig

        # 3) Обрежем по лимиту
        if len(deduped) > self.max_steps:
            deduped = deduped[: self.max_steps]

        return deduped

    async def execute(self, text: str) -> List[ToolResult]:
        text_l = text.lower().strip()
        results: list[ToolResult] = []

        # 1) Пытаемся получить LLM-план
        steps = await llm_plan(text)

        # 2) Если пусто — фоллбэк на правила
        if not steps:
            steps = await self._rule_based(text, text_l)

        # 3) Применим guardrails (message, дедуп, лимит)
        steps = self._guardrails(text, text_l, steps)

        # 4) Выполнение шагов через Router (адаптация аргументов/политики — внутри него)
        ctx: dict = {"last_ok": None}
        consecutive_errors = 0

        for step in steps:
            r = await self.router.execute_step(step, raw_text=text, ctx=ctx)
            results.append(r)

            if r.status == "ok":
                ctx["last_ok"] = r.data
                consecutive_errors = 0
            else:
                consecutive_errors += 1
                # Простой error budget: если подряд слишком много ошибок — прекращаем сценарий
                if consecutive_errors >= self.error_budget:
                    break

        return results
