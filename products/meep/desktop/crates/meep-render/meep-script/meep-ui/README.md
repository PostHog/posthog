# meep-ui

Copy this directory into your Rust project. The default features provide GPUI layout, typography, navigation, forms, motion, composer surfaces and settings components. The crate re-exports the GPUI kit its components use.

```toml
[dependencies]
meep-ui = { path = "meep-ui" }
```

```rust
use meep_ui::{components, gpui_kit::*, settings};

fn preferences() -> Div {
    components::column().child(settings::note("Changes are saved on this device."))
}
```

Initialize the toolkit once with `meep_ui::gpui_kit::init(cx)`. A host supplies its own window, input models, callbacks and persistence. In an existing GPUI Kit application, use `meep_ui::gpui_kit` for compatible entity and element types.

For a headless consumer, set `default-features = false`. The `theme` and `design` modules then expose the palette and serializable design tokens independently of GPUI. Apply tokens with `design::set` on the rendering thread. Store and restore them through your application's settings backend.
