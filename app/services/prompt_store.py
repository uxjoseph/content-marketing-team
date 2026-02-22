from __future__ import annotations

import datetime as dt
from collections import defaultdict
from typing import Any

from sqlmodel import Session, select

from app.core.db import session_scope
from app.domain.models import PromptTemplate, PromptVariable

PROMPT_VARIABLE_TYPES = ("INPUT_REQUIRED", "INPUT_WITH_DEFAULT", "AI_GENERATED")
PROMPT_VARIABLE_TYPE_LABELS = {
    "INPUT_REQUIRED": "입력 필수",
    "INPUT_WITH_DEFAULT": "입력 + 기본값",
    "AI_GENERATED": "AI 생성",
}

DEFAULT_PROMPTS: dict[str, dict[str, str]] = {
    "planner.brief-template": {
        "label": "브리핑 생성 템플릿",
        "description": "Planner 단계에서 brief.md를 생성할 때 사용하는 템플릿입니다. source, 핵심 메시지, 경고, 요약 구조를 제어합니다.",
        "content": (
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
        ),
    },
    "system.text-agent": {
        "label": "텍스트 에이전트 시스템 프롬프트",
        "description": "모든 텍스트 생성 에이전트가 공통으로 사용하는 시스템 역할 지시입니다. 톤, 언어, 문체 가이드가 포함됩니다.",
        "content": (
            "You are {agent_name}. Write natural {language} content for marketers. "
            "Tone must be: {tone}. Avoid hype words and provide practical details."
        ),
    },
    "task.newsletter": {
        "label": "뉴스레터 작업 지시",
        "description": "newsletter 에이전트에 전달되는 작업 지시문입니다. 분량/형식 요구를 조정할 때 사용합니다.",
        "content": "15,000자 내외 인터뷰형 뉴스레터를 작성해 주세요.",
    },
    "task.blog": {
        "label": "블로그 작업 지시",
        "description": "blog 에이전트의 목표 형식과 길이를 제어하는 지시문입니다.",
        "content": "SEO 친화적 블로그 글(3,000~5,000자)을 작성해 주세요.",
    },
    "task.linkedin": {
        "label": "링크드인 작업 지시",
        "description": "linkedin 에이전트의 톤과 문서 성격(전문가형 포스트)을 정의합니다.",
        "content": "링크드인 전문가 톤 포스트를 작성해 주세요.",
    },
    "task.youtube-script": {
        "label": "유튜브 대본 작업 지시",
        "description": "youtube-script 에이전트의 출력 형식(타임스탬프 포함 대본)을 지정합니다.",
        "content": "타임스탬프 포함 유튜브 대본을 작성해 주세요.",
    },
    "task.thread": {
        "label": "스레드 작업 지시",
        "description": "threads 생성 시 각 게시글의 길이/구조를 정의합니다. {index} 치환 변수를 사용합니다.",
        "content": "X 스레드 {index}/10: 280자 이내로 작성해 주세요.",
    },
    "task.shorts-script": {
        "label": "쇼츠 대본 작업 지시",
        "description": "shorts-scripts 생성 시 후킹/본문/CTA 구조를 제어합니다. {index} 치환 변수를 사용합니다.",
        "content": "쇼츠 대본 {index}/3: 후킹-본문-CTA 60초 구조로 작성해 주세요.",
    },
    "visual.card.cover": {
        "label": "카드뉴스 표지 프롬프트",
        "description": "카드뉴스 1페이지(커버) 이미지 생성 프롬프트입니다.",
        "content": "Instagram card-news cover. Strong hook title, high contrast, modern marketing style.",
    },
    "visual.card.body": {
        "label": "카드뉴스 본문 프롬프트",
        "description": "카드뉴스 본문 슬라이드 공통 프롬프트입니다. {message} 치환 변수를 사용합니다.",
        "content": "Instagram card-news slide focused on: {message}. Clean layout, iconography, readable Korean text.",
    },
    "visual.card.cta": {
        "label": "카드뉴스 CTA 프롬프트",
        "description": "카드뉴스 마지막 슬라이드(CTA) 프롬프트입니다.",
        "content": "Instagram card-news last slide. Clear CTA. Bold typography. Marketing action oriented.",
    },
    "visual.thumbnail": {
        "label": "썸네일 프롬프트",
        "description": "썸네일 이미지 생성 프롬프트입니다. {topic} 치환 변수로 핵심 주제를 삽입합니다.",
        "content": "YouTube thumbnail 1280x720. Big Korean title around '{topic}'. Strong contrast, human-friendly, no clutter.",
    },
    "chart.overview.title": {
        "label": "차트 개요 제목",
        "description": "charts/overview.png 상단 타이틀 텍스트입니다.",
        "content": "핵심 메시지 우선순위 차트",
    },
    "chart.trend.title": {
        "label": "차트 추세 제목",
        "description": "charts/trend.png 상단 타이틀 텍스트입니다.",
        "content": "실행 임팩트 추세",
    },
}

DEFAULT_PROMPT_VARIABLES: dict[str, list[dict[str, Any]]] = {
    "planner.brief-template": [
        {
            "name": "source_ref",
            "value_type": "INPUT_REQUIRED",
            "default_value": "",
            "description": "생성 요청 시 입력 소스 식별자(예: URL, 문서명).",
            "ai_instruction": "",
            "sort_order": 10,
        },
        {
            "name": "source_type",
            "value_type": "INPUT_REQUIRED",
            "default_value": "markdown",
            "description": "입력 소스 타입입니다. 예: youtube, web, markdown.",
            "ai_instruction": "",
            "sort_order": 20,
        },
        {
            "name": "title",
            "value_type": "INPUT_REQUIRED",
            "default_value": "제목 없음",
            "description": "원문 제목입니다.",
            "ai_instruction": "",
            "sort_order": 30,
        },
        {
            "name": "language",
            "value_type": "INPUT_WITH_DEFAULT",
            "default_value": "ko",
            "description": "콘텐츠 생성 언어. 비어 있으면 기본값 사용.",
            "ai_instruction": "",
            "sort_order": 40,
        },
        {
            "name": "tone",
            "value_type": "INPUT_WITH_DEFAULT",
            "default_value": "친근하고 실용적, 실행 중심",
            "description": "콘텐츠 톤. 비어 있으면 기본값 사용.",
            "ai_instruction": "",
            "sort_order": 50,
        },
        {
            "name": "target_lines",
            "value_type": "AI_GENERATED",
            "default_value": "- 없음",
            "description": "타겟 산출물 섹션용 Markdown bullet 목록입니다.",
            "ai_instruction": "입력된 타겟 목록을 기반으로 실행 우선순위가 드러나게 bullet 3~7줄로 정리하세요.",
            "sort_order": 60,
        },
        {
            "name": "key_lines",
            "value_type": "AI_GENERATED",
            "default_value": "- 핵심 메시지를 추출하지 못했습니다.",
            "description": "핵심 메시지 섹션용 Markdown bullet 목록입니다.",
            "ai_instruction": "원문과 제목을 기반으로 핵심 메시지 3~5개를 추출하고, 문장형 bullet로 작성하세요.",
            "sort_order": 70,
        },
        {
            "name": "warning_lines",
            "value_type": "AI_GENERATED",
            "default_value": "- 없음",
            "description": "주의/제약 섹션용 Markdown bullet 목록입니다.",
            "ai_instruction": "입력 경고와 리스크를 통합해 마케터 관점의 주의사항 bullet 1~5개를 작성하세요.",
            "sort_order": 80,
        },
        {
            "name": "source_preview",
            "value_type": "AI_GENERATED",
            "default_value": "요약 정보가 없습니다.",
            "description": "원문 요약 본문입니다.",
            "ai_instruction": "원문을 4~6문장으로 요약하고 실행 가능한 인사이트를 포함하세요.",
            "sort_order": 90,
        },
    ],
    "system.text-agent": [
        {
            "name": "agent_name",
            "value_type": "INPUT_REQUIRED",
            "default_value": "marketing-writer",
            "description": "에이전트 이름입니다.",
            "ai_instruction": "",
            "sort_order": 10,
        },
        {
            "name": "language",
            "value_type": "INPUT_WITH_DEFAULT",
            "default_value": "ko",
            "description": "콘텐츠 언어 기본값입니다.",
            "ai_instruction": "",
            "sort_order": 20,
        },
        {
            "name": "tone",
            "value_type": "INPUT_WITH_DEFAULT",
            "default_value": "친근하고 실용적, 실행 중심",
            "description": "텍스트 생성 기본 톤입니다.",
            "ai_instruction": "",
            "sort_order": 30,
        },
    ],
    "task.thread": [
        {
            "name": "index",
            "value_type": "INPUT_REQUIRED",
            "default_value": "1",
            "description": "스레드 순번 변수입니다.",
            "ai_instruction": "",
            "sort_order": 10,
        },
    ],
    "task.shorts-script": [
        {
            "name": "index",
            "value_type": "INPUT_REQUIRED",
            "default_value": "1",
            "description": "쇼츠 스크립트 순번 변수입니다.",
            "ai_instruction": "",
            "sort_order": 10,
        },
    ],
    "visual.card.cover": [
        {
            "name": "topic",
            "value_type": "INPUT_WITH_DEFAULT",
            "default_value": "입력 원문의 핵심 주제",
            "description": "카드뉴스 커버 중심 주제입니다.",
            "ai_instruction": "",
            "sort_order": 10,
        },
    ],
    "visual.card.body": [
        {
            "name": "message",
            "value_type": "INPUT_WITH_DEFAULT",
            "default_value": "핵심 메시지를 시각적으로 전달",
            "description": "카드뉴스 본문 슬라이드 메시지입니다.",
            "ai_instruction": "",
            "sort_order": 10,
        },
        {
            "name": "topic",
            "value_type": "INPUT_WITH_DEFAULT",
            "default_value": "입력 원문의 핵심 주제",
            "description": "카드뉴스 본문 슬라이드 주제입니다.",
            "ai_instruction": "",
            "sort_order": 20,
        },
    ],
    "visual.card.cta": [
        {
            "name": "message",
            "value_type": "INPUT_WITH_DEFAULT",
            "default_value": "행동 유도 메시지",
            "description": "카드뉴스 CTA 메시지입니다.",
            "ai_instruction": "",
            "sort_order": 10,
        },
    ],
    "visual.thumbnail": [
        {
            "name": "topic",
            "value_type": "INPUT_WITH_DEFAULT",
            "default_value": "마케팅 자동화 핵심 포인트",
            "description": "썸네일 중심 주제입니다.",
            "ai_instruction": "",
            "sort_order": 10,
        },
    ],
}


def normalize_prompt_variable_type(raw: str) -> str:
    normalized = (raw or "").strip().upper()
    if normalized in PROMPT_VARIABLE_TYPES:
        return normalized
    return "INPUT_REQUIRED"


def ensure_default_prompts() -> None:
    now = dt.datetime.now(dt.timezone.utc)
    with session_scope() as session:
        existing = {
            prompt.key: prompt for prompt in session.exec(select(PromptTemplate)).all()
        }
        existing_variables = {
            (item.prompt_key, item.name): item for item in session.exec(select(PromptVariable)).all()
        }
        changed = False
        for key, item in DEFAULT_PROMPTS.items():
            label = item["label"]
            content = item["content"]
            if key in existing:
                continue
            session.add(
                PromptTemplate(
                    key=key,
                    label=label,
                    content=content,
                    created_at=now,
                    updated_at=now,
                )
            )
            changed = True
        for prompt_key, variable_items in DEFAULT_PROMPT_VARIABLES.items():
            for item in variable_items:
                name = str(item.get("name", "")).strip()
                if not name:
                    continue
                if (prompt_key, name) in existing_variables:
                    continue
                session.add(
                    PromptVariable(
                        prompt_key=prompt_key,
                        name=name,
                        value_type=normalize_prompt_variable_type(str(item.get("value_type", "INPUT_REQUIRED"))),
                        default_value=str(item.get("default_value", "")),
                        description=str(item.get("description", "")),
                        ai_instruction=str(item.get("ai_instruction", "")),
                        sort_order=int(item.get("sort_order", 0)),
                        created_at=now,
                        updated_at=now,
                    )
                )
                changed = True
        if changed:
            session.commit()


def load_prompt_map() -> dict[str, str]:
    with session_scope() as session:
        prompts = session.exec(select(PromptTemplate)).all()
    values = {item.key: item.content for item in prompts}
    for key, item in DEFAULT_PROMPTS.items():
        values.setdefault(key, item["content"])
    return values


def list_prompt_templates(session: Session) -> list[PromptTemplate]:
    return session.exec(select(PromptTemplate).order_by(PromptTemplate.key.asc())).all()


def update_prompt_template(session: Session, key: str, content: str) -> PromptTemplate:
    now = dt.datetime.now(dt.timezone.utc)
    prompt = session.get(PromptTemplate, key)
    if prompt is None:
        label = DEFAULT_PROMPTS.get(key, {"label": key}).get("label", key)
        prompt = PromptTemplate(key=key, label=label, content=content, created_at=now, updated_at=now)
    else:
        prompt.content = content
        prompt.updated_at = now
    session.add(prompt)
    session.commit()
    session.refresh(prompt)
    return prompt


def list_prompt_variables(session: Session, prompt_key: str | None = None) -> list[PromptVariable]:
    query = select(PromptVariable)
    if prompt_key:
        query = query.where(PromptVariable.prompt_key == prompt_key)
        query = query.order_by(PromptVariable.sort_order.asc(), PromptVariable.name.asc())
    else:
        query = query.order_by(
            PromptVariable.prompt_key.asc(),
            PromptVariable.sort_order.asc(),
            PromptVariable.name.asc(),
        )
    return session.exec(query).all()


def list_prompt_variables_by_key(session: Session) -> dict[str, list[PromptVariable]]:
    grouped: dict[str, list[PromptVariable]] = defaultdict(list)
    for variable in list_prompt_variables(session):
        grouped[variable.prompt_key].append(variable)
    return dict(grouped)


def upsert_prompt_variable(
    session: Session,
    *,
    prompt_key: str,
    name: str,
    value_type: str = "INPUT_REQUIRED",
    default_value: str = "",
    description: str = "",
    ai_instruction: str = "",
    sort_order: int = 0,
) -> PromptVariable:
    normalized_name = (name or "").strip()
    if not normalized_name:
        raise ValueError("name is required")
    now = dt.datetime.now(dt.timezone.utc)
    variable = session.get(PromptVariable, (prompt_key, normalized_name))
    if variable is None:
        variable = PromptVariable(
            prompt_key=prompt_key,
            name=normalized_name,
            created_at=now,
            updated_at=now,
        )
    variable.value_type = normalize_prompt_variable_type(value_type)
    variable.default_value = (default_value or "").strip()
    variable.description = (description or "").strip()
    variable.ai_instruction = (ai_instruction or "").strip()
    variable.sort_order = int(sort_order)
    variable.updated_at = now
    session.add(variable)
    session.commit()
    session.refresh(variable)
    return variable


def delete_prompt_variable(session: Session, *, prompt_key: str, name: str) -> bool:
    normalized_name = (name or "").strip()
    if not normalized_name:
        return False
    variable = session.get(PromptVariable, (prompt_key, normalized_name))
    if variable is None:
        return False
    session.delete(variable)
    session.commit()
    return True


def load_prompt_variable_map() -> dict[str, list[dict[str, Any]]]:
    with session_scope() as session:
        rows = list_prompt_variables(session)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row.prompt_key].append(
            {
                "name": row.name,
                "value_type": normalize_prompt_variable_type(row.value_type),
                "default_value": row.default_value,
                "description": row.description,
                "ai_instruction": row.ai_instruction,
                "sort_order": row.sort_order,
            }
        )

    for prompt_key, items in DEFAULT_PROMPT_VARIABLES.items():
        bucket = grouped[prompt_key]
        existing_names = {str(item.get("name", "")).strip() for item in bucket}
        for default_item in items:
            name = str(default_item.get("name", "")).strip()
            if not name or name in existing_names:
                continue
            bucket.append(
                {
                    "name": name,
                    "value_type": normalize_prompt_variable_type(str(default_item.get("value_type", "INPUT_REQUIRED"))),
                    "default_value": str(default_item.get("default_value", "")),
                    "description": str(default_item.get("description", "")),
                    "ai_instruction": str(default_item.get("ai_instruction", "")),
                    "sort_order": int(default_item.get("sort_order", 0)),
                }
            )
    for bucket in grouped.values():
        bucket.sort(key=lambda item: (int(item.get("sort_order", 0)), str(item.get("name", ""))))
    return dict(grouped)


def resolve_prompt_variable_values(
    prompt_key: str,
    runtime_values: dict[str, str],
    variable_map: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, str]:
    values = {str(key): str(value) for key, value in runtime_values.items()}
    variables = (variable_map or load_prompt_variable_map()).get(prompt_key, [])
    for item in variables:
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        value_type = normalize_prompt_variable_type(str(item.get("value_type", "INPUT_REQUIRED")))
        current = str(values.get(name, "")).strip()
        default_value = str(item.get("default_value", "")).strip()
        if value_type == "INPUT_WITH_DEFAULT":
            values[name] = current or default_value
            continue
        if value_type == "INPUT_REQUIRED":
            values[name] = current or default_value
            continue
        values[name] = current or default_value
    return values


def render_prompt_with_variables(
    prompt_key: str,
    template: str,
    runtime_values: dict[str, str],
    variable_map: dict[str, list[dict[str, Any]]] | None = None,
) -> str:
    resolved_values = resolve_prompt_variable_values(
        prompt_key=prompt_key,
        runtime_values=runtime_values,
        variable_map=variable_map,
    )
    rendered = template
    for key, value in resolved_values.items():
        rendered = rendered.replace("{" + key + "}", value)
    return rendered


def get_prompt_descriptions() -> dict[str, str]:
    return {key: item.get("description", "") for key, item in DEFAULT_PROMPTS.items()}
