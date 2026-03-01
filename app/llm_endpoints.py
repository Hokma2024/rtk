from typing import List

from fastapi import APIRouter, HTTPException
from clients.mcp_client import McpClient

import logging

logger = logging.getLogger(__name__)

llm_router = APIRouter(prefix="/agent")

client = McpClient("server.py")



@llm_router.post("/query")
async def procces_query(message: str):

    try:
        await client.connect_mcp()
        
        response = await client.chat_completion(message)

        print(response)
        return response
            
    except Exception as e:
        logger.error(f"Ошибка при обработке запроса: {e}")
    finally:
        await client.close()