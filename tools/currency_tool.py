# tools/currency_tool.py
from ..base_tool import BaseTool, ToolResult
import httpx
import time
import asyncio
from typing import Dict, Tuple, Any

# Простой in-memory кэш ответа API на короткое время
_CACHE: Dict[str, Tuple[float, Any]] = {}  # url -> (ts_monotonic, data)
_CACHE_TTL = 60.0  # сек


class CurrencyTool(BaseTool):
    name = "currency"

    async def _execute(self, text: str):
        url = "https://open.er-api.com/v6/latest/RUB"

        # Кэш: отдаём свежий результат без запроса
        now = time.monotonic()
        cached = _CACHE.get(url)
        if cached and (now - cached[0]) < _CACHE_TTL:
            data = cached[1]
        else:
            data = None
            # 3 попытки с короткой паузой между ними
            for attempt in range(3):
                try:
                    async with httpx.AsyncClient(timeout=10) as client:
                        r = await client.get(url)
                        if r.status_code != 200:
                            raise ValueError(f"Ошибка запроса API: {r.status_code}")
                        data = r.json()
                        break
                except Exception:
                    if attempt < 2:
                        await asyncio.sleep(0.4)
            if data is None:
                raise ValueError("Не удалось получить курсы после повторов")
            _CACHE[url] = (now, data)

        if data.get("result") != "success":
            raise ValueError(f"Ошибка API: {data.get('error-type', 'неизвестно')}")

        rates = data.get("rates")
        if not rates:
            raise ValueError("Ответ API не содержит данных о курсах валют")

        # отберём нужные валюты
        filtered = {cur: rates[cur] for cur in ("USD", "EUR", "CNY") if cur in rates}

        # инвертируем: сколько рублей за 1 единицу валюты (точность до тысячных)
        inverted = {cur: round(1 / val, 3) for cur, val in filtered.items() if val not in (0, None)}

        return {
            "base": "RUB",
            "date": data.get("time_last_update_utc"),
            "rates": inverted,
        }
