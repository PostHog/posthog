# hog-rs

PostHog Rust service monorepo. This is *not* the Rust client library for PostHog.

### Requirements

1. [Rust](https://www.rust-lang.org/tools/install).
1. [Docker](https://docs.docker.com/engine/install/), or [podman](https://podman.io/docs/installation) and [podman-compose](https://github.com/containers/podman-compose#installation): To setup development stack.
1. `sqlx-cli` - this is *optional to use* if your project interacts with a database (unit tests etc.) that you'd like to manange with `sqlx`. It is installed for you either way locally and in CI by `posthog/rust/bin/migrate_tests` if it's missing.

### Testing

1. Start development stack:
```bash
# from posthog repo root
> docker compose -f docker-compose.dev.yml up -d --wait
> bin/migrate
```

2. Test:

```bash
# from posthog repo root (if you haven't already)
> docker compose -f docker-compose.dev.yml up -d --wait

# from posthog/rust (Rust workspace root)

# Bootstrap the test environment (required to run tests!)
> bin/migrate_tests

# Run an individual workspace subproject's test suite
# Note: see `cargo test --help` to filter to specific modules or unit tests
> RUST_BACKTRACE=1 cargo test -p <SUBPROJECT_NAME>

# Run the full test suite for all workspace projects (CI does this)
> bin/run_workspace_tests
```

**Note** this does all of the following:
1. Sources the `.env` file to establish a *test-scoped* `DATABASE_URL` for all subprojects that use `sqlx` or don't depend on Postgres
1. Creates and migrates the consolidated test database for all Rust workspace services (except `feature-flags`)
1. Runs `posthog` repo root `manage.py setup_test_environment` to bootstrap Django-managed DB for `feature-flags` service
1. Installs `sqlx-cli` at pinned version if missing
1. Runs an `sqlx`-managed DB migration for every Rust workspace service that depends on `sqlx`
1. Refreshes the `sqlx` query cache required by all `sqlx::query*` macros, updating the cache at `posthog/rust/.sqlx`
1. Runs the full-workspace test suite on a capped thread pool to avoid Docker resource saturation


## Rust Workspace Local Dev, Test, and CI components

* `posthog/docker-compose.dev.yml`: the single, unified Docker Compose environment used by `posthog` and Rust workspace projects
* `bin/migrate`
    * Runs the Django `setup_test_environment` automation for Rust projects that share the `posthog` and `test_posthog` databases
    * Runs individual DB creation + migrations for Rust subprojects that manage their own isolated databases in production
        * Currently, this is `cyclotron-*` and (soon) `property-defs-rs`
* `posthog/rust/.env`
    * Sourced by automation including `cargo` and `sqlx` as well as `posthog/rust/bin` scripts
    * Sets up a **test scoped** unified database namespace on the `posthog` Docker Compose Postgres instance `postgres-db-1`
    * Must be **overridden in your local env** to work directly with isolated DBs/namespaces outside of test scope
    * Can also be overridden (see `posthog/rust/bin` scripts for details) in use by `cargo` and `sqlx` commands using `-D <DB_URL>`
* `posthog/rust/.cargo/config.toml`
    * Sets up `SQLX_OFFLINE=true` (offline query caching) by default with `cargo` and `sqlx` tools
* `posthog/rust/bin/update_sqlx_query_cache`
    * Depends on and executed by `bin/migrate_tests`
    * Can be run directly in local dev _if_ `bin/migrate_tests` has already run successfully
* `posthog/rust/bin/migrate_tests`
    * Runs the Django `setup_test_environment` automation for Rust projects that share the `posthog` and `test_posthog` databases
    * Runs all `migrtations` and `test_migrations` against `rust_test_database` DB namespace, for all `sqlx`-dependent workspace subprojects
    * Runs `cargo sqlx prepare` for the entire workspace, curating a unified query cache at `posthog/rust/.sqlx`
* `posthog/plugin-server/package.json`
    * Manages running the `posthog/rust/cyclotron-*` service and bootstrapping its isolated DB for local dev
    * Cyclotron is a library and set of support services wrapped by a NodeJS API for use in the Node `plugin-server` deployments
* `posthog/rust/bin/run_workspace_tests`
    * Runs `bin/migrate_tests`
    * Runs `cargo test` at the workspace level for all subprojects
* `posthog/.github/workspaces/ci-rust.yml`
    * Runs a single workspace-wide test prep and suite
    * Utilizes `bin/run_workspace_tests` in CI as in local dev and unit testing
* `posthog/.github/workspaces/ci-hobby.yml`
    * Deploys the "Hobby" (FOSS) bootstrap of `posthog` in a Droplet
    * Attempts to sanity check the deployment is successful and live
    * Gates CI success for `posthog` repo PRs
* `posthog/bin/hobby-ci.py`
    * Utility script used by `ci-hobby.yml` GitHub Action

### Updating the SQLX query cache
This is required when making changes to any production (dev) or test-scoped queries managed using `sqlx::query*` macros in Rust code. If you see fail messages during test runs referring to `SQLX_OFFLINE` then you need to update the query cache locally.

```
# From the `posthog` directory
> docker compose -f docker-compose.dev.yml up -d --wait

# From the `posthog/rust` directory
> bin/migrate_tests

# If you've already done the above and are in mid-dev-loop, you can just run:
> bin/update_sqlx_query_cache

# If ^ this fails, fix the query syntax or code errors it surfaces

# If it succeeds, check in the changes at `posthog/rust/.sqlx` with your PR
```

## Rust Workspace

The Rust workspace and subprojects diverge in how they manage their development, test, and CI lifecycles. In order to consolidate and automate management of these environments, these differences had to be taken into account. This motivated some special-case handling in the new `posthog/rust/bin/` scripts and related repo root automation `posthog/bin/migrate` and related CI Actions and scripts they call.

I'll attempt to provide some brief context on this below:

#### The subprojects dev/test divergences
The subprojects in the workspace fall into several categories:

* Projects that don't depend on a Postgres database
* Those that depend on [sqlx](https://github.com/launchbadge/sqlx) and [sqlx-cli](https://github.com/launchbadge/sqlx/blob/main/sqlx-cli/README.md) to manage the DB
   * Some of these rely on tables that currently exist in the `posthog` (Django-managed) DB in dev/test, and could be refactored to behave as `feature-flags` project does
   * Some of these rely on isolated, self-managed database instances in production and local dev, but in order to depend on `sqlx` at the workspace level, must apply migrations into a shared test-scoped DB namespace when executing test suites in local dev or CI
* Those that depend on the `posthog` (Django-managed) database and internal scripting to manage the DB
   * Currently, the `feature-flags` subproject is the most mature example of this approach

#### SQLX is useful but opinionated
`sqlx` provides a lot of useful features for projects that depend on it:
* Provides query-construction macros that cache metadata offline to ensure proper SQL syntax and placeholders at compile time
* Provides strong serialization integration with existing Rust frameworks for hydrating and persisting complex data types
* Provides `sqlx::test` annotations that automate per-test database isolation and migration services to enable parallel test execution

However, `sqlx` has some prickly points too:
* `cargo sqlx prepare --workspace` requires that all tables referenced in `sqlx::query*` macros are created and exist on the same database
* `sqlx::test` requires a single `DATABASE_URL` (and therefore Postgres DB namespace) to be shared when running tests from the workspace level

These friction points inform the choices and special cases in the `posthog/rust/bin` automation scripts.


## Rust Subprojects
TODO: write up a brief intro for all of them.

### capture

This is a rewrite of [capture.py](https://github.com/PostHog/posthog/blob/master/posthog/api/capture.py), in Rust.

#### Why?

Capture is very simple. It takes some JSON, checks a key in Redis, and then pushes onto Kafka. It's mostly IO bound.

We currently use far too much compute to run this service, and it could be more efficient. This effort should not take too long to complete, but should massively reduce our CPU usage - and therefore spend.

#### How?

I'm trying to ensure the rewrite at least vaguely resembles the Python version. This will both minimize accidental regressions, but also serve as a "rosetta stone" for engineers at PostHog who have not written Rust before.

### rusty-hook
A reliable and performant webhook system for PostHog

### property-defs-rs
Consumes the `clickhouse_events_json` (post-processed events) topic, scanning for new event definitions and properties. Attempts to classify the value type of each property and update the `posthog_propertydefinition`, `posthog_eventproperty`, and `posthog_eventdefinition` tables accordingly.

This data is queried by the Django taxonomy API to display event property types and metadata used in filter and query building in the product. 

### feature-flags
Manages PostHog Feature Flags. **IMPORTANT** this project does not rely on `sqlx` for database management. It utilizes the `posthog` (Django-managed) database setup `manage.py setup_test_environment` and it's own internal project scripts to handle local dev and test flows. It *does* share the `posthog` (repo root) Docker Compose with the rest of the Rust workspace, and utilizes the same common `posthog/rust/bin` database and test suite management scripts, which are special-cased in places to accommodate it.

See the `posthog/rust/feature-flags/README.md` for details.

If you're starting a new Rust project and do not intend to depend on `sqlx`, this 

### hook-\*
Various libraries and services that manage PostHog webhooks

### cymbal
Manages ingest for the PostHog Error Tracking.

