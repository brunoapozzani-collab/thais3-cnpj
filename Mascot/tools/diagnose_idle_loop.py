#!/usr/bin/env python3
"""
diagnose_idle_loop.py — measure the continuity of the idle loop at its wrap point.

Extracts:
  - frame 0 (first frame)
  - last frame (via ffmpeg -sseof)
  - frame at (duration - 0.5s)

Computes MAE and SSIM for each against frame 0.
Saves a labeled side-by-side PNG to /tmp/idle_loop_seam.png.

Usage:
    python tools/diagnose_idle_loop.py
"""

import json
import re
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from skimage.metrics import structural_similarity as skssim

# ── config ────────────────────────────────────────────────────────────────────

SCRIPT_DIR  = Path(__file__).parent
VIDEOS_DIR  = SCRIPT_DIR.parent / "assets" / "videos"
IDLE_CLIP   = VIDEOS_DIR / "idle_breathing_loop.mp4"
OUTPUT_PNG  = Path("/tmp/idle_loop_seam.png")

DIAG_W = 64   # grayscale comparison resolution
DIAG_H = 64
DISPLAY_W = 320  # per-frame display size in output PNG
DISPLAY_H = 320

# ── ffprobe ───────────────────────────────────────────────────────────────────

def ffprobe_duration(path):
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "format=duration",
        "-of", "json", str(path),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    d = json.loads(r.stdout)
    return float(d["format"]["duration"])


# ── frame extraction ──────────────────────────────────────────────────────────

def extract_frame_gray(path, ss=None, sseof=None):
    """Extract one frame as DIAG_W×DIAG_H grayscale float32 array [0,1]."""
    cmd = ["ffmpeg", "-v", "error"]
    if sseof is not None:
        cmd += ["-sseof", str(sseof)]
    if ss is not None:
        cmd += ["-ss", f"{ss:.6f}"]
    cmd += [
        "-i", str(path),
        "-vframes", "1",
        "-vf", f"scale={DIAG_W}:{DIAG_H},format=gray",
        "-f", "rawvideo", "pipe:1",
    ]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0 or len(r.stdout) < DIAG_W * DIAG_H:
        raise RuntimeError(f"frame extract failed: {r.stderr.decode()[-300:]}")
    buf = np.frombuffer(r.stdout[:DIAG_W * DIAG_H], dtype=np.uint8)
    return buf.reshape(DIAG_H, DIAG_W).astype(np.float32) / 255.0


def extract_frame_rgb(path, ss=None, sseof=None):
    """Extract one frame as DISPLAY_W×DISPLAY_H RGB bytes for PIL."""
    cmd = ["ffmpeg", "-v", "error"]
    if sseof is not None:
        cmd += ["-sseof", str(sseof)]
    if ss is not None:
        cmd += ["-ss", f"{ss:.6f}"]
    cmd += [
        "-i", str(path),
        "-vframes", "1",
        "-vf", f"scale={DISPLAY_W}:{DISPLAY_H}",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
    ]
    r = subprocess.run(cmd, capture_output=True)
    n = DISPLAY_W * DISPLAY_H * 3
    if r.returncode != 0 or len(r.stdout) < n:
        raise RuntimeError(f"RGB frame extract failed: {r.stderr.decode()[-300:]}")
    arr = np.frombuffer(r.stdout[:n], dtype=np.uint8).reshape(DISPLAY_H, DISPLAY_W, 3)
    return Image.fromarray(arr)


# ── metrics ───────────────────────────────────────────────────────────────────

def mae(a, b):
    return float(np.mean(np.abs(a - b)))


def ssim(a, b):
    return float(skssim(a, b, data_range=1.0))


# ── PNG assembly ──────────────────────────────────────────────────────────────

def make_grid(frames_rgb, labels):
    """Stitch frames into a labeled horizontal grid."""
    n = len(frames_rgb)
    pad = 8
    label_h = 32
    W = n * (DISPLAY_W + pad) + pad
    H = DISPLAY_H + label_h + 2 * pad
    grid = Image.new("RGB", (W, H), (30, 30, 30))
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 18)
    except Exception:
        font = ImageFont.load_default()

    draw = ImageDraw.Draw(grid)
    for i, (img, label) in enumerate(zip(frames_rgb, labels)):
        x = pad + i * (DISPLAY_W + pad)
        y = pad
        grid.paste(img, (x, y))
        draw.text((x + 4, y + DISPLAY_H + 4), label, fill=(220, 220, 220), font=font)

    return grid


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    if not IDLE_CLIP.exists():
        print(f"ERROR: idle clip not found at {IDLE_CLIP}", file=sys.stderr)
        sys.exit(1)

    duration = ffprobe_duration(IDLE_CLIP)
    t_pre    = max(0.0, duration - 0.5)

    print(f"Idle clip:   {IDLE_CLIP.name}")
    print(f"Duration:    {duration:.4f}s")
    print()

    print("Extracting frames...")
    f0        = extract_frame_gray(IDLE_CLIP, ss=0.0)
    f_last    = extract_frame_gray(IDLE_CLIP, sseof=-0.05)
    f_pre05   = extract_frame_gray(IDLE_CLIP, ss=t_pre)

    f0_rgb      = extract_frame_rgb(IDLE_CLIP, ss=0.0)
    f_last_rgb  = extract_frame_rgb(IDLE_CLIP, sseof=-0.05)
    f_pre05_rgb = extract_frame_rgb(IDLE_CLIP, ss=t_pre)

    mae_last   = mae(f_last,  f0)
    ssim_last  = ssim(f_last, f0)
    mae_pre05  = mae(f_pre05, f0)
    ssim_pre05 = ssim(f_pre05, f0)

    print(f"{'Metric':<30} {'MAE':>8} {'SSIM':>8}  {'Verdict'}")
    print("-" * 62)
    print(f"{'last frame  vs frame 0':<30} {mae_last:>8.4f} {ssim_last:>8.4f}  "
          f"{'CONTINUOUS' if ssim_last >= 0.92 else 'DISCONTINUOUS ← SNAP SOURCE'}")
    print(f"{'frame-0.5s  vs frame 0':<30} {mae_pre05:>8.4f} {ssim_pre05:>8.4f}  "
          f"{'CONTINUOUS' if ssim_pre05 >= 0.92 else 'DISCONTINUOUS ← SNAP SOURCE'}")
    print()

    # PNG grid
    labels = [
        "frame 0 (loop start)",
        f"last frame ({duration:.2f}s)",
        f"frame-0.5s ({t_pre:.2f}s)",
    ]
    grid = make_grid([f0_rgb, f_last_rgb, f_pre05_rgb], labels)
    grid.save(OUTPUT_PNG)
    print(f"Saved: {OUTPUT_PNG}")
    print()

    # Decision hint
    if ssim_last < 0.92 or ssim_pre05 < 0.92:
        print("DECISION: SSIM < 0.92 — idle loop is discontinuous at wrap point → Phase 3A applies.")
    else:
        print("DECISION: SSIM ≥ 0.92 — idle loop wraps cleanly. Snap is NOT the idle wrap point.")


if __name__ == "__main__":
    main()
