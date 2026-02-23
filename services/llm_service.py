from models.message import Message, MessageRole
from repositories.llm_repository import LlmRepository
from common.prompts import Prompts
import logging

logger = logging.getLogger(__name__)



class LlmService:
    def __init__(self):
        self.repository = LlmRepository()

    async def initialization_llm(self):
        return await self.repository.initialization_llm()
    

    async def process_query(self, message: str):
        try:
            system_message = Message()
            system_message.role = MessageRole.SYSTEM
            system_message.content = Prompts.SYSTEM_PROMPT #здесь промпт того, как должна отрабатывать ллм
            logger.debug("Создание системного сообщения с промтом для ЛЛМ")
        except AttributeError as e:
                    logger.error(f"Ошибка при создании системного сообщения - отсутствует SYSTEM_PROMPT: {e}")

        if message is None:
             raise ValueError("Отсутствует сообщение для ЛЛМ")
        user_message = Message()
        user_message.role = MessageRole.USER
        user_message.content = message #здесь запрос и ЗДЕСЬ отправляются логи для анализа и тд
        logger.debug("Создание пользовательского сообщения с логами и запросом для обработки")

        response = await self.repository.chat_completion([system_message, user_message])
             
        return response