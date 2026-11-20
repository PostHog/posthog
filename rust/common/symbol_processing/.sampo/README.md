# Sampo

This directory stores pending release changesets for `posthog-symbol-processing`.

Run from `rust/common/symbol_processing/`:

```bash
sampo add --package cargo/posthog-symbol-processing --bump patch --message "Describe the crate change"
```

The release workflow consumes files in `.sampo/changesets/`, updates `Cargo.toml`, `Cargo.lock`, and `CHANGELOG.md`, points `cli/Cargo.toml` and `cli/Cargo.lock` at the new version, then opens a draft release pull request.
Merging that pull request publishes the crate to crates.io with trusted publishing.

Do not bump the version, publish the crate, or push release tags manually.
