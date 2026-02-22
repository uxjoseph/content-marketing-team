# 멀티 에이전트 마케팅 웹 도구 (로컬 PoC) - ENV 설정 가이드

이 프로젝트는 로컬에서 동작하는 무인증 PoC 웹 도구입니다.  
마케터가 URL 1개를 입력하면 콘텐츠 생성 파이프라인을 실행하고 결과물을 `outputs/`에 저장합니다.

## 1) 사전 요구사항

- Python 3.10+
- `ffmpeg` / `ffprobe` 설치
- 인터넷 연결 (실제 URL 수집, 모델/API 호출 시)
- 선택 사항:
  - OpenAI API Key
  - Anthropic API Key
  - Nanobanana API URL/Key (비주얼 실제 생성용)

## 2) 설치

```bash
cd /Users/limchaesung/Github/team-auruda/content-marketing-team
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 3) ENV 파일 생성

`.env.example`을 복사해 `.env`를 만드세요.

```bash
cp .env.example .env
```

## 4) 필수/권장 ENV 값

아래 항목을 우선 설정하세요.

### 공통

- `APP_NAME`: 앱 이름
- `DATABASE_URL`: SQLite 경로 (기본값 사용 가능)
- `OUTPUT_ROOT`: 결과물 저장 경로
- `RETENTION_DAYS`: 자동 정리 보관일 (기본 7)
- `MAX_JOBS`: 최대 보관 작업 수 (기본 200)
- `WORKER_POLL_SECONDS`: 워커 폴링 주기

### 기본 콘텐츠 옵션

- `DEFAULT_LANGUAGE`: 기본 언어 (권장 `ko`)
- `DEFAULT_TONE`: 기본 톤
- `DEFAULT_TARGETS`: 기본 타겟 목록  
  기본값은 `shorts-videos` 제외 상태입니다.

### LLM

- `LLM_PROVIDER`: 기본 제공자 이름 (`openai` 또는 `anthropic`)
- `OPENAI_API_KEY`, `OPENAI_MODEL`
- `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`

둘 중 하나만 유효해도 텍스트 생성이 가능하며, 둘 다 없으면 mock fallback 텍스트가 생성됩니다.

### Nanobanana (비주얼)

- `NANOBANANA_API_URL`: 이미지 생성 API 엔드포인트
- `NANOBANANA_API_KEY`: API 키
- `NANOBANANA_MODEL`: 모델명

값이 없으면 비주얼 단계가 실패하고 작업은 `PARTIAL_SUCCESS`가 될 수 있습니다.  
`mock_mode=true` 작업은 플레이스홀더 PNG를 생성합니다.

### Whisper

- `WHISPER_MODEL` (예: `small`)
- `WHISPER_DEVICE` (예: `cpu`)
- `WHISPER_COMPUTE_TYPE` (예: `int8`)
- `REQUEST_TIMEOUT_SECONDS`

## 5) 실행

단일 워커로 실행하세요.

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
```

접속:

- UI: `http://localhost:8000`
- API docs: `http://localhost:8000/docs`

## 6) mock 모드와 실제 모드

### mock 모드

- 작업 생성 시 `mock_mode=true`
- 외부 API 키 없이 동작 확인 가능
- 비주얼/영상은 테스트용 산출물 생성

### 실제 모드

- `mock_mode=false`
- URL 수집/전사/LLM/비주얼 API가 실제 호출됨
- 시스템 의존성(`ffmpeg`, `yt-dlp`)과 API 키가 필요

## 7) 출력 경로

작업별 결과물:

```text
/Users/limchaesung/Github/team-auruda/content-marketing-team/outputs/{job_id}/
```

대표 파일:

- `brief.md`
- `blog.md`, `newsletter.md`, `linkedin.md`, `youtube-script.md`
- `threads/thread-*.md`
- `shorts-scripts/shorts-*.md`
- `visuals/card-news/slide-*.png`
- `visuals/thumbnail.png`
- `shorts-videos/shorts-*.mp4`
- `review-report.md`

## 8) 최소 동작 확인 (API)

```bash
curl -X POST "http://localhost:8000/api/jobs" \
  -H "Content-Type: application/json" \
  -d '{
    "source_url":"https://example.com",
    "targets":["blog","visuals"],
    "tone":"친근하고 실용적",
    "language":"ko",
    "mock_mode":true
  }'
```

응답의 `job_id`로 상태 조회:

```bash
curl "http://localhost:8000/api/jobs/{job_id}"
```

## 9) 문제 해결

- `ffmpeg not found`: 시스템에 `ffmpeg`/`ffprobe` 설치 필요
- 비주얼 실패: `NANOBANANA_API_URL`, `NANOBANANA_API_KEY` 확인
- 쇼츠 실패: YouTube 원본 다운로드 가능 여부/네트워크 확인
- `PARTIAL_SUCCESS`: `review-report.md`의 실패/경고 섹션 확인
