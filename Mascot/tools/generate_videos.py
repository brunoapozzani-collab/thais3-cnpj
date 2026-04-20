"""
Generate image-to-video clips for each animation using Kling.

Usage:
    python tools/generate_videos.py --dry-run
    python tools/generate_videos.py --execute --clip idle_breathing
    python tools/generate_videos.py --execute  # generate all
"""

import argparse
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

SPRITES_DIR = Path("assets/sprites")
OUTPUT_DIR = Path("assets/videos")

MODEL = "kwaivgi/kling-v1.6-standard"

_IDLE = (
    "PHASE 1 — IDLE (frames 0–10%): Princess stands in her exact default resting pose. "
    "Arms at sides, head facing forward, eyes looking ahead, shoulders relaxed, "
    "dress and hair completely still. This is the starting frame. "
)

_RECOVER = (
    "PHASE 4 — EXACT IDLE RECOVERY (frames 75–100%): Every body part physically travels back "
    "to its resting position through natural deceleration. "
    "Right arm/hand (if raised): elbow drops first, forearm follows, fingers relax and fall to the right side. "
    "Head: rotates back to face directly forward, chin levels to neutral. "
    "Eyes: return to soft forward gaze, expression neutralizes. "
    "Mouth: closes, smile fades completely to a composed rest. "
    "Shoulders: lower and level, settling to their natural relaxed position. "
    "Torso: straightens, spine neutral, weight centered. "
    "Dress, cape, and sleeves: finish their last natural drift and go completely still. "
    "Braid: stops swinging and hangs naturally at rest. "
    "By frame 88%, she stands fully in her default idle pose — arms at sides, head forward, "
    "eyes forward, shoulders relaxed, expression neutral. "
    "From frame 88% to 100%: she remains in the idle pose with gentle breathing — "
    "chest rises and falls softly, a slow blink may occur, dress fabric rests. "
    "The final frame is indistinguishable from the opening frame. "
    "Camera perfectly static. Background unchanged."
)

CLIPS = {
    "idle_breathing": {
        "source": "idle_stand.png",
        "end_source": "idle_stand.png",
        "prompt": (
            "Elsa ice queen princess standing in calm resting pose. "
            "Subtle natural breathing: chest rises and falls gently, a slow soft blink, "
            "very slight micro-movements of the head. Dress fabric drifts very softly. "
            "Perfectly relaxed regal idle throughout. Camera perfectly static. No background change."
        ),
        "duration": 5,
    },
    "wave": {
        "source": "idle_stand.png",
        "end_source": "idle_stand.png",
        "prompt": (
            f"{_IDLE}"
            "PHASE 2 — ACTION (frames 10–45%): Her chin lifts slightly, a gentle smile forms. "
            "She raises her right hand slowly and delicately, elbow first then wrist, "
            "and performs a soft royal wave side to side. Her sleeve and flowing cape trail naturally. "
            "PHASE 3 — SETTLE (frames 45–75%): She lowers her arm gradually, elbow dropping first, "
            "wrist next, fingers relaxing last. Her smile softens. Her cape and dress sway for a beat. "
            "Her gaze returns forward, posture eases. "
            f"{_RECOVER}"
        ),
        "duration": 10,
    },
    "laugh": {
        "source": "idle_stand.png",
        "end_source": "idle_stand.png",
        "prompt": (
            f"{_IDLE}"
            "PHASE 2 — ACTION (frames 10–45%): A warm amusement crosses her face, eyes crinkle, "
            "a smile grows into a light elegant laugh. Mouth opens, head tilts back slightly, "
            "shoulders lift with gentle mirth. Her platinum braid sways softly with the head movement. "
            "PHASE 3 — SETTLE (frames 45–75%): The laughter softens — mouth closes, smile fades "
            "into lingering warmth, shoulders lower, head tilts forward again, braid swings back. "
            "She exhales quietly and composes herself. "
            f"{_RECOVER}"
        ),
        "duration": 10,
    },
    "poke_reaction": {
        "source": "idle_stand.png",
        "end_source": "idle_stand.png",
        "prompt": (
            f"{_IDLE}"
            "PHASE 2 — ACTION (frames 10–45%): She is lightly touched — eyes widen, a small breath, "
            "chin lifts in mild surprise, hands rise softly at her sides in a composed startle. "
            "A faint amused expression crosses her face. Cape drifts with the motion. "
            "PHASE 3 — SETTLE (frames 45–75%): She exhales slowly, hands lower back to sides, "
            "shoulders drop, expression returns to neutral calm, cape fabric settles gradually. "
            f"{_RECOVER}"
        ),
        "duration": 10,
    },
    "tickle_belly": {
        "source": "idle_stand.png",
        "end_source": "idle_stand.png",
        "prompt": (
            f"{_IDLE}"
            "PHASE 2 — ACTION (frames 10–45%): She is tickled at the waist — a sharp breath, "
            "surprised giggle, hands come toward her stomach, she bends slightly forward laughing, "
            "braid swings forward with the lean. Eyes squint with the laugh. "
            "PHASE 3 — SETTLE (frames 45–75%): She slowly straightens, exhales with a soft smile, "
            "hands fall back to sides, braid swings back, smile fades to soft neutral. "
            f"{_RECOVER}"
        ),
        "duration": 10,
    },
    "tickle_feet": {
        "source": "idle_stand.png",
        "end_source": "idle_stand.png",
        "prompt": (
            f"{_IDLE}"
            "PHASE 2 — ACTION (frames 10–45%): A tickle at her foot — she shifts weight, lifts "
            "one foot slightly with a surprised smile, arms rise gently for balance, dress sways. "
            "She laughs softly. "
            "PHASE 3 — SETTLE (frames 45–75%): She places her foot back down carefully, "
            "shifts weight back to center, arms lower, dress settles with a soft sway, "
            "smile fades to neutral. "
            f"{_RECOVER}"
        ),
        "duration": 10,
    },
    "angry": {
        "source": "idle_stand.png",
        "end_source": "idle_stand.png",
        "prompt": (
            f"{_IDLE}"
            "PHASE 2 — ACTION (frames 10–45%): Her expression hardens — eyebrows draw together, "
            "jaw sets, eyes become cool and sharp. Shoulders pull back, chin lifts, hands close "
            "at her sides with quiet tension. Regal ice-cold displeasure. "
            "PHASE 3 — SETTLE (frames 45–75%): She takes a slow deliberate breath. Shoulders drop, "
            "hands open, jaw releases, eyebrows smooth out, expression softens to neutral calm. "
            f"{_RECOVER}"
        ),
        "duration": 10,
    },
    "happy": {
        "source": "idle_stand.png",
        "end_source": "idle_stand.png",
        "prompt": (
            f"{_IDLE}"
            "PHASE 2 — ACTION (frames 10–45%): Joy spreads across her face — eyes brighten, "
            "a full warm smile blooms. She rises slightly onto her toes, opens her arms outward "
            "and upward in a soft celebratory gesture, head tilts up, braid and cape lift. "
            "PHASE 3 — SETTLE (frames 45–75%): She lowers her arms gradually, settles back from "
            "her toes, braid falls, cape drifts down. The smile softens to a peaceful glow. "
            f"{_RECOVER}"
        ),
        "duration": 10,
    },
    "sad": {
        "source": "idle_stand.png",
        "end_source": "idle_stand.png",
        "prompt": (
            f"{_IDLE}"
            "PHASE 2 — ACTION (frames 10–45%): Sadness crosses her expression — eyes lower, "
            "soft sigh, chin dips toward chest, shoulders curve inward gently. "
            "One hand rises slowly and rests near her heart. She holds the tender sadness. "
            "PHASE 3 — SETTLE (frames 45–75%): A slow breath in — chin lifts softly, hand lowers "
            "back to side, shoulders ease open again, expression returns to quiet calm. "
            f"{_RECOVER}"
        ),
        "duration": 10,
    },
    "sleepy": {
        "source": "idle_stand.png",
        "end_source": "idle_stand.png",
        "prompt": (
            f"{_IDLE}"
            "PHASE 2 — ACTION (frames 10–45%): Drowsiness comes over her — eyelids grow heavy, "
            "a slow elegant yawn forms, one hand rises gracefully to partially cover her mouth. "
            "Eyes close briefly, head tilts slightly, shoulders soften. "
            "PHASE 3 — SETTLE (frames 45–75%): She lowers her hand slowly, blinks eyes back open, "
            "takes a quiet breath, chin lifts, shoulders roll back gently. "
            f"{_RECOVER}"
        ),
        "duration": 10,
    },
    "pointing_right": {
        "source": "idle_stand.png",
        "end_source": "idle_stand.png",
        "prompt": (
            f"{_IDLE}"
            "PHASE 2 — ACTION (frames 10–45%): She turns her head slightly right, gaze follows, "
            "a knowing smile forms. She raises her right arm with grace — elbow first, then forearm "
            "extends, finger points elegantly right, sleeve trails the arc. "
            "PHASE 3 — SETTLE (frames 45–75%): She lowers her arm slowly — elbow drops, hand "
            "relaxes, sleeve settles. Head turns back to center, gaze forward, smile fades. "
            f"{_RECOVER}"
        ),
        "duration": 10,
    },
}


def dry_run(clip_name=None):
    clips = {k: v for k, v in CLIPS.items() if not clip_name or k == clip_name}
    print("=== DRY RUN ===")
    print(f"Model: {MODEL}")
    print(f"Output dir: {OUTPUT_DIR}")
    print(f"Clips to generate: {len(clips)}")
    print()
    for name, c in clips.items():
        print(f"  [{name}] from {c['source']}")
        print(f"    {c['prompt'][:100]}...")
        print(f"    duration: {c['duration']}s")
        print()
    cost_per_10s = 0.50  # kling 1.6 standard ~$0.50 per 10s clip
    reaction_clips = [c for c in clips.values() if c["duration"] == 10]
    idle_clips = [c for c in clips.values() if c["duration"] == 5]
    total = len(reaction_clips) * 0.50 + len(idle_clips) * 0.25
    print(f"Estimated cost: ~${total:.2f} ({len(reaction_clips)} × $0.50 + {len(idle_clips)} × $0.25)")
    print("Run with --execute to generate.")


def execute(clip_name=None):
    import replicate

    token = os.getenv("REPLICATE_API_TOKEN")
    if not token:
        print("ERROR: REPLICATE_API_TOKEN not set in .env")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    clips = {k: v for k, v in CLIPS.items() if not clip_name or k == clip_name}
    if not clips:
        print(f"ERROR: No clip matching '{clip_name}'")
        sys.exit(1)

    print(f"Generating {len(clips)} video clip(s) using {MODEL}")
    print()

    items = list(clips.items())
    for idx, (name, cfg) in enumerate(items):
        output_path = OUTPUT_DIR / f"{name}.mp4"
        if output_path.exists():
            print(f"[{name}] already exists, skipping")
            continue

        source = SPRITES_DIR / cfg["source"]
        if not source.exists():
            print(f"[{name}] source not found: {source}")
            continue

        print(f"[{name}] generating from {source.name}...")
        print(f"  prompt: {cfg['prompt'][:80]}...")

        start = time.time()
        end_src = cfg.get("end_source")
        end_path = SPRITES_DIR / end_src if end_src else None
        if end_path:
            print(f"  end_image: {end_path.name} (idle recovery anchor)")

        with open(source, "rb") as f:
            inputs = {
                "prompt": cfg["prompt"],
                "start_image": f,
                "duration": cfg["duration"],
                "cfg_scale": 0.7,
                "aspect_ratio": "9:16",
                "negative_prompt": "zoom in, zoom out, camera pan, camera movement, camera shake, background change, scene change, distortion, morphing, warping, character changing, different character, freeze, abrupt stop, loop glitch",
            }
            if end_path and end_path.exists():
                end_f = open(end_path, "rb")
                inputs["end_image"] = end_f
                try:
                    output = replicate.run(MODEL, input=inputs)
                finally:
                    end_f.close()
            else:
                output = replicate.run(MODEL, input=inputs)

        if hasattr(output, "read"):
            output_path.write_bytes(output.read())
        elif isinstance(output, str):
            import urllib.request
            urllib.request.urlretrieve(output, output_path)
        elif isinstance(output, list) and len(output) > 0:
            import urllib.request
            urllib.request.urlretrieve(str(output[0]), output_path)

        elapsed = time.time() - start
        print(f"  Saved: {output_path} ({elapsed:.0f}s)")

        if idx < len(items) - 1:
            time.sleep(11)

    print()
    print(f"Done. Videos saved to {OUTPUT_DIR}/")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate image-to-video clips")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Preview (default)")
    parser.add_argument("--execute", action="store_true", help="Run via API")
    parser.add_argument("--clip", type=str, help="Generate one specific clip by name")
    args = parser.parse_args()

    if args.execute:
        execute(clip_name=args.clip)
    else:
        dry_run(clip_name=args.clip)
