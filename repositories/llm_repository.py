import asyncio
from typing import List

import httpx

from providers.ollama_provider import OllamaProvider
from providers.openrouter_provider import OpenRouterProvider
from models.message import Message, MessageRole
from langchain_core.messages import HumanMessage, SystemMessage
from models.llm_config import LlmConfig, ProviderType
from tools.tools import tools

import logging

logger = logging.getLogger(__name__)

class LlmRepository:
    def __init__(self):
        try: 
            self.config = LlmConfig()
            logger.info("Загрузка конфигурации")
        except Exception as e:
            logger.error(f"Ошибка при загрузке конфигурации: {e}")    

        self.provider_type = self.config.provider

        if self.provider_type == ProviderType.LOCAL:
            self.provider = OllamaProvider()
            logger.info("Создан Ollama провайдер")
        elif self.provider_type == ProviderType.OPENROUTER:
            self.provider = OpenRouterProvider()
            logger.info("Создан OpenRouter провайдер")
        else:
            logger.error(f"Неизвестный провайдер: {self.provider_type}")
            raise ValueError(f"Неизвестный провайдер: {self.provider_type}")



    async def initialization_llm(self):
        try:
            llm = self.provider.initialization_llm()
            logger.info("Инициализация подключения к ЛЛМ, репозиторий")
        except Exception as e:
            logger.error(f"Ошибка при инициализации подключения к ЛЛМ: {e}")
        return llm
    
    async def chat_completion(self, messages: List[Message]):
        langchain_messages = []
        try:
            for msg in messages:
                if msg.role == MessageRole.SYSTEM:
                    langchain_messages.append(SystemMessage(content=msg.content))
                    logger.debug("Добавлено системное сообщение")
                if msg.role == MessageRole.USER:
                    langchain_messages.append(HumanMessage(content=msg.content))
                    logger.debug("Добавлено пользовательское сообщение")
        except AttributeError as e:
            logger.error(f"Ошибка: сообщение не имеет нужных атрибутов - {e}")
        except Exception as e:
            logger.error(f"Ошибка при составлении списка сообщений к агенту: {e}")

        try:
            llm_with_tools = self.provider.llm.bind_tools(tools)
        except AttributeError as e:
            logger.error(f"ЛЛМ не поддерживает bind_tools: {e}") 
        except Exception as e:
            logger.error(f"Ошибка при привязке инструментов к ЛЛМ: {e}")   

        try:
            response = await llm_with_tools.ainvoke(langchain_messages)
            logger.info("Отправка запроса к ЛЛМ")
            if response is None:
                raise ValueError("Получен пустой ответ от ЛЛМ")
        except httpx.HTTPError as e:
            logger.error(f"Ошибка HTTP при запросе к ЛЛМ: {e}")
        except asyncio.TimeoutError as e:
            logger.error(f"Таймаут при обращении к ЛЛМ: {e}")
        except Exception as e:
            logger.error(f"Ошибка при запросе к ЛЛМ: {e}")


        return {
            "text": response.content,
            "tools_called": response.tool_calls 
        }


