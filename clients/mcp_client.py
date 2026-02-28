import asyncio
import json
from typing import Any, Dict

from openai import AsyncOpenAI
from mcp.client.stdio import stdio_client
from mcp import ClientSession


OPENAI_MODEL = "gpt-4o-mini"  # можно заменить


class MCPAgent:
    def __init__(self, mcp_command: str):
        self.mcp_command = mcp_command
        self.openai = AsyncOpenAI()
        self.session: ClientSession | None = None
        self.tools_schema = None

    async def connect_mcp(self):
        self.stdio_ctx = stdio_client("python", [self.mcp_command])
        read, write = await self.stdio_ctx.__aenter__()
        self.session = ClientSession(read, write)
        await self.session.__aenter__()

        tools = await self.session.list_tools()
        self.tools_schema = self._convert_tools_to_openai_schema(tools)

    def _convert_tools_to_openai_schema(self, mcp_tools):
        """Преобразуем MCP schema → OpenAI function schema"""
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

    async def run(self, user_input: str):
        messages = [
            {"role": "system", "content": "Ты агент поддержки заказов."},
            {"role": "user", "content": user_input},
        ]

        response = await self.openai.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            tools=self.tools_schema,
            tool_choice="auto",
        )

        message = response.choices[0].message

        # Если модель решила вызвать инструмент
        if message.tool_calls:
            for tool_call in message.tool_calls:
                result = await self._handle_tool_call(tool_call)

                messages.append(message.model_dump())
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result),
                })

            # Второй проход — уже с результатом инструмента
            second_response = await self.openai.chat.completions.create(
                model=OPENAI_MODEL,
                messages=messages,
            )
            return second_response.choices[0].message.content

        return message.content

    async def _handle_tool_call(self, tool_call):
        name = tool_call.function.name
        arguments = json.loads(tool_call.function.arguments)

        result = await self.session.call_tool(name, arguments)
        return result.content  # MCP возвращает structured payload

    async def close(self):
        if self.session:
            await self.session.__aexit__(None, None, None)
        if hasattr(self, "stdio_ctx"):
            await self.stdio_ctx.__aexit__(None, None, None)


async def main():
    agent = MCPAgent("server.py")  # твой MCP сервер
    await agent.connect_mcp()

    answer = await agent.run(
        "Проверь заказ 12345 и обнови его статус на DONE если есть ошибка ERROR42"
    )
    print(answer)

    await agent.close()


if __name__ == "__main__":
    asyncio.run(main())