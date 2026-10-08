# Contributing to posthog-symbol-data

## Releasing a new version

The crate uses [Sampo](https://github.com/bruits/sampo) changesets and publishes to [crates.io](https://crates.io/crates/posthog-symbol-data) with trusted publishing.
No crates.io API token is required.

Add a changeset for every releasable change.
Run this command from `rust/common/symbol_data/`:

```bash
sampo add --package cargo/posthog-symbol-data --bump patch --message "Describe the crate change"
```

Use `minor` or `major` instead of `patch` when appropriate.
Commit the generated file under `.sampo/changesets/` with the change.
Do not edit the package version in the feature pull request.

After the changeset reaches `master`, the `Release posthog-symbol-data` workflow:

1. Waits for approval in the GitHub `Release SDK` environment.
2. Runs `sampo release` to update `Cargo.toml`, `rust/Cargo.lock`, and `CHANGELOG.md`.
3. Opens a draft release pull request with the generated changes.
4. Publishes `posthog-symbol-data` to crates.io after the release pull request reaches `master` through the merge queue.

A maintainer must review the draft release pull request, mark it ready, and send it through the merge queue.
Do not run `sampo publish`, `cargo publish`, or push a release tag manually.
