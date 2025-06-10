# Project

This project implements a link redirect service for short urls, similar to bit.ly.

# Testing

First, make sure docker compose is running (from main posthog repo), and test database exists:

```sh
docker compose -f ../docker-compose.dev.yml up -d
```

```sh
TEST=1 python manage.py setup_test_environment --only-postgres
```

To run the tests:

```sh
cargo test --package links
```

# Running

```sh
RUST_LOG=debug cargo run --bin links
```

# Format code

```sh
cargo fmt --package links
```
