use super::TestWindowExt;
use crate::{App, InputHandler, UTF16Selection, Window};
use std::ops::Range;

/// Simulates the text-input protocol against a caller-supplied input handler.
///
/// GPUI keeps the installed platform handler private. Construct an
/// [`crate::ElementInputHandler`] from the rendered control's entity and bounds
/// and supply it here. This bridge does not discover the focused control or
/// drive a native IME, candidate window, or platform event translation.
pub struct TestInput<'a> {
    handler: Box<dyn InputHandler>,
    window: &'a mut Window,
}

impl<'a> TestInput<'a> {
    /// Borrows a window and owns a handler for its rendered text control.
    pub fn new(handler: impl InputHandler, window: &'a mut Window) -> Self {
        Self {
            handler: Box::new(handler),
            window,
        }
    }

    /// Commits one complete text insertion, replacing the selection or preedit.
    /// Unlike `Window::input`, this does not generate per-character keystrokes.
    pub fn commit_text(&mut self, text: &str, cx: &mut App) {
        self.handler
            .replace_text_in_range(None, text, self.window, cx);
        self.window.render_frame(cx);
    }

    /// Replaces and marks a preedit, then completes a frame.
    ///
    /// Both ranges use UTF-16 code units. `replacement` is document-relative;
    /// `selection` is relative to `text`. With no replacement range, the
    /// handler replaces the current marked range or selection. An empty text
    /// cancels the preedit according to the control's input protocol.
    pub fn compose_text(
        &mut self,
        replacement: Option<Range<usize>>,
        text: &str,
        selection: Option<Range<usize>>,
        cx: &mut App,
    ) {
        if let Some(range) = &replacement {
            assert!(range.start <= range.end, "replacement range is reversed");
        }
        if let Some(range) = &selection {
            let length = text.encode_utf16().count();
            assert!(
                range.start <= range.end && range.end <= length,
                "composition selection must lie inside the UTF-16 preedit"
            );
        }
        self.handler
            .replace_and_mark_text_in_range(replacement, text, selection, self.window, cx);
        self.window.render_frame(cx);
    }

    /// Ends composition while retaining its text, then completes a frame.
    pub fn unmark_text(&mut self, cx: &mut App) {
        self.handler.unmark_text(self.window, cx);
        self.window.render_frame(cx);
    }

    /// Returns the document-relative marked range in UTF-16 code units.
    pub fn marked_text_range(&mut self, cx: &mut App) -> Option<Range<usize>> {
        self.handler.marked_text_range(self.window, cx)
    }

    /// Returns the selection and its direction in UTF-16 code units.
    pub fn selected_text_range(&mut self, cx: &mut App) -> Option<UTF16Selection> {
        self.handler.selected_text_range(false, self.window, cx)
    }
}
