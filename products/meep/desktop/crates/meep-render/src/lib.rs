//! The host's GPUI design system and view contract. Script views render
//! through these blocks; nothing is loaded as a separate module.
#[cfg(feature = "widgets")]
pub mod brands;
pub use meep_script::design;
pub mod emoji;
pub use meep_workflows::{FailureKind, HostError};
pub mod icons;
pub use meep_script::links;

#[cfg(feature = "ui")]
pub mod sdk;

#[cfg(feature = "widgets")]
pub use gpui_kit;
pub use meep_script::theme;
#[cfg(feature = "widgets")]
pub use meep_ui::components as ui;
pub use serde_json;

#[cfg(all(feature = "ui", not(target_family = "wasm")))]
use meep_script::script;
pub use meep_script::{datasets, scene, script_contract, script_engine};
#[cfg(all(feature = "ui", target_family = "wasm"))]
mod script {
    pub use meep_script::browser::*;
    pub use meep_script::script_contract::*;
}
#[cfg(feature = "ui")]
pub mod block_editor;
pub mod image_source;
#[cfg(feature = "ui")]
mod script_motion;
#[cfg(feature = "ui")]
pub mod script_view;

#[cfg(all(feature = "ui", not(target_family = "wasm")))]
pub use script_view::mount;

/// Initialize the toolkit and register the script surface's keyboard bindings.
#[cfg(feature = "ui")]
pub fn init(cx: &mut gpui_kit::App) {
    gpui_kit::init(cx);
    script_view::bind_keys(cx);
    block_editor::bind_keys(cx);
}
