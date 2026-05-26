# Cymbal testing and coverage

This document is the Cymbal-local guide for choosing tests and collecting coverage.
Run commands from `rust/cymbal/` unless a command says otherwise.
Cymbal Rust packages are workspace members of the parent `rust/Cargo.toml`, so local commands pass `--manifest-path ../Cargo.toml`.

## Fast validation commands

Use the narrowest command that exercises the code you changed first, then widen before committing.

```sh
cargo metadata --manifest-path ../Cargo.toml --format-version 1 --no-deps
cargo fmt --check --manifest-path ../Cargo.toml --all
```

For broad Cymbal Rust validation, use the package set shared by the local coverage helper:

```sh
cargo test --manifest-path ../Cargo.toml \
  -p cymbal-api \
  -p cymbal-core \
  -p cymbal-domain \
  -p cymbal-fingerprinting \
  -p cymbal-pipeline \
  -p cymbal-repositories \
  -p cymbal-runtime \
  -p cymbal-rules \
  -p cymbal-alerting \
  -p cymbal-grouping \
  -p cymbal-linking \
  -p cymbal-rate-limiting \
  -p cymbal-resolution \
  -p cymbal-symbol-store \
  -p cymbal-symbolication \
  -p cymbal-server \
  --no-fail-fast
```

## Choosing the right test shape

### Unit tests

Use unit tests for deterministic transformation logic, validation, codec behavior, and stage-local branches that do not need an external service.
These should be the default for framework primitives in `cymbal-core`, domain DTOs, serializers/codecs, routing decisions, rate-limit mode application, and pure stage helpers.

Prefer small table-driven cases when one behavior has several variants.
Keep the test input close to the assertion and avoid large static fixtures unless the code path specifically parses or resolves those artifact formats.

### `#[sqlx::test]`

Use `#[sqlx::test]` for repository behavior that must prove real Postgres semantics: inserts, constraints, tenant scoping, race behavior, status transitions, truncation, and SQLx query metadata compatibility.
Keep these tests in repository-facing crates and make the transaction or test database setup explicit through the SQLx test harness.

Do not use SQLx tests for pure payload conversion or stage orchestration.
If local Postgres/test migrations are unavailable, record the exact blocker and run the pure subset, but do not treat that as equivalent to repository coverage.

SQLx tests in `cymbal-repositories` require Postgres at `postgres://posthog:posthog@localhost:5432/posthog` (the standard dev stack).
No new migrations are needed; `#[sqlx::test]` uses per-test ephemeral schemas.

### gRPC integration tests

Use gRPC integration tests when the public or internal wire boundary matters: tonic status mapping, streaming result order, metadata/load propagation, admission rejection, remote-stage fallback, and local-vs-remote parity.
Keep servers in-process and use loopback only.
Do not introduce real network dependencies beyond local test servers.

### Snapshots

Use snapshots for stable public or internal contract shapes where a diff is easier to review than many scalar assertions.
Cymbal server snapshots are especially useful for public ingestion outcomes, mixed terminal cases, and error/retry/drop shapes.

Review snapshot changes as API behavior changes, not as formatting noise.
If a snapshot changes unexpectedly, investigate before accepting it.

### Mocks and fakes

Use mocks or small fakes at side-effect boundaries: symbol resolvers, grouping/assignment/suppression repositories, Redis/global limiters, object storage, PostHog capture, and remote stage clients.
The goal is to test Cymbal's decisions without calling real Redis, S3, Postgres, external HTTP, PostHog capture, or non-loopback services unless the test is explicitly a SQLx or in-process gRPC integration test.

Prefer trait-backed fakes already present in the owning crate.
When a new seam is needed, keep it scoped to the dependency boundary rather than mocking internal implementation details.

## Coverage helper

`scripts/coverage.sh` runs `cargo-llvm-cov` against the broad Cymbal package set while delegating to `../Cargo.toml`.
It excludes generated/static/target noise from reports with an ignore regex covering `target/`, `node/src/generated/`, local Node build directories, and large static fixture directories.

Install the required tool with:

```sh
cargo install cargo-llvm-cov --locked
rustup component add llvm-tools-preview
```

If `cargo-llvm-cov` still reports "failed to find llvm-tools-preview" after the above steps, provide explicit LLVM binary paths:

```sh
LLVM_COV=~/.rustup/toolchains/stable-aarch64-apple-darwin/lib/rustlib/aarch64-apple-darwin/bin/llvm-cov \
LLVM_PROFDATA=~/.rustup/toolchains/stable-aarch64-apple-darwin/lib/rustlib/aarch64-apple-darwin/bin/llvm-profdata \
scripts/coverage.sh --summary
```

Adjust the toolchain name to match your platform (e.g. `stable-x86_64-unknown-linux-gnu`).

Supported modes:

```sh
scripts/coverage.sh --summary
scripts/coverage.sh --html
scripts/coverage.sh --lcov
```

`--summary` prints the text summary used for baseline updates.
`--html` writes `target/coverage/html/index.html` for local exploration.
`--lcov` writes `target/coverage/cymbal.lcov` for tooling that consumes LCOV.

The script intentionally fails early with a clear install command when `cargo-llvm-cov` is missing, so agents should not interpret a missing subcommand as a Rust test failure.

## Percentage coverage vs risk coverage

Percentage coverage tells us which lines or regions executed during tests.
It is useful for spotting untested files and tracking whether coverage is moving in the right direction, but it is not a release gate by itself.
A high percentage can still miss dangerous behavior if the untested lines are side-effect boundaries, retry logic, concurrency limits, codec errors, or tenant isolation checks.

Risk coverage is the higher-priority question: have we tested the failure modes that can drop events, duplicate side effects, break the public wire contract, overload remote stages, or cross tenant boundaries?
Use percentage coverage to find blind spots, then prioritize tests by operational and product risk.

## Measured baselines

### 2026-05-26 — Batch 8 final baseline

Measured with `cargo-llvm-cov` v0.8.7 and `llvm-tools` from the `stable-aarch64-apple-darwin` toolchain.
Runtime: ~99 seconds real time (250 s user / 92 s sys).
All 406 tests in the 16-crate package set pass.

```text
TOTAL   lines: 19839 lines, 3272 missed = 83.51%
        functions: 2260, 373 missed = 83.50%
        regions: 26171, 4736 missed = 81.90%
```

#### Per-file summary (lines covered)

| File | Lines | Covered |
|---|---|---|
| api/src/lib.rs | 30 | 100.00% |
| core/src/circuit.rs | 205 | 95.61% |
| core/src/concurrency.rs | 152 | 95.39% |
| core/src/emission.rs | 194 | 97.94% |
| core/src/executor.rs | 13 | 76.92% |
| core/src/lib.rs | 65 | 67.69% |
| core/src/pipeline.rs | 215 | 88.37% |
| core/src/progress.rs | 19 | **0.00%** |
| core/src/rate_limit.rs | 206 | 98.54% |
| core/src/routing/capacity.rs | 97 | 85.57% |
| core/src/routing/fallback.rs | 44 | 97.73% |
| core/src/routing/key.rs | 45 | 86.67% |
| core/src/routing/mod.rs | 275 | 98.91% |
| core/src/routing/partition.rs | 101 | 94.06% |
| core/src/routing/policy.rs | 165 | 98.18% |
| core/src/runner.rs | 656 | 91.01% |
| domain/src/event.rs | 99 | 100.00% |
| domain/src/exception.rs | 201 | 94.53% |
| domain/src/frame.rs | 123 | 65.04% |
| domain/src/release.rs | 54 | 100.00% |
| domain/src/sanitize.rs | 70 | 95.71% |
| fingerprinting/src/lib.rs | 297 | 95.62% |
| pipeline/src/lib.rs | 377 | 87.53% |
| pipeline/src/ordering.rs | 68 | 61.76% |
| pipeline/src/runner.rs | 298 | 95.64% |
| pipeline/src/stage_graph.rs | 36 | 91.67% |
| pipeline/src/streaming.rs | 123 | 91.06% |
| repositories/src/issue.rs | 339 | 93.81% |
| repositories/src/posthog.rs | 250 | 90.80% |
| repositories/src/redis.rs | 46 | 69.57% |
| repositories/src/team.rs | 58 | **34.48%** |
| rules/src/assignment.rs | 91 | **36.26%** |
| rules/src/grouping.rs | 98 | 59.18% |
| rules/src/suppression.rs | 165 | 76.36% |
| runtime/src/lib.rs | 740 | **27.03%** |
| server/src/api.rs | 347 | 97.12% |
| server/src/codec.rs | 143 | 90.21% |
| server/src/config.rs | 331 | 84.89% |
| server/src/main.rs | 250 | **0.00%** (binary entry, excluded by design) |
| server/src/observability.rs | 570 | 90.00% |
| server/src/pipeline.rs | 940 | 92.55% |
| server/src/pipeline_routing.rs | 101 | 89.11% |
| server/src/registry.rs | 384 | 87.76% |
| server/src/remote/circuit.rs | 51 | 94.12% |
| server/src/remote/client.rs | 77 | 98.70% |
| server/src/remote/connection.rs | 1124 | 93.42% |
| server/src/remote/load.rs | 101 | 98.02% |
| server/src/remote_runner.rs | 1457 | 96.71% |
| server/src/stage.rs | 324 | 98.15% |
| stages/alerting/src/lib.rs | 945 | 94.71% |
| stages/grouping/src/lib.rs | 368 | 90.76% |
| stages/linking/src/lib.rs | 1003 | 89.93% |
| stages/rate-limiting/src/lib.rs | 512 | 71.68% |
| stages/resolution/src/exception.rs | 114 | 78.07% |
| stages/resolution/src/frame.rs | 57 | 100.00% |
| stages/resolution/src/lib.rs | 646 | 91.95% |
| stages/resolution/src/properties.rs | 69 | 100.00% |
| stages/resolution/src/symbol.rs | 55 | **0.00%** |
| symbol-store/src/apple.rs | 222 | 80.18% |
| symbol-store/src/caching.rs | 95 | 75.79% |
| symbol-store/src/catalog.rs | 23 | 73.91% |
| symbol-store/src/chunk_id.rs | 32 | 90.62% |
| symbol-store/src/concurrency.rs | 72 | 95.83% |
| symbol-store/src/config.rs | 40 | 100.00% |
| symbol-store/src/dart_minified_names.rs | 62 | 95.16% |
| symbol-store/src/error.rs | 79 | **18.99%** |
| symbol-store/src/hermesmap.rs | 27 | 62.96% |
| symbol-store/src/lib.rs | 2 | 100.00% |
| symbol-store/src/proguard.rs | 58 | 67.24% |
| symbol-store/src/refs.rs | 82 | 73.17% |
| symbol-store/src/s3.rs | 84 | 84.52% |
| symbol-store/src/saving.rs | 331 | 94.56% |
| symbol-store/src/sourcemap.rs | 459 | 77.12% |
| symbolication/src/apple.rs | 458 | 74.89% |
| symbolication/src/custom.rs | 131 | 100.00% |
| symbolication/src/dart.rs | 93 | 100.00% |
| symbolication/src/go.rs | 66 | 100.00% |
| symbolication/src/hermes.rs | 184 | 61.96% |
| symbolication/src/java.rs | 182 | 52.75% |
| symbolication/src/js.rs | 225 | **21.33%** |
| symbolication/src/lib.rs | 30 | 90.00% |
| symbolication/src/node.rs | 214 | **0.00%** |
| symbolication/src/php.rs | 131 | 97.71% |
| symbolication/src/python.rs | 124 | 100.00% |
| symbolication/src/raw_frame.rs | 203 | 83.74% |
| symbolication/src/ruby.rs | 105 | 100.00% |
| symbolication/src/utils.rs | 41 | 82.93% |

### Known report exclusions

The coverage helper excludes report noise from:

- `target/` build output.
- `node/src/generated/` generated TypeScript bindings.
- `node/dist/` and `node/node_modules/` local Node artifacts.
- `tests/static/` and `crates/*/tests/static/` large fixtures.

These exclusions are intended to keep generated or fixture-heavy paths from obscuring Cymbal Rust source coverage.
They do not exclude Rust source files in the package set.

`server/src/main.rs` reports 0% because it is the binary entry point (main function and startup wiring) which cannot be called by unit or integration tests.
This is expected and should be treated as an infrastructure-only file.

## Remaining gaps and risk prioritization

The following files have the lowest line coverage and are highest-risk for operational failure or data loss.
They should be targeted for the next test investment before proposing a CI coverage gate.

### Zero-coverage files (not entry points)

- `core/src/progress.rs` — 0% (19 lines).
  Progress tracking implementation.
  Add a focused unit test for the progress callback path.

- `stages/resolution/src/symbol.rs` — 0% (55 lines).
  Symbol-type dispatch and classification helpers used during resolution.
  These are called only via the full symbolication path which requires a real or mocked provider.
  Add unit tests covering the type dispatch branches directly.

- `symbolication/src/node.rs` — 0% (214 lines).
  Node.js source-map frame resolution.
  No unit tests exist because the Node symbolication path requires a source-map fetch stub.
  Add mocked tests covering the resolution and error-fallback branches.

### Low-coverage high-risk files

- `symbolication/src/js.rs` — 21.33% (177/225 lines missed).
  JavaScript source-map resolution: the production-critical path for web events.
  Most paths require a source-map provider; add `httpmock`-backed tests for the resolution,
  error, and 404 paths consistent with `crates/symbol-store/src/sourcemap.rs` patterns.

- `runtime/src/lib.rs` — 27.03% (540/740 lines missed).
  Process startup, service construction, and Tokio runtime wiring.
  Most untested paths are constructors that pull env-vars or build real clients.
  The pure-config tests added in Batch 7 cover a subset; the remainder requires either
  dependency injection or additional scoped config-builder tests.

- `rules/src/assignment.rs` — 36.26% (58/91 lines missed).
  Assignment rule evaluation.
  Currently tested only at the grouping/linking stage level.
  Add unit tests for the rule-matching branches, user/role extraction, and error paths
  directly in `cymbal-rules`.

- `repositories/src/team.rs` — 34.48% (38/58 lines missed).
  Cached team repository: cache hit/miss, TTL, and error branches.
  SQLx tests would require the dev Postgres stack.
  Consider a pure fake-backend test for the caching layer.

- `symbol-store/src/error.rs` — 18.99% (64/79 lines missed).
  Error type conversions and `Display` impls.
  Add trivial unit tests covering each `From` conversion and the important `Display` strings.

- `symbolication/src/hermes.rs` — 61.96% (70/184 lines missed).
  React Native / Hermes source-map resolution.
  Extend existing `tests/static/` fixture test to cover error and fallback branches.

- `symbolication/src/java.rs` — 52.75% (86/182 lines missed).
  ProGuard/Java resolution.
  Most untested paths are within `resolve` and `resolve_impl`, which require a ProGuard
  mapping fixture.
  Use `httpmock` or a `MockBlobClient` to cover the resolution and fallback branches.

### Medium-gap files worth watching

- `pipeline/src/ordering.rs` — 61.76%: ordering edge cases for in-flight drain.
- `rules/src/grouping.rs` — 59.18%: grouping-rule evaluation branches.
- `stages/rate-limiting/src/lib.rs` — 71.68%: rate-limit enforcer paths (team-scoped key construction, error types).
- `symbol-store/src/sourcemap.rs` — 77.12%: source-map fetch paths (some branches require HTTP stubs).

## CI enforcement recommendation

Do not add a CI coverage gate in the next batch.
Reasons:

1. The `scripts/coverage.sh --summary` run takes ~99 seconds real time (250 s user) locally.
   On a CI runner without caching, this would add 3–5 minutes to every PR run.
2. The gaps in `runtime/src/lib.rs` and `server/src/main.rs` are structural (startup wiring, binary entry point) and would require a non-trivial threshold exception list.
3. The zero-coverage files (`node.rs`, `symbol.rs`, `progress.rs`) are legitimate targets for the next test batch, not measurement noise.

**Recommended path to CI enforcement:**

1. Close the zero-coverage and <50% gaps listed above (estimate: 1–2 batches).
2. Add `--fail-under=N` to `scripts/coverage.sh --summary` (supported by `cargo-llvm-cov`).
3. Add a `coverage` job to `.github/workflows/` that runs `scripts/coverage.sh --summary` only on PRs touching Cymbal source files (use path filters to avoid cost on non-Cymbal changes).
4. Set the initial threshold at 80% lines (below the current 83.51% measured baseline) to start fail-closed without blocking existing PRs.
5. Ratchet the threshold upward as gaps close.
