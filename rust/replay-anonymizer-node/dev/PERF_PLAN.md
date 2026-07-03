# Path to 2.5x: replay anonymizer performance plan

Working doc for the ml-mirror anonymizer perf push (PR #67917). Delete before merge or move to a
follow-up issue.

## Where we are

Shipped on this branch: byte-buffer FFI (rung ①), zero-copy borrowed tree (rung ②), streaming
per-event rewrite with a tree fallback/reference (rung ③), differential-tested.

Numbers from the cloud sandbox (gVisor, 1 shared core — ~3-4x slower than a laptop and noisier;
**re-baseline everything on real hardware first**):

| fixture (3.3 MB DOM-heavy) | ms | vs TS |
|---|---|---|
| TS pipeline (parse + scrub + serialize) | 115.7 | 1.0x |
| Rust byte path, streaming (production) | 89.5 end-to-end / 66 in-addon | ~1.3x |
| Rust byte path if routed via tree | ~54 in-addon (47 inner + 7 outer parse) | ~2.1x |
| scrub walk alone (the floor) | ~16 | ceiling ≈ 2.5-3x |

The surprise: on all-scrub DOM-heavy fixtures the **streaming path loses to the tree path** (60 vs
47 ms inner). The fixture has zero pass-through events, so streaming pays its extra scan passes
(event scan, data scan, scratch memcpy, per-span parse setup) with no memcpy wins. On a
mousemove-heavy fixture (the realistic by-count regime) streaming wins (21.0 vs 22.4+outer).
`cargo run --release --example anonymize_bench` decomposes all of this.

Target: 2.5x ⇒ in-addon total ≈ 46 ms on the sandbox scale, i.e. shave ~20 ms off the streaming
path (or ~8 ms off tree + adaptive routing).

## Guardrails (non-negotiable while optimizing)

- `cargo test -p replay-anonymizer-node` must stay green — especially `tests/snapshot.rs`: the
  stream-vs-tree differential (fixtures + seeded fuzz) and the leak tests (escaped keys, duplicate
  keys, byte-exact pass-through, JSONL framing). Any scanner change reruns these; extend the fuzz
  corpus when adding scanner capabilities.
- Jest `shared-fixtures.test.ts` drives the production byte API against the built addon.
- Fail-closed posture: scanner uncertainty (escaped keys, dup routing keys, newlines) must keep
  falling back to a real parse; unchanged scrub-routed events must keep re-serializing from the
  parsed tree (duplicate-key shadow-content leak).

## Step 0 — re-baseline on real hardware

1. `pnpm --filter=@posthog/replay-anonymizer build` (release addon)
2. un-skip `anonymize/dev/anonymize-bench.test.ts`, run with `--runInBand` (also dumps
   `/tmp/replay-bench-*.json`)
3. `cargo run --release --example anonymize_bench -p replay-anonymizer-node`

The sandbox exaggerates scan costs relative to SIMD parse; the stream/tree crossover point may sit
elsewhere on Apple Silicon / prod x86. Decide the ordering of the work below from real numbers.

## The ladder to 2.5x (ordered by expected value / risk)

### 1. Parse scrub-routed `data` spans in place (removes the scratch memcpy + double buffering)

`process_event` currently copies each data span into `sink.scratch` because simd-json mutates its
input and the surrounding bytes must stay pristine for the splice. But the parse only mutates
*within* the parsed span, and prefix/suffix live outside it — so parsing in place is safe if
`inner` is `&mut [u8]`.

Getting a mutable `inner`: the outer payload buffer is owned (`payload: &mut [u8]`) and the parsed
`data` string usually borrows into it (simd unescapes in place). Compute the borrowed str's offset
inside `payload` via pointer arithmetic while the outer tree is alive, drop the tree, re-slice
mutably. Handle the `Cow::Owned` case (rare) by keeping an owned buffer. Estimated ~2-4 ms on the
large fixture, plus cache-warmth benefits.

### 2. Merge the per-event scans into one pass

Today a scrub-routed incremental event's data span is walked up to 3 times before parsing:
`object_entries` on the event (locate_value = full skip over data), `scan_data` (depth-1 keys),
then the parse. Replace `locate_value` for the `data` value with a specialized walk that returns
the span end *and* the depth-1 `source`/`type`/`href`/`payload` spans in the same pass. ~1 full
pass over the bulk saved (~3-6 ms).

### 3. Tune `skip_string` for tiny strings

DOM JSON is millions of 5-20 byte strings; `memchr2` per-call setup dominates at that size and can
be slower than a byte loop. Hybrid: scan the first ~16 bytes bytewise, fall back to memchr for the
tail. Benchmark both `scan.rs::skip_string` and `json.rs::max_bracket_depth`. Consider a SWAR
(u64-word) scan instead. (~2-5 ms across the scan passes.)

### 4. Cheapen the outer envelope parse (~7 ms → ~2 ms)

`anonymize_kafka_payload` full-parses the outer payload just to get `distinct_id` + the `data`
string. Replace with a scan: locate the two top-level values (scan.rs already can), unescape
`data` ourselves into a reusable buffer (single pass, memchr-accelerated). Also removes the
JSON-depth pre-pass over the outer payload (the inner one stays). Keep the tree parse as the
fallback for escaped outer keys.

### 5. Fold dedupe detection into existing passes

`dedupe_in_place` walks every parsed tree checking every object for duplicate keys. Two options:
(a) detect duplicates at the byte level during the (now merged) scan pass and skip the tree walk
when the span provably has none; (b) fold the check into the scrub walk itself (it already visits
every object). Safety-critical — the duplicate-key leak test must stay green. (~2-4 ms.)

### 6. Adaptive stream/tree routing (if DOM-heavy still favors tree after 1-3)

Both paths produce identical output (differential-tested), so routing is free to choose per
message. Cheap heuristic from the envelope scan: if the largest event span exceeds ~50% of the
items span (a full-snapshot-dominated message), take the tree path; otherwise stream. Tune the
threshold from canary `phase`-labelled metrics.

### 7. FFI copy elimination (small, do last)

Two bulk memcpys remain at the boundary: JsBuffer→Vec on the way in (bytes can't be borrowed
across the threadpool hop) and Vec→JsBuffer for the lines on the way out. The output copy can go —
return an externally-backed buffer (`JsArrayBuffer::external`) wrapping the `Vec<u8>`. ~1-2 ms.

### 8. Scrub-walk floor items (the "16 ms" isn't all floor)

- `text.rs::tokenize_scrub` uses `char_indices`; an ASCII fast path (bytewise until a non-ASCII
  byte) would speed the dominant case.
- Allow-list lookups per word — check `AllowLists` set hashing (ahash / phf for the fixed set).
- `scrub_attrs` collects attr names into a `Vec<String>` per element (`keys().map(to_string)`) —
  borrow instead.

### 9. Rung ④, SIMD tokenizer — only if still short

The original last-mile option. Large, uncertain, PII-sensitive. Re-derive the ceiling from real
hardware after 1-8 before considering.

## In parallel (ops, multiplies with everything)

Scale replicas/vCPU on the ml-mirror deployment — a 2x pod bump times whatever the code path wins
is the fastest way to burn down the backlog while the flag rolls out.

## Rollout

1. Canary with `SESSION_RECORDING_ML_RUST_ANONYMIZER=true`; watch
   `recording_blob_ingestion_v2_ml_anonymize_duration_ms{impl=...}` (direct A/B vs TS) and
   `..._ml_anonymize_failed` (should be ~0; every failure is a dropped message).
2. Compare consumer lag burn-down, not just per-message latency — the event loop is now free
   during the scrub, so batch concurrency behaves differently.
3. Watch dlq/drop reason rates vs the TS baseline — classification parity is tested, but prod
   traffic is the real fixture.
