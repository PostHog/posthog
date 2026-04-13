# personhog-router

## Test conventions

- **Prefer parameterized tests.** When testing multiple variations of the same behavior, use a parameterized approach with `rstest` or a loop over test cases rather than writing separate test functions for each variation.
- Mock traits live in `src/service/tests/mocks.rs`.
- Integration tests go in `tests/`.
