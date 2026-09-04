# personhog-router

## Test conventions

- **Prefer parameterized tests.** When testing multiple variations of the same behavior, use a parameterized approach with `rstest` or a loop over test cases rather than writing separate test functions for each variation.
- Integration tests go in `tests/`. Shared helpers live in `tests/common/mod.rs` — they start real in-process gRPC test servers (`TestReplicaService`, `TestLeaderService`), not mock traits.
