#!/usr/bin/env python3
"""
generate_images.py
週次台本データ(week_data.json)の画像生成プロンプトを、Gemini API(Nano Banana =
gemini-2.5-flash-image)で静止画(png)にする。

前提:
- 環境変数 GEMINI_API_KEY にAPIキーが入っていること(GitHub Secretsから渡す)。
- pip install google-genai が必要 (requirements.txtに記載)。

使い方:
  export GEMINI_API_KEY=xxxx
  python generate_images.py --data week_data.json --out-dir out/images \
      [--model gemini-2.5-flash-image] [--size 1024x1792]

出力:
  out/images/day1.png ... day7.png

注意:
- プロンプトは実在の作品名・キャラクターを再現しないよう、週次台本の時点で
  一般的なシーン(スマホ画面・部屋・アイコン等)に寄せてある前提。ここでは
  そのまま渡すだけで、追加の著作権チェックはしていない。
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path


def generate_one(client, model: str, prompt: str, out_path: Path, retries: int = 3) -> None:
    from google.genai import types  # 遅延import(未インストール環境でも --help は動くように)

    last_err = None
    for attempt in range(1, retries + 1):
        try:
            resp = client.models.generate_content(
                model=model,
                contents=prompt,
            )
            for part in resp.candidates[0].content.parts:
                if getattr(part, "inline_data", None) is not None:
                    out_path.write_bytes(part.inline_data.data)
                    return
            raise RuntimeError("応答に画像データが含まれていませんでした")
        except Exception as e:  # noqa: BLE001 - リトライのため広めに捕捉
            last_err = e
            print(f"  [warn] attempt {attempt}/{retries} failed: {e}", file=sys.stderr)
            time.sleep(2 * attempt)
    raise RuntimeError(f"画像生成に失敗しました: {last_err}")


def main() -> int:
    ap = argparse.ArgumentParser(description="週次台本の画像プロンプトをGemini(Nano Banana)で生成する")
    ap.add_argument("--data", required=True, help="week_data.json のパス")
    ap.add_argument("--out-dir", required=True, help="png出力先ディレクトリ")
    ap.add_argument("--model", default="gemini-2.5-flash-image", help="使用するGeminiモデル")
    args = ap.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("[error] 環境変数 GEMINI_API_KEY が設定されていません", file=sys.stderr)
        return 1

    try:
        from google import genai
    except ImportError:
        print("[error] google-genai がインストールされていません: pip install google-genai", file=sys.stderr)
        return 1

    client = genai.Client(api_key=api_key)

    data = json.loads(Path(args.data).read_text(encoding="utf-8"))
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    days = data.get("days", [])
    if not days:
        print("[error] week_data.json に days がありません", file=sys.stderr)
        return 1

    for d in days:
        day_no = d["day"]
        prompt = d["image_prompt_en"]
        out_path = out_dir / f"day{day_no}.png"
        print(f"[day {day_no}] 画像生成中: {prompt[:40]}...")
        generate_one(client, args.model, prompt, out_path)
        print(f"  -> {out_path}")

    print(f"完了: {len(days)}件の画像 {out_dir} に出力しました")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
