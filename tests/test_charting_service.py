from __future__ import annotations

import base64
import io
from pathlib import Path

import httpx
from PIL import Image

from app.core.config import Settings
from app.services.charting import ChartAssetService


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
        nanobanana_model="gemini-3-pro-image-preview",
    )


def _sample_inline_data_png() -> str:
    image = Image.new("RGB", (64, 64), color=(0, 100, 220))
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def _response(status_code: int, payload: dict) -> httpx.Response:
    req = httpx.Request(
        "POST",
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-3-pro-image-preview:generateContent",
    )
    return httpx.Response(status_code, json=payload, request=req)


def test_chart_service_uses_gemini_3_pro_for_chart_images(monkeypatch, tmp_path: Path):
    service = ChartAssetService(_settings())
    encoded = _sample_inline_data_png()
    responses = [
        _response(
            200,
            {"candidates": [{"content": {"parts": [{"inlineData": {"data": encoded}}]}}]},
        ),
        _response(
            200,
            {"candidates": [{"content": {"parts": [{"inlineData": {"data": encoded}}]}}]},
        ),
    ]
    calls: list[dict] = []
    monkeypatch.setattr("app.services.charting.httpx.Client", lambda timeout: _FakeClient(responses, calls))
    brief = (
        "# brief.md\n\n"
        "## 핵심 메시지 (3~5개)\n"
        "- 환율 변동성 대응 체계를 분기 단위로 점검해야 한다.\n"
        "- CAC 하락을 위해 캠페인 믹스를 재설계해야 한다.\n"
    )

    artifacts, warnings = service.generate_assets(brief, tmp_path, mock_mode=False)

    assert warnings == []
    assert "charts/overview.png" in artifacts
    assert "charts/trend.png" in artifacts
    assert len(calls) == 2
    assert all("/models/gemini-3-pro-image-preview:generateContent" in call["url"] for call in calls)
    assert all(call["json"]["generationConfig"]["responseModalities"] == ["IMAGE"] for call in calls)


def test_chart_service_fallbacks_to_local_when_api_key_missing(tmp_path: Path):
    settings = Settings(
        nanobanana_api_url="https://generativelanguage.googleapis.com/v1beta/models/gemini-3-pro-image-preview:generateContent",
        nanobanana_api_key="",
    )
    service = ChartAssetService(settings)
    brief = (
        "# brief.md\n\n"
        "## 핵심 메시지 (3~5개)\n"
        "- 리타겟팅 빈도 최적화로 ROAS 개선 여지가 있다.\n"
    )

    artifacts, warnings = service.generate_assets(brief, tmp_path, mock_mode=False)

    assert "charts/overview.png" in artifacts
    assert "charts/trend.png" in artifacts
    assert len(warnings) >= 2
    assert (tmp_path / "charts" / "overview.png").exists()
    assert (tmp_path / "charts" / "trend.png").exists()
