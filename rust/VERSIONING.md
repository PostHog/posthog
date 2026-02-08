# Rust Versioning Protocol

This document defines the protocol for updating Rust toolchain and dependency versions across the PostHog Rust workspace.

## Overview

The Rust stable channel releases every 6 weeks. To balance staying current with stability, we follow a conservative update cadence that keeps us one version behind stable while ensuring all workspace members remain in sync.

## Update Schedule

### Rust Toolchain

- **Frequency:** Every 12 weeks (approximately 3 months)
- **Strategy:** Adopt the even minor version when the following odd version becomes available on stable
- **Example:** When Rust 1.95.0 is released to stable, we upgrade to 1.94.0

This "one version behind" approach provides:

- Time for the community to identify and report issues with the latest release
- Reduced churn from immediate patch releases
- A predictable, manageable update cadence

### Crate Dependencies

Dependencies are updated alongside Rust toolchain updates. We use `cargo outdated --root-deps-only` to identify updates to direct dependencies only, avoiding noise from transitive dependencies.

## Version Synchronization Points

The Rust version is pinned across multiple files in the repository. The source of truth is `rust/rust-toolchain.toml`, and all other locations must stay in sync.

A verification script is provided at `rust/bin/check-rust-version-sync`. Run it from the repository root to confirm all sync points match:

```sh
rust/bin/check-rust-version-sync
```

### Source of Truth

| File | Format | Notes |
|------|--------|-------|
| `rust/rust-toolchain.toml` | `1.XX.Y` | Canonical version; used by `rustup` for local development |

### CI Workflows (full version `1.XX.Y`)

All `toolchain:` entries in the following workflow files must match the full version:

| File | Notes |
|------|-------|
| `.github/workflows/ci-rust.yml` | Rust build, test, and lint jobs |
| `.github/workflows/ci-backend.yml` | Backend CI requiring Rust compilation |
| `.github/workflows/ci-cli.yml` | CLI build, test, lint, and release jobs |
| `.github/workflows/ci-ai.yml` | AI service CI |
| `.github/workflows/ci-nodejs.yml` | Node.js CI (native module compilation) |

### Dockerfiles (minor version `1.XX`)

Docker base images use the minor version only so patch updates are picked up automatically:

| File | Notes |
|------|-------|
| `rust/Dockerfile` | Main Rust service image |
| `rust/Dockerfile.sqlx-migrate` | SQLx migration runner |
| `rust/Dockerfile.migrate-hooks` | Hooks migration runner |

### Composite Container Images (minor version `1.XX`)

These use a composite `rust-node-container` image tag that embeds the Rust minor version:

| File | Notes |
|------|-------|
| `Dockerfile` | Root production image |
| `Dockerfile.node` | Node.js production image |

### Other

| File | Format | Notes |
|------|--------|-------|
| `.flox/env/manifest.toml` | `1.XX.Y` | Flox dev environment; keeps local tooling in sync |
| `rust/cyclotron-core/Cargo.toml` | `1.XX.Y` | MSRV metadata (`rust-version` field) |

### Workspace-Level Dependency Versions

All shared dependencies are defined in `rust/Cargo.toml` under `[workspace.dependencies]`. Individual packages reference these with `{ workspace = true }`.

The lockfile at `rust/Cargo.lock` ensures reproducible builds across all environments.

## Step-by-Step Update Procedure

### Prerequisites

- Ensure you're on the `master` branch with no uncommitted changes
- Have `cargo-outdated` installed: `cargo install cargo-outdated`

### Step 1: Check Current Rust Version

Determine the current stable Rust version:

```sh
rustup check
```

Or check the official [Rust releases page](https://releases.rs/).

### Step 2: Determine Target Version

Apply the versioning strategy:

- If current stable is an **odd** minor version (e.g., 1.95.0), target the previous **even** version (1.94.0)
- If current stable is an **even** minor version (e.g., 1.94.0), wait for the next odd release

### Step 3: Update Rust Toolchain Version

Search for the current version across the repository and replace it in every sync point listed above. Start with the source of truth, then propagate:

1. Update `rust/rust-toolchain.toml` with the new full version
2. Search `.github/workflows/` for the old `toolchain:` value and replace with the new full version
3. Search `rust/Dockerfile*` for the old `rust:` base image tag and replace the minor version
4. Search the root `Dockerfile` and `Dockerfile.node` for `rust_` in the composite image tag and replace the minor version
5. Update the `cargo` version in `.flox/env/manifest.toml`
6. Update `rust-version` in `rust/cyclotron-core/Cargo.toml`

After editing, run the verification script from the repository root to confirm every sync point was updated correctly:

```sh
rust/bin/check-rust-version-sync
```

### Step 4: Verify Toolchain Compatibility

Run `cargo check` to verify the workspace compiles with the new Rust version:

```sh
cd rust
cargo check --all
```

If there are compilation errors (e.g., deprecated features, removed APIs), fix them before proceeding.

### Step 5: Update Compatible Dependencies

Run `cargo update` to update all dependencies to their latest compatible versions according to semver:

```sh
cargo update
```

> **Note:** This command only modifies `Cargo.lock`, not `Cargo.toml`. It updates dependencies to the latest versions that satisfy the version constraints already specified in `Cargo.toml`. For example, if `Cargo.toml` specifies `tokio = "1.34.0"`, running `cargo update` may update the lockfile to use `1.43.0` (or whatever the latest 1.x version is).

### Step 6: Verify After Lockfile Update

Run `cargo check` again to ensure all updated dependencies work correctly together:

```sh
cargo check --all
```

If any issues arise from updated dependencies, investigate and resolve them before continuing.

### Step 7: Check for Outdated Dependencies

Navigate to the workspace root and check for outdated direct dependencies:

```sh
cd rust
cargo outdated --root-deps-only
```

This outputs a table showing:

- **Name:** Package name
- **Project:** Currently specified version
- **Compat:** Latest compatible version (within semver)
- **Latest:** Absolute latest version
- **Kind:** Dependency type (Normal, Development, Build)

Generally there won't be a lot of outdated crates listed here, but they will require the most work.

### Step 8: Evaluate Dependency Updates

For each outdated dependency, assess the update:

1. **Compatible updates** (Project -> Compat): Generally safe, apply these
2. **Breaking updates** (Project -> Latest crosses major version): Review changelog for:
   - Breaking API changes
   - Deprecated features we use
   - New features that benefit us
   - Migration guides

Document any breaking changes that require code modifications.

### Step 9: Update Dependencies

Edit `rust/Cargo.toml` under `[workspace.dependencies]` to update versions:

```toml
[workspace.dependencies]
# Update from:
tokio = { version = "1.34.0", features = ["full"] }
# To:
tokio = { version = "1.40.0", features = ["full"] }
```

### Step 10: Update Lockfile

Regenerate the lockfile with the new versions:

```sh
cd rust
cargo update
```

For specific packages only:

```sh
cargo update -p tokio -p axum
```

### Step 11: Build and Test

Verify the workspace builds and all tests pass:

```sh
# Build all packages
cargo build --all --locked --release

# Run all tests (or use individual package tests)
cargo test --all

# Check formatting
cargo fmt --check

# Run clippy
cargo clippy --all-targets --all-features -- -D warnings

# Check for unused dependencies
cargo shear
```

Alternatively, use the feature-flags Makefile for integrated testing:

```sh
cd rust/feature-flags
make test
```

### Step 12: Verify Docker Build

Build the Docker image locally to ensure the Dockerfile works:

```sh
cd rust
docker build -t posthog-rust-test .
```

### Step 13: Create Pull Request

Commit all changes with a descriptive message:

```sh
git add -A
git commit -m "chore(rust): update rust to 1.XX.Y and refresh dependencies"
```

Include in the PR description:

- Target Rust version and rationale
- List of updated dependencies with version changes
- Any breaking changes and how they were addressed
- Test results summary

## Handling Breaking Changes

When a dependency update introduces breaking changes:

1. **Review the changelog** for the affected crate
2. **Check for migration guides** in the crate documentation
3. **Update code** across all affected workspace members
4. **Run tests** to verify correctness
5. **Document the change** in the PR description

For significant breaking changes, consider:

- Splitting the PR into separate toolchain and dependency updates
- Creating follow-up issues for larger refactoring efforts
- Consulting with the team on architectural decisions

### rust-toolchain.toml

The file `rust/rust-toolchain.toml` is the single source of truth for the Rust version. When present in a directory, `rustup` automatically installs and uses the specified toolchain, which ensures local development stays in sync with CI and production.

## Quick Reference

```sh
# 1. Check current stable Rust version
rustup check

# 2. Update all sync points (see table above for the full list)
#    - rust/rust-toolchain.toml               (full version)
#    - .github/workflows/ci-*.yml             (full version, toolchain: entries)
#    - rust/Dockerfile*                        (minor version, FROM rust: tags)
#    - Dockerfile, Dockerfile.node             (minor version, rust_ in image tag)
#    - .flox/env/manifest.toml                 (full version, cargo version)
#    - rust/cyclotron-core/Cargo.toml          (full version, rust-version field)

# 3. Verify all sync points match
rust/bin/check-rust-version-sync

# 4. Verify toolchain compatibility
cd rust
cargo check --all

# 5. Update lockfile with compatible versions (semver)
cargo update

# 6. Verify after lockfile update
cargo check --all

# 7. Check for outdated dependencies (breaking updates)
cargo outdated --root-deps-only

# 8. Edit Cargo.toml for any breaking updates, then:
cargo update -p <package1> -p <package2>

# 9. Full verification
cargo build --all --locked --release
cargo test --all
cargo fmt --check
cargo clippy --all-targets --all-features -- -D warnings
cargo shear

# 10. Verify Docker build
docker build -t posthog-rust-test .

# 11. Commit and create PR
git add -A
git commit -m "chore(rust): update rust to 1.XX.Y and refresh dependencies"
```
