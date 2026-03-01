from enum import Enum

class MessageRole(Enum):
    SYSTEM = "system"
    USER = "user"

class Message:
    def __init__(self, role: MessageRole, content: str):
        self.role = role
        self.content = content
