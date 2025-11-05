# testT.py
import os, httpx
from dotenv import load_dotenv

load_dotenv()
token = os.getenv("BOT_TOKEN")
url = f"https://api.telegram.org/bot{token}/getUpdates"

r = httpx.get(url, timeout=10)
data = r.json()
print(data)

# Быстрая выборка chat_id (если есть апдейты)
try:
    chat_id = data["result"][-1]["message"]["chat"]["id"]
    print("CHAT_ID:", chat_id)
except Exception as e:
    print("Не нашёл chat_id. Пришли боту сообщение и запусти снова.", e)
    print("TOKEN:",token)
    
