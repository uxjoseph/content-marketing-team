from __future__ import annotations

import datetime as dt
import shutil
from pathlib import Path

from sqlmodel import select

from app.core.config import Settings
from app.core.db import session_scope
from app.domain.models import Job


def _delete_output_dir(root: Path, job_id: str) -> None:
    target = (root / job_id).resolve()
    if target.exists() and target.is_dir():
        shutil.rmtree(target, ignore_errors=True)


def prune_jobs_and_outputs(settings: Settings) -> None:
    root = settings.output_root_path
    root.mkdir(parents=True, exist_ok=True)
    cutoff = dt.datetime.utcnow() - dt.timedelta(days=settings.retention_days)

    with session_scope() as session:
        jobs = session.exec(select(Job).order_by(Job.created_at.asc())).all()

        stale_by_age = [job for job in jobs if _to_utc_naive(job.created_at) < cutoff]
        for job in stale_by_age:
            _delete_output_dir(root, job.id)
            session.delete(job)

        session.commit()

        fresh_jobs = session.exec(select(Job).order_by(Job.created_at.desc())).all()
        for stale in fresh_jobs[settings.max_jobs :]:
            _delete_output_dir(root, stale.id)
            session.delete(stale)

        session.commit()


def _to_utc_naive(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is not None:
        return value.astimezone(dt.timezone.utc).replace(tzinfo=None)
    return value
