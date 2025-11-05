# router.py
from typing import Dict
from base_tool import ToolResult
class ToolRouter:
    def __init__(self, tools: Dict[str, object]):
        self.tools = tools  # {'weather': WeatherTool(), 'currency': CurrencyTool(), ...}

    async def route(self, text: str) -> ToolResult:
        text_l = text.lower()

        if "погод" in text_l:
            tool = self.tools.get("weather")
        elif any(word in text_l for word in ("курс", "доллар", "евро", "юан", "валют")):
            tool = self.tools.get("currency")
        elif "сообщ" in text_l or "отправ" in text_l:
            tool = self.tools.get("message")
        else:
            return ToolResult(tool="router", status="error", error="Не удалось определить действие")

        if not tool:
            return ToolResult(tool="router", status="error", error="Инструмент не найден")

        return await tool.run(text=text)