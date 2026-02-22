from __future__ import annotations

import datetime as dt
from uuid import uuid4

from sqlmodel import Field, SQLModel


class Job(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True, index=True)
    source_url: str
    targets: str = Field(default="[]")
    tone: str = Field(default="친근하고 실용적")
    language: str = Field(default="ko")
    mock_mode: bool = Field(default=False)

    status: str = Field(default="PENDING", index=True)
    current_stage: str = Field(default="QUEUED")
    progress: int = Field(default=0)
    error_message: str | None = None
    retry_count: int = Field(default=0)
    cancel_requested: bool = Field(default=False)

    created_at: dt.datetime = Field(default_factory=lambda: dt.datetime.now(dt.timezone.utc), index=True)
    started_at: dt.datetime | None = None
    finished_at: dt.datetime | None = None


class PromptTemplate(SQLModel, table=True):
    key: str = Field(primary_key=True, index=True)
    label: str
    content: str
    created_at: dt.datetime = Field(default_factory=lambda: dt.datetime.now(dt.timezone.utc))
    updated_at: dt.datetime = Field(default_factory=lambda: dt.datetime.now(dt.timezone.utc))


class PromptVariable(SQLModel, table=True):
    prompt_key: str = Field(primary_key=True, index=True)
    name: str = Field(primary_key=True)
    value_type: str = Field(default="INPUT_REQUIRED")
    default_value: str = Field(default="")
    description: str = Field(default="")
    ai_instruction: str = Field(default="")
    sort_order: int = Field(default=0)
    created_at: dt.datetime = Field(default_factory=lambda: dt.datetime.now(dt.timezone.utc))
    updated_at: dt.datetime = Field(default_factory=lambda: dt.datetime.now(dt.timezone.utc))
