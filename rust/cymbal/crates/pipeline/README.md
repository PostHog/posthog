# cymbal-pipeline

Pure Rust composition of Cymbal stages: rate limiting, resolution, grouping, linking, and alerting.

Edit this package when changing stage order, executor behavior, result merging, streaming, or output ordering. Keep server transport and runtime wiring elsewhere.

Validate from `rust/cymbal`:

```sh
cargo test --manifest-path ../Cargo.toml -p cymbal-pipeline
```
