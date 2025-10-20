# PostHog Rust Workspace

The `posthog/rust` directory serves as PostHog's "Rust monorepo" hosting Rust libraries and service implementations. This is *not* the Rust client library for PostHog.

## Catalog

Some selected examples of subprojects homed in the Rust workspace.

### capture

This is the microservice that receives HTTP event capture requests and extracts the event payloads, lightly preprocesses the events, and passes well-formed events along as Kafka messages for downstream validation, CDP processing, and ingestion into Postgres and ClickHouse.

### feature-flags

The new feature flags backend service that handles flag-scoped PostHog API requests. Currently, `/flags` endpoint is natively supported, and legacy `/decide` traffic is gradually being shifted to the Rust service.

### cymbal

Processing inbound source map payloads into symbols for the PostHog error tracking product.

### property-defs-rs

Extracts event and property definitions from the post-processed event stream and infers data types for the same. Stores these in Postgres for use in event/property lookup widgets in the PostHog product UI.

This service has some known data quality issues that are being addressed by a re-architecture effort. That effort may result in a change of role or even decomissioning of this service in the near future.

### batch-import-worker

Backend service that handles PostHog user requests to import bulk datasets from external sources (S3, Amplitude, Segment, etc.)

### kafka-deduplicator

PoC service that will deduplicate events in the ingestion pipeline within a given time window.

### cyclotron

Rust services to manage a job queuing service backed by Postgres. Includes NodeJS API bindings and backend state management functionality.

### hogvm

A Rust re-implementation of the HogVM stack machine for evaluating compiled HogQL bytecode.

### rusty-hook

Rust based webhook management services. Includes `hook-api`, `hook-common`, `hook-janitor`, and `hook-worker`.

### common

Miscellaneous internal Rust libraries reused by service implementations.

## Requirements

1. [Rust](https://www.rust-lang.org/tools/install).
2. [Docker](https://docs.docker.com/engine/install/), or [podman](https://podman.io/docs/installation) and [podman-compose](https://github.com/containers/podman-compose#installation): To setup development stack.

Other useful links for those new to Rust:

* [The Rust Programming Language](https://doc.rust-lang.org/book/index.html)
* [Cargo manual](https://doc.rust-lang.org/cargo/)
* [The "Rustonomicon"](https://doc.rust-lang.org/nomicon/)
* [crates.io](https://crates.io/)

## Local Development

Start up and bootstrap the "top-level" `posthog` repo dev environment, including the Docker-Compose support services. Ensure that `bin/migrate` has run and `bin/start` behaves as expected. Leave the Docker services running when developing in the Rust workspace. The `bin/start` processes are typically optional for running Rust tests or the inner dev loop.

You may optionally seed data using the "top-level" management console scripts:

```bash
# from repo root
$ ./manage.py generate_demo_data
$ ./manage.py setup_test_environment
```

```bash
# run tests for all workspace projects
$ cd rust
$ cargo test
```

Migrations for most Rust workspace subprojects are managed by the [sqlx](https://github.com/launchbadge/sqlx) tool. When running `cargo` or `sqlx` commands from within the `posthog/rust` workspace root directory, the top-level `posthog` Docker Compose database is targeted as specified in the `DATABASE_URL` env var injected by the `rust/.env` file.
