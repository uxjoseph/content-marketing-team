from __future__ import annotations

import json
from pathlib import Path

from app.core.cleanup import prune_jobs_and_outputs
from app.core.config import Settings
from app.core.db import create_db_and_tables, init_engine, session_scope
from app.domain.models import Job
from app.services.ingestion import IngestionResult
from app.services.orchestrator import JobOrchestrator
from sqlmodel import select


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'orchestrator.db'}",
        output_root=str(tmp_path / "outputs"),
        openai_api_key="",
        anthropic_api_key="",
        nanobanana_api_key="",
        nanobanana_api_url="",
    )


def test_orchestrator_success_with_real_reviewer(tmp_path: Path):
    settings = _settings(tmp_path)
    init_engine(settings.database_url)
    create_db_and_tables()
    orchestrator = JobOrchestrator(settings)

    with session_scope() as session:
        job = Job(
            source_url="https://example.com/article",
            targets=json.dumps(["blog"]),
            mock_mode=True,
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        job_id = job.id

    orchestrator.process_job(job_id)

    with session_scope() as session:
        current = session.get(Job, job_id)
        assert current is not None
        assert current.status == "SUCCEEDED"
        assert current.error_message is None
    report_path = Path(settings.output_root) / job_id / "review-report.md"
    assert report_path.exists()


def test_orchestrator_does_not_duplicate_failures(tmp_path: Path, monkeypatch):
    settings = _settings(tmp_path)
    init_engine(settings.database_url)
    create_db_and_tables()
    orchestrator = JobOrchestrator(settings)

    with session_scope() as session:
        job = Job(
            source_url="https://example.com/article",
            targets=json.dumps(["blog", "visuals"]),
            mock_mode=False,
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        job_id = job.id

    def fake_ingest(*_args, **_kwargs):
        return IngestionResult(source_type="web", title="test", text="sample source text" * 100)

    def fail_visuals(*_args, **_kwargs):
        raise RuntimeError("visual provider down")

    monkeypatch.setattr("app.services.orchestrator.ingest_source", fake_ingest)
    monkeypatch.setattr(orchestrator.visuals, "generate_assets", fail_visuals)
    orchestrator.process_job(job_id)

    with session_scope() as session:
        current = session.get(Job, job_id)
        assert current is not None
        assert current.status == "PARTIAL_SUCCESS"
        assert (current.error_message or "").count("VISUAL 실패") == 1


def test_orchestrator_skips_shorts_for_non_video_source(tmp_path: Path, monkeypatch):
    settings = _settings(tmp_path)
    init_engine(settings.database_url)
    create_db_and_tables()
    orchestrator = JobOrchestrator(settings)

    with session_scope() as session:
        job = Job(
            source_url="https://example.com/article",
            targets=json.dumps(["blog", "shorts-videos"]),
            mock_mode=False,
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        job_id = job.id

    def fake_ingest(*_args, **_kwargs):
        return IngestionResult(source_type="web", title="web", text="sample source text" * 100, video_path=None)

    monkeypatch.setattr("app.services.orchestrator.ingest_source", fake_ingest)
    orchestrator.process_job(job_id)

    with session_scope() as session:
        current = session.get(Job, job_id)
        assert current is not None
        assert current.status == "SUCCEEDED"
        assert "shorts-videos 생성을 건너뛰었습니다" in (
            (Path(settings.output_root) / job_id / "review-report.md").read_text(encoding="utf-8")
        )


def test_orchestrator_generates_chart_artifacts(tmp_path: Path):
    settings = _settings(tmp_path)
    init_engine(settings.database_url)
    create_db_and_tables()
    orchestrator = JobOrchestrator(settings)

    with session_scope() as session:
        job = Job(
            source_url="markdown://# 수요 예측\n\n- 광고 전환율이 상승했습니다.\n- CAC가 하락했습니다.",
            targets=json.dumps(["chart"]),
            mock_mode=True,
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        job_id = job.id

    orchestrator.process_job(job_id)

    root = Path(settings.output_root) / job_id
    assert (root / "charts" / "overview.png").exists()
    assert (root / "charts" / "trend.png").exists()

    with session_scope() as session:
        current = session.get(Job, job_id)
        assert current is not None
        assert current.status == "SUCCEEDED"


def test_cleanup_handles_naive_and_aware_datetimes(tmp_path: Path):
    settings = _settings(tmp_path)
    init_engine(settings.database_url)
    create_db_and_tables()

    with session_scope() as session:
        old_job_aware = Job(
            source_url="https://example.com/old",
            targets=json.dumps(["blog"]),
        )
        old_job_aware.created_at = old_job_aware.created_at.replace(year=2000)
        old_job_naive = Job(
            source_url="https://example.com/old-naive",
            targets=json.dumps(["blog"]),
        )
        old_job_naive.created_at = old_job_naive.created_at.replace(year=2001, tzinfo=None)
        session.add(old_job_aware)
        session.add(old_job_naive)
        session.commit()

    prune_jobs_and_outputs(settings)

    with session_scope() as session:
        remaining = session.exec(select(Job)).all()
        assert remaining == []
