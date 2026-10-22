# Rust crates

## Metrics labels

When emitting metrics via the `metrics` crate (`histogram!`, `counter!`, `gauge!`), dynamic label values (method names, client names, etc.) must use `Arc<str>`, never `String` or `.to_string()`.

- Construct an `Arc<str>` once at the top of the function (`Arc::from(value)`) and `.clone()` it into each macro call. `Arc::clone` is a single atomic increment — no heap allocation.
- `current_client_name()` already returns `Arc<str>`, so use `.clone()` directly. Never call `.to_string()` on it.
- When passing a dynamic label through multiple functions, pass `Arc<str>` by value, not `&str` — the downstream function will need to clone it into macros anyway.
- Static label values (`"ok"`, `"error"`, `"unavailable"`) can be passed as `&'static str` literals directly.

## personhog

- **A change to the publish outbox contract between `personhog-identity` and `personhog-publisher` lands in the publisher first, in its own PR, and in identity in a later PR.** The two are separate deployments with no ordering between them. The contract (the outbox row shapes, the `lifecycle_op_person.moved` entries, the pointer cursor, the GC guard) is listed under "Publish outbox contract" in [personhog-identity/README.md](personhog-identity/README.md). Read it before you change `rust/personhog-identity/src/publish/`, the outbox writers in `src/lifecycle/` and `src/storage/`, or a persons migration that touches the outbox or `lifecycle_op_person`.

## Container images

A pull request builds no Rust image unless it carries a `smoke_test:<image>` label (one image) or `smoke_test` (all images).
`ci-rust.yml` compiles every affected crate, so a code change needs no image build.
Add a label when the change can break the image build but not `cargo build`: a new binary or image entry, a `build.rs` or system dependency change, a new workspace crate, or a Dockerfile edit.
Add one too when the PR needs a deployable image.
Master builds and deploys after merge, and a broken image stops that deploy.
