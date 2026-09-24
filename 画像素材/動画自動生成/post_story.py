"""
動画をCloudflare R2にアップロードし、Instagram Stories として投稿するスクリプト。

必要な環境変数:
  IG_ACCESS_TOKEN      Instagramログインで取得したアクセストークン
  IG_USER_ID           InstagramビジネスアカウントのユーザーID
  R2_ACCOUNT_ID        Cloudflareアカウントの ID
  R2_ACCESS_KEY_ID     R2 APIトークンの Access Key ID
  R2_SECRET_ACCESS_KEY R2 APIトークンの Secret Access Key
  R2_BUCKET_NAME       アップロード先のR2バケット名
  R2_PUBLIC_URL        バケットの公開URL（例: https://xxxx.r2.dev）

使い方:
  python post_story.py --video out/videos/day1.mp4
  python post_story.py --video out/videos/day1.mp4 --dry-run
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

GRAPH_API_BASE = "https://graph.facebook.com/v21.0"
POSTED_LOG = Path(__file__).parent / "posted_stories.json"

REQUIRED_ENV_VARS = [
    "IG_ACCESS_TOKEN",
    "IG_USER_ID",
    "R2_ACCOUNT_ID",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "R2_BUCKET_NAME",
    "R2_PUBLIC_URL",
]


def load_posted() -> dict:
    if POSTED_LOG.exists():
        return json.loads(POSTED_LOG.read_text(encoding="utf-8"))
    return {}


def save_posted(posted: dict) -> None:
    POSTED_LOG.write_text(
        json.dumps(posted, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def upload_to_r2(video_path: Path) -> str:
    import boto3

    account_id = os.environ["R2_ACCOUNT_ID"]
    access_key = os.environ["R2_ACCESS_KEY_ID"]
    secret_key = os.environ["R2_SECRET_ACCESS_KEY"]
    bucket_name = os.environ["R2_BUCKET_NAME"]
    public_base = os.environ["R2_PUBLIC_URL"]

    client = boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="auto",
    )

    key = f"videos/{video_path.name}"
    print(f"R2へアップロード中: {key}")
    client.upload_file(str(video_path), bucket_name, key)

    public_url = f"{public_base.rstrip('/')}/{key}"
    print(f"アップロード完了: {public_url}")
    return public_url


def graph_request(path: str, method: str = "GET", params: dict | None = None) -> dict:
    params = dict(params or {})
    url = f"{GRAPH_API_BASE}/{path}"

    if method == "GET":
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, method="GET")
    else:
        data = urllib.parse.urlencode(params).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        print(f"Graph APIエラー ({e.code}): {body}", file=sys.stderr)
        raise


def create_story_container(ig_user_id: str, access_token: str, video_url: str) -> str:
    result = graph_request(
        f"{ig_user_id}/media",
        method="POST",
        params={
            "media_type": "STORIES",
            "video_url": video_url,
            "access_token": access_token,
        },
    )
    creation_id = result["id"]
    print(f"メディアコンテナ作成完了: creation_id={creation_id}")
    return creation_id


def wait_until_ready(creation_id: str, access_token: str, timeout: int = 300) -> None:
    start = time.time()
    while time.time() - start < timeout:
        result = graph_request(
            creation_id,
            method="GET",
            params={"fields": "status_code", "access_token": access_token},
        )
        status = result.get("status_code")
        print(f"処理状況: {status}")
        if status == "FINISHED":
            return
        if status == "ERROR":
            raise RuntimeError(f"動画の処理に失敗しました: {result}")
        time.sleep(10)
    raise TimeoutError("動画の処理がタイムアウトしました（300秒）")


def publish_story(ig_user_id: str, access_token: str, creation_id: str) -> str:
    result = graph_request(
        f"{ig_user_id}/media_publish",
        method="POST",
        params={"creation_id": creation_id, "access_token": access_token},
    )
    media_id = result["id"]
    print(f"Instagram Storiesへの投稿完了: media_id={media_id}")
    return media_id


def main() -> int:
    parser = argparse.ArgumentParser(description="動画をInstagram Storiesに投稿する")
    parser.add_argument("--video", required=True, help="投稿する動画ファイルのパス")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="R2へのアップロードのみ行い、Instagramへの投稿は行わない",
    )
    args = parser.parse_args()

    missing = [name for name in REQUIRED_ENV_VARS if not os.environ.get(name)]
    if missing:
        print(f"以下の環境変数が設定されていません: {', '.join(missing)}", file=sys.stderr)
        return 1

    video_path = Path(args.video)
    if not video_path.exists():
        print(f"動画ファイルが見つかりません: {video_path}", file=sys.stderr)
        return 1

    posted = load_posted()
    if video_path.name in posted:
        print(f"既に投稿済みのためスキップします: {video_path.name}")
        return 0

    video_url = upload_to_r2(video_path)

    if args.dry_run:
        print("dry-runモードのため、Instagramへの投稿はスキップします")
        return 0

    ig_user_id = os.environ["IG_USER_ID"]
    access_token = os.environ["IG_ACCESS_TOKEN"]

    creation_id = create_story_container(ig_user_id, access_token, video_url)
    wait_until_ready(creation_id, access_token)
    media_id = publish_story(ig_user_id, access_token, creation_id)

    posted[video_path.name] = media_id
    save_posted(posted)

    return 0


if __name__ == "__main__":
    sys.exit(main())
