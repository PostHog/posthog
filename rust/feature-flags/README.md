
# Testing

First, make sure docker compose is running (from main posthog repo), and test database exists:

```sh
docker compose -f ../docker-compose.dev.yml up -d
```

```sh
TEST=1 python manage.py setup_test_environment --only-postgres
```

We only need to run the above once, when the test database is created.

TODO: Would be nice to make the above automatic.

Then, run the tests:

```sh
cargo test --package feature-flags
```

## To watch changes

```sh
brew install cargo-watch
```

and then run:

```sh
cargo watch -x test --package feature-flags
```

To run a specific test:

```sh
cargo watch -x "test --package feature-flags --lib -- property_matching::tests::test_match_properties_math_operators --exact --show-output"
```

# Running

```sh
RUST_LOG=debug cargo run --bin feature-flags
```

# Format code

```sh
cargo fmt --package feature-flags
```

# Trying a PR against live traffic

Members of `team-feature-flags` can comment `/pr-canary` on an approved PR authored by an active PostHog organization member to build the `feature-flags` image from the PR head and route a share of traffic to it.
The default target is `dev`. `/pr-canary help` lists the `weight=` and `env=` options.
Send a request with the `X-PostHog-Fleet: canary` header to reach the canary pods, or `X-PostHog-Fleet: stable` to skip them.
The canary stops when the PR closes, or after 48 hours.
