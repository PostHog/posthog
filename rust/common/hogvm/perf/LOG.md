# Optimization loop log

One entry per session, newest last. A session that commits an accepted change records the
same-machine before -> after ratio; a blocked or rejected session records what was learned.
The loop is over only when this file ends with a closing summary (see PROMPT.md step 8) —
this file does not yet contain one.

## 2026-07-23 — session blocked: no mmdb reachable (no iteration performed)

- Machine: ephemeral Linux sandbox runner, x86_64, 4 cores, rustc 1.94.1.
- Outcome: **BLOCKED — environment, not a converged loop.** No baseline measured, no code
  changed. This is a session note, not a closing summary.
- Cause: this runner's egress policy denies `mmdbcdn.posthog.net` (HTTP 403 on proxy
  CONNECT, confirmed as a policy denial by the proxy's own status endpoint, which
  documents such denials as non-retryable). `./bin/download-mmdb` retried for its full
  budget and never received a byte, so `share/GeoLite2-City.mmdb` cannot be provisioned
  and `profile_geoip` cannot run. Per PROMPT.md environment setup: nothing can be
  measured without the database, so the session stops here.
- Dead end checked, so later sessions don't re-try it: the repo ships MaxMind's small
  test database (`nodejs/tests/assets/GeoLite2-City-Test.mmdb.br`, brotli — decompress
  with node `zlib.brotliDecompressSync` if the `brotli` CLI is absent). The harness runs
  against it, but its data diverges from the pinned fixture — the full GeoLite2 resolves
  fixture IP `89.160.20.129` to Karlstad, the test DB to Linköping, and the other four
  fixture IPs are real-world addresses outside the test DB's ranges — so the
  expected-output gate hard-fails. Do NOT "fix" this with `--write-expected`: that would
  re-pin the fixture to the test DB and break the gate for every properly provisioned
  machine.
- Harness usage note: BENCHMARKING.md says empty-string positionals fall back to
  defaults, but `profile_geoip` treats `""` as a literal path (`unwrap_or_else` only
  fires when the arg is absent). Pass real paths or no positionals at all.
- Prep that did happen (no measurements, no source changes): confirmed `cymbal` and
  `cohort-core` import only `ExecutionContext`/`Program`/`StepOutcome`/`VmError`/
  `sync_execute` and never touch `HogLiteral`/`HogValue` directly, so backlog item 1
  (`HogLiteral::String(String)` -> `Arc<str>`) cannot break their compile (constraint 2).
  Also noted `Token::Str` is already `Arc<str>`, so with item 1 in place the
  `Operation::String` push becomes a pure refcount bump.
- Next session: run on a machine that can reach `mmdbcdn.posthog.net` (or has
  `share/GeoLite2-City.mmdb` pre-provisioned), measure the same-machine HEAD baseline,
  and start with backlog item 1 (`Arc<str>`-backed string literals), staged as a
  mechanical type change with behavior pinned by the existing gates.

## 2026-07-23 — iteration 1: `Arc<str>`-backed string literals

- Machine: ephemeral Linux sandbox runner, x86_64, 4 cores, rustc 1.94.1
  (same runner class as the blocked session above; egress now allows mmdbcdn).
- Environment note for future ephemeral runners: `mmdbcdn.posthog.net` serves a rolling
  GeoLite2 snapshot, so a fresh download can legitimately drift from the pinned expected
  fixture with zero code changes. That happened this session on unmodified HEAD: fixture
  event 0 (89.160.20.129, Karlstad) moved accuracy radius 50 -> 20 and postal code
  "652 30" -> "650 02"; every other field/event was byte-identical. Re-pinned via
  `--write-expected` in its own commit, then re-verified the gate passes on HEAD.
  If the gate fails on *unmodified* HEAD, audit the diff and re-pin only if it is pure
  geo-data drift like this.
- Also: the `brotli` CLI is absent here; decompress the CDN payload with node
  `zlib.brotliDecompressSync`. `perf` comes from `apt-get install linux-tools-generic`
  (binary at `/usr/lib/linux-tools/<ver>/perf`, after `apt-get update`).
- Same-machine baseline (unmodified HEAD, canonical harness, median of 3):
  **273.0 us/op** (270.4 / 273.0 / 275.0).
- Profile (perf, flat self-time): allocator ~27% (`_int_malloc` 9.6, `malloc` 5.3,
  `_int_free` 4.1, `malloc_consolidate` 3.1, `cfree` 3.1, `unlink_chunk` 1.9), `step`
  self 10.6%, `memmove` 5.1%, siphash+`hash_one` 5.6%, `get_token` 2.7%, indexmap
  `insert_full` 2.3% + `get` 1.3%, `hoist` 1.8%, `memcmp` 1.6%, `String::clone` 1.1%,
  `HogLiteral` drop glue 1.4%. Matches the macOS profile in FINDINGS.md — allocation
  churn dominates.
- Hypothesis (backlog item 1): change `HogLiteral::String(String)` to
  `HogLiteral::String(Arc<str>)`. `Token::Str` is already `Arc<str>`, so every
  `Operation::String` constant push becomes a refcount bump instead of a fresh String
  allocation, and every clone of a string value (hoist, GetProperty/get_nested
  `.cloned()`, stack copies, drop) stops allocating/freeing. Predicted saving: a
  meaningful slice of the ~27% allocator time; gate at >= 2%, expecting ~8%+.
- Diff summary: mechanical variant swap across `values.rs`/`vm.rs`/`stl.rs`/`print.rs`/
  `state.rs`/`context.rs`/`node/src/ext_fns.rs` (~50 sites), added
  `From<&str>`/`From<Arc<str>>` and `FromHogLiteral for Arc<str>`; object keys stayed
  `IndexMap<String, _>`. All gates green (77 crate + 19 addon tests, fixture parity,
  cymbal/cohort-core compile, fmt/clippy/shear).
- Measurement (interleaved A/B, same binary paths, 100k iters each):
  baseline 277.6 / 274.0 / 273.2 (median 274.0) vs candidate 299.1 / 311.5 / 293.3
  (median 299.1) -> **~9% regression**.
- Verdict: **REVERTED.** On x86-64/glibc the swap loses: (a) every string clone/drop
  became an atomic RMW pair, and the VM clones strings constantly — glibc's small-alloc
  fast path is cheaper than the atomic traffic; (b) the swap *added* copies where moves
  used to happen: `From<String>` now does `Arc::from(String)` (fresh buffer + copy) on
  every native-fn string return and every `.into()` construction, and the SetProperty
  key does `Arc -> String` copy where the popped `String` used to move into the map.
  A plain refcount swap is refuted for this workload/platform. If revisited, it must
  (1) use a non-atomic count (`Rc<str>` is viable — `HogValue` is already `!Send` via
  the `Rc<RefCell<Upvalue>>` cells) and (2) eliminate the added copies (intern object
  keys as the same shared-str type so SetProperty moves the refcount instead of
  copying, and keep native-fn returns as owned `String` until the boundary).
- Bonus knowledge (measured, then suppressed): clippy 1.94's
  `unnecessary_lazy_evaluations` wants `ok_or_else(|| VmError::X)` rewritten to
  `ok_or(VmError::X)`; applying it to the crate (15 sites, including `get_token`'s
  `EndOfProgram(ip)`) is a consistent, interleaved-A/B-confirmed **~3% regression** —
  eagerly constructing the large `VmError` enum per successful token fetch is exactly
  the FINDINGS.md `ok_or` trap, unit-ish variants included. The lint is now allowed
  crate-wide in `lib.rs` with a comment; do not "fix" it.
- Toolchain drift handled in a separate chore commit so gates stay green on current
  stable (1.94): crate-wide clippy allow above, `cargo fmt` reformat of a few
  chain-wrap spots (this rustfmt wraps chains the authoring machine's rustfmt kept
  inline; no toolchain pin exists), `protoc` needed for the cymbal/cohort-core check
  (`apt-get install protobuf-compiler`), and `cargo-shear` at 1.1.12 (latest needs
  rustc 1.95).
- Iteration score: 1 consecutive iteration with no committed improvement (stop
  condition fires at 3).
- Next-iteration candidates, in order: (1) backlog item 3 — box the large
  `HogLiteral`/`HogValue` variants (Object/Array/Closure/Callable) to cut the ~5%
  memmove cost of moving big enums through the stack; small, self-contained, and
  orthogonal to the string question. (2) backlog item 5 — CallGlobal symbol-probe
  allocation (two `String`s per global call just to probe `has_symbol`; restructure the
  symbol table for a `(&str, &str)` lookup, semantics-preserving). (3) A copy-free
  SetProperty key path (pop the key as `String` and move it into the IndexMap is what
  we already do — the win would come from interning keys, which only pays off together
  with a shared-str value type per the verdict above).

## 2026-07-23 — iteration 2: shrink `HogLiteral`/`HogValue` by boxing large variants

- Machine: same ephemeral Linux sandbox runner as iteration 1 (x86_64, 4 cores,
  rustc 1.94.1). HEAD at start: the iteration-1 chore commits (no VM code change since
  the iteration-1 baseline).
- Measured sizes on HEAD: `HogLiteral`/`HogValue` = **120 bytes**, `Closure` = 120,
  `Callable` = 96 (its `LocalCallable` carries a name String + `Option<Symbol>` of two
  more Strings), `Num` = 16; `Object`'s inline `IndexMap` header is ~72.
- Hypothesis (backlog item 3): box the `Callable`, `Closure`, and `Object` variant
  payloads so `HogValue` drops from 120 to ~32 bytes. Every stack push/pop/clone,
  heap-Vec emplacement, and enum move then copies a quarter of the bytes — targeting
  the ~5% `memmove` self-time plus part of `step`'s 10.6% and the allocator's Vec-growth
  traffic. Cost added: one small allocation per object/closure/callable *construction*
  (objects are heap-emplaced immediately anyway) and one pointer chase per access.
  Closures/callables are cold in the geoip template; objects are hot but their
  contents already live behind the heap indirection. Gate at >= 2%; predicted ~3-5%.
- Baseline (this iteration, median of 3): see measurement below.
- Baseline measured (median of 3): **274.6 us/op** (282.7 / 274.1 / 274.6) — consistent
  with iteration 1's baseline, no drift.
- Diff summary: `Object(Box<IndexMap<..>>)`, `Callable(Box<Callable>)`,
  `Closure(Box<Closure>)` in `values.rs`; mechanical `Box::new(...)` at construction
  sites and `.iter()` at a few `for .. in &Box<..>` loops across `vm.rs`/`stl.rs`/
  `state.rs`/`print.rs`/`context.rs`. No public-API removals (variant payload types
  changed; cymbal/cohort-core compile untouched). `HogLiteral`/`HogValue`: 120 -> 32
  bytes.
- Gates: 77 crate + 19 addon tests green, fixture parity green, cymbal/cohort-core
  compile, fmt/clippy/shear clean in both workspaces.
- Measurement (interleaved A/B, 100k iters each):
  baseline 274.2 / 272.9 / 274.4 (median 274.2) vs candidate 247.1 / 245.2 / 242.6
  (median 245.2) -> **10.6% improvement** (ratio ~0.89 in every round).
- Verdict: **COMMITTED** (`perf(hogvm): box large HogLiteral variants (274.2 -> 245.2 us/op)`).
  Same-machine cumulative ratio so far: 245.2/274.2 = 0.894 (~11% below this machine's
  branch baseline; target is ~0.83 of branch baseline, stretch ~0.62).
- Iteration score: committed improvement — consecutive-no-commit counter resets to 0.
- Next-iteration candidates: (1) backlog item 5 — CallGlobal's per-call `Symbol` probe
  allocates two Strings; restructure the symbol table for a `(&str, &str)` lookup.
  (2) re-profile after this change to see whether memmove/allocator shares shifted and
  whether hoist/GetLocal or the IndexMap key path is now the top lever. (3) the
  SetProperty size-accounting walk (`HogLiteral::size`, backlog item 7).
