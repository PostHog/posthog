# Replay anonymizer performance plan

Working doc for the ml-mirror anonymizer perf push (PR #67917). Delete before merge or move to a follow-up issue.

## Where we are (M4 Pro re-baseline, 2026-07-03)

The original ladder (rungs 1–8) is done, measured, or explicitly declined; see per-rung status below.
`cargo run --release --example anonymize_bench -p replay-anonymizer-node` decomposes everything (it prints the taken route and the dedupe cost too);
fixtures come from un-skipping `anonymize/dev/anonymize-bench.test.ts`, which also gives the end-to-end TS-vs-addon comparison.

End-to-end through the FFI (same-run pairs; the TS side swings ±20% run to run, the ratio pairs are honest):

| fixture | TS pipeline | Rust addon | speedup (was at re-baseline) |
|---|---|---|---|
| large 3.3 MB DOM-heavy | 62.1 ms | 33.4 ms | 1.86x (was 1.22x) |
| medium 1.1 MB DOM-heavy | 18.8 ms | 12.1 ms | 1.56x (was 1.17x) |

In-addon (cargo bench, stable to ±0.3 ms):

| | at re-baseline | now |
|---|---|---|
| mousemove-heavy 1.7 MB / 12k events (the by-count prod regime) | 12.6 ms | 7.0 ms |
| large end-to-end (production entry) | 40.9 ms | 31.0 ms (routes to tree) |
| large outer envelope | 7.0 ms | ~5.4 ms (~1.5 ms of that is the bench's own payload clone) |
| tree path large | 21.0 ms | 20.9 ms |
| scrub walk floor large | 8.7 ms | ~6.8 ms |

The sandbox premise ("streaming wins by-count, loses DOM-heavy") inverted twice on real hardware:
first M4 said the tree wins everywhere; after rungs 1+2 the streaming path beats the tree in the by-count regime (7.0 vs 7.4+outer) and sits ~5 ms behind it on DOM-heavy.
**M4 and the sandbox x86 disagree on the stream/tree crossover; only prod canary data settles it** — that's what the `route` metric label exists for.

## Guardrails (unchanged, non-negotiable)

- `cargo test -p replay-anonymizer-node` stays green — especially `tests/snapshot.rs`: the stream-vs-tree differential (fixtures + seeded fuzz, **with adaptive routing forced off** so it pins the streaming path) and the leak tests (escaped keys, duplicate keys, byte-exact pass-through, JSONL framing).
- Jest `shared-fixtures.test.ts` drives the production byte API against the built addon.
- Fail-closed posture: scanner uncertainty falls back to a real parse; unchanged scrub-routed events re-serialize from the parsed tree (duplicate-key shadow-content leak); adaptive routing may only abort to the tree while the buffer is intact (the scratch budget exists for exactly this).

## Ladder status

1. **In-place data-span parse — DONE.** `split_at_mut` in `process_event_at`; the per-event scratch memcpy is gone. Early small events (< 64 KB cumulative) still copy-parse via scratch so routing stays possible (real messages open with a scrub-routed Meta event).
2. **Merged per-event scans — DONE.** One walk per event discovers its own end and captures type/timestamp/cv + data's depth-1 source/type/href/payload; the envelope scan walks root+properties once. This was the biggest single win (mousemove 12.6→7.0).
3. **skip_string tuning — DONE, went further.** SWAR-first (8-byte words, zero setup) escalating to memchr after 32 clean bytes, in `skip_string` and both unescapers. memchr3 in `skip_balanced` was tried and **rejected** (~20% regression on bracket-dense payloads — the structural gaps between strings are too short to amortize memchr setup).
4. **Outer envelope scan — DONE.** Single-pass scan for `distinct_id`+`data`, then the data string is unescaped *in place* inside the payload buffer (no allocation; decoded JSON never outgrows its escaped form), UTF-8-validated. Full-parse fallback (before any mutation) keeps classification parity. 7.0 → ~2 ms/MB.
5. **Dedupe folding — MEASURED AND DECLINED.** The walk costs 1.3 ms on the large fixture (bench prints it). A byte-level full-depth duplicate detector costs about as much as the walk it would skip, and folding into the scrub walk is unsound (the scrub walk doesn't visit every object; unvisited dup objects would leak shadow content on re-serialize). The v2-style byte walk (below) obviates it instead.
6. **Adaptive routing — DONE, wash on M4.** A scrub-routed data span > 50% of the message aborts to the tree path, only while nothing has been consumed in place. On M4 the routed cost ≈ streaming cost (the ~5 ms of scan work before the abort can't be shared with the tree's parse); the sandbox x86 numbers had the tree winning DOM-heavy by ~20%. The FFI returns `route` and `recording_blob_ingestion_v2_ml_anonymize_duration_ms` carries it as a label — **tune `TREE_ROUTE_MIN_DATA_FRACTION` from canary, or delete routing if prod x86 looks like M4.**
7. **FFI output copy — DONE.** `JsBuffer::external` (neon `external-buffers` feature; safe, we never run under V8 sandboxed pointers). Input copy stays (threadpool hop + in-place processing needs owned bytes anyway).
8. **Scrub-walk floor — DONE.** ahash allow-lists, bytewise ASCII-fast tokenizer with bulk non-word-run copies, in-place attr scrub via `iter_mut` (no per-element key Vec). 8.7 → ~6.8 ms on large. A reusable scrub-output buffer was evaluated and skipped: the tree stores `Cow::Owned`, so the per-changed-value allocation is structural until the byte walk lands.

Also done beyond the ladder: **decompression moved into the addon** (lz4 block + capture's LE size prefix, gzip by magic bytes, 256 MB cap, `invalid_compressed_data` parity) — `gunzipSync` no longer blocks the event loop.

## MLHog v2 comparison (the byte-walk endgame)

`MLHog/prep/labeling/src/v2` is a fully parse-free byte rewriter: it never builds a tree even for scrub-routed events, byte-copies unchanged subtrees (`copy_value` = one structural skip + one memcpy), re-emits only changed strings, and re-uses a thread-local scrub buffer.
Techniques already adopted from it: SWAR/hybrid string scanning, zero-copy unescape, byte-slice key dispatch, reusable worker buffers, the O(N) email scan (we had it independently).
The remaining architectural gap is the walk itself: our scrub route still simd-parses the whole `data` span and re-serializes it (plus the dedupe walk), where v2 touches only the bytes it changes.
Porting that walk is the real path to the scrub floor: it removes parse + dedupe + encode for scrub-routed events entirely (~15 of the 21 ms tree cost on large), and the stream/tree split with it.
It is PII-sensitive: the fail-closed duplicate-key story changes shape (v2 scrubs *every* occurrence during the walk rather than re-serializing a deduped tree), so it needs the differential + fuzz corpus extended before it ships.
Estimated ceiling if it lands: large DOM-heavy in-addon ~12–15 ms (≈ 4x vs TS), by-count unchanged (already scan-bound).

## Tried and rejected: fusing scan_event into the byte walk

The walk pays two structural passes (scan_event for span/routing/meta, then the walk). Fusing them
into one emit-while-walking pass measured **flat on DOM-heavy (26.4 vs 26.3 ms) and a 22% regression
on mousemove-heavy (8.2 vs 6.7 ms)**, and was reverted. Why: after the SWAR work, scan_event *skips*
a snapshot's bytes at memchr speed (~1 ms/3 MB) — there was no second walk-grade pass to reclaim —
while the fused routing pre-scans added real per-event cost to the ~90% of events that decline to
the scan path. The two-pass structure is the right shape: a near-free skipping pass that routes,
then walk-grade traversal only where scrubbing happens. (The attempt also surfaced that a fused
walker must pre-check `data`'s shape for snapshots — a string could be a cv blob — which the
fail-closed test caught; that check is inherent to any future re-attempt.)

With the scrub-leaf work (bulk `write_json_string`, chunked redaction marks, allow-list length-mask
rejects), the full-contract numbers are: large 26.1 ms (vs the MLHog-v2 engine's 30.0 on the same contract
after its redundant routing re-scan was removed via `scrub_line_scanned`, and the tree's ~23 with
outer work), medium 8.8 ms. The remaining profile is dominated by
`scrub_text` + `skip_string` + emission — i.e. genuine scrub work; we are near the floor for this
contract on M4.

## Producer byte order (capture) — the walker is now order-independent

Capture deserializes every replay payload into `serde_json::Value` (BTreeMap) and re-serializes it,
so **real prod messages have alphabetized keys at every level** — `childNodes` before `tagName`/
`type` in every node. The walker's original routing pre-scans budget-busted on that order and
declined everything big; `walk_node` now walks in document order, defers the small order-sensitive
members as spans, emits children optimistically (splicing the rare script/style discovery), and
tree-redoes odd node shapes locally — no pre-scans, order-independent, faster than the pre-scan
design on both orders. The bench fixtures are serde-sorted (prod-accurate); the static test
fixtures keep insertion order, so the differential pins both.

Two follow-ups this surfaced: (1) the vendored MLHog v2 walk goes **quadratic on prod byte order**
(203 ms vs 29 on the same fixture) — its production labeling pipeline is likely paying this today;
(2) capture could keep `snapshot_data` as `Box<RawValue>` and byte-splice the arrays instead of
materializing Values — saving capture CPU on every replay payload *and* restoring SDK-native key
order for all consumers.

## Real production data (1000 session blocks from the ml-training bucket)

`dev/prod_bench.rs` replays payloads rebuilt (byte-preserving) from 1000 real ml-mirror session
blocks (76% web / 24% mobile, 451 MB decompressed). Findings that synthetic fixtures missed:

- **Node-level alphabetization is confirmed in prod bytes** (every observed uncompressed snapshot
  has `childNodes` before `tagName`), so the order-independent walk is required, not optional.
- **40% of prod events (37% of bytes) are cv-gzip-compressed**, and mobile wireframes route to the
  parse path too — so on real traffic all three architectures converge (crate walk 9.6 ms/msg avg,
  walk-off 10.2, MLHog engine 9.4; all ~47 MB/s): the cost is dominated by the shared
  gunzip -> parse -> scrub -> regzip cv path, not traversal.
- Consequently **the biggest real-world lever left is the cv path**: libdeflater over flate2 (the
  one MLHog technique not yet adopted), and byte-walking the decompressed payload instead of
  tree-parsing it. The traversal wins measured on uncompressed fixtures still stand, but they
  apply to the uncompressed minority of today's traffic mix.

### cv-path moves (done): libdeflater + byte-walk + per-field recompression

Landed as a set; corpus average went **9.6 -> 5.94 ms/msg (47 -> 76 MB/s), 0 failures**
(libdeflater one-shot decoded all 1000 prod streams). Same corpus, same run:
crate walk 5.94 / walk-off 6.10 / MLHog engine 6.51 ms/msg.

- **libdeflater for every gzip leg** (`src/gzip.rs`): one-shot codec sized from the gzip ISIZE
  footer, 256 MB bomb cap *before* allocation (footer lying small fails with InsufficientSpace —
  both directions fail closed), thread-local (de)compressor state. Used by cv, the outer
  Kafka-payload gunzip, and the MLHog port (restoring its original codec — the flate2 port was a
  downgrade we introduced).
- **Byte-walk the decompressed cv payload** (`bytewalk::scrub_cv_snapshot` /
  `scrub_cv_mutation_field`): the same self-guarded walkers the uncompressed stream path uses, so
  the scrub semantics were already pinned by the stream/tree differential; parse fallback on
  decline (escaped/duplicate keys, non-array sub-fields, over-deep). The whole-buffer depth
  pre-scan moved from `decompress_string` to the parse fallbacks only — the walk bounds its own
  recursion and copies unwalked spans iteratively, mirroring the uncompressed path.
- **Per-field recompression**: only sub-fields the scrub actually changed are re-gzipped; the TS
  pipeline re-compresses every sub-field once any changed, which re-encodes identical content.
  Same payload after gunzip, and level-6 compression is the single most expensive leg (see below).

Tried and rejected here: a hand-rolled byte-level latin-1 transcode (replacing `chars()`).
Measured *slower* on the corpus — gzip bytes are high-entropy, so the ASCII/two-byte branch
mispredicts either way, there is no run structure to exploit, and the safe indexed loop adds
bounds checks that `chars()`'s internals avoid. Reverted to per-char with an exact presize.

### Post-move profile (prod corpus, top of stack)

1. **Level-6 deflate of changed cv payloads: ~29%** of all samples — the dominant cost by 3x, and
   real traffic recompresses *more* than this corpus (see biases below). The remaining lever is a
   product knob, not engineering: gzip level for re-compressed payloads (level 1 compresses ~3-5x
   faster for ~10-15% larger output; storage vs CPU). Also worth checking why a *pre-scrubbed*
   corpus recompresses at all — likely non-idempotent css rewrite / attr-stash output; harmless
   for single-scrub prod, but it inflates corpus recompress rates and would double-stash if a
   payload were ever scrubbed twice.
2. **latin-1 transcode + cv strings through the event tree parse: ~10%** combined
   (`decompress_string`/`compress_bytes` transcode ~7.5%, plus part of simd `parse_str`). The
   structural fix is extending the byte walk to compressed events themselves: unescape the cv
   string straight off the wire span into gzip bytes (mlhog-style `latin1_from_json`), skipping
   the UTF-8 `String` materialization and the event-tree parse of the wrapper. **Done** —
   `bytewalk::latin1_from_wire`/`write_latin1_json_string` plus compressed routes in
   `scrub_data_bytes` mirroring `route_data`: corpus average 5.94 -> 5.59 ms/msg (81 MB/s), and
   tree-routed messages fell 206 -> 41 (compressed events no longer force the tree). Pinned by a
   dedicated cv differential (every cv shape, stream-vs-tree, verified to fail on an injected
   wire-writer bug) and an all-256-byte codec round-trip test.
3. `skip_string` ~10% — SWAR structural skipping; fundamental to walking, already tuned.
4. Outer unescape (`next_backslash` + `unescape_in_place`) ~6%; gunzip ~4.5% (was ~3x that under
   flate2); remaining `max_bracket_depth` ~2.5% is the guards ahead of tree-route/scratch parses.

### cv re-compression codec measurements (`dev/compression_bench.rs`)

Measured on the decompressed cv payloads extracted from the prod corpus (153k payloads / 589 MB
full, or an even-stride 1k sample — both give the same relative picture; M4, single thread).
Full-corpus table:

| codec               | compress MB/s | decompress MB/s | ratio |
| ------------------- | ------------- | --------------- | ----- |
| gzip (libdeflate) 1 | 369           | 1628            | 0.169 |
| gzip (libdeflate) 3 | 267           | 1663            | 0.162 |
| gzip (libdeflate) 6 | 184           | 1671            | 0.149 |
| gzip (libdeflate) 9 | 78            | 1632            | 0.146 |
| zstd 1              | 958           | 2628            | 0.149 |
| zstd 3              | 843           | 2609            | 0.143 |
| zstd 6              | 293           | 2857            | 0.129 |
| zstd 12             | 99            | 3070            | 0.123 |
| lz4 block           | 1351          | 6120            | 0.232 |

Conclusions:

- **zstd level 1 equals gzip level 6's ratio at ~5x the compress speed** (and ~1.6x the decompress
  speed for the consumer); zstd 3 beats the ratio at ~4.5x. Since compression of changed payloads
  is the single largest pipeline cost, re-emitting changed cv payloads as zstd is the biggest
  remaining lever — the SDK input stays gzip (we always decode gzip), only the re-emitted format
  changes. It needs a format marker (e.g. a new `cv` version value) and support in the one
  consumer, the MLHog prep loader — a coordinated but small change, deliberately not made
  unilaterally here.
- Staying gzip: level 3 is ~1.45x compress speed for ~9% more storage, level 1 ~2x for ~13% more.
  Real but far less attractive than the format switch.
- The corpus median cv payload decompresses to **2 bytes** (`[]` — the SDK gzips even empty
  mutation sub-field arrays); volume, and therefore cost, is concentrated in the large snapshot
  payloads.

Provenance checks on the corpus (it is the *output* of the TS scrubber, so know the biases):

- **cv-gzip is SDK-origin, not a storage artifact**: `cv: "2024-10"` is set by posthog-js
  (`lazy-loaded-session-recorder.ts`), which gzips large event payloads client-side; the block
  bytes carry the gzip magic (`\u001f\u008b\b`) as latin-1-in-JSON. The scrubber keeps or
  re-compresses cv payloads, so the ~40% share is representative of consumer input.
- **Event-level key order in the blocks is zod-normalized** (`timestamp` first) by the TS parse
  step — true consumer input is capture-alphabetized at every level. Node-level order in the
  blocks is untouched and confirms the alphabetization.
- **Text is already scrubbed** (redaction-mark runs tokenize as non-words), so the corpus
  understates scrub-change rates — and therefore cv *re-compression* cost, which only changed
  payloads pay and which is several times the decompress cost. Real input costs more than the
  measured 9.6 ms/msg for every implementation, weighted toward the cv path — strengthening,
  not weakening, the cv-lever conclusion.

## Remaining TS-side work (from the framework audit)

Nothing on the `useRustAnonymizer` path parses the Kafka payload in TS anymore. What's left, by cost:

1. **Snappy + `Buffer.concat` at flush** (`snappy-session-recorder.ts`) — heaviest remaining TS CPU; moving it needs an accumulate-across-messages addon API (per-session state), a real design change. Follow-up.
2. **`parseJSON(result.meta!)`** — ~1–3 KB per message; binary meta (or fields on the result object) would shave it. Low priority.
3. **Segmentation sort + events[] walk at flush** — Rust could return aggregates/pre-sorted events. Low priority.
4. TopHog stringifies `{token, session_id}` 3–4x per message as Map keys; a string concat would do. Shared-framework micro-noise; left alone deliberately.

## Rollout (unchanged, plus route)

1. Canary with `SESSION_RECORDING_ML_RUST_ANONYMIZER=true`; watch `recording_blob_ingestion_v2_ml_anonymize_duration_ms{impl=...,route=...}` (direct A/B vs TS, and stream-vs-tree per regime) and `..._ml_anonymize_failed` (~0; every failure is a dropped message).
2. Use the route label to tune or delete `TREE_ROUTE_MIN_DATA_FRACTION` on prod hardware.
3. Compare consumer lag burn-down, not just per-message latency — the event loop is now free during scrub *and* decompression, so batch concurrency behaves differently.
4. Watch dlq/drop reason rates vs the TS baseline — classification parity is tested (including `invalid_compressed_data` now), but prod traffic is the real fixture.

In parallel (ops, multiplies with everything): scale replicas/vCPU on the ml-mirror deployment while the flag rolls out.
