"""Одноразовый прогон тикета №7 (ORDER_STATUS_DENIED, Юг) через агента.

Использование: python run_ticket.py  (по умолчанию LLM_MODE=tools, Ollama qwen3:8b).
Переопределить через env: LLM_MODE, LLM_PROVIDER, LLM_MODEL_NAME и т.д.
"""
from __future__ import annotations

import json
import os

os.environ.setdefault("LLM_MODE", "tools")
os.environ.setdefault("LLM_PROVIDER", "ollama")
os.environ.setdefault("LLM_MODEL_NAME", "qwen3:8b")
os.environ.setdefault("OLLAMA_HOST", "http://localhost:11434")
# --- Альтернатива: OpenRouter (облако, нужен ключ) ---
# os.environ.setdefault("LLM_PROVIDER", "openrouter")
# os.environ.setdefault("LLM_MODEL_NAME", "qwen/qwen3-8b")
# os.environ.setdefault("LLM_API_KEY", "sk-or-v1-...")
os.environ.setdefault("LLM_TIMEOUT_SECONDS", "120")
os.environ.setdefault("REQUEST_TIME_BUDGET_SECONDS", "300")
os.environ.setdefault("RAG_BASE_URL", "http://localhost:8090")
os.environ.setdefault("MCP_SERVER_MODULE", "services.mcp_server.mcp_server")
os.environ.setdefault("DEBUG", "1")
os.environ.setdefault("ALLOW_QUEUE_CHANGE", "false")

from fastapi.testclient import TestClient  # noqa: E402

from agent_api.main import app  # noqa: E402

TICKET = {
    "id": "T-1800003879409",
    "order_id": "1800003879409",
    "subject": "Ошибка ORDER_STATUS_DENIED",
    "annotation": "Юг; СУЛЗ. Заявка уже отправлена в СУЛЗ; 1800003879409",
    "description": "Описание ошибки: Ошибка ORDER_STATUS_DENIED. Статус заявки: Ошибка ORDER_STATUS_DENIED.",
    "region": "Юг",
    "queue": "ОЦО.МРФ.Эксплуатация СУЛЗ",
    "metadata": {"source": "otrs_real", "ticket_number": 7},
}


def main() -> None:
    with TestClient(app) as client:
        resp = client.post("/tickets/intake", json=TICKET)
        print(f"HTTP {resp.status_code}")
        if resp.status_code != 200:
            print(resp.text)
            return
        data = resp.json()
        print("\n=== ticket_id ===")
        print(data["ticket_id"])
        print("\n=== summary ===")
        print(data["summary"])
        print("\n=== final_comment ===")
        print(data["final_comment"])
        print("\n=== actions (DEBUG) ===")
        for a in data.get("actions") or []:
            print(
                f"- {a['tool']:<24} ok={a['ok']}  {a.get('duration_ms')}ms"
                + (f"  ERR={a['error']}" if a.get("error") else "")
            )
        print("\n=== full JSON ===")
        print(json.dumps(data, ensure_ascii=False, indent=2)[:2000])


if __name__ == "__main__":
    main()
