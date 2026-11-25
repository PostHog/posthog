use gpui::{AnyElement, App, IntoElement, RenderOnce, SharedString, Styled, Window, svg};

include!(concat!(env!("OUT_DIR"), "/icon_name.rs"));

/// A named icon that resolves to a path in an application's asset source.
/// Implement this for custom icon sets accepted by GPUI Component's `Icon`.
pub trait IconNamed {
    fn path(self) -> SharedString;
}

impl IconNamed for IconName {
    fn path(self) -> SharedString {
        IconName::path(self)
    }
}

// Keep direct `.child(IconName::Search)` usable by every presentation layer.
// Explicit themed sizes and transformations belong to the consumer's Icon.
impl RenderOnce for IconName {
    fn render(self, window: &mut Window, _: &mut App) -> impl IntoElement {
        let text_style = window.text_style();
        svg()
            .path(self.path())
            .flex_shrink_0()
            .size(text_style.font_size.to_pixels(window.rem_size()))
            .text_color(text_style.color)
    }
}

impl From<IconName> for AnyElement {
    fn from(name: IconName) -> Self {
        name.into_any_element()
    }
}
