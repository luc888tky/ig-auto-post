#!/usr/bin/env python3
"""
voicevox_narrate.py
週次台本データ(week_data.json)のナレーション原稿を、VOICEVOX ENGINEのHTTP APIで
音声化(wav)する。

前提:
- VOICEVOX ENGINE (無料・OSS) がどこかで動いていること。
  GitHub Actions上では voicevox/voicevox_engine の公式Dockerイメージを
  サービスコンテナとして起動し、http://localhost:50021 で待ち受ける想定。
  ローカルで試す場合も同様にDockerで起動できる:
    docker run -d -p 50021:50021 voicevox/voicevox_engine:cpu-ubuntu20.04-latest

使い方:
  python voicevox_narrate.py --data week_data.json --out-dir out/audio \
      [--engine-url http://localhost:50021] [--speaker 3]

出力:
  out/audio/day1.wav ... day7.wav

speakerは話者ID。VOICEVOXのデフォルトは四国めたん(ノーマル)=2、ずんだもん(ノーマル)=3など。
"""
import argparse
import json
import sys
import time
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path


def synth_one(
    engine_url: str,
    text: str,
    speaker: int,
    out_path: Path,
    speed: float = 1.2,
    retries: int = 3,
) -> None:
    """1件のテキストをVOICEVOX ENGINEで音声化してout_pathに保存する。

    speed: 話速倍率(VOICEVOXのspeedScale)。1.0が標準、大きいほど速い。
    """
    query_url = f"{engine_url}/audio_query?speaker={speaker}&text={urllib.parse.quote(text)}"
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            # 1) audio_query: テキストから音声合成用クエリ(韻律等)を作る
            req = urllib.request.Request(query_url, method="POST")
            with urllib.request.urlopen(req, timeout=30) as resp:
                query = resp.read()

            # 話速を調整する(speedScaleを書き換える)
            query_obj = json.loads(query)
            query_obj["speedScale"] = speed
            query = json.dumps(query_obj).encode("utf-8")

            # 2) synthesis: クエリから実際の音声(wav)を作る
            synth_url = f"{engine_url}/synthesis?speaker={speaker}"
            req2 = urllib.request.Request(
                synth_url, data=query, method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req2, timeout=60) as resp2:
                wav_bytes = resp2.read()

            out_path.write_bytes(wav_bytes)
            return
        except (urllib.error.URLError, urllib.error.HTTPError) as e:
            last_err = e
            print(f"  [warn] attempt {attempt}/{retries} failed: {e}", file=sys.stderr)
            time.sleep(2 * attempt)
    raise RuntimeError(f"VOICEVOX synthesis failed for '{text[:20]}...': {last_err}")


def main() -> int:
    ap = argparse.ArgumentParser(description="週次台本のナレーションをVOICEVOXで音声化する")
    ap.add_argument("--data", required=True, help="week_data.json のパス")
    ap.add_argument("--out-dir", required=True, help="wav出力先ディレクトリ")
    ap.add_argument("--engine-url", default="http://localhost:50021", help="VOICEVOX ENGINEのURL")
    ap.add_argument("--speaker", type=int, default=3, help="話者ID(既定: ずんだもん ノーマル=3)")
    ap.add_argument(
        "--speed",
        type=float,
        default=1.2,
        help="話速倍率(既定: 1.2倍。1.0が標準速度)",
    )
    args = ap.parse_args()

    data = json.loads(Path(args.data).read_text(encoding="utf-8"))
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    days = data.get("days", [])
    if not days:
        print("[error] week_data.json に days がありません", file=sys.stderr)
        return 1

    for d in days:
        day_no = d["day"]
        text = d["narration"]
        out_path = out_dir / f"day{day_no}.wav"
        print(f"[day {day_no}] 音声生成中: {text[:24]}...")
        synth_one(args.engine_url, text, args.speaker, out_path, speed=args.speed)
        print(f"  -> {out_path}")

    print(f"完了: {len(days)}件の音声を {out_dir} に出力しました")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
