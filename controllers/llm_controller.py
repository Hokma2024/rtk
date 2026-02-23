from fastapi import APIRouter
from services.llm_service import LlmService

llm_router = APIRouter(prefix="/agent")

service = LlmService()

@llm_router.post("/initialization")
async def llm_initialization():
    return await service.initialization_llm()

@llm_router.post("/query")
async def procces_query(message: str):
    return await service.process_query(message=message)