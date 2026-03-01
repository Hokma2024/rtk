import json
from typing import Any, Dict, List

import httpx
from models.llm_config import LlmConfig
import logging

from models.message import Message, MessageRole

logger = logging.getLogger(__name__)

class OpenRouterProvider:
    def __init__(self):
        self.config = LlmConfig()
        
    async def chat_completion(self, messages: list[dict], tools: List[Any] | None = None):
        
        request_body = {
        "model": self.config.model,
        "messages": messages
        }
            
        if tools:
            request_body["tools"] = self._convert_tools_to_openrouter_format(tools)
            request_body["tool_choice"] = "auto"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.config.base_url}/chat/completions",
                headers=self.config.headers,
                json=request_body,
                timeout=self.config.timeout
            )
        data = response.json()

        parce_data = self._parce_response(data)

        return parce_data
        

    def _convert_tools_to_openrouter_format(self, mcp_tools):
        converted = []
        for tool in mcp_tools:
            converted.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": tool.inputSchema,
                },
            })
        return converted
    
    def _parce_response(self, response: Dict[str, Any]):

        choices = response.get("choices", [])
        if not choices:
            logger.warning("В ответе API от OpenRouter нет choices")
            return []
        
        if not isinstance(choices[0], Dict):
            logger.warning("Неверный формат choices")
            return []

        message = choices[0].get("message", {})
        if not message:
            logger.warning("В ответе API от OpenRouter нет message")
            return []
        
        if not isinstance(message, Dict):
            logger.warning("Неверный формат message")
            return []
        
        tool_calls = message.get("tool_calls", [])
        if not tool_calls:
            logger.warning("В ответе API от OpenRouter нет tool_calls")
            return []
        
        if not isinstance(tool_calls, list):
            logger.warning("Неверный формат tool_calls")
            return []   
        

        return tool_calls   


    # def _tool_call(self, tools):
    #     function = tools.get("function", {})
    #     if not function:
    #         logger.warning("В ответе API от OpenRouter нет function")
    #         return []

    #     if not isinstance(function, dict):
    #         logger.warning("Неверный формат isinstance")
    #         return []
        
    #     name = tools.get("name", "")
    #     if not name:
    #         logger.warning("В ответе API от OpenRouter нет name")
    #         return []

    #     if not isinstance(name, str):
    #         logger.warning("Неверный формат name")
    #         return []
        
    #     arguments = tools.get("arguments", "")
    #     if not arguments:
    #         logger.warning("В ответе API от OpenRouter нет arguments")
    #         return []

    #     if not isinstance(arguments, str):
    #         logger.warning("Неверный формат arguments")
    #         return []
        




        