"""
Diagnose seam quality between each reaction clip's last frame and the idle loop's first frame.

Usage:
    python tools/diagnose_seams.py

Output:
    - Ranked table to stdout (worst mismatch first)
    - /tmp/seam_diagnosis.png — side-by-side grid of all last frames vs idle frame 0
"""

import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from skimage.metrics import structural_similarity as ssim

VIDEOS_DIR = Path("assets/videos")
IDLE_CLIP = VIDEOS_DIR / "idle_breathing_loop.mp4"
OUTPUT_PNG = Path("/tmp/seam_diagnosis.png")

CLIPS = [
    "wave",
    "laugh",
    "poke_reaction",
    "tickle_belly",
    "tickle_feet",
    "angry",
    "happy",
    "sad",
    "sleepy",
    "pointing_right",
]


def extract_frame(video_path: Path, time_offset: str) -> Image.Image:
    """Extract a single frame from a video at a given time offset ('0' = first, 'eof' for last)."""
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        out = Path(f.name)

    if time_offset == "eof":
        # Seek to near end by reading the last frame via sseof
        cmd = [
            "ffmpeg", "-y",
            "-sseof", "-0.1",
            "-i", str(video_path),
            "-vframes", "1",
            "-q:v", "1",
            str(out),
        ]
    else:
        cmd = [
            "ffmpeg", "-y",
            "-ss", time_offset,
            "-i", str(video_path),
            "-vframes", "1",
            "-q:v", "1",
            str(out),
        ]

    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0 or not out.exists():
        raise RuntimeError(f"ffmpeg failed for {video_path}: {result.stderr.decode()[-300:]}")

    img = Image.open(out).convert("RGB")
    out.unlink()
    return img


def compute_metrics(img_a: Image.Image, img_b: Image.Image) -> tuple[float, float]:
    """Return (mae, ssim_score) comparing img_a to img_b (resized to match if needed)."""
    if img_a.size != img_b.size:
        img_b = img_b.resize(img_a.size, Image.LANCZOS)

    arr_a = np.array(img_a, dtype=np.float32) / 255.0
    arr_b = np.array(img_b, dtype=np.float32) / 255.0

    mae = float(np.mean(np.abs(arr_a - arr_b)))
    ssim_score = float(ssim(arr_a, arr_b, channel_axis=2, data_range=1.0))
    return mae, ssim_score


def make_label(text: str, width: int, height: int = 28) -> Image.Image:
    img = Image.new("RGB", (width, height), color=(30, 30, 30))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 14)
    except Exception:
        font = ImageFont.load_default()
    draw.text((4, 6), text, fill=(240, 240, 240), font=font)
    return img


def build_grid(results: list[dict], idle_frame: Image.Image, thumb_w: int = 280) -> Image.Image:
    """Build a side-by-side grid: [idle first frame | reaction last frame] per clip."""
    aspect = idle_frame.height / idle_frame.width
    thumb_h = int(thumb_w * aspect)
    label_h = 28
    row_h = thumb_h + label_h
    cols = 2
    rows = len(results)

    grid = Image.new("RGB", (thumb_w * cols, row_h * rows), color=(20, 20, 20))

    idle_thumb = idle_frame.resize((thumb_w, thumb_h), Image.LANCZOS)

    for i, r in enumerate(results):
        y = i * row_h
        # Left: idle first frame
        idle_label = make_label("idle frame 0", thumb_w)
        grid.paste(idle_label, (0, y))
        grid.paste(idle_thumb, (0, y + label_h))
        # Right: reaction last frame
        clip_label = make_label(
            f"{r['clip']}  MAE={r['mae']:.4f}  SSIM={r['ssim']:.4f}", thumb_w
        )
        reaction_thumb = r["last_frame"].resize((thumb_w, thumb_h), Image.LANCZOS)
        grid.paste(clip_label, (thumb_w, y))
        grid.paste(reaction_thumb, (thumb_w, y + label_h))

    return grid


def main():
    if not IDLE_CLIP.exists():
        print(f"ERROR: idle clip not found at {IDLE_CLIP}")
        sys.exit(1)

    print(f"Extracting idle frame 0 from {IDLE_CLIP}...")
    idle_frame = extract_frame(IDLE_CLIP, "0")

    results = []
    for clip_name in CLIPS:
        video = VIDEOS_DIR / f"{clip_name}.mp4"
        if not video.exists():
            print(f"  [{clip_name}] MISSING — skipping")
            continue
        try:
            last_frame = extract_frame(video, "eof")
            mae, ssim_score = compute_metrics(last_frame, idle_frame)
            results.append({
                "clip": clip_name,
                "mae": mae,
                "ssim": ssim_score,
                "last_frame": last_frame,
            })
            print(f"  [{clip_name}] MAE={mae:.4f}  SSIM={ssim_score:.4f}")
        except Exception as e:
            print(f"  [{clip_name}] ERROR: {e}")

    if not results:
        print("No results to display.")
        sys.exit(1)

    # Rank worst first (highest MAE = worst match)
    ranked = sorted(results, key=lambda r: r["mae"], reverse=True)

    print()
    print("=" * 52)
    print(f"{'RANK':<5} {'CLIP':<20} {'MAE':>8} {'SSIM':>8}")
    print("-" * 52)
    for rank, r in enumerate(ranked, 1):
        flag = " ← worst" if rank == 1 else (" ← best" if rank == len(ranked) else "")
        print(f"{rank:<5} {r['clip']:<20} {r['mae']:>8.4f} {r['ssim']:>8.4f}{flag}")
    print("=" * 52)

    print(f"\nBuilding grid PNG...")
    grid = build_grid(ranked, idle_frame)
    grid.save(OUTPUT_PNG)
    print(f"Saved: {OUTPUT_PNG}")


if __name__ == "__main__":
    main()
