from pydantic import BaseModel

class LlmResponse(BaseModel):
    tool_calls: list[str]