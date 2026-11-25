# Working on Meep

Meep provides reusable desktop crates under `crates/`. The maintained gallery in `examples/desktop/` shows how a host composes them with fixture data. Keep application-specific storage, credentials and service choices in the host.

## Development

- Run `sh scripts/check.sh` for formatting, Clippy and workspace tests. Run it before you push.
- Exercise changed UI in the gallery or a fixture host and inspect the affected states. Keep regression assertions with the code they cover.
- Keep the workspace and its documented commands runnable from a fresh checkout. Every example checked into Git should demonstrate a supported API and run against fixtures or explicitly documented prerequisites.

## Local work

- Keep personal apps, live-service clients, launchers and experimental harnesses in the ignored `.local/` directory. A local Rust project can use its own Cargo workspace and consume the checked-in crates by path.
- Put disposable screenshots, design-review notes, logs and probes under `.scratch/<task>/`. Remove your own directory after use. Keep local experiments and review evidence out of commits.
- Give tests an isolated temporary directory and release it on success or failure. Keep secrets, live databases and running service environments outside scratch. Use fixture data in captures.
- `sh scripts/clean.sh` clears shared scratch once active reviews finish. After builds finish, `sh scripts/clean.sh --build` also clears compiled Cargo profiles under the root `target/`. Both commands preserve `.local/` and bundled apps.
- Stage specific paths and review `git diff --cached` before committing. Preserve other work in shared checkouts and use the configured signing.
