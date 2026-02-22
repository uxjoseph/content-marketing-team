from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Marketing Multi-Agent PoC"
    database_url: str = "sqlite:///./marketing_poc.db"
    output_root: str = "/Users/limchaesung/Github/team-auruda/content-marketing-team/outputs"
    retention_days: int = 7
    max_jobs: int = 200
    worker_poll_seconds: float = 0.5

    default_language: str = "ko"
    default_tone: str = "친근하고 실용적"
    default_targets: str = (
        "newsletter,blog,linkedin,threads,youtube-script,shorts-scripts,card-news,thumbnail,chart"
    )

    llm_provider: str = "openai"
    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-3-5-sonnet-latest"

    nanobanana_api_url: str = ""
    nanobanana_api_key: str = ""
    nanobanana_model: str = "gemini-3-pro-image-preview"

    whisper_model: str = "small"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    request_timeout_seconds: int = 120

    @property
    def output_root_path(self) -> Path:
        return Path(self.output_root).expanduser().resolve()

    @property
    def default_targets_list(self) -> list[str]:
        mapped: list[str] = []
        for raw in self.default_targets.split(","):
            item = raw.strip().lower()
            if not item:
                continue
            if item == "visuals":
                mapped.extend(["card-news", "thumbnail"])
                continue
            if item == "visual-card-news":
                mapped.append("card-news")
                continue
            if item == "visual-thumbnail":
                mapped.append("thumbnail")
                continue
            if item == "charts":
                mapped.append("chart")
                continue
            mapped.append(item)
        return list(dict.fromkeys(mapped))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
