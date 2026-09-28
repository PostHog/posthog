# deltalite

Streaming partition-level upsert for Delta tables, replacing delta-rs's SQL
`MERGE` for the warehouse-sync incremental path. delta-rs stays the storage and
protocol layer (log, checkpoints, Parquet writing, Add-action statistics, S3
conditional-put commits, conflict resolution); only the *merge execution* is
replaced.

Why: MERGE executes a DataFusion hash join whose memory scales with the scanned
target and which deadlocks under a bounded memory pool
([delta-io/delta-rs#4614](https://github.com/delta-io/delta-rs/issues/4614),
reproduced). deltalite builds a PK hash set over the (small) source, streams the
(large) target one row group at a time, drops replaced rows, writes survivors
plus the source rows, and commits every partition in ONE atomic commit. Peak
memory is bounded by the source and the concurrency knobs — never by table
size. The validation spike measured memory flat from 62k to 1M-row partitions,
~4x below MERGE, at matching write volume via exact content-based file
selection; the semantics are proven by the differential parity suite in
`python/tests/`.

## Layout — and why it is two crates

| Path | What |
|---|---|
| `core/` | `deltalite-core`: all the logic (upsert pipeline, PK set, pruning/probing, schema casting, decimal realignment, process-global limits, multipart store). Pure Rust, no pyo3. **Workspace member** — normal CI (build, nextest, clippy, fmt) applies. All Rust unit tests live here. |
| `python/` | `deltalite-python`: thin pyo3 binding, built by maturin, imported as `deltalite`. Workspace member shaped like `rust/hogql/parser` (cdylib+rlib, `extension-module`, abi3-py312) — no Rust tests, see below. |
| `python/tests/` | The differential parity suite plus probe/operations/types/crash-redelivery/interop/planner/guard tests (pytest, 159 tests). Runs the same batch sequences through real delta-rs `merge` and through `deltalite.upsert` and asserts identical logical content. |
| `python/harness/` | The two write paths + logical comparison used by the tests. `merge_path` is a faithful transcription of the production incremental branch of `DeltaTableHelper.write_to_deltalake`. |
| `python/deltalite_planner.py` | Rough knob tuning: given concurrent upserts and pod memory, suggests starting values for `max_parallel_partitions` / `max_parallel_files` / the byte budget and the process-global env ceilings. A heuristic, not a capacity model. |

Two crates because pyo3's `extension-module` feature suppresses the libpython
link, so a `cargo test` harness binary for an extension crate **cannot link on
Linux**. `hogql/parser` sidesteps this by having no Rust tests; deltalite needs
Rust unit tests for its pure logic, so the logic lives in a pyo3-free crate and
the binding crate stays test-free.

Related constraint: cargo permits only **one pyo3 version per dependency graph**
(pyo3 has `links = "python"`). deltalite's pyarrow ingest uses arrow 58's
`pyarrow` feature (arrow major fixed by `deltalake` 0.32), which requires
pyo3 0.28 — so `rust/hogql/parser` was migrated from pyo3 0.22 to 0.28 to share
the workspace, and the two must bump pyo3 in lockstep from here on.

`deltalite-core` pins `deltalake = "=0.32.4"` — the newest *published*
crates.io release, deliberately NOT "the same delta-rs as the Python package"
(that tree is unbuildable as published: it pins a moving git branch and ships
no lockfile — see the comment in `core/Cargo.toml`). The parity suite, not
version equality, is the compatibility check; every bump of either side must
keep it green.

## Building locally

```bash
# Editable install of the extension into the active venv:
uv pip install -e rust/deltalite/python

# Or via maturin directly (faster incremental):
maturin develop --release --manifest-path rust/deltalite/python/Cargo.toml

# Sanity check
python -c "import deltalite; print(deltalite.DeltaLiteTable)"

# Rust unit tests / lints (workspace tooling covers core):
cd rust && cargo test -p deltalite-core && cargo clippy -p deltalite-core --all-targets

# Note for non-flox shells on macOS: rust/.cargo/config.toml adds -fuse-ld=lld,
# which only exists inside the flox env. Outside it, override with
#   RUSTFLAGS="--cfg tokio_unstable" cargo <cmd>
```

The Python test suite (needs `deltalake`, `pyarrow`, `duckdb`, `pytest` —
versions matching the repo's `pyproject.toml` pins):

```bash
uv venv /tmp/deltalite-venv --python 3.13
VIRTUAL_ENV=/tmp/deltalite-venv uv pip install maturin pytest \
    'deltalake==1.6.1' 'pyarrow==23.0.1' 'duckdb~=1.5.2'
VIRTUAL_ENV=/tmp/deltalite-venv /tmp/deltalite-venv/bin/python -m maturin develop \
    --release --manifest-path rust/deltalite/python/Cargo.toml
/tmp/deltalite-venv/bin/python -m pytest rust/deltalite/python/tests -q
```

CI runs exactly this in `.github/workflows/ci-deltalite-python.yml`,
path-filtered to `rust/deltalite/**`.

## How the wheel is built and consumed

Mirrors `hogql-parser-rs` (see `.github/workflows/build-hogql-parser-rs.yml`):

- maturin builds a single `cp312-abi3` wheel per platform that works on every
  Python 3.12+ (including the pinned prod 3.13). `[project] name = "deltalite"`,
  module name `deltalite`.
- When a release is cut, a `build-deltalite` workflow (to be cloned from
  `build-hogql-parser-rs.yml` at rollout time: version-bump detection on
  `rust/deltalite/python/**`, maturin-action wheel matrix for manylinux 2_28 +
  musllinux x86_64/aarch64 and macOS arm64/x86_64, publish, then a follow-up PR
  pinning `deltalite==<version>` in `pyproject.toml`) publishes it; the posthog
  image then installs it like any other wheel via `uv sync` — no Rust toolchain
  in the image.
- Version lives in BOTH `python/Cargo.toml` and `python/pyproject.toml`
  (always identical); bump both together.

Until that workflow lands, the wheel is dev-installed as above; nothing in the
Django app imports `deltalite` yet (the `DeltaTableHelper` seam is a separate,
flag-gated change).

## Operational knobs

Per-call (arguments to `DeltaLiteTable.upsert`): `max_parallel_partitions` (2),
`max_parallel_files` (4), `max_buffered_bytes` (64 MiB), `prune_strategy`
(`probe`), `probe_concurrency` (8), `read_batch_size` (8192),
`target_file_size` (table's `delta.targetFileSize`, else delta-rs's 100 MiB),
`max_source_bytes` (2 GiB guard), `multipart_threshold` (64 MiB) /
`multipart_part_size` (16 MiB), `commit_max_retries` (15).

Process-global (environment, enforced on top of the per-call knobs so that
~15 concurrent upsert threads in one Temporal worker cannot multiply the
budgets): `DELTALITE_PROCESS_MAX_PARALLEL_PARTITIONS` (8),
`DELTALITE_PROCESS_MAX_PARALLEL_FILES` (16),
`DELTALITE_PROCESS_MAX_BUFFERED_BYTES` (256 MiB), `DELTALITE_MAX_SOURCE_BYTES`,
`DELTALITE_MULTIPART_THRESHOLD_BYTES`, `DELTALITE_MULTIPART_PART_SIZE_BYTES`.

For a rough starting point on a given pod, `python/deltalite_planner.py`
suggests knob values from concurrency + pod memory, e.g.
`python deltalite_planner.py 15 8000 --source-mb 250`.

Metrics (`metrics` crate, static labels only): `deltalite_upserts_total`
(`outcome`, `prune_strategy`, `error_kind`), `deltalite_upsert_duration_seconds`,
`deltalite_files_{added,removed,carried_over,probed}_total`,
`deltalite_rows_{updated,inserted,copied}_total`.

## Pre-rollout conditions (from the spike verdict, still open)

- Verify against real AWS S3 (spike verified MinIO/SeaweedFS only).
- Gate rollout on a conditional-put startup probe: an endpoint that silently
  ignores `If-None-Match: *` loses concurrent commits with no error anywhere.
- Adopt a `vacuum(full=True)` policy where deltalite ships: lite vacuum never
  reclaims crash orphans, and a late crash orphans a whole batch's files.
- Check rollout tables for pre-existing duplicate-key batches: deltalite
  rejects duplicate source PKs that MERGE silently double-inserts.
