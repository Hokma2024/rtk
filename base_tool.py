# base_tool.py
from pydantic import BaseModel
from typing import Any, Optional, Literal
import time


class ToolResult(BaseModel):
    tool: str                           # имя инструмента
    status: Literal["ok", "error"]      # результат выполнения
    data: Optional[Any] = None          # полезные данные (если ok)
    error: Optional[str] = None         # сообщение об ошибке (если error)
    duration_ms: float = 0.0            # длительность выполнения в мс


class BaseTool:
    name: str = "base"

    async def run(self, text: str) -> ToolResult:
        """меряет время, ловит ошибки, нормализует результат."""
        start = time.perf_counter()
        try:
            data = await self._execute(text)
            status, err = "ok", None
        except Exception as e:
            data, status, err = None, "error", str(e)
        duration_ms = (time.perf_counter() - start) * 1000.0
        return ToolResult(
            tool=self.name,
            status=status,
            data=data,
            error=err,
            duration_ms=round(duration_ms, 3),
        )

    async def _execute(self, text: str) -> Any:
        """Реализация конкретного инструмента."""
        raise NotImplementedError
