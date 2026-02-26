
# clients/mcp_client.py
import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

class MCPClient:
    def __init__(self, server_script_path: str):
        self.server_params = StdioServerParameters(
            command="python",
            args=[server_script_path]   # путь к server.py
        )
        self.session = None

    async def __aenter__(self):
        reader, writer = await stdio_client(self.server_params).__aenter__()
        self.session = await ClientSession(reader, writer).__aenter__()
        await self.session.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.session.__aexit__(exc_type, exc_val, exc_tb)

    async def call_tool(self, tool_name: str, arguments: dict):
        """Вызывает инструмент по имени с переданными аргументами."""
        result = await self.session.call_tool(tool_name, arguments)
        # result.content содержит список TextContent или других типов
        # В данном случае все инструменты возвращают текст (JSON)
        if result.content and result.content[0].type == "text":
            import json
            return json.loads(result.content[0].text)
        else:
            raise ValueError(f"Unexpected response from tool {tool_name}: {result}")