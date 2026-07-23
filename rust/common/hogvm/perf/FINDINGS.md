# Rust HogVM geoip performance — findings to date (2026-07-23)

Context: the geoip transformation runs as a Hog template on the Rust HogVM
(`@posthog/hogvm-node` napi addon, primary executor behind
`CDP_HOG_RUST_VM_EXECUTION_ENABLED`). The legacy TS geoip plugin runs the same logic as native
compiled JS. The legacy plugin is ~26µs/event; the rust path started at ~189µs/event. This
document records everything measured so far so an optimization loop does not re-derive or
re-try dead ends.

## Measured numbers (small ~2KB event, 30 properties, M-series mac)

| Path | µs/event |
| --- | --- |
| legacy TS plugin (`posthog-plugin-geoip` processEvent) | 26 |
| raw `@maxmind/geoip2-node` `reader.city` alone | 24 |
| rust hogvm via `executeSync` (bytecode marshalled per call) | ~190–210 |
| rust hogvm via registered program (`executeRegisteredSync`) | ~154 |
| node hogvm, same template | ~355–410 |
| pure-rust harness (`profile_geoip`, no napi), LTO release | 96.6 internal |
| rust `geoipLookup` + record construction alone | ~14 |
| template early-return path (`$geoip_disable`) | ~18 internal |
| `return event` (globals→hog→json round trip only) | ~6 internal |

Composition of the ~154µs registered-program path: ~113µs VM execution + ~30µs globals/result
JSON round trip over napi + ~10µs napi call/result overhead. The mmdb lookup is ~0.6% of VM
time — the interpreter machinery is essentially all of it.

## What was tried and the outcome

### Confirmed win: program registry (shipped on this branch)

`executeSync` used to marshal the 758-token bytecode JS→Rust and copy it per event (~38µs).
`registerProgram`/`executeRegisteredSync` in the addon validate + pre-decode once and execute
by handle. Production wiring into `nodejs/src/cdp/hog-transformations/rust-vm-executor.ts`
(cache handle per hogFunction id + bytecode version) is still TODO.

### Confirmed win, smaller than hoped: pre-decoded token stream (shipped on this branch)

`Token` enum in `src/program.rs`, decoded once per `Program`/`ExportedFunction`,
index-aligned with the raw token array (ip/jump semantics unchanged). `vm.rs` typed
`next_op/next_usize/next_i32/next_bool/next_f64/next_str` accessors replaced the serde-based
`next<T>()`. Also: `get_fn_reference` returns `Option` (was allocating a discarded error on
GetGlobal's normal fallthrough), and all hot `.ok_or(VmError::…)` became `.ok_or_else`
(`ok_or` constructed + dropped a VmError on every successful token fetch). Net: −8%
(118.8 → 109.0µs/op on the debug-symbols build; 96.6µs on the default release build).

### REFUTED: slimming the geoip template

A parity-checked template variant with no runtime f-string keys and no dead
`if (value != null)` branch ran at identical speed (and slower on the node VM). The cost is
the ~90 property writes themselves (~0.9µs each), not key construction. Do not pursue
template-level rewrites.

### REFUTED as major costs

- serde per-token decode: removed, was only ~6µs.
- VmError drop glue on token fetches: removed, within noise.
- The geoip mmdb lookup: ~0.6% of VM time; rust's lookup already beats node's (14 vs 24µs).
- `print()` statements: ~3µs.

## Current profile (macOS `sample`, top of stack, after the shipped changes)

- `HogVM::step` self ~8–10% — dispatch + inlined op bodies
- allocator (malloc/free/realloc/memset) ~20%
- `memmove` ~5% — moving large `HogValue` enums through the stack
- `ExecutionContext::get_token` ~2.5%
- `indexmap insert_full` ~2.4% + `hash_one` ~1.1% + `reserve_rehash` ~1.2%
- `hoist` ~1.3% (with String/HogLiteral clone children)
- `mach_absolute_time` ~1.6% — the per-event `Instant::now` pair in `node/src/exec.rs`
- `memcmp` ~1.3% — IndexMap String-key comparisons
- `HogLiteral::size` ~1.2% — SetProperty heap accounting

## Why each property write costs ~0.9µs (the dominant loop)

`returnEvent.properties.$set[key] := value` executes: String-literal pushes for chain names
(each allocates a fresh `String` in `Operation::String` — `HogLiteral::String` owns a
`String`), `GetLocal` + `hoist` (heap emplacement), two `GetProperty`/`get_nested` steps (heap
deref + IndexMap `get_index_of` + memcmp per key), then `SetProperty` (`insert_full` with an
owned String key, hashing, and size accounting). The template does ~90 of these per event.

## The identified big lever: value-model rework

To roughly halve VM time, the value representation needs to stop allocating per step:

1. `Arc<str>`-backed string literals (`HogLiteral::String(Arc<str>)` or similar) so constant
   pushes, hoists, and clones are refcount bumps. Ripples through `stl.rs` (~100KB of native
   fns), `print.rs`, `state.rs`, `values.rs`.
2. Interned object keys — `IndexMap<Arc<str>, HogValue>` (or a key-id scheme) so property
   writes stop allocating and comparing owned Strings.
3. Shrink `HogValue`/`HogLiteral` (box the large variants: Object/Array/Closure/Callable) so
   stack pushes/pops stop memmoving huge enums.
4. Hoist elision for immutable scalars in `GetLocal` (verify aliasing semantics against the
   reference VM first).

## Guardrails learned the hard way

- `ok_or(...)` evaluates its argument eagerly — never put a VmError constructor in it on a hot
  path.
- The napi-side `durationUs` (prod metric `hogvm_rust_execution_duration_ms`) only measures
  `sync_execute` — boundary costs are invisible in it.
- `cymbal` and `cohort-core` depend on this crate; keep the public API additive.
- The TS reference VM defines the semantics; the crate's tests (77) + node addon tests (19) +
  the pinned expected-output fixture in `perf/fixtures/geoip-expected.json` are the parity
  gate.
