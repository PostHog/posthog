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
