from typing import List
from providers.openrouter_provider import OpenRouterProvider
from models.message import Message, MessageRole
from langchain_core.messages import HumanMessage, SystemMessage
from tools.tools import tools

class OpenRouterRepository:
    def __init__(self):
        self.openrouter_provider = OpenRouterProvider()
        self.openrouter_provider.initialization_llm()
        
        
    async def initialization_llm(self):
        return self.openrouter_provider.llm
    

    # async def reinitialization_llm(self):
    #     self.openrouter_provider.initialization_llm()
    #     return self.openrouter_provider.llm
    

    async def chat_completion(self, messages: List[Message]):
        langchain_messages = []
        for msg in messages:
            if msg.role == MessageRole.SYSTEM:
                langchain_messages.append(SystemMessage(content=msg.content))
            if msg.role == MessageRole.USER:
                langchain_messages.append(HumanMessage(content=msg.content))

        llm_with_tools = self.openrouter_provider.llm.bind_tools(tools)

        response = await llm_with_tools.ainvoke(langchain_messages)
        print(response.tool_calls)

        return response.tool_calls