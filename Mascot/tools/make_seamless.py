"""
make_seamless.py — post-process reaction clips into seamless idle-handoff versions.

For clips in PROCESS_CLIPS (default: pointing_right, angry):
  1. Detect motion-settling point in last 2s via inter-frame MAE threshold.
  2. Backup existing _seamless.mp4 to _seamless.prev.mp4.
  3. Trim the clip to that settling point.
  4. Append a 400ms crossfade tail: settling-frame → idle frame at the
     offset stored in supabase/functions/debora/idle_offsets.json.
  5. Output assets/videos/{name}_seamless.mp4 at source resolution/fps/codec.
  6. Measure before/after SSIM and log to /tmp/seam_finish.log.

For all other clips: cp {name}.mp4 → {name}_seamless.mp4 if missing.

Usage:
    python tools/make_seamless.py
    python tools/make_seamless.py --clips laugh,happy,tickle_feet
"""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from fractions import Fraction
from pathlib import Path

import numpy as np
from skimage.metrics import structural_similarity as skssim

# ── config ───────────────────────────────────────────────────────────────────

VIDEOS_DIR = Path("assets/videos")
IDLE_CLIP  = VIDEOS_DIR / "idle_breathing_loop.mp4"
OFFSETS_JSON = Path("../supabase/functions/debora/idle_offsets.json")
LOG_FILE   = Path("/tmp/seam_finish.log")

PROCESS_CLIPS = ["pointing_right", "angry"]

ALL_CLIPS = [
    "wave", "laugh", "poke_reaction", "tickle_belly", "tickle_feet",
    "angry", "happy", "sad", "sleepy", "pointing_right",
]

TAIL_DURATION = 0.4    # seconds for crossfade tail
LAST_N_SECS   = 2.0    # search window for settling detection
SETTLE_MAE    = 0.010  # inter-frame MAE threshold (0–1) — below = settled
DETECT_SIZE   = 64     # pixel width/height for motion detection
CRF           = 18     # h264 quality for encoded segments

# ── helpers ──────────────────────────────────────────────────────────────────

def ffprobe(video_path):
    """Return dict with width, height, fps (float), duration (float), pix_fmt."""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate,pix_fmt",
        "-show_entries", "format=duration",
        "-of", "json", str(video_path),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    d = json.loads(r.stdout)
    s = d["streams"][0]
    fps = float(Fraction(s["r_frame_rate"]))
    return {
        "width":    s["width"],
        "height":   s["height"],
        "fps":      fps,
        "pix_fmt":  s.get("pix_fmt", "yuv420p"),
        "duration": float(d["format"]["duration"]),
    }


def extract_raw_gray(video_path, ss=None, duration=None, sseof=None):
    """
    Extract frames as raw DETECT_SIZE×DETECT_SIZE grayscale bytes.
    Returns list of float32 arrays normalized to [0,1].
    """
    vf = f"scale={DETECT_SIZE}:{DETECT_SIZE},format=gray"
    cmd = ["ffmpeg", "-v", "error"]
    if sseof is not None:
        cmd += ["-sseof", str(sseof)]
    if ss is not None:
        cmd += ["-ss", f"{ss:.6f}"]
    cmd += ["-i", str(video_path)]
    if duration is not None:
        cmd += ["-t", f"{duration:.6f}"]
    cmd += ["-vf", vf, "-f", "rawvideo", "pipe:1"]

    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg raw extract failed: {r.stderr.decode()[-300:]}")

    buf = r.stdout
    n_bytes = DETECT_SIZE * DETECT_SIZE
    count = len(buf) // n_bytes
    frames = [
        np.frombuffer(buf[i * n_bytes:(i + 1) * n_bytes], dtype=np.uint8).astype(np.float32) / 255.0
        for i in range(count)
    ]
    return frames


def measure_ssim(video_path, idle_offset):
    """SSIM of video's last frame vs idle@idle_offset on 64×64 grayscale."""
    last = extract_raw_gray(video_path, sseof=-0.1)
    if not last:
        return float("nan")
    idle = extract_raw_gray(IDLE_CLIP, ss=idle_offset)
    if not idle:
        return float("nan")
    a = last[-1].reshape(DETECT_SIZE, DETECT_SIZE)
    b = idle[0].reshape(DETECT_SIZE, DETECT_SIZE)
    return float(skssim(a, b, data_range=1.0))


def detect_settling(video_path, source_duration, threshold=SETTLE_MAE):
    """
    Find the timestamp in the last LAST_N_SECS where inter-frame MAE first
    drops below `threshold`. Falls back to quietest frame if not found.

    Returns (settling_t, all_maes, all_timestamps)
    """
    window_start = max(0.0, source_duration - LAST_N_SECS)
    window_dur   = source_duration - window_start

    frames = extract_raw_gray(video_path, ss=window_start, duration=window_dur)
    if len(frames) < 2:
        return source_duration - 0.5, [], []

    info = ffprobe(video_path)
    fps  = info["fps"]

    maes  = []
    times = []
    for i in range(1, len(frames)):
        m = float(np.mean(np.abs(frames[i] - frames[i - 1])))
        maes.append(m)
        times.append(window_start + i / fps)

    settling_t = None
    for t, m in zip(times, maes):
        if m < threshold:
            settling_t = t
            break

    if settling_t is None:
        idx = int(np.argmin(maes))
        settling_t = times[idx]
        print(f"    [warn] no frame below threshold {threshold:.4f}; using quietest "
              f"(MAE={maes[idx]:.4f}) at t={settling_t:.3f}s")

    return settling_t, maes, times


def extract_frame_png(video_path, timestamp, output_path, width, height):
    """Extract one frame at `timestamp` as a full-resolution PNG."""
    cmd = [
        "ffmpeg", "-v", "error",
        "-ss", f"{timestamp:.6f}",
        "-i", str(video_path),
        "-vframes", "1",
        "-vf", f"scale={width}:{height}",
        "-q:v", "1",
        "-y", str(output_path),
    ]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0 or not output_path.exists():
        raise RuntimeError(f"Frame extract failed at t={timestamp:.3f}s: {r.stderr.decode()[-300:]}")


def build_crossfade_tail(frame_a, frame_b, fps, pix_fmt, output_path):
    """400ms dissolve from frame_a still image to frame_b still image."""
    cmd = [
        "ffmpeg", "-v", "error",
        "-loop", "1", "-framerate", str(int(fps)), "-t", str(TAIL_DURATION), "-i", str(frame_a),
        "-loop", "1", "-framerate", str(int(fps)), "-t", str(TAIL_DURATION), "-i", str(frame_b),
        "-filter_complex",
        f"[0:v][1:v]xfade=transition=dissolve:offset=0:duration={TAIL_DURATION},"
        f"format={pix_fmt}[xf]",
        "-map", "[xf]",
        "-c:v", "libx264", "-crf", str(CRF), "-preset", "fast",
        "-r", str(int(fps)),
        "-y", str(output_path),
    ]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(f"Crossfade build failed: {r.stderr.decode()[-400:]}")


def trim_clip(video_path, end_t, pix_fmt, fps, output_path):
    """Trim source to [0, end_t], re-encode to ensure clean cut."""
    cmd = [
        "ffmpeg", "-v", "error",
        "-i", str(video_path),
        "-t", f"{end_t:.6f}",
        "-vf", f"format={pix_fmt}",
        "-c:v", "libx264", "-crf", str(CRF), "-preset", "fast",
        "-r", str(int(fps)),
        "-an",
        "-y", str(output_path),
    ]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(f"Trim failed: {r.stderr.decode()[-300:]}")


def concat_segments(seg_a, seg_b, pix_fmt, fps, output_path):
    """Concatenate two video segments using the concat filter."""
    cmd = [
        "ffmpeg", "-v", "error",
        "-i", str(seg_a),
        "-i", str(seg_b),
        "-filter_complex",
        f"[0:v][1:v]concat=n=2:v=1:a=0,format={pix_fmt}[v]",
        "-map", "[v]",
        "-c:v", "libx264", "-crf", str(CRF), "-preset", "fast",
        "-r", str(int(fps)),
        "-an",
        "-y", str(output_path),
    ]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(f"Concat failed: {r.stderr.decode()[-300:]}")


def log(msg):
    print(msg)
    with open(LOG_FILE, "a") as f:
        f.write(msg + "\n")


# ── per-clip processing ───────────────────────────────────────────────────────

def process_clip(name, idle_offsets):
    source   = VIDEOS_DIR / f"{name}.mp4"
    output   = VIDEOS_DIR / f"{name}_seamless.mp4"
    backup   = VIDEOS_DIR / f"{name}_seamless.prev.mp4"

    info = ffprobe(source)
    w, h = info["width"], info["height"]
    fps  = info["fps"]
    pix  = info["pix_fmt"]
    dur  = info["duration"]

    idle_offset = idle_offsets.get(name, 0.0)

    log(f"  source duration:  {dur:.3f}s")
    log(f"  resolution/fps:   {w}×{h} @ {fps:.0f}fps  pix={pix}")
    log(f"  idle offset:      {idle_offset:.4f}s")

    # Measure before SSIM (on existing seamless if present, else source)
    measure_src = output if output.exists() else source
    ssim_before = measure_ssim(measure_src, idle_offset)
    log(f"  SSIM before:      {ssim_before:.4f}  (from {measure_src.name})")

    # Backup existing seamless
    if output.exists():
        shutil.copy2(output, backup)
        log(f"  backed up:        {backup.name}")

    # Detect settling
    log(f"  detecting settling in last {LAST_N_SECS}s (threshold MAE < {SETTLE_MAE})...")
    settling_t, _, _ = detect_settling(source, dur)
    log(f"  settling point:   t={settling_t:.3f}s")

    with tempfile.TemporaryDirectory() as tmp:
        tmp     = Path(tmp)
        trimmed = tmp / "trimmed.mp4"
        tail    = tmp / "tail.mp4"
        frame_a = tmp / "settling.png"
        frame_b = tmp / "idle_frame.png"

        log(f"  trimming to t={settling_t:.3f}s...")
        trim_clip(source, settling_t, pix, fps, trimmed)

        log(f"  extracting settling frame...")
        extract_frame_png(source, settling_t, frame_a, w, h)

        log(f"  extracting idle frame at t={idle_offset:.4f}s...")
        extract_frame_png(IDLE_CLIP, idle_offset, frame_b, w, h)

        log(f"  building {TAIL_DURATION*1000:.0f}ms crossfade tail...")
        build_crossfade_tail(frame_a, frame_b, fps, pix, tail)

        log(f"  concatenating segments...")
        concat_segments(trimmed, tail, pix, fps, output)

    actual_dur  = ffprobe(output)["duration"]
    ssim_after  = measure_ssim(output, idle_offset)
    log(f"  output duration:  {actual_dur:.3f}s  → {output.name}")
    log(f"  SSIM after:       {ssim_after:.4f}")
    log(f"  SSIM delta:       {ssim_after - ssim_before:+.4f}")

    return settling_t, actual_dur, ssim_before, ssim_after


def copy_if_missing(name):
    source   = VIDEOS_DIR / f"{name}.mp4"
    seamless = VIDEOS_DIR / f"{name}_seamless.mp4"
    if seamless.exists():
        print(f"  {seamless.name} already exists — skipping")
        return
    if not source.exists():
        print(f"  {source.name} not found — skipping")
        return
    shutil.copy2(source, seamless)
    print(f"  copied → {seamless.name}")


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Build seamless reaction clips")
    parser.add_argument(
        "--clips",
        type=lambda s: [c.strip() for c in s.split(",")],
        default=None,
        help="Comma-separated list of clip names to process (default: PROCESS_CLIPS constant)",
    )
    args = parser.parse_args()

    process = args.clips if args.clips else PROCESS_CLIPS

    if not IDLE_CLIP.exists():
        print(f"ERROR: idle clip not found at {IDLE_CLIP}")
        sys.exit(1)

    if not OFFSETS_JSON.exists():
        print(f"ERROR: idle_offsets.json not found at {OFFSETS_JSON}")
        sys.exit(1)

    idle_offsets = json.loads(OFFSETS_JSON.read_text())

    log("=" * 60)
    log(f"make_seamless run — processing: {process}")
    log("=" * 60)

    results = {}
    for name in process:
        log(f"\n[{name}] — settle + crossfade")
        source = VIDEOS_DIR / f"{name}.mp4"
        if not source.exists():
            log(f"  {source} not found — skipping")
            continue
        try:
            settling_t, out_dur, ssim_b, ssim_a = process_clip(name, idle_offsets)
            results[name] = dict(settling_t=settling_t, out_dur=out_dur,
                                 ssim_before=ssim_b, ssim_after=ssim_a,
                                 idle_offset=idle_offsets.get(name, 0.0))
        except Exception as e:
            log(f"  ERROR: {e}")

    # Copy remaining clips if seamless missing
    skip = set(process)
    others = [n for n in ALL_CLIPS if n not in skip]
    if others:
        log("\n── copy pass " + "─" * 46)
        for name in others:
            print(f"[{name}]")
            copy_if_missing(name)

    # Summary table
    if results:
        log("\n── summary " + "─" * 49)
        log(f"{'CLIP':<18} {'SETTLE':>7} {'IDLE_OFF':>9} {'OUT_DUR':>8} {'SSIM_BEF':>9} {'SSIM_AFT':>9} {'DELTA':>7}")
        log("-" * 75)
        for name, r in results.items():
            log(
                f"{name:<18} {r['settling_t']:>7.3f} {r['idle_offset']:>9.4f} "
                f"{r['out_dur']:>8.3f} {r['ssim_before']:>9.4f} {r['ssim_after']:>9.4f} "
                f"{r['ssim_after']-r['ssim_before']:>+7.4f}"
            )
        log("─" * 75)

    log("\nDone.")


if __name__ == "__main__":
    main()
