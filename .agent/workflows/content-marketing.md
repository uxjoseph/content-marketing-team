---
description: URL 입력 → 멀티 플랫폼 마케팅 콘텐츠 자동 생성. YouTube URL 또는 웹사이트 URL을 입력하면 뉴스레터, 블로그, 스레드, 링크드인, 유튜브 대본, 쇼츠 대본, 카드뉴스, 썸네일을 자동 생성합니다.
---

# 콘텐츠 마케팅 자동화 워크플로우

YouTube URL 또는 웹사이트 URL을 입력받아 멀티 플랫폼 마케팅 콘텐츠를 자동 생성합니다.

## 사전 요구사항

### 시스템 의존성 (쇼츠 영상 제작 시)
```bash
pip install yt-dlp openai-whisper
brew install ffmpeg  # macOS
```

---

## 워크플로우 실행 단계

### 1단계: URL 분석 및 콘텐츠 추출

1. 사용자에게 URL 입력 요청
2. URL 유형 판별:
   - YouTube (`youtube.com/watch?v=` 또는 `youtu.be/`)
   - 웹사이트 (그 외)
3. 콘텐츠 추출:
   - YouTube: `read_url_content` 또는 `browser_subagent`로 영상 정보/자막 추출
   - 웹사이트: `read_url_content`로 본문 추출

### 2단계: 브리프 작성

`guides/style-guide.md` 참조하여 `outputs/brief.md` 생성:

```markdown
# 콘텐츠 마케팅 브리프

## 원본 정보
- URL: [원본 URL]
- 유형: [YouTube / 웹사이트]
- 제목: [원본 제목]
- 추출일: [날짜]

## 핵심 메시지
### 메인 주제
[한 줄 요약]

### 핵심 포인트
1. [포인트 1]
2. [포인트 2]
3. [포인트 3]

## 타겟 오디언스
- 주요 타겟: 1인 창업가, IT/AI 관심층
- 핵심 니즈: [이 콘텐츠가 해결하는 문제]
- 가치 제안: [청중이 얻어갈 것]

## 원본 콘텐츠 요약
[추출된 전체 콘텐츠의 압축 버전 - 팩트체크용]
```

### 3단계: 텍스트 콘텐츠 생성 (순차 실행)

각 콘텐츠 유형별로 해당 가이드 파일을 참조하여 생성:

| 콘텐츠 | 가이드 | 출력 파일 |
|--------|--------|-----------|
| 뉴스레터 | `guides/newsletter-guide.md` | `outputs/newsletter.md` |
| 블로그 | `guides/blog-guide.md` | `outputs/blog.md` |
| 쇼츠 대본 | `guides/shorts-guide.md` | `outputs/shorts-scripts/shorts-01~03.md` |
| X 스레드 | `guides/thread-guide.md` | `outputs/threads/thread-01~10.md` |
| 링크드인 | `guides/linkedin-guide.md` | `outputs/linkedin.md` |
| 유튜브 대본 | `guides/youtube-script-guide.md` | `outputs/youtube-script.md` |

### 4단계: 비주얼 콘텐츠 (선택)

`guides/visual-guide.md` 참조:
- 카드뉴스 프롬프트 생성 (나노바나나 API용)
- 썸네일 프롬프트 생성

> 나노바나나 API가 설정되어 있으면 실제 이미지 생성, 없으면 프롬프트만 저장

### 5단계: 쇼츠 영상 제작 (선택, YouTube URL인 경우)

// turbo-all
```bash
# 1. 영상 다운로드
python scripts/download_video.py --url "[YOUTUBE_URL]" --output "temp/"

# 2. 자막 추출
python scripts/transcribe.py --input "temp/video.mp4" --output "temp/transcript.json"

# 3. 쇼츠 클립 생성
python scripts/cut_shorts.py \
  --input "temp/video.mp4" \
  --transcript "temp/transcript.json" \
  --scripts "outputs/shorts-scripts/" \
  --output "outputs/shorts-videos/"
```

### 6단계: 품질 검수

모든 콘텐츠 생성 후 `outputs/review-report.md` 작성:

#### 검수 체크리스트
- [ ] 브랜드 톤 일관성 ("요"체, 친근하고 실용적)
- [ ] AI틱 표현 없음 (혁신적인, 획기적인, 놀라운 등)
- [ ] 팩트 체크 (원본 대비)
- [ ] 플랫폼별 스펙 준수
- [ ] 한국어 자연스러움

---

## 출력 폴더 구조

```
outputs/
├── brief.md                    # 기획 브리프
├── newsletter.md               # 뉴스레터 (15,000-20,000자)
├── blog.md                     # 블로그 (3,000-5,000자)
├── linkedin.md                 # 링크드인 (1,500자 이내)
├── youtube-script.md           # 유튜브 대본
├── threads/
│   └── thread-01.md ~ thread-10.md  # X 스레드 (각 280자)
├── shorts-scripts/
│   └── shorts-01.md ~ shorts-03.md  # 쇼츠 대본 (각 60초)
├── visuals/
│   ├── card-news/              # 카드뉴스 이미지
│   └── thumbnail.png           # 썸네일
├── shorts-videos/
│   └── shorts-01.mp4 ~ shorts-03.mp4  # 쇼츠 영상
└── review-report.md            # 검수 리포트
```

---

## 참조 가이드

실행 시 다음 가이드 파일들을 참조:

- `guides/style-guide.md` - 공통 스타일 가이드 (톤앤매너, 금지 표현)
- `guides/newsletter-guide.md` - 뉴스레터 작성 가이드
- `guides/blog-guide.md` - 블로그 작성 가이드
- `guides/shorts-guide.md` - 쇼츠 대본 작성 가이드
- `guides/thread-guide.md` - X 스레드 작성 가이드
- `guides/linkedin-guide.md` - 링크드인 작성 가이드
- `guides/youtube-script-guide.md` - 유튜브 대본 작성 가이드
- `guides/visual-guide.md` - 비주얼 콘텐츠 가이드
