# cymbal-repositories

Concrete Postgres, Redis, and PostHog side-effect boundaries plus repository-facing DTOs.

Edit this package when changing issue persistence, fingerprint lookup, Redis-backed state, team lookup, or PostHog capture hooks. Preserve tenant scoping on all queries.

Validate from `rust/cymbal`:

```sh
cargo test --manifest-path ../Cargo.toml -p cymbal-repositories
```
