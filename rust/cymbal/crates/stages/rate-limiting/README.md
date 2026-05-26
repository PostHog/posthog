# cymbal-rate-limiting

Pre-resolution team rate-limiting gate keyed by numeric `team_id`.

Edit this package when changing Cymbal rate-limit config, limiter construction, limiter decisions, or rate-limit metrics. Do not include user-controlled payload strings in Redis keys.

Validate from `rust/cymbal`:

```sh
cargo test --manifest-path ../Cargo.toml -p cymbal-rate-limiting
```
