from __future__ import annotations

import base64
import io
import random
import re
import textwrap
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from PIL import Image, ImageDraw

from app.core.config import Settings
from app.services.prompt_store import load_prompt_map


class ChartAssetService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def generate_assets(
        self,
        brief_text: str,
        output_dir: Path,
        mock_mode: bool = False,
    ) -> tuple[list[str], list[str]]:
        charts_root = output_dir / "charts"
        charts_root.mkdir(parents=True, exist_ok=True)

        prompt_map = load_prompt_map()
        messages = self._extract_key_messages(brief_text)
        scores = self._score_messages(messages)

        artifacts: list[str] = []
        warnings: list[str] = []

        overview_title = self._prompt(
            prompt_map,
            "chart.overview.title",
            "핵심 메시지 우선순위 차트",
        )
        trend_title = self._prompt(
            prompt_map,
            "chart.trend.title",
            "실행 임팩트 추세",
        )

        overview_path = charts_root / "overview.png"
        trend_path = charts_root / "trend.png"

        overview_prompt = self._overview_prompt(overview_title, scores)
        trend_prompt = self._trend_prompt(trend_title, scores)

        self._generate_one_chart(
            chart_type="overview",
            path=overview_path,
            prompt=overview_prompt,
            title=overview_title,
            scores=scores,
            output_dir=output_dir,
            warnings=warnings,
            artifacts=artifacts,
            mock_mode=mock_mode,
        )
        self._generate_one_chart(
            chart_type="trend",
            path=trend_path,
            prompt=trend_prompt,
            title=trend_title,
            scores=scores,
            output_dir=output_dir,
            warnings=warnings,
            artifacts=artifacts,
            mock_mode=mock_mode,
        )

        return artifacts, warnings

    def _generate_one_chart(
        self,
        *,
        chart_type: str,
        path: Path,
        prompt: str,
        title: str,
        scores: list[tuple[str, int]],
        output_dir: Path,
        warnings: list[str],
        artifacts: list[str],
        mock_mode: bool,
    ) -> None:
        if mock_mode:
            if chart_type == "overview":
                self._draw_bar_chart(path, title, scores)
            else:
                self._draw_line_chart(path, title, scores)
            artifacts.append(str(path.relative_to(output_dir)))
            return

        try:
            image_bytes = self._request_chart_image(prompt, width=1280, height=720)
            path.write_bytes(image_bytes)
            artifacts.append(str(path.relative_to(output_dir)))
            return
        except Exception as exc:
            warnings.append(f"chart {chart_type} Gemini 생성 실패, fallback 사용: {exc}")

        if chart_type == "overview":
            self._draw_bar_chart(path, title, scores)
        else:
            self._draw_line_chart(path, title, scores)
        artifacts.append(str(path.relative_to(output_dir)))

    def _extract_key_messages(self, brief_text: str) -> list[str]:
        messages: list[str] = []
        in_key_section = False
        for line in brief_text.splitlines():
            raw = line.strip()
            if raw.startswith("## "):
                in_key_section = "핵심 메시지" in raw
                continue
            if not in_key_section:
                continue
            if raw.startswith("- "):
                value = raw.removeprefix("- ").strip()
                if value:
                    messages.append(value)
            elif raw:
                break
        if messages:
            return messages[:5]

        fallback: list[str] = []
        for line in brief_text.splitlines():
            raw = line.strip()
            if raw.startswith("- "):
                value = raw.removeprefix("- ").strip()
                if value:
                    fallback.append(value)
        if fallback:
            return fallback[:5]
        return ["핵심 메시지를 추출하지 못했습니다."]

    def _score_messages(self, messages: list[str]) -> list[tuple[str, int]]:
        scored: list[tuple[str, int]] = []
        for index, message in enumerate(messages):
            normalized = max(16, min(98, len(message) + 28 - index * 4))
            label = textwrap.shorten(message, width=36, placeholder="...")
            scored.append((label, normalized))
        return scored[:5]

    def _overview_prompt(self, title: str, scores: list[tuple[str, int]]) -> str:
        lines = "\n".join(
            f"- {label}: {score}"
            for label, score in scores
        )
        return (
            "Create a clean 16:9 business dashboard bar chart image.\n"
            f"Title: {title}\n"
            "Language for on-image text: Korean.\n"
            "Data:\n"
            f"{lines}\n"
            "Constraints:\n"
            "- Show only chart/title/labels from provided data.\n"
            "- Do not include prompt, instruction, API, or meta text.\n"
            "- High readability, ERP report style, clear axis/legend.\n"
            "- PNG image output."
        )

    def _trend_prompt(self, title: str, scores: list[tuple[str, int]]) -> str:
        lines = "\n".join(
            f"- Point {idx + 1}: {label} = {score}"
            for idx, (label, score) in enumerate(scores)
        )
        return (
            "Create a clean 16:9 business dashboard line chart image.\n"
            f"Title: {title}\n"
            "Language for on-image text: Korean.\n"
            "Data:\n"
            f"{lines}\n"
            "Constraints:\n"
            "- Show only chart/title/labels from provided data.\n"
            "- Do not include prompt, instruction, API, or meta text.\n"
            "- High readability, ERP report style, clear trend emphasis.\n"
            "- PNG image output."
        )

    def _request_chart_image(self, prompt: str, width: int, height: int) -> bytes:
        if not self.settings.nanobanana_api_key:
            raise RuntimeError("NANOBANANA_API_KEY is required for Gemini chart generation.")
        api_url = self._chart_api_url()
        model = self._chart_model()

        attempts = 3
        for attempt in range(attempts):
            try:
                headers, payload = self._request_components(api_url, model, prompt)
                with httpx.Client(timeout=self.settings.request_timeout_seconds) as client:
                    response = client.post(api_url, headers=headers, json=payload)
                if response.status_code in {429, 500, 502, 503, 504} and attempt < attempts - 1:
                    self._backoff_sleep(attempt)
                    continue
                response.raise_for_status()
                content_type = response.headers.get("content-type", "").lower()
                if "image/" in content_type:
                    return self._resize_to_png(response.content, width, height)
                image_bytes = self._extract_image_bytes(response.json())
                if image_bytes is None:
                    raise RuntimeError("Gemini image response did not include inlineData.")
                return self._resize_to_png(image_bytes, width, height)
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code if exc.response else 0
                if status in {429, 500, 502, 503, 504} and attempt < attempts - 1:
                    self._backoff_sleep(attempt)
                    continue
                raise
            except httpx.HTTPError:
                if attempt < attempts - 1:
                    self._backoff_sleep(attempt)
                    continue
                raise
        raise RuntimeError("Gemini chart image request failed after retries.")

    def _request_components(self, api_url: str, model: str, prompt: str) -> tuple[dict[str, str], dict]:
        if "generativelanguage.googleapis.com" in api_url:
            headers = {
                "x-goog-api-key": self.settings.nanobanana_api_key,
                "Content-Type": "application/json",
            }
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"responseModalities": ["IMAGE"]},
            }
            return headers, payload

        headers = {
            "Authorization": f"Bearer {self.settings.nanobanana_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": f"models/{model}",
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "",
                "responseModalities": ["IMAGE"],
            },
        }
        return headers, payload

    def _chart_model(self) -> str:
        model = (self.settings.nanobanana_model or "").strip()
        if not model:
            return "gemini-3-pro-image-preview"
        if model.startswith("models/"):
            return model[len("models/") :]
        return model

    def _chart_api_url(self) -> str:
        raw = (self.settings.nanobanana_api_url or "").strip()
        if not raw:
            raise RuntimeError("NANOBANANA_API_URL is required for Gemini chart generation.")
        if "generativelanguage.googleapis.com" not in raw:
            return raw

        model = self._chart_model()
        rewritten = re.sub(
            r"/models/[^/:]+:generateContent",
            f"/models/{model}:generateContent",
            raw,
        )
        if rewritten != raw:
            return rewritten

        parsed = urlsplit(raw)
        return f"{parsed.scheme}://{parsed.netloc}/v1beta/models/{model}:generateContent"

    def _extract_image_bytes(self, data: dict) -> bytes | None:
        candidates = data.get("candidates", [])
        for candidate in candidates:
            content = candidate.get("content", {})
            for part in content.get("parts", []):
                inline_data = part.get("inlineData") or part.get("inline_data")
                if inline_data:
                    encoded = inline_data.get("data") or inline_data.get("bytesBase64Encoded")
                    if encoded:
                        return base64.b64decode(encoded)
                file_data = part.get("fileData") or part.get("file_data")
                if file_data:
                    encoded = file_data.get("data") or file_data.get("bytesBase64Encoded")
                    if encoded:
                        return base64.b64decode(encoded)
                direct = part.get("data")
                if isinstance(direct, str) and direct:
                    return base64.b64decode(direct)
        return None

    def _resize_to_png(self, image_bytes: bytes, width: int, height: int) -> bytes:
        with Image.open(io.BytesIO(image_bytes)) as raw:
            rgb = raw.convert("RGB")
            resized = rgb.resize((width, height), Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            resized.save(buf, format="PNG")
            return buf.getvalue()

    def _backoff_sleep(self, attempt: int) -> None:
        base_delay = min(2**attempt, 4)
        jitter = random.uniform(0.0, 0.5)
        time.sleep(base_delay + jitter)

    def _draw_bar_chart(self, path: Path, title: str, scores: list[tuple[str, int]]) -> None:
        width = 1280
        height = 720
        image = Image.new("RGB", (width, height), (247, 250, 252))
        draw = ImageDraw.Draw(image)

        draw.rectangle((0, 0, width, 88), fill=(14, 52, 90))
        draw.text((32, 28), title, fill=(255, 255, 255))

        left = 80
        top = 140
        chart_width = 1120
        bar_height = 72
        gap = 28

        draw.line((left, top - 10, left, height - 60), fill=(150, 167, 184), width=2)
        draw.line((left, height - 60, left + chart_width, height - 60), fill=(150, 167, 184), width=2)

        for idx, (label, score) in enumerate(scores):
            y0 = top + idx * (bar_height + gap)
            y1 = y0 + bar_height
            w = int((chart_width - 220) * (score / 100))
            color = (30, 120 + idx * 18, 190 - idx * 12)
            draw.rounded_rectangle((left + 160, y0, left + 160 + w, y1), radius=12, fill=color)
            draw.text((left, y0 + 24), f"{idx + 1}. {label}", fill=(27, 37, 48))
            draw.text((left + 170 + w, y0 + 24), f"{score}", fill=(27, 37, 48))

        image.save(path, format="PNG")

    def _draw_line_chart(self, path: Path, title: str, scores: list[tuple[str, int]]) -> None:
        width = 1280
        height = 720
        image = Image.new("RGB", (width, height), (253, 252, 248))
        draw = ImageDraw.Draw(image)

        draw.rectangle((0, 0, width, 88), fill=(66, 45, 114))
        draw.text((32, 28), title, fill=(255, 255, 255))

        left = 110
        right = width - 90
        top = 140
        bottom = height - 90

        draw.rectangle((left, top, right, bottom), outline=(190, 184, 210), width=2)
        for i in range(1, 5):
            y = top + ((bottom - top) // 5) * i
            draw.line((left, y, right, y), fill=(228, 224, 238), width=1)

        if not scores:
            scores = [("No Data", 30), ("No Data", 40), ("No Data", 50)]

        points: list[tuple[int, int]] = []
        span = max(1, len(scores) - 1)
        for i, (_, score) in enumerate(scores):
            x = left + int((right - left) * (i / span))
            normalized = max(0, min(100, score))
            y = bottom - int((bottom - top) * (normalized / 100))
            points.append((x, y))

        for idx in range(1, len(points)):
            draw.line((points[idx - 1], points[idx]), fill=(87, 95, 214), width=4)

        for idx, point in enumerate(points):
            draw.ellipse(
                (point[0] - 8, point[1] - 8, point[0] + 8, point[1] + 8),
                fill=(247, 112, 93),
                outline=(255, 255, 255),
                width=2,
            )
            label = scores[idx][0]
            value = scores[idx][1]
            draw.text((point[0] - 46, min(bottom + 14, point[1] + 20)), textwrap.shorten(label, width=12, placeholder="..."), fill=(40, 33, 53))
            draw.text((point[0] - 8, max(top - 26, point[1] - 24)), str(value), fill=(40, 33, 53))

        slope_note = self._trend_summary(scores)
        draw.text((left, bottom + 34), slope_note, fill=(67, 60, 85))
        image.save(path, format="PNG")

    def _trend_summary(self, scores: list[tuple[str, int]]) -> str:
        if len(scores) < 2:
            return "데이터가 부족해 추세를 단정할 수 없습니다."
        first = scores[0][1]
        last = scores[-1][1]
        delta = last - first
        if delta >= 10:
            return f"추세 판단: 상승(+{delta}) - 실행 확장 우선"
        if delta <= -10:
            return f"추세 판단: 하락({delta}) - 리스크 대응 우선"
        return f"추세 판단: 보합({delta:+d}) - 점진적 최적화"

    def _prompt(self, prompt_map: dict[str, str], key: str, fallback: str) -> str:
        value = prompt_map.get(key)
        if value and value.strip():
            return value
        return fallback
