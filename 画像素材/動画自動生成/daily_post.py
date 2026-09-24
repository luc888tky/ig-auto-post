"""
R2にアップロード済みの動画を、進捗ファイルに従って1日1本、Instagram Storiesに自動投稿するスクリプト。
このスクリプト自体は動画を生成しない（generate-videos.yml で生成・R2アップロード済みの動画が対象）。

必要な環境変数:
  IG_ACCESS_TOKEN
  IG_USER_ID
  R2_PUBLIC_URL

進捗管理:
  画像素材/動画自動生成/progress.json に {"week_file": "...", "next_day": N} を保存し、
  投稿成功のたびに next_day を1つ進める。データを使い切ったら何もせず終了する。
"""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

APP_DIR = Path(__file__).parent
DATA_DIR = APP_DIR / "data"
PROGRESS_FILE = APP_DIR / "progress.json"
GRAPH_API_BASE = "https://graph.facebook.com/v21.0"

REQUIRED_ENV_VARS = ["IG_ACCESS_TOKEN", "IG_USER_ID", "R2_PUBLIC_URL"]


def load_progress() -> dict:
    if PROGRESS_FILE.exists():
        return json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
    return {"week_file": "week1.json", "next_day": 1}


def save_progress(progress: dict) -> None:
    PROGRESS_FILE.write_text(
        json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf-8"
    )


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
    missing = [name for name in REQUIRED_ENV_VARS if not os.environ.get(name)]
    if missing:
        print(f"以下の環境変数が設定されていません: {', '.join(missing)}", file=sys.stderr)
        return 1

    progress = load_progress()
    week_file = progress.get("week_file", "week1.json")
    next_day = progress.get("next_day", 1)

    data_path = DATA_DIR / week_file
    if not data_path.exists():
        print(f"台本データが見つかりません: {data_path}", file=sys.stderr)
        return 1

    week_data = json.loads(data_path.read_text(encoding="utf-8"))
    total_days = len(week_data.get("days", []))

    if next_day > total_days:
        print(
            f"{week_file} の全{total_days}日分の投稿が完了しています。"
            f"新しい週のデータ（例: week2.json）を用意し、generate-videos.yml で生成・R2アップロードした上で、"
            f"progress.json の week_file / next_day を更新してください。"
        )
        return 0

    week_stem = Path(week_file).stem
    r2_public_url = os.environ["R2_PUBLIC_URL"].rstrip("/")
    video_url = f"{r2_public_url}/videos/{week_stem}/day{next_day}.mp4"

    print(f"投稿対象: {video_url}（{week_stem} day{next_day}）")

    ig_user_id = os.environ["IG_USER_ID"]
    access_token = os.environ["IG_ACCESS_TOKEN"]

    creation_id = create_story_container(ig_user_id, access_token, video_url)
    wait_until_ready(creation_id, access_token)
    publish_story(ig_user_id, access_token, creation_id)

    progress["next_day"] = next_day + 1
    save_progress(progress)

    return 0


if __name__ == "__main__":
    sys.exit(main())
