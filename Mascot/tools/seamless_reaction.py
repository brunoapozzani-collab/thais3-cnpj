"""
Build a true closed-loop reaction clip.

Takes a Kling image-to-video output and produces a video where:
  - Frame 0 is IDENTICAL to the last frame (mathematically, same pixels)
  - Motion plays forward (idle -> action) then reverses (action -> idle)

Structure produced:
  0%        : idle pose (exact first frame of Kling clip)
  0 -> 50%  : forward motion (idle -> peak action)
  50 -> 100%: reverse motion (peak action -> idle)
  100%      : idle pose (== frame 0)

This is a true palindrome — guaranteed seamless at the loop point.

Usage:
    python tools/seamless_reaction.py assets/videos/wave.mp4
    python tools/seamless_reaction.py assets/videos/wave.mp4 -o custom_output.mp4
    python tools/seamless_reaction.py assets/videos/wave.mp4 --trim-percent 0.6
"""

import argparse
import subprocess
import sys
from pathlib import Path


# Portion of the Kling clip to use for the forward half.
# Kling output is idle -> peak -> attempted-idle. We only want idle -> peak,
# so taking the first half (or a bit more) captures the action cleanly.
DEFAULT_TRIM_PERCENT = 0.55


def get_video_duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(result.stdout.strip())


def make_closed_loop(input_path: Path, output_path: Path, trim_percent: float) -> None:
    duration = get_video_duration(input_path)
    trim_duration = duration * trim_percent

    # Take frames [0, trim_duration], then concatenate with their reverse
    # (skipping the first frame of the reverse to avoid a duplicate at the seam).
    # Result: [0, 1, 2, ..., N, N-1, ..., 1, 0] — frame 0 == last frame mathematically.
    filter_complex = (
        f"[0:v]trim=0:{trim_duration},setpts=PTS-STARTPTS,split[fwd][rev_src];"
        f"[rev_src]reverse,trim=start_frame=1,setpts=PTS-STARTPTS[rev];"
        f"[fwd][rev]concat=n=2:v=1[out]"
    )
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-preset", "fast",
        "-crf", "20",
        "-an",
        str(output_path),
    ]
    print(f"  {input_path.name} (in={duration:.2f}s, trim={trim_duration:.2f}s → out≈{2*trim_duration:.2f}s)")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("FFmpeg failed:")
        print(result.stderr[-3000:])
        sys.exit(1)
    size_mb = output_path.stat().st_size / 1024 / 1024
    print(f"    → {output_path.name} ({size_mb:.2f} MB)")


def main():
    parser = argparse.ArgumentParser(description="Build a true closed-loop reaction clip")
    parser.add_argument("input", type=Path, help="Input reaction MP4")
    parser.add_argument("-o", "--output", type=Path, help="Output path")
    parser.add_argument(
        "--trim-percent", type=float, default=DEFAULT_TRIM_PERCENT,
        help=f"Portion of input to use for forward half (default {DEFAULT_TRIM_PERCENT})",
    )
    args = parser.parse_args()

    if not args.input.exists():
        print(f"ERROR: {args.input} not found")
        sys.exit(1)
    if not (0.1 <= args.trim_percent <= 1.0):
        print("ERROR: --trim-percent must be between 0.1 and 1.0")
        sys.exit(1)

    output = args.output or args.input.with_name(f"{args.input.stem}_seamless.mp4")
    make_closed_loop(args.input, output, args.trim_percent)


if __name__ == "__main__":
    main()
