# base_tool.py
from pydantic import BaseModel
from typing import Any, Optional, Literal
import time

class ToolResult(BaseModel):
    tool: str                      # имя инструмента (например: "weather")
    status: Literal["ok", "error"] # результат выполнения
    data: Optional[Any] = None     # любые полезные данные
    error: Optional[str] = None    # сообщение об ошибке
    duration_ms: Optional[float] = None  # время выполнения

class BaseTool:
    name: str = "base"

    async def run(self, text: str) -> ToolResult:
        """Главный метод, который обязан реализовать каждый tool."""
        start = time.perf_counter()
        try:
            data = await self._execute(text)
            duration = (time.perf_counter() - start) * 1000
            return ToolResult(tool=self.name, status="ok", data=data, duration_ms=duration)
        except Exception as e:
            duration = (time.perf_counter() - start) * 1000
            return ToolResult(tool=self.name, status="error", error=str(e), duration_ms=duration)

    async def _execute(self, text: str) -> Any:
        """Реальная логика конкретного инструмента (переопределяется в наследниках)."""
        raise NotImplementedError
