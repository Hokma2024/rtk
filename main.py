from datetime import datetime
import logging

from fastapi import FastAPI
from controllers.llm_controller import llm_router

log_filename = f"app_{datetime.now().strftime('%Y-%m-%d')}.log"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_filename, encoding='utf-8'),  # запись в файл
        logging.StreamHandler()  # вывод в консоль (если хочешь оставить)
    ]
)


app = FastAPI()
app.include_router(llm_router)

@app.get("/")
async def root():
    return {"app": "good"}