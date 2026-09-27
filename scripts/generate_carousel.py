"""
プロンプトJSONを読み込み、Gemini(Nano Banana)画像生成APIを叩いて
確認用フォルダ(images/pending/)に保存するスクリプト。
使い方: python scripts/generate_carousel.py scripts/prompts/d8.json
"""
import json
import os
import sys
import base64
import time
import requests

API_KEY = os.environ["GEMINI_API_KEY"]
MODEL = "gemini-2.5-flash-image-preview"
URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"

def generate_one(prompt: str) -> bytes:
    headers = {
        "x-goog-api-key": API_KEY,
        "Content-Type": "application/json",
    }
    body = {
        "contents": [{"parts": [{"text": prompt}]}]
    }
    for attempt in range(3):
        res = requests.post(URL, headers=headers, json=body, timeout=120)
        if res.status_code == 200:
            data = res.json()
            parts = data["candidates"][0]["content"]["parts"]
            for p in parts:
                if "inlineData" in p:
                    return base64.b64decode(p["inlineData"]["data"])
            raise RuntimeError(f"画像データが見つかりません: {data}")
        elif res.status_code in (429, 503):
            time.sleep(10 * (attempt + 1))
            continue
        else:
            raise RuntimeError(f"APIエラー {res.status_code}: {res.text[:500]}")
    raise RuntimeError("リトライ上限に達しました")

def main():
    prompts_path = sys.argv[1]
    with open(prompts_path, encoding="utf-8") as f:
        spec = json.load(f)

    out_dir = "画像素材/インスタ自動投稿/images/pending"
    os.makedirs(out_dir, exist_ok=True)

    for item in spec["slides"]:
        filename = item["filename"]
        prompt = item["prompt"]
        print(f"生成中: {filename}")
        img_bytes = generate_one(prompt)
        out_path = os.path.join(out_dir, filename)
        with open(out_path, "wb") as f:
            f.write(img_bytes)
        print(f"保存しました: {out_path}")
        time.sleep(3)

if __name__ == "__main__":
    main()
