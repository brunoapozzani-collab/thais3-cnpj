"""
Check status of the most recent LoRA training.
Auto-writes REPLICATE_LORA_MODEL to .env when training succeeds.

Usage:
    python tools/check_training.py <training_id>
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def update_env(key: str, value: str) -> None:
    env_path = Path(".env")
    lines = env_path.read_text().splitlines()
    updated = False
    for i, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[i] = f"{key}={value}"
            updated = True
            break
    if not updated:
        lines.append(f"{key}={value}")
    env_path.write_text("\n".join(lines) + "\n")


def main():
    import replicate

    if len(sys.argv) < 2:
        print("Usage: python tools/check_training.py <training_id>")
        sys.exit(1)

    training_id = sys.argv[1]
    t = replicate.trainings.get(training_id)

    print(f"Training ID: {t.id}")
    print(f"Status: {t.status}")
    print(f"Started: {t.started_at}")
    print(f"Completed: {t.completed_at}")

    if t.status == "succeeded":
        model_version = f"{t.output['version']}" if isinstance(t.output, dict) and "version" in t.output else None
        if not model_version and hasattr(t, "version") and t.version:
            model_version = str(t.output) if t.output else None
        # Replicate returns the trained model under output.version or similar
        print(f"Output: {t.output}")
        if t.output:
            if isinstance(t.output, dict):
                version = t.output.get("version") or t.output.get("weights")
            else:
                version = str(t.output)
            if version:
                print(f"\nTrained model: {version}")
                update_env("REPLICATE_LORA_MODEL", version)
                print(f"Saved to .env as REPLICATE_LORA_MODEL")

    elif t.status == "failed":
        print(f"ERROR: {t.error}")
        sys.exit(1)
    else:
        print(f"\nStill running. Check back in a few minutes.")
        print(f"URL: https://replicate.com/trainings/{t.id}")


if __name__ == "__main__":
    main()
