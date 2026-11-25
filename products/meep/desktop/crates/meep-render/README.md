# meep-render

Copy this directory into your macOS project and add the path dependency below. It includes the script engine, workflow interpreter, fonts and marks supplied by the packages, and the patched GPUI family. Build with the Rust and Xcode toolchains used for GPUI.

```toml
[dependencies]
meep-render = { path = "meep-render" }
```

Use `meep_render::gpui_kit` to open your window, call `meep_render::init` once on the app, and pass the source and a `ViewContext` to `meep_render::mount`. Implement `ViewHost::request` to expose the operations your script can use. The example mounts a counter and services its asynchronous increment entirely in memory.

```sh
cargo run --example counter
cargo test --features ui-tests --test embedded
```

The default feature enables the full surface. The `widgets` feature with defaults disabled exposes the design system without a JavaScript engine. Copy `meep-script/` alone for native validation or `meep-workflows/` alone for a headless workflow runner. The wasm backend is intended for trusted preview content.
