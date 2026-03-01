from enum import Enum
from typing import Any, Dict, Optional
from common.settings import settings
from pydantic import BaseModel

class ProviderType(Enum):
    LOCAL = "local"
    OPENROUTER = "openrouter"


class LlmConfig(BaseModel):
    provider: ProviderType = ProviderType.LOCAL

    model: str = settings.LLM_MODEL_NAME
    temperature: float = 0.0
    timeout: int = 60
    max_retries: int = 3

    api_key: Optional[str] = settings.LLM_API_KEY
    base_url: Optional[str] = settings.LLM_BASE_URL
    headers: Optional[Dict[str, Any]] = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
    
    ollama_host: Optional[str] = settings.OLLAMA_HOST
    ollama_chat: Optional[str] = settings.OLLAMA_CHAT
