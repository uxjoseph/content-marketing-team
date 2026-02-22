from __future__ import annotations

from app.domain.schemas import JobCreateRequest


def test_job_create_request_expands_legacy_visuals_target():
    payload = JobCreateRequest(
        source_markdown="# 제목\n\n본문",
        targets=["blog", "visuals", "charts"],
    )
    assert payload.targets == ["blog", "card-news", "thumbnail", "chart"]


def test_job_create_request_accepts_split_visual_targets():
    payload = JobCreateRequest(
        source_markdown="# 제목\n\n본문",
        targets=["card-news", "thumbnail", "chart"],
    )
    assert payload.targets == ["card-news", "thumbnail", "chart"]
