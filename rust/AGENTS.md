# Rust crates

## Metrics labels

When emitting metrics via the `metrics` crate (`histogram!`, `counter!`, `gauge!`), dynamic label values (method names, client names, etc.) must use `Arc<str>`, never `String` or `.to_string()`.

- Construct an `Arc<str>` once at the top of the function (`Arc::from(value)`) and `.clone()` it into each macro call. `Arc::clone` is a single atomic increment — no heap allocation.
- `current_client_name()` already returns `Arc<str>`, so use `.clone()` directly. Never call `.to_string()` on it.
- When passing a dynamic label through multiple functions, pass `Arc<str>` by value, not `&str` — the downstream function will need to clone it into macros anyway.
- Static label values (`"ok"`, `"error"`, `"unavailable"`) can be passed as `&'static str` literals directly.
