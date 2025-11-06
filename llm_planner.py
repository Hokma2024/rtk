# llm_planner.py
import os, json, httpx
from pydantic import BaseModel, Field, ValidationError

BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
MODEL = os.getenv("PLANNER_MODEL", "qwen2.5:7b-instruct")

SYSTEM_PROMPT = (
    "Ты планировщик действий агента. Верни ТОЛЬКО JSON:\n"
    '{"steps":[{"tool":"weather"|"currency"|"message","args":{}} ...]}\n'
    "- Если видишь 'сообщение: ...' — отправь ИМЕННО этот текст (без кавычек в args.text).\n"
    "- Если есть слово 'сообщение' БЕЗ двоеточия — отправь результат предыдущего шага.\n"
    "- Если город не указан — оставь args пустыми ({}), нормализуем позже.\n"
)

class PlanStep(BaseModel):
    tool: str
    args: dict = Field(default_factory=dict)

class PlanResponse(BaseModel):
    steps: list[PlanStep]

async def llm_plan(query: str) -> list[PlanStep]:
    payload = {
         "model": MODEL,
         "messages": [
             {"role":"system","content": SYSTEM_PROMPT},
             {"role":"user","content": query}
         ],
         "temperature": 0,
         "response_format": {"type": "json_object"}
     }
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(f"{BASE_URL}/chat/completions", json=payload)
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
        try:
            plan = PlanResponse.model_validate(json.loads(content))
            return plan.steps
        except (ValidationError, json.JSONDecodeError):
            return []  # пустой план -> перейдём на rule-based
    except Exception:
        # Любая сеть/таймаут/5xx -> тихо уходим в rule-based
        return []
