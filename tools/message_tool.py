# tools/message_tool.py
from base_tool import BaseTool
import httpx
import os
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ENGINEER_CHAT_ID = os.getenv("ENGINEER_CHAT_ID")

class MessageTool(BaseTool):
    name = "message"

    async def _execute(self, text: str):
        if not BOT_TOKEN or not ENGINEER_CHAT_ID:
            raise ValueError("Не настроен токен или chat_id")

        # простейшее извлечение сообщения
        parts = text.split("сообщение:", 1)
        msg_text = parts[1].strip() if len(parts) > 1 else "Пустое сообщение"

        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {"chat_id": ENGINEER_CHAT_ID, "text": msg_text}

        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(url, json=payload)
            data = r.json()

        if not data.get("ok"):
            raise ValueError(f"Ошибка Telegram API: {data}")

        return {
            "recipient": ENGINEER_CHAT_ID,
            "message": msg_text,
            "telegram_status": "ok"
        }
