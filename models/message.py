from enum import Enum

class MessageRole(Enum):
    SYSTEM = "system"
    USER = "user"

class Message:
    role: MessageRole
    content: str