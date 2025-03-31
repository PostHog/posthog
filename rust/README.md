# hog-rs

PostHog Rust service monorepo. This is *not* the Rust client library for PostHog.

## Requirements

1. [Rust](https://www.rust-lang.org/tools/install).
1. [Docker](https://docs.docker.com/engine/install/), or [podman](https://podman.io/docs/installation) and [podman-compose](https://github.com/containers/podman-compose#installation): To setup development stack.
1. [sqlx](https://github.com/launchbadge/sqlx) and [sqlx-cli](https://github.com/launchbadge/sqlx/blob/main/sqlx-cli/README.md) - this is *optional to use* if your project interacts with a database (unit tests etc.) that you'd like to manage with `sqlx`. It is installed for you either way locally and in CI by `posthog/rust/bin/migrate_tests` if it's missing.

### Local Dev
Generally not needed for Rust projects in local, since the default `DATABASE_URL` and test suites run against test-scoped Docker Compose and DB namespaces. However, if you want to code "live" against isolated DB namespaces + the `posthog` local dev DB, you can override `DATABASE_URL` as set in the `rust/.env` file and do so this way:

1. Start development stack:
```bash
# from posthog repo root
> docker compose -f docker-compose.dev.yml up -d --wait
> bin/migrate
```

### Testing (local and CI)
This is the typical flow for working locally and running test suites. CI now behaves very similarly using the same scripts/automation.

```bash
# from posthog repo root (if you haven't already)
> docker compose -f docker-compose.dev.yml up -d --wait

# from posthog/rust (Rust workspace root)

# Run an individual workspace subproject's test suite
> bin/migrate_tests
> RUST_BACKTRACE=1 cargo test -p <SUBPROJECT_NAME>

# Run the test migrations and test suites for all workspace projects (CI does this)
> bin/run_workspace_tests
```

## Rust Workspace Local Dev, Test, and CI components
The Rust workspace dev/test/CI environment has a bunch of moving parts. Here's a brief intro to orient you on all of them:

* `posthog/docker-compose.dev.yml`: the single, unified Docker Compose environment used by `posthog` and Rust workspace projects
* `posthog/bin/migrate`
    * Bootstraps and migrates the `posthog` (repo root) database for local development
    * Executes `posthog/rust/bin/migrate` to bootstrap DB namespaces in local dev for Rust services that depend on an _isolated Postgres instance in production_
* /posthog/rust/bin/migrate`
    * Bootstraps and migrates isolated DB namespaces for local dev (*not* tests/CI) for Rust services that depend on an isolated Postgres instance in production
        * Currently, this is `cyclotron-*` and (soon) `property-defs-rs`
* `posthog/plugin-server/package.json`
    * Manages running the `posthog/rust/cyclotron-*` service and bootstrapping its isolated DB for local dev
    * Cyclotron is a library and set of support services wrapped by a NodeJS API for use in the Node `plugin-server` deployments
* `posthog/rust/.sqlx/`
    * Single unified query cache for all `sqlx`-dependent Rust workspace subprojects
    * Must be updated when queries constructed by `sqlx::query*` macros change and checked into your PR
* `posthog/rust/.env`
    * Sourced by automation including `cargo` and `sqlx` as well as `posthog/rust/bin` scripts
    * Sets up a **test scoped** unified database namespace on the `posthog` Docker Compose Postgres instance `postgres-db-1`
    * Must be **overridden in your local env** to work directly with isolated DBs/namespaces outside of test scope
    * Can be overridden when executing `cargo` and `sqlx` commands directly, using `-D <DB_URL>`
* `posthog/rust/.cargo/config.toml`
    * Sets up `SQLX_OFFLINE=true` (offline query caching) by default with `cargo` and `sqlx` tools
* `posthog/rust/bin/update_sqlx_query_cache`
    * Runs `cargo sqlx prepare` for the entire workspace, curating a unified query cache at `posthog/rust/.sqlx`
    * Can be run directly in local dev _if_ `bin/migrate_tests` has already run successfully
* `posthog/rust/bin/migrate_tests`
    * Sources the current test DB namespace and URL from `posthog/rust/.env`
    * Runs the Django `setup_test_environment` automation for Rust projects that share the `posthog` and `test_posthog` databases
    * Runs all Rust workspace migrations against single shared `rust_test_database` DB namespace
        * :point_up: this is required to curate single query cache for all `sqlx`-dependent subprojects
    * Executes `bin/update_sqlx_query_cache`
* `posthog/rust/bin/run_workspace_tests`
    * Runs `bin/migrate_tests`
    * Runs `cargo test` at the workspace level for all subprojects
* `posthog/.github/workspaces/ci-rust.yml`
    * Runs a single workspace-wide test prep and suite
    * Utilizes `bin/run_workspace_tests` in CI as in local dev and unit testing

### Updating the SQLX query cache
This is required when making changes to any production (dev) or test-scoped queries managed using `sqlx::query*` macros in Rust code. If you see fail messages during test runs referring to `SQLX_OFFLINE` then you need to update the query cache locally.

```
# From the `posthog` directory
> docker compose -f docker-compose.dev.yml up -d --wait

# From the `posthog/rust` directory - also runs SQLX cache update
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

However, `sqlx` has some prickly points that we must accommodate:
* `cargo sqlx prepare --workspace` requires that all tables referenced in `sqlx::query*` macros are created and exist on the same database
* `sqlx::test` requires a single `DATABASE_URL` (and therefore Postgres DB namespace) to be shared when running tests from the workspace level

These friction points inform the choices and special cases in the `posthog/rust/bin` automation scripts.


## Rust Subprojects
TODO: write up a brief intro for all of them.

### capture

This is a rewrite of [capture.py](https://github.com/PostHog/posthog/blob/master/posthog/api/capture.py), in Rust.

_TODO: complete the transition from legacy `capture` implementations into the Rust version hosted here._

### common
Shared boilerplate code (metrics publishing, k8s health endpoints, kafka client wrappers, etc.) that many of the other subprojects depend on.

### property-defs-rs
Consumes the `clickhouse_events_json` (post-processed events) topic, scanning for new event definitions and properties. Attempts to classify the value type of each property and update the `posthog_propertydefinition`, `posthog_eventproperty`, and `posthog_eventdefinition` tables accordingly.

This data is queried by the Django taxonomy API to display event property types and metadata used in filter and query building in the product.

### feature-flags
Manages PostHog Feature Flags. **IMPORTANT** this project does not rely on `sqlx` for database management. It utilizes the `posthog` (Django-managed) database setup `manage.py setup_test_environment` and it's own internal project scripts to handle local dev and test flows. It *does* share the `posthog` (repo root) Docker Compose with the rest of the Rust workspace, and utilizes the same common `posthog/rust/bin` database and test suite management scripts, which are special-cased in places to accommodate it.

See the `posthog/rust/feature-flags/README.md` for details.

If you're starting a new Rust project and do not intend to depend on `sqlx`, this project is a good template to start with.

### hook-\*
Various libraries and services that manage PostHog webhooks

### cymbal
Manages ingest for the PostHog Error Tracking.


## Adding a new subproject to the Rust workspace
Start out by `cd`ing into the `posthog/rust` workspace root directory. Use `cargo` to initialize your new project as [documented here](https://doc.rust-lang.org/book/ch14-03-cargo-workspaces.html#creating-the-second-package-in-the-workspace).

As noted above, there are 3 flavors of workspace project at the moment you can choose as templates for your new project. The bootstrap process for each is listed below:

#### Project with no DB dependencies
Just start coding! Your decision isn't permanent - you can easily adapt in flight to an `SQLX`-dependent project or not in the future. The only dependency you'll need right off the bat is to have the `posthog` Docker Compose rig up and running in local dev, and to code against those (non-DB!) backing stores if you require them.

You can execute `bin/run_workspace_tests` as well as linting checks documented in `ci-rust.yml` locally just as CI will do when a PR is submitted.

#### Project depends on Postgres + SQLX
In your subproject directory root (`posthog/rust/<YOUR_SUBPROJECT>`) you'll need to set up a bit of boilerplate depending on how your new project will be deployed in production.

* If the project _will manage it's own isolated database instance in prod_ you should:
    1. Create a `migrations` subdirectory in your subproject root
    1. Use `sqlx migrate add ...` to create migrations and add your table schemas to it
    1. When writing tests, annotate each `fn test_*` with `sqlx::test(migrations = "<PATH>")` where `PATH` points to your `migrations` directory
    1. Add an `sqlx migrate run ...` clause to `bin/migrate` and `bin/migrate_tests` where `--source` points to your `migrations` directory
    1. Execute `bin/migrate_tests` and/or `bin/migrate` when making changes to SQL wrapped by `sqlx::query*` macros

* If the project _will not manage its own DB in production_:
    1. Verify that existing migrations (see `bin/migrate_test`) don't already cover the tables your queries will referece. If so, you're done! :tada:
    1. If not, create a `tests/test_migrations` subdirectory in your subproject root
    1. `cd` into `tests` and `sqlx migrate add ...` to create migrations and add the missing table schemas to it
    1. When writing tests, annotate each `fn test_*` with `sqlx::test(migrations = "<PATH>")` where `PATH` points to your `test_migrations` directory
    1. Add an `sqlx migrate run ...` clause to `bin/migrate` and `bin/migrate_tests` where `--source` points to your `test_migrations` directory
    1. Execute `bin/migrate_tests` and/or `bin/migrate` when making changes to SQL wrapped by `sqlx::query*` macros

#### Project depends on a database but not SQLX
Here, the `feature-flags` project will be a good template for you. You'll need to manage things like test and dev migrations manually, including isolating DB namespaces per test case to avoid parallel test executions interfering with each other.

Otherwise, as `feature-flags` does, use the repo root (`posthog`) Docker Compose to code and test against, and all the same `posthog/rust/bin` dev/test/CI scripts as described above to manage environment, testing, and DB lifecycle.