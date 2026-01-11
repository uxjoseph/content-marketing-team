#!/usr/bin/env python3
"""
음성 인식 및 자막 생성 스크립트
OpenAI Whisper를 사용하여 영상에서 음성을 텍스트로 변환합니다.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

try:
    import whisper
except ImportError:
    print("Error: whisper가 설치되지 않았습니다.")
    print("설치: pip install openai-whisper")
    sys.exit(1)


def extract_audio(video_path: str, audio_path: str) -> str:
    """
    영상에서 오디오를 추출합니다.

    Args:
        video_path: 입력 영상 파일 경로
        audio_path: 출력 오디오 파일 경로

    Returns:
        추출된 오디오 파일 경로
    """
    print(f"🎵 오디오 추출 중: {video_path}")

    # ffmpeg 명령어
    cmd = [
        "ffmpeg",
        "-i", video_path,
        "-vn",  # 비디오 제외
        "-acodec", "pcm_s16le",  # PCM 16-bit
        "-ar", "16000",  # 16kHz 샘플레이트 (Whisper 권장)
        "-ac", "1",  # 모노
        "-y",  # 덮어쓰기
        audio_path,
    ]

    try:
        subprocess.run(cmd, check=True, capture_output=True)
        print(f"   ✅ 오디오 추출 완료: {audio_path}")
        return audio_path
    except subprocess.CalledProcessError as e:
        print(f"   ❌ 오디오 추출 실패: {e.stderr.decode()}")
        sys.exit(1)
    except FileNotFoundError:
        print("   ❌ ffmpeg가 설치되지 않았습니다.")
        print("   설치: brew install ffmpeg (macOS) 또는 apt-get install ffmpeg (Ubuntu)")
        sys.exit(1)


def transcribe_audio(
    audio_path: str,
    model_name: str = "base",
    language: str = "ko",
) -> Dict:
    """
    오디오를 텍스트로 변환합니다.

    Args:
        audio_path: 오디오 파일 경로
        model_name: Whisper 모델 이름 (tiny, base, small, medium, large)
        language: 언어 코드

    Returns:
        변환 결과 딕셔너리
    """
    print(f"🎤 음성 인식 중... (모델: {model_name})")
    print("   ⏳ 모델 로딩 중 (처음 실행 시 다운로드됨)...")

    # 모델 로드
    model = whisper.load_model(model_name)
    print(f"   ✅ 모델 로드 완료")

    # 음성 인식 실행
    print("   🔊 음성 인식 진행 중...")
    result = model.transcribe(
        audio_path,
        language=language,
        verbose=False,
        word_timestamps=True,  # 단어별 타임스탬프
    )

    print(f"   ✅ 음성 인식 완료")

    return result


def format_transcript(result: Dict) -> Dict:
    """
    Whisper 결과를 정형화된 포맷으로 변환합니다.

    Args:
        result: Whisper 변환 결과

    Returns:
        정형화된 트랜스크립트
    """
    segments = []

    for segment in result.get("segments", []):
        formatted_segment = {
            "id": segment.get("id"),
            "start": round(segment.get("start", 0), 2),
            "end": round(segment.get("end", 0), 2),
            "text": segment.get("text", "").strip(),
            "words": [],
        }

        # 단어별 타임스탬프 (있으면)
        if "words" in segment:
            for word in segment["words"]:
                formatted_segment["words"].append({
                    "word": word.get("word", "").strip(),
                    "start": round(word.get("start", 0), 2),
                    "end": round(word.get("end", 0), 2),
                })

        segments.append(formatted_segment)

    transcript = {
        "language": result.get("language", "unknown"),
        "duration": round(segments[-1]["end"], 2) if segments else 0,
        "text": result.get("text", "").strip(),
        "segments": segments,
    }

    return transcript


def save_transcript(transcript: Dict, output_path: str) -> str:
    """
    트랜스크립트를 JSON 파일로 저장합니다.

    Args:
        transcript: 트랜스크립트 딕셔너리
        output_path: 출력 파일 경로

    Returns:
        저장된 파일 경로
    """
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(transcript, f, ensure_ascii=False, indent=2)

    print(f"💾 트랜스크립트 저장 완료: {output_path}")
    return str(output_file)


def generate_srt(transcript: Dict, output_path: str) -> str:
    """
    SRT 자막 파일을 생성합니다.

    Args:
        transcript: 트랜스크립트 딕셔너리
        output_path: 출력 파일 경로 (.srt)

    Returns:
        저장된 파일 경로
    """
    def format_time(seconds: float) -> str:
        """초를 SRT 시간 형식으로 변환"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds - int(seconds)) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

    srt_content = []
    for i, segment in enumerate(transcript["segments"], 1):
        start_time = format_time(segment["start"])
        end_time = format_time(segment["end"])
        text = segment["text"]

        srt_content.append(f"{i}")
        srt_content.append(f"{start_time} --> {end_time}")
        srt_content.append(text)
        srt_content.append("")  # 빈 줄

    output_file = Path(output_path)
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("\n".join(srt_content))

    print(f"📝 SRT 자막 저장 완료: {output_path}")
    return str(output_file)


def main():
    parser = argparse.ArgumentParser(
        description="영상 음성 인식 및 자막 생성",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  python transcribe.py --input video.mp4 --output transcript.json
  python transcribe.py -i video.mp4 -o transcript.json --model medium --language ko

모델 선택:
  tiny   - 가장 빠름, 정확도 낮음 (~1GB VRAM)
  base   - 빠름, 적당한 정확도 (~1GB VRAM) [기본값]
  small  - 균형잡힌 속도/정확도 (~2GB VRAM)
  medium - 높은 정확도 (~5GB VRAM)
  large  - 최고 정확도, 가장 느림 (~10GB VRAM)
        """,
    )

    parser.add_argument(
        "--input", "-i", required=True, help="입력 영상 파일 경로"
    )
    parser.add_argument(
        "--output", "-o", required=True, help="출력 JSON 파일 경로"
    )
    parser.add_argument(
        "--model", "-m", default="base",
        choices=["tiny", "base", "small", "medium", "large"],
        help="Whisper 모델 (기본값: base)"
    )
    parser.add_argument(
        "--language", "-l", default="ko", help="언어 코드 (기본값: ko)"
    )
    parser.add_argument(
        "--srt", "-s", action="store_true", help="SRT 자막 파일도 생성"
    )

    args = parser.parse_args()

    # 입력 파일 확인
    if not os.path.exists(args.input):
        print(f"❌ 입력 파일을 찾을 수 없습니다: {args.input}")
        sys.exit(1)

    print("=" * 50)
    print("🎬 영상 음성 인식 시작")
    print("=" * 50)

    # 1. 오디오 추출
    audio_path = args.input.rsplit(".", 1)[0] + "_audio.wav"
    extract_audio(args.input, audio_path)

    # 2. 음성 인식
    result = transcribe_audio(audio_path, args.model, args.language)

    # 3. 결과 포맷팅
    transcript = format_transcript(result)

    # 4. JSON 저장
    save_transcript(transcript, args.output)

    # 5. SRT 저장 (옵션)
    if args.srt:
        srt_path = args.output.rsplit(".", 1)[0] + ".srt"
        generate_srt(transcript, srt_path)

    # 6. 임시 오디오 파일 정리
    if os.path.exists(audio_path):
        os.remove(audio_path)
        print(f"🧹 임시 파일 정리: {audio_path}")

    print("=" * 50)
    print("✅ 음성 인식 완료!")
    print(f"   전체 길이: {transcript['duration']}초")
    print(f"   세그먼트 수: {len(transcript['segments'])}개")
    print("=" * 50)

    return args.output


if __name__ == "__main__":
    main()
