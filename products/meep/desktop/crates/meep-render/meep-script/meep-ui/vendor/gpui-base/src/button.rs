use std::rc::Rc;

use gpui::{
    AnyElement, App, ClickEvent, Div, ElementId, FocusHandle, InteractiveElement, Interactivity,
    IntoElement, MouseButton, ParentElement, Refineable as _, RenderOnce, Role, SharedString,
    Stateful, StatefulInteractiveElement, StyleRefinement, Styled, Window, div,
    prelude::FluentBuilder as _, relative,
};
use smallvec::SmallVec;

use crate::{
    RoleOverride, Selectable, StateStyle, StyledExt as _, TestSupportExt as _,
    a11y_disabled::A11yDisabledExt as _,
};

type ClickHandler = Rc<dyn Fn(&ClickEvent, &mut Window, &mut App)>;

/// An unstyled button that owns interaction, focus, keyboard, and accessibility behavior.
///
/// Layout and visual states are intentionally supplied by the application through
/// GPUI's [`Styled`] API.
#[derive(IntoElement)]
pub struct Button {
    id: ElementId,
    base: crate::ObservedElement<Stateful<Div>>,
    style: StyleRefinement,
    semantic_styles: ButtonStyles,
    selected: bool,
    disabled: bool,
    children: SmallVec<[AnyElement; 2]>,
    on_click: Option<ClickHandler>,
    accessibility_label: Option<SharedString>,
    role: RoleOverride,
    provided_focus_handle: Option<FocusHandle>,
    tab_index: isize,
    tab_stop: bool,
    focusable: bool,
}

impl Button {
    pub fn new(id: impl Into<ElementId>) -> Self {
        let id = id.into();
        Self {
            base: div().id(id.clone()).test_support(),
            id,
            style: StyleRefinement::default(),
            semantic_styles: ButtonStyles::default(),
            selected: false,
            disabled: false,
            children: SmallVec::new(),
            on_click: None,
            accessibility_label: None,
            role: RoleOverride::Implicit,
            provided_focus_handle: None,
            tab_index: 0,
            tab_stop: true,
            focusable: true,
        }
    }

    /// Sets whether the button ignores pointer and keyboard activation.
    ///
    /// Disabled buttons are skipped during Tab traversal. If this button already
    /// owns focus when it becomes disabled, it retains the focus binding until
    /// focus moves away, so keyboard traversal can continue in either direction.
    pub fn disabled(mut self, disabled: bool) -> Self {
        self.disabled = disabled;
        self
    }

    /// Sets the application-controlled selected presentation state.
    ///
    /// This supports persistent trigger presentation while an associated menu
    /// or popover is open. It is distinct from momentary `active`, Toggle's
    /// `pressed` state, and accessibility toggle metadata; selecting a Button
    /// does not automatically set `aria_toggled`.
    pub fn selected(mut self, selected: bool) -> Self {
        self.selected = selected;
        self
    }

    /// Defines application-owned styles for the button's semantic states.
    pub fn styles(mut self, build: impl FnOnce(ButtonStyles) -> ButtonStyles) -> Self {
        self.semantic_styles = build(self.semantic_styles);
        self
    }

    /// Sets the label exposed to accessibility clients.
    pub fn accessibility_label(mut self, label: impl Into<SharedString>) -> Self {
        self.accessibility_label = Some(label.into());
        self
    }

    /// Overrides the accessibility role. The default is [`Role::Button`].
    pub fn role(mut self, role: impl Into<RoleOverride>) -> Self {
        self.role = role.into();
        self
    }

    /// Uses a caller-owned focus handle instead of creating keyed state.
    pub fn track_focus(mut self, focus_handle: &FocusHandle) -> Self {
        self.provided_focus_handle = Some(focus_handle.clone());
        self
    }

    /// Sets the activation handler for pointer, Enter, and Space input.
    pub fn on_click(
        mut self,
        handler: impl Fn(&ClickEvent, &mut Window, &mut App) + 'static,
    ) -> Self {
        self.on_click = Some(Rc::new(handler));
        self
    }

    /// Sets the focus traversal index. The default is `0`.
    pub fn tab_index(mut self, tab_index: isize) -> Self {
        self.tab_index = tab_index;
        self
    }

    /// Sets whether the button participates in keyboard focus traversal.
    pub fn tab_stop(mut self, tab_stop: bool) -> Self {
        self.tab_stop = tab_stop;
        self
    }

    /// Sets whether pressing the button moves focus onto it. The default is `true`.
    ///
    /// A non-focusable button leaves focus wherever it already is, which keeps a
    /// composed control from flickering its focus ring on every press. It also
    /// gives up Enter and Space activation, so only use it for a button that a
    /// focused sibling already exposes to the keyboard, such as a number input's
    /// step buttons.
    pub fn focusable(mut self, focusable: bool) -> Self {
        self.focusable = focusable;
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

    fn resolved_style(&self) -> StyleRefinement {
        crate::state_style::resolve_style(
            &self.style,
            [
                self.selected.then_some(&self.semantic_styles.selected),
                self.disabled.then_some(&self.semantic_styles.disabled),
            ]
            .into_iter()
            .flatten(),
        )
    }
}

impl Selectable for Button {
    fn selected(self, selected: bool) -> Self {
        Button::selected(self, selected)
    }

    fn is_selected(&self) -> bool {
        self.selected
    }
}

/// Semantic styles supported by [`Button`].
#[derive(Default)]
pub struct ButtonStyles {
    selected: StyleRefinement,
    disabled: StyleRefinement,
}

impl ButtonStyles {
    /// Refines the root style when the button is selected.
    pub fn selected(mut self, build: impl FnOnce(StateStyle) -> StateStyle) -> Self {
        self.selected
            .refine(&build(StateStyle::default()).into_refinement());
        self
    }

    /// Refines the root style when the button is disabled.
    pub fn disabled(mut self, build: impl FnOnce(StateStyle) -> StateStyle) -> Self {
        self.disabled
            .refine(&build(StateStyle::default()).into_refinement());
        self
    }
}

impl Styled for Button {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl ParentElement for Button {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

impl InteractiveElement for Button {
    fn interactivity(&mut self) -> &mut Interactivity {
        self.base.interactivity()
    }
}

impl StatefulInteractiveElement for Button {}

impl RenderOnce for Button {
    fn render(self, window: &mut Window, cx: &mut App) -> impl IntoElement {
        let focus_handle = self.focus_handle(window, cx);
        let disabled = self.disabled;
        let style = self.resolved_style();
        let on_click = self.on_click;

        self.base
            // Centering is part of Button's control geometry. Without a flex
            // formatting context an ordinary child starts at the root's
            // leading edge, so a fixed-height unstyled Button cannot align its
            // label even though its neutral line height is correct.
            .flex()
            .items_center()
            .justify_center()
            // A neutral line height is geometry, not visual policy: with the
            // inherited value the text box is taller than the glyphs, so the
            // caller's padding no longer determines the control's height and a
            // button cannot be sized precisely. `relative(1.)` makes the text
            // box exactly the font size; anything the caller sets refines over
            // it, so a product that wants looser text still can.
            .line_height(relative(1.))
            .when_some(self.role.resolve(|| Role::Button), |this, role| {
                this.role(role)
            })
            .when_some(self.accessibility_label, |this, label| {
                this.aria_label(label)
            })
            // Keep the current focus in the dispatch tree when activation
            // disables this button, so Tab can still leave it in either direction.
            .when(
                self.focusable && (!disabled || focus_handle.is_focused(window)),
                |this| {
                    this.track_focus(
                        &focus_handle
                            .tab_index(self.tab_index)
                            .tab_stop(self.tab_stop && !disabled),
                    )
                },
            )
            .when(disabled, |this| {
                this.on_mouse_down(MouseButton::Left, |_, _, cx| {
                    cx.stop_propagation();
                })
            })
            .when_some(
                (!disabled).then_some(on_click).flatten(),
                |this, on_click| {
                    this.on_click(move |event, window, cx| {
                        on_click(event, window, cx);
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
    use crate::ElementExt as _;
    use std::{
        cell::Cell,
        rc::Rc,
        sync::{Arc, Mutex},
    };

    use gpui::{
        AppContext as _, ClickEvent, Context, Element as _, KeyDownEvent, KeyUpEvent, Keystroke,
        Modifiers, Render, TestAppContext, VisualTestContext, accesskit, canvas, point, px,
    };

    struct ButtonHarness {
        disabled: bool,
        button_clicks: Rc<Cell<usize>>,
        parent_clicks: Rc<Cell<usize>>,
        keyboard_events: Rc<Cell<usize>>,
    }

    impl Render for ButtonHarness {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            let button_clicks = self.button_clicks.clone();
            let keyboard_events = self.keyboard_events.clone();
            let parent_clicks = self.parent_clicks.clone();

            div()
                .id("button-parent")
                .tab_group()
                .size(px(100.))
                .on_click(move |_, _, _| parent_clicks.set(parent_clicks.get() + 1))
                .child(
                    Button::new("button")
                        .disabled(self.disabled)
                        .size_full()
                        .on_click(move |event, _, _| {
                            button_clicks.set(button_clicks.get() + 1);
                            if matches!(event, ClickEvent::Keyboard(_)) {
                                keyboard_events.set(keyboard_events.get() + 1);
                            }
                        }),
                )
        }
    }

    fn harness(
        cx: &mut TestAppContext,
        disabled: bool,
    ) -> (
        &mut VisualTestContext,
        Rc<Cell<usize>>,
        Rc<Cell<usize>>,
        Rc<Cell<usize>>,
    ) {
        let button_clicks = Rc::new(Cell::new(0));
        let parent_clicks = Rc::new(Cell::new(0));
        let keyboard_events = Rc::new(Cell::new(0));
        let (_, cx) = cx.add_window_view({
            let button_clicks = button_clicks.clone();
            let parent_clicks = parent_clicks.clone();
            let keyboard_events = keyboard_events.clone();
            move |_, _| ButtonHarness {
                disabled,
                button_clicks,
                parent_clicks,
                keyboard_events,
            }
        });
        cx.update(|window, cx| {
            window.draw(cx).clear(cx);
        });
        (cx, button_clicks, parent_clicks, keyboard_events)
    }

    #[gpui::test]
    fn pointer_activation_fires_once(cx: &mut TestAppContext) {
        let (cx, button_clicks, _, keyboard_events) = harness(cx, false);

        cx.simulate_click(point(px(10.), px(10.)), Modifiers::default());

        assert_eq!(button_clicks.get(), 1);
        assert_eq!(keyboard_events.get(), 0);
    }

    #[gpui::test]
    fn enter_and_space_use_one_native_keyboard_click_each(cx: &mut TestAppContext) {
        let (cx, button_clicks, _, keyboard_events) = harness(cx, false);
        cx.simulate_click(point(px(10.), px(10.)), Modifiers::default());
        button_clicks.set(0);
        cx.update(|window, cx| {
            assert!(window.focused(cx).is_some());
            window.draw(cx).clear(cx);
        });

        for key in ["enter", "space"] {
            let keystroke =
                cx.update(|_, cx| Keystroke::parse_with_os(key, cx.platform_info().os).unwrap());
            cx.simulate_event(KeyDownEvent {
                keystroke: keystroke.clone(),
                is_held: false,
                prefer_character_input: false,
            });
            cx.simulate_event(KeyUpEvent { keystroke });
        }

        assert_eq!(button_clicks.get(), 2);
        assert_eq!(keyboard_events.get(), 2);
    }

    #[gpui::test]
    fn disabled_button_is_inert_and_blocks_parent_activation(cx: &mut TestAppContext) {
        let (cx, button_clicks, parent_clicks, _) = harness(cx, true);

        cx.simulate_click(point(px(10.), px(10.)), Modifiers::default());
        cx.update(|window, cx| window.focus_next(cx));
        cx.simulate_keystrokes("enter space");

        assert_eq!(button_clicks.get(), 0);
        assert_eq!(parent_clicks.get(), 0);
    }

    struct DisableDuringFocus {
        handles: [FocusHandle; 3],
        disabled: bool,
        activations: usize,
    }

    impl Render for DisableDuringFocus {
        fn render(&mut self, _: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
            div()
                .size_full()
                .flex()
                .tab_group()
                .child(
                    Button::new("before")
                        .track_focus(&self.handles[0])
                        .child("Before"),
                )
                .child(
                    Button::new("disable-self")
                        .track_focus(&self.handles[1])
                        .disabled(self.disabled)
                        .child("Disable self")
                        .on_click(cx.listener(|this, _, _, cx| {
                            this.disabled = true;
                            this.activations += 1;
                            cx.notify();
                        })),
                )
                .child(
                    Button::new("after")
                        .track_focus(&self.handles[2])
                        .child("After"),
                )
        }
    }

    fn press_transition_key(cx: &mut VisualTestContext, key: &str) {
        let keystroke =
            cx.update(|_, cx| Keystroke::parse_with_os(key, cx.platform_info().os).unwrap());
        cx.simulate_event(KeyDownEvent {
            keystroke: keystroke.clone(),
            is_held: false,
            prefer_character_input: false,
        });
        cx.simulate_event(KeyUpEvent { keystroke });
        cx.update(|window, cx| window.draw(cx).clear(cx));
    }

    #[gpui::test]
    fn disabling_focused_button_preserves_bidirectional_traversal(cx: &mut TestAppContext) {
        cx.update(crate::init);
        for (key, expected, back, opposite) in
            [("tab", 2, "shift-tab", 0), ("shift-tab", 0, "tab", 2)]
        {
            let handles = cx.update(|cx| std::array::from_fn(|_| cx.focus_handle()));
            let controls = cx.new(|_| DisableDuringFocus {
                handles: handles.clone(),
                disabled: false,
                activations: 0,
            });
            let (_, cx) =
                cx.add_window_view(|window, cx| crate::Root::new(controls.clone(), window, cx));
            cx.update(|window, cx| {
                window.activate_window();
                window.draw(cx).clear(cx);
                handles[0].focus(window, cx);
                window.draw(cx).clear(cx);
            });
            press_transition_key(cx, "tab");
            cx.update(|window, cx| {
                window.draw(cx).clear(cx);
                assert_eq!(window.focused(cx).as_ref(), Some(&handles[1]));
            });
            press_transition_key(cx, "space");
            cx.update(|window, cx| {
                window.draw(cx).clear(cx);
                assert!(controls.read(cx).disabled);
                assert_eq!(controls.read(cx).activations, 1);
            });
            press_transition_key(cx, "enter");
            press_transition_key(cx, "space");
            cx.update(|_, cx| {
                assert_eq!(controls.read(cx).activations, 1, "disabled stays inert");
            });
            press_transition_key(cx, key);
            cx.update(|window, cx| {
                window.draw(cx).clear(cx);
                assert_eq!(window.focused(cx).as_ref(), Some(&handles[expected]));
            });
            press_transition_key(cx, back);
            cx.update(|window, cx| {
                window.draw(cx).clear(cx);
                assert_eq!(window.focused(cx).as_ref(), Some(&handles[opposite]));
            });
            controls.update(cx, |this, cx| {
                this.disabled = false;
                cx.notify();
            });
            cx.update(|window, cx| window.draw(cx).clear(cx));
            press_transition_key(cx, key);
            cx.update(|window, cx| {
                window.draw(cx).clear(cx);
                assert_eq!(window.focused(cx).as_ref(), Some(&handles[1]));
            });
        }
    }

    #[gpui::test]
    fn fixed_height_button_centers_ordinary_child_geometry(cx: &mut TestAppContext) {
        type Captured = Arc<
            Mutex<(
                Option<gpui::Bounds<gpui::Pixels>>,
                Option<gpui::Bounds<gpui::Pixels>>,
            )>,
        >;

        struct AlignmentProbe {
            captured: Captured,
        }

        impl Render for AlignmentProbe {
            fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
                let root_capture = self.captured.clone();
                let child_capture = self.captured.clone();
                Button::new("alignment-button")
                    .w(px(120.))
                    .h(px(40.))
                    .child(
                        div()
                            .w(px(48.))
                            .h(px(12.))
                            .on_prepaint(move |bounds, _, _| {
                                child_capture.lock().unwrap().1 = Some(bounds);
                            }),
                    )
                    .on_prepaint(move |bounds, _, _| {
                        root_capture.lock().unwrap().0 = Some(bounds);
                    })
            }
        }

        let captured = Arc::new(Mutex::new((None, None)));
        let (_, context) = cx.add_window_view({
            let captured = captured.clone();
            move |_, _| AlignmentProbe { captured }
        });
        context.update(|window, cx| window.draw(cx).clear(cx));

        let (root, child) = *captured.lock().unwrap();
        let root = root.expect("button bounds");
        let child = child.expect("child bounds");
        assert_eq!(child.center(), root.center());
    }

    #[test]
    fn state_styling_methods_are_available_to_applications() {
        let _ = Button::new("states")
            .styles(|styles| {
                styles.disabled(|style| {
                    style
                        .opacity(0.5)
                        .when(true, |style| style.border_1())
                        .when_some(Some(0.4), |style, opacity| style.opacity(opacity))
                        .when_none(&None::<f32>, |style| style.rounded_sm())
                })
            })
            .hover(|style| style.opacity(0.9))
            .active(|style| style.opacity(0.8))
            .focus_visible(|style| style.opacity(0.7));
    }

    #[test]
    fn disabled_style_applies_only_while_disabled_and_then_wins() {
        let enabled = Button::new("enabled")
            .opacity(0.9)
            .styles(|styles| styles.disabled(|style| style.opacity(0.5)));
        assert_eq!(enabled.resolved_style().opacity, Some(0.9));

        let disabled = Button::new("disabled")
            .styles(|styles| styles.disabled(|style| style.opacity(0.5)))
            .opacity(0.9)
            .disabled(true);
        assert_eq!(disabled.resolved_style().opacity, Some(0.5));

        let semantic_only = Button::new("semantic-only")
            .styles(|styles| styles.disabled(|style| style.opacity(0.5)))
            .disabled(true);
        assert_eq!(semantic_only.resolved_style().opacity, Some(0.5));
    }

    #[test]
    fn selected_disabled_and_instance_styles_follow_the_shared_priority() {
        let selected_color = gpui::hsla(0.6, 0.7, 0.5, 1.0);
        let disabled_color = gpui::hsla(0.1, 0.2, 0.3, 0.5);
        let button = |selected, disabled| {
            Button::new("button")
                .selected(selected)
                .disabled(disabled)
                .styles(|styles| {
                    styles
                        .selected(|style| style.bg(selected_color))
                        .disabled(|style| style.bg(disabled_color))
                })
        };

        assert_eq!(button(false, false).resolved_style().background, None);
        assert_eq!(
            button(true, false).resolved_style().background,
            Some(selected_color.into())
        );
        assert_eq!(
            button(true, true).resolved_style().background,
            Some(disabled_color.into())
        );
        assert_eq!(
            button(true, true)
                .bg(selected_color)
                .resolved_style()
                .background,
            Some(disabled_color.into())
        );
    }

    #[gpui::test]
    fn accessibility_role_label_and_disabled_action_surface(cx: &mut TestAppContext) {
        type Captured = Arc<Mutex<Option<(accesskit::Node, accesskit::Node)>>>;

        struct A11yProbe {
            captured: Captured,
        }

        impl Render for A11yProbe {
            fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
                let captured = self.captured.clone();
                canvas(
                    move |_, window, cx| {
                        let mut info = |button: Button| {
                            let mut node = accesskit::Node::new(Role::Button);
                            button
                                .render(window, cx)
                                .into_element()
                                .write_a11y_info(&mut node);
                            node
                        };
                        let enabled = info(
                            Button::new("enabled")
                                .accessibility_label("Save")
                                .on_click(|_, _, _| {}),
                        );
                        let disabled = info(
                            Button::new("disabled")
                                .disabled(true)
                                .accessibility_label("Save")
                                .on_click(|_, _, _| {}),
                        );
                        *captured.lock().unwrap() = Some((enabled, disabled));
                    },
                    |_, _, _, _| {},
                )
            }
        }

        let captured: Captured = Arc::new(Mutex::new(None));
        let result = captured.clone();
        let (_, cx) = cx.add_window_view(move |_, _| A11yProbe { captured });
        cx.update(|window, cx| {
            window.draw(cx).clear(cx);
        });
        let (enabled, disabled) = result.lock().unwrap().take().unwrap();
        assert_eq!(enabled.role(), Role::Button);
        assert_eq!(enabled.label(), Some("Save"));
        assert!(enabled.supports_action(accesskit::Action::Click));

        assert_eq!(disabled.role(), Role::Button);
        assert!(!disabled.supports_action(accesskit::Action::Click));
        assert!(!enabled.is_disabled());
        assert!(disabled.is_disabled());
    }
}
