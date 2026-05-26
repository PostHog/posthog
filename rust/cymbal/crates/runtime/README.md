# cymbal-runtime

Runtime setup and construction of infrastructure-backed stage dependencies from environment config.

Edit this package when adding runtime config, wiring repositories into stages, building symbolication dependencies, or changing process guards. Keep server transport knobs in `cymbal-server`.

Validate from `rust/cymbal`:

```sh
cargo test --manifest-path ../Cargo.toml -p cymbal-runtime
```
