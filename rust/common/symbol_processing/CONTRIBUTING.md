# Contributing to posthog-symbol-processing

## Releasing a new version

The crate uses [Sampo](https://github.com/bruits/sampo) changesets and publishes to [crates.io](https://crates.io/crates/posthog-symbol-processing) with trusted publishing.
No crates.io API token is required.

Add a changeset for every releasable change.
Run this command from `rust/common/symbol_processing/`:

```bash
sampo add --package cargo/posthog-symbol-processing --bump patch --message "Describe the crate change"
```

Use `minor` or `major` instead of `patch` when appropriate.
Commit the generated file under `.sampo/changesets/` with the change.
Do not edit the package version in the feature pull request.

After the changeset reaches `master`, the `Release posthog-symbol-processing` workflow:

1. Waits for approval in the GitHub `Release SDK` environment.
2. Runs `sampo release` to update `Cargo.toml`, `Cargo.lock`, and `CHANGELOG.md`.
3. Points posthog-cli at the new version, in `cli/Cargo.toml` and `cli/Cargo.lock`.
4. Opens a draft release pull request with the generated changes.
5. Publishes `posthog-symbol-processing` to crates.io after the release pull request reaches `master` through the merge queue.

A maintainer must review the draft release pull request, mark it ready, and send it through the merge queue.
Do not run `sampo publish`, `cargo publish`, or push a release tag manually.

## Release it before posthog-cli

posthog-cli builds this crate from this folder, and its crates.io package resolves the version named in `cli/Cargo.toml` from crates.io.
The two only match when that version is published and holds the source in this folder.

So a change to this crate that posthog-cli needs is released in this order:

1. Merge the change with a changeset for this crate, and a changeset for posthog-cli when its behavior changes.
2. Merge this crate's release pull request and wait for the publish job.
3. Merge posthog-cli's release pull request.

The `Release CLI` workflow runs `cli/scripts/check-symbol-processing-published.sh` before it prepares a release and again before it publishes.
The check fails with the missing step when the order was not followed.
