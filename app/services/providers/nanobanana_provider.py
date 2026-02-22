from __future__ import annotations

import base64
import io
import random
import textwrap
import time
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageOps

from app.core.config import Settings
from app.services.prompt_store import load_prompt_map, render_prompt_with_variables


class NanobananaProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def generate_assets(
        self,
        brief_text: str,
        output_dir: Path,
        mock_mode: bool = False,
        generate_card_news: bool = True,
        generate_thumbnail: bool = True,
    ) -> tuple[list[str], list[str]]:
        visuals_root = output_dir / "visuals"
        visuals_root.mkdir(parents=True, exist_ok=True)
        card_root = visuals_root / "card-news"
        if generate_card_news:
            card_root.mkdir(parents=True, exist_ok=True)

        key_messages = self._extract_key_messages(brief_text)
        prompt_map = load_prompt_map()
        paths: list[str] = []
        warnings: list[str] = []

        if generate_card_news:
            slide_count = min(max(len(key_messages) + 2, 5), 7)
            for index in range(slide_count):
                prompt = self._slide_prompt(index, key_messages, prompt_map)
                slide_path = card_root / f"slide-{index + 1:02d}.png"
                try:
                    self._write_image(prompt, slide_path, 1080, 1080, mock_mode)
                except Exception as exc:
                    self._write_mock_image(slide_path, 1080, 1080, f"{prompt}\n\nFallback: {exc}")
                    warnings.append(
                        f"{slide_path.name} 생성 실패로 fallback 이미지를 생성했습니다: {exc}"
                    )
                paths.append(str(slide_path.relative_to(output_dir)))

        if generate_thumbnail:
            thumbnail_prompt = self._thumbnail_prompt(key_messages, prompt_map)
            thumbnail_path = visuals_root / "thumbnail.png"
            try:
                self._write_image(thumbnail_prompt, thumbnail_path, 1280, 720, mock_mode)
            except Exception as exc:
                self._write_mock_image(
                    thumbnail_path,
                    1280,
                    720,
                    f"{thumbnail_prompt}\n\nFallback: {exc}",
                )
                warnings.append(
                    f"{thumbnail_path.name} 생성 실패로 fallback 이미지를 생성했습니다: {exc}"
                )
            paths.append(str(thumbnail_path.relative_to(output_dir)))
        return paths, warnings

    def _slide_prompt(self, index: int, key_messages: list[str], prompt_map: dict[str, str]) -> str:
        topic = key_messages[0] if key_messages else "입력 원문의 핵심 주제"
        if index == 0:
            template = self._prompt(
                prompt_map,
                "visual.card.cover",
                "Instagram card-news cover. Strong hook title, high contrast, modern marketing style.",
            )
            return self._compose_visual_prompt(
                "visual.card.cover",
                template,
                topic=topic,
                message=topic,
                stage="cover",
            )
        if index == len(key_messages) + 1:
            cta_message = key_messages[-1] if key_messages else topic
            template = self._prompt(
                prompt_map,
                "visual.card.cta",
                "Instagram card-news last slide. Clear CTA. Bold typography. Marketing action oriented.",
            )
            return self._compose_visual_prompt(
                "visual.card.cta",
                template,
                topic=topic,
                message=cta_message,
                stage="cta",
            )
        msg_index = min(max(index - 1, 0), len(key_messages) - 1) if key_messages else 0
        core = key_messages[msg_index] if key_messages else "핵심 메시지를 시각적으로 전달"
        template = self._prompt(
            prompt_map,
            "visual.card.body",
            "Instagram card-news slide focused on: {message}. Clean layout, iconography, readable Korean text.",
        )
        return self._compose_visual_prompt(
            "visual.card.body",
            template,
            topic=topic,
            message=core,
            stage="body",
        )

    def _thumbnail_prompt(self, key_messages: list[str], prompt_map: dict[str, str]) -> str:
        topic = key_messages[0] if key_messages else "마케팅 자동화 핵심 포인트"
        template = self._prompt(
            prompt_map,
            "visual.thumbnail",
            "YouTube thumbnail 1280x720. Big Korean title around '{topic}'. Strong contrast, human-friendly, no clutter.",
        )
        return self._compose_visual_prompt(
            "visual.thumbnail",
            template,
            topic=topic,
            message=topic,
            stage="thumbnail",
        )

    def _extract_key_messages(self, brief_text: str) -> list[str]:
        # Prefer only the bullets under "핵심 메시지" section.
        messages: list[str] = []
        in_key_section = False
        for line in brief_text.splitlines():
            raw = line.strip()
            if raw.startswith("## "):
                in_key_section = "핵심 메시지" in raw.lower() or "핵심 메시지" in raw
                continue
            if not in_key_section:
                continue
            if raw.startswith("- "):
                value = raw.removeprefix("- ").strip()
                if value:
                    messages.append(value)
            elif raw:
                # Stop when next non-bullet paragraph begins.
                break

        if messages:
            return messages[:5]

        # Fallback for older briefs that may not have the dedicated section.
        fallback: list[str] = []
        for line in brief_text.splitlines():
            raw = line.strip()
            if not raw.startswith("- "):
                continue
            value = raw.removeprefix("- ").strip()
            if not value:
                continue
            if value.startswith(("Source:", "소스 타입:", "제목:", "언어:", "톤:", "URL:")):
                continue
            fallback.append(value)
        return fallback[:5]

    def _write_image(self, prompt: str, path: Path, width: int, height: int, mock_mode: bool) -> None:
        if mock_mode:
            self._write_mock_image(path, width, height, prompt)
            return
        image_bytes = self._request_image(prompt, width, height)
        path.write_bytes(image_bytes)

    def _request_image(self, prompt: str, width: int, height: int) -> bytes:
        if not self.settings.nanobanana_api_url or not self.settings.nanobanana_api_key:
            raise RuntimeError("NANOBANANA_API_URL / NANOBANANA_API_KEY is required for visuals.")

        if "generativelanguage.googleapis.com" in self.settings.nanobanana_api_url:
            return self._request_image_from_gemini(prompt, width, height)

        headers = {"Authorization": f"Bearer {self.settings.nanobanana_api_key}"}
        payload = {
            "model": self.settings.nanobanana_model,
            "prompt": prompt,
            "width": width,
            "height": height,
            "format": "png",
        }
        with httpx.Client(timeout=self.settings.request_timeout_seconds) as client:
            response = client.post(self.settings.nanobanana_api_url, headers=headers, json=payload)
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            if "image/" in content_type:
                return response.content
            data = response.json()

        if isinstance(data, dict):
            image_base64 = data.get("image_base64") or data.get("b64_json")
            if image_base64:
                return base64.b64decode(image_base64)

            images = data.get("images")
            if isinstance(images, list) and images:
                item = images[0]
                if isinstance(item, str):
                    return base64.b64decode(item)
                if isinstance(item, dict):
                    if item.get("b64_json"):
                        return base64.b64decode(item["b64_json"])
                    if item.get("url"):
                        with httpx.Client(timeout=self.settings.request_timeout_seconds) as client:
                            image_resp = client.get(item["url"])
                            image_resp.raise_for_status()
                            return image_resp.content
        raise RuntimeError("Nanobanana API did not return a supported image payload.")

    def _request_image_from_gemini(self, prompt: str, width: int, height: int) -> bytes:
        headers = {
            "x-goog-api-key": self.settings.nanobanana_api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseModalities": ["IMAGE"]},
        }
        attempts = 3
        for attempt in range(attempts):
            try:
                with httpx.Client(timeout=self.settings.request_timeout_seconds) as client:
                    response = client.post(self.settings.nanobanana_api_url, headers=headers, json=payload)
                if response.status_code in {429, 500, 502, 503, 504} and attempt < attempts - 1:
                    self._backoff_sleep(attempt)
                    continue
                response.raise_for_status()
                image_bytes = self._extract_gemini_image_bytes(response.json())
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
        raise RuntimeError("Gemini image request failed after retries.")

    def _extract_gemini_image_bytes(self, data: dict) -> bytes | None:
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
            fitted = ImageOps.fit(rgb, (width, height), method=Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            fitted.save(buf, format="PNG")
            return buf.getvalue()

    def _backoff_sleep(self, attempt: int) -> None:
        base_delay = min(2**attempt, 4)
        jitter = random.uniform(0.0, 0.5)
        time.sleep(base_delay + jitter)

    def _prompt(self, prompt_map: dict[str, str], key: str, fallback: str) -> str:
        value = prompt_map.get(key)
        if value and value.strip():
            return value
        return fallback

    def _compose_visual_prompt(
        self,
        prompt_key: str,
        template: str,
        *,
        topic: str,
        message: str,
        stage: str,
    ) -> str:
        safe_topic = topic.strip() or "입력 원문의 핵심 주제"
        safe_message = message.strip() or safe_topic
        base = render_prompt_with_variables(
            prompt_key=prompt_key,
            template=template,
            runtime_values={
                "topic": safe_topic,
                "message": safe_message,
                "stage": stage,
            },
        )
        grounding = textwrap.dedent(
            f"""

            Source grounding:
            - Topic: {safe_topic}
            - Core message: {safe_message}
            - Stage: {stage}
            - On-image Korean copy must be created only from Topic/Core message.
            - Never print planning or instruction text in the final image.
            """
        ).strip()
        return f"{base}\n\n{grounding}"

    def _write_mock_image(self, path: Path, width: int, height: int, text: str) -> None:
        image = Image.new("RGB", (width, height), color=(36, 50, 77))
        draw = ImageDraw.Draw(image)
        wrapped = textwrap.fill(text, width=32)
        draw.multiline_text((40, 40), wrapped, fill=(255, 255, 255), spacing=8)
        image.save(path, format="PNG")
