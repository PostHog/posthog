
# Testing

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