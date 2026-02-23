import os
import httpx
from langchain_ollama import ChatOllama
from models.llm_config import LlmConfig
import logging

logger = logging.getLogger(__name__)

class OllamaProvider:
    def __init__(self):

        try: 
            self.config = LlmConfig()
            logger.info("Загрузка конфигурации")
        except Exception as e:
            logger.error(f"Ошибка при загрузке конфигурации: {e}")

    def initialization_llm(self):
        try:
            os.environ['NO_PROXY'] = 'localhost,127.0.0.1'
            os.environ['no_proxy'] = 'localhost,127.0.0.1'
            logging.info("Отключение прокси для localhost")
        
            custom_timeout = httpx.Timeout(
                connect=30.0,    # Время на установку соединения
                read=120.0,      # Время на чтение ответа
                write=30.0,      # Время на отправку
                pool=10.0        # Время ожидания в пуле
            )
            logging.info("Создание таймаута")
            
            transport = httpx.HTTPTransport(
                retries=3,
                verify=True
            )
            logging.info("Создание транспорта для HTTP запросов")
        
            http_client = httpx.Client(
                timeout=custom_timeout,
                transport=transport,
                follow_redirects=True
            )
            logging.info("Создание HTTP-клиента")
        
            self.llm = ChatOllama(
                model=self.config.model,
                base_url=self.config.ollama_host,
                temperature=self.config.temperature,
                num_predict=2048,
                client=http_client  # Передаем настроенный клиент
            )
            logging.info(f"Подлкючение к локальной ЛЛМ, модель = {self.llm.model}")
        except httpx.HTTPError as e:
            logger.error(f"Ошибка HTTP: {e}")
            raise
        except Exception as e:
            logger.error(f"Ошибка при инициализации ЛЛМ: {e}") 
