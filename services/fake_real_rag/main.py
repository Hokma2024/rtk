"""Фейковый "реальный" RAG для сквозного теста.

Эмулирует внешний сервис, который ожидает rag_adapter:
POST /query  {collection_name, text, use_cache, prompt_type}
→ {answer, source, cached}

Берёт фикстуры из tests/fixtures/rag_real_responses.json и выбирает
подходящий кейс по вхождению current_order_id в поле text запроса.
Если совпадений нет — возвращает case_4_general_guidance.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

FIXTURE_PATH = Path(
    os.getenv("FAKE_RAG_FIXTURE", "/app/tests/fixtures/rag_real_responses.json")
)

app = FastAPI(title="Fake Real RAG")


def _load_cases() -> list[dict[str, Any]]:
    with FIXTURE_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


_CASES: list[dict[str, Any]] = _load_cases()


class RealRagRequest(BaseModel):
    collection_name: str
    text: str
    use_cache: bool = True
    prompt_type: str = "system"


@app.get("/health")
async def health() -> dict[str, bool]:
    return {"ok": True}


@app.post("/query")
async def query(req: RealRagRequest) -> dict[str, Any]:
    text = req.text or ""
    override = os.getenv("FAKE_RAG_CASE")
    picked: dict[str, Any] | None = None

    if override:
        for c in _CASES:
            if c.get("id") == override:
                picked = c
                break

    if picked is None:
        for c in _CASES:
            oid = c.get("current_order_id")
            if oid and oid in text:
                picked = c
                break

    if picked is None:
        picked = next((c for c in _CASES if c.get("id") == "case_4_general_guidance"), _CASES[0])

    return {
        "answer": picked.get("raw_answer", ""),
        "source": picked.get("sources", []),
        "cached": False,
    }
