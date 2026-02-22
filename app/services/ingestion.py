from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from readability import Document

from app.core.config import Settings


YOUTUBE_DOMAINS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "www.youtu.be"}
TIMECODE_RE = re.compile(r"^\d{2}:\d{2}:\d{2}\.\d{3}\s+-->\s+\d{2}:\d{2}:\d{2}\.\d{3}$")
MARKDOWN_PREFIX = "markdown://"


@dataclass
class IngestionResult:
    source_type: str
    title: str
    text: str
    metadata: dict[str, str] = field(default_factory=dict)
    video_path: Path | None = None
    warnings: list[str] = field(default_factory=list)


def ingest_source(url: str, work_dir: Path, settings: Settings, mock_mode: bool = False) -> IngestionResult:
    work_dir.mkdir(parents=True, exist_ok=True)
    if mock_mode:
        return IngestionResult(
            source_type="mock",
            title="Mock Source",
            text=(
                "이 콘텐츠는 무인증 PoC 동작 확인을 위한 샘플 텍스트입니다. "
                "마케터가 URL을 입력하면 기획/콘텐츠 제작/검수를 자동 수행합니다."
            ),
            metadata={"url": url},
        )
    if url.startswith(MARKDOWN_PREFIX):
        markdown = url[len(MARKDOWN_PREFIX) :]
        return ingest_markdown(markdown)
    if _is_youtube_url(url):
        return _ingest_youtube(url, work_dir, settings)
    return _ingest_web(url, settings)


def ingest_markdown(markdown_text: str) -> IngestionResult:
    text = (markdown_text or "").strip()
    title = "Markdown Source"
    for line in text.splitlines():
        raw = line.strip()
        if raw.startswith("#"):
            title = raw.lstrip("#").strip() or title
            break
    if not text:
        raise RuntimeError("markdown source is empty")
    return IngestionResult(
        source_type="markdown",
        title=title,
        text=text,
        metadata={"source_ref": "markdown input"},
    )


def _is_youtube_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in YOUTUBE_DOMAINS


def _ingest_youtube(url: str, work_dir: Path, settings: Settings) -> IngestionResult:
    warnings: list[str] = []
    metadata = _youtube_metadata(url, settings)
    title = metadata.get("title", "Untitled YouTube source")
    text = ""
    video_path = None

    subtitle_path = _download_subtitle_vtt(url, work_dir)
    if subtitle_path:
        text = _vtt_to_text(subtitle_path)

    if not text:
        try:
            video_path = _download_youtube_video(url, work_dir)
            text = _transcribe_video_to_text(video_path, settings)
            warnings.append("공식 자막 추출 실패로 Whisper 전사 결과를 사용했습니다.")
        except Exception as exc:
            warnings.append(f"Whisper 전사 실패: {exc}")

    if video_path is None:
        try:
            video_path = _download_youtube_video(url, work_dir)
        except Exception as exc:
            warnings.append(f"쇼츠용 영상 다운로드 실패: {exc}")

    if not text:
        description = metadata.get("description", "")
        text = f"{title}\n\n{description}".strip()
        warnings.append("자막/전사 추출 실패로 메타데이터 기반 요약 모드를 사용했습니다.")

    return IngestionResult(
        source_type="youtube",
        title=title,
        text=text,
        metadata={"url": url, "channel": str(metadata.get("channel", ""))},
        video_path=video_path,
        warnings=warnings,
    )


def _ingest_web(url: str, settings: Settings) -> IngestionResult:
    with httpx.Client(timeout=settings.request_timeout_seconds, follow_redirects=True) as client:
        response = client.get(url)
        response.raise_for_status()
        html = response.text

    document = Document(html)
    title = document.short_title() or "Untitled Web source"
    cleaned_html = document.summary()
    cleaned_text = BeautifulSoup(cleaned_html, "html.parser").get_text(separator="\n", strip=True)

    warnings: list[str] = []
    if len(cleaned_text) < 300:
        raw_text = BeautifulSoup(html, "html.parser").get_text(separator="\n", strip=True)
        if not raw_text.strip():
            raise RuntimeError("웹 본문 추출에 실패했습니다.")
        warnings.append("Readability 본문 추출 길이가 짧아 raw text fallback을 사용했습니다.")
        cleaned_text = raw_text

    return IngestionResult(
        source_type="web",
        title=title,
        text=cleaned_text,
        metadata={"url": url},
        warnings=warnings,
    )


def _youtube_metadata(url: str, settings: Settings) -> dict:
    command = ["yt-dlp", "--dump-single-json", "--no-warnings", url]
    completed = subprocess.run(command, capture_output=True, text=True, check=True)
    return json.loads(completed.stdout or "{}")


def _download_subtitle_vtt(url: str, work_dir: Path) -> Path | None:
    subtitle_dir = work_dir / "subs"
    subtitle_dir.mkdir(parents=True, exist_ok=True)
    output_template = str(subtitle_dir / "%(id)s.%(ext)s")
    command = [
        "yt-dlp",
        "--skip-download",
        "--write-auto-subs",
        "--sub-langs",
        "ko,en",
        "--sub-format",
        "vtt",
        "-o",
        output_template,
        url,
    ]
    subprocess.run(command, capture_output=True, text=True, check=False)
    vtt_files = sorted(subtitle_dir.glob("*.vtt"))
    return vtt_files[0] if vtt_files else None


def _vtt_to_text(path: Path) -> str:
    lines = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        raw = line.strip()
        if not raw or raw == "WEBVTT" or raw.isdigit() or TIMECODE_RE.match(raw):
            continue
        lines.append(raw)
    return "\n".join(lines).strip()


def _download_youtube_video(url: str, work_dir: Path) -> Path:
    video_dir = work_dir / "video"
    video_dir.mkdir(parents=True, exist_ok=True)
    output_template = str(video_dir / "source.%(ext)s")
    command = ["yt-dlp", "-f", "mp4/best", "-o", output_template, url]
    subprocess.run(command, check=True, capture_output=True, text=True)
    candidates = sorted(video_dir.glob("source.*"))
    if not candidates:
        raise RuntimeError("다운로드된 영상 파일을 찾을 수 없습니다.")
    return candidates[0]


def _transcribe_video_to_text(video_path: Path, settings: Settings) -> str:
    from faster_whisper import WhisperModel

    model = WhisperModel(
        settings.whisper_model,
        device=settings.whisper_device,
        compute_type=settings.whisper_compute_type,
    )
    segments, _info = model.transcribe(str(video_path), vad_filter=True)
    chunks = [segment.text.strip() for segment in segments if segment.text.strip()]
    if not chunks:
        raise RuntimeError("Whisper 전사 결과가 비어 있습니다.")
    return "\n".join(chunks)
