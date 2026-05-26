# cymbal-resolution

Resolution stage that parses exception properties and raw frames into normalized, resolved events.

Edit this package when changing exception parsing, frame resolution, symbol lookup orchestration, or symbol-resolution metrics. Keep artifact fetching in `cymbal-symbol-store`.

Validate from `rust/cymbal`:

```sh
cargo test --manifest-path ../Cargo.toml -p cymbal-resolution
```
