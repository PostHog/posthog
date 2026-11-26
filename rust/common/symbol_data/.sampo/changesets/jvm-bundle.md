---
cargo/posthog-symbol-data: minor
---

Add the `JvmBundle` type, which holds the source files of a JVM build, keyed by package path, and an optional ProGuard mapping. A bundle holds at most `MAX_JVM_BUNDLE_SOURCES` source files, and reading a larger one fails with the new `TooManyEntries` error.
