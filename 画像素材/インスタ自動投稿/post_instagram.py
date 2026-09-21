#!/usr/bin/env python3
"""Instagram カルーセル自動投稿（Instagram API with Instagram Login）

使い方:
  python post_instagram.py              # 今日（日本時間）の投稿を公開
  python post_instagram.py --dry-run    # 投稿せず、内容と画像URLの確認だけ
  python post_instagram.py --date 2026-10-21   # 日付を指定

必要な環境変数:
  IG_TOKEN            Instagramのアクセストークン（GitHubのSecretsに保存）
  GITHUB_REPOSITORY   例: username/repo（GitHub Actionsが自動で設定）
任意:
  IMAGE_BASE_URL      画像の公開URLの前半（未設定なら raw.githubusercontent.com を使う）
  IG_API_BASE         APIのURL（テスト用）
  IG_API_VERSION      APIのバージョン（初期値 v24.0）
"""
import argparse, datetime, json, os, sys, time, urllib.parse, urllib.request, urllib.error

ROOT = os.path.dirname(os.path.abspath(__file__))
JST = datetime.timezone(datetime.timedelta(hours=9))
VERSION = os.environ.get("IG_API_VERSION", "v24.0")
BASE = os.environ.get("IG_API_BASE", "https://graph.instagram.com").rstrip("/")


def call(method, path, params=None, token=None):
    params = dict(params or {})
    if token:
        params["access_token"] = token
    url = f"{BASE}/{VERSION}/{path.lstrip('/')}" if not path.startswith("http") else path
    data = None
    if method == "GET":
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    else:
        data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=data, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise SystemExit(f"APIエラー {e.code} {method} {path}: {body}")


def image_url(rel):
    base = os.environ.get("IMAGE_BASE_URL")
    if not base:
        repo = os.environ.get("GITHUB_REPOSITORY")
        branch = os.environ.get("IMAGE_BRANCH", "main")
        if not repo:
            raise SystemExit("GITHUB_REPOSITORY か IMAGE_BASE_URL を設定してください")
        base = f"https://raw.githubusercontent.com/{repo}/{branch}"
    return f"{base.rstrip('/')}/{urllib.parse.quote(rel)}"


def check_image(url):
    req = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            ctype = r.headers.get("Content-Type", "")
            return r.status == 200 and "image" in ctype, f"{r.status} {ctype}"
    except Exception as e:  # noqa
        return False, str(e)


def wait_finished(container_id, token, tries=40, interval=15):
    for _ in range(tries):
        r = call("GET", container_id, {"fields": "status_code"}, token)
        st = r.get("status_code")
        if st == "FINISHED":
            return
        if st in ("ERROR", "EXPIRED"):
            raise SystemExit(f"コンテナ {container_id} が {st} になりました: {r}")
        time.sleep(interval)
    raise SystemExit(f"コンテナ {container_id} の準備が時間内に終わりませんでした")


def refresh_token(token):
    """トークンの有効期限を延ばす（失敗しても投稿は続ける）。新しい値を返す。"""
    try:
        r = call("GET", f"{BASE}/refresh_access_token",
                 {"grant_type": "ig_refresh_token"}, token)
        days = r.get("expires_in", 0) / 86400
        print(f"トークン更新OK: 残り約{days:.0f}日")
        return r.get("access_token", token)
    except (SystemExit, Exception) as e:  # 24時間以内の再更新や通信エラーでも、投稿は成功扱いにする
        print(f"トークン更新はスキップ: {e}")
        return token


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--date", help="YYYY-MM-DD（省略時は日本時間の今日）")
    a = ap.parse_args()

    today = a.date or datetime.datetime.now(JST).strftime("%Y-%m-%d")
    posts = json.load(open(os.path.join(ROOT, "posts.json"), encoding="utf-8"))
    state_path = os.path.join(ROOT, "posted.json")
    state = json.load(open(state_path)) if os.path.exists(state_path) else {"posted": []}

    todo = [p for p in posts if p["date"] == today]
    if not todo:
        print(f"{today}: 予定された投稿はありません")
        return
    post = todo[0]
    if post["date"] in [x["date"] for x in state["posted"]]:
        print(f"{today}: 投稿済みのためスキップ")
        return

    urls = [image_url(i) for i in post["images"]]
    print(f"{today}: 日{post.get('day')}  画像{len(urls)}枚")
    if a.dry_run:
        for u in urls:
            ok, info = check_image(u) if os.environ.get("CHECK_URLS") else (None, "未確認")
            print(" ", u, info)
        print("--- キャプション ---\n" + post["caption"])
        print("（dry-run: 投稿はしていません）")
        return

    token = os.environ.get("IG_TOKEN")
    if not token:
        raise SystemExit("IG_TOKEN が設定されていません")

    for u in urls:
        ok, info = check_image(u)
        if not ok:
            raise SystemExit(f"画像を取得できません: {u} ({info})")

    me = call("GET", "me", {"fields": "user_id,username"}, token)
    uid = me.get("user_id") or me.get("id")
    print(f"アカウント: @{me.get('username')} ({uid})")

    children = []
    for u in urls:
        c = call("POST", f"{uid}/media", {"image_url": u, "is_carousel_item": "true"}, token)
        children.append(c["id"])
    for cid in children:
        wait_finished(cid, token)

    car = call("POST", f"{uid}/media",
               {"media_type": "CAROUSEL", "children": ",".join(children),
                "caption": post["caption"]}, token)
    wait_finished(car["id"], token)
    pub = call("POST", f"{uid}/media_publish", {"creation_id": car["id"]}, token)
    print("投稿しました:", pub)

    state["posted"].append({"date": post["date"], "media_id": pub.get("id"),
                            "at": datetime.datetime.now(JST).isoformat(timespec="seconds")})
    json.dump(state, open(state_path, "w"), ensure_ascii=False, indent=2)

    new_token = refresh_token(token)
    out_file = os.environ.get("NEW_TOKEN_FILE")  # リポジトリの外（一時フォルダ）にだけ書く
    if new_token != token and out_file:
        with open(out_file, "w") as f:
            f.write(new_token)


if __name__ == "__main__":
    sys.exit(main())
