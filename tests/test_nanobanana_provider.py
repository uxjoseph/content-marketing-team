from __future__ import annotations

import base64
import io
import re
from pathlib import Path

import httpx
from PIL import Image

from app.core.config import Settings
from app.services.providers.nanobanana_provider import NanobananaProvider


class _FakeClient:
    def __init__(self, responses: list[httpx.Response], calls: list[dict]) -> None:
        self._responses = responses
        self._calls = calls

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def post(self, url: str, headers: dict, json: dict) -> httpx.Response:
        self._calls.append({"url": url, "headers": headers, "json": json})
        if not self._responses:
            raise RuntimeError("no fake response configured")
        return self._responses.pop(0)


def _settings() -> Settings:
    return Settings(
        nanobanana_api_url="https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-image:generateContent",
        nanobanana_api_key="test-key",
    )


def _response(status_code: int, payload: dict) -> httpx.Response:
    req = httpx.Request("POST", "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-image:generateContent")
    return httpx.Response(status_code, json=payload, request=req)


def _sample_inline_data_png() -> str:
    image = Image.new("RGB", (64, 64), color=(255, 0, 0))
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def test_gemini_response_is_resized_to_requested_dimensions(monkeypatch):
    provider = NanobananaProvider(_settings())
    encoded = _sample_inline_data_png()
    responses = [
        _response(
            200,
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [{"inlineData": {"data": encoded, "mimeType": "image/png"}}]
                        }
                    }
                ]
            },
        )
    ]
    calls: list[dict] = []

    monkeypatch.setattr(
        "app.services.providers.nanobanana_provider.httpx.Client",
        lambda timeout: _FakeClient(responses, calls),
    )

    image_bytes = provider._request_image("thumbnail prompt", width=1280, height=720)
    with Image.open(io.BytesIO(image_bytes)) as generated:
        assert generated.size == (1280, 720)
        assert generated.format == "PNG"
    assert len(calls) == 1


def test_gemini_retries_on_429_and_succeeds(monkeypatch):
    provider = NanobananaProvider(_settings())
    encoded = _sample_inline_data_png()
    responses = [
        _response(429, {"error": {"code": 429, "message": "rate limited"}}),
        _response(
            200,
            {
                "candidates": [
                    {"content": {"parts": [{"inlineData": {"data": encoded}}]}}
                ]
            },
        ),
    ]
    calls: list[dict] = []

    monkeypatch.setattr(
        "app.services.providers.nanobanana_provider.httpx.Client",
        lambda timeout: _FakeClient(responses, calls),
    )
    monkeypatch.setattr(provider, "_backoff_sleep", lambda attempt: None)

    image_bytes = provider._request_image("card prompt", width=1080, height=1080)
    assert len(image_bytes) > 0
    assert len(calls) == 2


def test_env_example_keeps_api_keys_empty():
    text = Path(".env.example").read_text(encoding="utf-8")
    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "NANOBANANA_API_KEY"):
        match = re.search(rf"^{key}=\"(.*)\"$", text, flags=re.MULTILINE)
        assert match is not None
        assert match.group(1) == ""


def test_extract_key_messages_prefers_brief_core_section():
    provider = NanobananaProvider(_settings())
    brief = (
        "# brief.md\n\n"
        "## 입력 정보\n"
        "- Source: markdown input\n"
        "- 소스 타입: markdown\n"
        "- 제목: 테스트 제목\n\n"
        "## 타겟 산출물\n"
        "- visuals\n\n"
        "## 핵심 메시지 (3~5개)\n"
        "- 고객이 바로 실행할 수 있는 체크리스트 제공\n"
        "- 실패 사례를 줄이는 자동화 기준 정리\n"
        "- 비용 대비 효율이 높은 우선순위 제안\n\n"
        "## 주의/제약\n"
        "- 없음\n"
    )
    key_messages = provider._extract_key_messages(brief)
    assert key_messages == [
        "고객이 바로 실행할 수 있는 체크리스트 제공",
        "실패 사례를 줄이는 자동화 기준 정리",
        "비용 대비 효율이 높은 우선순위 제안",
    ]


def test_generate_assets_falls_back_to_mock_images_when_gemini_payload_has_no_image(monkeypatch, tmp_path: Path):
    provider = NanobananaProvider(_settings())

    def always_fail(*_args, **_kwargs):
        raise RuntimeError("Gemini image response did not include inlineData.")

    monkeypatch.setattr(provider, "_request_image", always_fail)
    assets, warnings = provider.generate_assets("brief text", tmp_path, mock_mode=False)

    assert "visuals/thumbnail.png" in assets
    assert any(path.startswith("visuals/card-news/slide-") for path in assets)
    assert len(warnings) >= 2
    assert (tmp_path / "visuals" / "thumbnail.png").exists()
    assert len(list((tmp_path / "visuals" / "card-news").glob("slide-*.png"))) >= 5


def test_slide_prompts_are_grounded_to_source_content():
    provider = NanobananaProvider(_settings())
    key_messages = [
        "미국 경기 둔화 신호로 인해 수출기업 리스크 관리가 중요해졌다",
        "환율 변동성 대응을 위해 분기별 환헤지 점검이 필요하다",
    ]

    cover_prompt = provider._slide_prompt(0, key_messages, {})
    body_prompt = provider._slide_prompt(1, key_messages, {})
    cta_prompt = provider._slide_prompt(len(key_messages) + 1, key_messages, {})
    thumbnail_prompt = provider._thumbnail_prompt(key_messages, {})

    assert "Topic: 미국 경기 둔화 신호로 인해 수출기업 리스크 관리가 중요해졌다" in cover_prompt
    assert "Core message: 미국 경기 둔화 신호로 인해 수출기업 리스크 관리가 중요해졌다" in body_prompt
    assert "Core message: 환율 변동성 대응을 위해 분기별 환헤지 점검이 필요하다" in cta_prompt
    assert "Never print planning or instruction text in the final image." in cover_prompt
    assert "Topic: 미국 경기 둔화 신호로 인해 수출기업 리스크 관리가 중요해졌다" in thumbnail_prompt


def test_slide_prompt_replaces_topic_and_message_placeholders_from_prompt_store():
    provider = NanobananaProvider(_settings())
    key_messages = ["핵심 소재 메시지"]
    prompt_map = {
        "visual.card.cover": "커버: {topic}",
        "visual.card.body": "본문: {message}",
        "visual.card.cta": "CTA: {message}",
    }

    cover_prompt = provider._slide_prompt(0, key_messages, prompt_map)
    body_prompt = provider._slide_prompt(1, key_messages, prompt_map)
    cta_prompt = provider._slide_prompt(2, key_messages, prompt_map)

    assert "커버: 핵심 소재 메시지" in cover_prompt
    assert "본문: 핵심 소재 메시지" in body_prompt
    assert "CTA: 핵심 소재 메시지" in cta_prompt


def test_generate_assets_can_create_thumbnail_only(monkeypatch, tmp_path: Path):
    provider = NanobananaProvider(_settings())

    def always_fail(*_args, **_kwargs):
        raise RuntimeError("forced fallback")

    monkeypatch.setattr(provider, "_request_image", always_fail)
    assets, warnings = provider.generate_assets(
        "brief text",
        tmp_path,
        mock_mode=False,
        generate_card_news=False,
        generate_thumbnail=True,
    )

    assert assets == ["visuals/thumbnail.png"]
    assert len(warnings) == 1
    assert (tmp_path / "visuals" / "thumbnail.png").exists()
    assert not (tmp_path / "visuals" / "card-news").exists()
