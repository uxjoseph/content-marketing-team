from __future__ import annotations

import json
import math
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.core.config import Settings


@dataclass
class TranscriptSegment:
    start: float
    end: float
    text: str


class ShortsVideoService:
    def generate_assets(
        self,
        source_url: str,
        video_path: Path | None,
        scripts_dir: Path,
        output_dir: Path,
        settings: Settings,
        mock_mode: bool = False,
        clip_count: int = 3,
    ) -> tuple[list[str], list[str]]:
        shorts_root = output_dir / "shorts-videos"
        shorts_root.mkdir(parents=True, exist_ok=True)
        warnings: list[str] = []

        if mock_mode:
            return self._generate_mock_videos(shorts_root, clip_count)

        if video_path is None or not video_path.exists():
            raise RuntimeError(f"쇼츠 생성용 원본 영상을 찾을 수 없습니다: {source_url}")

        segments = self._transcribe_with_timestamps(video_path, settings)
        if not segments:
            raise RuntimeError("타임스탬프 전사 결과가 비어 있어 쇼츠 구간을 선정할 수 없습니다.")

        script_hints = self._load_script_hints(scripts_dir, clip_count)
        windows = self._pick_windows(segments, clip_count)
        artifacts: list[str] = []

        for index, window in enumerate(windows):
            clip_index = index + 1
            srt_path = shorts_root / f"shorts-{clip_index:02d}.srt"
            self._write_srt_for_window(srt_path, segments, window.start, window.end, script_hints[index])
            output_path = shorts_root / f"shorts-{clip_index:02d}.mp4"
            self._render_clip(video_path, output_path, srt_path, window.start, window.end)
            artifacts.append(str(output_path.relative_to(output_dir)))
        return artifacts, warnings

    def _generate_mock_videos(self, shorts_root: Path, clip_count: int) -> tuple[list[str], list[str]]:
        warnings: list[str] = []
        artifacts: list[str] = []
        for index in range(clip_count):
            output_path = shorts_root / f"shorts-{index + 1:02d}.mp4"
            command = [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "color=c=black:s=1080x1920:d=5",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                str(output_path),
            ]
            try:
                subprocess.run(command, capture_output=True, text=True, check=True)
            except Exception as exc:
                output_path.write_bytes(b"")
                warnings.append(f"{output_path.name} mock 생성 실패: {exc}")
            artifacts.append(str(output_path.relative_to(shorts_root.parent)))
        return artifacts, warnings

    def _transcribe_with_timestamps(self, video_path: Path, settings: Settings) -> list[TranscriptSegment]:
        from faster_whisper import WhisperModel

        model = WhisperModel(
            settings.whisper_model,
            device=settings.whisper_device,
            compute_type=settings.whisper_compute_type,
        )
        segments, _info = model.transcribe(str(video_path), vad_filter=True)
        rows: list[TranscriptSegment] = []
        for seg in segments:
            text = seg.text.strip()
            if not text:
                continue
            rows.append(TranscriptSegment(start=float(seg.start), end=float(seg.end), text=text))
        return rows

    def _load_script_hints(self, scripts_dir: Path, clip_count: int) -> list[str]:
        hints: list[str] = []
        for index in range(clip_count):
            path = scripts_dir / f"shorts-{index + 1:02d}.md"
            if not path.exists():
                hints.append("")
                continue
            lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            hints.append(lines[0] if lines else "")
        return hints

    def _pick_windows(self, segments: list[TranscriptSegment], clip_count: int) -> list[TranscriptSegment]:
        duration = max(segment.end for segment in segments)
        window_size = 55.0
        windows: list[TranscriptSegment] = []
        for index in range(clip_count):
            anchor = (duration / clip_count) * index
            start = max(0.0, min(anchor, max(0.0, duration - window_size)))
            end = min(duration, start + window_size)
            if end - start < 45:
                start = max(0.0, end - 45)
            windows.append(TranscriptSegment(start=start, end=end, text=""))
        return windows

    def _write_srt_for_window(
        self,
        srt_path: Path,
        segments: list[TranscriptSegment],
        start: float,
        end: float,
        script_hint: str,
    ) -> None:
        lines: list[str] = []
        item_index = 1
        if script_hint:
            lines.extend(
                [
                    str(item_index),
                    "00:00:00,000 --> 00:00:03,000",
                    script_hint,
                    "",
                ]
            )
            item_index += 1

        for segment in segments:
            if segment.end < start or segment.start > end:
                continue
            local_start = max(0.0, segment.start - start)
            local_end = min(end - start, segment.end - start)
            if local_end <= local_start:
                continue
            lines.extend(
                [
                    str(item_index),
                    f"{_format_srt_time(local_start)} --> {_format_srt_time(local_end)}",
                    segment.text,
                    "",
                ]
            )
            item_index += 1
        srt_path.write_text("\n".join(lines), encoding="utf-8")

    def _render_clip(self, video_path: Path, output_path: Path, srt_path: Path, start: float, end: float) -> None:
        escaped_srt = _escape_subtitles_path(srt_path)
        vf = (
            "scale=1080:1920:force_original_aspect_ratio=increase,"
            f"crop=1080:1920,subtitles='{escaped_srt}'"
        )
        command = [
            "ffmpeg",
            "-y",
            "-ss",
            f"{start:.3f}",
            "-to",
            f"{end:.3f}",
            "-i",
            str(video_path),
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or "ffmpeg render failed")

    def probe_video(self, path: Path) -> tuple[int, int, float] | None:
        command = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=width,height:format=duration",
            "-of",
            "json",
            str(path),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            return None
        data = json.loads(completed.stdout)
        streams = data.get("streams", [])
        fmt = data.get("format", {})
        if not streams:
            return None
        width = int(streams[0].get("width", 0))
        height = int(streams[0].get("height", 0))
        duration = float(fmt.get("duration", 0.0))
        return width, height, duration


def _format_srt_time(seconds: float) -> str:
    millis = int(round(seconds * 1000))
    hours = millis // 3_600_000
    millis %= 3_600_000
    minutes = millis // 60_000
    millis %= 60_000
    secs = millis // 1000
    millis %= 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _escape_subtitles_path(path: Path) -> str:
    text = str(path.resolve())
    text = text.replace("\\", "\\\\")
    text = text.replace(":", "\\:")
    text = text.replace(",", "\\,")
    text = text.replace("'", "\\'")
    return text
