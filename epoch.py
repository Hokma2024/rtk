# epoch2.py
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, field_validator, StringConstraints
from typing_extensions import Annotated

from .router import ToolRouter
from .tools.weather_tool import WeatherTool
from .tools.currency_tool import CurrencyTool
from .tools.message_tool import MessageTool
from .planner import Planner

import uuid
import time

app = FastAPI()
ALERT_DEDUP: dict[str, float] = {}  # key -> expires_at (monotonic seconds)
ALERT_TTL = 60.0  # сек, защита от спама одинаковыми ошибками

# --- Инструменты и маршрутизатор
tools = {
    "weather": WeatherTool(),
    "currency": CurrencyTool(),
    "message": MessageTool(),
}
router = ToolRouter(tools)
planner = Planner(router)

# --- Валидация входа
Text4000 = Annotated[str, StringConstraints(max_length=4000, strip_whitespace=True)]


class HandleRequest(BaseModel):
    text: Text4000

    @field_validator("text", mode="after")
    @classmethod
    def check_not_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("Введите непустой запрос")
        return v


# --- Эндпоинт агента (многошаговый)
@app.post("/agent/handle")
async def handle(req: HandleRequest, request: Request):
    results = await planner.execute(req.text)

    # FALLBACK: уведомляем инженера по КАЖДОЙ ошибке шага
    msg_tool = tools.get("message")
    if msg_tool:
        for r in results:
            if r.status == "error":
                alert = (
                    f"[ALERT] tool={r.tool} "
                    f"trace_id={request.state.trace_id} "
                    f"error={r.error} "
                    f"path={str(request.url.path)}"
                )
                # простая дедупликация на ALERT_TTL секунд
                key = f"{r.tool}:{(r.error or '')[:120]}"
                now = time.monotonic()
                if ALERT_DEDUP.get(key, 0) < now:
                    try:
                        _ = await msg_tool.run(text=f"сообщение: {alert}")
                    except Exception:
                        # Не ломаем пользовательский ответ из-за ошибки алерта
                        pass
                    ALERT_DEDUP[key] = now + ALERT_TTL

    return {
        "status": "ok",
        "trace_id": request.state.trace_id,
        "results": [r.model_dump() for r in results],
        "status_code": 200,
    }


# -------------------------------
# Observability middleware
# -------------------------------
@app.middleware("http")
async def observability_middleware(request: Request, call_next):
    trace_id = f"req-{uuid.uuid4().hex[:8]}"
    request.state.trace_id = trace_id

    start_time = time.perf_counter()
    request.state.start_time = start_time

    response = await call_next(request)
    duration = (time.perf_counter() - start_time) * 1000

    response.headers.update(
        {
            "X-Trace-Id": trace_id,
            "X-Response-Time-ms": f"{duration:.2f}",
        }
    )
    return response


# -------------------------------
# Глобальный обработчик 422
# -------------------------------
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    clean_errors = []
    for err in exc.errors():
        ctx = err.get("ctx")
        if ctx and "error" in ctx:
            ctx["error"] = str(ctx["error"])
        clean_errors.append(err)

    start_time = getattr(request.state, "start_time", None)
    duration_ms = None
    if start_time is not None:
        duration_ms = (time.perf_counter() - start_time) * 1000

    first_error = clean_errors[0] if clean_errors else {}
    message = first_error.get("msg", "Ошибка валидации данных")

    payload = {
        "status": "error",
        "status_code": 422,
        "error_code": "VALIDATION_ERROR",
        "message": message,
        "trace_id": getattr(request.state, "trace_id", "unknown"),
        "path": str(request.url.path),
        "details": clean_errors,
        "duration_ms": None if duration_ms is None else round(duration_ms, 2),
    }
    return JSONResponse(status_code=422, content=payload)
