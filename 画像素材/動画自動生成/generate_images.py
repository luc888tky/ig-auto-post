#!/usr/bin/env python3
"""
generate_images.py
週次台本データ(week_data.json)の画像生成プロンプトを、Cloudflare Workers AI
(FLUX.1 [schnell] = @cf/black-forest-labs/flux-1-schnell、無料枠あり)で
静止画(png)にする。

前提:
- 環境変数 CLOUDFLARE_ACCOUNT_ID / CLOUDFLARE_API_TOKEN が設定されていること
  (GitHub Secretsから渡す)。
- 追加の外部ライブラリは不要(標準ライブラリの urllib のみ使用)。

使い方:
  export CLOUDFLARE_ACCOUNT_ID=xxxx
  export CLOUDFLARE_API_TOKEN=xxxx
  python generate_images.py --data week_data.json --out-dir out/images \
      [--model @cf/black-forest-labs/flux-1-schnell] [--steps 8]

出力:
  out/images/day1.png ... day7.png

無料枠について:
  Cloudflare Workers AIは1日10,000 Neuronsまで無料(クレジットカード登録不要)。
  FLUX.1 [schnell]なら週7枚程度の生成では無料枠内に十分収まる。

注意:
- プロンプトは実在の作品名・キャラクターを再現しないよう、週次台本の時点で
  一般的なシーン(スマホ画面・部屋・アイコン等)に寄せてある前提。ここでは
  そのまま渡すだけで、追加の著作権チェックはしていない。
"""
import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API_BASE = "https://api.cloudflare.com/client/v4/accounts"


def generate_one(
    account_id: str,
    api_token: str,
    model: str,
    prompt: str,
    steps: int,
    out_path: Path,
    retries: int = 3,
) -> None:
    url = f"{API_BASE}/{account_id}/ai/run/{model}"
    body = json.dumps({"prompt": prompt, "steps": steps}).encode("utf-8")

    last_err = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(
                url,
                data=body,
                method="POST",
                headers={
                    "Authorization": f"Bearer {api_token}",
                    "Content-Type": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            if data.get("success") is False:
                raise RuntimeError(f"Cloudflare APIエラー: {data.get('errors')}")

            b64_image = None
            if isinstance(data.get("result"), dict):
                b64_image = data["result"].get("image")
            if b64_image is None:
                b64_image = data.get("image")
            if not b64_image:
                raise RuntimeError(f"応答に画像データが含まれていませんでした: {data}")

            out_path.write_bytes(base64.b64decode(b64_image))
            return
        except urllib.error.HTTPError as e:
            body_text = e.read().decode("utf-8", errors="replace")
            last_err = f"HTTP {e.code}: {body_text}"
            print(f"  [warn] attempt {attempt}/{retries} failed: {last_err}", file=sys.stderr)
            time.sleep(2 * attempt)
        except Exception as e:  # noqa: BLE001 - リトライのため広めに捕捉
            last_err = e
            print(f"  [warn] attempt {attempt}/{retries} failed: {e}", file=sys.stderr)
            time.sleep(2 * attempt)
    raise RuntimeError(f"画像生成に失敗しました: {last_err}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="週次台本の画像プロンプトをCloudflare Workers AI(FLUX)で生成する"
    )
    ap.add_argument("--data", required=True, help="week_data.json のパス")
    ap.add_argument("--out-dir", required=True, help="png出力先ディレクトリ")
    ap.add_argument(
        "--model",
        default="@cf/black-forest-labs/flux-1-schnell",
        help="使用するCloudflare Workers AIモデル",
    )
    ap.add_argument("--steps", type=int, default=8, help="拡散ステップ数(最大8)")
    args = ap.parse_args()

    account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
    api_token = os.environ.get("CLOUDFLARE_API_TOKEN")
    if not account_id or not api_token:
        print(
            "[error] 環境変数 CLOUDFLARE_ACCOUNT_ID / CLOUDFLARE_API_TOKEN が設定されていません",
            file=sys.stderr,
        )
        return 1

    data = json.loads(Path(args.data).read_text(encoding="utf-8"))
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    days = data.get("days", [])
    if not days:
        print("[error] week_data.json に days がありません", file=sys.stderr)
        return 1

    total_images = 0
    for d in days:
        day_no = d["day"]
        # 新形式: "images": [{"prompt": "..."}, ...] (2〜3秒ごとのカット割り用に複数枚)
        # 旧形式: "image_prompt_en": "..." (1日1枚) にも後方互換で対応する
        images = d.get("images")
        if images:
            prompts = [im["prompt"] for im in images]
        else:
            prompts = [d["image_prompt_en"]]

        for idx, prompt in enumerate(prompts, start=1):
            if len(prompts) == 1:
                out_path = out_dir / f"day{day_no}.png"
            else:
                out_path = out_dir / f"day{day_no}_{idx}.png"
            print(f"[day {day_no} / {idx}] 画像生成中: {prompt[:40]}...")
            generate_one(account_id, api_token, args.model, prompt, args.steps, out_path)
            print(f"  -> {out_path}")
            total_images += 1

    print(f"完了: {total_images}枚の画像を {out_dir} に出力しました")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
