//! Compile-time input modes.
//!
//! The three input states are one engine seen through a mode marker, one per
//! state:
//!
//! ```ignore
//! pub type InputState    = InputBaseState<InputMode>;
//! pub type TextareaState = InputBaseState<TextareaMode>;
//! pub type EditorState   = InputBaseState<EditorMode>;
//! ```
//!
//! A method that only makes sense for one mode lives in that mode's `impl`
//! block, so it does not exist on the others: `InputState` has no `auto_grow`
//! or `soft_wrap`, `TextareaState` has no `masked` or `line_number`, and only
//! `EditorState` performs code actions. Methods shared by the two multi-line
//! modes go on [`MultiLineMode`]. Reaching for the wrong one is a compile
//! error rather than a debug assertion.
//!
//! [`super::LayoutMode`] carries the same distinction at runtime, since the
//! engine branches on it while editing. The marker only decides which API is
//! reachable.

use std::cell::RefCell;
use std::rc::Rc;

use gpui::{Div, Entity, Stateful, Window};
use ropey::Rope;

use super::decorations::DecorationCollections;
use super::lsp::{ContextMenuContent, HoverDefinition, InlineCompletion};
use crate::input::{
    GutterDecoration, HighlightStyleResolver, InputEdit, InputHighlighter, OverviewRulerDecoration,
    RangeDecoration, SyntaxContext, TextDecoration,
};
use crate::input::{HoverPopoverState, Lsp};
use gpui::Task;

use super::InputBaseState;

/// A single-line text field: the mode of [`crate::input::InputState`].
pub struct InputMode;

/// Ordinary multi-line text: the mode of [`crate::input::TextareaState`].
pub struct TextareaMode;

/// Source code, with language features: the mode of [`crate::input::EditorState`].
pub struct EditorMode;

mod sealed {
    pub trait Sealed {}
}

impl sealed::Sealed for InputMode {}
impl sealed::Sealed for TextareaMode {}
impl sealed::Sealed for EditorMode {}

/// The modes whose layout spans more than one line: [`TextareaMode`] and
/// [`EditorMode`].
///
/// Soft wrap, wrapping indent and the search session are meaningless in a
/// single-line field, but shared by the two multi-line modes. Bounding an
/// `impl` block on this trait puts those methods on both without writing them
/// twice, and keeps them off [`InputMode`].
pub trait MultiLineMode: InputModeKind {}

impl MultiLineMode for TextareaMode {}
impl MultiLineMode for EditorMode {}

/// What the renderer may read out of a mode's extra state.
///
/// Kept apart from [`InputModeKind`] on purpose. This trait is *data*: the
/// renderer is generic over the mode, so it cannot name `EditorExtras` and
/// reach its fields directly, and these are the accessors it goes through
/// instead. Every one of them has an empty answer, which is what a plain input
/// and a textarea give.
///
/// [`InputModeKind`] is *behavior*: points where the engine hands control back
/// during an edit. Adding a field an editor renders belongs here and leaves
/// the engine's callbacks alone.
pub trait InputExtras: Default + 'static {
    /// Decoration ranges to paint, innermost collection first.
    fn decoration_layers(&self) -> Vec<&[TextDecoration]> {
        Vec::new()
    }

    /// Geometric decorations intersecting visible, non-folded buffer spans.
    fn range_decorations(&self, _ranges: &[std::ops::Range<usize>]) -> Vec<&RangeDecoration> {
        Vec::new()
    }

    /// Return the gutter decoration strip width, or `None` when no gutter
    /// collection exists.
    fn gutter_decorations_width(&self) -> Option<gpui::Pixels> {
        None
    }

    /// Return the gutter decorations that touch a UTF-8 byte range, in paint
    /// order. An empty decoration touches the range when it lies inside it.
    fn gutter_decorations(&self, _range: std::ops::Range<usize>) -> Vec<&GutterDecoration> {
        Vec::new()
    }

    /// Return all overview ruler decorations in paint order.
    fn overview_ruler_decorations(&self) -> Vec<&OverviewRulerDecoration> {
        Vec::new()
    }

    /// A number that changes whenever an overview ruler collection is created,
    /// replaced, extended, cleared or released.
    fn overview_ruler_revision(&self) -> u64 {
        0
    }

    /// Semantic-token styles for a visible range, when an LSP supplies them.
    fn semantic_token_styles(
        &self,
        _text: &Rope,
        _range: &std::ops::Range<usize>,
        _resolver: &dyn HighlightStyleResolver,
    ) -> Vec<(std::ops::Range<usize>, gpui::HighlightStyle)> {
        Vec::new()
    }

    /// Document colours to paint as swatches, when an LSP supplies them.
    fn document_color_swatches(
        &self,
        _text: &Rope,
        _range: &std::ops::Range<usize>,
    ) -> Vec<(std::ops::Range<usize>, gpui::Hsla)> {
        Vec::new()
    }

    /// The symbol range the hover popover is anchored to.
    fn hover_symbol_range(&self) -> Option<std::ops::Range<usize>> {
        None
    }

    /// The inline completion to paint as ghost text.
    fn inline_completion_item(&self) -> Option<&lsp_types::InlineCompletionItem> {
        None
    }

    /// What this mode can offer its context menu: go-to-definition, code actions.
    fn context_menu_capabilities(&self) -> (bool, bool) {
        (false, false)
    }
}

/// A mode with nothing extra to render.
impl InputExtras for () {}

/// Hooks the shared engine calls back into for mode-specific work.
///
/// The engine's render path is generic over the mode, so it cannot name a
/// specific state type. This hook is the seam: each implementation is written
/// for one concrete mode, so inside it `Entity<InputBaseState<Self>>` is that
/// mode's own state type.
/// Sealed: the engine branches on a closed set of runtime modes, so the
/// markers are a closed set too. The three above are all of them.
pub trait InputModeKind: sealed::Sealed + Sized + 'static {
    /// Whether this kind of input spans more than one line.
    ///
    /// The kind decides this, not the layout: [`super::LayoutMode`] carries
    /// how many rows to show and how to grow, which is a different question
    /// from whether the input is a text field or a document. Deriving it from
    /// the layout let the two disagree — an auto-growing textarea capped at
    /// one row used to report itself as single-line.
    const MULTI_LINE: bool;

    /// Whether this kind of input is a source-code editor.
    const CODE_EDITOR: bool = false;

    /// State only this mode needs.
    ///
    /// The engine is shared, but its parts are not: a single-line field has no
    /// use for an LSP client or a search session, and an editor has no use for
    /// number stepping. Keeping those here means a form full of text fields
    /// does not carry an editor's worth of machinery.
    type Extras: InputExtras;

    /// Drives the syntax highlighter after the text changed.
    ///
    /// Only a code editor has one. The engine's edit path is generic over the
    /// mode, so it dispatches here, where `Self` is concrete and the highlighter
    /// can be handed this mode's own context.
    fn drive_highlighter(
        _highlighter: &Rc<RefCell<Option<Box<dyn InputHighlighter>>>>,
        _edit: InputEdit,
        _text: &Rope,
        _folding: bool,
        _window: &mut Window,
        _cx: &mut gpui::Context<InputBaseState<Self>>,
    ) {
    }

    /// Drives the syntax highlighter once for several edits applied as one
    /// change, each paired with the text right after it.
    fn drive_highlighter_batch(
        _highlighter: &Rc<RefCell<Option<Box<dyn InputHighlighter>>>>,
        _edits: &[(InputEdit, Rope)],
        _folding: bool,
        _window: &mut Window,
        _cx: &mut gpui::Context<InputBaseState<Self>>,
    ) {
    }

    /// The range highlighted while Cmd-hovering a symbol, with its style.
    fn hover_definition_style(
        _state: &InputBaseState<Self>,
        _cx: &gpui::App,
    ) -> Option<(std::ops::Range<usize>, gpui::HighlightStyle)> {
        None
    }

    /// The hitbox for Cmd-hover, when the mode supports go-to-definition.
    fn hover_definition_hitbox(
        _state: &InputBaseState<Self>,
        _window: &mut Window,
        _cx: &gpui::App,
    ) -> Option<gpui::Hitbox> {
        None
    }

    /// Drops cached language-server results, e.g. after the text is replaced.
    fn reset_language_features(_state: &mut InputBaseState<Self>) {}

    /// Drops decorations and hover state when the text is replaced wholesale.
    fn reset_annotations(_state: &mut InputBaseState<Self>) {}

    /// Syntax context at `offset` for editing decisions.
    ///
    /// Only a code editor can have a provider installed; the default answer
    /// is `Code`, which preserves character-heuristic behavior.
    fn editing_syntax_context(_state: &InputBaseState<Self>, _offset: usize) -> SyntaxContext {
        SyntaxContext::Code
    }

    /// Slides decoration ranges along with an edit.
    fn adjust_annotations(
        _state: &mut InputBaseState<Self>,
        _range: &std::ops::Range<usize>,
        _new_len: usize,
    ) {
    }

    /// Refreshes language-server state after the text changed.
    fn refresh_language_features(
        _state: &mut InputBaseState<Self>,
        _window: &mut Window,
        _cx: &mut gpui::Context<InputBaseState<Self>>,
    ) {
    }

    /// Takes the pending inline completion, when Tab should accept it.
    fn accept_inline_completion(
        _state: &mut InputBaseState<Self>,
        _window: &mut Window,
        _cx: &mut gpui::Context<InputBaseState<Self>>,
    ) -> bool {
        false
    }

    /// Whether an inline completion is waiting to be accepted.
    fn has_inline_completion(_state: &InputBaseState<Self>) -> bool {
        false
    }

    /// Reacts to a click, for Cmd-click go-to-definition.
    fn on_click(
        _state: &mut InputBaseState<Self>,
        _event: &gpui::MouseDownEvent,
        _offset: usize,
        _window: &mut Window,
        _cx: &mut gpui::Context<InputBaseState<Self>>,
    ) -> bool {
        false
    }

    /// Drops hover state when the pointer leaves or focus moves.
    fn clear_hover_state(
        _state: &mut InputBaseState<Self>,
        _cx: &mut gpui::Context<InputBaseState<Self>>,
    ) {
    }

    /// Offers freshly typed text to the completion engine.
    fn on_text_typed(
        _state: &mut InputBaseState<Self>,
        _range: &std::ops::Range<usize>,
        _text: &str,
        _window: &mut Window,
        _cx: &mut gpui::Context<InputBaseState<Self>>,
    ) {
    }

    /// Drops any inline completion after the text or cursor moved.
    fn clear_inline_completion(
        _state: &mut InputBaseState<Self>,
        _cx: &mut gpui::Context<InputBaseState<Self>>,
    ) {
    }

    /// Closes any open completion or code-action menu.
    fn hide_context_menu(
        _state: &mut InputBaseState<Self>,
        _cx: &mut gpui::Context<InputBaseState<Self>>,
    ) {
    }

    /// Whether a completion or code-action menu is currently open.
    fn is_context_menu_open(_state: &InputBaseState<Self>, _cx: &gpui::App) -> bool {
        false
    }

    /// Lets an open menu consume the action first. Returns true when it did.
    fn handle_context_menu_action(
        _state: &mut InputBaseState<Self>,
        _action: Box<dyn gpui::Action>,
        _window: &mut Window,
        _cx: &mut gpui::Context<InputBaseState<Self>>,
    ) -> bool {
        false
    }

    /// Highlights the symbol under the pointer for go-to-definition.
    ///
    /// Separate from [`Self::on_mouse_move`]: this runs on paths that have no
    /// mouse event to hand over, such as opening the context menu.
    fn on_hover_definition(
        _state: &mut InputBaseState<Self>,
        _offset: usize,
        _window: &mut Window,
        _cx: &mut gpui::Context<InputBaseState<Self>>,
    ) {
    }

    /// Reacts to the pointer moving, for the hover popover.
    fn on_mouse_move(
        _state: &mut InputBaseState<Self>,
        _offset: usize,
        _event: &gpui::MouseMoveEvent,
        _window: &mut Window,
        _cx: &mut gpui::Context<InputBaseState<Self>>,
    ) {
    }

    /// Registers the actions that only this mode handles.
    fn register_actions(
        element: Stateful<Div>,
        _entity: &Entity<InputBaseState<Self>>,
        _window: &mut Window,
    ) -> Stateful<Div> {
        element
    }
}

impl InputModeKind for InputMode {
    const MULTI_LINE: bool = false;

    /// A single-line field needs nothing beyond the shared engine. Masking,
    /// validation and number stepping live there: together they are ~120 bytes
    /// and their access sites sit inside the shared edit path, so separating
    /// them would cost more in dispatch than it saves.
    type Extras = ();
}
impl InputModeKind for TextareaMode {
    const MULTI_LINE: bool = true;

    /// Ordinary multi-line text needs nothing beyond the shared engine.
    type Extras = ();
}
// `EditorMode`'s implementation lives with the editor code, next to the
// language features it dispatches to.

/// What a code editor adds on top of multi-line text: language features.
pub struct EditorExtras {
    pub(crate) lsp: Lsp,
    pub(crate) decorations: DecorationCollections,
    pub(crate) range_decorations: DecorationCollections<RangeDecoration>,
    pub(crate) gutter_decorations: DecorationCollections<GutterDecoration>,
    pub(crate) gutter_decorations_width: gpui::Pixels,
    pub(crate) overview_ruler_decorations: DecorationCollections<OverviewRulerDecoration>,
    pub(crate) inline_completion: InlineCompletion,
    pub(crate) context_menu_content: ContextMenuContent,
    pub(crate) hover_popover: Option<HoverPopoverState>,
    pub(crate) hover_definition: HoverDefinition,
    pub(crate) context_menu_task: Task<anyhow::Result<()>>,
}

impl Default for EditorExtras {
    fn default() -> Self {
        Self {
            lsp: Lsp::default(),
            decorations: DecorationCollections::default(),
            range_decorations: DecorationCollections::default(),
            gutter_decorations: DecorationCollections::default(),
            gutter_decorations_width: gpui::px(3.),
            overview_ruler_decorations: DecorationCollections::default(),
            inline_completion: InlineCompletion::default(),
            context_menu_content: ContextMenuContent::default(),
            hover_popover: None,
            hover_definition: HoverDefinition::default(),
            context_menu_task: Task::ready(Ok(())),
        }
    }
}
