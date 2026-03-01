# import asyncio
# from typing import List

# import httpx
 
# from providers.openrouter_provider import OpenRouterProvider
# from providers.ollama_provider import OllamaProvider
# from models.message import Message, MessageRole
# from models.llm_config import LlmConfig, ProviderType 

# from common.prompts import Prompts

# from mcp.client.stdio import stdio_client
# from mcp import ClientSession, StdioServerParameters

# import logging

# logger = logging.getLogger(__name__)

# class McpClient:


#     def __init__(self, mcp_command: str):
#         self.mcp_command = mcp_command
#         self.config = LlmConfig()
#         self.provider = OllamaProvider()
#         self.session: ClientSession | None = None
#         self.tools = []

#     async def connect_mcp(self):
#         server_params = StdioServerParameters(
#             command="python", 
#             args=[self.mcp_command]
#         )

#         self.stdio_ctx = stdio_client(server_params)
#         read, write = await self.stdio_ctx.__aenter__()
#         self.session = ClientSession(read, write)
#         await self.session.__aenter__()
#         await self.session.initialize()

#         tools_result = await self.session.list_tools()
#         logger.info(f"Получены инструменты: {tools_result.tools}")

#         self.tools = tools_result.tools


#     async def chat_completion(self, mes: str):
        
#         message = [
#             Message(MessageRole.SYSTEM, Prompts.SYSTEM_PROMPT),
#             Message(MessageRole.USER, mes)
#         ]
        
#         print(message)
#         return await self.provider.chat_completion(message, self.tools)
    
#     async def close(self):
#         if self.session:
#             await self.session.__aexit__(None, None, None)
#         if hasattr(self, "stdio_ctx"):
#             await self.stdio_ctx.__aexit__(None, None, None)
        
    


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