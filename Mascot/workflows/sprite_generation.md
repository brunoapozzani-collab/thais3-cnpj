# Sprite Generation Pipeline

## Overview

Generate consistent fox mascot poses using a LoRA model trained on the character.

## Phase 1 — Training Data Preparation

**Input:** Single reference image (`assets/reference/fox_original.png`)

**Steps:**
1. Use an image-to-image AI tool to generate 8-10 variations of the fox from different angles and with different expressions, keeping the same character design
2. Manually review and curate — remove any that drift from the character
3. Place final training set in `assets/reference/training/`

**Tool:** `tools/generate_training_images.py`

## Phase 2 — LoRA Training

**Input:** 8-10 curated training images

**Steps:**
1. Upload training images to Replicate
2. Train LoRA using SDXL fine-tuning (~15 min)
3. Save the trained model URL to `.env` as `REPLICATE_LORA_MODEL`

**Tool:** `tools/train_lora.py`

## Phase 3 — Sprite Pose Generation

**Input:** Trained LoRA model + pose prompts

**Target poses (core set):**
- idle_stand — neutral standing, slight smile
- idle_blink — eyes closed mid-blink
- idle_breathe — subtle chest rise
- wave — right hand up, friendly wave
- laugh — mouth open, eyes squinted, slight lean back
- poke_reaction — surprised face, slight jump
- tickle_belly — giggling, arms guarding belly
- tickle_feet — pulling foot away, laughing
- angry_poke — crossed arms, annoyed eyebrow
- happy — big smile, both hands up
- sad — drooped ears, slight frown
- sleepy — half-closed eyes, yawn
- pointing_right — pointing toward the app half of the screen

**Steps:**
1. Generate each pose via LoRA-powered image generation
2. Remove backgrounds (transparent PNG)
3. Save to `assets/sprites/`

**Tool:** `tools/generate_sprites.py`

## Phase 4 — Sprite Sheet Assembly

**Input:** Individual transparent PNGs

**Steps:**
1. Normalize all sprites to same dimensions
2. Pack into sprite sheets for Pixi.js
3. Generate JSON metadata (frame positions, sizes)
4. Output to `assets/spritesheets/`

**Tool:** `tools/build_spritesheet.py`

## Notes

- All tools default to `--dry-run`. Use `--execute` for real API calls.
- Replicate API key stored in `.env` as `REPLICATE_API_TOKEN`
- Budget: LoRA training ~$1-3, sprite generation ~$0.01-0.05 per image
