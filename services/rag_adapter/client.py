"""HTTP-клиент к реальному RAG.

Реальный RAG ожидает запрос в формате, зафиксированном в ``тикеты.txt``::

    POST <real-rag-url>
    {
      "collection_name": "СУЛЗ",
      "text": "Аннотация: ... Описание: ... Тема обращения: ...",
      "use_cache": true,
      "prompt_type": "system"
    }

Ответ::

    {
      "answer": "<markdown>",
      "source": [{"url": "...", "page_title": "..."}, ...],
      "cached": false
    }

URL реального RAG на момент разработки не задан — помечен как TODO.
Ставится через ``REAL_RAG_URL`` в ``.env``.
"""

from __future__ import annotations

from typing import Any

import httpx

from common.config import get_settings
from common.logging import get_logger
from pipeline.rag_models import RagRequest

log = get_logger(__name__)


class RealRagNotConfiguredError(RuntimeError):
    """Бросается, когда REAL_RAG_URL не задан в конфигурации."""


def build_rag_text(req: RagRequest) -> str:
    """Собирает поле ``text`` запроса к реальному RAG из полей тикета.

    Формат близок к реальному примеру из ``тикеты.txt``: "Аннотация: ...
    Описание: ... Тема обращения: ...". Precheck в запрос не уходит —
    используется только локально в pipeline/LLM для принятия решений.
    """
    parts: list[str] = []
    if req.annotation:
        parts.append(f"Аннотация: {req.annotation}")
    if req.description:
        parts.append(f"Описание: {req.description}")
    if req.subject:
        parts.append(f"Тема обращения: {req.subject}")
    return ". ".join(parts)


async def call_real_rag(req: RagRequest) -> dict[str, Any]:
    """Вызывает реальный RAG и возвращает распарсенный JSON-ответ.

    :raises RealRagNotConfiguredError: если ``REAL_RAG_URL`` не установлен.
    :raises httpx.HTTPError: при сетевых/HTTP ошибках.
    """
    settings = get_settings()
    url = settings.real_rag_url
    if not url:
        # TODO(stand): URL реального RAG получить у команды тестового стенда.
        raise RealRagNotConfiguredError(
            "REAL_RAG_URL is not set. Configure real_rag_url in .env "
            "to use rag_adapter with a live RAG service."
        )

    payload = {
        "collection_name": settings.real_rag_collection,
        "text": build_rag_text(req),
        "use_cache": settings.real_rag_use_cache,
        "prompt_type": settings.real_rag_prompt_type,
    }

    log.info(
        "real_rag_call_start",
        url=url,
        collection=settings.real_rag_collection,
        text_len=len(payload["text"]),
    )

    async with httpx.AsyncClient(timeout=settings.real_rag_timeout_seconds) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()

    log.info(
        "real_rag_call_end",
        url=url,
        cached=data.get("cached"),
        answer_len=len(data.get("answer") or ""),
        sources_count=len(data.get("source") or []),
    )
    return data
