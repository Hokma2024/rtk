import os
import httpx
from langchain_ollama import ChatOllama
from models.llm_config import LlmConfig
<<<<<<< HEAD
import logging

logger = logging.getLogger(__name__)
=======
>>>>>>> 036362937c5bda2524caeb84e3e5e96b651df6d9


class OllamaProvider:
    def __init__(self):
<<<<<<< HEAD
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
=======
        self.config = LlmConfig()

    def initialization_llm(self):
        # Критически важно: исключаем localhost из прокси
        os.environ['NO_PROXY'] = 'localhost,127.0.0.1'
        os.environ['no_proxy'] = 'localhost,127.0.0.1'
        
        # Создаем HTTP-клиент с явным отключением прокси
        custom_timeout = httpx.Timeout(
            connect=30.0,    # Время на установку соединения
            read=120.0,      # Время на чтение ответа
            write=30.0,      # Время на отправку
            pool=10.0        # Время ожидания в пуле
        )
        
        # Создаем транспорт, который игнорирует прокси
        transport = httpx.HTTPTransport(
            retries=3,
            verify=True
        )
        
        http_client = httpx.Client(
            timeout=custom_timeout,
            transport=transport,
            follow_redirects=True
        )
        
        self.llm = ChatOllama(
            model=self.config.model,
            base_url=self.config.ollama_host,
            temperature=self.config.temperature,
            num_predict=2048,
            client=http_client  # Передаем настроенный клиент
        )
        # self.llm = ChatOllama(
        #     model=self.config.model,
        #     base_url=self.config.ollama_host,
        #     temperature=self.config.temperature,
        #     timeout=self.config.timeout,
        #     num_ctx=4096,
        #     num_predict=1024,
        #     keep_alive="5m"
        # ) 
        print("ИНИЦИАЛИЗИРОВАЛИ ЛЛМ")
>>>>>>> 036362937c5bda2524caeb84e3e5e96b651df6d9
