"""
生成済みの動画（out/videos/*.mp4）をCloudflare R2にアップロードするスクリプト。
Instagramへの投稿は行わない（投稿は daily_post.py が毎日1本ずつ自動実行する）。

必要な環境変数:
  R2_ACCOUNT_ID
  R2_ACCESS_KEY_ID
  R2_SECRET_ACCESS_KEY
  R2_BUCKET_NAME
"""

import argparse
import os
import sys
from pathlib import Path

REQUIRED_ENV_VARS = [
    "R2_ACCOUNT_ID",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "R2_BUCKET_NAME",
]


def upload_all(video_dir: Path, week_stem: str) -> None:
    import boto3

    account_id = os.environ["R2_ACCOUNT_ID"]
    access_key = os.environ["R2_ACCESS_KEY_ID"]
    secret_key = os.environ["R2_SECRET_ACCESS_KEY"]
    bucket_name = os.environ["R2_BUCKET_NAME"]

    client = boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="auto",
    )

    videos = sorted(video_dir.glob("*.mp4"))
    if not videos:
        print(f"アップロード対象の動画が見つかりません: {video_dir}", file=sys.stderr)
        return

    for video_path in videos:
        key = f"videos/{week_stem}/{video_path.name}"
        print(f"R2へアップロード中: {key}")
        client.upload_file(str(video_path), bucket_name, key)

    print(f"{len(videos)}件のアップロードが完了しました。（保存先プレフィックス: videos/{week_stem}/）")


def main() -> int:
    parser = argparse.ArgumentParser(description="生成済み動画をR2にアップロードする")
    parser.add_argument(
        "--video-dir", required=True, help="動画ファイルのディレクトリ（例: out/videos）"
    )
    parser.add_argument(
        "--week-file", required=True, help="台本データのファイル名（例: week1.json）"
    )
    args = parser.parse_args()

    missing = [name for name in REQUIRED_ENV_VARS if not os.environ.get(name)]
    if missing:
        print(f"以下の環境変数が設定されていません: {', '.join(missing)}", file=sys.stderr)
        return 1

    week_stem = Path(args.week_file).stem
    upload_all(Path(args.video_dir), week_stem)
    return 0


if __name__ == "__main__":
    sys.exit(main())
