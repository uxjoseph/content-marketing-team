from __future__ import annotations

from abc import ABC, abstractmethod


class TextProvider(ABC):
    name: str = "base"

    @abstractmethod
    def is_available(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def generate(self, system_prompt: str, user_prompt: str, max_tokens: int = 1400) -> str:
        raise NotImplementedError
