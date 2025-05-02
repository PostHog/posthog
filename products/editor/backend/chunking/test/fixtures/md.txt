# hog-rs

PostHog Rust service monorepo. This is *not* the Rust client library for PostHog.

## capture

This is a rewrite of [capture.py](https://github.com/PostHog/posthog/blob/master/posthog/api/capture.py), in Rust.

### Why?

Capture is very simple. It takes some JSON, checks a key in Redis, and then pushes onto Kafka. It's mostly IO bound.

We currently use far too much compute to run this service, and it could be more efficient. This effort should not take too long to complete, but should massively reduce our CPU usage - and therefore spend.

### How?

I'm trying to ensure the rewrite at least vaguely resembles the Python version. This will both minimize accidental regressions, but also serve as a "rosetta stone" for engineers at PostHog who have not written Rust before.

## rusty-hook
A reliable and performant webhook system for PostHog

### Requirements

1. [Rust](https://www.rust-lang.org/tools/install).
2. [Docker](https://docs.docker.com/engine/install/), or [podman](https://podman.io/docs/installation) and [podman-compose](https://github.com/containers/podman-compose#installation): To setup development stack.

### Testing

1. Start development stack:
```bash
docker compose -f docker-compose.yml up -d --wait
```

2. Test:
```bash
# Note that tests require a DATABASE_URL environment variable to be set, e.g.:
# export DATABASE_URL=postgres://posthog:posthog@localhost:15432/test_database
# But there is an .env file in the project root that should be used automatically.
cargo test
```
