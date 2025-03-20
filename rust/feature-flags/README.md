
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
