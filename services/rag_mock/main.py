import os
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import List, Dict, Any, Optional, Tuple

from fastapi import FastAPI
from pydantic import BaseModel


app = FastAPI(title="RAG Mock (Examples + Similarity)")


DEFAULT_Q_PATH = "/app/services/rag_mock/examples/questions.txt"
DEFAULT_A_PATH = "/app/services/rag_mock/examples/answers.txt"

QUESTIONS_PATH = os.getenv("RAG_EXAMPLES_QUESTIONS", DEFAULT_Q_PATH)
ANSWERS_PATH = os.getenv("RAG_EXAMPLES_ANSWERS", DEFAULT_A_PATH)

MATCH_THRESHOLD = float(os.getenv("RAG_MATCH_THRESHOLD", "0.12"))


class RagRequest(BaseModel):
    ticket_id: str
    log_error_found: bool
    log_error_name: str | None = None
    subject: str
    description: str
    annotation: str | None = None
    error_text: str | None = None


class RagTextResponse(BaseModel):
    ticket_id: str
    answer_text: str


@dataclass
class Example:
    idx: int
    query_text: str
    answer_text: str


EXAMPLES: List[Example] = []


def _safe_read(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def parse_numbered_blocks(raw: str) -> List[str]:
    """
    Парсит формат:
    1:
    текст...

    2:
    текст...
    """
    raw = (raw or "").strip()
    if not raw:
        return []

    headers = list(re.finditer(r"(?m)^\s*(\d+)\s*:\s*$", raw))
    if not headers:
        return [raw]

    blocks: List[str] = []
    for i, h in enumerate(headers):
        start = h.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(raw)
        chunk = raw[start:end].strip()
        blocks.append(chunk)

    return blocks


def normalize_text(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[^a-zа-я0-9]+", " ", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def token_set(s: str) -> set[str]:
    s = normalize_text(s)
    toks = [t for t in s.split(" ") if len(t) >= 3]
    return set(toks)


def similarity(a: str, b: str) -> float:
    a_n = normalize_text(a)
    b_n = normalize_text(b)
    if not a_n or not b_n:
        return 0.0

    ta = token_set(a_n)
    tb = token_set(b_n)
    inter = len(ta & tb)
    union = len(ta | tb) if (ta | tb) else 1
    jacc = inter / union

    seq = SequenceMatcher(None, a_n, b_n).ratio()
    return 0.65 * jacc + 0.35 * seq


def build_request_text(req: RagRequest) -> str:
    parts: List[str] = []
    if req.annotation:
        parts.append(f"Аннотация: {req.annotation}")
    if req.subject:
        parts.append(f"Тема обращения: {req.subject}")
    if req.description:
        parts.append(f"Описание: {req.description}")
    if req.error_text:
        parts.append(f"Текст ошибки: {req.error_text}")

    if req.log_error_found:
        parts.append(f"Проверка логов: ошибка {req.log_error_name or 'UNKNOWN'} обнаружена")
    else:
        parts.append("Проверка логов: ошибка не обнаружена")

    return ". ".join(parts)


def choose_example(req_text: str) -> Tuple[Optional[Example], float]:
    best: Optional[Example] = None
    best_score = 0.0
    for ex in EXAMPLES:
        sc = similarity(req_text, ex.query_text)
        if sc > best_score:
            best_score = sc
            best = ex
    return best, best_score


def load_examples() -> None:
    global EXAMPLES

    q_raw = _safe_read(QUESTIONS_PATH)
    a_raw = _safe_read(ANSWERS_PATH)

    qs = parse_numbered_blocks(q_raw)
    ans = parse_numbered_blocks(a_raw)

    pairs = min(len(qs), len(ans))
    EXAMPLES = [Example(idx=i + 1, query_text=qs[i], answer_text=ans[i]) for i in range(pairs)]

    print(f"[rag-mock] Loaded questions={len(qs)} answers={len(ans)} pairs={pairs}")
    if len(qs) != len(ans):
        print("[rag-mock] WARNING: questions/answers count mismatch. Using min(pairs).")


@app.on_event("startup")
def _startup():
    load_examples()


@app.post("/rag/solve_ticket", response_model=RagTextResponse)
def solve_ticket(req: RagRequest):
    if not EXAMPLES:
        return RagTextResponse(
            ticket_id=req.ticket_id,
            answer_text="RAG-mock: нет загруженных примеров.",
        )

    req_text = build_request_text(req)
    ex, score = choose_example(req_text)

    if ex is None or score < MATCH_THRESHOLD:
        return RagTextResponse(
            ticket_id=req.ticket_id,
            answer_text=(
                "Не найден близкий пример в RAG-mock.\n"
                "Рекомендуемые действия:\n"
                "1. Зафиксировать исходные данные тикета и результаты проверок.\n"
                "2. Передать инженеру для ручного анализа.\n"
            ),
        )

    return RagTextResponse(ticket_id=req.ticket_id, answer_text=ex.answer_text)


@app.get("/debug/examples")
def debug_examples() -> List[Dict[str, Any]]:
    return [
        {
            "idx": ex.idx,
            "query_preview": ex.query_text[:200],
            "answer_preview": ex.answer_text[:200],
        }
        for ex in EXAMPLES
    ]


@app.get("/debug/match")
def debug_match(text: str):
    ex, score = choose_example(text)
    if not ex:
        return {"matched": False, "score": 0.0}
    return {"matched": True, "idx": ex.idx, "score": score, "query_preview": ex.query_text[:200]}
