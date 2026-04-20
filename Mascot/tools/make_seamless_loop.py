"""
Post-process a video into a guaranteed-seamless loop using palindrome
(play forward then reverse). The last frame equals the first, so the
loop is mathematically seamless.

Usage:
    python tools/make_seamless_loop.py assets/videos/idle_breathing.mp4
    python tools/make_seamless_loop.py assets/videos/idle_breathing.mp4 -o assets/videos/idle_breathing_loop.mp4
"""

import argparse
import subprocess
import sys
from pathlib import Path


def make_palindrome(input_path: Path, output_path: Path) -> None:
    """
    Create a palindrome: forward clip concatenated with its reverse.
    The reverse starts from the frame *before* the last (to avoid duplicate
    frame at the seam), and we skip the first frame of the reverse portion
    so the concatenation doesn't show a freeze.
    """
    # forward: all frames
    # reverse: all frames reversed, drop first (which is the last frame of forward) to avoid duplicate
    filter_complex = (
        "[0:v]split[fwd][rev_src];"
        "[rev_src]reverse,trim=start_frame=1,setpts=PTS-STARTPTS[rev];"
        "[fwd][rev]concat=n=2:v=1[out]"
    )
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-pix_fmt", "yuv420p",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "20",
        "-an",
        str(output_path),
    ]
    print(f"Running: ffmpeg palindrome on {input_path.name}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("FFmpeg failed:")
        print(result.stderr[-2000:])
        sys.exit(1)
    print(f"  Saved: {output_path} ({output_path.stat().st_size / 1024 / 1024:.2f} MB)")


def main():
    parser = argparse.ArgumentParser(description="Create seamless looping video")
    parser.add_argument("input", type=Path, help="Input MP4")
    parser.add_argument("-o", "--output", type=Path, help="Output path (default: <input>_loop.mp4)")
    args = parser.parse_args()

    if not args.input.exists():
        print(f"ERROR: {args.input} not found")
        sys.exit(1)

    output = args.output or args.input.with_name(f"{args.input.stem}_loop.mp4")
    make_palindrome(args.input, output)


if __name__ == "__main__":
    main()
