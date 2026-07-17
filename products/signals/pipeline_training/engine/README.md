# Signals training evaluator

This Cargo project is the compact replay and scoring executable used by the parent training orchestrator. It exposes four operations:

- `replay CONFIG OUTPUT_DIR`
- `featurize-pairs CONFIG`
- `featurize-cuts CONFIG`
- `score ASSIGNMENT PAIR_LABELS REPORT_LABELS SOURCE_REPORTS OUTPUT`

The files under `src/kernel/` are a source-pinned copy of the Rust implementation that produced the elected artifact family. Artifact feature-contract strings are intentionally preserved because they are serving compatibility identifiers.

The copied classifier retains type references to the optional shuffler oracle. [`src/training_llm.rs`](src/training_llm.rs) satisfies that interface with a fail-closed stub, so this project has no HTTP client dependency and cannot initialize an API client. The CLI rejects `member_repair_llm_oracle=true` before constructing a replayer.

Build from this directory:

```bash
cargo build --release --features neural-onnx
```

The parent orchestrator runs that command in `build_engine`. `cargo check --features neural-onnx` is the cheap source validation path.

The compact evaluator was previously compared with the source evaluator over the same first 1,000 chronological validation A signals, model artifacts, and frozen operating point. It produced the same 98-report partition, and all 1,000 decision rows, 75 split events, and 59 report-shuffler events matched. The compact evaluator writes final assignment keys in sorted signal-ID order for deterministic serialization.
