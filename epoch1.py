# epoch1.py
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, field_validator, StringConstraints
from typing_extensions import Annotated

from router import ToolRouter
from tools.weather_tool import WeatherTool
from tools.currency_tool import CurrencyTool
from tools.message_tool import MessageTool

import uuid
import time

app = FastAPI()

tools = {
    "weather": WeatherTool(),
    "currency": CurrencyTool(),
    "message": MessageTool(),
}

router = ToolRouter(tools)

Text500 = Annotated[str, StringConstraints(max_length=500, strip_whitespace=True)]

class HandleRequest(BaseModel):
    text: Text500

    @field_validator("text", mode="after")
    @classmethod
    def check_not_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("Введите непустой запрос")
        return v

@app.post("/agent/handle")
async def handle(req: HandleRequest, request: Request):
    result = await router.route(req.text)

    #FALLBACK: если инструмент не справился — уведомляем инженера
    if result.status == "error" and tools.get("message"):
        alert = f"[ALERT] tool={result.tool} trace_id={request.state.trace_id} error={result.error} path={ str(request.url.path)}"
        _ = await tools["message"].run(text=f"сообщение: {alert}")

    return {"status": "ok", "trace_id": request.state.trace_id, "result": result.model_dump(), "status_code": 200}

# -------------------------------
# Observability_middleware
# -------------------------------
@app.middleware("http")
async def observability_middleware(request: Request, call_next):
    trace_id = f"req-{uuid.uuid4().hex[:8]}"
    request.state.trace_id = trace_id

    start_time = time.perf_counter()
    request.state.start_time = start_time  # ← добавляем эту строку

    response = await call_next(request)
    duration = (time.perf_counter() - start_time) * 1000

    response.headers.update({
        "X-Trace-Id": trace_id,
        "X-Response-Time-ms": f"{duration:.2f}",
    })

    return response


# -------------------------------
# Обработчик 422
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