"""
R2にアップロード済みの動画を、進捗ファイルに従って1日1本、
Instagram Stories / Instagram Reels / TikTok / YouTube Shorts に自動投稿するスクリプト。
このスクリプト自体は動画を生成しない（generate-videos.yml で生成・R2アップロード済みの動画が対象）。

必須の環境変数（Instagram Storiesの投稿に必要）:
  IG_ACCESS_TOKEN
  IG_USER_ID
  R2_PUBLIC_URL

任意の環境変数（設定されていればそのプラットフォームにも投稿する。未設定ならスキップするだけで、
他のプラットフォームの投稿は止めない）:
  IG_POST_REELS=true         Instagram Reelsにも投稿する（デフォルトはfalse=Storiesのみ）
  TIKTOK_ACCESS_TOKEN        TikTok Content Posting API のアクセストークン
  TIKTOK_PRIVACY_LEVEL       省略時 SELF_ONLY（TikTokアプリが監査未完了の間は自動的にSELF_ONLYになる）
  YOUTUBE_CLIENT_ID          Google Cloud OAuthクライアントID
  YOUTUBE_CLIENT_SECRET      Google Cloud OAuthクライアントシークレット
  YOUTUBE_REFRESH_TOKEN      YouTubeアップロード用に一度だけ認可して得たリフレッシュトークン
  YOUTUBE_PRIVACY_STATUS     省略時 unlisted（public/unlisted/private）

進捗管理:
  画像素材/動画自動生成/progress.json に {"week_file": "...", "next_day": N} を保存し、
  Instagram Storiesへの投稿成功のたびに next_day を1つ進める。
  データを使い切ったら何もせず終了する。
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
TIKTOK_API_BASE = "https://open.tiktokapis.com/v2"
YOUTUBE_TOKEN_URL = "https://oauth2.googleapis.com/token"
YOUTUBE_UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"

REQUIRED_ENV_VARS = ["IG_ACCESS_TOKEN", "IG_USER_ID", "R2_PUBLIC_URL"]


def load_progress() -> dict:
    if PROGRESS_FILE.exists():
        return json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
    return {"week_file": "week1.json", "next_day": 1}


def save_progress(progress: dict) -> None:
    PROGRESS_FILE.write_text(
        json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def get_caption_for_day(week_data: dict, day_index: int) -> str:
    days = week_data.get("days", [])
    if 0 <= day_index - 1 < len(days):
        cta = days[day_index - 1].get("cta") or ""
        if cta:
            return cta
    return f"Day {day_index}"


# ── Instagram（Stories / Reels）───────────────────────────────

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


def create_ig_container(
    ig_user_id: str,
    access_token: str,
    video_url: str,
    media_type: str,
    caption: str | None = None,
) -> str:
    params = {
        "media_type": media_type,
        "video_url": video_url,
        "access_token": access_token,
    }
    if caption:
        params["caption"] = caption
    result = graph_request(f"{ig_user_id}/media", method="POST", params=params)
    creation_id = result["id"]
    print(f"[Instagram/{media_type}] メディアコンテナ作成完了: creation_id={creation_id}")
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
        print(f"[Instagram] 処理状況: {status}")
        if status == "FINISHED":
            return
        if status == "ERROR":
            raise RuntimeError(f"動画の処理に失敗しました: {result}")
        time.sleep(10)
    raise TimeoutError("動画の処理がタイムアウトしました（300秒）")


def publish_ig(ig_user_id: str, access_token: str, creation_id: str) -> str:
    result = graph_request(
        f"{ig_user_id}/media_publish",
        method="POST",
        params={"creation_id": creation_id, "access_token": access_token},
    )
    media_id = result["id"]
    print(f"[Instagram] 投稿完了: media_id={media_id}")
    return media_id


def post_to_instagram_stories(ig_user_id: str, access_token: str, video_url: str) -> None:
    creation_id = create_ig_container(ig_user_id, access_token, video_url, "STORIES")
    wait_until_ready(creation_id, access_token)
    publish_ig(ig_user_id, access_token, creation_id)


def post_to_instagram_reels(
    ig_user_id: str, access_token: str, video_url: str, caption: str
) -> None:
    if os.environ.get("IG_POST_REELS", "").lower() != "true":
        print("[Instagram Reels] IG_POST_REELS が true でないためスキップします。")
        return
    creation_id = create_ig_container(ig_user_id, access_token, video_url, "REELS", caption)
    wait_until_ready(creation_id, access_token)
    publish_ig(ig_user_id, access_token, creation_id)


# ── TikTok ─────────────────────────────────────────────────────

def post_to_tiktok(video_url: str, caption: str) -> None:
    access_token = os.environ.get("TIKTOK_ACCESS_TOKEN")
    if not access_token:
        print("[TikTok] TIKTOK_ACCESS_TOKEN が未設定のためスキップします。")
        return

    body = {
        "post_info": {
            "title": caption,
            "privacy_level": os.environ.get("TIKTOK_PRIVACY_LEVEL", "SELF_ONLY"),
            "disable_duet": False,
            "disable_stitch": False,
            "disable_comment": False,
        },
        "source_info": {
            "source": "PULL_FROM_URL",
            "video_url": video_url,
        },
    }
    req = urllib.request.Request(
        f"{TIKTOK_API_BASE}/post/publish/video/init/",
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        publish_id = result.get("data", {}).get("publish_id")
        print(f"[TikTok] 投稿受付完了: publish_id={publish_id}")
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        print(f"[TikTok] 投稿エラー ({e.code}): {error_body}", file=sys.stderr)
        raise


# ── YouTube Shorts ─────────────────────────────────────────────

def get_youtube_access_token() -> str | None:
    client_id = os.environ.get("YOUTUBE_CLIENT_ID")
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
    refresh_token = os.environ.get("YOUTUBE_REFRESH_TOKEN")
    if not (client_id and client_secret and refresh_token):
        return None

    data = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
    ).encode("utf-8")
    req = urllib.request.Request(YOUTUBE_TOKEN_URL, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    return result["access_token"]


def post_to_youtube(video_url: str, title: str, description: str) -> None:
    access_token = get_youtube_access_token()
    if not access_token:
        print("[YouTube] 認証情報（CLIENT_ID/CLIENT_SECRET/REFRESH_TOKEN）が未設定のためスキップします。")
        return

    tmp_path = Path("/tmp/youtube_upload.mp4")
    print("[YouTube] 動画を一時ダウンロード中...")
    with urllib.request.urlopen(video_url, timeout=120) as resp, open(tmp_path, "wb") as f:
        f.write(resp.read())
    video_size = tmp_path.stat().st_size

    metadata = {
        "snippet": {
            "title": title,
            "description": description,
            "categoryId": "24",
        },
        "status": {
            "privacyStatus": os.environ.get("YOUTUBE_PRIVACY_STATUS", "unlisted"),
        },
    }
    init_req = urllib.request.Request(
        f"{YOUTUBE_UPLOAD_URL}?uploadType=resumable&part=snippet,status",
        data=json.dumps(metadata).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Type": "video/mp4",
            "X-Upload-Content-Length": str(video_size),
        },
    )
    try:
        with urllib.request.urlopen(init_req, timeout=30) as resp:
            upload_url = resp.headers.get("Location")
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        print(f"[YouTube] アップロード開始エラー ({e.code}): {error_body}", file=sys.stderr)
        tmp_path.unlink(missing_ok=True)
        raise

    if not upload_url:
        print("[YouTube] アップロードURLの取得に失敗しました。", file=sys.stderr)
        tmp_path.unlink(missing_ok=True)
        return

    with open(tmp_path, "rb") as f:
        video_bytes = f.read()
    upload_req = urllib.request.Request(
        upload_url,
        data=video_bytes,
        method="PUT",
        headers={"Content-Type": "video/mp4", "Content-Length": str(video_size)},
    )
    try:
        with urllib.request.urlopen(upload_req, timeout=600) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        print(f"[YouTube] 投稿完了: video_id={result.get('id')}")
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        print(f"[YouTube] アップロードエラー ({e.code}): {error_body}", file=sys.stderr)
        raise
    finally:
        tmp_path.unlink(missing_ok=True)


# ── メイン処理 ────────────────────────────────────────────────

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
    caption = get_caption_for_day(week_data, next_day)

    print(f"投稿対象: {video_url}（{week_stem} day{next_day}）")

    ig_user_id = os.environ["IG_USER_ID"]
    ig_access_token = os.environ["IG_ACCESS_TOKEN"]

    # Instagram Storiesは必須（失敗したら全体を失敗扱いにする＝next_dayを進めない）
    post_to_instagram_stories(ig_user_id, ig_access_token, video_url)

    # 以下は任意のプラットフォーム。1つ失敗しても他への投稿とnext_dayの更新は止めない。
    try:
        post_to_instagram_reels(ig_user_id, ig_access_token, video_url, caption)
    except Exception as e:
        print(f"[Instagram Reels] エラーが発生しましたが、続行します: {e}", file=sys.stderr)

    try:
        post_to_tiktok(video_url, caption)
    except Exception as e:
        print(f"[TikTok] エラーが発生しましたが、続行します: {e}", file=sys.stderr)

    try:
        post_to_youtube(video_url, f"{week_stem} Day{next_day} #Shorts", f"{caption} #Shorts")
    except Exception as e:
        print(f"[YouTube] エラーが発生しましたが、続行します: {e}", file=sys.stderr)

    progress["next_day"] = next_day + 1
    save_progress(progress)

    return 0


if __name__ == "__main__":
    sys.exit(main())
