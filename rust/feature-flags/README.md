
# Testing

First, make sure docker compose is running (from main posthog repo), and test database exists:

```
docker compose -f ../docker-compose.dev.yml up -d
```

```
TEST=1 python manage.py setup_test_environment --only-postgres
```

We only need to run the above once, when the test database is created.

TODO: Would be nice to make the above automatic.


Then, run the tests:

```
cargo test --package feature-flags
```

### To watch changes

```
brew install cargo-watch
```

and then run:

```
cargo watch -x test --package feature-flags
```

To run a specific test:

```
cargo watch -x "test --package feature-flags --lib -- property_matching::tests::test_match_properties_math_operators --exact --show-output"
```

# Running

```
RUST_LOG=debug cargo run --bin feature-flags
```

# Format code

```
cargo fmt --package feature-flags
```