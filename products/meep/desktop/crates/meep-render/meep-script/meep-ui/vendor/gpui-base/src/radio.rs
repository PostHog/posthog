use std::rc::Rc;

use gpui::{
    AnyElement, App, ClickEvent, Div, ElementId, FocusHandle, InteractiveElement, Interactivity,
    IntoElement, ParentElement, Refineable as _, RenderOnce, Role, SharedString, Stateful,
    StatefulInteractiveElement, StyleRefinement, Styled, Toggled, Window, div,
    prelude::FluentBuilder as _,
};
use smallvec::SmallVec;

use crate::{StateStyle, StyledExt as _, TestSupportExt as _, a11y_disabled::A11yDisabledExt as _};

type ChangeHandler = Rc<dyn Fn(bool, &ClickEvent, &mut Window, &mut App)>;

/// An unstyled radio control that owns activation, focus, and accessibility behavior.
///
/// The application owns its indicator, label, layout, colors, and state styling.
/// Selection is controlled through [`Radio::checked`]; activating an unchecked
/// radio requests `true` through [`Radio::on_change`].
#[derive(IntoElement)]
pub struct Radio {
    id: ElementId,
    base: Stateful<Div>,
    style: StyleRefinement,
    semantic_styles: RadioStyles,
    checked: bool,
    disabled: bool,
    children: SmallVec<[AnyElement; 2]>,
    on_change: Option<ChangeHandler>,
    accessibility_label: Option<SharedString>,
    tab_index: isize,
    tab_stop: bool,
    provided_focus_handle: Option<FocusHandle>,
    position_in_set: Option<usize>,
    size_of_set: Option<usize>,
}

/// Semantic root styles supported by [`Radio`].
#[derive(Default)]
pub struct RadioStyles {
    checked: StyleRefinement,
    disabled: StyleRefinement,
}

impl RadioStyles {
    pub fn checked(mut self, build: impl FnOnce(StateStyle) -> StateStyle) -> Self {
        self.checked
            .refine(&build(StateStyle::default()).into_refinement());
        self
    }

    pub fn disabled(mut self, build: impl FnOnce(StateStyle) -> StateStyle) -> Self {
        self.disabled
            .refine(&build(StateStyle::default()).into_refinement());
        self
    }
}

impl Radio {
    pub fn new(id: impl Into<ElementId>) -> Self {
        let id = id.into();
        Self {
            base: div().id(id.clone()),
            id,
            style: StyleRefinement::default(),
            semantic_styles: RadioStyles::default(),
            checked: false,
            disabled: false,
            children: SmallVec::new(),
            on_change: None,
            accessibility_label: None,
            tab_index: 0,
            tab_stop: true,
            provided_focus_handle: None,
            position_in_set: None,
            size_of_set: None,
        }
    }

    /// Updates the element identity used when the radio is rendered.
    ///
    /// A group that assigns positional ids after construction needs this so
    /// each radio keeps a distinct element identity.
    pub fn id(mut self, id: impl Into<ElementId>) -> Self {
        let id = id.into();
        self.base.interactivity().element_id = Some(id.clone());
        self.id = id;
        self
    }

    pub fn checked(mut self, checked: bool) -> Self {
        self.checked = checked;
        self
    }

    pub fn disabled(mut self, disabled: bool) -> Self {
        self.disabled = disabled;
        self
    }

    /// Configures application-owned styles for the radio's semantic states.
    pub fn styles(mut self, build: impl FnOnce(RadioStyles) -> RadioStyles) -> Self {
        self.semantic_styles = build(self.semantic_styles);
        self
    }

    fn resolved_style(&self) -> StyleRefinement {
        crate::state_style::resolve_style(
            &self.style,
            [
                self.checked.then_some(&self.semantic_styles.checked),
                self.disabled.then_some(&self.semantic_styles.disabled),
            ]
            .into_iter()
            .flatten(),
        )
    }

    pub fn accessibility_label(mut self, label: impl Into<SharedString>) -> Self {
        self.accessibility_label = Some(label.into());
        self
    }

    /// Handles a requested selection change.
    ///
    /// The callback receives `true`. Activating an already checked radio is a
    /// no-op because a radio cannot deselect itself.
    pub fn on_change(
        mut self,
        handler: impl Fn(bool, &ClickEvent, &mut Window, &mut App) + 'static,
    ) -> Self {
        self.on_change = Some(Rc::new(handler));
        self
    }

    /// Uses a caller-owned focus handle instead of creating keyed state.
    ///
    /// A styled radio needs this to draw its own focus ring from the same
    /// handle the primitive tracks.
    pub fn track_focus(mut self, focus_handle: &FocusHandle) -> Self {
        self.provided_focus_handle = Some(focus_handle.clone());
        self
    }

    /// Sets this radio's one-based position and its group's total size, so
    /// assistive technology can announce "option 2 of 5".
    pub fn set_position(mut self, position: usize, size: usize) -> Self {
        self.position_in_set = Some(position);
        self.size_of_set = Some(size);
        self
    }

    pub fn tab_index(mut self, tab_index: isize) -> Self {
        self.tab_index = tab_index;
        self
    }

    pub fn tab_stop(mut self, tab_stop: bool) -> Self {
        self.tab_stop = tab_stop;
        self
    }

    fn focus_handle(&self, window: &mut Window, cx: &mut App) -> FocusHandle {
        self.provided_focus_handle.clone().unwrap_or_else(|| {
            window
                .use_keyed_state(self.id.clone(), cx, |_, cx| cx.focus_handle())
                .read(cx)
                .clone()
        })
    }
}

impl Styled for Radio {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl ParentElement for Radio {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

impl InteractiveElement for Radio {
    fn interactivity(&mut self) -> &mut Interactivity {
        self.base.interactivity()
    }
}

impl StatefulInteractiveElement for Radio {}

impl RenderOnce for Radio {
    fn render(self, window: &mut Window, cx: &mut App) -> impl IntoElement {
        let focus_handle = self.focus_handle(window, cx);
        let disabled = self.disabled;
        let checked = self.checked;
        let style = self.resolved_style();
        let on_change = self.on_change;

        self.base
            .test_support()
            .role(Role::RadioButton)
            .aria_toggled(if checked {
                Toggled::True
            } else {
                Toggled::False
            })
            // A radio is both "toggled" and "selected"; different assistive
            // technology reads one or the other, so state both rather than
            // making callers choose.
            .aria_selected(checked)
            .when_some(self.accessibility_label, |this, label| {
                this.aria_label(label)
            })
            .when_some(self.position_in_set, |this, position| {
                this.aria_position_in_set(position)
            })
            .when_some(self.size_of_set, |this, size| this.aria_size_of_set(size))
            .when(!disabled, |this| {
                this.track_focus(
                    &focus_handle
                        .tab_index(self.tab_index)
                        .tab_stop(self.tab_stop),
                )
            })
            .when_some(
                (!disabled && !checked).then_some(on_change).flatten(),
                |this, on_change| {
                    this.on_click(move |event, window, cx| {
                        on_change(!checked, event, window, cx);
                    })
                },
            )
            .children(self.children)
            .refine_style(&style)
            .a11y_disabled(disabled)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{
        cell::Cell,
        rc::Rc,
        sync::{Arc, Mutex},
    };

    use gpui::{
        Context, Element as _, KeyDownEvent, KeyUpEvent, Keystroke, Modifiers, Render,
        TestAppContext, VisualTestContext, accesskit, canvas, point, px,
    };

    #[test]
    fn semantic_state_styles_are_available_to_applications() {
        let _ = Radio::new("states").styles(|styles| {
            styles
                .checked(|style| style.opacity(0.8))
                .disabled(|style| {
                    style
                        .opacity(0.5)
                        .when(true, |style| style.border_1())
                        .when_some(Some(0.4), |style, opacity| style.opacity(opacity))
                        .when_none(&None::<f32>, |style| style.rounded_sm())
                })
        });
    }

    #[test]
    fn semantic_root_styles_follow_radio_priority() {
        let styled = |radio: Radio| {
            radio.styles(|styles| {
                styles
                    .checked(|style| style.opacity(0.8))
                    .disabled(|style| style.opacity(0.5))
            })
        };

        assert_eq!(styled(Radio::new("normal")).resolved_style().opacity, None);
        assert_eq!(
            styled(Radio::new("checked").checked(true))
                .resolved_style()
                .opacity,
            Some(0.8)
        );
        assert_eq!(
            styled(Radio::new("checked-disabled").checked(true).disabled(true))
                .resolved_style()
                .opacity,
            Some(0.5)
        );
        assert_eq!(
            styled(
                Radio::new("state-over-instance")
                    .checked(true)
                    .disabled(true)
                    .opacity(0.9),
            )
            .resolved_style()
            .opacity,
            Some(0.5)
        );
    }

    struct RadioHarness {
        checked: bool,
        disabled: bool,
        changes: Rc<Cell<usize>>,
        keyboard_changes: Rc<Cell<usize>>,
    }

    impl Render for RadioHarness {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            let changes = self.changes.clone();
            let keyboard_changes = self.keyboard_changes.clone();
            Radio::new("radio")
                .checked(self.checked)
                .disabled(self.disabled)
                .size(px(100.))
                .on_change(move |checked, event, _, _| {
                    assert!(checked);
                    changes.set(changes.get() + 1);
                    if matches!(event, ClickEvent::Keyboard(_)) {
                        keyboard_changes.set(keyboard_changes.get() + 1);
                    }
                })
        }
    }

    fn harness(
        cx: &mut TestAppContext,
        checked: bool,
        disabled: bool,
    ) -> (&mut VisualTestContext, Rc<Cell<usize>>, Rc<Cell<usize>>) {
        let changes = Rc::new(Cell::new(0));
        let keyboard_changes = Rc::new(Cell::new(0));
        let (_, cx) = cx.add_window_view({
            let changes = changes.clone();
            let keyboard_changes = keyboard_changes.clone();
            move |_, _| RadioHarness {
                checked,
                disabled,
                changes,
                keyboard_changes,
            }
        });
        cx.update(|window, cx| window.draw(cx).clear(cx));
        (cx, changes, keyboard_changes)
    }

    #[gpui::test]
    fn pointer_and_keyboard_activation_fire_once(cx: &mut TestAppContext) {
        let (cx, changes, keyboard_changes) = harness(cx, false, false);
        cx.simulate_click(point(px(10.), px(10.)), Modifiers::default());
        assert_eq!(changes.get(), 1);

        changes.set(0);
        cx.update(|window, cx| window.draw(cx).clear(cx));
        for key in ["enter", "space"] {
            let keystroke = Keystroke::parse(key).unwrap();
            cx.simulate_event(KeyDownEvent {
                keystroke: keystroke.clone(),
                is_held: false,
                prefer_character_input: false,
            });
            cx.simulate_event(KeyUpEvent { keystroke });
        }
        assert_eq!(changes.get(), 2);
        assert_eq!(keyboard_changes.get(), 2);
    }

    #[gpui::test]
    fn checked_and_disabled_radios_are_inert(cx: &mut TestAppContext) {
        for (checked, disabled) in [(true, false), (false, true)] {
            let (cx, changes, _) = harness(cx, checked, disabled);
            cx.simulate_click(point(px(10.), px(10.)), Modifiers::default());
            cx.simulate_keystrokes("enter space");
            assert_eq!(changes.get(), 0);
        }
    }

    #[gpui::test]
    fn accessibility_exposes_role_state_and_action(cx: &mut TestAppContext) {
        type Captured = Arc<Mutex<Option<accesskit::Node>>>;
        struct Probe(Captured);
        impl Render for Probe {
            fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
                let captured = self.0.clone();
                canvas(
                    move |_, window, cx| {
                        let mut node = accesskit::Node::new(Role::RadioButton);
                        Radio::new("probe")
                            .checked(true)
                            .accessibility_label("Choice")
                            .render(window, cx)
                            .into_element()
                            .write_a11y_info(&mut node);
                        *captured.lock().unwrap() = Some(node);
                    },
                    |_, _, _, _| {},
                )
            }
        }
        let captured: Captured = Arc::new(Mutex::new(None));
        let result = captured.clone();
        let (_, cx) = cx.add_window_view(move |_, _| Probe(captured));
        cx.update(|window, cx| window.draw(cx).clear(cx));
        let node = result.lock().unwrap().take().unwrap();
        assert_eq!(node.role(), Role::RadioButton);
        assert_eq!(node.label(), Some("Choice"));
        assert_eq!(node.toggled(), Some(Toggled::True));
        assert!(!node.supports_action(accesskit::Action::Click));
    }
}
