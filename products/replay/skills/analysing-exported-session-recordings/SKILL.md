---
name: analysing-exported-session-recordings
description: >-
  Decode and analyse a downloaded session-recording export zip (the `data/` blocks
  plus ClickHouse metadata) to understand what is making a recording large or slow:
  size composition by DOM mutations vs full snapshots vs network bodies, biggest
  payloads, content-type breakdown, churned tags/attributes. Use when asked "why is
  this recording so big?", "what's in this export?", "break down replay size for
  this session", "analyse the exported recording", or to validate whether a
  size-reduction change (e.g. skipping binary network bodies) would actually help a
  given session. Pairs with `exporting-session-recordings`, which produces the zip
  this skill reads.
---

# Analysing exported session recordings

An export bundles a recording's raw v2 storage blocks (under `data/`) plus its
ClickHouse metadata (`session-replay-events.json`, `events.json`).
Use this skill to crack those blocks open and measure what the recording is made of,
so size or performance conclusions rest on decoded data — not on raw bytes.

Get the zip first via the `exporting-session-recordings` skill.

## The one thing that will mislead you: the blocks are double-compressed

A `data/` block is **not** readable JSON. It is two layers deep, and skipping either
layer makes the bytes look like binary garbage or "corruption" that isn't there:

1. **Whole block: snappy-compressed.** The exporter fetches blocks with
   `decompress=False` (`export_recording/activities.py`), so it writes the raw S3
   object. Each block is `snappy`-compressed and written at its byte offset, zero-padded
   (so a `data/` file is mostly `\x00` with the real block at the end). Snappy keeps
   literal text runs verbatim with binary copy-tokens between them, which is why a raw
   block reads as "half JSON, half binary".
2. **Per field: gzip-compressed.** Once snappy-decompressed, a block is JSONL of
   `["windowId", {event}]` rows. Events tagged `cv: "2024-10"` have their heavy DOM
   fields (full-snapshot `data`; mutation `adds`/`attributes`/`texts`/`removes`)
   individually gzip-compressed and stored as a binary-in-JSON string via fflate
   `strFromU8(gzipSync(strToU8(json)), true)` — each string char is one gzip byte.

**Do not measure or draw conclusions from the raw block bytes.** Reading them as UTF-8
produces phantom `U+FFFD` runs and wildly wrong size splits (e.g. network bodies look
tiny because they are still snappy-compressed). Always decode both layers first, then
measure. The decoder script below does this; reach for it before hand-rolling anything.

The exporter is lossless — it round-trips the raw S3 block (base64 through Redis, binary
write). Do **not** "fix" the exporter to decompress: export and import are a matched pair
that re-upload the raw blocks, so changing the export format breaks `import_recording`.
The decode belongs on the read side.

## Decoding and the size report

`scripts/decode_recording_export.py` does snappy-then-gzip and reports composition.
It needs a snappy codec (`pip install python-snappy`, or `cramjam`).

```bash
# size + composition report (accepts the zip directly, or an already-extracted dir)
python scripts/decode_recording_export.py export-<session_id>.zip

# also emit fully-decoded events (DOM fields un-gzipped and inlined) for deeper digging
python scripts/decode_recording_export.py export-<session_id>.zip --dump-jsonl decoded.jsonl
```

The report gives you:

- **Decompressed DOM payload** split across full snapshots vs mutation
  `adds`/`attributes`/`texts`/`removes` — `adds` and repeated full snapshots are the
  usual DOM-side offenders.
- **Network bodies** by response content-type — these are stored **un-gzipped** in the
  JSONL, so compare them to DOM on **decoded** size, never on raw bytes.
- **Top tag names and mutated attribute keys**, to see what the DOM churn actually is
  (e.g. SVG icon trees, inline `style` animation churn).

## Reading the numbers honestly

- **Compare like with like.** DOM fields are gzip-then-snappy; network bodies are
  plaintext-then-snappy. The report's decompressed sizes tell you what is _in_ the
  recording (and what the player must hold), which is the right lens for "what should we
  cut". For "what does it cost to store/ingest", remember network bodies compress far
  better than already-gzipped DOM, so their stored share is smaller than their decoded
  share.
- **A handful of blocks may fail to snappy-decompress** (empty/edge blocks). The script
  logs and skips them; a few skips do not move the totals.
- **Blocks are sequential byte ranges and should not overlap** — if you write your own
  pass, sanity-check for duplicate `(name, timestamp, kind, len)` bodies before trusting
  a total.

## Worked example (validated)

A long single-page-app session decoded to ~70 MiB of DOM payload but **~253 MiB of
network bodies**, of which `binary/octet-stream` (136 MiB), `image/webp` (18.5 MiB) and
`image/svg+xml` (3.5 MiB) were binary assets captured as text. The lesson that earned
this skill: measuring those same bodies on the raw (still-snappy) bytes reported only
single-digit MiB and pointed at the wrong culprit. Decoded, the conclusion flips —
skipping binary network bodies (`feat(replay): skip binary/asset bodies in network
capture`, posthog-js #3912) is the dominant lever for a session like this, not a
rounding error. Decode before you conclude.
