use gpui::{
    App, ClipboardItem, Context, IntoElement, ParentElement as _, Render, Subscription, Window, div,
};
use gpui_base::TextSelection;
use rust_i18n::t;

use super::{EditMenuItem, TouchSelectionOverlay};

/// Draws the handles and the edit menu of the window text selection — the one
/// a [`crate::text::TextView`] takes part in. [`crate::Root`] mounts one per
/// window, after the content, so the surfaces float above whatever was
/// selected.
///
/// Read-only text offers Copy and Select All.
pub(crate) struct WindowTouchSelectionOverlay {
    _subscription: Subscription,
}

impl WindowTouchSelectionOverlay {
    pub(crate) fn new(window: &Window, cx: &mut Context<Self>) -> Self {
        let this = cx.weak_entity();
        let subscription = TextSelection::observe_touch_selection(window, cx, move |cx| {
            let _ = this.update(cx, |_, cx| cx.notify());
        });
        Self {
            _subscription: subscription,
        }
    }

    fn copy(window: &mut Window, cx: &mut App) {
        let text = TextSelection::selected_text(window, cx);
        let text = text.trim();
        if !text.is_empty() {
            cx.write_to_clipboard(ClipboardItem::new_string(text.to_string()));
        }
        TextSelection::close_edit_menu(window, cx);
    }

    fn select_all(window: &mut Window, cx: &mut App) {
        TextSelection::select_all(window, cx);
    }
}

impl Render for WindowTouchSelectionOverlay {
    fn render(&mut self, window: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        if TextSelection::touch_selection(window, cx).is_none() {
            return div();
        }
        // The handles are painted by the text that owns them, where they
        // are covered by whatever covers the text; only the menu floats.
        let overlay = TouchSelectionOverlay::new("window-touch-selection", |window, cx| {
            TextSelection::touch_selection(window, cx)
        })
        .items([
            EditMenuItem::new(t!("Input.Copy"), Self::copy),
            EditMenuItem::new(t!("Input.Select All"), Self::select_all),
        ])
        .on_paint(|bounds, window, cx| TextSelection::register_touch_ui(bounds, window, cx));
        div().children(overlay.into_elements(window, cx))
    }
}
