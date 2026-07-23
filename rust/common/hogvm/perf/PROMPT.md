# Optimization loop: Rust HogVM geoip execution

You are running an iterative performance-optimization loop on the Rust HogVM
(`rust/common/hogvm`, plus its napi addon in `rust/common/hogvm/node`). Work only within
these two crates unless an iteration's plan explicitly says otherwise.

## Goal

Reduce the per-event execution time of the geoip Hog transformation as measured by the
canonical harness, without changing observable semantics.

- Metric: `us/op` from `cargo run --release --features noop --bin profile_geoip`
  (run from `rust/common/hogvm/node`; median of 3 runs).
- Baseline at branch creation: 96.6 us/op.
- Target: below 60 us/op. Stretch: below 40 us/op.

## Read first

- `rust/common/hogvm/perf/FINDINGS.md` — everything measured so far, including refuted
  approaches. Do not re-try refuted approaches (template rewrites; chasing the mmdb lookup;
  further serde/token-decode work).
- `rust/common/hogvm/perf/BENCHMARKING.md` — how to measure, profile, and gate.

## Hard constraints

1. Semantics are pinned by the TS reference VM. Every iteration must keep green:
   - `cargo test -p hogvm` (from `rust/`)
   - `cargo test --features noop` (from `rust/common/hogvm/node`)
   - the built-in expected-output check in `profile_geoip` (it hard-fails on drift)
2. `cargo check -p cymbal -p cohort-core` (from `rust/`) must keep compiling — the crate's
   public API may grow but must not break.
3. `cargo fmt`, `cargo clippy --all-targets -- -D warnings`, `cargo shear` clean in both
   workspaces (`--features noop` for addon clippy).
4. No new dependencies without recording the rationale in the iteration log.
5. Do not edit `perf/fixtures/geoip-expected.json` except via `--write-expected`, and only
   with a written justification of why the output legitimately changed. Treat this as a last
   resort; an unexplained output change is a bug in your change.
6. Do not weaken, skip, or delete tests. Do not change the fixtures to make the workload
   easier.

## Loop protocol (one hypothesis per iteration)

1. Profile: use the sampling recipe in BENCHMARKING.md; identify the current top cost.
2. Hypothesize: one specific change and its predicted saving. Log it before implementing.
3. Implement the single change, as small as possible.
4. Gate: run all correctness checks above.
5. Measure: canonical harness, median of 3. Compare against the previous iteration's median.
6. Decide:
   - Improvement ≥ 2%: commit (`perf(hogvm): <what> (<before> -> <after> us/op)`).
   - Below 2% or a regression: revert the change, keep the knowledge.
7. Log the iteration in `rust/common/hogvm/perf/LOG.md` (create on first iteration): date,
   hypothesis, diff summary, measurement, verdict. Negative results are valuable — record
   them so later iterations don't repeat them.
8. Stop conditions: target reached, or 3 consecutive iterations with no committed
   improvement — then write a closing summary in LOG.md proposing what a bigger refactor
   would need.

## Ranked starting backlog (from the profile in FINDINGS.md)

1. **`Arc<str>`-backed string literals** — `HogLiteral::String` currently owns a `String`;
   every constant push, hoist, and clone allocates. This is the biggest identified lever but
   ripples through `stl.rs`/`print.rs`/`state.rs`. Consider staging it (e.g. introduce the
   type change, fix call sites mechanically, keep behavior identical).
2. **Interned object keys** — property writes do `IndexMap<String, HogValue>` inserts with
   owned keys plus memcmp-heavy lookups. Pairs naturally with (1).
3. **Shrink `HogValue`/`HogLiteral`** — box large variants (Object/Array/Closure/Callable) to
   cut the ~5% memmove cost of moving big enums through the stack.
4. **Hoist elision** — `GetLocal` hoists every local to the heap; scalars/immutable values may
   not need it. Verify aliasing semantics against the reference VM (vm.rs has a comment
   discussing this) before changing.
5. **CallGlobal fast path** — `Symbol::new("stl", name)` allocates two Strings per global call
   just to probe the symbol table; probing `has_native` first (if the name sets are disjoint —
   verify) skips it for the common native case.
6. **`get_token` fast path** — root-chunk executions could skip the `Option<Symbol>` branch
   via a cached slice pointer.
7. **SetProperty size accounting** — `HogLiteral::size` walks values on every write; consider
   incremental accounting.

Items 1–3 are where the remaining ~20% allocator + ~5% memmove time lives; 4–7 are smaller
but low-risk.

## Reporting

At the end of the loop, update FINDINGS.md with the new numbers and profile, and summarize
total improvement, committed iterations, and rejected hypotheses in LOG.md.
