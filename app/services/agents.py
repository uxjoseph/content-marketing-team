from __future__ import annotations

import textwrap
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from app.core.config import Settings
from app.services.providers.anthropic_provider import AnthropicProvider
from app.services.providers.base import TextProvider
from app.services.providers.openai_provider import OpenAIProvider
from app.services.prompt_store import load_prompt_map, render_prompt_with_variables

TEXT_TARGETS = {
    "newsletter",
    "blog",
    "linkedin",
    "threads",
    "youtube-script",
    "shorts-scripts",
}


class TextAgentService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.providers: list[TextProvider] = [
            OpenAIProvider(settings),
            AnthropicProvider(settings),
        ]

    def generate_text_assets(
        self,
        brief_text: str,
        source_text: str,
        output_dir: Path,
        targets: list[str],
        tone: str,
        language: str,
        mock_mode: bool = False,
    ) -> tuple[list[str], list[str]]:
        selected_targets = [target for target in targets if target in TEXT_TARGETS]
        artifacts: list[str] = []
        failures: list[str] = []
        if not selected_targets:
            return artifacts, failures
        prompt_map = load_prompt_map()

        (output_dir / "threads").mkdir(parents=True, exist_ok=True)
        (output_dir / "shorts-scripts").mkdir(parents=True, exist_ok=True)
        with ThreadPoolExecutor(max_workers=min(6, len(selected_targets))) as executor:
            future_map = {
                executor.submit(
                    self._generate_target,
                    target,
                    brief_text,
                    source_text,
                    output_dir,
                    tone,
                    language,
                    mock_mode,
                    prompt_map,
                ): target
                for target in selected_targets
            }
            for future in as_completed(future_map):
                target = future_map[future]
                try:
                    generated = future.result()
                    artifacts.extend(generated)
                except Exception as exc:
                    failures.append(f"{target}: {exc}")
        return artifacts, failures

    def _generate_target(
        self,
        target: str,
        brief_text: str,
        source_text: str,
        output_dir: Path,
        tone: str,
        language: str,
        mock_mode: bool,
        prompt_map: dict[str, str],
    ) -> list[str]:
        if target == "newsletter":
            content = self._generate_single_text(
                "newsletter-writer",
                brief_text,
                source_text,
                tone,
                language,
                self._prompt(
                    prompt_map,
                    "task.newsletter",
                    "15,000자 내외 인터뷰형 뉴스레터를 작성해 주세요.",
                ),
                mock_mode,
                prompt_map,
            )
            path = output_dir / "newsletter.md"
            path.write_text(content, encoding="utf-8")
            return [str(path.relative_to(output_dir))]

        if target == "blog":
            content = self._generate_single_text(
                "blog-writer",
                brief_text,
                source_text,
                tone,
                language,
                self._prompt(
                    prompt_map,
                    "task.blog",
                    "SEO 친화적 블로그 글(3,000~5,000자)을 작성해 주세요.",
                ),
                mock_mode,
                prompt_map,
            )
            path = output_dir / "blog.md"
            path.write_text(content, encoding="utf-8")
            return [str(path.relative_to(output_dir))]

        if target == "linkedin":
            content = self._generate_single_text(
                "linkedin-writer",
                brief_text,
                source_text,
                tone,
                language,
                self._prompt(
                    prompt_map,
                    "task.linkedin",
                    "링크드인 전문가 톤 포스트를 작성해 주세요.",
                ),
                mock_mode,
                prompt_map,
            )
            path = output_dir / "linkedin.md"
            path.write_text(content, encoding="utf-8")
            return [str(path.relative_to(output_dir))]

        if target == "youtube-script":
            content = self._generate_single_text(
                "youtube-scriptwriter",
                brief_text,
                source_text,
                tone,
                language,
                self._prompt(
                    prompt_map,
                    "task.youtube-script",
                    "타임스탬프 포함 유튜브 대본을 작성해 주세요.",
                ),
                mock_mode,
                prompt_map,
            )
            path = output_dir / "youtube-script.md"
            path.write_text(content, encoding="utf-8")
            return [str(path.relative_to(output_dir))]

        if target == "threads":
            artifacts: list[str] = []
            for index in range(10):
                task_template = self._prompt(
                    prompt_map,
                    "task.thread",
                    "X 스레드 {index}/10: 280자 이내로 작성해 주세요.",
                )
                content = self._generate_single_text(
                    "thread-writer",
                    brief_text,
                    source_text,
                    tone,
                    language,
                    render_prompt_with_variables(
                        prompt_key="task.thread",
                        template=task_template,
                        runtime_values={"index": str(index + 1)},
                    ),
                    mock_mode,
                    prompt_map,
                )
                path = output_dir / "threads" / f"thread-{index + 1:02d}.md"
                path.write_text(content, encoding="utf-8")
                artifacts.append(str(path.relative_to(output_dir)))
            return artifacts

        if target == "shorts-scripts":
            artifacts = []
            for index in range(3):
                task_template = self._prompt(
                    prompt_map,
                    "task.shorts-script",
                    "쇼츠 대본 {index}/3: 후킹-본문-CTA 60초 구조로 작성해 주세요.",
                )
                content = self._generate_single_text(
                    "shorts-scriptwriter",
                    brief_text,
                    source_text,
                    tone,
                    language,
                    render_prompt_with_variables(
                        prompt_key="task.shorts-script",
                        template=task_template,
                        runtime_values={"index": str(index + 1)},
                    ),
                    mock_mode,
                    prompt_map,
                )
                path = output_dir / "shorts-scripts" / f"shorts-{index + 1:02d}.md"
                path.write_text(content, encoding="utf-8")
                artifacts.append(str(path.relative_to(output_dir)))
            return artifacts

        return []

    def _generate_single_text(
        self,
        agent_name: str,
        brief_text: str,
        source_text: str,
        tone: str,
        language: str,
        task_instruction: str,
        mock_mode: bool,
        prompt_map: dict[str, str],
    ) -> str:
        if mock_mode:
            return self._mock_text(agent_name, task_instruction, brief_text, source_text)

        system_prompt_template = self._prompt(
            prompt_map,
            "system.text-agent",
            "You are {agent_name}. Write natural {language} content for marketers. "
            "Tone must be: {tone}. Avoid hype words and provide practical details.",
        )
        system_prompt = render_prompt_with_variables(
            prompt_key="system.text-agent",
            template=system_prompt_template,
            runtime_values={
                "agent_name": agent_name,
                "language": language,
                "tone": tone,
            },
        )
        user_prompt = (
            f"[Task]\n{task_instruction}\n\n"
            f"[Brief]\n{brief_text}\n\n"
            f"[Source]\n{source_text[:5000]}"
        )
        for provider in self.providers:
            if not provider.is_available():
                continue
            try:
                result = provider.generate(system_prompt, user_prompt)
                if result.strip():
                    return result.strip()
            except Exception:
                continue
        return self._mock_text(agent_name, task_instruction, brief_text, source_text)

    def _mock_text(self, agent_name: str, task: str, brief_text: str, source_text: str) -> str:
        preview = textwrap.shorten(source_text.replace("\n", " "), width=500, placeholder="...")
        return (
            f"# {agent_name}\n\n"
            f"## 작업 지시\n{task}\n\n"
            "## 핵심 정리\n"
            f"{textwrap.shorten(brief_text.replace(chr(10), ' '), width=500, placeholder='...')}\n\n"
            "## 초안\n"
            f"{preview}\n\n"
            "실제 API 키를 설정하면 모델 기반 결과가 생성됩니다."
        )

    def _prompt(self, prompt_map: dict[str, str], key: str, fallback: str) -> str:
        value = prompt_map.get(key)
        if value and value.strip():
            return value
        return fallback
