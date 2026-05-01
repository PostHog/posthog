# personhog-replica

## Test conventions

- **Prefer parameterized tests.** When testing multiple variations of the same behavior (e.g. different batch sizes, empty vs non-empty inputs, boundary conditions), use a parameterized approach with `rstest` or a loop over test cases rather than writing separate test functions for each variation.
- Storage tests go in `tests/storage_tests.rs`, service tests in `tests/service_tests.rs`.
- Mock traits live in `src/service/tests/mocks.rs`.
