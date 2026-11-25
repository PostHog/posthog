//! Shared semantic palette, typography and native GPUI components.
#[cfg(feature = "components")]
pub mod agent_marks;
#[cfg(feature = "components")]
pub mod appearance;
#[cfg(feature = "components")]
pub mod components;
#[cfg(feature = "components")]
pub mod composer;
#[cfg(feature = "components")]
pub mod controls;
pub mod design;
pub mod palettes;
#[cfg(feature = "components")]
pub mod settings;
pub mod theme;
#[cfg(feature = "components")]
pub use gpui_kit;
