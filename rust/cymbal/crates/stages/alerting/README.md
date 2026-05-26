# cymbal-alerting

Whole-batch spike-detection alerting stage and alerting side-effect hooks.

Edit this package when changing spike bucket logic, alerting enablement, cooldowns, metrics, or alerting side-effect contracts. Event outcomes should pass through unchanged.

Validate from `rust/cymbal`:

```sh
cargo test --manifest-path ../Cargo.toml -p cymbal-alerting
```
