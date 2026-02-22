from __future__ import annotations

import json
from pathlib import Path

from app.core.config import Settings
from app.core.db import create_db_and_tables, init_engine, session_scope
from app.domain.models import Job, PromptTemplate
from app.services.ingestion import IngestionResult
from app.services.orchestrator import JobOrchestrator
from app.services.prompt_store import ensure_default_prompts


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'brief_prompt.db'}",
        output_root=str(tmp_path / "outputs"),
    )


def test_brief_template_from_db_controls_generated_brief(tmp_path: Path, monkeypatch):
    settings = _settings(tmp_path)
    init_engine(settings.database_url)
    create_db_and_tables()
    ensure_default_prompts()

    with session_scope() as session:
        prompt = session.get(PromptTemplate, "planner.brief-template")
        assert prompt is not None
        prompt.content = (
            "# CUSTOM BRIEF\n"
            "source={source_ref}\n"
            "title={title}\n"
            "keys:\n{key_lines}\n"
        )
        session.add(prompt)
        session.commit()

        job = Job(
            source_url="markdown://# 제목\n\n본문입니다.",
            targets=json.dumps(["blog"]),
            mock_mode=True,
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        job_id = job.id

    orchestrator = JobOrchestrator(settings)

    def fake_ingest(*_args, **_kwargs):
        return IngestionResult(
            source_type="markdown",
            title="테스트 제목",
            text="첫 문장입니다. 둘째 문장입니다. 셋째 문장입니다.",
            metadata={"source_ref": "markdown input"},
        )

    def fake_text_assets(**_kwargs):
        out_dir = Path(_kwargs["output_dir"])
        path = out_dir / "blog.md"
        path.write_text("# blog", encoding="utf-8")
        return [str(path.relative_to(out_dir))], []

    def fake_reviewer(output_dir, _targets, _failures, _warnings):
        report = output_dir / "review-report.md"
        report.write_text("# review-report.md", encoding="utf-8")
        return report, []

    monkeypatch.setattr("app.services.orchestrator.ingest_source", fake_ingest)
    monkeypatch.setattr(orchestrator.text_agents, "generate_text_assets", fake_text_assets)
    monkeypatch.setattr(orchestrator, "_run_reviewer", fake_reviewer)
    orchestrator.process_job(job_id)

    brief_path = Path(settings.output_root) / job_id / "brief.md"
    brief = brief_path.read_text(encoding="utf-8")
    assert brief.startswith("# CUSTOM BRIEF")
    assert "title=테스트 제목" in brief
    assert "keys:" in brief
