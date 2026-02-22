from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlmodel import Session

from app.core.db import get_session
from app.domain.models import Job
from app.domain.schemas import (
    ArtifactItem,
    ArtifactsResponse,
    CancelResponse,
    JobCreateRequest,
    JobCreateResponse,
    JobDetailResponse,
    RetryResponse,
)

router = APIRouter(tags=["jobs"])
ALLOWED_EXTENSIONS = {".md", ".png", ".jpg", ".jpeg", ".mp4", ".json"}
MARKDOWN_PREFIX = "markdown://"


@router.post("/jobs", response_model=JobCreateResponse)
def create_job(
    payload: JobCreateRequest,
    request: Request,
    session: Session = Depends(get_session),
) -> JobCreateResponse:
    if payload.source_markdown and payload.source_markdown.strip():
        source_value = f"{MARKDOWN_PREFIX}{payload.source_markdown.strip()}"
    else:
        source_value = (payload.source_url or "").strip()
    job = Job(
        source_url=source_value,
        targets=json.dumps(payload.targets, ensure_ascii=False),
        tone=payload.tone,
        language=payload.language,
        mock_mode=payload.mock_mode,
        status="PENDING",
        current_stage="QUEUED",
        progress=0,
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    request.app.state.job_queue.enqueue(job.id)
    return JobCreateResponse(job_id=job.id, status=job.status, created_at=job.created_at)


@router.get("/jobs/{job_id}", response_model=JobDetailResponse)
def get_job(job_id: str, session: Session = Depends(get_session)) -> JobDetailResponse:
    job = session.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return _job_to_detail(job)


@router.get("/jobs/{job_id}/artifacts", response_model=ArtifactsResponse)
def list_artifacts(job_id: str, request: Request, session: Session = Depends(get_session)) -> ArtifactsResponse:
    job = session.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    output_root: Path = request.app.state.settings.output_root_path
    job_root = output_root / job_id
    if not job_root.exists():
        return ArtifactsResponse(artifacts=[])

    artifacts: list[ArtifactItem] = []
    for item in sorted(job_root.rglob("*")):
        if not item.is_file():
            continue
        rel = item.relative_to(job_root).as_posix()
        artifacts.append(
            ArtifactItem(
                path=rel,
                type=_artifact_type(item),
                size=item.stat().st_size,
            )
        )
    return ArtifactsResponse(artifacts=artifacts)


@router.get("/jobs/{job_id}/artifacts/{artifact_path:path}")
def download_artifact(
    job_id: str,
    artifact_path: str,
    request: Request,
    session: Session = Depends(get_session),
):
    job = session.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    safe_path = _resolve_artifact_path(request.app.state.settings.output_root_path, job_id, artifact_path)
    return FileResponse(path=safe_path, filename=safe_path.name)


@router.post("/jobs/{job_id}/retry", response_model=RetryResponse)
def retry_job(job_id: str, request: Request, session: Session = Depends(get_session)) -> RetryResponse:
    job = session.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    if job.status not in {"FAILED", "PARTIAL_SUCCESS"}:
        raise HTTPException(status_code=400, detail="only failed or partial jobs can be retried")
    if job.retry_count >= 1:
        raise HTTPException(status_code=400, detail="retry limit reached")
    job.retry_count += 1
    job.status = "PENDING"
    job.current_stage = "QUEUED"
    job.progress = 0
    job.error_message = None
    job.started_at = None
    job.finished_at = None
    job.cancel_requested = False
    session.add(job)
    session.commit()
    request.app.state.job_queue.enqueue(job.id)
    return RetryResponse(job_id=job.id, status=job.status, retry_count=job.retry_count)


@router.post("/jobs/{job_id}/cancel", response_model=CancelResponse)
def cancel_job(job_id: str, session: Session = Depends(get_session)) -> CancelResponse:
    job = session.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    if job.status in {"SUCCEEDED", "FAILED", "PARTIAL_SUCCESS", "CANCELED"}:
        return CancelResponse(job_id=job.id, status=job.status)
    job.cancel_requested = True
    session.add(job)
    session.commit()
    return CancelResponse(job_id=job.id, status="CANCELED")


def _resolve_artifact_path(output_root: Path, job_id: str, artifact_path: str) -> Path:
    job_root = (output_root / job_id).resolve()
    candidate = (job_root / artifact_path).resolve()
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="artifact not found")
    if job_root not in candidate.parents and candidate != job_root:
        raise HTTPException(status_code=400, detail="invalid artifact path")
    if candidate.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="unsupported artifact extension")
    return candidate


def _artifact_type(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == ".md":
        return "MARKDOWN"
    if ext in {".png", ".jpg", ".jpeg"}:
        return "IMAGE"
    if ext == ".mp4":
        return "VIDEO"
    return "FILE"


def _job_to_detail(job: Job) -> JobDetailResponse:
    return JobDetailResponse(
        job_id=job.id,
        status=job.status,
        progress=job.progress,
        current_stage=job.current_stage,
        error_message=job.error_message,
        retry_count=job.retry_count,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )
