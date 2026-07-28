# deltalite (Python package)

Thin pyo3 binding over `deltalite-core`, built with maturin and imported as
`deltalite`. See [`../README.md`](../README.md) for what deltalite is, why the
crate is split in two, how the wheel is built and consumed, the operational
knobs, and the pre-rollout conditions.

- `src/lib.rs` — the pyo3 module: `DeltaLiteTable.open(...).upsert(...)`,
  `UpsertStats`, and the `DeltaLiteError` exception hierarchy.
- `tests/` — the differential parity suite (delta-rs MERGE vs deltalite upsert)
  plus probe/operations/types/crash-redelivery/interop/planner tests.
- `harness/` — the two write paths and logical-content comparison the tests use.
- `deltalite_planner.py` — rough knob-tuning helper (concurrent upserts + pod
  memory in, suggested mpp/mpf/byte-budget out).
- `bench/` — test-data generation helpers shared by the tests.
