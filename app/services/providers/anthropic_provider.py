from __future__ import annotations

import httpx

from app.core.config import Settings
from app.services.providers.base import TextProvider


class AnthropicProvider(TextProvider):
    name = "anthropic"
    api_url = "https://api.anthropic.com/v1/messages"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def is_available(self) -> bool:
        return bool(self.settings.anthropic_api_key)

    def generate(self, system_prompt: str, user_prompt: str, max_tokens: int = 1400) -> str:
        if not self.is_available():
            raise RuntimeError("ANTHROPIC_API_KEY is missing.")
        payload = {
            "model": self.settings.anthropic_model,
            "max_tokens": max_tokens,
            "temperature": 0.6,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
        }
        headers = {
            "x-api-key": self.settings.anthropic_api_key,
            "anthropic-version": "2023-06-01",
        }
        with httpx.Client(timeout=self.settings.request_timeout_seconds) as client:
            response = client.post(self.api_url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
        chunks = data.get("content", [])
        return "\n".join(chunk.get("text", "") for chunk in chunks if chunk.get("type") == "text")
