# tools/weather_tool.py
from base_tool import BaseTool, ToolResult
import httpx

class WeatherTool(BaseTool):
    name = "weather"

    # простая карта координат (для начала)
    CITY_COORDS = {
        "моск": (55.75, 37.62),
        "питер": (59.93, 30.33),
        "казан": (55.79, 49.12),
        "екат": (56.83, 60.60),
        "новосиб": (55.03, 82.92),
        "краснод": (45.0355, 38.9753),
    }

    WEATHER_DESC = {
    0: "ясно",
    1: "в основном ясно",
    2: "переменная облачность",
    3: "пасмурно",
    45: "туман",
    48: "изморозь",
    51: "слабый дождь",
    61: "дождь",
    71: "снег",
    80: "ливни",
    }

    async def _execute(self, text: str):
        text_l = text.lower()
        coords = None

        # поиск города в тексте
        for key, (lat, lon) in self.CITY_COORDS.items():
            if key in text_l:
                coords = (lat, lon)
                city_name = key
                break

        if not coords:
            raise ValueError("Не удалось определить город")

        lat, lon = coords
        url = (
            f"https://api.open-meteo.com/v1/forecast?"
            f"latitude={lat}&longitude={lon}&current_weather=true"
        )

        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url)
            if r.status_code != 200:
                raise ValueError(f"Ошибка запроса API: {r.status_code}")
            data = r.json()

        weather = data.get("current_weather", {})
        if not weather:
            raise ValueError("Ответ API не содержит данных о погоде")
        code = weather.get("weathercode")
        description = self.WEATHER_DESC.get(code, "неизвестно")
        return {
            "city": city_name.title(),
            "temp": weather.get("temperature"),
            "windspeed": weather.get("windspeed"),
            "weathercode": code,
            "description": description,
        }
