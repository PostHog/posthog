use crate::theme::ActiveTheme;
use gpui::{
    AnyElement, App, Entity, FocusHandle, Focusable, InteractiveElement as _,
    StatefulInteractiveElement as _, Window, div, px,
};
use gpui::{
    IntoElement, ParentElement, RenderOnce, SharedString, StyleRefinement, Styled, TextAlign,
    prelude::FluentBuilder as _,
};

use crate::{Disableable, Icon, IconName, Sizable, Size, StyleSized as _, StyledExt as _};

use super::{Input, InputState, input::input_style};
use crate::ThemeStyled as _;
use gpui_base::NumberInput as BaseNumberInput;
pub use gpui_base::{NumberInputEvent, NumberStep, StepAction};
use rust_i18n::t;

/// A number input element with increment and decrement buttons.
#[derive(IntoElement)]
pub struct NumberInput {
    state: Entity<InputState>,
    placeholder: SharedString,
    size: Size,
    prefix: Option<AnyElement>,
    suffix: Option<AnyElement>,
    appearance: bool,
    focus_ring_enabled: bool,
    disabled: bool,
    accessibility_label: Option<SharedString>,
    style: StyleRefinement,
}

impl NumberInput {
    /// Create a new [`NumberInput`] element bind to the [`InputState`].
    pub fn new(state: &Entity<InputState>) -> Self {
        Self {
            state: state.clone(),
            size: Size::default(),
            placeholder: SharedString::default(),
            prefix: None,
            suffix: None,
            appearance: true,
            focus_ring_enabled: true,
            disabled: false,
            accessibility_label: None,
            style: StyleRefinement::default(),
        }
    }

    /// Set the placeholder text of the number input.
    pub fn placeholder(mut self, placeholder: impl Into<SharedString>) -> Self {
        self.placeholder = placeholder.into();
        self
    }

    /// Set the prefix element of the number input.
    pub fn prefix(mut self, prefix: impl IntoElement) -> Self {
        self.prefix = Some(prefix.into_any_element());
        self
    }

    /// Set the suffix element of the number input.
    pub fn suffix(mut self, suffix: impl IntoElement) -> Self {
        self.suffix = Some(suffix.into_any_element());
        self
    }

    /// Set the appearance of the number input, if false will no border and background.
    pub fn appearance(mut self, appearance: bool) -> Self {
        self.appearance = appearance;
        self
    }

    /// Set the name a screen reader announces.
    ///
    /// A number input has no visible text of its own to be named by, so set
    /// this whenever it is shown without one, for example next to a separate
    /// label. This does not change what is displayed.
    pub fn accessibility_label(mut self, label: impl Into<SharedString>) -> Self {
        self.accessibility_label = Some(label.into());
        self
    }
}

impl Disableable for NumberInput {
    fn disabled(mut self, disabled: bool) -> Self {
        self.disabled = disabled;
        self
    }
}

impl crate::FocusableExt for NumberInput {
    fn focus_ring(mut self, enabled: bool) -> Self {
        self.focus_ring_enabled = enabled;
        self
    }

    fn is_focus_ring_enabled(&self) -> bool {
        self.focus_ring_enabled
    }
}

impl Focusable for NumberInput {
    fn focus_handle(&self, cx: &App) -> FocusHandle {
        self.state.focus_handle(cx)
    }
}

impl Sizable for NumberInput {
    fn with_size(mut self, size: impl Into<Size>) -> Self {
        self.size = size.into();
        self
    }
}

impl Styled for NumberInput {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl RenderOnce for NumberInput {
    fn render(self, window: &mut Window, cx: &mut App) -> impl IntoElement {
        let focused = self.state.read(cx).focus_handle(cx).is_focused(window) && !self.disabled;
        let (bg, _) = input_style(self.disabled, cx);
        let border_color = if self.disabled {
            cx.theme().input.opacity(0.5)
        } else {
            cx.theme().input
        };
        // Transparent like a ghost button, but tinted to the frame on hover.
        let button_foreground = cx.theme().secondary_foreground;
        let button_hover = cx.theme().input.opacity(0.4);
        let button_active = cx.theme().input.opacity(0.6);
        let button_size = self.size;
        // The buttons sit inside the 1px frame, so their corners are a pixel
        // tighter than the frame's, or they paint over its inner curve.
        let button_radius = if self.appearance {
            (cx.theme().radius - px(1.)).max(px(0.))
        } else {
            cx.theme().radius
        };
        let base_state = self.state.clone();
        let content = BaseNumberInput::new(&base_state)
            .disabled(self.disabled)
            .when_some(self.accessibility_label, |this, label| {
                this.accessibility_label(label)
            })
            .size_full()
            .decrement_button(move |this| {
                this.accessibility_label(t!("Input.Decrement"))
                    .flex()
                    .items_center()
                    .justify_center()
                    .text_color(button_foreground)
                    .hover(move |this| this.bg(button_hover))
                    .active(move |this| this.bg(button_active))
                    // The frame owns the control height, so the buttons fill it
                    // rather than setting their own and outgrowing the border.
                    .h_full()
                    .map(|this| match button_size {
                        Size::XSmall | Size::Small => this.min_w_6(),
                        Size::Medium | Size::Large => this.min_w_8(),
                        Size::Size(size) => this.min_w(size),
                    })
                    // Only the outer corners are rounded, to follow the frame.
                    .rounded_tl(button_radius)
                    .rounded_bl(button_radius)
                    .child(Icon::new(IconName::Minus).with_size(button_size))
            })
            .input(
                Input::new(&self.state)
                    .appearance(false)
                    .with_size(button_size)
                    .h_full()
                    .disabled(self.disabled)
                    .gap_0()
                    .rounded_none()
                    .text_align(TextAlign::Center)
                    .when_some(self.prefix, |this, prefix| this.prefix(prefix))
                    .when_some(self.suffix, |this, suffix| this.suffix(suffix)),
            )
            .increment_button(move |this| {
                this.accessibility_label(t!("Input.Increment"))
                    .flex()
                    .items_center()
                    .justify_center()
                    .text_color(button_foreground)
                    .hover(move |this| this.bg(button_hover))
                    .active(move |this| this.bg(button_active))
                    .h_full()
                    .map(|this| match button_size {
                        Size::XSmall | Size::Small => this.min_w_6(),
                        Size::Medium | Size::Large => this.min_w_8(),
                        Size::Size(size) => this.min_w(size),
                    })
                    .rounded_tr(button_radius)
                    .rounded_br(button_radius)
                    .child(Icon::new(IconName::Plus).with_size(button_size))
            });

        // The visual frame wraps the complete spinbutton. BaseNumberInput routes
        // application children into its text slot, so putting the ring on that
        // element would incorrectly surround only the editable middle region.
        div()
            .flex_1()
            .input_h(self.size)
            .rounded(cx.theme().radius)
            .when(self.appearance, |this| {
                this.bg(bg)
                    .border_1()
                    .border_color(border_color)
                    .when(focused, |this| {
                        this.border_1().border_color(cx.theme().ring)
                    })
            })
            .refine_style(&self.style)
            .when(self.disabled, |this| this.opacity(0.5))
            .child(content)
            .when(
                focused && self.appearance && self.focus_ring_enabled,
                |this| this.focus_ring_style(window, cx),
            )
    }
}

#[cfg(test)]
mod tests {
    use super::StepAction;
    use gpui_base::step_value;

    // `test_number_step` lives in `state::tests` because `NumberStep::value`
    // now needs a `Context<InputState>` to invoke the `by_value` closure.

    #[test]
    fn test_step_value() {
        fn some(value: &str) -> Option<String> {
            Some(value.to_string())
        }

        // Step from empty value
        assert_eq!(
            step_value("", StepAction::Increment, 1., None, None),
            some("1")
        );
        assert_eq!(
            step_value("", StepAction::Decrement, 1., None, None),
            some("-1")
        );
        // Invalid intermediate values are treated as 0
        assert_eq!(
            step_value("-", StepAction::Increment, 1., None, None),
            some("1")
        );
        assert_eq!(
            step_value("1", StepAction::Increment, 1., None, None),
            some("2")
        );
        assert_eq!(
            step_value("-2", StepAction::Increment, 1., None, None),
            some("-1")
        );

        // Avoid float precision issue, e.g. 0.1 + 0.2 != 0.30000000000000004
        assert_eq!(
            step_value("0.1", StepAction::Increment, 0.2, None, None),
            some("0.3")
        );
        assert_eq!(
            step_value("0.3", StepAction::Decrement, 0.1, None, None),
            some("0.2")
        );
        // Keep the fraction digits of the current value
        assert_eq!(
            step_value("1.25", StepAction::Increment, 1., None, None),
            some("2.25")
        );

        // Step from empty value always steps into the range
        assert_eq!(
            step_value("", StepAction::Increment, 1., Some(10.), None),
            some("10")
        );
        assert_eq!(
            step_value("", StepAction::Decrement, 1., Some(10.), None),
            some("10")
        );
        // Clamp to min/max
        assert_eq!(
            step_value("99.5", StepAction::Increment, 1., None, Some(100.)),
            some("100.0")
        );
        assert_eq!(
            step_value("1000", StepAction::Decrement, 1., None, Some(100.)),
            some("100")
        );
        // Keep the fraction digits of the clamped bound
        assert_eq!(
            step_value("1", StepAction::Decrement, 1., Some(0.25), None),
            some("0.25")
        );

        // Stepping must move the value in the pressed direction:
        // no-op at the boundary
        assert_eq!(
            step_value("10", StepAction::Decrement, 1., Some(10.), None),
            None
        );
        assert_eq!(
            step_value("100", StepAction::Increment, 1., None, Some(100.)),
            None
        );
        // Decrement on a below-min value (or Increment on an above-max value)
        // does nothing, instead of moving the value in the opposite direction
        assert_eq!(
            step_value("5", StepAction::Decrement, 1., Some(10.), None),
            None
        );
        assert_eq!(
            step_value("1000", StepAction::Increment, 1., None, Some(100.)),
            None
        );
    }
}
