# cymbal-symbol-store

Symbol artifact storage, fetch/cache/load/save helpers, provider parsers, and symbol-store metrics.

Edit this package when changing symbol set references, object storage access, sourcemap/Proguard/Hermes/Apple parsing, cache behavior, or save reporting. Keep SSRF and cache-size controls intact.

Validate from `rust/cymbal`:

```sh
cargo test --manifest-path ../Cargo.toml -p cymbal-symbol-store
```
