#!/usr/bin/env python3
"""
assemble_video.py
week_data.json + ナレーション音声(day*.wav) + 静止画(day*.png) を、ffmpegで
1日1本・縦型9:16のショート動画(mp4)に自動組み立てする。CapCutの代わり。

やること(1日分):
  1. 静止画をゆっくりズームさせる(Ken Burns風)
  2. ナレーション音声をそのまま乗せる
  3. テロップ(telop配列)を、動画を等分した時間帯に順番に字幕として焼き込む
  4. BGMを小音量でミックスする(任意。--bgm-dir を渡さなければBGMなしで書き出す)

使い方:
  python assemble_video.py --data week_data.json \
      --audio-dir out/audio --image-dir out/images --out-dir out/videos \
      [--bgm-dir bgm] [--width 1080 --height 1920]

出力:
  out/videos/day1.mp4 ... day7.mp4
"""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


def ffprobe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def escape_drawtext(text: str) -> str:
    # ffmpeg drawtextの特殊文字(: ' \)をエスケープする
    return text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "’")


# 日本語テロップを焼き込むためのフォント。fontconfig任せだと豆腐(□□□)になる
# 環境があるため、明示的にfontfileで指定する。候補を順に探し、見つかった最初の
# ものを使う。GitHub Actions(ubuntu-latest)では fonts-noto-cjk を apt-get install
# しておくこと(ワークフロー側で対応)。
_JP_FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Medium.ttc",
]


def find_jp_font() -> str | None:
    for p in _JP_FONT_CANDIDATES:
        if Path(p).exists():
            return p
    return None


def build_telop_filter(telop_lines: list[str], duration: float, width: int, height: int) -> str:
    """テロップ行を動画の長さで等分し、drawtextフィルタのチェーンを作る。"""
    if not telop_lines:
        return ""
    font_path = find_jp_font()
    if font_path is None:
        print(
            "  [warn] 日本語フォントが見つからないため、テロップが文字化け(□)する可能性があります。"
            " fonts-noto-cjk をインストールしてください。",
            file=sys.stderr,
        )
    n = len(telop_lines)
    seg = duration / n
    filters = []
    fontsize = max(36, width // 18)
    y = f"h-{int(height*0.18)}"
    fontfile_opt = f"fontfile='{font_path}':" if font_path else ""
    for i, line in enumerate(telop_lines):
        start = i * seg
        end = duration if i == n - 1 else (i + 1) * seg
        text = escape_drawtext(line)
        filters.append(
            "drawtext="
            f"{fontfile_opt}"
            f"text='{text}':fontsize={fontsize}:fontcolor=white:"
            "box=1:boxcolor=black@0.55:boxborderw=18:"
            f"x=(w-text_w)/2:y={y}:"
            f"enable='between(t,{start:.2f},{end:.2f})'"
        )
    return ",".join(filters)


def assemble_one(day: dict, audio_dir: Path, image_dir: Path, out_dir: Path,
                  bgm_dir: Path | None, width: int, height: int) -> Path:
    day_no = day["day"]
    audio_path = audio_dir / f"day{day_no}.wav"
    image_path = image_dir / f"day{day_no}.png"
    out_path = out_dir / f"day{day_no}.mp4"

    if not audio_path.exists():
        raise FileNotFoundError(f"音声が見つかりません: {audio_path}")
    if not image_path.exists():
        raise FileNotFoundError(f"画像が見つかりません: {image_path}")

    duration = ffprobe_duration(audio_path)
    # ナレーションの前後に少し余白(1秒)を足す
    total = duration + 1.5

    # Ken Burns風: 静止画をゆっくよらズーユパン
    zoom_frames = int(total * 25)  # 25fps想定
    zoompan = (
        f"scale=8000:-1,zoompan=z='min(zoom+0.0007,1.15)':d={zoom_frames}:"
        f"s={width}x{height}:fps=25"
    )
    telop_filter = build_telop_filter(day.get("telop", []), total, width, height)
    vf_chain = zoompan + ("," + telop_filter if telop_filter else "")

    cmd = ["ffmpeg", "-y", "-loop", "1", "-i", str(image_path), "-i", str(audio_path)]

    filter_complex = None
    audio_map = "1:a"
    if bgm_dir is not None:
        bgm_mood = day.get("bgm_mood", "default")
        bgm_path = _find_bgm(bgm_dir, bgm_mood)
        if bgm_path is not None:
            cmd += ["-stream_loop", "-1", "-i", str(bgm_path)]
            # ナレーションを前面、BGMを小音量(0.12)でミックス
            filter_complex = f"[2:a]volume=0.12[bgm];[1:a][bgm]amix=inputs=2:duration=first[aout]"
            audio_map = "[aout]"

    cmd += ["-t", f"{total:.2f}", "-vf", vf_chain]
    if filter_complex:
        cmd += ["-filter_complex", filter_complex, "-map", "0:v", "-map", audio_map]
    else:
        cmd += ["-map", "0:v", "-map", audio_map]

    cmd += [
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
        "-shortest", str(out_path),
    ]

    subprocess.run(cmd, check=True, capture_output=True, text=True)
    return out_path


def _find_bgm(bgm_dir: Path, mood: str) -> Path | None:
    for ext in (".mp3", ".m4a", ".wav"):
        p = bgm_dir / f"{mood}{ext}"
        if p.exists():
            return p
    # moodに合うファイルがなければdefaultを探す
    for ext in (".mp3", ".m4a", ".wav")
        p = bgm_dir / f"default{ext}"
        if p.exists():
            return p
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="音声・画像・テロップ・BGMを1本のmp4に自動画組み立てする")
    ap.add_argument("--data", required=True)
    ap.add_argument("--audio-dir", required=True)
    ap.add_argument("--image-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--bgm-dir", default=None, help="BGMファイルのディレクトリ(任意)")
    ap.add_argument("--width", type=int, default=1080)
    ap.add_argument("--height", type=int, default=1920)
    args = ap.parse_args()

    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        print("[error] ffmpeg / ffprobe が見つかりません", file=sys.stderr)
        return 1

    data = json.loads(Path(args.data).read_text(encoding="utf-8"))
    days = data.get("days", [])
    if not days:
        print("[error] week_data.json に days がありません", file=sys.stderr)
        return 1

    audio_dir = Path(args.audio_dir)
    image_dir = Path(args.image_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    bgm_dir = Path(args.bgm_dir) if args.bgm_dir else None

    for d in days:
        day_no = d["day"]
        print(f"[day {day_no}] 動画組み立て中...")
        try:
            out_path = assemble_one(d, audio_dir, image_dir, out_dir, bgm_dir, args.width, args.height)
            print(f"  -> {out_path}")
        except subprocess.CalledProcessError as e:
            print(f"  [error] ffmpeg failed:\n{e.stderr}", file=sys.stderr)
            return 1

    print(f"完了: {len(days)}本の動画を {out_dir} に出力しました")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
