# Contributing to posthog-symbol-data

## Releasing a new version

The crate is published to [crates.io](https://crates.io/crates/posthog-symbol-data) automatically via GitHub Actions
using trusted publishing (OIDC — no API tokens required).

### Steps

1. **Bump the version** in `Cargo.toml` following [semver](https://semver.org/):

   ```toml
   version = "0.5.0"
   ```

2. **Tag the release** on your branch:

   ```sh
   git tag posthog-symbol-data/v0.5.0
   git push origin posthog-symbol-data/v0.5.0
   ```

   The tag **must** match the version in `Cargo.toml` — the workflow verifies this before publishing.

3. **Monitor the publish** — the [publish-symbol-data-crate](/.github/workflows/publish-symbol-data-crate.yml) workflow
   runs automatically on the tag push.

   Check the Actions tab for status.
