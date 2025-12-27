# posthog-symbol-data

## Publishing to crates.io

This crate is automatically published to crates.io when a PR labeled with `release-symbol-data` is merged to master. The GitHub workflow uses trusted publishing for authentication.

### Release Process

1. Create a new branch for the release:

   ```bash
   git checkout -b "symbol-data/release-v0.1.0"
   ```

2. Update the version number in `Cargo.toml`

3. Build to update `Cargo.lock`:

   ```bash
   cargo build
   ```

4. Commit your changes:

   ```bash
   git add .
   git commit -m "Bump symbol-data version to 0.1.0"
   ```

5. Create a PR and add the `release-symbol-data` label

6. Once the PR is approved and merged, the crate will be automatically published to crates.io
