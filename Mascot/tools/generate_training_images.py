"""
Generate training images for LoRA fine-tuning from a single reference image.
Uses Replicate's image-to-image models to create consistent variations.

Usage:
    python tools/generate_training_images.py --dry-run
    python tools/generate_training_images.py --execute
"""

import argparse
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

REFERENCE_IMAGE = Path("assets/reference/elsa_original.png")
OUTPUT_DIR = Path("assets/reference/training")

OUTFIT = "shimmering ice-blue ball gown with snowflake crystalline cape, platinum blonde French braid, pale skin, blue eyes, ice queen tiara"

VARIATION_PROMPTS = [
    f"Elsa from Frozen wearing {OUTFIT}, front view, neutral calm regal expression, standing upright, premium 3D illustration, cool blue cinematic lighting",
    f"Elsa from Frozen wearing {OUTFIT}, slight left three-quarter turn, gentle elegant smile, standing upright, premium 3D illustration, cool blue cinematic lighting",
    f"Elsa from Frozen wearing {OUTFIT}, slight right three-quarter turn, gentle elegant smile, standing upright, premium 3D illustration, cool blue cinematic lighting",
    f"Elsa from Frozen wearing {OUTFIT}, front view, laughing elegantly with mouth open, eyes sparkling, premium 3D illustration, cool blue cinematic lighting",
    f"Elsa from Frozen wearing {OUTFIT}, front view, surprised expression, eyes wide open, snowflakes floating, premium 3D illustration, cool blue cinematic lighting",
    f"Elsa from Frozen wearing {OUTFIT}, front view, waving right hand gracefully, warm smile, premium 3D illustration, cool blue cinematic lighting",
    f"Elsa from Frozen wearing {OUTFIT}, front view, arms crossed gracefully, confident elegant smirk, premium 3D illustration, cool blue cinematic lighting",
    f"Elsa from Frozen wearing {OUTFIT}, front view, sleepy yawning expression, half-closed eyes, premium 3D illustration, cool blue cinematic lighting",
    f"Elsa from Frozen wearing {OUTFIT}, front view, pointing to the right with right hand, confident smile, ice sparkles, premium 3D illustration, cool blue cinematic lighting",
    f"Elsa from Frozen wearing {OUTFIT}, three-quarter view, hands on hips, proud regal stance, premium 3D illustration, cool blue cinematic lighting",
]


def dry_run():
    print("=== DRY RUN ===")
    print(f"Reference image: {REFERENCE_IMAGE}")
    print(f"Output directory: {OUTPUT_DIR}")
    print(f"Variations to generate: {len(VARIATION_PROMPTS)}")
    print()
    for i, prompt in enumerate(VARIATION_PROMPTS):
        print(f"  [{i+1:02d}] {prompt}")
    print()
    print("Estimated cost: ~$0.50 (10 images × ~$0.05 each)")
    print("Run with --execute to generate.")


def execute():
    import replicate

    token = os.getenv("REPLICATE_API_TOKEN")
    if not token:
        print("ERROR: REPLICATE_API_TOKEN not set in .env")
        sys.exit(1)

    if not REFERENCE_IMAGE.exists():
        print(f"ERROR: Reference image not found at {REFERENCE_IMAGE}")
        print("Place the Elsa reference image there first.")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Generating {len(VARIATION_PROMPTS)} variations...")
    print()

    for i, prompt in enumerate(VARIATION_PROMPTS):
        output_path = OUTPUT_DIR / f"variation_{i+1:02d}.png"
        if output_path.exists():
            print(f"[{i+1:02d}/{len(VARIATION_PROMPTS)}] already exists, skipping")
            continue

        print(f"[{i+1:02d}/{len(VARIATION_PROMPTS)}] {prompt[:60]}...")

        with open(REFERENCE_IMAGE, "rb") as img_file:
            output = replicate.run(
                "black-forest-labs/flux-1.1-pro",
                input={
                    "prompt": prompt,
                    "image": img_file,
                    "prompt_upsampling": True,
                    "aspect_ratio": "3:4",
                    "output_format": "png",
                    "safety_tolerance": 5,
                },
            )

        if hasattr(output, "read"):
            output_path.write_bytes(output.read())
        elif isinstance(output, str):
            import urllib.request
            urllib.request.urlretrieve(output, output_path)
        elif isinstance(output, list) and len(output) > 0:
            import urllib.request
            urllib.request.urlretrieve(str(output[0]), output_path)

        print(f"  Saved: {output_path}")

        if i < len(VARIATION_PROMPTS) - 1:
            time.sleep(12)

    print()
    print(f"Done. {len(VARIATION_PROMPTS)} images saved to {OUTPUT_DIR}/")
    print("Review them and remove any that drift from the character before training.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate LoRA training images")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Preview what will be generated (default)")
    parser.add_argument("--execute", action="store_true", help="Actually generate images via API")
    args = parser.parse_args()

    if args.execute:
        execute()
    else:
        dry_run()
