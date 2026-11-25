use std::rc::Rc;

use gpui::{
    Anchor, AnyElement, App, Context, DismissEvent, ElementId, EventEmitter, FocusHandle,
    Focusable, InteractiveElement as _, IntoElement, KeyBinding, MouseButton, ParentElement as _,
    Render, RenderOnce, Role, StatefulInteractiveElement as _, StyleRefinement, Styled,
    Subscription, Window, div, prelude::FluentBuilder as _,
};

use crate::{
    DeferredPopover, GlobalState, Popup, ResolvedPosition, Selectable, StyledExt as _,
    actions::{Cancel, Confirm},
};

const CONTEXT: &str = "Popover";
const CONTENT_CONTEXT: &str = "PopoverContent";

pub(crate) fn init(cx: &mut App) {
    cx.bind_keys([
        KeyBinding::new("escape", Cancel, Some(CONTEXT)),
        KeyBinding::new("enter", Confirm { secondary: false }, Some(CONTEXT)),
        KeyBinding::new("space", Confirm { secondary: false }, Some(CONTEXT)),
        KeyBinding::new("escape", Cancel, Some(CONTENT_CONTEXT)),
        // The content is still a descendant of the trigger's dispatch node.
        // Leave activation to its controls, not the trigger or an outer dialog.
        // More deeply scoped input bindings retain precedence.
        KeyBinding::new("enter", gpui::NoAction, Some(CONTENT_CONTEXT)),
        KeyBinding::new("space", gpui::NoAction, Some(CONTENT_CONTEXT)),
    ]);
}

type OpenChangeHandler = Rc<dyn Fn(&bool, &mut Window, &mut App)>;

/// State and focus lifecycle for an unstyled popover.
///
/// Applications own trigger/content construction, positioning, appearance, and
/// animation. This state owns the controlled open lifecycle, dismissal, focus
/// capture and restoration, and deferred-popup registration.
pub struct PopoverState {
    focus_handle: FocusHandle,
    tracked_focus_handle: Option<FocusHandle>,
    previous_focus_handle: Option<FocusHandle>,
    open: bool,
    on_open_change: Option<OpenChangeHandler>,
    dismiss_subscription: Option<Subscription>,
    /// Held while open, so that a state collected without being closed — this
    /// lives in element state — takes its registration with it.
    deferred_context: Option<DeferredPopover>,
}

impl PopoverState {
    pub fn new(default_open: bool, cx: &mut App) -> Self {
        Self {
            focus_handle: cx.focus_handle(),
            tracked_focus_handle: None,
            previous_focus_handle: None,
            open: default_open,
            on_open_change: None,
            dismiss_subscription: None,
            deferred_context: None,
        }
    }

    pub fn is_open(&self) -> bool {
        self.open
    }

    pub fn dismiss(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        if self.open {
            self.toggle_open(window, cx);
        }
    }

    pub fn show(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        if !self.open {
            self.toggle_open(window, cx);
        }
    }

    #[doc(hidden)]
    pub fn set_open(&mut self, open: bool, cx: &mut Context<Self>) {
        self.open = open;
        self.deferred_context = open.then(|| GlobalState::register_deferred_popover(cx));
    }

    #[doc(hidden)]
    pub fn sync_open(&mut self, open: bool, window: &mut Window, cx: &mut Context<Self>) {
        self.transition_to(open, false, window, cx);
    }

    #[doc(hidden)]
    pub fn toggle_open(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        self.transition_to(!self.open, true, window, cx);
    }

    fn transition_to(
        &mut self,
        opening: bool,
        announce: bool,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        if self.open == opening {
            return;
        }
        if opening {
            self.previous_focus_handle = window.focused(cx);
        }
        self.set_open(opening, cx);

        if self.open {
            // Weak: the subscription is stored on this state, so a strong
            // handle would keep the state, and its deferred-popover
            // registration, alive after its trigger is gone.
            let state = cx.entity().downgrade();
            self.tracked_focus_handle
                .clone()
                .unwrap_or_else(|| self.focus_handle.clone())
                .focus(window, cx);

            self.dismiss_subscription =
                Some(
                    window.subscribe(&cx.entity(), cx, move |_, _: &DismissEvent, window, cx| {
                        _ = state.update(cx, |state, cx| state.dismiss(window, cx));
                        window.refresh();
                    }),
                );
        } else {
            self.dismiss_subscription = None;
            let previous = self.previous_focus_handle.take();
            if self.focus_handle.contains_focused(window, cx) {
                match previous {
                    Some(previous) => previous.focus(window, cx),
                    // Nothing had focus when the popover opened, so nothing has it now. Left
                    // alone, focus would stay on the closed popover's own handle, which is no
                    // longer in the tree.
                    None => window.blur(cx),
                }
            }
        }

        if announce && let Some(callback) = self.on_open_change.as_ref() {
            callback(&opening, window, cx);
        }
        cx.notify();
    }

    #[doc(hidden)]
    pub fn track_focus(&mut self, focus_handle: Option<FocusHandle>) {
        self.tracked_focus_handle = focus_handle;
    }

    #[doc(hidden)]
    pub fn set_on_open_change(&mut self, handler: Option<OpenChangeHandler>) {
        self.on_open_change = handler;
    }

    #[doc(hidden)]
    pub fn on_action_cancel(&mut self, _: &Cancel, window: &mut Window, cx: &mut Context<Self>) {
        self.dismiss(window, cx);
    }
}

impl Focusable for PopoverState {
    fn focus_handle(&self, _: &App) -> FocusHandle {
        self.focus_handle.clone()
    }
}

impl Render for PopoverState {
    fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
        div()
    }
}

impl EventEmitter<DismissEvent> for PopoverState {}

type TriggerBuilder = Box<dyn FnOnce(bool, &Window, &App) -> AnyElement>;
type ContentBuilder =
    Box<dyn FnOnce(&mut PopoverState, &mut Window, &mut Context<PopoverState>) -> AnyElement>;

/// An unstyled popover owning trigger interaction, open state, dismissal, and focus.
///
/// Enter and Space on the trigger toggle the popover. Inside its content, those
/// keys belong to the focused control instead; Escape dismisses the popover and
/// restores the previous focus.
#[derive(IntoElement)]
pub struct Popover {
    id: ElementId,
    style: StyleRefinement,
    anchor: Anchor,
    offset: gpui::Pixels,
    on_position: Option<Box<dyn Fn(ResolvedPosition, gpui::Bounds<gpui::Pixels>)>>,
    default_open: bool,
    open: Option<bool>,
    tracked_focus_handle: Option<FocusHandle>,
    trigger: Option<TriggerBuilder>,
    content: Option<ContentBuilder>,
    mouse_button: MouseButton,
    overlay_closable: bool,
    on_open_change: Option<OpenChangeHandler>,
}

impl Popover {
    pub fn new(id: impl Into<ElementId>) -> Self {
        Self {
            id: id.into(),
            style: StyleRefinement::default(),
            anchor: Anchor::TopLeft,
            offset: gpui::px(0.),
            on_position: None,
            default_open: false,
            open: None,
            tracked_focus_handle: None,
            trigger: None,
            content: None,
            mouse_button: MouseButton::Left,
            overlay_closable: true,
            on_open_change: None,
        }
    }

    pub fn anchor(mut self, anchor: impl Into<Anchor>) -> Self {
        self.anchor = anchor.into();
        self
    }

    /// Gap from the trigger along the anchor's outward direction, zero by default.
    pub fn offset(mut self, offset: gpui::Pixels) -> Self {
        self.offset = offset;
        self
    }

    /// Observe geometry to supply presentation such as a pointer arrow.
    pub fn on_position(
        mut self,
        callback: impl Fn(ResolvedPosition, gpui::Bounds<gpui::Pixels>) + 'static,
    ) -> Self {
        self.on_position = Some(Box::new(callback));
        self
    }

    pub fn mouse_button(mut self, mouse_button: MouseButton) -> Self {
        self.mouse_button = mouse_button;
        self
    }

    pub fn trigger<T>(mut self, trigger: T) -> Self
    where
        T: Selectable + IntoElement + 'static,
    {
        self.trigger = Some(Box::new(|is_open, _, _| {
            let open = trigger.is_open();
            trigger.open(open || is_open).into_any_element()
        }));
        self
    }

    /// Supplies a trigger builder for higher-level presentation facades.
    #[doc(hidden)]
    pub fn trigger_with(
        mut self,
        trigger: impl FnOnce(bool, &Window, &App) -> AnyElement + 'static,
    ) -> Self {
        self.trigger = Some(Box::new(trigger));
        self
    }

    pub fn default_open(mut self, open: bool) -> Self {
        self.default_open = open;
        self
    }

    pub fn open(mut self, open: bool) -> Self {
        self.open = Some(open);
        self
    }

    pub fn track_focus(mut self, handle: &FocusHandle) -> Self {
        self.tracked_focus_handle = Some(handle.clone());
        self
    }

    pub fn overlay_closable(mut self, closable: bool) -> Self {
        self.overlay_closable = closable;
        self
    }

    pub fn on_open_change(
        mut self,
        callback: impl Fn(&bool, &mut Window, &mut App) + 'static,
    ) -> Self {
        self.on_open_change = Some(Rc::new(callback));
        self
    }

    pub fn content<F, E>(mut self, content: F) -> Self
    where
        E: IntoElement,
        F: FnOnce(&mut PopoverState, &mut Window, &mut Context<PopoverState>) -> E + 'static,
    {
        self.content = Some(Box::new(move |state, window, cx| {
            content(state, window, cx).into_any_element()
        }));
        self
    }
}

/// Styles the trigger container: the element that takes part in the parent
/// layout and whose bounds the popup is anchored to.
impl Styled for Popover {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl RenderOnce for Popover {
    fn render(self, window: &mut Window, cx: &mut App) -> impl IntoElement {
        let state = window.use_keyed_state(self.id.clone(), cx, |_, cx| {
            PopoverState::new(self.default_open, cx)
        });
        state.update(cx, |state, cx| {
            state.track_focus(self.tracked_focus_handle);
            state.set_on_open_change(self.on_open_change);
            if let Some(open) = self.open {
                state.sync_open(open, window, cx);
            }
        });

        let open = state.read(cx).is_open();
        let focus_handle = state.read(cx).focus_handle(cx);
        let Some(trigger) = self.trigger else {
            return div().id("empty").into_any_element();
        };
        let parent_view_id = window.current_view();
        let popup = Popup::new(self.id, trigger(open, window, cx))
            .refine_style(&self.style)
            .anchor(self.anchor)
            .offset(self.offset)
            .when_some(self.on_position, |this, callback| {
                this.on_position(callback)
            })
            .key_context(CONTEXT)
            .on_action({
                let state = state.clone();
                move |_: &Confirm, window, cx| {
                    state.update(cx, |state, cx| state.toggle_open(window, cx));
                    cx.notify(parent_view_id);
                }
            })
            .on_mouse_down(self.mouse_button, {
                let state = state.clone();
                move |_, window, cx| {
                    cx.stop_propagation();
                    state.update(cx, |state, cx| {
                        if state.is_open() == open {
                            state.toggle_open(window, cx);
                        }
                    });
                    cx.notify(parent_view_id);
                }
            });
        if !open {
            return popup.into_any_element();
        }

        let content = div()
            .id("content")
            // A popover surface is a non-modal dialog: it takes focus and is
            // dismissed with Escape, which is what this role tells assistive
            // technology to expect.
            .role(Role::Dialog)
            .occlude()
            .tab_group()
            .track_focus(&focus_handle)
            .key_context(CONTENT_CONTEXT)
            .on_action(window.listener_for(&state, PopoverState::on_action_cancel))
            .when_some(self.content, |this, content| {
                this.child(state.update(cx, |state, cx| (content)(state, window, cx)))
            })
            .when(self.overlay_closable, |this| {
                this.on_mouse_down_out({
                    let state = state.clone();
                    move |_, window, cx| {
                        state.update(cx, |state, cx| state.dismiss(window, cx));
                        cx.notify(parent_view_id);
                    }
                })
            });
        popup.content(content).into_any_element()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use gpui::{AppContext as _, Context, Render, point, px};
    use std::{cell::RefCell, rc::Rc};

    /// Popover state lives in element state, which is collected as soon as it
    /// stops being rendered — a trigger scrolled out of a virtual list, a panel
    /// closed with its menu open. A registration that outlived it would leave
    /// the application believing a popup is open for the rest of the session.
    #[gpui::test]
    fn a_state_dropped_while_open_closes_the_deferred_context(cx: &mut gpui::TestAppContext) {
        let state = cx.update(|cx| {
            GlobalState::init(cx);
            let state = cx.new(|cx| PopoverState::new(false, cx));
            state.update(cx, |state, cx| state.set_open(true, cx));
            assert!(GlobalState::is_in_deferred_context(cx));
            state
        });

        cx.update(|_| drop(state));
        cx.update(|cx| assert!(!GlobalState::is_in_deferred_context(cx)));
    }

    #[gpui::test]
    fn open_state_registers_and_unregisters_deferred_context(cx: &mut gpui::TestAppContext) {
        cx.update(|cx| {
            GlobalState::init(cx);
            let state = cx.new(|cx| PopoverState::new(false, cx));

            state.update(cx, |state, cx| state.set_open(true, cx));
            assert!(state.read(cx).is_open());
            assert!(GlobalState::is_in_deferred_context(cx));

            state.update(cx, |state, cx| state.set_open(false, cx));
            assert!(!state.read(cx).is_open());
            assert!(!GlobalState::is_in_deferred_context(cx));
        });
    }

    struct PopoverHarness {
        changes: Rc<RefCell<Vec<bool>>>,
        default_open: bool,
    }

    struct KeyboardPopoverHarness {
        trigger_focus: FocusHandle,
    }

    impl Render for KeyboardPopoverHarness {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            Popover::new("keyboard-popover")
                .trigger(
                    crate::Button::new("keyboard-trigger")
                        .track_focus(&self.trigger_focus)
                        .child("Open"),
                )
                .content(|_, _, _| {
                    div()
                        .debug_selector(|| "keyboard-popover-content".into())
                        .size(px(40.))
                })
        }
    }

    impl Render for PopoverHarness {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            let changes = self.changes.clone();
            Popover::new("base-popover")
                .default_open(self.default_open)
                .trigger_with(|_, _, _| div().child("Open").into_any_element())
                .content(|_, _, _| {
                    div()
                        .debug_selector(|| "base-popover-content".into())
                        .size(px(40.))
                })
                .on_open_change(move |open, _, _| changes.borrow_mut().push(*open))
        }
    }

    #[gpui::test]
    fn unstyled_popover_owns_pointer_open_and_outside_dismiss(cx: &mut gpui::TestAppContext) {
        cx.update(crate::init);
        let changes = Rc::new(RefCell::new(Vec::new()));
        let (_, cx) = cx.add_window_view({
            let changes = changes.clone();
            move |_, _| PopoverHarness {
                changes,
                default_open: false,
            }
        });
        cx.update(|window, cx| window.draw(cx).clear(cx));
        cx.update(|window, cx| assert!(window.focused(cx).is_none(), "nothing has focus yet"));

        cx.simulate_click(point(px(20.), px(10.)), Default::default());
        cx.update(|window, cx| window.draw(cx).clear(cx));
        assert!(cx.debug_bounds("base-popover-content").is_some());
        cx.update(|window, cx| assert!(window.focused(cx).is_some(), "the popover takes focus"));

        cx.simulate_click(point(px(300.), px(300.)), Default::default());
        cx.update(|window, cx| window.draw(cx).clear(cx));
        assert!(cx.debug_bounds("base-popover-content").is_none());
        assert_eq!(&*changes.borrow(), &[true, false]);
        // Nothing had focus when the popover opened, so nothing has it now, not the closed
        // popover's own handle.
        cx.update(|window, cx| {
            assert!(
                window.focused(cx).is_none(),
                "focus stays on {:?}",
                window.focused(cx)
            )
        });
    }

    #[gpui::test]
    fn default_open_renders_content_without_activation(cx: &mut gpui::TestAppContext) {
        cx.update(crate::init);
        let (_, cx) = cx.add_window_view(|_, _| PopoverHarness {
            changes: Rc::new(RefCell::new(Vec::new())),
            default_open: true,
        });
        cx.update(|window, cx| window.draw(cx).clear(cx));
        cx.update(|window, cx| window.draw(cx).clear(cx));
        assert!(cx.debug_bounds("base-popover-content").is_some());
    }

    /// A trigger that keeps "open" and "selected" apart, the way a downstream
    /// sidebar row does: it is selected when it is the current view, and open
    /// only while its popover is showing.
    #[derive(IntoElement)]
    struct RecordingTrigger {
        calls: Rc<RefCell<Vec<(&'static str, bool)>>>,
        selected: bool,
        open: bool,
    }

    impl Selectable for RecordingTrigger {
        fn selected(mut self, selected: bool) -> Self {
            self.calls.borrow_mut().push(("selected", selected));
            self.selected = selected;
            self
        }

        fn is_selected(&self) -> bool {
            self.selected
        }

        fn open(mut self, open: bool) -> Self {
            self.calls.borrow_mut().push(("open", open));
            self.open = open;
            self
        }

        fn is_open(&self) -> bool {
            self.open
        }
    }

    impl RenderOnce for RecordingTrigger {
        fn render(self, _: &mut Window, _: &mut App) -> impl IntoElement {
            div().size(px(40.)).child("Open")
        }
    }

    struct RecordingTriggerHarness {
        calls: Rc<RefCell<Vec<(&'static str, bool)>>>,
    }

    impl Render for RecordingTriggerHarness {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            Popover::new("recording-popover")
                .trigger(RecordingTrigger {
                    calls: self.calls.clone(),
                    selected: false,
                    open: false,
                })
                .content(|_, _, _| div().size(px(40.)))
        }
    }

    #[gpui::test]
    fn an_open_popover_tells_its_trigger_it_is_open_not_selected(cx: &mut gpui::TestAppContext) {
        cx.update(crate::init);
        let calls = Rc::new(RefCell::new(Vec::new()));
        let (_, cx) = cx.add_window_view({
            let calls = calls.clone();
            move |_, _| RecordingTriggerHarness { calls }
        });
        cx.update(|window, cx| window.draw(cx).clear(cx));
        calls.borrow_mut().clear();

        cx.simulate_click(point(px(20.), px(10.)), Default::default());
        cx.update(|window, cx| window.draw(cx).clear(cx));

        let calls = calls.borrow();
        assert!(
            calls.contains(&("open", true)),
            "an open popover marks its trigger open, got {calls:?}"
        );
        assert!(
            !calls.iter().any(|(name, _)| *name == "selected"),
            "opening must not touch the trigger's own selection, got {calls:?}"
        );
    }

    #[gpui::test]
    fn keyboard_activation_opens_the_popover(cx: &mut gpui::TestAppContext) {
        cx.update(crate::init);
        let (view, cx) = cx.add_window_view(|_, cx| KeyboardPopoverHarness {
            trigger_focus: cx.focus_handle(),
        });
        cx.update(|window, cx| window.draw(cx).clear(cx));

        cx.update(|window, cx| {
            let focus = view.read(cx).trigger_focus.clone();
            focus.focus(window, cx);
        });
        cx.simulate_keystrokes("enter");
        cx.update(|window, cx| window.draw(cx).clear(cx));

        assert!(cx.debug_bounds("keyboard-popover-content").is_some());
    }
}
