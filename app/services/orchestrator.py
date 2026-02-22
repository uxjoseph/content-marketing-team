from __future__ import annotations

import datetime as dt
import json
import re
import textwrap
from pathlib import Path

from PIL import Image

from app.core.config import Settings
from app.core.db import session_scope
from app.domain.models import Job
from app.services.agents import TextAgentService
from app.services.charting import ChartAssetService
from app.services.ingestion import IngestionResult, ingest_source
from app.services.providers.nanobanana_provider import NanobananaProvider
from app.services.prompt_store import (
    load_prompt_map,
    load_prompt_variable_map,
    resolve_prompt_variable_values,
)
from app.services.shorts import ShortsVideoService


class JobOrchestrator:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.text_agents = TextAgentService(settings)
        self.visuals = NanobananaProvider(settings)
        self.charts = ChartAssetService(settings)
        self.shorts = ShortsVideoService()

    def process_job(self, job_id: str) -> None:
        now = dt.datetime.now(dt.timezone.utc)
        self._update_job(
            job_id,
            status="RUNNING",
            current_stage="INGESTION",
            progress=5,
            started_at=now,
            error_message=None,
        )
        output_dir = self.settings.output_root_path / job_id
        output_dir.mkdir(parents=True, exist_ok=True)
        tmp_dir = output_dir / "_tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)

        job = self._get_job(job_id)
        if job is None:
            return
        if self._cancel_if_requested(job_id):
            return

        targets = _json_list(job.targets)
        effective_targets = _normalize_targets(targets)
        failures: list[str] = []
        warnings: list[str] = []
        artifacts: list[str] = []

        try:
            ingestion = ingest_source(job.source_url, tmp_dir, self.settings, mock_mode=job.mock_mode)
            warnings.extend(ingestion.warnings)
        except Exception as exc:
            self._fail_job(job_id, f"INGESTION 실패: {exc}")
            return

        # Web source may not have a downloadable source video. Skip shorts gracefully.
        if "shorts-videos" in effective_targets and ingestion.video_path is None and not job.mock_mode:
            effective_targets = [target for target in effective_targets if target != "shorts-videos"]
            warnings.append("입력 소스에 원본 영상이 없어 shorts-videos 생성을 건너뛰었습니다.")

        if self._cancel_if_requested(job_id):
            return
        self._update_job(job_id, current_stage="PLANNER", progress=20)

        try:
            brief_text = self._build_brief(job, ingestion, effective_targets, warnings)
            brief_path = output_dir / "brief.md"
            brief_path.write_text(brief_text, encoding="utf-8")
            artifacts.append(str(brief_path.relative_to(output_dir)))
        except Exception as exc:
            self._fail_job(job_id, f"PLANNER 실패: {exc}")
            return

        if self._cancel_if_requested(job_id):
            return
        self._update_job(job_id, current_stage="TEXT_AGENTS", progress=40)

        try:
            text_artifacts, text_failures = self.text_agents.generate_text_assets(
                brief_text=brief_text,
                source_text=ingestion.text,
                output_dir=output_dir,
                targets=effective_targets,
                tone=job.tone,
                language=job.language,
                mock_mode=job.mock_mode,
            )
            artifacts.extend(text_artifacts)
            failures.extend(text_failures)
        except Exception as exc:
            failures.append(f"TEXT_AGENTS 실패: {exc}")

        if self._cancel_if_requested(job_id):
            return
        self._update_job(job_id, current_stage="VISUAL", progress=60)

        if "card-news" in effective_targets or "thumbnail" in effective_targets:
            try:
                visual_artifacts, visual_warnings = self.visuals.generate_assets(
                    brief_text=brief_text,
                    output_dir=output_dir,
                    mock_mode=job.mock_mode,
                    generate_card_news="card-news" in effective_targets,
                    generate_thumbnail="thumbnail" in effective_targets,
                )
                artifacts.extend(visual_artifacts)
                warnings.extend(visual_warnings)
            except Exception as exc:
                failures.append(f"VISUAL 실패: {exc}")

        if self._cancel_if_requested(job_id):
            return
        self._update_job(job_id, current_stage="CHART", progress=72)

        if "chart" in effective_targets:
            try:
                chart_artifacts, chart_warnings = self.charts.generate_assets(
                    brief_text=brief_text,
                    output_dir=output_dir,
                    mock_mode=job.mock_mode,
                )
                artifacts.extend(chart_artifacts)
                warnings.extend(chart_warnings)
            except Exception as exc:
                failures.append(f"CHART 실패: {exc}")

        if self._cancel_if_requested(job_id):
            return
        self._update_job(job_id, current_stage="SHORTS", progress=82)

        if "shorts-videos" in effective_targets:
            try:
                shorts_artifacts, shorts_warnings = self.shorts.generate_assets(
                    source_url=job.source_url,
                    video_path=ingestion.video_path,
                    scripts_dir=output_dir / "shorts-scripts",
                    output_dir=output_dir,
                    settings=self.settings,
                    mock_mode=job.mock_mode,
                    clip_count=3,
                )
                artifacts.extend(shorts_artifacts)
                warnings.extend(shorts_warnings)
            except Exception as exc:
                failures.append(f"SHORTS 실패: {exc}")

        if self._cancel_if_requested(job_id):
            return
        self._update_job(job_id, current_stage="REVIEW", progress=92)

        review_path, review_failures = self._run_reviewer(output_dir, effective_targets, failures, warnings)
        artifacts.append(str(review_path.relative_to(output_dir)))
        failures.extend(review_failures)

        final_status = "PARTIAL_SUCCESS" if failures else "SUCCEEDED"
        error_message = "\n".join(failures[:20]) if failures else None
        self._update_job(
            job_id,
            status=final_status,
            current_stage="DONE",
            progress=100,
            error_message=error_message,
            finished_at=dt.datetime.now(dt.timezone.utc),
        )

    def _build_brief(self, job: Job, ingestion: IngestionResult, targets: list[str], warnings: list[str]) -> str:
        key_messages = _extract_key_messages(ingestion.title, ingestion.text, 5)
        warning_lines = "\n".join(f"- {item}" for item in warnings) if warnings else "- 없음"
        target_lines = "\n".join(f"- {target}" for target in targets) if targets else "- 없음"
        key_lines = "\n".join(f"- {item}" for item in key_messages)
        source_preview = textwrap.shorten(ingestion.text.replace("\n", " "), width=1200, placeholder="...")
        source_ref = ingestion.metadata.get("url") or ingestion.metadata.get("source_ref") or "local source"
        base_values = {
            "source_ref": source_ref,
            "source_type": ingestion.source_type,
            "title": ingestion.title,
            "language": job.language,
            "tone": job.tone,
            "target_lines": target_lines,
            "key_lines": key_lines,
            "warning_lines": warning_lines,
            "source_preview": source_preview,
        }

        variable_map = load_prompt_variable_map()
        variable_configs = variable_map.get("planner.brief-template", [])
        resolved_values = resolve_prompt_variable_values(
            prompt_key="planner.brief-template",
            runtime_values=base_values,
            variable_map=variable_map,
        )
        ai_values = self._resolve_brief_ai_variables(
            job=job,
            ingestion=ingestion,
            targets=targets,
            warnings=warnings,
            key_messages=key_messages,
            variable_configs=variable_configs,
            fallback_values=resolved_values,
        )
        resolved_values.update(ai_values)
        template = load_prompt_map().get("planner.brief-template", _brief_template_fallback())
        return _render_prompt_template(template, resolved_values)

    def _resolve_brief_ai_variables(
        self,
        *,
        job: Job,
        ingestion: IngestionResult,
        targets: list[str],
        warnings: list[str],
        key_messages: list[str],
        variable_configs: list[dict[str, object]],
        fallback_values: dict[str, str],
    ) -> dict[str, str]:
        ai_variables = [
            item
            for item in variable_configs
            if str(item.get("value_type", "")).strip().upper() == "AI_GENERATED"
        ]
        if not ai_variables:
            return {}

        fallback: dict[str, str] = {}
        for item in ai_variables:
            name = str(item.get("name", "")).strip()
            if not name:
                continue
            fallback[name] = str(fallback_values.get(name, "")).strip() or str(
                item.get("default_value", "")
            ).strip()
        if not fallback:
            return {}
        if job.mock_mode:
            return fallback

        provider = next((candidate for candidate in self.text_agents.providers if candidate.is_available()), None)
        if provider is None:
            return fallback

        variable_lines = []
        for item in ai_variables:
            name = str(item.get("name", "")).strip()
            if not name:
                continue
            description = str(item.get("description", "")).strip() or "-"
            ai_instruction = str(item.get("ai_instruction", "")).strip() or "-"
            default_value = str(item.get("default_value", "")).strip() or "-"
            variable_lines.append(
                f"- {name}: description={description}; ai_instruction={ai_instruction}; default={default_value}"
            )
        if not variable_lines:
            return fallback

        source_excerpt = textwrap.shorten(
            ingestion.text.replace("\n", " "),
            width=5200,
            placeholder="...",
        )
        targets_text = ", ".join(targets) if targets else "없음"
        warnings_text = "\n".join(f"- {warning}" for warning in warnings) if warnings else "- 없음"
        key_messages_text = "\n".join(f"- {item}" for item in key_messages) if key_messages else "- 없음"

        system_prompt = (
            "You generate variables for a markdown template. "
            "Return only a JSON object. Never include markdown code fences."
        )
        user_prompt = (
            "[목표]\n"
            "brief.md 템플릿의 AI 생성형 변수 값을 채운다.\n\n"
            "[변수 정의]\n"
            f"{chr(10).join(variable_lines)}\n\n"
            "[입력 컨텍스트]\n"
            f"- source_ref: {fallback_values.get('source_ref', '')}\n"
            f"- source_type: {fallback_values.get('source_type', '')}\n"
            f"- title: {fallback_values.get('title', '')}\n"
            f"- language: {fallback_values.get('language', '')}\n"
            f"- tone: {fallback_values.get('tone', '')}\n"
            f"- targets: {targets_text}\n"
            f"- warnings:\n{warnings_text}\n"
            f"- key_candidates:\n{key_messages_text}\n\n"
            "[원문 발췌]\n"
            f"{source_excerpt}\n\n"
            "[출력 규칙]\n"
            "- 반드시 JSON 객체 1개만 출력한다.\n"
            "- 키는 변수 정의에 있는 name만 사용한다.\n"
            "- *_lines 변수는 각 줄이 '- '로 시작하는 Markdown bullet 문자열로 출력한다.\n"
            "- source_preview는 4~6문장 한국어 요약으로 작성한다.\n"
            "- 프롬프트 지시나 메타 문장을 출력하지 않는다."
        )

        try:
            raw = provider.generate(system_prompt, user_prompt, max_tokens=900)
            parsed = _parse_json_object(raw)
            if parsed is None:
                return fallback
            merged = dict(fallback)
            for name in fallback.keys():
                candidate = parsed.get(name)
                if isinstance(candidate, str) and candidate.strip():
                    merged[name] = candidate.strip()
            return merged
        except Exception:
            return fallback

    def _run_reviewer(
        self,
        output_dir: Path,
        targets: list[str],
        failures: list[str],
        warnings: list[str],
    ) -> tuple[Path, list[str]]:
        review_failures: list[str] = []
        report_lines = ["# review-report.md", ""]
        report_lines.append("## 상태 요약")
        report_lines.append(f"- 현재 실패 수: {len(failures)}")
        report_lines.append(f"- 경고 수: {len(warnings)}")
        report_lines.append("")
        report_lines.append("## 필수 산출물 검증")

        required = _required_paths_for_targets(targets)
        for rel in required:
            full = output_dir / rel
            if full.exists():
                report_lines.append(f"- [OK] {rel}")
            else:
                report_lines.append(f"- [FAIL] {rel}")
                review_failures.append(f"missing artifact: {rel}")

        visuals_dir = output_dir / "visuals"
        if ("card-news" in targets or "thumbnail" in targets) and visuals_dir.exists():
            if "thumbnail" in targets:
                thumb = visuals_dir / "thumbnail.png"
                if thumb.exists():
                    with Image.open(thumb) as img:
                        if img.size != (1280, 720):
                            review_failures.append("thumbnail resolution mismatch (expected 1280x720)")
                            report_lines.append(f"- [FAIL] thumbnail size is {img.size}")
                        else:
                            report_lines.append("- [OK] thumbnail is 1280x720")
                else:
                    review_failures.append("missing artifact: visuals/thumbnail.png")
                    report_lines.append("- [FAIL] missing thumbnail.png")
            if "card-news" in targets:
                card_news = sorted((visuals_dir / "card-news").glob("slide-*.png"))
                if not (5 <= len(card_news) <= 7):
                    review_failures.append(f"card-news slide count mismatch ({len(card_news)})")
                    report_lines.append(f"- [FAIL] card-news slide count={len(card_news)}")
                else:
                    report_lines.append(f"- [OK] card-news slide count={len(card_news)}")

        charts_dir = output_dir / "charts"
        if "chart" in targets and charts_dir.exists():
            chart_files = sorted(charts_dir.glob("*.png"))
            if len(chart_files) < 2:
                review_failures.append(f"charts count mismatch ({len(chart_files)})")
                report_lines.append(f"- [FAIL] charts count={len(chart_files)}")
            else:
                report_lines.append(f"- [OK] charts count={len(chart_files)}")
            for chart in chart_files:
                with Image.open(chart) as img:
                    if img.size != (1280, 720):
                        review_failures.append(f"{chart.name} resolution mismatch (expected 1280x720)")
                        report_lines.append(f"- [FAIL] {chart.name} size is {img.size}")
                    else:
                        report_lines.append(f"- [OK] {chart.name} is 1280x720")

        shorts_dir = output_dir / "shorts-videos"
        if "shorts-videos" in targets and shorts_dir.exists():
            for video_path in sorted(shorts_dir.glob("shorts-*.mp4")):
                probed = self.shorts.probe_video(video_path)
                if probed is None:
                    report_lines.append(f"- [WARN] ffprobe unavailable or failed: {video_path.name}")
                    continue
                width, height, duration = probed
                if not (height > width and width >= 720):
                    review_failures.append(f"{video_path.name} is not vertical video")
                    report_lines.append(f"- [FAIL] {video_path.name} resolution={width}x{height}")
                elif duration > 60.5:
                    review_failures.append(f"{video_path.name} duration exceeds 60s")
                    report_lines.append(f"- [FAIL] {video_path.name} duration={duration:.2f}")
                else:
                    report_lines.append(
                        f"- [OK] {video_path.name} {width}x{height}, duration={duration:.2f}s"
                    )

        if warnings:
            report_lines.append("")
            report_lines.append("## 경고")
            for warning in warnings:
                report_lines.append(f"- {warning}")

        if failures or review_failures:
            report_lines.append("")
            report_lines.append("## 실패/누락")
            for failure in [*failures, *review_failures]:
                report_lines.append(f"- {failure}")

        report_path = output_dir / "review-report.md"
        report_path.write_text("\n".join(report_lines), encoding="utf-8")
        return report_path, review_failures

    def _cancel_if_requested(self, job_id: str) -> bool:
        with session_scope() as session:
            job = session.get(Job, job_id)
            if job is None:
                return True
            if not job.cancel_requested:
                return False
            job.status = "CANCELED"
            job.current_stage = "DONE"
            job.progress = 100
            job.finished_at = dt.datetime.now(dt.timezone.utc)
            session.add(job)
            session.commit()
            return True

    def _get_job(self, job_id: str) -> Job | None:
        with session_scope() as session:
            return session.get(Job, job_id)

    def _update_job(self, job_id: str, **fields) -> None:
        with session_scope() as session:
            job = session.get(Job, job_id)
            if job is None:
                return
            for key, value in fields.items():
                setattr(job, key, value)
            session.add(job)
            session.commit()

    def _fail_job(self, job_id: str, message: str) -> None:
        self._update_job(
            job_id,
            status="FAILED",
            current_stage="DONE",
            progress=100,
            error_message=message,
            finished_at=dt.datetime.now(dt.timezone.utc),
        )


_META_PATTERNS = (
    "instagram card-news",
    "responsemodalities",
    "generationconfig",
    "\"model\"",
    "prompt",
    "thumbnail",
    "last slide",
    "cta",
    "output format",
    "system instruction",
)

_PRIORITY_TERMS = (
    "핵심",
    "전략",
    "시장",
    "고객",
    "매출",
    "성과",
    "전환",
    "효율",
    "비용",
    "리스크",
    "자동화",
    "성장",
    "수익",
    "개선",
)

_TITLE_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "about",
    "this",
    "that",
    "guide",
    "news",
    "update",
    "분석",
    "가이드",
    "정리",
    "리포트",
    "콘텐츠",
    "마케팅",
}


def _extract_key_messages(title: str, text: str, count: int) -> list[str]:
    candidates = _collect_candidates(text)
    title_keywords = _title_keywords(title)
    scored: list[tuple[int, int, str]] = []
    for idx, candidate in enumerate(candidates):
        score = _score_candidate(candidate, title_keywords)
        if score <= 0:
            continue
        scored.append((score, idx, candidate))
    scored.sort(key=lambda item: (-item[0], item[1]))

    selected: list[str] = []
    used = set()
    for _score, _idx, candidate in scored:
        key = candidate.lower()
        if key in used:
            continue
        selected.append(textwrap.shorten(candidate, width=120, placeholder="..."))
        used.add(key)
        if len(selected) >= count:
            break

    if len(selected) < min(count, 3):
        for candidate in candidates:
            key = candidate.lower()
            if key in used:
                continue
            if _is_meta_candidate(candidate):
                continue
            selected.append(textwrap.shorten(candidate, width=120, placeholder="..."))
            used.add(key)
            if len(selected) >= count:
                break

    if not selected:
        return ["핵심 메시지를 추출하지 못했습니다. 원문 검토가 필요해요."]
    return selected


def _collect_candidates(text: str) -> list[str]:
    raw = re.sub(r"```.*?```", " ", text or "", flags=re.DOTALL)
    raw = raw.replace("\r\n", "\n")
    pieces: list[str] = []
    seen = set()
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        stripped = re.sub(r"^\s*[-*]\s+", "", stripped)
        stripped = re.sub(r"^\s*\d+[.)]\s+", "", stripped)
        stripped = stripped.lstrip("#").strip()
        if not stripped:
            continue
        sentence_chunks = re.split(r"(?<=[.!?。])\s+|(?<=다\.)\s+", stripped)
        for chunk in sentence_chunks:
            candidate = _clean_candidate(chunk)
            if not candidate:
                continue
            key = candidate.lower()
            if key in seen:
                continue
            seen.add(key)
            pieces.append(candidate)
    return pieces


def _clean_candidate(chunk: str) -> str | None:
    value = chunk.strip()
    if not value:
        return None
    value = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", value)
    value = value.replace("`", "").replace("*", "")
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) < 18:
        return None
    if value.startswith(("http://", "https://")):
        return None
    if "{message}" in value or "{topic}" in value:
        return None
    if _is_meta_candidate(value):
        return None
    return value


def _title_keywords(title: str) -> list[str]:
    tokens = re.findall(r"[가-힣A-Za-z0-9]+", title or "")
    cleaned: list[str] = []
    for token in tokens:
        word = token.lower().strip()
        if len(word) < 2:
            continue
        if word in _TITLE_STOPWORDS:
            continue
        cleaned.append(word)
    cleaned.sort(key=len, reverse=True)
    return cleaned[:8]


def _score_candidate(candidate: str, title_keywords: list[str]) -> int:
    lowered = candidate.lower()
    if _is_meta_candidate(candidate):
        return -100
    score = min(len(candidate), 90)
    if any(ch.isdigit() for ch in candidate):
        score += 16
    priority_hits = sum(1 for term in _PRIORITY_TERMS if term in candidate)
    score += min(priority_hits * 10, 40)
    title_hits = sum(1 for keyword in title_keywords if keyword in lowered)
    score += min(title_hits * 14, 42)
    if len(candidate) < 30:
        score -= 20
    if len(candidate) > 180:
        score -= 15
    if _looks_like_instruction(candidate):
        score -= 45
    return score


def _looks_like_instruction(candidate: str) -> bool:
    lowered = candidate.lower()
    instruction_terms = ("create", "generate", "style", "prompt", "slide", "thumbnail", "output")
    if not any(term in lowered for term in instruction_terms):
        return False
    hangul_chars = sum(1 for ch in candidate if "\uac00" <= ch <= "\ud7a3")
    ascii_alpha = sum(1 for ch in candidate if ch.isascii() and ch.isalpha())
    return ascii_alpha > 18 and hangul_chars < 4


def _is_meta_candidate(candidate: str) -> bool:
    lowered = candidate.lower()
    return any(pattern in lowered for pattern in _META_PATTERNS)


def _required_paths_for_targets(targets: list[str]) -> list[str]:
    required = ["brief.md"]
    if "newsletter" in targets:
        required.append("newsletter.md")
    if "blog" in targets:
        required.append("blog.md")
    if "linkedin" in targets:
        required.append("linkedin.md")
    if "youtube-script" in targets:
        required.append("youtube-script.md")
    if "threads" in targets:
        required.append("threads/thread-01.md")
    if "shorts-scripts" in targets:
        required.append("shorts-scripts/shorts-01.md")
    if "thumbnail" in targets:
        required.append("visuals/thumbnail.png")
    if "card-news" in targets:
        required.append("visuals/card-news/slide-01.png")
    if "chart" in targets:
        required.extend(["charts/overview.png", "charts/trend.png"])
    if "shorts-videos" in targets:
        required.append("shorts-videos/shorts-01.mp4")
    return required


def _normalize_targets(targets: list[str]) -> list[str]:
    expanded: list[str] = []
    for target in targets:
        normalized = target.strip().lower()
        if not normalized:
            continue
        if normalized == "visuals":
            expanded.extend(["card-news", "thumbnail"])
            continue
        if normalized == "visual-card-news":
            expanded.append("card-news")
            continue
        if normalized == "visual-thumbnail":
            expanded.append("thumbnail")
            continue
        if normalized == "charts":
            expanded.append("chart")
            continue
        expanded.append(normalized)
    return list(dict.fromkeys(expanded))


def _json_list(raw: str) -> list[str]:
    try:
        value = json.loads(raw)
        if isinstance(value, list):
            return [str(item) for item in value]
    except Exception:
        pass
    return []


def _parse_json_object(raw: str) -> dict[str, object] | None:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        loaded = json.loads(text)
        if isinstance(loaded, dict):
            return loaded
    except Exception:
        pass
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return None
    try:
        loaded = json.loads(match.group(0))
        if isinstance(loaded, dict):
            return loaded
    except Exception:
        return None
    return None


def _render_prompt_template(template: str, values: dict[str, str]) -> str:
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace("{" + key + "}", value)
    return rendered


def _brief_template_fallback() -> str:
    return (
        "# brief.md\n\n"
        "## 입력 정보\n"
        "- Source: {source_ref}\n"
        "- 소스 타입: {source_type}\n"
        "- 제목: {title}\n"
        "- 언어: {language}\n"
        "- 톤: {tone}\n\n"
        "## 타겟 산출물\n"
        "{target_lines}\n\n"
        "## 핵심 메시지 (3~5개)\n"
        "{key_lines}\n\n"
        "## 주의/제약\n"
        "{warning_lines}\n\n"
        "## 원문 요약\n"
        "{source_preview}\n"
    )
