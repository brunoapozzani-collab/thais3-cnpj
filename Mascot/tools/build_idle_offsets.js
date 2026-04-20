#!/usr/bin/env node
/**
 * Build idle_offsets.json — finds the best-matching idle-loop timestamp
 * for each reaction clip's final frame.
 *
 * Matching metric: MAE on downscaled 64×64 grayscale.
 * No npm dependencies — uses ffmpeg via child_process and raw pixel buffers.
 *
 * Usage:
 *   node tools/build_idle_offsets.js
 *
 * Outputs:
 *   supabase/functions/debora/idle_offsets.json
 *   /tmp/offset_report.txt
 */

const { spawnSync } = require("child_process");
const fs = require("fs");
const path = require("path");

const VIDEOS_DIR = path.resolve(__dirname, "../assets/videos");
const OUTPUT_JSON = path.resolve(__dirname, "../../supabase/functions/debora/idle_offsets.json");
const OUTPUT_REPORT = "/tmp/offset_report.txt";

const IDLE_CLIP = path.join(VIDEOS_DIR, "idle_breathing_loop.mp4");
const SAMPLE_FPS = 15;
const FRAME_W = 64;
const FRAME_H = 64;
const FRAME_BYTES = FRAME_W * FRAME_H; // grayscale

const CLIPS = [
  "wave",
  "laugh",
  "poke_reaction",
  "tickle_belly",
  "tickle_feet",
  "angry",
  "happy",
  "sad",
  "sleepy",
  "pointing_right",
];

// ── helpers ──────────────────────────────────────────────────────────────────

function extractRawFrames(videoPath, fps) {
  /**
   * Extract all frames from a video at `fps` as raw 64×64 grayscale bytes.
   * Returns { frames: Buffer[], timestamps: number[] }
   */
  const args = [
    "-v", "error",
    "-i", videoPath,
    "-vf", `fps=${fps},scale=${FRAME_W}:${FRAME_H},format=gray`,
    "-f", "rawvideo",
    "pipe:1",
  ];
  const result = spawnSync("ffmpeg", args, { maxBuffer: 256 * 1024 * 1024 });
  if (result.status !== 0) {
    throw new Error(`ffmpeg failed for ${videoPath}: ${result.stderr?.toString().slice(-300)}`);
  }

  const buf = result.stdout;
  const count = Math.floor(buf.length / FRAME_BYTES);
  const frames = [];
  const timestamps = [];
  for (let i = 0; i < count; i++) {
    frames.push(buf.slice(i * FRAME_BYTES, (i + 1) * FRAME_BYTES));
    timestamps.push(i / fps);
  }
  return { frames, timestamps };
}

function extractLastFrame(videoPath) {
  /**
   * Extract the last frame of a video as raw 64×64 grayscale bytes.
   */
  const args = [
    "-v", "error",
    "-sseof", "-0.1",
    "-i", videoPath,
    "-vframes", "1",
    "-vf", `scale=${FRAME_W}:${FRAME_H},format=gray`,
    "-f", "rawvideo",
    "pipe:1",
  ];
  const result = spawnSync("ffmpeg", args, { maxBuffer: 4 * 1024 * 1024 });
  if (result.status !== 0 || result.stdout.length < FRAME_BYTES) {
    throw new Error(`ffmpeg failed for ${videoPath}: ${result.stderr?.toString().slice(-300)}`);
  }
  return result.stdout.slice(0, FRAME_BYTES);
}

function mae(frameA, frameB) {
  /** Mean absolute error, normalized to [0, 1]. */
  let sum = 0;
  for (let i = 0; i < FRAME_BYTES; i++) {
    sum += Math.abs(frameA[i] - frameB[i]);
  }
  return sum / FRAME_BYTES / 255;
}

function ssim(frameA, frameB) {
  /** Simplified SSIM on grayscale pixels normalized to [0, 1]. */
  const n = FRAME_BYTES;
  const C1 = 0.0001; // (0.01 * L)^2 with L=1
  const C2 = 0.0009; // (0.03 * L)^2 with L=1

  let muA = 0, muB = 0;
  for (let i = 0; i < n; i++) {
    muA += frameA[i];
    muB += frameB[i];
  }
  muA = muA / n / 255;
  muB = muB / n / 255;

  let varA = 0, varB = 0, cov = 0;
  for (let i = 0; i < n; i++) {
    const da = frameA[i] / 255 - muA;
    const db = frameB[i] / 255 - muB;
    varA += da * da;
    varB += db * db;
    cov += da * db;
  }
  varA /= n;
  varB /= n;
  cov /= n;

  return (
    ((2 * muA * muB + C1) * (2 * cov + C2)) /
    ((muA * muA + muB * muB + C1) * (varA + varB + C2))
  );
}

function findBest(reactionFrame, idleFrames, idleTimestamps) {
  let bestIdx = 0;
  let bestMAE = Infinity;
  for (let i = 0; i < idleFrames.length; i++) {
    const m = mae(reactionFrame, idleFrames[i]);
    if (m < bestMAE) {
      bestMAE = m;
      bestIdx = i;
    }
  }
  return {
    timestamp: idleTimestamps[bestIdx],
    mae: bestMAE,
    ssim: ssim(reactionFrame, idleFrames[bestIdx]),
  };
}

// ── main ─────────────────────────────────────────────────────────────────────

console.log(`Extracting idle loop frames at ${SAMPLE_FPS}fps from ${path.basename(IDLE_CLIP)}...`);
const { frames: idleFrames, timestamps: idleTimestamps } = extractRawFrames(IDLE_CLIP, SAMPLE_FPS);
console.log(`  ${idleFrames.length} idle frames sampled (${idleTimestamps.at(-1).toFixed(2)}s coverage)`);
console.log();

// Frame 0 of idle (used as baseline delta)
const idleFrame0 = idleFrames[0];

const results = [];

for (const clipName of CLIPS) {
  const videoPath = path.join(VIDEOS_DIR, `${clipName}.mp4`);
  if (!fs.existsSync(videoPath)) {
    console.warn(`  [${clipName}] MISSING — skipping`);
    continue;
  }

  try {
    const lastFrame = extractLastFrame(videoPath);

    // Baseline: match against idle frame 0
    const baselineMAE = mae(lastFrame, idleFrame0);
    const baselineSSIM = ssim(lastFrame, idleFrame0);

    // Best match across all idle frames
    const best = findBest(lastFrame, idleFrames, idleTimestamps);
    const improvement = baselineMAE - best.mae;

    results.push({
      clip: clipName,
      timestamp: parseFloat(best.timestamp.toFixed(4)),
      mae: best.mae,
      ssim: best.ssim,
      baseline_mae: baselineMAE,
      baseline_ssim: baselineSSIM,
      improvement,
    });

    console.log(
      `  [${clipName}] best idle t=${best.timestamp.toFixed(3)}s  MAE=${best.mae.toFixed(4)}  SSIM=${best.ssim.toFixed(4)}  Δmae=${improvement >= 0 ? "+" : ""}${improvement.toFixed(4)}`
    );
  } catch (e) {
    console.error(`  [${clipName}] ERROR: ${e.message}`);
  }
}

// ── Write idle_offsets.json ──────────────────────────────────────────────────

const offsets = {};
for (const r of results) {
  offsets[r.clip] = r.timestamp;
}

fs.writeFileSync(OUTPUT_JSON, JSON.stringify(offsets, null, 2) + "\n");
console.log(`\nWrote: ${OUTPUT_JSON}`);

// ── Write /tmp/offset_report.txt ─────────────────────────────────────────────

const sorted = [...results].sort((a, b) => b.improvement - a.improvement);

const lines = [];
lines.push("Idle-offset seam improvement report");
lines.push(`Idle loop sampled at ${SAMPLE_FPS}fps  |  Comparison: 64×64 grayscale MAE`);
lines.push("=".repeat(88));
lines.push(
  `${"CLIP".padEnd(18)} ${"T(s)".padStart(6)} ${"MAE@T".padStart(8)} ${"SSIM@T".padStart(8)} ${"MAE@0".padStart(8)} ${"SSIM@0".padStart(8)} ${"ΔMAE".padStart(9)}`
);
lines.push("-".repeat(88));

for (const r of sorted) {
  const flag = r.improvement > 0.002 ? " ← improved" : r.improvement < -0.001 ? " ← worse" : "";
  lines.push(
    `${r.clip.padEnd(18)} ${r.timestamp.toFixed(3).padStart(6)} ${r.mae.toFixed(4).padStart(8)} ${r.ssim.toFixed(4).padStart(8)} ${r.baseline_mae.toFixed(4).padStart(8)} ${r.baseline_ssim.toFixed(4).padStart(8)} ${(r.improvement >= 0 ? "+" : "") + r.improvement.toFixed(4).padStart(8)}${flag}`
  );
}
lines.push("=".repeat(88));

const report = lines.join("\n") + "\n";
fs.writeFileSync(OUTPUT_REPORT, report);
process.stdout.write("\n" + report);
console.log(`Wrote: ${OUTPUT_REPORT}`);
