from __future__ import annotations

from app.services.orchestrator import _extract_key_messages


def test_extract_key_messages_filters_prompt_like_meta_text():
    title = "미국 경기 둔화가 수출 기업에 미치는 영향"
    text = (
        "Instagram card-news last slide. Clear CTA. Bold typography.\n"
        "{\n"
        '  "model": "models/gemini-3-pro-image-preview",\n'
        '  "generationConfig": {"responseModalities": ["IMAGE"]}\n'
        "}\n"
        "미국 경기 둔화 신호가 뚜렷해지며 반도체 수출 증가율이 2분기 4%로 하락했다.\n"
        "환율 변동성 확대에 대비해 수출 기업은 분기별 환헤지 비율을 재조정해야 한다.\n"
        "단가 인상보다 재고 회전율 개선이 영업이익 방어에 더 효과적이라는 분석이 제시됐다.\n"
    )

    messages = _extract_key_messages(title, text, 5)
    merged = " ".join(messages).lower()

    assert "instagram card-news" not in merged
    assert "responsemodalities" not in merged
    assert any("환율 변동성" in message for message in messages)
    assert any("재고 회전율 개선" in message for message in messages)


def test_extract_key_messages_prioritizes_business_relevance():
    title = "광고 효율 개선 체크리스트"
    text = (
        "# 작성 지시\n"
        "- 아래 지시를 따라 출력하세요.\n"
        "- output format: markdown\n"
        "CAC가 3개월 연속 상승하면 캠페인 구조를 재설계해야 한다.\n"
        "리타겟팅 빈도를 주 5회에서 3회로 낮추자 ROAS가 18% 개선됐다.\n"
        "랜딩페이지 첫 화면의 메시지 일치율을 높이면 전환율이 개선된다.\n"
    )

    messages = _extract_key_messages(title, text, 5)
    merged = " ".join(messages).lower()

    assert "output format" not in merged
    assert any("CAC가 3개월 연속 상승" in message for message in messages)
    assert any("ROAS가 18% 개선" in message for message in messages)
