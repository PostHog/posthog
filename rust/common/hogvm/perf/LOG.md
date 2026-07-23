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

## 2026-07-23 — iteration 3: alloc-free constant-string pushes (`HogStr`)

- Machine: same Linux sandbox runner (x86_64, 4 cores, rustc 1.94.1).
- Baseline (HEAD = boxed-variants commit, median of 3): **251.4 us/op**
  (247.4 / 254.9 / 251.4).
- Fresh profile after boxing: allocator ~30% (malloc 16.3 across malloc/_int_malloc,
  free 8.1, consolidate 3.2, unlink 2.0), `step` 9.2%, memmove down 5.1 -> 3.7%,
  siphash+hash_one 5.5%, `get_token` 2.7%, indexmap insert 2.1 + get 1.1 +
  reserve_rehash 1.8, memcmp 1.8, `String::clone` 1.3, `push_stack` 1.3.
- Hypothesis: every `Operation::String` constant push does `Arc<str> -> to_string()`
  (malloc+copy), and in the ~90-write loop two of the three pushed constants (the
  chain names `properties`/`$set`/...) are popped and freed within a few ops — ~200
  malloc/free pairs per event doing no useful work. Replace `HogLiteral::String(String)`
  with `HogLiteral::String(HogStr)` where `HogStr = Owned(String) | Shared(Arc<str>)`:
  constant pushes become `Shared` (one refcount bump, zero alloc; `Token::Str` is
  already `Arc<str>`), while every owned-string path (globals, native returns, map
  keys) stays `Owned` with move semantics — explicitly avoiding both iteration-1
  failure modes (atomic churn on hot clone paths, added copies on owned paths).
  `HogStr` gets a content-based `PartialEq` (an `Owned("a")` must equal a
  `Shared("a")`) and `Deref<Target=str>`, so the compiler forces every match site to
  choose an accessor — no silent semantic misses. Gate at >= 2%; predicted 4-8%.
- Diff summary: new `HogStr { Owned(String), Shared(Arc<str>) }` payload for
  `HogLiteral::String` in `values.rs` (content-based `PartialEq`, `Deref<Target=str>`,
  `into_string()` that moves the `Owned` arm); `Operation::String` and the `Token::Str`
  arm of `Integer` push `Shared(token.clone())`; everything else stays `Owned` via the
  existing `From<String>` route. ~60 mechanical accessor fixes, compiler-enforced.
  `HogStr` exported for extension authors.
- Gates: 77 crate + 19 addon tests, fixture parity, cymbal/cohort-core compile,
  fmt/clippy/shear in both workspaces — all green.
- Measurement (interleaved A/B, 7 rounds, 100k iters each):
  base 249.6 / 249.3 / 246.6 / 248.6 / 256.5 / 244.7 / 247.6 (median 248.6) vs
  cand 260.1 / 242.0 / 238.8 / 240.8 / 240.6 / 234.4 / 236.8 (median 240.6);
  round 1 of the candidate was a cold-start outlier, rounds 2-7 ratios 0.94-0.97.
  -> **~3.2% improvement**.
- Verdict: **COMMITTED** (`perf(hogvm): alloc-free constant-string pushes (248.6 -> 240.6 us/op)`).
  Smaller than the 4-8% prediction: the chain-name malloc/free pairs are gone, but the
  hashing/memcmp on the map probes and the remaining owned-string traffic (globals
  conversion, map keys) still dominate. Cumulative same-machine ratio:
  240.6/274.2 = 0.877 vs iteration-2 baseline, i.e. ~12.3% below this machine's branch
  HEAD-at-session-start.
- Iteration score: committed improvement — consecutive-no-commit counter stays 0.
- Next-iteration candidates: (1) re-profile; if `json_to_hog`/`hog_to_json` (globals in,
  result out) are now the biggest coherent block, attack the per-event JSON round trip
  (e.g. lazy globals conversion — most of the ~30 event properties are never read by the
  template beyond `properties`/`$ip`). (2) CallGlobal `Symbol` probe allocations.
  (3) IndexMap rehash on the growing `$set`/`$set_once` maps (reserve on first insert).

## 2026-07-23 — iteration 4: ahash for object maps

- Machine note: the runner was re-scheduled between sessions — the same HEAD binary
  that measured 240.6 us/op last session measures ~157 here (~35% faster hardware).
  Absolute us/op values are NOT comparable across sessions on ephemeral runners; only
  same-session interleaved A/B ratios are.
- Baseline (HEAD = HogStr commit, median of 3): **157.0 us/op** (160.9 / 157.0 / 156.5).
- Fresh profile: allocator ~26%, `step` 9.8%, IndexMap+hash block ~12.4%
  (`insert_full` 3.7, `reserve_rehash` 2.2, SipHash write 2.6 + `hash_one` 2.5,
  `memcmp` 1.8, `get` 1.2), JSON boundary ~6.2% (`json_to_hog` 2.6, `hog_to_json` 1.3,
  `construct_free_standing` 1.2, `walk_emplacing` 1.1), `get_token` 2.4%, memmove 2.7%.
  Note GetGlobal conversion is already lazy per accessed subtree, and the geoip template
  returns the whole event, so the JSON round trip has little skippable work — the
  "lazy globals" candidate from iteration 3 is weaker than it looked.
- Hypothesis: swap the object maps' hasher from the default SipHash `RandomState` to
  `ahash::RandomState` (`IndexMap<String, HogValue, ahash::RandomState>`). SipHash is
  ~5% of self-time and sits under every property write/read; ahash is several times
  faster on short keys while still being a keyed, DoS-resistant hash (object keys come
  from user-defined Hog programs, so an unkeyed hasher like FxHash is off the table).
  Insertion order, equality, and serialization are hasher-independent, so semantics are
  pinned. New dependency rationale (constraint 4): `ahash` 0.8 is already in the rust
  workspace lockfile (used transitively elsewhere); this adds it as a direct dep of the
  hogvm crate. Gate at >= 2%; predicted 3-5%.
- Diff summary: new `pub type HogMap = IndexMap<String, HogValue, ahash::RandomState>`
  in `values.rs`; `HogLiteral::Object(Box<HogMap>)`; construction sites moved to
  `HogMap::default()` / `with_capacity_and_hasher`; `&IndexMap<..>` parameter types
  became `&HogMap`; kept the existing default-hasher `From<IndexMap>` impl (re-collects)
  for API compatibility and added `From<HogMap>`. `ahash` added via the workspace dep
  (already pinned at 0.8.11 in the root Cargo.toml and present in the lockfile).
- Gates: 77 crate + 19 addon tests, fixture parity, cymbal/cohort-core compile,
  fmt/clippy/shear both workspaces — all green.
- Measurement (interleaved A/B, 4 rounds, 100k iters each):
  base 158.9 / 157.6 / 155.7 / 157.8 (median 157.7) vs
  cand 147.2 / 141.9 / 147.4 / 150.8 (median 147.3) -> **~6.6% improvement**.
- Verdict: **COMMITTED** (`perf(hogvm): ahash-backed object maps (157.7 -> 147.3 us/op)`).
- Iteration score: committed improvement — consecutive-no-commit counter stays 0.
- Cumulative committed same-machine ratios: iter2 0.894 x iter3 0.968 x iter4 0.934
  = **~0.808 of branch HEAD-at-loop-start** (~19% cumulative reduction) — past the
  ~17% target-equivalent; stretch (~38% cumulative) still open.
- Next-iteration candidates: (1) re-profile — with SipHash gone, see whether the
  allocator block (still ~26%) has a dominant contributor worth attacking directly
  (json_to_hog String clones? heap Vec growth? `walk_emplacing` clone of geoip
  records?). (2) CallGlobal `Symbol` probe allocations. (3) `HogLiteral::size`
  accounting walk on SetProperty (backlog 7).

## 2026-07-23 — iteration 5: in-place object emplacement in `walk_emplacing`

- Machine: same runner as iteration 4 (verified same hardware class; HEAD binary
  measures within ~3% of last session).
- Baseline (HEAD = ahash commit + lockfile chore, median of 3): **152.1 us/op**
  (155.8 / 152.1 / 151.7).
- Profile: allocator ~27%, `step` 10.3%, indexmap insert_full 3.6 + rehash 2.0 + get
  1.1, memmove 2.8, `json_to_hog_impl` 2.5, `get_token` 2.5, memcmp 1.8,
  `construct_free_standing` 1.4, `walk_emplacing` 1.2 self. Malloc call-graph: the
  native-call path (geoipLookup) carries ~29% of allocation traffic — record
  construction (`construct_free_standing` ~4%) plus `walk_emplacing` ~6%, which
  *rebuilds every returned object map via `collect`* (fresh IndexMap: re-hash +
  re-insert every key). The array arm has an all-flat fast path (added long ago when
  this walk was the hottest function) — the object arm never got one.
- Hypothesis: emplace object children **in place** — iterate `values_mut()`, `mem::replace`
  each child out, walk it, write the result back. No new map, no re-hash, no re-insert,
  and the `Box<HogMap>` moves to the heap untouched. Applies to every native-fn object
  result (the geoip record has ~10 nested sub-objects per event). Gate >= 2%;
  predicted 3-5%.
- Diff summary: single-arm change in `context.rs::walk_emplacing` — `Object` children
  are now walked via `values_mut()` + `mem::replace`, keeping the original `Box<HogMap>`
  (no fresh map, no re-hash/re-insert); the array arm is untouched (its Vec collect
  already reuses the allocation via in-place iteration specialization).
- Gates: 77 crate + 19 addon tests, fixture parity, cymbal/cohort-core compile,
  fmt/clippy/shear both workspaces — all green.
- Measurement (interleaved A/B, 4 rounds, 100k iters each):
  base 152.8 / 150.9 / 152.7 / 150.0 (median 151.8) vs
  cand 146.1 / 144.6 / 146.8 / 145.0 (median 145.6) -> **~4.1% improvement**.
- Verdict: **COMMITTED** (`perf(hogvm): emplace object children in place (151.8 -> 145.6 us/op)`).
- Iteration score: committed improvement — consecutive-no-commit counter stays 0.
- Cumulative committed same-machine ratios: 0.894 x 0.968 x 0.934 x 0.959 = **~0.775**
  (~22.5% cumulative reduction vs loop start; stretch ~38% still open).
- Next-iteration candidates: (1) `json_to_hog_impl` — reserve map/vec capacity from the
  JSON node size and consider taking ownership of globals subtrees to move String leaves
  instead of cloning. (2) CallGlobal `Symbol` probe allocations. (3) `HogLiteral::size`
  walk on SetProperty (backlog 7).

## 2026-07-23 — iteration 6: alloc-free CallGlobal symbol probe

- Machine: same runner as iteration 5.
- Baseline measurement deferred to the interleaved A/B (the HEAD binary from
  iteration 5 is the base side).
- Static op mix of the template (442 ops straight-line): String 111, GetLocal 101,
  GetProperty 51, Pop 33, **CallGlobal 25** (empty, print x4, substring, geoipLookup,
  keys x3, values x3, length x3, concat x9), SetProperty 22 — loops multiply the
  write/call blocks at runtime.
- Hypothesis (backlog item 5, hardened): every executed CallGlobal builds
  `Symbol::new("stl", name)` — two String allocations — just to probe the symbol
  table, and for native calls (the overwhelming majority here) the probe always
  misses. Instead of flipping probe order (which would silently change semantics if a
  name ever appeared in both the native-fn map and the symbol table — possible via
  runtime `with_ext_fn` registrations), add an `Arc`-shared `HashSet<String>` of the
  "stl"-module symbol names, probed by `&str` with zero allocation; construct the
  `Symbol` only on a hit (an actual cross-module call — none in the geoip hot path).
  Exact same resolution semantics. Gate >= 2%; predicted 1-3% (riskiest gate margin
  so far — CallGlobal is ~25-80 executions/event vs the ~200 pushes iteration 3
  removed for 3.2%).
- Diff summary (implemented, then reverted): `Arc<HashSet<String>>` of stl-module names
  in `ExecutionContext` (maintained by all constructors and module mutators),
  `has_stl_symbol(&str)` probe, and CallGlobal building the `Symbol` only on a hit.
  All gates were green (77+19 tests, parity, deps, lints).
- Measurement (interleaved A/B, 10 rounds, 100k iters each): per-round ratios
  0.907 / 0.964 / 0.995 / 1.044 / 1.027 / 0.985 / 1.016 / 0.935 / 1.038 / 0.962 —
  median **0.990 (~1.0% improvement)**, spread ±5%. The runner became heavily
  contended mid-measurement (absolute times rose from ~145 to ~225 us/op), but even
  the quieter early rounds put the effect near ~1-2%, under the gate.
- Verdict: **REVERTED** (below the 2% gate). The probe allocations are real but small:
  ~25-80 CallGlobals/event x 2 tiny Strings is an order of magnitude less allocator
  traffic than the wins that cleared the gate. Worth folding into a future batched
  "small allocs" iteration if one forms, not worth a solo slot. Negative result
  recorded so it is not re-tried alone.
- Iteration score: 1 consecutive iteration with no committed improvement (stop at 3).
- Next-iteration candidates: (1) `json_to_hog_impl` capacity reservation for maps/vecs
  (targets `reserve_rehash` ~2% + some malloc) — similar risk profile to this
  iteration, so consider pairing its measurement with a quiet-machine check first.
  (2) The remaining big block is `step` dispatch + `get_token` (~12%) — a
  frame-cached token-slice pointer (backlog item 6) skips the per-fetch
  `Option<Symbol>` match + `HashMap` lookup for root-chunk execution; geoip runs
  ~100% in the root chunk. (3) `hog_to_json` BTreeMap output path.

## 2026-07-23 — iteration 7: frame-cached token slice for the fetch path

- Machine: same runner, moderate background load (HEAD measures ~177 us/op vs ~145
  quiet / ~225 contended earlier today — absolute numbers remain session-relative;
  the interleaved A/B carries the decision).
- Baseline (HEAD binary, median of 3): **177.4 us/op** (178.5 / 176.1 / 177.4).
- Hypothesis (backlog item 6): every token fetch calls
  `context.get_token(ip, &current_symbol)`, which matches on `Option<Symbol>` and, for
  module chunks, hashes two Strings for a `HashMap<Symbol, _>` lookup — and even the
  root-chunk path goes through the match + program indirection. Cache the current
  chunk's `&[Token]` slice in the VM (`current_tokens`), updated at the five places
  `current_symbol` changes (init, CallLocal, Return, Throw, cross-module call), so
  `next_token` becomes a bounds-checked slice index. `step` + `get_token` +
  `next_usize` is ~13% of self-time and every single opcode pays the fetch. Gate
  >= 2%; predicted 2-4%.
- Diff summary: `Program::body_tokens()` / `ExportedFunction::body_tokens()` slice
  accessors, `ExecutionContext::chunk_tokens(&Option<Symbol>)`, and a `current_tokens:
  &'a [Token]` field on `HogVM` kept in lockstep with `current_symbol` via a `set_chunk`
  helper (all six assignment sites routed through it, including the resume path).
  `next_token` is now `current_tokens.get(ip)`.
- Gates: 77 crate + 19 addon tests, fixture parity, cymbal/cohort-core compile,
  fmt/clippy/shear both workspaces — all green.
- Measurement (interleaved A/B, 5 rounds, 100k iters each): per-round ratios
  0.979 / 0.949 / 0.938 / 0.959 / 0.959 — median **0.959 (~4.1% improvement)**;
  base median 176.1, cand median 167.6.
- Verdict: **COMMITTED** (`perf(hogvm): cache chunk token slice for fetches (176.1 -> 167.6 us/op)`).
- Iteration score: committed improvement — consecutive-no-commit counter resets to 0.
- Cumulative committed same-machine ratios: 0.894 x 0.968 x 0.934 x 0.959 x 0.959 =
  **~0.743 (~25.7% cumulative reduction vs loop start)**; stretch (~38%) still open.
- Next-iteration candidates: (1) `json_to_hog_impl` capacity reservation (+ possibly
  `hog_to_json` reservations) — retry now that quieter measurement patterns (per-round
  ratios) are established. (2) `HogLiteral::size` walk on SetProperty. (3) profile
  again — allocator block should now dominate even more; consider whether the
  remaining malloc traffic (globals conversion + result serialization) needs a
  structural change (reusing buffers across events in run_batch_program).

## 2026-07-23 — iteration 8: jemalloc for the addon binary

- Machine: same runner, moderate load (HEAD ~206.5 us/op median of 3:
  203.3 / 210.9 / 206.5).
- Profile: allocator now ~32.6% of self-time (malloc 17.6, free 9.1, consolidate 3.9,
  unlink 2.0) — the dominant block, spread across many small sources (globals JSON
  conversion, property writes, geoip record, result serialization); no single caller
  is worth a solo iteration anymore. `step` 9.7, memmove 4.3, indexmap 3.8, memcmp
  2.0, json_to_hog 2.0.
- Hypothesis: swap the allocator under the addon. glibc malloc's
  small-alloc/free churn (with visible `malloc_consolidate`/`unlink_chunk` binning
  overhead) is the bottleneck; the rust workspace's standard allocator is jemalloc via
  the `common-alloc` crate (`common_alloc::used!()`), already used by PostHog's Rust
  services — the napi addon just never adopted it. Add it to `hogvm-node` (lib.rs), so
  the cdylib and its bins (including `profile_geoip`) allocate via jemalloc.
  Dependency rationale (constraint 4): not a new dependency in spirit — it is the
  workspace-standard allocator crate, path-depended from the addon workspace.
  Gate >= 2%; predicted 5-15% (allocator time should compress substantially).
- Diff summary: `common-alloc = { path = "../../alloc" }` in the addon manifest and
  `common_alloc::used!()` in `node/src/lib.rs` — jemalloc as the Rust global allocator
  for the cdylib and its bins. No hogvm-crate changes (crate gates unaffected,
  re-verified green anyway).
- Gates: 77 crate + 19 addon tests, fixture parity, cymbal/cohort-core compile,
  fmt/clippy/shear — all green.
- Measurement (interleaved A/B, 5 rounds, 100k iters each): per-round ratios
  0.676 / 0.679 / 0.685 / 0.711 / 0.659 — median **0.679 (~32% improvement)**;
  base median 206.0, cand median 141.1.
- Verdict: **COMMITTED** (`perf(hogvm): jemalloc for the node addon (206.0 -> 141.1 us/op)`).
  Production note: this changes the Rust-side allocator inside the plugin-server node
  process when the addon loads — jemalloc is already the standard across PostHog Rust
  services, but memory-footprint characteristics of the addon will shift; watch RSS on
  rollout.
- Iteration score: committed improvement — counter stays 0.
- Cumulative committed same-machine ratios:
  0.894 x 0.968 x 0.934 x 0.959 x 0.959 x 0.679 = **~0.505** (~49.5% cumulative
  reduction vs loop start) — **the ~38% stretch-equivalent is exceeded; the loop's
  stop condition fires this iteration.**

## Closing summary (2026-07-23) — loop complete: stretch goal exceeded

- Stop condition: cumulative committed same-machine ratio reached **~0.505** (~49.5%
  reduction), past the ~38% stretch-equivalent (original-machine 60 us/op). If the
  ratios transfer, the original M-series baseline of 96.6 us/op maps to ~49 us/op.
- Committed iterations (ratios multiply): boxing large variants (0.894), HogStr
  shared-constant pushes (0.968), ahash object maps (0.934), in-place object
  emplacement (0.959), per-chunk token-slice cache (0.959), jemalloc in the addon
  (0.679).
- Rejected hypotheses (kept for posterity, do not re-try): pervasive `Arc<str>`
  strings (~9% regression); eager `ok_or` with unit VmError variants (~3% regression,
  lint suppressed crate-wide); solo CallGlobal probe de-allocation (~1%, under gate).
- Environment learnings for future loops on ephemeral runners are recorded in the
  session notes above (rolling mmdb snapshot vs pinned fixture, brotli/perf/protoc
  provisioning, cross-session hardware drift — trust only same-session interleaved
  A/B ratios).
- What a further push would need (target already exceeded; for reference): the final
  profile puts `step` dispatch itself on top (13.4%) with allocation down to ~9% —
  the remaining levers are structural: superinstruction/threaded dispatch,
  copy-on-write globals to shrink the per-event JSON round trip, and interned map
  keys paired with an `Rc`-based string model (the conditions under which the
  iteration-1 approach could be revisited).
- Production follow-ups for the human reviewing this branch: wire
  `registerProgram`/`executeRegisteredSync` into
  `nodejs/src/cdp/hog-transformations/rust-vm-executor.ts` (still TODO from the
  pre-loop work), and watch addon RSS after the jemalloc switch.
