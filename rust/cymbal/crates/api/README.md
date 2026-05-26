# cymbal-api

Protobuf definitions and generated Rust gRPC types for Cymbal's public ingestion API and internal stage API.

Edit this package when changing wire contracts in `proto/cymbal/v1/*.proto`. Keep domain logic out of this package.

Validate from `rust/cymbal`:

```sh
cargo test --manifest-path ../Cargo.toml -p cymbal-api
```
