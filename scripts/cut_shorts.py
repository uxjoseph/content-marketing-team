#!/usr/bin/env python3
"""
쇼츠 클립 추출 스크립트
ffmpeg를 사용하여 영상을 9:16 비율로 크롭하고 클리핑합니다.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def parse_time(time_str: str) -> float:
    """
    시간 문자열을 초로 변환합니다.

    Args:
        time_str: "MM:SS" 또는 "HH:MM:SS" 또는 초 단위 숫자

    Returns:
        초 단위 float
    """
    if isinstance(time_str, (int, float)):
        return float(time_str)

    parts = time_str.split(":")
    if len(parts) == 1:
        return float(parts[0])
    elif len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    elif len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    else:
        raise ValueError(f"Invalid time format: {time_str}")


def get_video_dimensions(video_path: str) -> Tuple[int, int]:
    """
    영상의 해상도를 가져옵니다.

    Args:
        video_path: 영상 파일 경로

    Returns:
        (width, height) 튜플
    """
    cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "json",
        video_path,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, check=True)
        data = json.loads(result.stdout)
        stream = data["streams"][0]
        return stream["width"], stream["height"]
    except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError) as e:
        print(f"❌ 영상 정보 추출 실패: {e}")
        sys.exit(1)


def calculate_crop(width: int, height: int) -> Tuple[int, int, int, int]:
    """
    16:9에서 9:16으로 크롭할 영역을 계산합니다.

    Args:
        width: 원본 너비
        height: 원본 높이

    Returns:
        (crop_width, crop_height, x_offset, y_offset) 튜플
    """
    # 목표 비율: 9:16
    target_ratio = 9 / 16

    # 세로 기준으로 가로 계산
    crop_height = height
    crop_width = int(height * target_ratio)

    # 가로가 원본보다 크면 가로 기준으로 재계산
    if crop_width > width:
        crop_width = width
        crop_height = int(width / target_ratio)

    # 중앙 정렬 오프셋
    x_offset = (width - crop_width) // 2
    y_offset = (height - crop_height) // 2

    return crop_width, crop_height, x_offset, y_offset


def extract_clip(
    input_path: str,
    output_path: str,
    start_time: float,
    end_time: float,
    crop: Optional[Tuple[int, int, int, int]] = None,
    subtitle_path: Optional[str] = None,
) -> str:
    """
    영상에서 클립을 추출합니다.

    Args:
        input_path: 입력 영상 경로
        output_path: 출력 영상 경로
        start_time: 시작 시간 (초)
        end_time: 종료 시간 (초)
        crop: (width, height, x, y) 크롭 설정
        subtitle_path: 자막 파일 경로 (선택)

    Returns:
        출력 파일 경로
    """
    duration = end_time - start_time

    # 기본 ffmpeg 명령어
    cmd = [
        "ffmpeg",
        "-ss", str(start_time),  # 시작 시간
        "-i", input_path,
        "-t", str(duration),  # 길이
    ]

    # 필터 체인 구성
    filters = []

    # 크롭 필터
    if crop:
        w, h, x, y = crop
        filters.append(f"crop={w}:{h}:{x}:{y}")

    # 출력 해상도 (1080x1920)
    filters.append("scale=1080:1920:force_original_aspect_ratio=decrease")
    filters.append("pad=1080:1920:(ow-iw)/2:(oh-ih)/2")

    # 자막 필터 (선택)
    if subtitle_path and os.path.exists(subtitle_path):
        # 자막 스타일 설정
        subtitle_style = (
            "FontName=NanumGothic Bold,"
            "FontSize=24,"
            "PrimaryColour=&HFFFFFF,"
            "OutlineColour=&H000000,"
            "Outline=2,"
            "Shadow=1,"
            "MarginV=50"
        )
        filters.append(f"subtitles={subtitle_path}:force_style='{subtitle_style}'")

    # 필터 적용
    if filters:
        cmd.extend(["-vf", ",".join(filters)])

    # 출력 설정
    cmd.extend([
        "-c:v", "libx264",  # H.264 코덱
        "-preset", "fast",  # 인코딩 속도
        "-crf", "23",  # 품질 (낮을수록 고품질)
        "-c:a", "aac",  # AAC 오디오
        "-b:a", "128k",  # 오디오 비트레이트
        "-movflags", "+faststart",  # 웹 스트리밍 최적화
        "-y",  # 덮어쓰기
        output_path,
    ])

    try:
        print(f"   ⏳ 클립 추출 중: {start_time:.1f}s - {end_time:.1f}s")
        subprocess.run(cmd, check=True, capture_output=True)
        print(f"   ✅ 완료: {output_path}")
        return output_path
    except subprocess.CalledProcessError as e:
        print(f"   ❌ 클립 추출 실패: {e.stderr.decode()}")
        return None


def parse_script_file(script_path: str) -> Optional[Dict]:
    """
    쇼츠 대본 파일에서 시간 정보를 추출합니다.

    Args:
        script_path: 대본 파일 경로

    Returns:
        시간 정보 딕셔너리 또는 None
    """
    if not os.path.exists(script_path):
        return None

    with open(script_path, "r", encoding="utf-8") as f:
        content = f.read()

    # "참조 구간: 시작시간 - 종료시간" 패턴 찾기
    pattern = r"참조\s*구간\s*:\s*(\d+:?\d*\.?\d*)\s*-\s*(\d+:?\d*\.?\d*)"
    match = re.search(pattern, content)

    if match:
        return {
            "start": parse_time(match.group(1)),
            "end": parse_time(match.group(2)),
        }

    return None


def find_best_segments(
    transcript: Dict,
    target_duration: float = 60,
    num_clips: int = 3,
) -> List[Dict]:
    """
    트랜스크립트에서 최적의 클립 구간을 찾습니다.

    Args:
        transcript: 트랜스크립트 딕셔너리
        target_duration: 목표 클립 길이 (초)
        num_clips: 생성할 클립 수

    Returns:
        클립 정보 리스트
    """
    segments = transcript.get("segments", [])
    if not segments:
        return []

    total_duration = transcript.get("duration", 0)
    clips = []

    # 균등하게 구간 분할
    interval = total_duration / (num_clips + 1)

    for i in range(num_clips):
        target_time = interval * (i + 1)

        # 가장 가까운 세그먼트 찾기
        best_segment = min(
            segments,
            key=lambda s: abs(s["start"] - target_time)
        )

        start = max(0, best_segment["start"] - 5)  # 5초 여유
        end = min(total_duration, start + target_duration)

        clips.append({
            "index": i + 1,
            "start": start,
            "end": end,
            "duration": end - start,
        })

    return clips


def main():
    parser = argparse.ArgumentParser(
        description="쇼츠 클립 추출",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  python cut_shorts.py --input video.mp4 --transcript transcript.json --output ./shorts/
  python cut_shorts.py -i video.mp4 -t transcript.json -s ./scripts/ -o ./shorts/

수동 구간 지정:
  python cut_shorts.py -i video.mp4 --clips "0:30-1:30,2:00-3:00,5:00-6:00" -o ./shorts/
        """,
    )

    parser.add_argument(
        "--input", "-i", required=True, help="입력 영상 파일 경로"
    )
    parser.add_argument(
        "--transcript", "-t", help="트랜스크립트 JSON 파일 경로"
    )
    parser.add_argument(
        "--scripts", "-s", help="쇼츠 대본 폴더 경로"
    )
    parser.add_argument(
        "--output", "-o", required=True, help="출력 폴더 경로"
    )
    parser.add_argument(
        "--clips", "-c", help="수동 클립 구간 (예: '0:30-1:30,2:00-3:00')"
    )
    parser.add_argument(
        "--subtitle", help="자막 파일 경로 (.srt)"
    )
    parser.add_argument(
        "--duration", "-d", type=int, default=60, help="클립 길이 (초, 기본값: 60)"
    )

    args = parser.parse_args()

    # 입력 파일 확인
    if not os.path.exists(args.input):
        print(f"❌ 입력 파일을 찾을 수 없습니다: {args.input}")
        sys.exit(1)

    print("=" * 50)
    print("🎬 쇼츠 클립 추출 시작")
    print("=" * 50)

    # 영상 정보 확인
    width, height = get_video_dimensions(args.input)
    print(f"📐 원본 해상도: {width}x{height}")

    # 크롭 계산
    crop = calculate_crop(width, height)
    print(f"✂️  크롭 설정: {crop[0]}x{crop[1]} at ({crop[2]}, {crop[3]})")

    # 출력 폴더 생성
    output_path = Path(args.output)
    output_path.mkdir(parents=True, exist_ok=True)

    # 클립 구간 결정
    clips = []

    # 1. 수동 지정
    if args.clips:
        for i, clip_str in enumerate(args.clips.split(","), 1):
            start_str, end_str = clip_str.strip().split("-")
            clips.append({
                "index": i,
                "start": parse_time(start_str),
                "end": parse_time(end_str),
            })

    # 2. 대본 파일에서 추출
    elif args.scripts:
        scripts_path = Path(args.scripts)
        for i in range(1, 4):
            script_file = scripts_path / f"shorts-{i:02d}.md"
            info = parse_script_file(str(script_file))
            if info:
                clips.append({
                    "index": i,
                    "start": info["start"],
                    "end": info["end"],
                })

    # 3. 트랜스크립트에서 자동 추출
    elif args.transcript and os.path.exists(args.transcript):
        with open(args.transcript, "r", encoding="utf-8") as f:
            transcript = json.load(f)
        clips = find_best_segments(transcript, args.duration, 3)

    # 클립이 없으면 기본값 사용
    if not clips:
        print("⚠️ 클립 구간을 찾을 수 없어 기본값을 사용합니다.")
        clips = [
            {"index": 1, "start": 30, "end": 90},
            {"index": 2, "start": 120, "end": 180},
            {"index": 3, "start": 240, "end": 300},
        ]

    print(f"\n📋 추출할 클립 {len(clips)}개:")
    for clip in clips:
        print(f"   [{clip['index']}] {clip['start']:.1f}s - {clip['end']:.1f}s")

    # 클립 추출
    print("\n" + "-" * 50)
    results = []

    for clip in clips:
        output_file = output_path / f"shorts-{clip['index']:02d}.mp4"
        result = extract_clip(
            args.input,
            str(output_file),
            clip["start"],
            clip["end"],
            crop,
            args.subtitle,
        )
        if result:
            results.append(result)

    print("-" * 50)
    print(f"\n✅ 쇼츠 클립 {len(results)}개 생성 완료!")
    for r in results:
        print(f"   📹 {r}")
    print("=" * 50)

    return results


if __name__ == "__main__":
    main()
