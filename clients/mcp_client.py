import asyncio
import json
import os
from typing import List

import httpx
 
from providers.openrouter_provider import OpenRouterProvider
from providers.ollama_provider import OllamaProvider
from models.message import Message, MessageRole
from models.llm_config import LlmConfig, ProviderType 

from common.prompts import Prompts

from mcp.client.stdio import stdio_client
from mcp import ClientSession, StdioServerParameters

import logging

logger = logging.getLogger(__name__)

class McpClient:


    def __init__(self, mcp_command: str):
        self.mcp_command = mcp_command
        self.config = LlmConfig()
        self.provider = OpenRouterProvider()
        self.session: ClientSession | None = None
        self.tools = []
        self._closed = False

    async def connect_mcp(self):
        if self._closed:
            self._closed = False
        
        server_params = StdioServerParameters(
            command="python", 
            args=[self.mcp_command]
        )

        # Создаем и сразу входим в контекстный менеджер
        self._stdio_ctx = stdio_client(server_params)
        self._read_stream, self._write_stream = await self._stdio_ctx.__aenter__()
        
        # Создаем сессию
        self.session = ClientSession(self._read_stream, self._write_stream)
        await self.session.__aenter__()
        await self.session.initialize()

        tools_result = await self.session.list_tools()
        logger.info(f"Получены инструменты: {tools_result.tools}")

        self.tools = tools_result.tools

    async def chat_completion(self, mes: str):
        
        message = [
            {"role": "system", "content": Prompts.SYSTEM_PROMPT},
            {"role": "user", "content": mes},
        ]
        
        print(message)
        result = await self.provider.chat_completion(message, self.tools)
        tools_result = []

        if result:
            for res in result:
                tool = await self._tool_call(res)
                tools_result.append(tool)

        return {
            "LLM": result,
            "Tools": tools_result
        }
    
    
    async def close(self):
        if self._closed:
            return
        
        self._closed = True
        
        errors = []
        
        # Закрываем сессию
        if self.session:
            try:
                print("ЗАКРЫТИЕ СЕССИИ")
                await self.session.__aexit__(None, None, None)
            except Exception as e:
                errors.append(f"Ошибка закрытия сессии: {e}")
            finally:
                self.session = None
        
        # Закрываем stdio контекст
        if self._stdio_ctx:
            try:
                print("ЗАКРЫТИЕ STDIO")
                await self._stdio_ctx.__aexit__(None, None, None)
            except Exception as e:
                errors.append(f"Ошибка закрытия stdio: {e}")
            finally:
                self._stdio_ctx = None
                self._read_stream = None
                self._write_stream = None
        
        if errors:
            logger.warning(f"Errors: {errors}")



    async def _tool_call(self, tool):
        try:

            function = tool.get("function", {})

            name = function.get("name", "")

            arguments = function.get("arguments", "")

            print("name: ", name)
            print("arg: ", arguments, type(arguments))


            if isinstance(arguments, str):
                try:
                    arguments_dict = json.loads(arguments)
                    print("Распарсенные аргументы:", arguments_dict)
                    print("Тип arguments_dict:", type(arguments_dict))
                except json.JSONDecodeError as e:
                    logger.error(f"Ошибка парсинга JSON: {e}")
                    return None
            else:
                arguments_dict = arguments

            mcp_arguments = {"input": arguments_dict}
            result = await self.session.call_tool(name, arguments=mcp_arguments)
            # print("РЕЗУЛЬТАТ ВЫЗОВА ТУЛЗОВ: ", result.content)
            return result.content 
                    

        except Exception as e:
            logger.error(f"Ошибка при обработке tool_calls: {e}")
        
        # result = await self.session.call_tool(name, arguments)
        # print(result)
        # return result.content

        # return {"name": name, "agr": arguments} 
       
    


# async def to_connetc_mcp():
#     agent = McpClient("server.py")
#     await agent.connect_mcp()
#     messages = [
#             Message(MessageRole.USER, "Не включается комп")
#         ]
#     print(messages)

#     res = await agent.chat_completion(messages)
#     print(res)
#     await agent.close()


# if __name__ == "__main__":
#     asyncio.run(to_connetc_mcp())


        # def __init__(self):
    #     try: 
    #         self.config = LlmConfig()
    #         logger.info("Загрузка конфигурации")
    #     except Exception as e:
    #         logger.error(f"Ошибка при загрузке конфигурации: {e}")    

    #     self.provider_type = self.config.provider

    #     if self.provider_type == ProviderType.LOCAL:
    #         self.provider = OllamaProvider()
    #         logger.info("Создан Ollama провайдер")
    #     elif self.provider_type == ProviderType.OPENROUTER:
    #         self.provider = OpenRouterProvider()
    #         logger.info("Создан OpenRouter провайдер")
    #     else:
    #         logger.error(f"Неизвестный провайдер: {self.provider_type}")
    #         raise ValueError(f"Неизвестный провайдер: {self.provider_type}")