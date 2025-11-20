.PHONY: test test-clean test-all cleanup

# Run tests
test:
	cargo test $(ARGS)

# Run tests and cleanup afterwards
test-clean:
	cargo test $(ARGS) && cargo run --bin cleanup-test-db

# Run all tests with cleanup
test-all:
	cargo test && cargo run --bin cleanup-test-db

# Just cleanup the test databases
cleanup:
	cargo run --bin cleanup-test-db

