use gpui::{
    AnyElement, App, Entity, Focusable, InteractiveElement as _, IntoElement, MouseButton,
    ParentElement as _, RenderOnce, Styled as _, Window, div, prelude::FluentBuilder,
};

use super::input::input_style;
use super::state::sync_focused_input_registry;
use crate::{ActiveTheme, Disableable, Icon, IconName, Sizable, Size, h_flex, v_flex};
use crate::{StyleSized as _, ThemeStyled as _};
use gpui_base::OtpInput as BaseOtpInput;
pub use gpui_base::{OtpEvent, OtpState};

/// A One Time Password (OTP) input element.
///
/// This can accept a fixed length number and can be masked.
///
/// Use case example:
///
/// - SMS OTP
/// - Authenticator OTP
#[derive(IntoElement)]
pub struct OtpInput {
    state: Entity<OtpState>,
    number_of_groups: usize,
    size: Size,
    focus_ring_enabled: bool,
    disabled: bool,
}

impl OtpInput {
    /// Create a new [`OtpInput`] element bind to the [`OtpState`].
    pub fn new(state: &Entity<OtpState>) -> Self {
        Self {
            state: state.clone(),
            number_of_groups: 2,
            size: Size::Medium,
            focus_ring_enabled: true,
            disabled: false,
        }
    }

    /// Set number of groups in the OTP Input.
    pub fn groups(mut self, n: usize) -> Self {
        self.number_of_groups = n;
        self
    }

    fn resolved_groups(length: usize, requested: usize) -> usize {
        requested.max(1).min(length.max(1))
    }
}
impl Disableable for OtpInput {
    fn disabled(mut self, disabled: bool) -> Self {
        self.disabled = disabled;
        self
    }
}
impl crate::FocusableExt for OtpInput {
    fn focus_ring(mut self, enabled: bool) -> Self {
        self.focus_ring_enabled = enabled;
        self
    }

    fn is_focus_ring_enabled(&self) -> bool {
        self.focus_ring_enabled
    }
}
impl Sizable for OtpInput {
    fn with_size(mut self, size: impl Into<crate::Size>) -> Self {
        self.size = size.into();
        self
    }
}
impl RenderOnce for OtpInput {
    fn render(self, window: &mut Window, cx: &mut App) -> impl IntoElement {
        sync_focused_input_registry(self.state.clone(), window, cx);
        let state = self.state.read(cx);
        let blink_show = state.cursor_visible(cx);
        let is_focused = state.focus_handle(cx).is_focused(window);

        let cursor_ix = state
            .value()
            .chars()
            .count()
            .min(state.len().saturating_sub(1));
        let number_of_groups = Self::resolved_groups(state.len(), self.number_of_groups);
        let mut groups: Vec<Vec<AnyElement>> = Vec::with_capacity(number_of_groups);
        let mut group_ix = 0;
        let group_items_count = state.len().div_ceil(number_of_groups).max(1);
        for _ in 0..number_of_groups {
            groups.push(vec![]);
        }

        let (bg, fg) = input_style(self.disabled, cx);

        for ix in 0..state.len() {
            let c = state.value().chars().nth(ix);
            if ix % group_items_count == 0 && ix != 0 {
                group_ix += 1;
            }

            let is_input_focused = ix == cursor_ix && is_focused;
            let focus_visible = is_input_focused && !self.disabled && self.focus_ring_enabled;

            groups[group_ix].push(
                h_flex()
                    .id(ix)
                    .border_1()
                    .border_color(cx.theme().input)
                    .bg(bg)
                    .text_color(fg)
                    .when(self.disabled, |this| this.opacity(0.5))
                    .when(focus_visible, |this| this.border_color(cx.theme().ring))
                    .items_center()
                    .justify_center()
                    .rounded(cx.theme().radius)
                    .map(|this| match self.size {
                        Size::Size(v) => this.text_size(v * 0.5),
                        size => this.input_text_size(size),
                    })
                    .map(|this| match self.size {
                        Size::XSmall => this.w_6().h_6(),
                        Size::Small => this.w_6().h_6(),
                        Size::Medium => this.w_8().h_8(),
                        Size::Large => this.w_11().h_11(),
                        Size::Size(px) => this.w(px).h(px),
                    })
                    .when(focus_visible, |this| this.focus_ring_style(window, cx))
                    .on_mouse_down(MouseButton::Left, {
                        let state = self.state.clone();
                        move |_, window, cx| state.read(cx).focus_handle(cx).focus(window, cx)
                    })
                    .map(|this| match c {
                        Some(c) => {
                            if state.is_masked() {
                                this.child(
                                    Icon::new(IconName::Asterisk)
                                        .text_color(cx.theme().secondary_foreground)
                                        .when(self.disabled, |this| {
                                            this.text_color(cx.theme().muted_foreground)
                                        }),
                                )
                            } else {
                                this.child(c.to_string())
                            }
                        }
                        None => this.when(is_input_focused && blink_show, |this| {
                            this.child(
                                div()
                                    .h_4()
                                    .w_0()
                                    .border_l_3()
                                    .border_color(cx.theme().caret),
                            )
                        }),
                    })
                    .into_any_element(),
            );
        }

        BaseOtpInput::new(&self.state)
            .disabled(self.disabled)
            .child(
                v_flex()
                    .id(("otp-input", self.state.entity_id()))
                    .items_center()
                    .child(
                        h_flex().items_center().gap_5().children(
                            groups
                                .into_iter()
                                .map(|inputs| h_flex().items_center().gap_1().children(inputs)),
                        ),
                    ),
            )
    }
}

#[cfg(test)]
mod tests {
    use super::OtpInput;

    #[test]
    fn invalid_group_counts_are_safely_clamped() {
        assert_eq!(OtpInput::resolved_groups(6, 0), 1);
        assert_eq!(OtpInput::resolved_groups(6, 20), 6);
        assert_eq!(OtpInput::resolved_groups(0, 0), 1);
        assert_eq!(OtpInput::resolved_groups(5, 2), 2);
    }
}
