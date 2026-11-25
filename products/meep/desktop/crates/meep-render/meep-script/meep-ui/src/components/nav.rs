//! Source-list geometry and buttons shared by the native shell and web preview.
use gpui_kit::assets::IconName as Glyph;
use gpui_kit::component::{
    Icon, Sizable,
    button::{Button, ButtonVariants},
};
use gpui_kit::prelude::FluentBuilder;
use gpui_kit::*;
fn text(s: impl Into<SharedString>) -> Div {
    div().child(s.into())
}

/// Inset of row fills from the sidebar edges.
pub const INSET: f32 = 10.;
/// Row height; rows sit on a 30pt pitch.
pub const ROW: f32 = 28.;
pub const GAP: f32 = 2.;
/// Leading padding inside a row, so the icon lands on x = INSET + PAD.
pub const PAD: f32 = 8.;
/// Trailing padding inside a row before the accessory slot.
pub const TRAIL: f32 = 4.;
pub const ICON: f32 = 15.;
pub const ICON_BOX: f32 = 16.;
pub const ACCESSORY: f32 = 20.;
pub const RADIUS: f32 = 6.;
/// Translucent fills read as part of the glass rather than plates on it.
pub const HOVER: u32 = 0x00000008;
pub const PRESSED: u32 = 0x00000012;
/// The list starts just under the titlebar row that holds the traffic lights.
pub const TOP: f32 = 52.;

pub fn glyph(glyph: Glyph, selected: bool) -> Div {
    div()
        .flex_none()
        .size(px(ICON_BOX))
        .flex()
        .items_center()
        .justify_center()
        .child(
            Icon::new(glyph)
                .size(px(ICON))
                .text_color(rgb(crate::components::theme::get(if selected {
                    0
                } else {
                    1
                }))),
        )
}
pub fn title(label: impl Into<SharedString>) -> Div {
    text(label)
        .flex_1()
        .min_w_0()
        .truncate()
        .text_size(px(crate::components::BODY))
        .text_color(rgb(crate::components::theme::color(super::INK)))
}
/// A full-width source-list row button: same fill, radius and insets everywhere.
pub fn button(id: impl Into<ElementId>, selected: bool, cx: &App) -> Button {
    Button::new(id)
        .custom(
            gpui_kit::component::button::ButtonCustomVariant::new(cx)
                .hover(rgba((crate::components::theme::get(0) << 8) | (HOVER & 0xff)).into())
                .active(rgba((crate::components::theme::get(0) << 8) | (PRESSED & 0xff)).into()),
        )
        .small()
        .w_full()
        .h(px(ROW))
        .pl(px(PAD))
        .pr(px(TRAIL))
        .justify_start()
        .rounded(px(RADIUS))
        .text_size(px(crate::components::BODY))
        .when(selected, |b| b.bg(rgb(crate::components::theme::get(7))))
}
/// Plain trailing count, right-aligned on the accessory column. Bare
/// digits have no plate to hold them off the edge, so they keep the same
/// distance from the fill's trailing edge as the icon keeps from its
/// leading one (10pt), instead of the 4pt a plated badge can take.
pub const COUNT_INSET: f32 = 10.;
pub fn count(value: impl Into<SharedString>) -> Div {
    div()
        .flex_none()
        .min_w(px(ACCESSORY))
        .pr(px(COUNT_INSET - TRAIL))
        .flex()
        .justify_end()
        .child(
            text(value.into())
                .text_size(px(11.))
                .text_color(rgb(crate::components::theme::color(super::SECONDARY))),
        )
}
/// Attention: the agent waits on the user's decision. It's the user's
/// turn, not a quantity, so it's a dot rather than a number.
pub fn decision_dot() -> Div {
    div().size(px(6.)).rounded_full().bg(rgb(
        crate::components::theme::named("accent").unwrap_or(crate::components::INK)
    ))
}
/// The same dot in a trailing slot, where there's no icon to sit on.
pub fn decision() -> Div {
    div()
        .flex_none()
        .h(px(ACCESSORY))
        .min_w(px(ACCESSORY))
        .pr(px(COUNT_INSET - TRAIL))
        .flex()
        .items_center()
        .justify_end()
        .child(decision_dot())
}
/// The view's agent is working: the chat's braille spinner, its ink
/// ending on the same line as a bare count's.
pub fn activity(spinner: AnyElement) -> Div {
    div()
        .flex_none()
        .h(px(ACCESSORY))
        .min_w(px(ACCESSORY))
        .pr(px(COUNT_INSET - TRAIL))
        .flex()
        .items_center()
        .justify_end()
        .child(spinner)
}

pub use crate::design::badge_text;
pub const SECTION_SPACE: f32 = 10.;
pub const PITCH: f32 = ROW + GAP;
