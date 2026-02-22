from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, Field, field_validator, model_validator

DEFAULT_TARGETS = [
    "newsletter",
    "blog",
    "linkedin",
    "threads",
    "youtube-script",
    "shorts-scripts",
    "card-news",
    "thumbnail",
    "chart",
]
TARGET_OPTIONS = DEFAULT_TARGETS + ["shorts-videos"]
ALLOWED_TARGETS = set(DEFAULT_TARGETS) | {
    "shorts-videos",
    "visuals",
    "visual-card-news",
    "visual-thumbnail",
    "charts",
}
ALLOWED_STATUSES = {"PENDING", "RUNNING", "SUCCEEDED", "PARTIAL_SUCCESS", "FAILED", "CANCELED"}


class JobCreateRequest(BaseModel):
    source_markdown: str | None = None
    source_url: str | None = None
    targets: list[str] = Field(default_factory=lambda: DEFAULT_TARGETS.copy())
    tone: str = "친근하고 실용적"
    language: str = "ko"
    mock_mode: bool = False

    @model_validator(mode="after")
    def validate_source(self) -> "JobCreateRequest":
        markdown = (self.source_markdown or "").strip()
        url = (self.source_url or "").strip()
        if not markdown and not url:
            raise ValueError("source_markdown or source_url is required")
        if url and not url.startswith(("http://", "https://")):
            raise ValueError("source_url must start with http:// or https://")
        return self

    @field_validator("targets")
    @classmethod
    def validate_targets(cls, values: list[str]) -> list[str]:
        normalized = [value.strip().lower() for value in values if value.strip()]
        if not normalized:
            raise ValueError("at least one target is required")
        expanded: list[str] = []
        for value in normalized:
            if value == "visuals":
                expanded.extend(["card-news", "thumbnail"])
            elif value == "visual-card-news":
                expanded.append("card-news")
            elif value == "visual-thumbnail":
                expanded.append("thumbnail")
            elif value == "charts":
                expanded.append("chart")
            else:
                expanded.append(value)
        unknown = sorted(set(expanded) - ALLOWED_TARGETS)
        if unknown:
            raise ValueError(f"unsupported targets: {', '.join(unknown)}")
        deduped = list(dict.fromkeys(expanded))
        return deduped


class JobCreateResponse(BaseModel):
    job_id: str
    status: str
    created_at: dt.datetime


class JobDetailResponse(BaseModel):
    job_id: str
    status: str
    progress: int
    current_stage: str
    error_message: str | None
    retry_count: int
    created_at: dt.datetime
    started_at: dt.datetime | None
    finished_at: dt.datetime | None


class ArtifactItem(BaseModel):
    path: str
    type: str
    size: int


class ArtifactsResponse(BaseModel):
    artifacts: list[ArtifactItem]


class RetryResponse(BaseModel):
    job_id: str
    status: str
    retry_count: int


class CancelResponse(BaseModel):
    job_id: str
    status: str
