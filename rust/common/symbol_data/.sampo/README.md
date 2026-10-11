# Sampo

This directory stores pending release changesets for `posthog-symbol-data`.

Run from `rust/common/symbol_data/`:

```bash
sampo add --package cargo/posthog-symbol-data --bump patch --message "Describe the crate change"
```

The release workflow consumes files in `.sampo/changesets/`, updates `Cargo.toml`, `rust/Cargo.lock`, and `CHANGELOG.md`, then opens a draft release pull request.
Merging that pull request publishes the crate to crates.io with trusted publishing.

Do not bump the version, publish the crate, or push release tags manually.
