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

The Rust version must be updated in the following locations:

| File | Line(s) | Format | Notes |
|------|---------|--------|-------|
| `.github/workflows/ci-rust.yml` | 73, 162, 255 | `1.XX.Y` | CI build, test, and lint jobs |
| `rust/Dockerfile` | 2 | `1.XX` | Minor version only (patch updates automatically) |
| `rust/cyclotron-core/Cargo.toml` | 5 | `1.XX.Y` | MSRV metadata |

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

Update all synchronization points:

```sh
cd /path/to/posthog

# 1. Update CI workflow (3 locations)
# Edit .github/workflows/ci-rust.yml and update all `toolchain:` entries

# 2. Update Dockerfile base image
# Edit rust/Dockerfile line 2: FROM rust:1.XX-bookworm AS base

# 3. Update MSRV in cyclotron-core
# Edit rust/cyclotron-core/Cargo.toml line 5: rust-version = "1.XX.Y"
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

1. **Compatible updates** (Project → Compat): Generally safe, apply these
2. **Breaking updates** (Project → Latest crosses major version): Review changelog for:
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

The workspace intentionally does not use a `rust-toolchain.toml` file. Version management is handled through:

- CI workflow for builds and tests
- Dockerfile for production images
- Developer discretion for local development

This approach provides flexibility while ensuring CI consistency.

## Quick Reference

```sh
cd rust

# 1. Check current stable Rust version
rustup check

# 2. Update sync points (manual edits):
#    - .github/workflows/ci-rust.yml (lines 73, 162, 255)
#    - rust/Dockerfile (line 2)
#    - rust/cyclotron-core/Cargo.toml (line 5)

# 3. Verify toolchain compatibility
cargo check --all

# 4. Update lockfile with compatible versions (semver)
cargo update

# 5. Verify after lockfile update
cargo check --all

# 6. Check for outdated dependencies (breaking updates)
cargo outdated --root-deps-only

# 7. Edit Cargo.toml for any breaking updates, then:
cargo update -p <package1> -p <package2>

# 8. Full verification
cargo build --all --locked --release
cargo test --all
cargo fmt --check
cargo clippy --all-targets --all-features -- -D warnings
cargo shear

# 9. Verify Docker build
docker build -t posthog-rust-test .

# 10. Commit and create PR
git add -A
git commit -m "chore(rust): update rust to 1.XX.Y and refresh dependencies"
```
