from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.db import session_scope
from app.domain.models import Job
from app.main import create_app


def _build_settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        output_root=str(tmp_path / "outputs"),
        openai_api_key="",
        anthropic_api_key="",
        nanobanana_api_key="",
        nanobanana_api_url="",
    )


def test_create_job_and_get_status(tmp_path: Path):
    app = create_app(settings=_build_settings(tmp_path), enable_worker=False)
    with TestClient(app) as client:
        response = client.post(
            "/api/jobs",
            json={
                "source_url": "https://example.com/article",
                "targets": ["blog"],
                "tone": "친근하고 실용적",
                "language": "ko",
                "mock_mode": True,
            },
        )
        assert response.status_code == 200
        payload = response.json()
        detail = client.get(f"/api/jobs/{payload['job_id']}")
        assert detail.status_code == 200
        assert detail.json()["status"] == "PENDING"


def test_retry_limit(tmp_path: Path):
    settings = _build_settings(tmp_path)
    app = create_app(settings=settings, enable_worker=False)
    with TestClient(app):
        with session_scope() as session:
            job = Job(
                source_url="https://example.com",
                targets=json.dumps(["blog"]),
                status="FAILED",
                retry_count=1,
            )
            session.add(job)
            session.commit()
            session.refresh(job)
            job_id = job.id

    with TestClient(app) as client:
        response = client.post(f"/api/jobs/{job_id}/retry")
        assert response.status_code == 400


def test_artifact_path_traversal_blocked(tmp_path: Path):
    settings = _build_settings(tmp_path)
    app = create_app(settings=settings, enable_worker=False)
    with TestClient(app):
        with session_scope() as session:
            job = Job(source_url="https://example.com", targets=json.dumps(["blog"]))
            session.add(job)
            session.commit()
            session.refresh(job)
            job_id = job.id

        job_root = Path(settings.output_root) / job_id
        job_root.mkdir(parents=True, exist_ok=True)
        (job_root / "brief.md").write_text("brief", encoding="utf-8")

    with TestClient(app) as client:
        response = client.get(f"/api/jobs/{job_id}/artifacts/%2E%2E%2Fsecret.txt")
        assert response.status_code in {400, 404}
