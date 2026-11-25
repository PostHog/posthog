use crate::input::InputState;
use std::rc::Rc;

use gpui::Focusable;
use gpui::{
    AnyElement, App, Entity, EventEmitter, InteractiveElement as _, IntoElement, KeyBinding,
    ParentElement, RenderOnce, Role, SharedString, StatefulInteractiveElement as _,
    StyleRefinement, Styled, Window, actions, div, prelude::FluentBuilder as _,
};

use crate::{Button, InputBase, StyledExt as _};

actions!(number_input, [Increment, Decrement]);

const CONTEXT: &str = "NumberInput";

pub(crate) fn init(cx: &mut App) {
    cx.bind_keys([
        KeyBinding::new("up", Increment, Some(CONTEXT)),
        KeyBinding::new("down", Decrement, Some(CONTEXT)),
    ]);
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum StepAction {
    Decrement,
    Increment,
}

/// Strategy used by numeric editors when stepping their value.
#[derive(Clone)]
pub enum NumberStep {
    Fixed(f64),
    ByValue(Rc<dyn Fn(f64, StepAction, &mut gpui::App) -> f64>),
}

impl NumberStep {
    pub fn by_value(f: impl Fn(f64, StepAction, &mut gpui::App) -> f64 + 'static) -> Self {
        Self::ByValue(Rc::new(f))
    }

    pub(crate) fn value(&self, current: f64, action: StepAction, cx: &mut gpui::App) -> f64 {
        match self {
            Self::Fixed(step) => *step,
            Self::ByValue(f) => f(current, action, cx),
        }
    }
}

impl From<f64> for NumberStep {
    fn from(step: f64) -> Self {
        Self::Fixed(step)
    }
}

#[derive(Clone)]
pub enum NumberInputEvent {
    Step(StepAction),
}
impl EventEmitter<NumberInputEvent> for InputState {}

impl InputState {
    /// Apply a number-input step or emit a step event when stepping is caller-controlled.
    fn apply_number_step(
        &mut self,
        action: StepAction,
        window: &mut Window,
        cx: &mut gpui::Context<Self>,
    ) {
        if self.disabled {
            return;
        }
        if let Some(step) = self.number_step.clone() {
            let value = self.unmask_value();
            let current = value.trim().parse::<f64>().unwrap_or(0.);
            let step = step.value(current, action, cx);
            if let Some(new_value) =
                step_value(&value, action, step, self.number_min, self.number_max)
            {
                if self.is_valid_input(&new_value, cx) {
                    let range = self.range_to_utf16(&(0..self.value().len()));
                    self.replace_text_in_range_silent(Some(range), &new_value, window, cx);
                    return;
                }
            } else {
                return;
            }
        }
        cx.emit(NumberInputEvent::Step(action));
    }
}

type StepHandler = Rc<dyn Fn(StepAction, &mut Window, &mut App)>;
type ButtonDecorator = Box<dyn FnOnce(Button) -> Button>;

/// An unstyled spinbutton root composed from the foundational [`InputBase`] frame.
#[derive(IntoElement)]
pub struct NumberInput {
    style: StyleRefinement,
    children: Vec<AnyElement>,
    disabled: bool,
    state: Entity<InputState>,
    on_step: Option<StepHandler>,
    decrement_button: Option<ButtonDecorator>,
    increment_button: Option<ButtonDecorator>,
    input: Option<AnyElement>,
    controls_right: bool,
    accessibility_label: Option<SharedString>,
}

/// The built-in text region of a [`NumberInput`].
///
/// Applications provide the editor itself as a child and can style this region
/// without having to recreate the number input's fixed three-part structure.
#[derive(IntoElement)]
pub struct NumberInputText {
    style: StyleRefinement,
    children: Vec<AnyElement>,
}

impl NumberInputText {
    pub fn new() -> Self {
        Self {
            style: StyleRefinement::default(),
            children: Vec::new(),
        }
    }
}

impl Default for NumberInputText {
    fn default() -> Self {
        Self::new()
    }
}

impl Styled for NumberInputText {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl ParentElement for NumberInputText {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

impl RenderOnce for NumberInputText {
    fn render(self, _: &mut Window, _: &mut App) -> impl IntoElement {
        gpui::div()
            .min_w_0()
            .flex_1()
            .children(self.children)
            .refine_style(&self.style)
    }
}

impl NumberInput {
    pub fn new(state: &Entity<InputState>) -> Self {
        Self {
            style: StyleRefinement::default(),
            children: Vec::new(),
            disabled: false,
            state: state.clone(),
            on_step: None,
            decrement_button: None,
            increment_button: None,
            input: None,
            controls_right: false,
            accessibility_label: None,
        }
    }

    pub fn disabled(mut self, disabled: bool) -> Self {
        self.disabled = disabled;
        self
    }

    pub fn on_step(
        mut self,
        handler: impl Fn(StepAction, &mut Window, &mut App) + 'static,
    ) -> Self {
        self.on_step = Some(Rc::new(handler));
        self
    }

    /// Decorate the built-in decrement button with application-owned content and styles.
    pub fn decrement_button(mut self, decorate: impl FnOnce(Button) -> Button + 'static) -> Self {
        self.decrement_button = Some(Box::new(decorate));
        self
    }

    /// Decorate the built-in increment button with application-owned content and styles.
    pub fn increment_button(mut self, decorate: impl FnOnce(Button) -> Button + 'static) -> Self {
        self.increment_button = Some(Box::new(decorate));
        self
    }

    /// Decorate the built-in text region with an editor, adornments, and styles.
    pub fn input(mut self, input: impl IntoElement) -> Self {
        self.input = Some(input.into_any_element());
        self
    }

    /// Stack both step buttons on the right side of the text region.
    pub fn controls_right(mut self) -> Self {
        self.controls_right = true;
        self
    }

    /// Sets the name exposed to accessibility clients.
    ///
    /// A number input has no visible text of its own to be named by, so set
    /// this unless the input is named some other way.
    pub fn accessibility_label(mut self, label: impl Into<SharedString>) -> Self {
        self.accessibility_label = Some(label.into());
        self
    }
}

impl Styled for NumberInput {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl ParentElement for NumberInput {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

impl RenderOnce for NumberInput {
    fn render(self, window: &mut Window, cx: &mut App) -> impl IntoElement {
        let disabled = self.disabled;
        let controls_right = self.controls_right;
        let on_step = self.on_step.unwrap_or_else(|| {
            let state = self.state.clone();
            Rc::new(move |action, window, cx| {
                state.update(cx, |state, cx| {
                    state.focus(window, cx);
                    state.apply_number_step(action, window, cx);
                });
            })
        });
        self.state.update(cx, |state, _| state.ensure_number_mask());
        let value = self.state.read(cx).value().parse::<f64>().ok();
        let decrement_button = self.decrement_button.map_or_else(
            || Button::new("decrement"),
            |decorate| decorate(Button::new("decrement")),
        );
        let increment_button = self.increment_button.map_or_else(
            || Button::new("increment"),
            |decorate| decorate(Button::new("increment")),
        );
        let text = NumberInputText::new().children(self.input);

        // Stepping is driven from the focused editor, so the buttons never take
        // focus themselves; otherwise every press would pull the focus ring off
        // the frame and hand it straight back.
        let decrement_button = decrement_button
            .when(controls_right, |this| this.flex_1().min_h_0())
            .when(!controls_right, |this| this.flex_none())
            .focusable(false)
            .disabled(disabled)
            .on_click({
                let on_step = on_step.clone();
                move |_, window, cx| {
                    on_step(StepAction::Decrement, window, cx);
                }
            });
        let increment_button = increment_button
            .when(controls_right, |this| this.flex_1().min_h_0())
            .when(!controls_right, |this| this.flex_none())
            .focusable(false)
            .disabled(disabled)
            .on_click({
                let on_step = on_step.clone();
                move |_, window, cx| {
                    on_step(StepAction::Increment, window, cx);
                }
            });

        let content = if controls_right {
            div()
                .flex()
                .items_center()
                .size_full()
                .child(text.children(self.children))
                .child(
                    div()
                        .h_full()
                        .flex()
                        .flex_col()
                        .child(increment_button)
                        .child(decrement_button),
                )
                .into_any_element()
        } else {
            div()
                .flex()
                .items_center()
                .size_full()
                .child(decrement_button)
                .child(text.children(self.children))
                .child(increment_button)
                .into_any_element()
        };

        InputBase::new(("number-input", self.state.entity_id()))
            .track_focus(&self.state.focus_handle(cx))
            .flex()
            .items_center()
            .disabled(disabled)
            .role(Role::SpinButton)
            .when_some(self.accessibility_label, |this, label| {
                this.aria_label(label)
            })
            .when_some(value, |this, value| this.aria_numeric_value(value))
            .key_context(CONTEXT)
            .on_action({
                let on_step = on_step.clone();
                move |_: &Increment, window, cx| {
                    if disabled {
                        cx.propagate();
                    } else {
                        on_step(StepAction::Increment, window, cx);
                    }
                }
            })
            .on_action(move |_: &Decrement, window, cx| {
                if disabled {
                    cx.propagate();
                } else {
                    on_step(StepAction::Decrement, window, cx);
                }
            })
            .child(content)
            .refine_style(&self.style)
            .render(window, cx)
    }
}

/// Step a numeric string while preserving decimal precision and range direction.
pub fn step_value(
    value: &str,
    action: StepAction,
    step: f64,
    min: Option<f64>,
    max: Option<f64>,
) -> Option<String> {
    fn fraction_digits(value: &str) -> usize {
        value.split('.').nth(1).map_or(0, |fraction| fraction.len())
    }

    let current = value.trim().parse::<f64>().ok();
    let mut new_value = match action {
        StepAction::Increment => current.unwrap_or(0.) + step,
        StepAction::Decrement => current.unwrap_or(0.) - step,
    };
    let mut digits = fraction_digits(value).max(fraction_digits(&step.to_string()));
    if let Some(min) = min
        && new_value < min
    {
        new_value = min;
        digits = digits.max(fraction_digits(&min.to_string()));
    }
    if let Some(max) = max
        && new_value > max
    {
        new_value = max;
        digits = digits.max(fraction_digits(&max.to_string()));
    }

    if let Some(current) = current {
        let moved = match action {
            StepAction::Increment => new_value > current,
            StepAction::Decrement => new_value < current,
        };
        if !moved {
            return None;
        }
    }

    Some(format!("{new_value:.digits$}"))
}

#[cfg(test)]
mod tests {
    use super::*;

    use crate::theme::Theme;
    use gpui::{
        AppContext as _, Context, Entity, Modifiers, MouseButton, Render, TestAppContext,
        VisualTestContext, point, px,
    };

    struct StepperHarness {
        state: Entity<InputState>,
    }

    impl Render for StepperHarness {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            NumberInput::new(&self.state)
                .w(px(120.))
                .h(px(20.))
                .decrement_button(|button| button.w(px(20.)).h_full())
                .input(div().size_full())
                .increment_button(|button| button.w(px(20.)).h_full())
        }
    }

    /// Pressing a step button must not move focus off the editor, not even for
    /// the press itself: the frame draws a focus ring, so a focus round-trip
    /// makes it flicker on every click.
    #[gpui::test]
    fn pressing_a_step_button_never_takes_focus_off_the_editor(cx: &mut TestAppContext) {
        cx.update(crate::init);

        let mut created: Option<Entity<InputState>> = None;
        let window = cx.update(|cx| {
            cx.open_window(Default::default(), |window, cx| {
                cx.set_global(Theme::default());
                let state = cx.new(|cx| InputState::new(window, cx).step(1.));
                created = Some(state.clone());
                cx.new(|_| StepperHarness { state })
            })
            .unwrap()
        });
        let state = created.unwrap();
        let cx = &mut VisualTestContext::from_window(window.into(), cx);

        cx.update(|window, cx| {
            state.update(cx, |state, cx| state.focus(window, cx));
            window.draw(cx).clear(cx);
        });
        cx.update(|window, cx| {
            assert!(
                state.read(cx).focus_handle(cx).is_focused(window),
                "the editor should start focused"
            );
        });

        // The decrement button sits at the left edge of the control.
        cx.simulate_mouse_move(
            point(px(10.), px(10.)),
            MouseButton::Left,
            Modifiers::default(),
        );
        cx.simulate_event(gpui::MouseDownEvent {
            button: MouseButton::Left,
            position: point(px(10.), px(10.)),
            modifiers: Modifiers::default(),
            click_count: 1,
            first_mouse: false,
        });

        cx.update(|window, cx| {
            assert!(
                state.read(cx).focus_handle(cx).is_focused(window),
                "pressing the step button pulled focus off the editor"
            );
        });

        cx.simulate_event(gpui::MouseUpEvent {
            button: MouseButton::Left,
            position: point(px(10.), px(10.)),
            modifiers: Modifiers::default(),
            click_count: 1,
        });

        cx.update(|window, cx| {
            assert!(
                state.read(cx).focus_handle(cx).is_focused(window),
                "releasing the step button left focus off the editor"
            );
        });
    }

    #[test]
    fn stepping_preserves_precision_and_directional_bounds() {
        assert_eq!(
            step_value("0.1", StepAction::Increment, 0.2, None, None).as_deref(),
            Some("0.3")
        );
        assert_eq!(
            step_value("10", StepAction::Decrement, 1., Some(10.), None),
            None
        );
        assert_eq!(
            step_value("99.5", StepAction::Increment, 1., None, Some(100.)).as_deref(),
            Some("100.0")
        );
        assert_eq!(
            step_value("10", StepAction::Increment, 1., None, Some(10.)),
            None
        );
        assert_eq!(
            step_value("5", StepAction::Decrement, 10., Some(0.), None).as_deref(),
            Some("0")
        );
    }
}
