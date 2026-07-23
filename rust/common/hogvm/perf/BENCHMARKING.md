# Benchmarking the Rust HogVM geoip path

## Prerequisites

- `share/GeoLite2-City.mmdb` must exist at the repo root (gitignored). On a fresh checkout
  run `./bin/download-mmdb` from the repo root — it fetches the database from
  mmdbcdn.posthog.net. (A normal dev setup via `hogli start` / `./bin/start` also runs it.)
- The napi addon crate lives at `rust/common/hogvm/node` and has its own workspace — build it
  from that directory, not the rust workspace root.

## The canonical metric: `profile_geoip`

From `rust/common/hogvm/node`:

```bash
cargo run --release --features noop --bin profile_geoip
```

This is fully self-contained: it loads the compiled geoip template bytecode and 5 realistic
event globals from `../perf/fixtures/`, initializes geoip from the dev mmdb, **asserts every
fixture event's output matches `perf/fixtures/geoip-expected.json` exactly** (hard failure on
semantic drift), then runs 100k iterations and prints `us/op`.

- Baseline at branch creation: **96.6 us/op** (M-series mac, default release profile with LTO).
- Runs vary ±3–5%; take the median of 3 runs before claiming a win or a regression.
- Numbers are machine-relative: on any new machine (e.g. a fresh CI or sandbox runner),
  re-measure the unmodified HEAD first and compare candidate changes against that
  same-machine baseline — never against numbers recorded on other hardware.
- After an *intentional, verified* semantic change (should be rare — the geoip output is
  pinned), regenerate the fixture with `--write-expected` and justify it in the commit message.
- Overrides: `profile_geoip <bytecode.json> <globals.json> <mmdb> [iters]`.

## Correctness gates (all must stay green)

```bash
# hogvm crate (from rust/, workspace member) — includes stl/vm/parity suites
cargo test -p hogvm

# napi addon (from rust/common/hogvm/node — own workspace; noop makes napi macros inert)
cargo test --features noop

# dependent crates must keep compiling (public API is additive-only)
cargo check -p cymbal -p cohort-core   # from rust/

# lint gates
cargo fmt --check && cargo clippy --all-targets -- -D warnings   # both workspaces
cargo shear
```

## Profiling (macOS)

Build with symbols and sample the running harness:

```bash
cd rust/common/hogvm/node
CARGO_PROFILE_RELEASE_DEBUG=true CARGO_PROFILE_RELEASE_LTO=false \
  cargo build --release --features noop --bin profile_geoip
$CARGO_TARGET_DIR/release/profile_geoip "" "" "" 300000 &
sample $! 15 -file /tmp/geoip-sample.txt
```

(Empty-string positionals fall back to defaults. The debug/LTO-off build is ~10% slower than
the canonical metric build — profile with it, measure with the canonical command.)

In the sample output, the "Sort by top of stack" section is the flat self-time profile.

## Profiling (Linux)

Same build, sampled with `perf`:

```bash
cd rust/common/hogvm/node
CARGO_PROFILE_RELEASE_DEBUG=true CARGO_PROFILE_RELEASE_LTO=false \
  cargo build --release --features noop --bin profile_geoip
perf record -F 997 -g --call-graph dwarf -o /tmp/geoip-perf.data -- \
  "${CARGO_TARGET_DIR:-target}/release/profile_geoip" "" "" "" 300000
perf report -i /tmp/geoip-perf.data --stdio --no-children --sort symbol | head -60
```

`--no-children` is the flat self-time profile (the equivalent of the macOS "Sort by top of
stack" section). If `perf record` is blocked by `kernel.perf_event_paranoid`, try
`sudo sysctl kernel.perf_event_paranoid=1`; failing that, fall back to
`valgrind --tool=callgrind` (much slower — use relative costs only).

## End-to-end comparison vs legacy plugin and node VM

From `nodejs/` (needs the addon built: `cd rust/common/hogvm/node && pnpm run build`):

```bash
./node_modules/.bin/tsx src/dev/bench-geoip.ts
```

Compares legacy TS plugin, node hogvm, and rust hogvm (executeSync / registered / batch)
on identical events, including output-parity assertions and per-path internal timings.
