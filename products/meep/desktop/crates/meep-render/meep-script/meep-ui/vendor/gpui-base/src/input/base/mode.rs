use crate::input::InputModeKind;
use std::rc::Rc;
use std::{cell::RefCell, ops::Range};

use gpui::{Context, Window};
use ropey::Rope;

use super::DisplayMap;
use crate::input::{
    DiagnosticSet, EditorLanguage, InputEdit, InputHighlighter, InputHighlighterFactory,
    LanguageConfig, RopeExt as _, TabSize,
};

/// What changed, handed to the syntax highlighter.
pub(crate) struct HighlighterUpdate<'a> {
    pub(super) selected_range: &'a Range<usize>,
    pub(super) old_text: &'a Rope,
    pub(super) new_text: &'a Rope,
    pub(super) change_text: &'a str,
    /// An edit already computed for this replacement. When absent, the
    /// highlighter derives one from the fields above.
    pub(super) input_edit: Option<InputEdit>,
    pub(super) force: bool,
}

/// How the input lays its text out: rows, growth, and the code-editor extras.
///
/// This does not say what *kind* of input this is — that is fixed at the type
/// level by [`crate::input::InputModeKind`], and asking it here is what used to
/// let the two disagree.
#[derive(Clone)]
pub(crate) enum LayoutMode {
    /// A plain text input mode.
    PlainText { tab: TabSize, rows: usize },
    /// An auto grow input mode.
    AutoGrow {
        rows: usize,
        min_rows: usize,
        max_rows: usize,
    },
    /// A code editor input mode.
    CodeEditor {
        tab: TabSize,
        rows: usize,
        /// Show line number
        line_number: bool,
        language: Box<EditorLanguage>,
        indent_guides: bool,
        folding: bool,
        highlighter: Rc<RefCell<Option<Box<dyn InputHighlighter>>>>,
        highlighter_factory: Option<InputHighlighterFactory>,
        diagnostics: DiagnosticSet,
        /// Automatic delimiter ranges, adjusted with document edits.
        auto_closed_pairs: super::auto_close::AutoClosedPairs,
        auto_close: bool,
        smart_indent: bool,
    },
}

impl Default for LayoutMode {
    fn default() -> Self {
        LayoutMode::plain_text()
    }
}

#[allow(unused)]
impl LayoutMode {
    /// Create a plain input mode with default settings.
    pub(super) fn plain_text() -> Self {
        LayoutMode::PlainText {
            tab: TabSize::default(),
            rows: 1,
        }
    }

    /// Create a code editor input mode with default settings.
    ///
    /// Starts with no language; the state sets one through its own builder.
    pub(super) fn code_editor(language: EditorLanguage) -> Self {
        LayoutMode::CodeEditor {
            rows: 2,
            tab: TabSize::default(),
            language: Box::new(language),
            highlighter: Rc::new(RefCell::new(None)),
            highlighter_factory: None,
            line_number: true,
            indent_guides: true,
            folding: true,
            diagnostics: DiagnosticSet::new(&Rope::new()),
            auto_closed_pairs: Default::default(),
            auto_close: true,
            smart_indent: true,
        }
    }

    /// Create an auto grow input mode with given min and max rows.
    pub(super) fn auto_grow(min_rows: usize, max_rows: usize) -> Self {
        LayoutMode::AutoGrow {
            rows: min_rows,
            min_rows,
            max_rows,
        }
    }

    /// Return true if this layout is a code editor with folding enabled.
    #[inline]
    pub(crate) fn is_folding(&self) -> bool {
        if cfg!(target_family = "wasm") {
            return false;
        }

        matches!(self, LayoutMode::CodeEditor { folding: true, .. })
    }

    pub(super) fn language_config(&self) -> Option<Rc<LanguageConfig>> {
        match self {
            Self::CodeEditor { language, .. } => Some(language.config()),
            _ => None,
        }
    }

    pub(super) fn syntax_context_at(
        &self,
        text: &Rope,
        offset: usize,
    ) -> crate::input::SyntaxContext {
        match self {
            Self::CodeEditor { language, .. } => language.context_at(text, offset),
            _ => crate::input::SyntaxContext::Code,
        }
    }

    pub(super) fn is_auto_close(&self) -> bool {
        matches!(
            self,
            Self::CodeEditor {
                auto_close: true,
                ..
            }
        )
    }

    pub(super) fn is_smart_indent(&self) -> bool {
        matches!(
            self,
            Self::CodeEditor {
                smart_indent: true,
                ..
            }
        )
    }

    pub(super) fn set_auto_close(&mut self, enabled: bool) {
        if let Self::CodeEditor { auto_close, .. } = self {
            *auto_close = enabled;
        }
    }

    pub(super) fn set_smart_indent(&mut self, enabled: bool) {
        if let Self::CodeEditor { smart_indent, .. } = self {
            *smart_indent = enabled;
        }
    }

    pub(super) fn auto_closed_pairs(&self) -> &super::auto_close::AutoClosedPairs {
        match self {
            Self::CodeEditor {
                auto_closed_pairs, ..
            } => auto_closed_pairs,
            _ => super::auto_close::AutoClosedPairs::empty(),
        }
    }

    pub(super) fn restore_auto_closed_pairs(&mut self, pairs: super::auto_close::AutoClosedPairs) {
        if let Self::CodeEditor {
            auto_closed_pairs, ..
        } = self
        {
            *auto_closed_pairs = pairs;
        }
    }

    pub(super) fn track_auto_closed_pair(&mut self, open: Range<usize>, close: Range<usize>) {
        if let Self::CodeEditor {
            auto_closed_pairs, ..
        } = self
        {
            auto_closed_pairs.record(open, close);
        }
    }

    pub(super) fn adjust_auto_closed_pair(&mut self, edit: &Range<usize>, new_len: usize) {
        let Self::CodeEditor {
            auto_closed_pairs, ..
        } = self
        else {
            return;
        };
        auto_closed_pairs.adjust(edit, new_len);
    }

    #[inline]
    pub(super) fn is_auto_grow(&self) -> bool {
        matches!(self, LayoutMode::AutoGrow { .. })
    }

    pub(super) fn set_rows(&mut self, new_rows: usize) {
        match self {
            LayoutMode::PlainText { rows, .. } => {
                *rows = new_rows;
            }
            LayoutMode::CodeEditor { rows, .. } => {
                *rows = new_rows;
            }
            LayoutMode::AutoGrow {
                rows,
                min_rows,
                max_rows,
            } => {
                *rows = new_rows.clamp(*min_rows, *max_rows);
            }
        }
    }

    /// Grow the row count to fit the content.
    ///
    /// Callers gate this on the input being multi-line; a single-line field
    /// keeps its one row. Only auto grow follows the content: in the other
    /// modes `rows` is the configured height.
    pub(super) fn update_auto_grow(&mut self, display_map: &DisplayMap) {
        if !self.is_auto_grow() {
            return;
        }
        let wrapped_lines = display_map.wrap_row_count();
        self.set_rows(wrapped_lines);
    }

    /// At least 1 row be return.
    pub(super) fn rows(&self) -> usize {
        match self {
            LayoutMode::PlainText { rows, .. } => *rows,
            LayoutMode::CodeEditor { rows, .. } => *rows,
            LayoutMode::AutoGrow { rows, .. } => *rows,
        }
        .max(1)
    }

    /// At least 1 row be return.
    #[allow(unused)]
    pub(super) fn min_rows(&self) -> usize {
        match self {
            LayoutMode::AutoGrow { min_rows, .. } => *min_rows,
            _ => 1,
        }
        .max(1)
    }

    #[allow(unused)]
    pub(super) fn max_rows(&self) -> usize {
        match self {
            LayoutMode::AutoGrow { max_rows, .. } => *max_rows,
            _ => usize::MAX,
        }
    }

    /// Return false if the mode is not [`LayoutMode::CodeEditor`].
    #[inline]
    pub(super) fn line_number(&self) -> bool {
        match self {
            LayoutMode::CodeEditor { line_number, .. } => *line_number,
            _ => false,
        }
    }

    /// Update the syntax highlighter with new text.
    ///
    pub(crate) fn update_highlighter<M: InputModeKind>(
        &mut self,
        update: HighlighterUpdate<'_>,
        window: &mut Window,
        cx: &mut Context<crate::input::InputBaseState<M>>,
    ) {
        match &self {
            LayoutMode::CodeEditor {
                language,
                highlighter,
                highlighter_factory,
                folding,
                ..
            } => {
                if !update.force && highlighter.borrow().is_some() {
                    return;
                }
                if !ensure_highlighter(highlighter, highlighter_factory.as_ref(), language) {
                    return;
                }

                let edit = update.input_edit.unwrap_or_else(|| {
                    replacement_input_edit(
                        update.old_text,
                        update.new_text,
                        update.selected_range,
                        update.change_text,
                    )
                });
                M::drive_highlighter(highlighter, edit, update.new_text, *folding, window, cx);
            }
            _ => {}
        }
    }

    /// Drive the highlighter once for several edits applied as one change,
    /// each paired with the text right after it, in application order.
    pub(crate) fn update_highlighter_batch<M: InputModeKind>(
        &mut self,
        edits: &[(InputEdit, Rope)],
        window: &mut Window,
        cx: &mut Context<crate::input::InputBaseState<M>>,
    ) {
        let LayoutMode::CodeEditor {
            language,
            highlighter,
            highlighter_factory,
            folding,
            ..
        } = &self
        else {
            return;
        };
        if !ensure_highlighter(highlighter, highlighter_factory.as_ref(), language) {
            return;
        }
        M::drive_highlighter_batch(highlighter, edits, *folding, window, cx);
    }

    #[allow(unused)]
    pub(super) fn diagnostics(&self) -> Option<&DiagnosticSet> {
        match self {
            LayoutMode::CodeEditor { diagnostics, .. } => Some(diagnostics),
            _ => None,
        }
    }

    pub(super) fn diagnostics_mut(&mut self) -> Option<&mut DiagnosticSet> {
        match self {
            LayoutMode::CodeEditor { diagnostics, .. } => Some(diagnostics),
            _ => None,
        }
    }

    /// Get a reference to the highlighter (if available)
    pub(super) fn highlighter(&self) -> Option<&Rc<RefCell<Option<Box<dyn InputHighlighter>>>>> {
        match self {
            LayoutMode::CodeEditor { highlighter, .. } => Some(highlighter),
            _ => None,
        }
    }

    pub(super) fn set_highlighter_factory(&mut self, factory: InputHighlighterFactory) {
        if let LayoutMode::CodeEditor {
            highlighter_factory,
            highlighter,
            ..
        } = self
        {
            *highlighter_factory = Some(factory);
            *highlighter.borrow_mut() = None;
        }
    }

    pub(super) fn ensure_highlighter_factory(&mut self, factory: InputHighlighterFactory) {
        if let LayoutMode::CodeEditor {
            highlighter_factory,
            ..
        } = self
        {
            if highlighter_factory.is_none() {
                *highlighter_factory = Some(factory);
            }
        }
    }
}

/// Create the highlighter from the factory if there is none yet. Returns
/// whether one is installed.
fn ensure_highlighter(
    highlighter: &RefCell<Option<Box<dyn InputHighlighter>>>,
    highlighter_factory: Option<&InputHighlighterFactory>,
    language: &EditorLanguage,
) -> bool {
    let mut highlighter = highlighter.borrow_mut();
    if highlighter.is_none()
        && let Some(factory) = highlighter_factory
    {
        *highlighter = factory(&language.name());
    }
    highlighter.is_some()
}

/// Builds the tree-sitter edit for a text replacement.
///
/// Byte offsets and positions for `start`/`old_end` come from `old_text`;
/// `new_end` byte/position come from the post-edit `text`.
pub(super) fn replacement_input_edit(
    old_text: &Rope,
    new_text: &Rope,
    selected_range: &Range<usize>,
    change_text: &str,
) -> InputEdit {
    let start_byte = selected_range.start.min(old_text.len());
    let old_end_byte = selected_range.end.min(old_text.len()).max(start_byte);
    let new_end_byte = (start_byte + change_text.len()).min(new_text.len());

    InputEdit {
        start_byte,
        old_end_byte,
        new_end_byte,
        start_position: old_text.offset_to_point(start_byte),
        old_end_position: old_text.offset_to_point(old_end_byte),
        new_end_position: new_text.offset_to_point(new_end_byte),
    }
}

#[cfg(test)]
mod tests {
    use ropey::Rope;

    use super::replacement_input_edit;
    use crate::input::{DiagnosticSet, Point, TabSize, mode::LayoutMode};

    #[test]
    fn test_replacement_input_edit_backspace_at_end_uses_old_range() {
        let old_text = Rope::from_str("-=");
        let text = Rope::from_str("-");
        let edit = replacement_input_edit(&old_text, &text, &(1..2), "");

        assert_eq!(edit.start_byte, 1);
        assert_eq!(edit.old_end_byte, 2);
        assert_eq!(edit.new_end_byte, 1);
        assert_eq!(edit.start_position, Point::new(0, 1));
        assert_eq!(edit.old_end_position, Point::new(0, 2));
        assert_eq!(edit.new_end_position, Point::new(0, 1));
    }

    #[test]
    fn test_code_editor() {
        let mode = LayoutMode::code_editor(Default::default());
        assert_eq!(mode.line_number(), true);
        assert_eq!(mode.has_indent_guides(), true);
        assert_eq!(mode.max_rows(), usize::MAX);
        assert_eq!(mode.min_rows(), 1);
        assert_eq!(mode.is_folding(), true);

        let mode = LayoutMode::CodeEditor {
            line_number: false,
            indent_guides: false,
            folding: false,
            rows: 0,
            tab: Default::default(),
            language: Box::default(),
            highlighter: Default::default(),
            highlighter_factory: None,
            diagnostics: DiagnosticSet::new(&Rope::new()),
            auto_closed_pairs: Default::default(),
            auto_close: false,
            smart_indent: false,
        };
        assert_eq!(mode.line_number(), false);
        assert_eq!(mode.has_indent_guides(), false);
        assert_eq!(mode.min_rows(), 1);
        assert_eq!(mode.is_folding(), false);
        assert_eq!(mode.is_auto_close(), false);
        assert_eq!(mode.is_smart_indent(), false);
    }

    #[test]
    fn test_plain() {
        let mode = LayoutMode::PlainText {
            tab: TabSize::default(),
            rows: 5,
        };
        assert_eq!(mode.line_number(), false);
        assert_eq!(mode.rows(), 5);
        assert_eq!(mode.max_rows(), usize::MAX);
        assert_eq!(mode.min_rows(), 1);

        let mode = LayoutMode::plain_text();
        assert_eq!(mode.line_number(), false);
        assert_eq!(mode.rows(), 1);
        assert_eq!(mode.min_rows(), 1);
    }

    #[test]
    fn test_auto_grow() {
        let mut mode = LayoutMode::auto_grow(2, 5);
        assert_eq!(mode.line_number(), false);
        assert_eq!(mode.rows(), 2);
        assert_eq!(mode.max_rows(), 5);
        assert_eq!(mode.min_rows(), 2);

        mode.set_rows(4);
        assert_eq!(mode.rows(), 4);

        mode.set_rows(1);
        assert_eq!(mode.rows(), 2);

        mode.set_rows(10);
        assert_eq!(mode.rows(), 5);
    }
}
