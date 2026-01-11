#!/usr/bin/env python3
"""
YouTube 영상 다운로드 스크립트
yt-dlp를 사용하여 최고 화질로 영상을 다운로드합니다.
"""

import argparse
import os
import sys
from pathlib import Path

try:
    import yt_dlp
except ImportError:
    print("Error: yt-dlp가 설치되지 않았습니다.")
    print("설치: pip install yt-dlp")
    sys.exit(1)


def download_video(url: str, output_dir: str, filename: str = "video") -> str:
    """
    YouTube 영상을 다운로드합니다.

    Args:
        url: YouTube 영상 URL
        output_dir: 저장할 디렉토리 경로
        filename: 저장할 파일명 (확장자 제외)

    Returns:
        다운로드된 파일의 전체 경로
    """
    # 출력 디렉토리 생성
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # 출력 파일 경로 템플릿
    output_template = str(output_path / f"{filename}.%(ext)s")

    # yt-dlp 옵션 설정
    ydl_opts = {
        # 최고 화질 + 오디오 병합
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "outtmpl": output_template,
        # 진행률 표시
        "progress_hooks": [progress_hook],
        # 자막 다운로드 (있으면)
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": ["ko", "en"],
        "subtitlesformat": "srt",
        # 메타데이터
        "writethumbnail": True,
        "writeinfojson": True,
        # 병합 설정
        "merge_output_format": "mp4",
        # 에러 처리
        "ignoreerrors": False,
        "no_warnings": False,
        # 재시도 설정
        "retries": 3,
        "fragment_retries": 3,
    }

    print(f"다운로드 시작: {url}")
    print(f"저장 위치: {output_path}")
    print("-" * 50)

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # 영상 정보 추출
            info = ydl.extract_info(url, download=True)

            # 다운로드된 파일 경로
            downloaded_file = str(output_path / f"{filename}.mp4")

            print("-" * 50)
            print(f"✅ 다운로드 완료!")
            print(f"   제목: {info.get('title', 'Unknown')}")
            print(f"   길이: {info.get('duration', 0)}초")
            print(f"   파일: {downloaded_file}")

            return downloaded_file

    except yt_dlp.utils.DownloadError as e:
        print(f"❌ 다운로드 실패: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ 예상치 못한 오류: {e}")
        sys.exit(1)


def progress_hook(d):
    """다운로드 진행률 표시 훅"""
    if d["status"] == "downloading":
        percent = d.get("_percent_str", "N/A")
        speed = d.get("_speed_str", "N/A")
        eta = d.get("_eta_str", "N/A")
        print(f"\r⏬ 다운로드 중: {percent} | 속도: {speed} | 남은 시간: {eta}", end="")
    elif d["status"] == "finished":
        print(f"\n📦 후처리 중...")


def main():
    parser = argparse.ArgumentParser(
        description="YouTube 영상 다운로드",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  python download_video.py --url "https://youtube.com/watch?v=xxxxx" --output "./temp"
  python download_video.py -u "https://youtu.be/xxxxx" -o "./temp" -f "my_video"
        """,
    )

    parser.add_argument(
        "--url", "-u", required=True, help="YouTube 영상 URL"
    )
    parser.add_argument(
        "--output", "-o", default="./temp", help="저장할 디렉토리 (기본값: ./temp)"
    )
    parser.add_argument(
        "--filename", "-f", default="video", help="저장할 파일명 (기본값: video)"
    )

    args = parser.parse_args()

    # URL 유효성 간단 체크
    if "youtube.com" not in args.url and "youtu.be" not in args.url:
        print("⚠️ 경고: YouTube URL이 아닌 것 같습니다.")
        response = input("계속하시겠습니까? (y/n): ")
        if response.lower() != "y":
            sys.exit(0)

    # 다운로드 실행
    downloaded_path = download_video(args.url, args.output, args.filename)

    return downloaded_path


if __name__ == "__main__":
    main()
