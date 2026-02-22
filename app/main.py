from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api import jobs_router, ui_router
from app.core.cleanup import prune_jobs_and_outputs
from app.core.config import Settings, get_settings
from app.core.db import create_db_and_tables, init_engine
from app.services.orchestrator import JobOrchestrator
from app.services.prompt_store import ensure_default_prompts
from app.workers.queue import JobQueue


def create_app(settings: Settings | None = None, enable_worker: bool = True) -> FastAPI:
    app_settings = settings or get_settings()
    job_queue = JobQueue(poll_seconds=app_settings.worker_poll_seconds)
    orchestrator = JobOrchestrator(app_settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        init_engine(app_settings.database_url)
        create_db_and_tables()
        ensure_default_prompts()
        prune_jobs_and_outputs(app_settings)
        app_settings.output_root_path.mkdir(parents=True, exist_ok=True)
        if enable_worker:
            job_queue.start(orchestrator.process_job)
        try:
            yield
        finally:
            job_queue.stop()

    app = FastAPI(title=app_settings.app_name, lifespan=lifespan)
    app.state.settings = app_settings
    app.state.job_queue = job_queue
    app.state.orchestrator = orchestrator

    static_dir = Path(__file__).resolve().parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    app.include_router(ui_router)
    app.include_router(jobs_router, prefix="/api")
    return app


app = create_app()
