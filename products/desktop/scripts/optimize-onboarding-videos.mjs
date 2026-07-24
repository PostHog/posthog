#!/usr/bin/env node
// Optimize the onboarding bento-card demo videos for smooth in-app playback.
//
// The cards (packages/ui/src/features/onboarding) play a short looping clip in
// a slot that never renders wider than ~500 CSS px. Raw screen recordings come
// in at 2x+ that resolution with the moov atom at the end of the file, which
// makes playback hitch on first play / seek / the framer-motion slot reflow.
//
// This re-encodes each clip to a sane width with faststart so the player can
// begin instantly, and tags the output so re-runs skip already-optimized files.
//
// See .claude/skills/onboarding-videos/SKILL.md for the full workflow (posters,
// adding a new clip, the WelcomeScreen videoStartTime contract).
import { execFileSync } from "node:child_process";
import { readdirSync, renameSync, statSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const ASSET_DIR = join(ROOT, "packages/ui/src/features/onboarding/assets");

// Tuning. The poster JPGs are authored at 1000px wide; match them so the
// poster -> first-frame seam is pixel-consistent. Bump only if the bento slot
// grows — bigger means heavier decode for no visible gain at this size.
const TARGET_WIDTH = 1000;
const CRF = 23; // visually lossless for flat UI screencasts; lower = bigger.
const PRESET = "veryslow"; // one-time encode, so spend the CPU on compression.
// Marker written into the file's `comment` tag so re-runs are idempotent.
const MARKER = `optimized-by=optimize-onboarding-videos w<=${TARGET_WIDTH} crf=${CRF}`;

const USAGE = `optimize-onboarding-videos — re-encode onboarding demo clips for smooth playback.

  node scripts/optimize-onboarding-videos.mjs            optimize clips not already optimized
  node scripts/optimize-onboarding-videos.mjs --force    re-encode every clip (e.g. after changing TARGET_WIDTH/CRF)
  node scripts/optimize-onboarding-videos.mjs --dry-run   report what would change, encode nothing

Target: H.264 yuv420p, width<=${TARGET_WIDTH}px, CRF ${CRF}, faststart, no audio.`;

const args = new Set(process.argv.slice(2));
if (args.has("-h") || args.has("--help")) {
  console.log(USAGE);
  process.exit(0);
}
const force = args.has("--force");
const dryRun = args.has("--dry-run");

function ffprobe(file, entries, stream) {
  const selectArgs = stream ? ["-select_streams", stream] : [];
  return execFileSync(
    "ffprobe",
    [
      "-v",
      "error",
      ...selectArgs,
      "-show_entries",
      entries,
      "-of",
      "default=noprint_wrappers=1:nokey=1",
      file,
    ],
    { encoding: "utf8" },
  ).trim();
}

function isOptimized(file) {
  const comment = ffprobe(file, "format_tags=comment");
  const width = Number(ffprobe(file, "stream=width", "v:0"));
  return comment === MARKER && Number.isFinite(width) && width <= TARGET_WIDTH;
}

function kb(bytes) {
  return `${(bytes / 1024).toFixed(0)} KB`;
}

function ensureFfmpeg() {
  try {
    execFileSync("ffmpeg", ["-version"], { stdio: "ignore" });
    execFileSync("ffprobe", ["-version"], { stdio: "ignore" });
  } catch {
    console.error(
      "ffmpeg/ffprobe not found on PATH. Install with: brew install ffmpeg",
    );
    process.exit(1);
  }
}

function optimize(file) {
  const before = statSync(file).size;
  const tmp = `${file}.opt.mp4`;
  execFileSync(
    "ffmpeg",
    [
      "-y",
      "-i",
      file,
      // Cap width, keep aspect with an even height, crisp downscale. Never
      // upscales a source already narrower than the target.
      "-vf",
      `scale='min(${TARGET_WIDTH},iw)':-2:flags=lanczos`,
      "-c:v",
      "libx264",
      "-profile:v",
      "high",
      "-pix_fmt",
      "yuv420p",
      "-crf",
      String(CRF),
      "-preset",
      PRESET,
      "-movflags",
      "+faststart", // moov atom up front -> player starts without reading EOF.
      "-an", // muted in the UI; drop the audio track entirely.
      "-map_metadata",
      "-1", // strip source metadata, then stamp our marker.
      "-metadata",
      `comment=${MARKER}`,
      tmp,
    ],
    { stdio: ["ignore", "ignore", "inherit"] },
  );
  const after = statSync(tmp).size;
  renameSync(tmp, file);
  return { before, after };
}

ensureFfmpeg();

let clips;
try {
  clips = readdirSync(ASSET_DIR)
    .filter((name) => name.endsWith(".mp4"))
    .sort();
} catch {
  console.error(`Asset dir not found: ${ASSET_DIR}`);
  process.exit(1);
}

if (clips.length === 0) {
  console.error(`No .mp4 clips in ${ASSET_DIR}`);
  process.exit(1);
}

let optimized = 0;
let skipped = 0;
let totalBefore = 0;
let totalAfter = 0;

for (const name of clips) {
  const file = join(ASSET_DIR, name);
  if (!force && isOptimized(file)) {
    console.log(`  skip   ${name} (already optimized)`);
    skipped++;
    continue;
  }
  if (dryRun) {
    console.log(`  would  ${name} (${kb(statSync(file).size)})`);
    continue;
  }
  const { before, after } = optimize(file);
  totalBefore += before;
  totalAfter += after;
  optimized++;
  const pct = (((before - after) / before) * 100).toFixed(0);
  console.log(`  ok     ${name}  ${kb(before)} -> ${kb(after)}  (-${pct}%)`);
}

if (dryRun) {
  console.log(`\nDry run: ${clips.length - skipped} clip(s) would be encoded.`);
} else if (optimized > 0) {
  console.log(
    `\nOptimized ${optimized} clip(s): ${kb(totalBefore)} -> ${kb(totalAfter)} total.`,
  );
} else {
  console.log("\nNothing to do — all clips already optimized.");
}
