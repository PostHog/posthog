//! Shared shell control feedback, also used by the agent panel.
use gpui_kit::component::button::{Button, ButtonVariants};
use gpui_kit::prelude::FluentBuilder;
use gpui_kit::*;

pub fn quiet_button(id: impl Into<ElementId>, cx: &App) -> Button {
    Button::new(id).custom(
        gpui_kit::component::button::ButtonCustomVariant::new(cx)
            .hover(crate::components::ink(0x06).into())
            .active(crate::components::ink(0x0b).into()),
    )
}

/// A primary pill that cannot be pressed gives up the accent: a neutral
/// wash and quiet text, never a faded tint of the accent colour.
pub trait Unavailable {
    fn unavailable(self, disabled: bool) -> Self;
}
impl Unavailable for Button {
    fn unavailable(self, disabled: bool) -> Self {
        use gpui_kit::component::Disableable as _;
        self.disabled(disabled).when(disabled, |b| {
            b.bg(crate::components::ink(0x0d))
                .border_color(gpui_kit::rgba(0x00000000))
                .text_color(rgb(crate::components::theme::get(2)))
        })
    }
}
