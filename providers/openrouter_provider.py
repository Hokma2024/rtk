import httpx
from langchain_openai import ChatOpenAI
from models.llm_config import LlmConfig
import logging

logger = logging.getLogger(__name__)

class OpenRouterProvider:
    def __init__(self):
        try: 
            self.config = LlmConfig()
            logger.info("Загрузка конфигурации")
        except Exception as e:
            logger.error(f"Ошибка при загрузке конфигурации: {e}")

    def initialization_llm(self):
        try: 
            self.llm = ChatOpenAI(
                model=self.config.model,
                base_url=self.config.base_url,
                api_key=self.config.api_key,
                timeout=self.config.timeout,
                temperature=self.config.temperature,
                max_retries=self.config.max_retries
            )
            logger.info(f"Подлкючение к удаленной ЛЛМ, модель = {self.llm.model}")
        except httpx.HTTPError as e:
            logger.error(f"Ошибка HTTP при инициализации ЛЛМ: {e}")
        except Exception as e:
            logger.error(f"Ошибка при инициализации ЛЛМ: {e}") 
            

