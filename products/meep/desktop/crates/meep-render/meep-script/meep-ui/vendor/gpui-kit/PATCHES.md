GPUI Kit 0.9.0, from crates.io (Apache-2.0).

Only Cargo.toml changes behavior: `default-features = false` on the
`gpui-pre-platform` and `gpui-pre-web` dependencies. The preview calls
`single_threaded_web`; enabling the defaults pulled in nightly `wasm_thread`
even for this path. Native feature selections are preserved. No Rust source
changes. Packaged test entries are omitted; the app's native gate tests the
facade with the vendored GPUI patches.

`upstream-profiler` enables frame profiling on View's GPUI backend. It avoids
resolving GPUI Fast, which pins a different patch release of Taffy.
