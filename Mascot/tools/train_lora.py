"""
Train a LoRA model on Replicate using the curated training images.

Usage:
    python tools/train_lora.py --dry-run
    python tools/train_lora.py --execute
"""

import argparse
import os
import sys
import zipfile
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

TRAINING_DIR = Path("assets/reference/training")
TMP_ZIP = Path(".tmp/training_images.zip")
TRIGGER_WORD = "thais_elsa"


def dry_run():
    images = list(TRAINING_DIR.glob("*.png")) + list(TRAINING_DIR.glob("*.jpg"))
    print("=== DRY RUN ===")
    print(f"Training directory: {TRAINING_DIR}")
    print(f"Images found: {len(images)}")
    for img in sorted(images):
        print(f"  - {img.name}")
    print(f"Trigger word: {TRIGGER_WORD}")
    print(f"Estimated cost: ~$2-3")
    print(f"Estimated time: ~15-20 minutes")
    print()
    if len(images) < 3:
        print("WARNING: Fewer than 3 images. Consider generating more variations first.")
    print("Run with --execute to start training.")


def execute():
    import replicate

    token = os.getenv("REPLICATE_API_TOKEN")
    if not token:
        print("ERROR: REPLICATE_API_TOKEN not set in .env")
        sys.exit(1)

    images = list(TRAINING_DIR.glob("*.png")) + list(TRAINING_DIR.glob("*.jpg"))
    if len(images) < 3:
        print(f"ERROR: Only {len(images)} images found. Need at least 3 for training.")
        sys.exit(1)

    username = os.getenv("REPLICATE_USERNAME")
    if not username:
        print("ERROR: REPLICATE_USERNAME not set in .env")
        sys.exit(1)

    model_name = "thais-elsa-lora"
    destination = f"{username}/{model_name}"

    try:
        replicate.models.get(destination)
        print(f"Destination model exists: {destination}")
    except Exception:
        print(f"Creating destination model: {destination}")
        replicate.models.create(
            owner=username,
            name=model_name,
            visibility="private",
            hardware="gpu-t4",
            description="Thais (Elsa) mascot LoRA — trained on character reference",
        )
        print(f"  Created.")

    print(f"Packaging {len(images)} images into zip...")
    TMP_ZIP.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(TMP_ZIP, "w") as zf:
        for img in images:
            zf.write(img, img.name)

    print(f"Starting LoRA training on Replicate...")
    print(f"Trigger word: {TRIGGER_WORD}")
    print()

    with open(TMP_ZIP, "rb") as zf:
        training = replicate.trainings.create(
            version="ostris/flux-dev-lora-trainer:d995297071a44dcb72244e6c19462111649ec86a9646c32df56daa7f14801944",
            input={
                "input_images": zf,
                "trigger_word": TRIGGER_WORD,
                "steps": 1000,
                "learning_rate": 0.0004,
                "batch_size": 1,
                "resolution": "1024",
                "autocaption": True,
            },
            destination=destination,
        )

    print(f"Training started!")
    print(f"Training ID: {training.id}")
    print(f"Status URL: https://replicate.com/trainings/{training.id}")
    print()
    print("Training takes ~15-20 minutes. When done:")
    print(f"1. Copy the model URL to .env as REPLICATE_LORA_MODEL")
    print(f"2. Run: python tools/generate_sprites.py --dry-run")

    TMP_ZIP.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train LoRA on Replicate")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Preview training config (default)")
    parser.add_argument("--execute", action="store_true", help="Start training via API")
    args = parser.parse_args()

    if args.execute:
        execute()
    else:
        dry_run()
