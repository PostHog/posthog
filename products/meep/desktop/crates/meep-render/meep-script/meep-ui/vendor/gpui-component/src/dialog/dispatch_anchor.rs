use gpui::{Action, App, FocusHandle, InteractiveElement as _, IntoElement, Styled, Window, div};

/// A focus node of a dialog control's own, so the control can dispatch its
/// action on the dialog it sits in rather than on whatever holds focus when
/// it is clicked.
///
/// [`Window::dispatch_action`] routes along the focused element. A surface
/// that keeps taking focus back — a native web view, an always-on-top window
/// — leaves every dialog button inert that way: the click lands, the action
/// is dispatched, and no dialog is on the focus path to handle it. Dispatching
/// from a node inside the control instead walks the control's own ancestors,
/// which end at exactly the dialog it belongs to, stacked dialogs included.
///
/// Create it where the control renders, so the keyed state lives in that
/// control's scope, and place [`Self::element`] inside the control.
#[derive(Clone)]
pub(crate) struct DialogDispatchAnchor {
    handle: FocusHandle,
}

impl DialogDispatchAnchor {
    pub(crate) fn new(key: &'static str, window: &mut Window, cx: &mut App) -> Self {
        let handle = window
            .use_keyed_state(key, cx, |_, cx| cx.focus_handle())
            .read(cx)
            .clone();
        Self { handle }
    }

    /// A zero-size, out-of-flow node that tracks the handle. It is never
    /// hovered, so it takes no focus of its own and does not enter the Tab
    /// order; it only gives the handle a place in the dispatch tree.
    pub(crate) fn element(&self) -> impl IntoElement {
        div().absolute().size_0().track_focus(&self.handle)
    }

    /// Dispatches `action` from the anchor, falling back to the focused
    /// element only if the anchor was never rendered.
    pub(crate) fn dispatch(&self, action: &dyn Action, window: &mut Window, cx: &mut App) {
        if self.handle.is_focused(window) || self.is_rendered(window) {
            self.handle.dispatch_action(action, window, cx);
        } else {
            window.dispatch_action(action.boxed_clone(), cx);
        }
    }

    fn is_rendered(&self, window: &Window) -> bool {
        // `FocusHandle::dispatch_action` is a no-op for a handle the rendered
        // frame does not contain; `contains` answers from that same frame.
        self.handle.contains(&self.handle, window)
    }
}
