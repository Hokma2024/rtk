# tools/currency_tool.py
from base_tool import BaseTool
import httpx

class CurrencyTool(BaseTool):
    name = "currency"

    async def _execute(self, text: str):
        url = "https://open.er-api.com/v6/latest/RUB"

        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            r = await client.get(url)
            if r.status_code != 200:
                raise ValueError(f"Ошибка запроса API: {r.status_code}")
            data = r.json()

        if data.get("result") != "success":
            raise ValueError(f"Ошибка API: {data.get('error-type', 'неизвестно')}")

        rates = data.get("rates")
        if not rates:
            raise ValueError("Ответ API не содержит данных о курсах валют")

        # отберём нужные валюты
        filtered = {cur: rates[cur] for cur in ("USD", "EUR", "CNY") if cur in rates}

        # инвертируем: сколько рублей за 1 единицу валюты
        inverted = {cur: round(1 / val, 2) for cur, val in filtered.items() if val != 0}

        return {
            "base": "RUB",
            "date": data.get("time_last_update_utc"),
            "rates": inverted
        }
