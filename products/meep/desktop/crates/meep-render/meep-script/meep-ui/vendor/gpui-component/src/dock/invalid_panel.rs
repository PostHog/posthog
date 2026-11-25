use gpui::{
    App, Context, EventEmitter, FocusHandle, Focusable, IntoElement, ParentElement as _, Render,
    Styled as _, Window, div,
};
use gpui_base::dock::{PanelEvent, PanelState};
use rust_i18n::t;

use crate::{ActiveTheme as _, dock::Panel};

/// Stands in for a panel this build cannot construct — one whose
/// `panel_name` no [`PanelRegistry`](gpui_base::dock::PanelRegistry) builder
/// answers to.
///
/// It reports the original [`PanelState`] from
/// [`dump`](gpui_base::dock::Panel::dump), so a layout written by a build that
/// knows the panel survives a load and a save here rather than losing it.
pub(crate) struct InvalidPanel {
    focus_handle: FocusHandle,
    old_state: PanelState,
}

impl InvalidPanel {
    /// The type name goes to the log rather than the screen: it means
    /// nothing to the person looking at the panel.
    pub(crate) fn new(state: PanelState, cx: &mut Context<Self>) -> Self {
        tracing::warn!(
            "the `{}` panel type is not registered in PanelRegistry",
            state.panel_name
        );
        Self {
            focus_handle: cx.focus_handle(),
            old_state: state,
        }
    }
}

impl gpui_base::dock::Panel for InvalidPanel {
    fn panel_name(&self) -> &'static str {
        "InvalidPanel"
    }

    fn dump(&self, _: &App) -> PanelState {
        self.old_state.clone()
    }
}

impl Panel for InvalidPanel {}

impl EventEmitter<PanelEvent> for InvalidPanel {}

impl Focusable for InvalidPanel {
    fn focus_handle(&self, _: &App) -> FocusHandle {
        self.focus_handle.clone()
    }
}

impl Render for InvalidPanel {
    fn render(&mut self, _: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        div()
            .size_full()
            .my_6()
            .flex()
            .flex_col()
            .items_center()
            .justify_center()
            .text_color(cx.theme().muted_foreground)
            .child(t!("Dock.Unavailable Panel"))
    }
}
