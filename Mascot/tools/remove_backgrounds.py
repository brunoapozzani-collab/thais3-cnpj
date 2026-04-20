"""
Remove backgrounds from all sprites, producing transparent PNGs.
Uses Replicate's background removal model.

Usage:
    python tools/remove_backgrounds.py --dry-run
    python tools/remove_backgrounds.py --execute
"""

import argparse
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

SPRITES_DIR = Path("assets/sprites")
OUTPUT_DIR = Path("assets/sprites_transparent")
MODEL = "851-labs/background-remover:a029dff38972b5fda4ec5d75d7d1cd25aeff621d2cf4946a41055d7db66b80bc"


def dry_run():
    sprites = sorted(SPRITES_DIR.glob("*.png"))
    print("=== DRY RUN ===")
    print(f"Input dir: {SPRITES_DIR}")
    print(f"Output dir: {OUTPUT_DIR}")
    print(f"Model: {MODEL.split(':')[0]}")
    print(f"Sprites to process: {len(sprites)}")
    for s in sprites:
        print(f"  - {s.name}")
    print(f"Estimated cost: ~${len(sprites) * 0.01:.2f}")
    print("Run with --execute to process.")


def execute():
    import replicate

    token = os.getenv("REPLICATE_API_TOKEN")
    if not token:
        print("ERROR: REPLICATE_API_TOKEN not set in .env")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    sprites = sorted(SPRITES_DIR.glob("*.png"))
    print(f"Processing {len(sprites)} sprites...")
    print()

    for idx, sprite in enumerate(sprites):
        output_path = OUTPUT_DIR / sprite.name
        if output_path.exists():
            print(f"[{sprite.name}] already processed, skipping")
            continue

        print(f"[{sprite.name}] removing background...")
        with open(sprite, "rb") as f:
            output = replicate.run(MODEL, input={"image": f})

        if hasattr(output, "read"):
            output_path.write_bytes(output.read())
        elif isinstance(output, str):
            import urllib.request
            urllib.request.urlretrieve(output, output_path)
        elif isinstance(output, list) and len(output) > 0:
            import urllib.request
            urllib.request.urlretrieve(str(output[0]), output_path)

        print(f"  Saved: {output_path}")

        if idx < len(sprites) - 1:
            time.sleep(11)

    print()
    print(f"Done. Transparent sprites saved to {OUTPUT_DIR}/")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Remove backgrounds from sprites")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Preview (default)")
    parser.add_argument("--execute", action="store_true", help="Run via API")
    args = parser.parse_args()

    if args.execute:
        execute()
    else:
        dry_run()
