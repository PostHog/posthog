# cymbal-server

Cymbal's gRPC server, public API conversion, local/remote stage dispatch, registry, observability, limits, readiness, and shutdown.

Edit this package when changing ingestion behavior, remote stage routing, stage serving, metrics, server config, or examples. Keep business logic in stage packages.

Validate from `rust/cymbal`:

```sh
cargo test --manifest-path ../Cargo.toml -p cymbal-server
cargo test --manifest-path ../Cargo.toml -p cymbal-server --test pipeline_snapshots
```
