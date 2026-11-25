//! GPUI Kit: one dependency for building desktop applications with GPUI.
//!
//! GPUI itself is published as a family of `gpui-pre-*` crates that move
//! together. This crate depends on the matching set for you, so an
//! application lists `gpui-kit` alone. `use gpui_kit::*;` is GPUI, and each
//! layer is reachable by name:
//!
//! | Path            | Crate             | Feature          |
//! | --------------- | ----------------- | ---------------- |
//! | `gpui_kit::*`   | `gpui`            | always           |
//! | `platform`      | `gpui_platform`   | desktop / web    |
//! | [`base`]        | `gpui-base`       | always           |
//! | [`component`]   | `gpui-component`  | `component` (on) |
//! | [`assets`]      | `gpui-kit-assets` | `assets` (on)    |
//!
//! On desktop and web, `application` opens the platform. Mobile applications
//! supply their backend to `Application::with_platform`. [`init`] initializes the enabled
//! layers:
//!
//! ```no_run
//! use gpui_kit::*;
//!
//! actions!(hello, [Quit]);
//!
//! struct Hello;
//!
//! impl Render for Hello {
//!     fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
//!         div().child("Hello, World!")
//!     }
//! }
//!
//! fn main() {
//!     gpui_kit::application().run(|cx| {
//!         gpui_kit::init(cx);
//!         gpui_kit::open_window(WindowOptions::default(), cx, |_, cx| cx.new(|_| Hello))
//!             .expect("failed to open window");
//!     });
//! }
//! ```
//!
//! Enable `gpui-fast` to select GPUI Fast for the core, platform, and enabled
//! layers without changing imports. Upstream remains the default backend.
//!
//! See [`component`] for the same program with the styled component library.

/// Defines unit actions without requiring consumers to depend on GPUI under the
/// crate name `gpui`.
///
/// GPUI's original macro spells its derive as `gpui::Action`, which does not
/// resolve when GPUI is consumed solely through this facade.
#[macro_export]
macro_rules! actions {
    ($namespace:path, [ $( $(#[$attr:meta])* $name:ident),* $(,)? ]) => {
        $(
            #[derive(
                ::std::clone::Clone,
                ::std::cmp::PartialEq,
                ::std::default::Default,
                ::std::fmt::Debug,
                $crate::Action
            )]
            #[action(namespace = $namespace)]
            $(#[$attr])*
            pub struct $name;
        )*
    };
    ([ $( $(#[$attr:meta])* $name:ident),* $(,)? ]) => {
        $(
            #[derive(
                ::std::clone::Clone,
                ::std::cmp::PartialEq,
                ::std::default::Default,
                ::std::fmt::Debug,
                $crate::Action
            )]
            $(#[$attr])*
            pub struct $name;
        )*
    };
}

// Public facade decision — 2026-09-08:
// GPUI Kit is the application-facing entry point. Users should depend on and
// import gpui-kit without needing to know which GPUI crates implement it.
// Keep GPUI APIs available through the Kit root and preserve the published
// #[gpui_kit::test] macro. Do not replace it with Rust's built-in #[test].
// A future switch to official GPUI crates is an internal dependency migration,
// not a reason to steer Kit users toward gpui:: paths or require import changes.
// Keep the existing gpui namespace re-export hidden for source compatibility;
// it is not the recommended application API. It names this crate rather than
// the GPUI crate: `gpui_kit::gpui::Window` is still GPUI's `Window` through the
// glob below, and applications can alias the Kit as `gpui`
// (`extern crate gpui_kit as gpui;`) so GPUI macro output resolves through the
// Kit whichever GPUI it is built on. Pointing this at the GPUI crate would make
// that alias ambiguous (E0659) wherever `gpui_kit::*` is glob-imported.
//
// With test-support, the glob below includes GPUI's test macro. Test modules
// should import their Kit types explicitly to avoid shadowing Rust's #[test].
#[cfg(not(feature = "gpui-fast"))]
pub use ::gpui::*;
#[cfg(feature = "gpui-fast")]
pub use ::gpui_fast::*;

// Preserve Kit-aware macro paths when the engine is Fast.
#[cfg(all(feature = "gpui-fast", any(feature = "inspector", debug_assertions)))]
pub use gpui_macros::derive_inspector_reflection;
#[cfg(feature = "gpui-fast")]
pub use gpui_macros::{
    Action, AppContext, IntoElement, Render, VisualContext, bench, border_style_methods,
    box_shadow_style_methods, cursor_style_methods, margin_style_methods, overflow_style_methods,
    padding_style_methods, position_style_methods, property_test, register_action, style_helpers,
    test, visibility_style_methods,
};

#[doc(hidden)]
pub use crate as gpui;

/// Whether this build selected GPUI Fast. Crates layered on the Kit that keep
/// a backend feature of their own check it at compile time to stay in step.
#[doc(hidden)]
pub const GPUI_FAST: bool = cfg!(feature = "gpui-fast");

/// UI integration testing: render real components in headless windows, dispatch
/// pointer and keyboard events, and assert state, focus, layout and callbacks.
/// Run tests with `#[gpui_kit::test]`; use this module to interact with their UI.
#[cfg(feature = "test-support")]
pub mod test;

pub use ::gpui_base as base;
#[cfg(all(
    not(any(target_os = "ios", target_os = "android")),
    feature = "gpui-fast"
))]
pub use ::gpui_fast_platform as platform;
#[cfg(all(target_family = "wasm", feature = "gpui-fast"))]
pub use ::gpui_fast_web as web;
#[cfg(all(
    not(any(target_os = "ios", target_os = "android")),
    not(feature = "gpui-fast")
))]
pub use ::gpui_platform as platform;
#[cfg(all(target_family = "wasm", not(feature = "gpui-fast")))]
pub use ::gpui_web as web;
pub use gpui_base::is_mobile;

/// The styled component library.
///
/// ```no_run
/// use gpui_kit::component::button::*;
/// use gpui_kit::*;
///
/// struct Hello;
///
/// impl Render for Hello {
///     fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
///         div().child(Button::new("ok").primary().label("Let's Go!"))
///     }
/// }
///
/// fn main() {
///     gpui_kit::application().run(|cx| {
///         gpui_kit::init(cx);
///         gpui_kit::open_window(WindowOptions::default(), cx, |_, cx| cx.new(|_| Hello))
///             .expect("failed to open window");
///     });
/// }
/// ```
#[cfg(feature = "component")]
pub use ::gpui_component as component;

#[cfg(feature = "assets")]
pub use ::gpui_kit_assets as assets;

/// Open a window with a Base Root and return the window and application content.
/// Applications own quit/close actions and confirmation flows.
/// Call [`init`] before opening application windows.
/// The builder returns application content, not another Root.
///
/// In an async context, call this inside `cx.update`.
pub fn open_window<V: Render>(
    options: WindowOptions,
    cx: &mut App,
    build: impl FnOnce(&mut Window, &mut App) -> Entity<V>,
) -> Result<(AnyWindowHandle, Entity<V>)> {
    let mut built = None;
    let window = cx.open_window(options, |window, cx| {
        let view = build(window, cx);
        built = Some(view.clone());
        cx.new(|cx| base::Root::new(view, window, cx))
    })?;
    Ok((
        window.into(),
        built.expect("open_window ran its build closure"),
    ))
}

// Mobile applications provide their platform with `Application::with_platform`.
#[cfg(not(any(target_os = "ios", target_os = "android")))]
pub use platform::application;

/// Initializes every enabled layer. Call it once, before using anything else.
///
/// With the `component` feature (on by default) this is
/// `gpui_component::init`, which also initializes `gpui-base`; otherwise it
/// is `gpui_base::init`.
pub fn init(cx: &mut App) {
    #[cfg(feature = "component")]
    gpui_component::init(cx);
    #[cfg(not(feature = "component"))]
    gpui_base::init(cx);
}

/// Fluent UI test observation, inert unless `test-support` is enabled.
pub use gpui_base::TestSupportExt;
