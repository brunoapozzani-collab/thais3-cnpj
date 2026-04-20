"""
Generate sprite poses using the trained LoRA model.

Usage:
    python tools/generate_sprites.py --dry-run
    python tools/generate_sprites.py --execute
    python tools/generate_sprites.py --execute --pose idle_stand
"""

import argparse
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

OUTPUT_DIR = Path("assets/sprites")
TRIGGER_WORD = "thais_elsa"

POSES = {
    "idle_stand": f"{TRIGGER_WORD}, standing upright, neutral regal expression, gentle smile, arms at sides, full body, transparent background",
    "idle_blink": f"{TRIGGER_WORD}, standing upright, eyes closed mid-blink, relaxed elegant pose, full body, transparent background",
    "wave": f"{TRIGGER_WORD}, standing upright, waving right hand gracefully, warm smile, snowflakes sparkling, full body, transparent background",
    "laugh": f"{TRIGGER_WORD}, standing upright, laughing elegantly, mouth open, eyes sparkling with joy, slight lean back, full body, transparent background",
    "poke_reaction": f"{TRIGGER_WORD}, startled surprised face, hands up in shock, ice crystals burst around her, eyes wide open, elegant cartoon surprise, full body, transparent background",
    "tickle_belly": f"{TRIGGER_WORD}, laughing hard, both hands clutching her stomach, eyes squeezed shut laughing, mouth wide open, ice sparkles flying, full body visible, transparent background",
    "tickle_feet": f"{TRIGGER_WORD}, standing on one leg with the other foot lifted, laughing hard, one hand reaching down, frosty sparkles around feet, full body, transparent background",
    "angry_poke": f"{TRIGGER_WORD}, icy furious face, eyebrows furrowed, eyes narrowed and intense glaring, hands clenched with frost emanating, ice shards forming around her, angry ice queen expression, full body, transparent background",
    "happy": f"{TRIGGER_WORD}, big radiant smile, both hands up celebrating, snowflakes swirling joyfully, full body, transparent background",
    "sad": f"{TRIGGER_WORD}, sad face with frozen tears, mouth frowning down, shoulders slumped, ice crystals dimming around her, deeply melancholic, full body, transparent background",
    "sleepy": f"{TRIGGER_WORD}, half-closed eyes, yawning elegantly, drowsy, snowflakes falling gently, full body, transparent background",
    "pointing_right": f"{TRIGGER_WORD}, pointing to the right with right hand, confident smile, ice trail following her gesture, full body, transparent background",
}

STYLE_SUFFIX = ", premium 3D illustration, cool blue cinematic lighting, ice-blue ball gown, snowflake cape, white background"


def dry_run(pose_filter=None):
    poses = {k: v for k, v in POSES.items() if not pose_filter or k == pose_filter}
    print("=== DRY RUN ===")
    print(f"LoRA model: {os.getenv('REPLICATE_LORA_MODEL', '(not set)')}")
    print(f"Output directory: {OUTPUT_DIR}")
    print(f"Poses to generate: {len(poses)}")
    print()
    for name, prompt in poses.items():
        print(f"  [{name}]")
        print(f"    {prompt}{STYLE_SUFFIX}")
        print()
    print(f"Estimated cost: ~${len(poses) * 0.05:.2f}")
    print("Run with --execute to generate.")


def execute(pose_filter=None):
    import replicate

    token = os.getenv("REPLICATE_API_TOKEN")
    if not token:
        print("ERROR: REPLICATE_API_TOKEN not set in .env")
        sys.exit(1)

    lora_model = os.getenv("REPLICATE_LORA_MODEL")
    if not lora_model:
        print("ERROR: REPLICATE_LORA_MODEL not set in .env")
        print("Train the LoRA first: python tools/train_lora.py --execute")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    poses = {k: v for k, v in POSES.items() if not pose_filter or k == pose_filter}

    print(f"Generating {len(poses)} sprites using LoRA: {lora_model}")
    print()

    items = list(poses.items())
    for idx, (name, prompt) in enumerate(items):
        output_path = OUTPUT_DIR / f"{name}.png"
        if output_path.exists():
            print(f"[{name}] already exists, skipping")
            continue

        full_prompt = f"{prompt}{STYLE_SUFFIX}"
        print(f"[{name}] {full_prompt[:70]}...")

        output = replicate.run(
            lora_model,
            input={
                "prompt": full_prompt,
                "num_outputs": 1,
                "aspect_ratio": "3:4",
                "output_format": "png",
                "guidance_scale": 7.5,
                "num_inference_steps": 28,
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

        if idx < len(items) - 1:
            time.sleep(12)

    print()
    print(f"Done. Sprites saved to {OUTPUT_DIR}/")
    print("Next: python tools/build_spritesheet.py --dry-run")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate sprite poses with LoRA")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Preview poses (default)")
    parser.add_argument("--execute", action="store_true", help="Generate via API")
    parser.add_argument("--pose", type=str, help="Generate a single pose by name")
    args = parser.parse_args()

    if args.execute:
        execute(pose_filter=args.pose)
    else:
        dry_run(pose_filter=args.pose)
