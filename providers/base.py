from __future__ import annotations
import abc
from typing import Any, Dict, List, Tuple

class BaseLLMProvider(abc.ABC):
    @abc.abstractmethod
    async def acall(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        *,
        timeout: int,
    ) -> Tuple[str, List[Dict[str, Any]]]:
        raise NotImplementedError
