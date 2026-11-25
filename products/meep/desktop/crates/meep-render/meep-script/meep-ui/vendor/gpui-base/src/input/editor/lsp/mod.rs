use anyhow::Result;
use gpui::{App, Context, Hsla, SharedString, Task, Window};
use ropey::Rope;
use std::rc::Rc;

use crate::input::{EditorMode, InputBaseState, RopeExt};

mod code_actions;
mod completions;
mod definitions;
mod document_colors;
mod hover;
mod overlay;
mod semantic_tokens;

pub use code_actions::*;
pub use completions::*;
pub use definitions::*;
pub use document_colors::*;
pub use hover::*;
pub use overlay::*;
pub use semantic_tokens::*;

/// Host hook to show a document when following an LSP location
/// (Go to Definition), modeled after the `window/showDocument` request.
///
/// https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/#window_showDocument
///
/// Called before the built-in behavior. Return `true` if the host has shown
/// the document (e.g. opened a docs window for a virtual/external URI);
/// return `false` to fall through to the default handling (`external` URIs
/// open in the browser, anything else jumps within the current document).
pub type ShowDocumentHandler =
    Rc<dyn Fn(&lsp_types::ShowDocumentParams, &mut Window, &mut App) -> bool>;

/// LSP ServerCapabilities
///
/// https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/#serverCapabilities
pub struct Lsp {
    /// The completion provider.
    pub completion_provider: Option<Rc<dyn CompletionProvider>>,
    /// The code action providers.
    pub code_action_providers: Vec<Rc<dyn CodeActionProvider>>,
    /// The hover provider.
    pub hover_provider: Option<Rc<dyn HoverProvider>>,
    /// The definition provider.
    pub definition_provider: Option<Rc<dyn DefinitionProvider>>,
    /// The document color provider.
    pub document_color_provider: Option<Rc<dyn DocumentColorProvider>>,
    /// The range semantic tokens provider.
    pub semantic_tokens_provider: Option<Rc<dyn DocumentRangeSemanticTokensProvider>>,
    /// Optional host hook to show documents for Go to Definition locations,
    /// following the `window/showDocument` request (see [`ShowDocumentHandler`]).
    ///
    /// https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/#window_showDocument
    pub show_document: Option<ShowDocumentHandler>,

    /// Display options for the completion popover.
    pub completion_menu: CompletionMenuOptions,

    /// Decides which bytes of each completion label the menu paints.
    ///
    /// Defaults to [`highlight_prefix`]. Replace it to paint a contiguous
    /// match, a character-by-character match, or ranges the host computed.
    completion_highlighter: Rc<CompletionHighlighter>,

    pub(crate) document_colors: Vec<(lsp_types::Range, Hsla)>,
    /// Cached semantic tokens as absolute position ranges + theme token-type
    /// names. Color is resolved from the name at paint time so theme switches
    /// take effect without a refetch.
    pub(crate) semantic_tokens: Vec<(lsp_types::Range, SharedString)>,
    pub(crate) _hover_task: Task<Result<()>>,
    pub(crate) _definition_task: Task<Result<()>>,
    pub(crate) _document_color_task: Task<()>,
    pub(crate) _semantic_tokens_task: Task<()>,
}

impl Default for Lsp {
    fn default() -> Self {
        Self {
            completion_provider: None,
            code_action_providers: vec![],
            hover_provider: None,
            definition_provider: None,
            document_color_provider: None,
            completion_menu: CompletionMenuOptions::default(),
            completion_highlighter: Rc::new(highlight_prefix),
            semantic_tokens_provider: None,
            show_document: None,
            document_colors: vec![],
            semantic_tokens: vec![],
            _hover_task: Task::ready(Ok(())),
            _definition_task: Task::ready(Ok(())),
            _document_color_task: Task::ready(()),
            _semantic_tokens_task: Task::ready(()),
        }
    }
}

impl Lsp {
    /// Set the completion label highlighter when constructing the LSP configuration.
    pub fn with_completion_highlighter(mut self, highlighter: Rc<CompletionHighlighter>) -> Self {
        self.set_completion_highlighter(highlighter);
        self
    }

    /// Return the completion label highlighter.
    pub fn completion_highlighter(&self) -> &Rc<CompletionHighlighter> {
        &self.completion_highlighter
    }

    /// Replace the completion label highlighter.
    ///
    /// Notify the editor after updating its LSP configuration to repaint an open menu.
    pub fn set_completion_highlighter(&mut self, highlighter: Rc<CompletionHighlighter>) {
        self.completion_highlighter = highlighter;
    }

    /// Update the LSP when the text changes.
    pub(crate) fn update(
        &mut self,
        text: &Rope,
        window: &mut Window,
        cx: &mut Context<InputBaseState<EditorMode>>,
    ) {
        self.update_document_colors(text, window, cx);
        self.update_semantic_tokens(text, window, cx);
    }

    /// Reset all LSP states.
    pub(crate) fn reset(&mut self) {
        self.document_colors.clear();
        self.semantic_tokens.clear();
        self._hover_task = Task::ready(Ok(()));
        self._definition_task = Task::ready(Ok(()));
        self._document_color_task = Task::ready(());
        self._semantic_tokens_task = Task::ready(());
    }
}

impl InputBaseState<EditorMode> {
    /// Apply a list of [`lsp_types::TextEdit`] to mutate the text.
    pub fn apply_lsp_edits(
        &mut self,
        text_edits: &Vec<lsp_types::TextEdit>,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        for edit in text_edits {
            let start = self.text.position_to_offset(&edit.range.start);
            let end = self.text.position_to_offset(&edit.range.end);

            let range_utf16 = self.range_to_utf16(&(start..end));
            self.replace_text_in_range_silent(Some(range_utf16), &edit.new_text, window, cx);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_lsp_builder() {
        let highlighter: Rc<CompletionHighlighter> = Rc::new(highlight_contains);
        let mut lsp = Lsp::default().with_completion_highlighter(highlighter.clone());
        assert!(Rc::ptr_eq(lsp.completion_highlighter(), &highlighter));

        let replacement: Rc<CompletionHighlighter> = Rc::new(highlight_characters);
        lsp.set_completion_highlighter(replacement.clone());
        assert!(Rc::ptr_eq(lsp.completion_highlighter(), &replacement));
    }
}
