//! Shared shell composer geometry: one surface, a quiet editor and a compact action.
use crate::components::{self as ui, CANVAS as PAPER, RULE as LINE, SECONDARY as MUTED};
use gpui_kit::{
    assets::IconName as Glyph,
    component::{
        button::{Button, ButtonVariants},
        input::{Textarea, TextareaState},
        *,
    },
    *,
};
pub const INSET: f32 = 12.;
pub const ACTION: f32 = 28.;

pub fn input(state: &Entity<TextareaState>, name: &'static str) -> Textarea {
    Textarea::new(state)
        .small()
        .w_full()
        .min_w_0()
        .items_start()
        .appearance(false)
        .bordered(false)
        .p(px(0.))
        .text_size(px(ui::BODY))
        .line_height(relative(1.5))
        .aria_label(name)
}

pub fn submit(id: impl Into<ElementId>, name: &'static str) -> Button {
    Button::new(id)
        .small()
        .primary()
        .size(px(ACTION))
        .rounded(px(ACTION / 2.))
        .icon(Glyph::ArrowUp)
        .accessibility_label(name)
}

pub fn shadow(progress: f32) -> Vec<BoxShadow> {
    vec![BoxShadow {
        color: rgba(0x00000014).into(),
        offset: point(px(0.), px(4.)),
        blur_radius: px(16.),
        spread_radius: px(-2.),
        inset: false,
    }]
    .into_iter()
    .map(|mut shadow| {
        shadow.color = shadow.color.opacity(progress.clamp(0., 1.).powi(3));
        shadow
    })
    .collect()
}

/// Same editor surface for a new view and an existing conversation.
pub fn surface(focused: bool) -> Div {
    ui::column()
        .bg(rgb(ui::theme::color(PAPER)))
        .gap(px(8.))
        .p(px(8.))
        .rounded(px(14.))
        .border_1()
        // Ink, not fixed greys, so the edge reads on dark themes too.
        .border_color(ui::ink(if focused { 0x30 } else { 0x18 }))
}

pub fn attachment_row() -> Div {
    ui::row().flex_wrap().min_w_0().gap(px(4.))
}

pub fn attachment_chip(name: &str, mime_type: &str) -> Div {
    ui::row()
        .min_w_0()
        .max_w(px(210.))
        .h(px(26.))
        .gap(px(4.))
        .px(px(6.))
        .rounded(px(6.))
        .border_1()
        .border_color(rgb(ui::theme::color(LINE)))
        .child(
            Icon::new(if mime_type.starts_with("image/") {
                Glyph::Image
            } else {
                Glyph::FileText
            })
            .flex_none()
            .size(px(13.))
            .text_color(rgb(ui::theme::color(MUTED))),
        )
        .child(
            div()
                .min_w_0()
                .truncate()
                .text_size(px(ui::CAPTION))
                .child(name.to_owned()),
        )
}
