use crate::TestSupportExt as _;
use std::{
    cell::{Cell, RefCell},
    rc::Rc,
};

use gpui::{
    AnyElement, App, ClickEvent, FocusHandle, InteractiveElement as _, IntoElement, KeyBinding,
    MouseButton, ParentElement, Pixels, RenderOnce, Role, StatefulInteractiveElement as _,
    StyleRefinement, Styled, Window, anchored, deferred, div, point, prelude::FluentBuilder as _,
    px,
};
use smallvec::SmallVec;

use crate::actions::{Cancel, Confirm};
use crate::{FocusTrapElement as _, StyledExt as _};

const CONTEXT: &str = "Dialog";
type Decision = Rc<dyn Fn(&ClickEvent, &mut Window, &mut App) -> bool>;
type Closed = Rc<dyn Fn(&ClickEvent, &mut Window, &mut App)>;
type CloseRequest = Rc<dyn Fn(bool, &mut Window, &mut App)>;
type OpenRequest = Rc<dyn Fn(&mut Window, &mut App)>;
type OpenChange = Rc<dyn Fn(bool, DialogChangeReason, &mut Window, &mut App)>;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DialogChangeReason {
    TriggerPress,
    BackdropPress,
    Cancel,
    Confirm,
    Imperative,
}

#[derive(Clone)]
pub struct DialogHandle {
    open: Rc<Cell<bool>>,
    on_open_change: Rc<RefCell<Option<OpenChange>>>,
}

impl DialogHandle {
    pub fn new(open: bool) -> Self {
        Self {
            open: Rc::new(Cell::new(open)),
            on_open_change: Rc::new(RefCell::new(None)),
        }
    }
    pub fn is_open(&self) -> bool {
        self.open.get()
    }
    pub fn open(&self, window: &mut Window, cx: &mut App) {
        self.set_open(true, DialogChangeReason::Imperative, window, cx);
    }
    pub fn close(&self, window: &mut Window, cx: &mut App) {
        self.set_open(false, DialogChangeReason::Imperative, window, cx);
    }
    pub(crate) fn set_open(
        &self,
        open: bool,
        reason: DialogChangeReason,
        window: &mut Window,
        cx: &mut App,
    ) {
        if self.open.replace(open) == open {
            return;
        }
        let callback = self.on_open_change.borrow().clone();
        if let Some(callback) = callback {
            callback(open, reason, window, cx);
        }
        window.refresh();
    }
}

fn request_open_change(
    handle: &Option<DialogHandle>,
    callback: &Option<OpenChange>,
    open: bool,
    reason: DialogChangeReason,
    window: &mut Window,
    cx: &mut App,
) {
    if let Some(handle) = handle {
        handle.set_open(open, reason, window, cx);
    } else if let Some(callback) = callback {
        callback(open, reason, window, cx);
    }
}

pub fn init(cx: &mut App) {
    cx.bind_keys([
        KeyBinding::new("escape", Cancel, Some(CONTEXT)),
        KeyBinding::new("enter", Confirm { secondary: false }, Some(CONTEXT)),
    ]);
}

impl Dialog {
    pub fn on_ok(
        mut self,
        handler: impl Fn(&ClickEvent, &mut Window, &mut App) -> bool + 'static,
    ) -> Self {
        self.on_ok = Rc::new(handler);
        self
    }

    pub fn on_cancel(
        mut self,
        handler: impl Fn(&ClickEvent, &mut Window, &mut App) -> bool + 'static,
    ) -> Self {
        self.on_cancel = Rc::new(handler);
        self
    }

    pub fn on_close(
        mut self,
        handler: impl Fn(&ClickEvent, &mut Window, &mut App) + 'static,
    ) -> Self {
        self.on_close = Rc::new(handler);
        self
    }
}

/// Unstyled modal host owning focus, keyboard actions, dismissal, and callback ordering.
#[derive(IntoElement)]
pub struct Dialog {
    style: StyleRefinement,
    focus: FocusHandle,
    role: Role,
    layer: usize,
    keyboard: bool,
    overlay_closable: bool,
    topmost: bool,
    dismiss_below_y: Pixels,
    backdrop: Option<AnyElement>,
    popup: Option<AnyElement>,
    children: SmallVec<[AnyElement; 2]>,
    on_ok: Decision,
    on_cancel: Decision,
    on_close: Closed,
    request_close: CloseRequest,
    handle: Option<DialogHandle>,
    open: bool,
    on_open_change: Option<OpenChange>,
}

/// Unstyled trigger that owns pointer activation for opening a dialog.
#[derive(IntoElement)]
pub struct DialogTrigger {
    trigger: AnyElement,
    open: OpenRequest,
    handle: Option<DialogHandle>,
}

impl DialogTrigger {
    pub fn new(trigger: impl IntoElement) -> Self {
        Self {
            trigger: trigger.into_any_element(),
            open: Rc::new(|_, _| {}),
            handle: None,
        }
    }
    pub fn handle(mut self, handle: DialogHandle) -> Self {
        self.handle = Some(handle);
        self
    }

    pub fn on_open(mut self, open: impl Fn(&mut Window, &mut App) + 'static) -> Self {
        self.open = Rc::new(open);
        self
    }
}

impl RenderOnce for DialogTrigger {
    fn render(self, _: &mut Window, _: &mut App) -> impl IntoElement {
        div()
            .on_mouse_down(MouseButton::Left, move |_, window, cx| {
                if let Some(handle) = self.handle.as_ref() {
                    handle.set_open(true, DialogChangeReason::TriggerPress, window, cx);
                }
                (self.open)(window, cx);
                cx.stop_propagation();
            })
            .child(self.trigger)
    }
}

macro_rules! dialog_part {
    ($(#[$meta:meta])* $name:ident, $id:literal) => {
        dialog_part!($(#[$meta])* $name, $id, false);
    };
    ($(#[$meta:meta])* $name:ident, $id:literal, $occlude:literal) => {
        $(#[$meta])*
        #[derive(IntoElement)]
        pub struct $name {
            style: StyleRefinement,
            children: SmallVec<[AnyElement; 2]>,
        }

        impl $name {
            pub fn new() -> Self {
                Self {
                    style: StyleRefinement::default(),
                    children: SmallVec::new(),
                }
            }
        }

        impl Default for $name {
            fn default() -> Self {
                Self::new()
            }
        }

        impl Styled for $name {
            fn style(&mut self) -> &mut StyleRefinement {
                &mut self.style
            }
        }

        impl ParentElement for $name {
            fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
                self.children.extend(elements);
            }
        }

        impl RenderOnce for $name {
            fn render(self, _: &mut Window, _: &mut App) -> impl IntoElement {
                div()
                    .id($id)
                    // The popup sits over the backdrop, whose press dismisses
                    // the dialog, so it keeps presses on itself from falling through.
                    .when($occlude, |this| this.occlude())
                    .children(self.children)
                    .refine_style(&self.style)
            }
        }
    };
}

dialog_part!(
    /// Unstyled backdrop part rendered behind a dialog popup.
    DialogBackdrop,
    "dialog-backdrop"
);

dialog_part!(
    /// Unstyled popup part containing dialog content.
    DialogPopup,
    "dialog-popup",
    true
);

/// Unstyled title slot for a dialog surface.
#[derive(IntoElement)]
pub struct DialogTitle {
    base: gpui::Div,
    style: StyleRefinement,
    children: SmallVec<[AnyElement; 2]>,
}

impl DialogTitle {
    pub fn new() -> Self {
        Self {
            base: div(),
            style: StyleRefinement::default(),
            children: SmallVec::new(),
        }
    }
}

impl Default for DialogTitle {
    fn default() -> Self {
        Self::new()
    }
}
impl Styled for DialogTitle {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}
impl ParentElement for DialogTitle {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}
impl RenderOnce for DialogTitle {
    fn render(self, _: &mut Window, _: &mut App) -> impl IntoElement {
        self.base
            .id("dialog-title")
            .children(self.children)
            .refine_style(&self.style)
    }
}

/// Unstyled descriptive-content slot for a dialog surface.
#[derive(IntoElement)]
pub struct DialogDescription {
    base: gpui::Div,
    style: StyleRefinement,
    children: SmallVec<[AnyElement; 2]>,
}

impl DialogDescription {
    pub fn new() -> Self {
        Self {
            base: div(),
            style: StyleRefinement::default(),
            children: SmallVec::new(),
        }
    }
}

impl Default for DialogDescription {
    fn default() -> Self {
        Self::new()
    }
}
impl Styled for DialogDescription {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}
impl ParentElement for DialogDescription {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}
impl RenderOnce for DialogDescription {
    fn render(self, _: &mut Window, _: &mut App) -> impl IntoElement {
        self.base
            .id("dialog-description")
            .children(self.children)
            .refine_style(&self.style)
    }
}

/// Wrapper that dispatches the dialog cancel action when activated.
#[derive(IntoElement)]
pub struct DialogClose {
    style: StyleRefinement,
    children: SmallVec<[AnyElement; 1]>,
    trigger: Option<AnyElement>,
    /// The focus node activation dispatches from, filled at render and read
    /// when clicked, so the trigger built earlier reaches it too.
    anchor: Rc<RefCell<Option<FocusHandle>>>,
}

impl DialogClose {
    pub fn new() -> Self {
        Self {
            style: StyleRefinement::default(),
            children: SmallVec::new(),
            trigger: None,
            anchor: Rc::default(),
        }
    }

    /// Styles a button with the accessible name "Close" and cancel activation.
    ///
    /// The supplied button already supports pointer, keyboard, and accessibility
    /// activation. The builder only needs to supply presentation.
    /// The wrapper does not also handle clicks when a trigger is supplied.
    pub fn trigger<E: IntoElement>(mut self, build: impl FnOnce(crate::Button) -> E) -> Self {
        let anchor = self.anchor.clone();
        let button = crate::Button::new("close")
            .accessibility_label("Close")
            .on_click(move |_, window, cx| Self::activate(&anchor, window, cx));
        self.trigger = Some(build(button).into_any_element());
        self
    }

    /// Dispatches [`Cancel`] from the control's own focus node, so it reaches
    /// the dialog the control sits in whatever holds focus at that moment: a
    /// surface that keeps taking focus back (a native web view, an
    /// always-on-top window) would otherwise leave the control inert.
    fn activate(anchor: &RefCell<Option<FocusHandle>>, window: &mut Window, cx: &mut App) {
        // Clone out before dispatching so the dialog's handlers never run
        // while the cell is borrowed.
        let anchor = anchor.borrow().clone();
        match anchor {
            Some(anchor) => anchor.dispatch_action(&Cancel, window, cx),
            None => window.dispatch_action(Box::new(Cancel), cx),
        }
    }
}
impl Default for DialogClose {
    fn default() -> Self {
        Self::new()
    }
}
impl ParentElement for DialogClose {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}
impl Styled for DialogClose {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}
impl RenderOnce for DialogClose {
    fn render(self, window: &mut Window, cx: &mut App) -> impl IntoElement {
        let anchor = window
            .use_keyed_state("dialog-close-anchor", cx, |_, cx| cx.focus_handle())
            .read(cx)
            .clone();
        *self.anchor.borrow_mut() = Some(anchor.clone());
        let cell = self.anchor;
        div()
            .id("dialog-close")
            // A zero-size, out-of-flow node that tracks the anchor: it is never
            // hovered, so it takes no focus on its own and does not enter the
            // Tab order, but it sits inside this dialog's dispatch path.
            .child(div().absolute().size_0().track_focus(&anchor))
            .when(self.trigger.is_none(), |this| {
                this.on_click(move |_, window, cx| Self::activate(&cell, window, cx))
            })
            .children(self.trigger)
            .children(self.children)
            .refine_style(&self.style)
    }
}

impl Dialog {
    pub fn new(cx: &mut App) -> Self {
        Self {
            style: StyleRefinement::default(),
            focus: cx.focus_handle(),
            role: Role::Dialog,
            layer: 0,
            keyboard: true,
            overlay_closable: true,
            topmost: true,
            dismiss_below_y: px(0.),
            backdrop: None,
            popup: None,
            children: SmallVec::new(),
            on_ok: Rc::new(|_, _, _| true),
            on_cancel: Rc::new(|_, _, _| true),
            on_close: Rc::new(|_, _, _| {}),
            request_close: Rc::new(|_, _, _| {}),
            handle: None,
            open: true,
            on_open_change: None,
        }
    }
    pub fn open(mut self, open: bool) -> Self {
        self.open = open;
        self
    }
    pub fn handle(mut self, handle: DialogHandle) -> Self {
        if let Some(callback) = self.on_open_change.as_ref() {
            *handle.on_open_change.borrow_mut() = Some(callback.clone());
        }
        self.handle = Some(handle);
        self
    }
    pub fn on_open_change(
        mut self,
        handler: impl Fn(bool, DialogChangeReason, &mut Window, &mut App) + 'static,
    ) -> Self {
        let handler: OpenChange = Rc::new(handler);
        if let Some(handle) = self.handle.as_ref() {
            *handle.on_open_change.borrow_mut() = Some(handler.clone());
        }
        self.on_open_change = Some(handler);
        self
    }

    pub fn backdrop(mut self, element: impl IntoElement) -> Self {
        self.backdrop = Some(element.into_any_element());
        self
    }
    pub fn popup(mut self, element: impl IntoElement) -> Self {
        self.popup = Some(element.into_any_element());
        self
    }
    pub fn close_on_escape(mut self, value: bool) -> Self {
        self.keyboard = value;
        self
    }
    pub fn close_on_backdrop_press(mut self, value: bool) -> Self {
        self.overlay_closable = value;
        self
    }
    pub fn dismiss_below_y(mut self, value: Pixels) -> Self {
        self.dismiss_below_y = value;
        self
    }
    pub(crate) fn role(mut self, role: Role) -> Self {
        self.role = role;
        self
    }
    #[doc(hidden)]
    pub fn layer(mut self, index: usize, topmost: bool) -> Self {
        self.layer = index;
        self.topmost = topmost;
        self
    }
    #[doc(hidden)]
    pub fn focus_handle(mut self, value: FocusHandle) -> Self {
        self.focus = value;
        self
    }
    #[doc(hidden)]
    pub fn request_close(
        mut self,
        handler: impl Fn(bool, &mut Window, &mut App) + 'static,
    ) -> Self {
        self.request_close = Rc::new(handler);
        self
    }
}

impl Styled for Dialog {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}
impl ParentElement for Dialog {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

impl RenderOnce for Dialog {
    fn render(self, window: &mut Window, _: &mut App) -> impl IntoElement {
        let open = self
            .handle
            .as_ref()
            .map_or(self.open, DialogHandle::is_open);
        if !open {
            return div().into_any_element();
        }
        let request_close = self.request_close;
        let cancel = self.on_cancel.clone();
        let confirm = self.on_ok.clone();
        let closed = self.on_close.clone();
        let overlay_closable = self.overlay_closable && self.topmost;
        let dismiss_below_y = self.dismiss_below_y;
        let escape_handle = self.handle.clone();
        let confirm_handle = self.handle.clone();
        let backdrop_handle = self.handle.clone();
        let escape_change = self.on_open_change.clone();
        let confirm_change = self.on_open_change.clone();
        let backdrop_change = self.on_open_change.clone();
        let viewport = window.viewport_size();

        deferred(
            anchored().position(point(px(0.), px(0.))).child(
                div()
                    .id(("dialog-host", self.layer))
                    .test_support()
                    .absolute()
                    .top_0()
                    .left_0()
                    .w(viewport.width)
                    .h(viewport.height)
                    // A popup in normal flow lands centered; `refine_style`
                    // below lets the caller lay the host out differently.
                    .flex()
                    .items_center()
                    .justify_center()
                    .role(self.role)
                    .track_focus(&self.focus)
                    .focus_trap(format!("dialog-{}", self.layer), &self.focus)
                    .when(self.keyboard, |this| this.key_context(CONTEXT))
                    .map(|this| {
                        let request_cancel = request_close.clone();
                        let request_confirm = request_close.clone();
                        let closed_cancel = closed.clone();
                        this.on_action(move |_: &Cancel, window, cx| {
                            let event = ClickEvent::default();
                            if cancel(&event, window, cx) {
                                request_open_change(
                                    &escape_handle,
                                    &escape_change,
                                    false,
                                    DialogChangeReason::Cancel,
                                    window,
                                    cx,
                                );
                                request_cancel(false, window, cx);
                                closed_cancel(&event, window, cx);
                            }
                        })
                        .on_action(move |_: &Confirm, window, cx| {
                            let event = ClickEvent::default();
                            if confirm(&event, window, cx) {
                                request_open_change(
                                    &confirm_handle,
                                    &confirm_change,
                                    false,
                                    DialogChangeReason::Confirm,
                                    window,
                                    cx,
                                );
                                request_confirm(true, window, cx);
                                closed(&event, window, cx);
                            }
                        })
                    })
                    .when_some(self.backdrop, |this, backdrop| {
                        let cancel = self.on_cancel.clone();
                        let closed = self.on_close.clone();
                        let request_close = request_close.clone();
                        this.child(
                            div()
                                // The backdrop covers the host, so a caller's
                                // `absolute()` surface has a box to fill.
                                .absolute()
                                .inset_0()
                                .on_any_mouse_down(move |event, window, cx| {
                                    if event.position.y < dismiss_below_y {
                                        return;
                                    }
                                    let button = event.button;
                                    cx.stop_propagation();
                                    let event = ClickEvent::default();
                                    if button == MouseButton::Left
                                        && overlay_closable
                                        && cancel(&event, window, cx)
                                    {
                                        request_open_change(
                                            &backdrop_handle,
                                            &backdrop_change,
                                            false,
                                            DialogChangeReason::BackdropPress,
                                            window,
                                            cx,
                                        );
                                        request_close(false, window, cx);
                                        closed(&event, window, cx);
                                    }
                                })
                                .child(backdrop),
                        )
                    })
                    .children(self.popup)
                    .children(self.children)
                    .refine_style(&self.style),
            ),
        )
        .with_priority(10 + self.layer)
        .into_any_element()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use gpui::{Context, Render, point};
    use std::{cell::RefCell, rc::Rc};

    #[gpui::test]
    fn close_trigger_supplies_accessible_button(cx: &mut gpui::TestAppContext) {
        use gpui::{Element as _, accesskit, canvas};
        use std::sync::{Arc, Mutex};

        struct Probe(Arc<Mutex<Option<accesskit::Node>>>);
        impl Render for Probe {
            fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
                let captured = self.0.clone();
                canvas(
                    move |_, window, cx| {
                        DialogClose::new().trigger(|button| {
                            let element = button.render(window, cx).into_element();
                            let mut node = accesskit::Node::new(element.a11y_role().unwrap());
                            element.write_a11y_info(&mut node);
                            *captured.lock().unwrap() = Some(node);
                            element
                        });
                    },
                    |_, _, _, _| {},
                )
            }
        }

        let captured = Arc::new(Mutex::new(None));
        let result = captured.clone();
        let (_, cx) = cx.add_window_view(move |_, _| Probe(captured));
        cx.update(|window, cx| window.draw(cx).clear(cx));
        let node = result.lock().unwrap().take().unwrap();
        assert_eq!(node.role(), Role::Button);
        assert_eq!(node.label(), Some("Close"));
        assert!(node.supports_action(accesskit::Action::Click));
    }

    #[gpui::test]
    fn close_trigger_activates_once_and_respects_cancel_veto(cx: &mut gpui::TestAppContext) {
        use gpui::{KeyDownEvent, KeyUpEvent, Keystroke};

        struct Harness {
            focus: FocusHandle,
            button_focus: FocusHandle,
            handle: DialogHandle,
            attempts: Rc<Cell<usize>>,
        }
        impl Render for Harness {
            fn render(&mut self, _: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
                let attempts = self.attempts.clone();
                let button_focus = self.button_focus.clone();
                Dialog::new(cx)
                    .handle(self.handle.clone())
                    .focus_handle(self.focus.clone())
                    .on_cancel(move |_, _, _| {
                        attempts.set(attempts.get() + 1);
                        attempts.get() > 1
                    })
                    .popup(
                        DialogClose::new().trigger(move |button| {
                            button.size(px(100.)).track_focus(&button_focus)
                        }),
                    )
            }
        }

        cx.update(crate::init);
        let handle = DialogHandle::new(true);
        let attempts = Rc::new(Cell::new(0));
        let (view, cx) = cx.add_window_view({
            let handle = handle.clone();
            let attempts = attempts.clone();
            move |_, cx| Harness {
                focus: cx.focus_handle(),
                button_focus: cx.focus_handle(),
                handle,
                attempts,
            }
        });
        let viewport = cx.update(|window, cx| {
            view.read(cx).focus.clone().focus(window, cx);
            window.draw(cx).clear(cx);
            window.viewport_size()
        });
        let popup_center = point(viewport.width / 2., viewport.height / 2.);
        cx.simulate_click(popup_center, Default::default());
        cx.run_until_parked();
        assert_eq!(attempts.get(), 1);
        assert!(handle.is_open(), "on_cancel can veto pointer dismissal");

        cx.update(|window, cx| {
            view.read(cx).button_focus.clone().focus(window, cx);
            window.draw(cx).clear(cx);
        });
        let keystroke = Keystroke::parse("space").unwrap();
        cx.simulate_event(KeyDownEvent {
            keystroke: keystroke.clone(),
            is_held: false,
            prefer_character_input: false,
        });
        cx.simulate_event(KeyUpEvent { keystroke });
        cx.run_until_parked();
        assert_eq!(attempts.get(), 2);
        assert!(!handle.is_open(), "Space uses the same cancel decision");
    }

    struct TriggerHarness {
        handle: DialogHandle,
    }
    impl Render for TriggerHarness {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            DialogTrigger::new(div().size(px(100.))).handle(self.handle.clone())
        }
    }

    #[gpui::test]
    fn trigger_opens_shared_handle_and_reports_reason(cx: &mut gpui::TestAppContext) {
        let handle = DialogHandle::new(false);
        let changes = Rc::new(RefCell::new(Vec::new()));
        *handle.on_open_change.borrow_mut() = Some({
            let changes = changes.clone();
            Rc::new(move |open, reason, _, _| changes.borrow_mut().push((open, reason)))
        });
        let (_, cx) = cx.add_window_view({
            let handle = handle.clone();
            move |_, _| TriggerHarness { handle }
        });
        cx.update(|window, cx| window.draw(cx).clear(cx));
        cx.simulate_click(point(px(20.), px(20.)), Default::default());

        assert!(handle.is_open());
        assert_eq!(
            &*changes.borrow(),
            &[(true, DialogChangeReason::TriggerPress)]
        );
    }

    /// The backdrop is the dimming surface every caller hands over as an
    /// `absolute()` element, so it has to have the host's box to resolve
    /// against — a collapsed wrapper leaves it zero-sized and invisible.
    #[gpui::test]
    fn the_backdrop_fills_the_host(cx: &mut gpui::TestAppContext) {
        use gpui::{Bounds, canvas};
        use std::cell::Cell;

        struct Harness {
            focus: FocusHandle,
            bounds: Rc<Cell<Bounds<Pixels>>>,
        }
        impl Render for Harness {
            fn render(&mut self, _: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
                let bounds = self.bounds.clone();
                Dialog::new(cx)
                    .open(true)
                    .focus_handle(self.focus.clone())
                    .backdrop(
                        canvas(
                            move |bounds_of_backdrop, _, _| bounds.set(bounds_of_backdrop),
                            |_, _, _, _| {},
                        )
                        .absolute()
                        .size_full(),
                    )
                    .popup(div().size(px(100.)))
            }
        }

        cx.update(crate::init);
        let bounds = Rc::new(Cell::new(Bounds::default()));
        let (_, cx) = cx.add_window_view({
            let bounds = bounds.clone();
            move |_, cx| Harness {
                focus: cx.focus_handle(),
                bounds,
            }
        });
        let viewport = cx.update(|window, cx| {
            let viewport = window.viewport_size();
            window.draw(cx).clear(cx);
            viewport
        });

        assert_eq!(
            bounds.get().size,
            viewport,
            "a zero-sized backdrop paints no overlay behind the dialog"
        );
    }

    /// The backdrop sits under the popup, so a press on the popup must not
    /// reach it and dismiss the dialog.
    #[gpui::test]
    fn pressing_the_popup_does_not_dismiss(cx: &mut gpui::TestAppContext) {
        struct Harness(DialogHandle);
        impl Render for Harness {
            fn render(&mut self, _: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
                Dialog::new(cx)
                    .handle(self.0.clone())
                    .backdrop(div().absolute().size_full())
                    .popup(DialogPopup::new().size(px(100.)))
            }
        }

        cx.update(crate::init);
        let handle = DialogHandle::new(true);
        let (_, cx) = cx.add_window_view({
            let handle = handle.clone();
            move |_, _| Harness(handle)
        });
        let viewport = cx.update(|window, cx| {
            window.draw(cx).clear(cx);
            window.viewport_size()
        });

        cx.simulate_click(
            point(viewport.width / 2., viewport.height / 2.),
            Default::default(),
        );
        assert!(
            handle.is_open(),
            "a press on the popup keeps the dialog open"
        );

        cx.simulate_click(point(px(5.), px(5.)), Default::default());
        assert!(!handle.is_open(), "a press on the backdrop still dismisses");
    }

    #[gpui::test]
    fn the_popup_is_centered_by_default(cx: &mut gpui::TestAppContext) {
        use gpui::{Bounds, canvas};
        use std::cell::Cell;

        struct Harness(Rc<Cell<Bounds<Pixels>>>);
        impl Render for Harness {
            fn render(&mut self, _: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
                let bounds = self.0.clone();
                Dialog::new(cx).popup(
                    canvas(move |popup, _, _| bounds.set(popup), |_, _, _, _| {}).size(px(100.)),
                )
            }
        }

        cx.update(crate::init);
        let bounds = Rc::new(Cell::new(Bounds::default()));
        let (_, cx) = cx.add_window_view({
            let bounds = bounds.clone();
            move |_, _| Harness(bounds)
        });
        let viewport = cx.update(|window, cx| {
            let viewport = window.viewport_size();
            window.draw(cx).clear(cx);
            viewport
        });

        assert_eq!(
            bounds.get().center(),
            point(viewport.width / 2., viewport.height / 2.)
        );
    }
}
