# cymbal-linking

Linking stage that connects grouped events to issues, suppression rules, assignment rules, and issue side effects.

Edit this package when changing issue creation/reopen flow, suppression sampling, assignment application, fingerprint metadata, or linking caches. Keep integrations behind traits.

Validate from `rust/cymbal`:

```sh
cargo test --manifest-path ../Cargo.toml -p cymbal-linking
```
