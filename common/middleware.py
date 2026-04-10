from __future__ import annotations

import time

from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from common.logging import bind_trace_id, clear_trace_id, get_or_create_trace_id
from common.metrics import http_request_duration_seconds, http_requests_total

_TRACE_HEADER = "X-Trace-Id"


class TraceIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        incoming = request.headers.get(_TRACE_HEADER)
        trace_id = get_or_create_trace_id(incoming)
        bind_trace_id(trace_id)
        try:
            response = await call_next(request)
        finally:
            clear_trace_id()
        response.headers[_TRACE_HEADER] = trace_id
        return response


def install_http_metrics(app: FastAPI, *, service_name: str) -> None:
    @app.middleware("http")
    async def _metrics(request: Request, call_next):
        start = time.perf_counter()
        status = "500"
        try:
            response = await call_next(request)
            status = str(response.status_code)
            return response
        finally:
            elapsed = time.perf_counter() - start
            endpoint = request.url.path
            http_requests_total.labels(
                service=service_name,
                endpoint=endpoint,
                method=request.method,
                status=status,
            ).inc()
            http_request_duration_seconds.labels(
                service=service_name,
                endpoint=endpoint,
            ).observe(elapsed)
