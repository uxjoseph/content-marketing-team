from __future__ import annotations

import httpx

from app.core.config import Settings
from app.services.providers.base import TextProvider


class OpenAIProvider(TextProvider):
    name = "openai"
    api_url = "https://api.openai.com/v1/chat/completions"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def is_available(self) -> bool:
        return bool(self.settings.openai_api_key)

    def generate(self, system_prompt: str, user_prompt: str, max_tokens: int = 1400) -> str:
        if not self.is_available():
            raise RuntimeError("OPENAI_API_KEY is missing.")
        payload = {
            "model": self.settings.openai_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.6,
            "max_tokens": max_tokens,
        }
        headers = {"Authorization": f"Bearer {self.settings.openai_api_key}"}
        with httpx.Client(timeout=self.settings.request_timeout_seconds) as client:
            response = client.post(self.api_url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
        content = data["choices"][0]["message"]["content"]
        if isinstance(content, list):
            return "\n".join(str(item.get("text", "")) for item in content)
        return str(content)
