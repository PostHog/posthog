# cymbal-domain

Shared error-tracking domain DTOs, exception-event stage payload contracts, and sanitizers used across Cymbal stages.

Edit this package when changing exception properties, frames, releases, fingerprint record parts, sanitization behavior, or exception-pipeline contracts such as `InputEvent`, `EventResult`, `EventOutcome`, and `RateLimitGateOutput`.
Keep transport, persistence, runtime config, and stage business logic out.

The event contracts in `src/event.rs` implement `StagePayload` with historical `cymbal.core.*` type strings for remote-stage compatibility after the Rust module move.
Do not change those strings without an explicit wire-version migration and registry/snapshot updates.

Validate from `rust/cymbal`:

```sh
cargo test --manifest-path ../Cargo.toml -p cymbal-domain
```
