use std::rc::Rc;

use gpui::{
    AnyElement, App, ElementId, FocusHandle, IntoElement, KeyBinding, ParentElement, RenderOnce,
    StyleRefinement, Styled, Window, prelude::FluentBuilder as _,
};

use crate::{
    Select,
    actions::{Cancel, Confirm, SelectDown, SelectUp},
    styled::StyledExt as _,
};

const CONTEXT: &str = "Combobox";

pub(crate) fn init(cx: &mut App) {
    cx.bind_keys([
        KeyBinding::new("up", SelectUp, Some(CONTEXT)),
        KeyBinding::new("down", SelectDown, Some(CONTEXT)),
        KeyBinding::new("enter", Confirm { secondary: false }, Some(CONTEXT)),
        KeyBinding::new(
            if cx.platform_info().is_mac() {
                "cmd-enter"
            } else {
                "ctrl-enter"
            },
            Confirm { secondary: true },
            Some(CONTEXT),
        ),
        KeyBinding::new("escape", Cancel, Some(CONTEXT)),
    ]);
}

type OpenChangeHandler = Rc<dyn Fn(bool, &mut Window, &mut App)>;
type ActionHandler = Rc<dyn Fn(&mut Window, &mut App)>;

/// An unstyled controlled combobox root.
///
/// Applications own the trigger, popup, searchable collection, selection, and
/// appearance. This root owns combobox semantics and keyboard focus transfer.
#[derive(IntoElement)]
pub struct Combobox {
    id: ElementId,
    open: bool,
    disabled: bool,
    focus_handle: Option<FocusHandle>,
    content_focus_handle: Option<FocusHandle>,
    style: StyleRefinement,
    children: Vec<AnyElement>,
    on_open_change: Option<OpenChangeHandler>,
    on_confirm: Option<ActionHandler>,
    on_dismiss: Option<ActionHandler>,
}

impl Combobox {
    pub fn new(id: impl Into<ElementId>) -> Self {
        Self {
            id: id.into(),
            open: false,
            disabled: false,
            focus_handle: None,
            content_focus_handle: None,
            style: StyleRefinement::default(),
            children: Vec::new(),
            on_open_change: None,
            on_confirm: None,
            on_dismiss: None,
        }
    }

    pub fn open(mut self, open: bool) -> Self {
        self.open = open;
        self
    }

    pub fn disabled(mut self, disabled: bool) -> Self {
        self.disabled = disabled;
        self
    }

    pub fn focus_handle(mut self, focus_handle: &FocusHandle) -> Self {
        self.focus_handle = Some(focus_handle.clone());
        self
    }

    pub fn content_focus_handle(mut self, focus_handle: &FocusHandle) -> Self {
        self.content_focus_handle = Some(focus_handle.clone());
        self
    }

    pub fn on_open_change(
        mut self,
        handler: impl Fn(bool, &mut Window, &mut App) + 'static,
    ) -> Self {
        self.on_open_change = Some(Rc::new(handler));
        self
    }

    /// Handles the Confirm action while the combobox is open.
    pub fn on_confirm(mut self, handler: impl Fn(&mut Window, &mut App) + 'static) -> Self {
        self.on_confirm = Some(Rc::new(handler));
        self
    }

    /// Handles a dismissal requested through the Cancel action.
    ///
    /// This runs before the controlled open state is asked to close, so a
    /// combobox that commits its pending value on dismissal can still read
    /// that value here.
    pub fn on_dismiss(mut self, handler: impl Fn(&mut Window, &mut App) + 'static) -> Self {
        self.on_dismiss = Some(Rc::new(handler));
        self
    }
}

impl Styled for Combobox {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl ParentElement for Combobox {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

impl RenderOnce for Combobox {
    fn render(self, _: &mut Window, _: &mut App) -> impl IntoElement {
        Select::new(self.id)
            .open(self.open)
            .disabled(self.disabled)
            .key_context(CONTEXT)
            .when_some(self.focus_handle, |this, handle| this.focus_handle(&handle))
            .when_some(self.content_focus_handle, |this, handle| {
                this.content_focus_handle(&handle)
            })
            .when_some(self.on_open_change, |this, handler| {
                this.on_open_change(move |open, window, cx| handler(open, window, cx))
            })
            .when_some(self.on_confirm, |this, handler| {
                this.on_confirm(move |window, cx| handler(window, cx))
            })
            .when_some(self.on_dismiss, |this, handler| {
                this.on_dismiss(move |window, cx| handler(window, cx))
            })
            .children(self.children)
            .refine_style(&self.style)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use gpui::{
        Context, Focusable, InteractiveElement as _, Render, TestAppContext, VisualTestContext,
        div, px,
    };
    use std::sync::{Arc, Mutex};

    struct Harness {
        open: bool,
        trigger_focus: FocusHandle,
        content_focus: FocusHandle,
        events: Arc<Mutex<Vec<&'static str>>>,
    }

    impl Harness {
        fn new(cx: &mut Context<Self>) -> Self {
            Self {
                open: true,
                trigger_focus: cx.focus_handle(),
                content_focus: cx.focus_handle(),
                events: Arc::new(Mutex::new(Vec::new())),
            }
        }
    }

    impl Focusable for Harness {
        fn focus_handle(&self, _: &App) -> FocusHandle {
            self.trigger_focus.clone()
        }
    }

    impl Render for Harness {
        fn render(&mut self, _: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
            let state = cx.entity();
            let confirm_events = self.events.clone();
            let dismiss_events = self.events.clone();
            let open_events = self.events.clone();

            Combobox::new("combobox")
                .open(self.open)
                .focus_handle(&self.trigger_focus)
                .content_focus_handle(&self.content_focus)
                .on_confirm(move |_, _| confirm_events.lock().unwrap().push("confirm"))
                .on_dismiss(move |_, _| dismiss_events.lock().unwrap().push("dismiss"))
                .on_open_change(move |open, _, cx| {
                    open_events.lock().unwrap().push("close");
                    state.update(cx, |state, cx| {
                        state.open = open;
                        cx.notify();
                    });
                })
                .child(div().track_focus(&self.content_focus).size(px(20.)))
        }
    }

    fn harness(cx: &mut TestAppContext) -> (&mut VisualTestContext, gpui::Entity<Harness>) {
        cx.update(crate::init);
        let (state, cx) = cx.add_window_view(|_, cx| Harness::new(cx));
        cx.update(|window, cx| {
            let content_focus = state.read(cx).content_focus.clone();
            content_focus.focus(window, cx);
            window.draw(cx).clear(cx);
        });
        (cx, state)
    }

    #[gpui::test]
    fn escape_dismisses_then_closes_and_restores_trigger_focus(cx: &mut TestAppContext) {
        let (cx, state) = harness(cx);
        cx.simulate_keystrokes("escape");

        cx.update(|window, cx| {
            assert!(!state.read(cx).open);
            assert!(state.read(cx).trigger_focus.is_focused(window));
            // Dismissal runs before the close request so a caller can still
            // commit its pending value.
            assert_eq!(
                state.read(cx).events.lock().unwrap().as_slice(),
                &["dismiss", "close"]
            );
        });
    }

    #[gpui::test]
    fn enter_confirms_without_dismissing_while_open(cx: &mut TestAppContext) {
        let (cx, state) = harness(cx);
        cx.simulate_keystrokes("enter");

        cx.update(|_, cx| {
            assert!(state.read(cx).open);
            assert_eq!(
                state.read(cx).events.lock().unwrap().as_slice(),
                &["confirm"]
            );
        });
    }
}
