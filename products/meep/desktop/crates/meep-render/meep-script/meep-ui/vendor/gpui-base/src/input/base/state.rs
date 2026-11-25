//! A text input field that allows the user to enter text.
//!
//! Based on the `Input` example from the `gpui` crate.
//! https://github.com/zed-industries/zed/blob/main/crates/gpui/examples/input.rs
use gpui::TextAlign;
use gpui::{
    Action, App, AppContext, Bounds, ClipboardItem, Context, Edges, Entity, EntityInputHandler,
    EventEmitter, FocusHandle, Focusable, InteractiveElement as _, IntoElement, KeyBinding,
    MouseButton, MouseDownEvent, MouseMoveEvent, MouseUpEvent, ParentElement as _, Pixels, Point,
    Render, ScrollEvent, ScrollHandle, SharedString, StatefulInteractiveElement as _, Styled as _,
    Subscription, UTF16Selection, WeakFocusHandle, Window, actions, div, point,
    prelude::FluentBuilder as _, px,
};
use gpui::{Autocapitalize, TextInputAction, TextInputConfiguration};
use ropey::{Rope, RopeSlice};
use serde::Deserialize;
use std::borrow::Cow;
use std::cell::Cell;
use std::ops::Range;
use std::rc::Rc;
use sum_tree::Bias;
use unicode_segmentation::*;

use super::{
    DiagnosticSet, DisplayMap, InputContextMenuCapabilities, InputEditorStyle,
    InputHighlighterFactory, MASK_CHAR, MaskPattern, NativeMenu, NumberStep, WrappingIndent,
    blink_cursor::BlinkCursor,
    change::Change,
    cursor::{CursorSelection, Selections},
    element::{
        EditorScrollbar, EditorScrollbarSnapshot, LongestLineKey, OverviewRulerRows, TextElement,
        clamp_horizontal_scroll_offset,
    },
    kind::InputModeKind,
    mask_pattern::normalize_number_input,
    mode::LayoutMode,
    undo_manager::{EditIntent, UndoManager},
};
use crate::actions::{SelectDown, SelectLeft, SelectRight, SelectUp};
use crate::input::blink_cursor::CURSOR_WIDTH;
use crate::input::movement::MoveDirection;
use crate::input::{
    InputEdit, InputExtras as _, Position, RopeExt as _, element::RIGHT_MARGIN, layout::LastLayout,
};
use crate::overscroll::Overscroll;
use crate::{AutoScroll, StepAction, TestSupportExt as _};

pub(super) const EDITOR_ELEMENT_ID: &str = "input-state";

/// Vertical clearance to retain when revealing a text position.
pub(crate) enum ScrollPadding {
    Minimal,
    SurroundingLines,
}

#[derive(Action, Clone, PartialEq, Eq, Deserialize)]
#[action(namespace = input, no_json)]
pub struct Enter {
    /// Is confirm with secondary.
    pub secondary: bool,
    /// Whether the Shift modifier was held when Enter was pressed.
    pub shift: bool,
}

impl Enter {
    /// Returns true if `action` is a primary `Enter` action (`secondary: false`),
    /// regardless of whether Shift was held.
    pub fn is_primary(action: &dyn Action) -> bool {
        action.partial_eq(&Enter {
            secondary: false,
            shift: false,
        }) || action.partial_eq(&Enter {
            secondary: false,
            shift: true,
        })
    }
}

actions!(
    input,
    [
        ActivateToken,
        Backspace,
        Delete,
        DeleteToBeginningOfLine,
        DeleteToEndOfLine,
        DeleteToPreviousWordStart,
        DeleteToNextWordEnd,
        Indent,
        Outdent,
        IndentInline,
        OutdentInline,
        MoveUp,
        MoveDown,
        MoveLeft,
        MoveRight,
        MoveHome,
        MoveEnd,
        MovePageUp,
        MovePageDown,
        AddCursorAbove,
        AddCursorBelow,
        SelectAll,
        SelectToStartOfLine,
        SelectToEndOfLine,
        SelectToStart,
        SelectToEnd,
        SelectToPreviousWordStart,
        SelectToNextWordEnd,
        ShowCharacterPalette,
        Copy,
        Cut,
        Paste,
        Undo,
        Redo,
        MoveToStartOfLine,
        MoveToEndOfLine,
        MoveToStart,
        MoveToEnd,
        MoveToPreviousWord,
        MoveToNextWord,
        Escape,
        ToggleCodeActions,
        ShowCompletions,
        Search,
        Replace,
        GoToDefinition,
    ]
);

/// An event emitted by an input.
///
/// Subscribe to [`InputEditsEvent`] for the immutable edits associated with a
/// change. `Change` itself remains available for consumers that only need a
/// notification.
#[derive(Clone)]
pub enum InputEvent {
    Change,
    PressEnter { secondary: bool, shift: bool },
    Focus,
    Blur,
}

/// An immutable batch of text edits emitted for one input change.
///
/// Each entry contains the edit and the document immediately after it, in
/// application order. Unlike reading the input state in a `Change` subscriber,
/// this snapshot remains associated with its event when updates are queued.
#[derive(Clone)]
pub struct InputEditsEvent {
    edits: Vec<(InputEdit, Rope)>,
}

impl InputEditsEvent {
    /// The edits and the text after each edit, in application order.
    pub fn edits(&self) -> &[(InputEdit, Rope)] {
        &self.edits
    }
}

pub(super) const CONTEXT: &str = "Input";

pub(crate) fn init(cx: &mut App) {
    cx.bind_keys([
        KeyBinding::new("backspace", Backspace, Some(CONTEXT)),
        KeyBinding::new("shift-backspace", Backspace, Some(CONTEXT)),
        #[cfg(target_os = "macos")]
        KeyBinding::new("ctrl-backspace", Backspace, Some(CONTEXT)),
        KeyBinding::new("delete", Delete, Some(CONTEXT)),
        KeyBinding::new("shift-delete", Delete, Some(CONTEXT)),
        #[cfg(target_os = "macos")]
        KeyBinding::new("cmd-backspace", DeleteToBeginningOfLine, Some(CONTEXT)),
        #[cfg(target_os = "macos")]
        KeyBinding::new("cmd-delete", DeleteToEndOfLine, Some(CONTEXT)),
        #[cfg(target_os = "macos")]
        KeyBinding::new("alt-backspace", DeleteToPreviousWordStart, Some(CONTEXT)),
        #[cfg(not(target_os = "macos"))]
        KeyBinding::new("ctrl-backspace", DeleteToPreviousWordStart, Some(CONTEXT)),
        #[cfg(target_os = "macos")]
        KeyBinding::new("alt-delete", DeleteToNextWordEnd, Some(CONTEXT)),
        #[cfg(not(target_os = "macos"))]
        KeyBinding::new("ctrl-delete", DeleteToNextWordEnd, Some(CONTEXT)),
        KeyBinding::new(
            "enter",
            Enter {
                secondary: false,
                shift: false,
            },
            Some(CONTEXT),
        ),
        KeyBinding::new(
            "shift-enter",
            Enter {
                secondary: false,
                shift: true,
            },
            Some(CONTEXT),
        ),
        KeyBinding::new(
            if cx.platform_info().is_mac() {
                "cmd-enter"
            } else {
                "ctrl-enter"
            },
            Enter {
                secondary: true,
                shift: false,
            },
            Some(CONTEXT),
        ),
        KeyBinding::new("escape", Escape, Some(CONTEXT)),
        KeyBinding::new("up", MoveUp, Some(CONTEXT)),
        KeyBinding::new("down", MoveDown, Some(CONTEXT)),
        KeyBinding::new("left", MoveLeft, Some(CONTEXT)),
        KeyBinding::new("right", MoveRight, Some(CONTEXT)),
        KeyBinding::new("pageup", MovePageUp, Some(CONTEXT)),
        KeyBinding::new("pagedown", MovePageDown, Some(CONTEXT)),
        KeyBinding::new("tab", IndentInline, Some(CONTEXT)),
        KeyBinding::new("shift-tab", OutdentInline, Some(CONTEXT)),
        #[cfg(target_os = "macos")]
        KeyBinding::new("cmd-]", Indent, Some(CONTEXT)),
        #[cfg(not(target_os = "macos"))]
        KeyBinding::new("ctrl-]", Indent, Some(CONTEXT)),
        #[cfg(target_os = "macos")]
        KeyBinding::new("cmd-[", Outdent, Some(CONTEXT)),
        #[cfg(not(target_os = "macos"))]
        KeyBinding::new("ctrl-[", Outdent, Some(CONTEXT)),
        KeyBinding::new("shift-left", SelectLeft, Some(CONTEXT)),
        KeyBinding::new("shift-right", SelectRight, Some(CONTEXT)),
        KeyBinding::new("shift-up", SelectUp, Some(CONTEXT)),
        KeyBinding::new("shift-down", SelectDown, Some(CONTEXT)),
        #[cfg(not(any(target_os = "macos", target_os = "linux")))]
        KeyBinding::new("shift-alt-left", SelectLeft, Some(CONTEXT)),
        #[cfg(not(any(target_os = "macos", target_os = "linux")))]
        KeyBinding::new("shift-alt-right", SelectRight, Some(CONTEXT)),
        // Avoid Ctrl+Alt+arrows on Linux, where desktops may reserve them.
        #[cfg(target_os = "macos")]
        KeyBinding::new("cmd-alt-up", AddCursorAbove, Some(CONTEXT)),
        #[cfg(target_os = "macos")]
        KeyBinding::new("cmd-alt-down", AddCursorBelow, Some(CONTEXT)),
        #[cfg(target_os = "windows")]
        KeyBinding::new("ctrl-alt-up", AddCursorAbove, Some(CONTEXT)),
        #[cfg(not(any(target_os = "macos", target_os = "windows")))]
        KeyBinding::new("shift-alt-up", AddCursorAbove, Some(CONTEXT)),
        #[cfg(target_os = "windows")]
        KeyBinding::new("ctrl-alt-down", AddCursorBelow, Some(CONTEXT)),
        #[cfg(not(any(target_os = "macos", target_os = "windows")))]
        KeyBinding::new("shift-alt-down", AddCursorBelow, Some(CONTEXT)),
        KeyBinding::new("home", MoveHome, Some(CONTEXT)),
        KeyBinding::new("end", MoveEnd, Some(CONTEXT)),
        #[cfg(not(target_os = "macos"))]
        KeyBinding::new("ctrl-home", MoveToStart, Some(CONTEXT)),
        #[cfg(not(target_os = "macos"))]
        KeyBinding::new("ctrl-end", MoveToEnd, Some(CONTEXT)),
        #[cfg(not(target_os = "macos"))]
        KeyBinding::new("ctrl-shift-home", SelectToStart, Some(CONTEXT)),
        #[cfg(not(target_os = "macos"))]
        KeyBinding::new("ctrl-shift-end", SelectToEnd, Some(CONTEXT)),
        KeyBinding::new("shift-home", SelectToStartOfLine, Some(CONTEXT)),
        KeyBinding::new("shift-end", SelectToEndOfLine, Some(CONTEXT)),
        #[cfg(target_os = "macos")]
        KeyBinding::new("ctrl-shift-a", SelectToStartOfLine, Some(CONTEXT)),
        #[cfg(target_os = "macos")]
        KeyBinding::new("ctrl-shift-e", SelectToEndOfLine, Some(CONTEXT)),
        #[cfg(target_os = "macos")]
        KeyBinding::new("shift-cmd-left", SelectToStartOfLine, Some(CONTEXT)),
        #[cfg(target_os = "macos")]
        KeyBinding::new("shift-cmd-right", SelectToEndOfLine, Some(CONTEXT)),
        #[cfg(any(target_os = "macos", target_os = "linux"))]
        KeyBinding::new("alt-shift-left", SelectToPreviousWordStart, Some(CONTEXT)),
        #[cfg(not(target_os = "macos"))]
        KeyBinding::new("ctrl-shift-left", SelectToPreviousWordStart, Some(CONTEXT)),
        #[cfg(any(target_os = "macos", target_os = "linux"))]
        KeyBinding::new("alt-shift-right", SelectToNextWordEnd, Some(CONTEXT)),
        #[cfg(not(target_os = "macos"))]
        KeyBinding::new("ctrl-shift-right", SelectToNextWordEnd, Some(CONTEXT)),
        #[cfg(target_os = "macos")]
        KeyBinding::new("ctrl-cmd-space", ShowCharacterPalette, Some(CONTEXT)),
        #[cfg(target_os = "macos")]
        KeyBinding::new("cmd-a", SelectAll, Some(CONTEXT)),
        #[cfg(not(target_os = "macos"))]
        KeyBinding::new("ctrl-a", SelectAll, Some(CONTEXT)),
        #[cfg(target_os = "macos")]
        KeyBinding::new("cmd-c", Copy, Some(CONTEXT)),
        #[cfg(not(target_os = "macos"))]
        KeyBinding::new("ctrl-c", Copy, Some(CONTEXT)),
        #[cfg(target_os = "macos")]
        KeyBinding::new("cmd-x", Cut, Some(CONTEXT)),
        #[cfg(not(target_os = "macos"))]
        KeyBinding::new("ctrl-x", Cut, Some(CONTEXT)),
        #[cfg(target_os = "macos")]
        KeyBinding::new("cmd-v", Paste, Some(CONTEXT)),
        #[cfg(not(target_os = "macos"))]
        KeyBinding::new("ctrl-v", Paste, Some(CONTEXT)),
        #[cfg(target_os = "macos")]
        KeyBinding::new("ctrl-a", MoveHome, Some(CONTEXT)),
        #[cfg(target_os = "macos")]
        KeyBinding::new("cmd-left", MoveHome, Some(CONTEXT)),
        #[cfg(target_os = "macos")]
        KeyBinding::new("ctrl-e", MoveEnd, Some(CONTEXT)),
        #[cfg(target_os = "macos")]
        KeyBinding::new("cmd-right", MoveEnd, Some(CONTEXT)),
        #[cfg(target_os = "macos")]
        KeyBinding::new("cmd-z", Undo, Some(CONTEXT)),
        #[cfg(target_os = "macos")]
        KeyBinding::new("cmd-shift-z", Redo, Some(CONTEXT)),
        #[cfg(target_os = "macos")]
        KeyBinding::new("cmd-up", MoveToStart, Some(CONTEXT)),
        #[cfg(target_os = "macos")]
        KeyBinding::new("cmd-down", MoveToEnd, Some(CONTEXT)),
        #[cfg(target_os = "macos")]
        KeyBinding::new("alt-left", MoveToPreviousWord, Some(CONTEXT)),
        #[cfg(target_os = "macos")]
        KeyBinding::new("alt-right", MoveToNextWord, Some(CONTEXT)),
        #[cfg(not(target_os = "macos"))]
        KeyBinding::new("ctrl-left", MoveToPreviousWord, Some(CONTEXT)),
        #[cfg(not(target_os = "macos"))]
        KeyBinding::new("ctrl-right", MoveToNextWord, Some(CONTEXT)),
        #[cfg(target_os = "macos")]
        KeyBinding::new("cmd-shift-up", SelectToStart, Some(CONTEXT)),
        #[cfg(target_os = "macos")]
        KeyBinding::new("cmd-shift-down", SelectToEnd, Some(CONTEXT)),
        #[cfg(not(target_os = "macos"))]
        KeyBinding::new("ctrl-z", Undo, Some(CONTEXT)),
        #[cfg(not(target_os = "macos"))]
        KeyBinding::new("ctrl-y", Redo, Some(CONTEXT)),
        #[cfg(target_os = "macos")]
        KeyBinding::new("cmd-.", ToggleCodeActions, Some(CONTEXT)),
        #[cfg(not(target_os = "macos"))]
        KeyBinding::new("ctrl-.", ToggleCodeActions, Some(CONTEXT)),
        #[cfg(target_os = "macos")]
        KeyBinding::new("cmd-f", Search, Some(CONTEXT)),
        #[cfg(not(target_os = "macos"))]
        KeyBinding::new("ctrl-f", Search, Some(CONTEXT)),
        #[cfg(target_os = "macos")]
        KeyBinding::new("cmd-shift-f", Replace, Some(CONTEXT)),
        #[cfg(not(target_os = "macos"))]
        KeyBinding::new("ctrl-h", Replace, Some(CONTEXT)),
    ]);
}

/// A mouse position resolved for a columnar (block) selection.
///
/// A position past the end of a short row has no glyph to land on, so `offset` clips to
/// that row's end and `columns_past_line_end` keeps what the clip dropped. Together they
/// say which column the pointer really reached, which is what a block spanning rows of
/// different lengths has to be measured in.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) struct ColumnarPoint {
    offset: usize,
    columns_past_line_end: usize,
}

impl ColumnarPoint {
    pub(super) fn new(offset: usize, columns_past_line_end: usize) -> Self {
        Self {
            offset,
            columns_past_line_end,
        }
    }
}

/// The document and selections a paste was asked to replace, taken when the
/// `Paste` action ran so a clipboard read that resolves later can tell
/// whether it still applies. See [`InputBaseState::paste_target`].
#[derive(Debug, PartialEq)]
struct PasteTarget {
    document_revision: u64,
    selections: Vec<CursorSelection>,
}

/// Caret positioning geometry from the input's latest prepaint.
///
/// Unlike `last_layout` (published at paint time), this is stashed during
/// prepaint so caret-anchored popups can position themselves from the
/// current frame's geometry in their deferred prepaint, instead of the
/// previous frame's paint.
#[derive(Clone, Copy, Debug)]
#[doc(hidden)]
pub struct PrepaintCaretGeometry {
    cursor_bounds: Bounds<Pixels>,
    line_height: Pixels,
    input_bounds: Bounds<Pixels>,
    scroll_offset: Point<Pixels>,
    /// A resize owns visibility while its requested repaint settles.
    pub(super) resize_reveal_owned: bool,
}

impl PrepaintCaretGeometry {
    pub(super) fn new(
        cursor_bounds: Bounds<Pixels>,
        line_height: Pixels,
        input_bounds: Bounds<Pixels>,
        scroll_offset: Point<Pixels>,
    ) -> Self {
        Self {
            cursor_bounds,
            line_height,
            input_bounds,
            scroll_offset,
            resize_reveal_owned: false,
        }
    }

    /// The active caret's bounds from the fresh prepaint layout.
    pub fn cursor_bounds(&self) -> Bounds<Pixels> {
        self.cursor_bounds
    }

    /// Line height from the fresh prepaint layout.
    pub fn line_height(&self) -> Pixels {
        self.line_height
    }

    /// The input container bounds from the fresh prepaint.
    pub fn input_bounds(&self) -> Bounds<Pixels> {
        self.input_bounds
    }

    /// The scroll offset that will be in effect after paint, clamped like
    /// `InputBaseState::update_scroll_offset` clamps it.
    pub fn scroll_offset(&self) -> Point<Pixels> {
        self.scroll_offset
    }
}

/// The shared text-editing engine behind [`crate::input::InputState`],
/// [`crate::input::TextareaState`] and [`crate::input::EditorState`].
///
/// `M` is the mode marker: it carries no data and only decides which methods
/// exist, so an ordinary input cannot reach the editor's language features.
///
/// The three states are type aliases of this one, which is why this name is
/// public: an alias is only as usable as the type behind it, so hiding this
/// would leave `InputState` unable to do anything. Prefer naming the aliases
/// — write `InputState`, not `InputBaseState<InputMode>`.
pub struct InputBaseState<M: InputModeKind> {
    /// State only this mode needs. See [`InputModeKind::Extras`].
    pub(crate) extras: M::Extras,
    pub(super) focus_handle: FocusHandle,
    selection_focus: Option<WeakFocusHandle>,
    pub(super) mode: LayoutMode,
    pub(super) text: Rope,
    pub(super) display_map: DisplayMap,
    pub(super) undo_manager: UndoManager,
    pub(super) inline_tokens: Option<Box<super::inline_tokens::InlineTokenStore>>,
    pub(super) pending_token: Option<super::InlineToken>,
    pub(super) replaying_history: bool,
    pub(super) validated_token_edit: bool,
    pub(super) document_revision: u64,
    pub(super) token_presentation: super::InlineTokenPresentation,
    pub(super) token_layout_cache: Option<Box<super::token_presentation::TokenLayoutCache>>,
    /// Real per-frame bounds of the placed token elements, keyed by token
    /// start offset; used for hover payloads and stale-hover reconciliation.
    pub(super) token_bounds: std::collections::HashMap<usize, Bounds<Pixels>>,
    /// The currently hovered token: its entered span, last measured bounds,
    /// and UTF-16 range as of entry. Retained so hover exit can still be
    /// delivered when the token is removed, replaced, scrolled out, or
    /// disabled.
    pub(super) hovered_token: Option<super::token_presentation::HoverSnapshot>,
    pub(super) pending_token_hover_exits: Vec<super::token_presentation::HoverSnapshot>,
    /// The start offset of a pressed token, with the document revision and
    /// pointer position at the press.
    pub(super) pressed_token: Option<(usize, u64, Point<Pixels>)>,
    pub(super) search_session: super::SearchSession,
    /// Advances every time search is explicitly invoked. See
    /// [`InputBaseState::search_activation_revision`].
    pub(super) search_activation_revision: u64,
    pub(super) searchable: bool,
    pub(super) replaceable: bool,
    pub(super) soft_wrap: bool,
    pub(super) wrapping_indent: WrappingIndent,
    pub(super) scroll_beyond_last_line: Option<usize>,
    pub(super) cursor_surrounding_lines: Option<usize>,
    pub(super) blink_cursor: Entity<BlinkCursor>,
    pub(super) loading: bool,
    /// The cursors and selections.
    ///
    /// Always contains at least one selection where index 0 is the active cursor.
    pub(super) selections: Selections,
    /// Range for save the selected word, use to keep word range when drag move.
    pub(super) selected_word_range: Option<CursorSelection>,
    /// The marked range is the temporary insert text on IME typing.
    pub(super) ime_marked_range: Option<CursorSelection>,
    /// Text before an unannounced IME composition, until the next change.
    ime_original_text: Option<Rope>,
    pub(super) last_layout: Option<LastLayout>,
    /// Fresh caret geometry stashed during prepaint for caret-anchored popups.
    ///
    /// Popups are positioned in their deferred prepaint, which runs after the
    /// input's prepaint but before its paint, so they read this instead of
    /// the previous frame's `last_layout`.
    pub(crate) prepaint_caret_geometry: Option<PrepaintCaretGeometry>,
    pub(super) last_cursor: Option<usize>,
    /// The input container bounds
    pub(super) input_bounds: Bounds<Pixels>,
    /// The text bounds
    pub(super) last_bounds: Option<Bounds<Pixels>>,
    /// The fully visible part of the window this input last asked its scroll
    /// containers to reveal it in, while focused. `None` while unfocused.
    pub(super) revealed_viewport: Option<Bounds<Pixels>>,
    pub(super) last_selected_range: Option<CursorSelection>,
    /// The current edit batch, copied into an event when a change is emitted.
    pub(super) last_input_edits: Vec<(InputEdit, Rope)>,
    pub(super) selecting: bool,
    /// Anchor point of an in-progress columnar (block) selection.
    pub(super) column_select_start: Option<ColumnarPoint>,
    /// The selection a long press made, with its handles and edit menu.
    pub(super) touch_selection: super::touch::TouchSelection,
    pub(crate) disabled: bool,
    pub(crate) readonly: bool,
    pub(crate) text_align: TextAlign,
    pub(super) masked: bool,
    pub(super) clean_on_escape: bool,
    pub(super) submit_on_enter: bool,
    /// Overrides for [`Self::text_input_configuration`].
    pub(super) input_action: Option<TextInputAction>,
    pub(super) autocorrect: Option<bool>,
    pub(super) autocapitalize: Option<Autocapitalize>,
    pub(super) show_whitespaces: bool,
    /// This flag tells the renderer to prefer the end of the current visual line.
    pub(crate) cursor_line_end_affinity: bool,
    pub(super) pattern: Option<regex::Regex>,
    pub(super) validate: Option<Box<dyn Fn(&str, &mut App) -> bool + 'static>>,
    /// The step strategy for [`super::NumberInput`] to increment/decrement.
    /// See [`Self::step`] and [`Self::step_by`].
    pub(crate) number_step: Option<NumberStep>,
    /// The minimum value for [`super::NumberInput`]. See [`Self::min`].
    pub(crate) number_min: Option<f64>,
    /// The maximum value for [`super::NumberInput`]. See [`Self::max`].
    pub(crate) number_max: Option<f64>,
    pub(crate) scroll_handle: ScrollHandle,
    /// Whether the text stretches past its ends, see [`Self::scroll_bounce`].
    scroll_bounce: bool,
    /// The text's stretch past an end, while it lasts.
    pub(super) overscroll: Overscroll,
    /// The deferred scroll offset to apply on next layout.
    pub(crate) deferred_scroll_offset: Option<Point<Pixels>>,
    /// The size of the scrollable content.
    pub(crate) scroll_size: gpui::Size<Pixels>,
    pub(super) editor_scrollbar_snapshot: Cell<Option<EditorScrollbarSnapshot>>,
    /// Overview ruler marks in display rows, kept between frames.
    pub(super) overview_ruler_rows: std::cell::RefCell<OverviewRulerRows>,
    /// The widest measured unwrapped line width and what it was measured for.
    pub(super) longest_line_width: Cell<Option<(LongestLineKey, Pixels)>>,
    pub(super) editor_paddings: Edges<Pixels>,
    /// The style this state paints with: what was projected onto it, with
    /// every colour left unset resolved from the palette that is current. It
    /// is rebuilt at the top of every render, which is what keeps it current
    /// when the palette changes after the state was built.
    pub(super) editor_style: InputEditorStyle,
    /// What a consumer projected, kept verbatim so that resolution never
    /// consumes its own output: resolving in place would fill the unset
    /// colours once and then never see them as unset again, which is the same
    /// freeze in a different place.
    projected_editor_style: InputEditorStyle,
    accessibility: Option<InputAccessibility>,
    /// What paints in place of Base's editor scrollbar, when a consumer
    /// supplies its own.
    pub(super) scrollbar_renderer: Option<crate::input::EditorScrollbarRenderer>,

    /// The mask pattern for formatting the input text
    pub(crate) mask_pattern: MaskPattern,
    /// Whether the `mask_pattern` was explicitly set (via [`Self::mask_pattern`]
    /// or [`Self::set_mask_pattern`]), to let [`super::NumberInput`] only apply
    /// its default mask when the user has not made an explicit choice.
    pub(super) mask_pattern_set: bool,
    pub(super) placeholder: SharedString,

    /// Diagnostic currently requested by pointer hover; applications render it.
    pub(super) diagnostic_popover: Option<Rc<crate::input::DiagnosticEntry>>,

    context_menu_handler: Option<
        Rc<dyn Fn(NativeMenu, InputContextMenuCapabilities, Point<Pixels>, &mut Window, &mut App)>,
    >,
    pending_context_menu: Option<(Point<Pixels>, usize)>,

    /// Whether the context menu that shows on right-click is enabled.
    ///
    pub(super) enable_context_menu: bool,

    /// A flag to indicate if we are currently inserting a completion item.
    pub(super) completion_inserting: bool,
    pub(super) overlay_action_handler: Option<
        Rc<
            dyn Fn(
                super::InputOverlayKind,
                Box<dyn Action>,
                &mut Window,
                &mut Context<InputBaseState<M>>,
            ) -> bool,
        >,
    >,

    /// A flag to indicate if we have a pending update to the text.
    ///
    /// If true, will call some update (for example LSP, Syntax Highlight) before render.
    _pending_update: bool,
    /// A flag to indicate if we should ignore the next completion event.
    pub(super) silent_replace_text: bool,
    /// A flag to indicate if we should emit InputEvents.
    pub(super) emit_events: bool,

    _subscriptions: Vec<Subscription>,

    pub(super) auto_scroll: AutoScroll,
}

/// Accessibility presentation for the editor's existing keyboard-focus boundary.
///
/// Frames and their addon controls keep their own identities. This projection
/// does not create a focus handle or register another text Tab stop. The engine
/// supplies the live value and guards accessibility actions against its current
/// disabled, read-only and masked state.
#[derive(Clone, Debug)]
pub struct InputAccessibility {
    role: Option<gpui::Role>,
    label: Option<SharedString>,
    placeholder: Option<SharedString>,
    accessibility_id: Option<SharedString>,
    value_exposed: bool,
}

impl InputAccessibility {
    pub fn new(role: Option<gpui::Role>) -> Self {
        Self {
            role,
            label: None,
            placeholder: None,
            accessibility_id: None,
            value_exposed: true,
        }
    }

    pub fn with_label(mut self, label: Option<SharedString>) -> Self {
        self.label = label;
        self
    }

    pub fn with_placeholder(mut self, placeholder: Option<SharedString>) -> Self {
        self.placeholder = placeholder;
        self
    }

    pub fn with_accessibility_id(mut self, id: Option<SharedString>) -> Self {
        self.accessibility_id = id;
        self
    }

    /// Suppress values for secret content even when the mask is revealed.
    pub fn with_value_exposed(mut self, exposed: bool) -> Self {
        self.value_exposed = exposed;
        self
    }

    pub fn role(&self) -> Option<gpui::Role> {
        self.role
    }

    pub fn label(&self) -> Option<&SharedString> {
        self.label.as_ref()
    }

    pub fn placeholder(&self) -> Option<&SharedString> {
        self.placeholder.as_ref()
    }

    pub fn accessibility_id(&self) -> Option<&SharedString> {
        self.accessibility_id.as_ref()
    }

    pub fn value_exposed(&self) -> bool {
        self.value_exposed
    }
}

/// Read-only styling data exposed to presentation facades.
///
/// The fields are private and read through the methods below, so that a new
/// one can be added without breaking the facades.
#[derive(Clone)]
pub struct InputPresentation {
    focus_handle: FocusHandle,
    disabled: bool,
    readonly: bool,
    loading: bool,
    masked: bool,
    multi_line: bool,
    code_editor: bool,
    text_align: TextAlign,
    placeholder: SharedString,
    mask_placeholder: Option<String>,
}

impl InputPresentation {
    pub fn focus_handle(&self) -> &FocusHandle {
        &self.focus_handle
    }

    pub fn is_disabled(&self) -> bool {
        self.disabled
    }

    pub fn is_readonly(&self) -> bool {
        self.readonly
    }

    /// Returns true if the user is allowed to change the text.
    ///
    /// See also: [`InputBaseState::is_editable`].
    pub fn is_editable(&self) -> bool {
        !self.disabled && !self.readonly
    }

    pub fn is_loading(&self) -> bool {
        self.loading
    }

    pub fn is_masked(&self) -> bool {
        self.masked
    }

    pub fn is_multi_line(&self) -> bool {
        self.multi_line
    }

    pub fn is_code_editor(&self) -> bool {
        self.code_editor
    }

    pub fn text_align(&self) -> TextAlign {
        self.text_align
    }

    pub fn placeholder(&self) -> &SharedString {
        &self.placeholder
    }

    /// The placeholder derived from the mask pattern, e.g.: `(___) ___-____`.
    pub fn mask_placeholder(&self) -> Option<&str> {
        self.mask_placeholder.as_deref()
    }
}

impl<M: InputModeKind> EventEmitter<InputEvent> for InputBaseState<M> {}
impl<M: InputModeKind> EventEmitter<InputEditsEvent> for InputBaseState<M> {}

impl<M: InputModeKind> InputBaseState<M> {
    #[doc(hidden)]
    pub fn cursor_layout(&self) -> Option<(Bounds<Pixels>, Pixels)> {
        let layout = self.last_layout.as_ref()?;
        Some((layout.cursor_bounds?, layout.line_height))
    }

    /// Caret geometry from the latest prepaint, for caret-anchored popups.
    ///
    /// Popups positioned in their deferred prepaint read this to anchor to
    /// the current frame's caret instead of the previous frame's paint.
    #[doc(hidden)]
    pub fn prepaint_caret_geometry(&self) -> Option<PrepaintCaretGeometry> {
        self.prepaint_caret_geometry
    }

    pub fn input_bounds(&self) -> Bounds<Pixels> {
        self.input_bounds
    }

    pub fn text_bounds(&self) -> Option<Bounds<Pixels>> {
        self.last_bounds
    }

    /// The cached display map for querying wrapped rows and display positions.
    ///
    /// Reading this does not prepare text or force layout. Before the first
    /// layout, [`DisplayMap::wrap_row_count`] can be zero; prepared empty text
    /// has one row. The count describes content, independent of minimum rows,
    /// auto-grow limits and viewport height.
    ///
    /// Text edits use the cached wrapping parameters. Layout refreshes the
    /// cache after width or font changes; consume that count on a subsequent
    /// render, or use [`Self::prewrap`] to prepare it before the first layout.
    pub fn display_map(&self) -> &DisplayMap {
        &self.display_map
    }

    /// Wrap the text for `font`, `font_size` and `width` before the first
    /// layout, so that [`DisplayMap::wrap_row_count`] is known on the first frame.
    ///
    /// Call it after setting the value and the wrapping indent. `width` is the
    /// width of the input's text area: its width less its padding, and less
    /// the line-number gutter for an editor with line numbers. It wraps as
    /// layout does, a little short of that width and with the state's wrapping
    /// indent. Once the input has been laid out this does nothing, and layout
    /// keeps the wrap up to date. The font and font size must match the input's
    /// actual text style.
    pub fn prewrap(
        &mut self,
        font: gpui::Font,
        font_size: Pixels,
        width: Pixels,
        cx: &mut Context<Self>,
    ) {
        if self.last_layout.is_some() {
            return;
        }
        let wrap_width = (width - RIGHT_MARGIN).max(px(1.));
        self.display_map.set_font(font, font_size, cx);
        self.display_map
            .set_tab_size(self.mode.tab_size().tab_size, cx);
        self.display_map
            .on_layout_changed(self.soft_wrap.then_some(wrap_width), cx);
        self.display_map
            .set_wrapping_indent(self.wrapping_indent, cx);
        self.display_map.ensure_text_prepared(&self.text, cx);
    }

    pub fn diagnostic_popover(&self) -> Option<Rc<crate::input::DiagnosticEntry>> {
        self.diagnostic_popover.clone()
    }

    pub fn presentation(&self) -> InputPresentation {
        InputPresentation {
            focus_handle: self.focus_handle.clone(),
            disabled: self.disabled,
            readonly: self.readonly,
            loading: self.loading,
            masked: self.masked,
            multi_line: self.is_multi_line(),
            code_editor: self.is_code_editor(),
            text_align: self.text_align,
            placeholder: self.placeholder.clone(),
            mask_placeholder: self.mask_pattern.placeholder(),
        }
    }

    /// Whether this input spans more than one line.
    ///
    /// Answered by the mode marker, which is fixed when the state is built.
    /// [`LayoutMode`] holds the row counts and growth policy, not the kind.
    #[inline]
    /// Whether this input paints scrollbars.
    ///
    /// Only a multi-line input can scroll: a single-line input keeps its
    /// caret in view by moving its own offset, and never has a viewport a
    /// user could drag. Adding the editor scrollbar to every input put a
    /// thumb inside every text field, which is a control the field does not
    /// have.
    pub(crate) fn shows_scrollbar(&self) -> bool {
        self.is_multi_line()
    }

    pub fn is_multi_line(&self) -> bool {
        M::MULTI_LINE
    }

    /// Whether this input is a single-line text field. See [`Self::is_multi_line`].
    #[inline]
    pub fn is_single_line(&self) -> bool {
        !M::MULTI_LINE
    }

    /// Whether this input is a source-code editor.
    #[inline]
    pub fn is_code_editor(&self) -> bool {
        M::CODE_EDITOR
    }

    /// Whether the user is allowed to copy the selection out.
    ///
    /// A masked input keeps its value out of the clipboard.
    pub fn is_copyable(&self) -> bool {
        self.selections.iter().any(|sel| !sel.is_empty()) && !self.masked
    }

    pub fn context_menu_capabilities(&self) -> InputContextMenuCapabilities {
        let (go_to_definition, code_actions) = self.extras.context_menu_capabilities();
        InputContextMenuCapabilities::new()
            .disabled(self.disabled)
            .readonly(self.readonly)
            .code_editor(self.is_code_editor())
            .selection(!self.active_selection().is_empty())
            .masked(self.masked)
            .go_to_definition(go_to_definition)
            .code_actions(code_actions)
    }

    pub fn set_text_align(&mut self, text_align: TextAlign, cx: &mut Context<Self>) {
        if !self.is_single_line() || self.text_align == text_align {
            return;
        }

        self.text_align = text_align;
        cx.notify();
    }

    /// Flip the password mask.
    ///
    /// Setting the mask is a single-line method, but flipping it stays here:
    /// the reveal button is rendered from the generic path, and it can only be
    /// switched on through [`crate::input::InputState`] anyway.
    pub fn toggle_masked(&mut self, _: &mut Window, cx: &mut Context<Self>) {
        self.masked = !self.masked;
        cx.notify();
    }

    pub fn on_context_menu(
        &mut self,
        handler: Rc<
            dyn Fn(NativeMenu, InputContextMenuCapabilities, Point<Pixels>, &mut Window, &mut App),
        >,
    ) {
        self.context_menu_handler = Some(handler);
    }

    /// Keeps the selection highlighted while this popup or one of its children has focus.
    ///
    /// This does not transfer keyboard focus or keep the caret visible. The
    /// association holds only a weak focus handle. Pass `None` to clear it.
    pub fn set_selection_focus(&mut self, focus: Option<FocusHandle>, cx: &mut Context<Self>) {
        self.selection_focus = focus.as_ref().map(FocusHandle::downgrade);
        cx.notify();
    }

    /// Whether the input or its associated selection popup has focus.
    pub fn has_selection_focus(&self, window: &Window, cx: &App) -> bool {
        self.focus_handle.is_focused(window)
            || self
                .selection_focus
                .as_ref()
                .and_then(WeakFocusHandle::upgrade)
                .is_some_and(|focus| focus.is_focused(window) || focus.contains_focused(window, cx))
    }

    /// Build the engine. Each mode's own `new` sets its layout on top of this.
    fn new_in_mode(window: &mut Window, cx: &mut Context<Self>) -> Self {
        let focus_handle = cx.focus_handle().tab_stop(true);
        let blink_cursor = cx.new(BlinkCursor::new);
        let undo_manager = UndoManager::new();

        let _subscriptions = vec![
            // Key bindings can consume events before on_key_down. Observe input
            // before action dispatch so every keystroke resets the blink delay.
            cx.intercept_keystrokes({
                let focus_handle = focus_handle.clone();
                let blink_cursor = blink_cursor.downgrade();
                move |_, window, cx| {
                    if focus_handle.is_focused(window) {
                        _ = blink_cursor.update(cx, |cursor, cx| cursor.pause(cx));
                    }
                }
            }),
            // Observe the blink cursor to repaint the view when it changes.
            cx.observe(&blink_cursor, |_, _, cx| cx.notify()),
            // Blink the cursor when the window is active, pause when it's not.
            cx.observe_window_activation(window, |input, window, cx| {
                if window.is_window_active() {
                    let focus_handle = input.focus_handle.clone();
                    if focus_handle.is_focused(window) {
                        input.blink_cursor.update(cx, |blink_cursor, cx| {
                            blink_cursor.start(cx);
                        });
                    }
                }
            }),
            cx.on_focus(&focus_handle, window, Self::on_focus),
            cx.on_blur(&focus_handle, window, Self::on_blur),
        ];

        let text_style = window.text_style();

        Self {
            extras: M::Extras::default(),
            focus_handle: focus_handle.clone(),
            selection_focus: None,
            text: "".into(),
            display_map: DisplayMap::new(text_style.font(), window.rem_size(), None),
            search_session: super::SearchSession::default(),
            search_activation_revision: 0,
            searchable: false,
            replaceable: true,
            soft_wrap: true,
            wrapping_indent: WrappingIndent::default(),
            scroll_beyond_last_line: None,
            cursor_surrounding_lines: None,
            blink_cursor,
            undo_manager,
            inline_tokens: None,
            pending_token: None,
            replaying_history: false,
            validated_token_edit: false,
            document_revision: 0,
            token_presentation: Default::default(),
            token_bounds: Default::default(),
            hovered_token: None,
            pending_token_hover_exits: Vec::new(),
            token_layout_cache: None,
            pressed_token: None,
            selections: Selections::default(),
            selected_word_range: None,
            ime_marked_range: None,
            ime_original_text: None,
            input_bounds: Bounds::default(),
            selecting: false,
            touch_selection: Default::default(),
            disabled: false,
            readonly: false,
            text_align: TextAlign::Left,
            masked: false,
            clean_on_escape: false,
            submit_on_enter: false,
            input_action: None,
            autocorrect: None,
            autocapitalize: None,
            show_whitespaces: false,
            loading: false,
            pattern: None,
            validate: None,
            number_step: Some(NumberStep::Fixed(1.)),
            number_min: None,
            number_max: None,
            mode: LayoutMode::default(),
            last_layout: None,
            prepaint_caret_geometry: None,
            last_bounds: None,
            revealed_viewport: None,
            last_selected_range: None,
            last_input_edits: Vec::new(),
            column_select_start: None,
            last_cursor: None,
            scroll_handle: ScrollHandle::new(),
            scroll_bounce: crate::ScrollBounce::enabled_by_default(),
            overscroll: Overscroll::default(),
            scroll_size: gpui::size(px(0.), px(0.)),
            editor_scrollbar_snapshot: Cell::new(None),
            overview_ruler_rows: Default::default(),
            longest_line_width: Cell::new(None),
            editor_paddings: Edges::default(),
            deferred_scroll_offset: None,
            placeholder: SharedString::default(),
            mask_pattern: MaskPattern::default(),
            mask_pattern_set: false,
            editor_style: InputEditorStyle::default(),
            projected_editor_style: InputEditorStyle::default(),
            accessibility: None,
            scrollbar_renderer: None,
            diagnostic_popover: None,
            context_menu_handler: None,
            pending_context_menu: None,
            enable_context_menu: true,
            completion_inserting: false,
            overlay_action_handler: None,
            silent_replace_text: false,
            emit_events: true,
            _subscriptions,
            _pending_update: false,
            cursor_line_end_affinity: false,
            auto_scroll: AutoScroll::default(),
        }
    }

    /// Sets whether the context menu that shows on right-click is enabled.
    ///
    /// The context menu is enabled by default. Disabling it turns off the
    /// right-click menu entirely, including a custom menu set on the element.
    /// A custom menu already replaces the built-in one, so keep this enabled
    /// to show only your own items.
    pub fn context_menu(mut self, enable: bool) -> Self {
        self.enable_context_menu = enable;
        self
    }

    pub fn set_context_menu_enabled(&mut self, enabled: bool) {
        self.enable_context_menu = enabled;
    }

    /// Set whether search UI allows replacement, default is true.
    #[doc(hidden)]
    pub fn replaceable(mut self, allow: bool) -> Self {
        self.replaceable = allow;
        self
    }

    /// Set placeholder
    pub fn placeholder(mut self, placeholder: impl Into<SharedString>) -> Self {
        self.placeholder = placeholder.into();
        self
    }

    /// Set highlighter language for for [`LayoutMode::CodeEditor`] mode.
    pub fn set_highlighter(
        &mut self,
        new_language: impl Into<SharedString>,
        cx: &mut Context<Self>,
    ) {
        match &mut self.mode {
            LayoutMode::CodeEditor {
                language,
                highlighter,
                ..
            } => {
                language.set_name(new_language.into());
                *highlighter.borrow_mut() = None;
            }
            _ => {}
        }
        self.refresh(cx);
    }

    fn reset_highlighter(&mut self, cx: &mut Context<Self>) {
        match &mut self.mode {
            LayoutMode::CodeEditor { highlighter, .. } => {
                *highlighter.borrow_mut() = None;
            }
            _ => {}
        }
        cx.notify();
    }

    /// Install the parser/highlighter adapter used by code-editor mode.
    pub fn set_highlighter_factory(
        &mut self,
        factory: InputHighlighterFactory,
        cx: &mut Context<Self>,
    ) {
        self.mode.set_highlighter_factory(factory);
        self._pending_update = true;
        self.token_layout_cache = None;
        cx.notify();
    }

    /// Install a default adapter without replacing an application-provided one.
    pub fn ensure_highlighter_factory(&mut self, factory: InputHighlighterFactory) {
        self.mode.ensure_highlighter_factory(factory);
    }

    pub fn set_editor_style(&mut self, style: InputEditorStyle) {
        self.editor_style = style.clone();
        self.projected_editor_style = style;
    }

    /// Project semantics onto the editor, never onto a second focus owner.
    pub fn set_accessibility(&mut self, accessibility: InputAccessibility) {
        self.accessibility = Some(accessibility);
    }

    fn handle_accessibility_focus(&self, window: &mut Window, cx: &mut Context<Self>) {
        if !self.disabled {
            self.focus(window, cx);
        }
    }

    fn handle_accessibility_set_value(
        &mut self,
        data: Option<&gpui::accesskit::ActionData>,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        let Some(gpui::accesskit::ActionData::Value(value)) = data else {
            return;
        };
        // The action may have been queued before editability changed.
        if self.is_editable() {
            self.replace_all(value.to_string(), window, cx);
        }
    }

    /// Set presentation padding for multi-line text and its scrollbar layout.
    #[doc(hidden)]
    pub fn set_editor_paddings(&mut self, paddings: Edges<Pixels>) {
        self.editor_paddings = paddings;
    }

    /// Supply the element painted in place of the editor's scrollbar, or
    /// `None` to keep Base's. The renderer is called where the editor paints
    /// its scrollbar, with that frame's [`EditorScrollbarContext`]. Like
    /// [`Self::set_editor_style`], this does not notify, so it can be called
    /// while rendering.
    ///
    /// [`EditorScrollbarContext`]: crate::input::EditorScrollbarContext
    pub fn set_scrollbar_renderer(
        &mut self,
        renderer: Option<crate::input::EditorScrollbarRenderer>,
    ) {
        self.scrollbar_renderer = renderer;
    }

    pub fn apply_highlighter_fold_candidates(
        &mut self,
        candidates: Vec<crate::input::FoldRange>,
        cx: &mut Context<Self>,
    ) {
        if self.mode.is_folding() {
            self.display_map.set_fold_candidates(candidates);
        }
        cx.notify();
    }

    #[inline]
    pub fn diagnostics(&self) -> Option<&DiagnosticSet> {
        self.mode.diagnostics()
    }

    #[inline]
    pub fn diagnostics_mut(&mut self) -> Option<&mut DiagnosticSet> {
        self.mode.diagnostics_mut()
    }

    /// Set placeholder
    pub fn set_placeholder(
        &mut self,
        placeholder: impl Into<SharedString>,
        _: &mut Window,
        cx: &mut Context<Self>,
    ) {
        self.placeholder = placeholder.into();
        cx.notify();
    }

    /// Find which line and sub-line the given offset belongs to, along with the position within that sub-line.
    ///
    /// Returns:
    ///
    /// - The index of the line (zero-based) containing the offset.
    /// - The index of the sub-line (zero-based) within the line containing the offset.
    /// - The position of the offset.
    pub(super) fn line_and_position_for_offset(
        &self,
        offset: usize,
    ) -> (usize, usize, Option<Point<Pixels>>) {
        let Some(last_layout) = &self.last_layout else {
            return (0, 0, None);
        };
        let line_height = last_layout.line_height;

        let mut y_offset = last_layout.visible_top;
        for (vi, line) in last_layout.lines.iter().enumerate() {
            let prev_lines_offset = last_layout.visible_line_byte_offsets[vi];
            let local_offset = offset.saturating_sub(prev_lines_offset);
            if let Some(pos) = line.position_for_index(local_offset, last_layout, false) {
                let sub_line_index = (pos.y / line_height) as usize;
                let adjusted_pos = point(pos.x + last_layout.line_number_width, pos.y + y_offset);
                return (vi, sub_line_index, Some(adjusted_pos));
            }

            y_offset += line.size(line_height).height;
        }
        (0, 0, None)
    }

    /// Set the value of the input field: plain text, or [`InputContent`] to
    /// restore text together with its inline tokens. Editing history is
    /// cleared and no [`InputEvent::Change`] is emitted.
    ///
    /// For single-line inputs the caret is placed at the end of the text while
    /// the view is scrolled back to the start, so a long value shows its
    /// beginning instead of its tail (matching HTML `<input>`). Multi-line
    /// inputs reset the selection to `0..0`.
    pub fn set_value(
        &mut self,
        value: impl Into<super::InputContent>,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        let content = value.into();
        self.inline_tokens = None;
        self.undo_manager.set_ignoring(true);
        self.emit_events = false;
        self.replace_text(content.text().clone(), window, cx);
        self.ime_original_text = None;
        self.install_tokens(content);
        self.undo_manager.set_ignoring(false);
        self.emit_events = true;

        self.reset_selection();
        self.reset_lsp_state();
        self.reset_scroll_to_start();

        self.undo_manager.clear();
        cx.notify();
    }

    /// Replace the entire text content while preserving undo history.
    ///
    /// Unlike [`set_value`](Self::set_value), this method records the
    /// replacement in the undo stack, allowing the user to undo/redo
    /// the change. The selection is placed at the end of the new text
    /// for single-line inputs, or cleared (0..0) for multi-line inputs.
    ///
    /// Use this when programmatically replacing the full text but the
    /// user should still be able to undo the operation — e.g. formatting.
    pub fn replace_all(
        &mut self,
        text: impl Into<SharedString>,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        self.replace_text(text, window, cx);
        self.reset_selection();
        self.reset_lsp_state();
        self.reset_scroll_to_start();

        cx.notify();
    }

    /// Perform `f` with the user-facing edit restrictions lifted.
    ///
    /// The `disabled` and `readonly` modes only reject the changes made by the
    /// user, the programmatic APIs must always be able to update the text.
    pub(super) fn with_edits_allowed(&mut self, f: impl FnOnce(&mut Self)) {
        let (was_disabled, was_readonly) = (self.disabled, self.readonly);
        (self.disabled, self.readonly) = (false, false);
        f(self);
        (self.disabled, self.readonly) = (was_disabled, was_readonly);
    }

    /// Insert text at the current cursor position.
    ///
    /// And the cursor will be moved to the end of inserted text.
    pub fn insert(
        &mut self,
        text: impl Into<SharedString>,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        let text: SharedString = text.into();
        self.with_edits_allowed(|this| {
            this.undo_manager.set_pending_intent(EditIntent::Atomic);
            let range_utf16 = this.range_to_utf16(&(this.cursor()..this.cursor()));
            this.replace_text_in_range_silent(Some(range_utf16), &text, window, cx);
            let end = this.active_selection().end;
            this.set_cursor_to(end);
        });
    }

    /// Replace text at the current cursor position.
    ///
    /// And the cursor will be moved to the end of replaced text.
    pub fn replace(
        &mut self,
        text: impl Into<SharedString>,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        let text: SharedString = text.into();
        self.with_edits_allowed(|this| {
            this.undo_manager.set_pending_intent(EditIntent::Atomic);
            this.replace_text_in_range_silent(None, &text, window, cx);
            let end = this.active_selection().end;
            this.set_cursor_to(end);
        });
    }

    fn replace_text(
        &mut self,
        text: impl Into<SharedString>,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        let text: SharedString = text.into();
        self.with_edits_allowed(|this| {
            this.undo_manager.set_pending_intent(EditIntent::Atomic);
            let range = 0..this.text.chars().map(|c| c.len_utf16()).sum();
            this.replace_text_in_range_silent(Some(range), &text, window, cx);
            this.reset_highlighter(cx);
        });
    }

    fn reset_selection(&mut self) {
        self.selections.remove_all_but_active();

        // For single-line inputs the caret is placed at the end of the text
        // (matching HTML `<input>`); multi-line inputs reset the selection to
        // `0..0`.
        if self.is_single_line() {
            let end = self.text.len();
            self.set_cursor_to(end);
        } else {
            self.active_selection_mut().clear();
        }
    }

    fn reset_lsp_state(&mut self) {
        if self.is_code_editor() {
            self._pending_update = true;
            M::reset_language_features(self);
        }
    }

    fn reset_scroll_to_start(&mut self) {
        // Move scroll to the start. For single-line the caret is at the end, so
        // override the cursor-follow scroll for the next painted frame to keep
        // the start visible; the deferred offset is consumed during that paint.
        self.scroll_handle.set_offset(point(px(0.), px(0.)));
        if self.is_single_line() {
            self.deferred_scroll_offset = Some(point(px(0.), px(0.)));
        }
    }

    /// Set with disabled mode.
    ///
    /// See also: [`Self::set_disabled`].
    #[allow(unused)]
    pub(crate) fn disabled(mut self, disabled: bool) -> Self {
        self.disabled = disabled;
        self
    }

    pub fn set_disabled(&mut self, disabled: bool, cx: &mut Context<Self>) {
        if self.disabled == disabled {
            return;
        }

        self.disabled = disabled;
        if disabled {
            M::hide_context_menu(self, cx);
            M::clear_inline_completion(self, cx);
        }
        cx.notify();
    }

    /// Set with read-only mode.
    ///
    /// Unlike [`Self::disabled`], a read-only input keeps the normal appearance,
    /// focus, cursor, selection and copy behavior, it only rejects any change
    /// of the text made by the user.
    ///
    /// See also: [`Self::set_readonly`].
    #[allow(unused)]
    pub(crate) fn readonly(mut self, readonly: bool) -> Self {
        self.readonly = readonly;
        self
    }

    pub fn set_readonly(&mut self, readonly: bool, cx: &mut Context<Self>) {
        if self.readonly == readonly {
            return;
        }

        self.readonly = readonly;
        if readonly {
            M::hide_context_menu(self, cx);
            M::clear_inline_completion(self, cx);
            self.search_session.replace_mode = false;
        }
        cx.notify();
    }

    /// Returns true if the user is allowed to change the text.
    ///
    /// This is false when the input is `disabled` or `readonly`, the programmatic
    /// APIs (e.g.: [`Self::set_value`], [`Self::insert`]) are not limited by this.
    pub fn is_editable(&self) -> bool {
        !self.disabled && !self.readonly
    }

    /// Set true to clear the input by pressing Escape key.
    ///
    /// Not on Android, where Escape is also the back button.
    pub fn clean_on_escape(mut self) -> Self {
        self.clean_on_escape = true;
        self
    }

    pub fn set_clean_on_escape(&mut self, clean: bool) {
        self.clean_on_escape = clean;
    }

    /// Set true to treat `Enter` as a submit action in multi-line mode,
    /// while `Shift+Enter` inserts a newline.
    ///
    /// Default is `false` (both `Enter` and `Shift+Enter` insert a newline).
    #[doc(hidden)]
    pub fn submit_on_enter(mut self, submit: bool) -> Self {
        self.submit_on_enter = submit;
        self
    }

    pub fn set_submit_on_enter(&mut self, submit: bool, cx: &mut Context<Self>) {
        self.submit_on_enter = submit;
        cx.notify();
    }

    /// Set the action a software keyboard shows on its enter key, like Search
    /// or Send. Pressing it still emits [`InputEvent::PressEnter`].
    ///
    /// Default is [`TextInputAction::Done`] for a single-line input (and a
    /// multi-line one that submits on enter), and [`TextInputAction::Enter`]
    /// (a line break) for a multi-line input.
    pub fn input_action(mut self, action: TextInputAction) -> Self {
        self.input_action = Some(action);
        self
    }

    /// Set whether the platform may autocorrect the text and offer word
    /// suggestions.
    ///
    /// Default is `false`. Enable this explicitly for fields that accept prose;
    /// masking or revealing text does not change the setting.
    pub fn autocorrect(mut self, autocorrect: bool) -> Self {
        self.autocorrect = Some(autocorrect);
        self
    }

    /// Set how a software keyboard capitalizes the text.
    ///
    /// Default is [`Autocapitalize::None`]. Enable capitalization explicitly for
    /// fields where it is appropriate, independently of autocorrection.
    pub fn autocapitalize(mut self, autocapitalize: Autocapitalize) -> Self {
        self.autocapitalize = Some(autocapitalize);
        self
    }

    /// The text assistance a platform IME (a software keyboard) should give
    /// this input, from [`Self::input_action`], [`Self::autocorrect`] and
    /// [`Self::autocapitalize`] or the defaults they describe.
    pub fn text_input_configuration(&self) -> TextInputConfiguration {
        // Masking is a presentation choice, not a reliable content type: a
        // revealed password must not acquire text assistance. Keep assistance
        // opt-in for structured fields such as passwords, email and URLs.
        let autocorrect = self.autocorrect.unwrap_or(false);
        let input_action =
            self.input_action
                .unwrap_or(if self.is_multi_line() && !self.submit_on_enter {
                    TextInputAction::Enter
                } else {
                    TextInputAction::Done
                });
        TextInputConfiguration {
            autocorrect,
            autocapitalize: self.autocapitalize.unwrap_or(Autocapitalize::None),
            suggestions: autocorrect,
            input_action,
        }
    }

    /// Set whether to show whitespace characters.
    #[doc(hidden)]
    pub fn show_whitespaces(mut self, show: bool) -> Self {
        self.show_whitespaces = show;
        self
    }

    /// Update whether to show whitespace characters.
    pub fn set_show_whitespaces(&mut self, show: bool, _: &mut Window, cx: &mut Context<Self>) {
        self.show_whitespaces = show;
        cx.notify();
    }

    /// Empty rows reserved below the last line of content ("scroll
    /// beyond last line"), code-editor mode only. Mirrors VSCode's
    /// `editor.scrollBeyondLastLine` / Zed's `scroll_beyond_last_line`.
    ///
    /// - `None` (default): half the viewport, floored at
    ///   [`BOTTOM_MARGIN_ROWS`] line-heights.
    /// - `Some(0)`: no trailing space; the cursor sits flush with the
    ///   last row at scroll-max.
    /// - `Some(n)`: exactly `n` rows.
    pub fn scroll_beyond_last_line(mut self, rows: Option<usize>) -> Self {
        self.scroll_beyond_last_line = rows;
        self
    }

    /// Update [`Self::scroll_beyond_last_line`] after construction.
    pub fn set_scroll_beyond_last_line(
        &mut self,
        rows: Option<usize>,
        _: &mut Window,
        cx: &mut Context<Self>,
    ) {
        if self.scroll_beyond_last_line == rows {
            return;
        }
        self.scroll_beyond_last_line = rows;
        cx.notify();
    }

    /// Minimum number of lines the cursor is kept clear of the viewport's
    /// top/bottom edge before auto-scroll engages. Mirrors VSCode's
    /// `editor.cursorSurroundingLines` / Zed's `vertical_scroll_margin`.
    /// Orthogonal to [`Self::scroll_beyond_last_line`], which sizes the
    /// empty region; this controls the cursor's resting distance from the
    /// edge.
    ///
    /// - `None` (default): [`BOTTOM_MARGIN_ROWS`] lines, falling back to
    ///   one line on small viewports.
    /// - `Some(n)`: requests `n` lines, clamped to half the viewport.
    ///
    /// In a constrained viewport, edge clearance yields to the cursor's
    /// complete visual row so surrounding space cannot clip the text being edited.
    pub fn cursor_surrounding_lines(mut self, lines: Option<usize>) -> Self {
        self.cursor_surrounding_lines = lines;
        self
    }

    /// Update [`Self::cursor_surrounding_lines`] after construction.
    pub fn set_cursor_surrounding_lines(
        &mut self,
        lines: Option<usize>,
        _: &mut Window,
        cx: &mut Context<Self>,
    ) {
        if self.cursor_surrounding_lines == lines {
            return;
        }
        self.cursor_surrounding_lines = lines;
        cx.notify();
    }

    /// Set the default value of the input field.
    pub fn default_value(mut self, value: impl Into<SharedString>) -> Self {
        let text: SharedString = value.into();
        self.text = Rope::from(self.normalize_input(&text).as_ref());
        if let Some(diagnostics) = self.mode.diagnostics_mut() {
            diagnostics.reset(&self.text)
        }
        // Note: We can't call display_map.set_text here because it needs cx.
        // The text will be set during prepare_if_need in element.rs
        self._pending_update = true;
        self
    }

    /// Return the value of the input field as an owned string.
    ///
    /// The string is materialized on each call. See [`Self::text`] for the
    /// [`Rope`] the state owns, which is borrowed and costs nothing to read.
    pub fn value(&self) -> SharedString {
        SharedString::new(self.text.to_string())
    }

    /// Return the portion of the value within the input field that
    /// is selected by the user, as an owned string.
    ///
    /// The string is materialized on each call. See [`Self::selected_text`]
    /// for the same selection borrowed out of the [`Rope`] the state owns.
    pub fn selected_value(&self) -> SharedString {
        SharedString::new(self.selected_text().to_string())
    }

    /// Return the value without mask.
    pub fn unmask_value(&self) -> SharedString {
        self.mask_pattern.unmask(&self.text.to_string()).into()
    }

    /// Kept so existing render paths keep compiling.
    ///
    /// Configuration used to be collected by a facade and applied here; the
    /// state now configures itself, so this does nothing and can be deleted at
    /// the call site.
    #[doc(hidden)]
    pub fn prepare(&mut self, _: &mut Window, _: &mut Context<Self>) {}

    /// Return the text [`Rope`] of the input field.
    ///
    /// Borrowed from the state, so reading even a large document copies
    /// nothing. See [`Self::value`] when an owned string is wanted.
    pub fn text(&self) -> &Rope {
        &self.text
    }

    /// Report the change with its own snapshot before the legacy notification.
    fn emit_change(&mut self, cx: &mut Context<Self>) {
        if let Some(original) = self.ime_original_text.take() {
            self.last_input_edits = vec![(
                Self::full_input_edit(&original, &self.text),
                self.text.clone(),
            )];
        }
        cx.emit(InputEditsEvent {
            edits: self.last_input_edits.clone(),
        });
        cx.emit(InputEvent::Change);
    }

    fn full_input_edit(old_text: &Rope, new_text: &Rope) -> InputEdit {
        InputEdit {
            start_byte: 0,
            old_end_byte: old_text.len(),
            new_end_byte: new_text.len(),
            start_position: old_text.offset_to_point(0),
            old_end_position: old_text.offset_to_point(old_text.len()),
            new_end_position: new_text.offset_to_point(new_text.len()),
        }
    }

    /// Return the (0-based) [`Position`] of the cursor.
    pub fn cursor_position(&self) -> Position {
        let offset = self.cursor();
        self.text.offset_to_position(offset)
    }

    /// Set (0-based) [`Position`] of the cursor.
    ///
    /// This will move the cursor to the specified line and column, and update the selection range.
    pub fn set_cursor_position(
        &mut self,
        position: impl Into<Position>,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        let position: Position = position.into();
        let offset = self.text.position_to_offset(&position);

        self.move_to(offset, None, cx);
        self.update_preferred_column();
        self.focus(window, cx);
    }

    /// Focus the input field.
    pub fn focus(&self, window: &mut Window, cx: &mut Context<Self>) {
        self.focus_handle.focus(window, cx);
        self.blink_cursor.update(cx, |cursor, cx| {
            cursor.start(cx);
        });
    }

    /// Refresh the input, so the next render re-runs syntax highlighting and
    /// the LSP providers, not just a redraw.
    ///
    /// Assigning the `lsp` providers (or other render-affecting state) at
    /// runtime does not take effect until the text next changes. Call this
    /// afterwards to force the refresh on the next render.
    ///
    /// ```ignore
    /// input.update(cx, |state, cx| {
    ///     state.extras.lsp.hover_provider = Some(provider);
    ///     state.refresh(cx);
    /// });
    /// ```
    pub fn refresh(&mut self, cx: &mut Context<Self>) {
        self._pending_update = true;
        cx.notify();
    }

    pub(super) fn select_left(&mut self, _: &SelectLeft, _: &mut Window, cx: &mut Context<Self>) {
        self.undo_manager.break_transaction_coalescing();
        self.select_all_cursors_to(|s, sel| s.previous_boundary(sel.cursor_offset()), cx);
    }

    pub(super) fn select_right(&mut self, _: &SelectRight, _: &mut Window, cx: &mut Context<Self>) {
        self.select_all_cursors_to(|s, sel| s.next_boundary(sel.cursor_offset()), cx);
    }

    pub(super) fn select_up(&mut self, _: &SelectUp, _: &mut Window, cx: &mut Context<Self>) {
        if self.is_single_line() {
            return;
        }
        self.select_all_cursors_to_with_affinity(
            |s, sel| {
                s.vertical_selection_target(
                    sel.cursor_offset(),
                    sel.column_anchor,
                    s.line_end_affinity_for(sel),
                    -1,
                )
            },
            true,
            cx,
        );
    }

    pub(super) fn select_down(&mut self, _: &SelectDown, _: &mut Window, cx: &mut Context<Self>) {
        if self.is_single_line() {
            return;
        }
        self.select_all_cursors_to_with_affinity(
            |s, sel| {
                s.vertical_selection_target(
                    sel.cursor_offset(),
                    sel.column_anchor,
                    s.line_end_affinity_for(sel),
                    1,
                )
            },
            true,
            cx,
        );
    }

    pub(super) fn on_action_select_all(
        &mut self,
        _: &SelectAll,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        self.select_all(window, cx);
    }

    pub(super) fn select_to_start(
        &mut self,
        _: &SelectToStart,
        _: &mut Window,
        cx: &mut Context<Self>,
    ) {
        self.undo_manager.break_transaction_coalescing();
        self.select_all_cursors_to(|_, _| 0, cx);
    }

    pub(super) fn select_to_end(
        &mut self,
        _: &SelectToEnd,
        _: &mut Window,
        cx: &mut Context<Self>,
    ) {
        self.undo_manager.break_transaction_coalescing();
        let end = self.text.len();
        self.select_all_cursors_to(move |_, _| end, cx);
    }

    pub(super) fn select_to_start_of_line(
        &mut self,
        _: &SelectToStartOfLine,
        _: &mut Window,
        cx: &mut Context<Self>,
    ) {
        self.undo_manager.break_transaction_coalescing();
        self.select_all_cursors_to(
            |s, sel| s.start_of_line_at(sel.cursor_offset(), s.line_end_affinity_for(sel)),
            cx,
        );
    }

    pub(super) fn select_to_end_of_line(
        &mut self,
        _: &SelectToEndOfLine,
        _: &mut Window,
        cx: &mut Context<Self>,
    ) {
        self.undo_manager.break_transaction_coalescing();
        self.select_all_cursors_to_with_affinity(
            |s, sel| {
                (
                    s.end_of_line_at(sel.cursor_offset(), s.line_end_affinity_for(sel)),
                    true,
                )
            },
            false,
            cx,
        );
    }

    pub(super) fn select_to_previous_word(
        &mut self,
        _: &SelectToPreviousWordStart,
        _: &mut Window,
        cx: &mut Context<Self>,
    ) {
        self.undo_manager.break_transaction_coalescing();
        self.select_all_cursors_to(
            |s, sel| s.previous_start_of_word_at(sel.cursor_offset()),
            cx,
        );
    }

    pub(super) fn select_to_next_word(
        &mut self,
        _: &SelectToNextWordEnd,
        _: &mut Window,
        cx: &mut Context<Self>,
    ) {
        self.undo_manager.break_transaction_coalescing();
        self.select_all_cursors_to(|s, sel| s.next_end_of_word_at(sel.cursor_offset()), cx);
    }

    /// Return the start offset of the previous word.
    /// Return the previous start offset of the word before `offset`.
    pub(super) fn previous_start_of_word_at(&self, offset: usize) -> usize {
        if self.masked {
            // The mask replaces every character, so the displayed text has no
            // word boundaries to move or delete by. Collapse the word to the
            // whole text.
            return 0;
        }

        let offset = self.offset_from_utf16(self.offset_to_utf16(offset));
        // FIXME: Avoid to_string
        let left_part = self.text.slice(0..offset).to_string();

        let target = UnicodeSegmentation::split_word_bound_indices(left_part.as_str())
            .rfind(|(_, s)| !s.trim_start().is_empty())
            .map(|(i, _)| i)
            .unwrap_or(0);
        self.token_boundary(target, Bias::Left)
    }

    /// Return the next end offset of the word after `offset`.
    pub(super) fn next_end_of_word_at(&self, offset: usize) -> usize {
        if self.masked {
            // See `previous_start_of_word_at`.
            return self.text.len();
        }

        let offset = self.offset_from_utf16(self.offset_to_utf16(offset));
        let right_part = self.text.slice(offset..self.text.len()).to_string();

        let target = UnicodeSegmentation::split_word_bound_indices(right_part.as_str())
            .find(|(_, s)| !s.trim_start().is_empty())
            .map(|(i, s)| offset + i + s.len())
            .unwrap_or(self.text.len());
        self.token_boundary(target, Bias::Right)
    }

    /// Get start of line byte offset for the given `offset`.
    ///
    /// When soft wrap is active, first press goes to visual line start,
    /// second press (already at visual start) goes to logical line start.
    pub(super) fn start_of_line_at(&self, offset: usize, line_end_affinity: bool) -> usize {
        if self.is_single_line() {
            return 0;
        }

        let row = self.text.offset_to_point(offset).row;
        let logical_start = self.text.line_start_offset(row);

        if self.soft_wrap && self.is_code_editor() {
            let wrap_point = self
                .display_map
                .offset_to_wrap_display_point_with_affinity(offset, line_end_affinity);
            if let Some(line) = self.display_map.line(row)
                && let Some(range) = line.wrapped_lines.get(wrap_point.local_row)
            {
                let visual_start = logical_start + range.start;
                if offset != visual_start {
                    return visual_start;
                }
            }
        }

        logical_start
    }

    /// Get end of line byte offset for the given `offset`.
    ///
    /// When soft wrap is active, first press goes to visual line end,
    /// second press (already at visual end) goes to logical line end.
    pub(super) fn end_of_line_at(&self, offset: usize, line_end_affinity: bool) -> usize {
        if self.is_single_line() {
            return self.text.len();
        }

        let row = self.text.offset_to_point(offset).row;
        let logical_start = self.text.line_start_offset(row);
        let logical_end = self.text.line_end_offset(row);

        if self.soft_wrap && self.is_code_editor() {
            // Use the row the caret is drawn on: at a wrap boundary the raw offset would name
            // the next row, and a second End press would keep walking down instead of falling
            // through to the logical line end.
            let wrap_point = self
                .display_map
                .offset_to_wrap_display_point_with_affinity(offset, line_end_affinity);
            if let Some(line) = self.display_map.line(row)
                && let Some(range) = line.wrapped_lines.get(wrap_point.local_row)
            {
                let visual_end = logical_start + range.end;
                if offset != visual_end {
                    return visual_end;
                }
            }
        }

        logical_end
    }

    /// Get indent string of next line.
    ///
    /// To get current and next line indent, to return more depth one.
    pub(super) fn indent_of_next_line(&mut self) -> String {
        self.indent_of_next_line_at(self.cursor())
    }

    /// Get indent string of the next line, relative to the given `offset`.
    pub(super) fn indent_of_next_line_at(&mut self, offset: usize) -> String {
        if self.is_single_line() {
            return "".into();
        }

        let mut current_indent = String::new();
        let mut next_indent = String::new();
        let line_end_affinity = self.line_end_affinity_at(offset);
        let current_line_start_pos = self.start_of_line_at(offset, line_end_affinity);
        let next_line_start_pos = self.end_of_line_at(offset, line_end_affinity);
        for c in self.text.slice(current_line_start_pos..).chars() {
            if !c.is_whitespace() {
                break;
            }
            if c == '\n' || c == '\r' {
                break;
            }
            current_indent.push(c);
        }

        for c in self.text.slice(next_line_start_pos..).chars() {
            if !c.is_whitespace() {
                break;
            }
            if c == '\n' || c == '\r' {
                break;
            }
            next_indent.push(c);
        }

        if next_indent.len() > current_indent.len() {
            return next_indent;
        }

        // Smart indent: one extra level after lines ending with a trigger.
        // Skipped inside strings and comments: the trigger is literal text.
        if let Some(rules) = self.mode.language_config() {
            if self.mode.is_smart_indent()
                && M::editing_syntax_context(self, offset) == crate::input::SyntaxContext::Code
            {
                let line_before: String = self
                    .text
                    .slice(current_line_start_pos..offset)
                    .chars()
                    .collect();
                if rules.opens_indent(line_before.trim_end()) {
                    let tab = self.mode.tab_size();
                    if tab.hard_tabs {
                        current_indent.push('\t');
                    } else {
                        for _ in 0..tab.tab_size {
                            current_indent.push(' ');
                        }
                    }
                } else {
                    let line_after = self.text.slice(offset..next_line_start_pos).to_string();
                    if rules.closes_indent(&line_after) {
                        let tab = self.mode.tab_size();
                        if current_indent.ends_with('\t') {
                            current_indent.pop();
                        } else {
                            for _ in 0..tab.tab_size {
                                if !current_indent.ends_with(' ') {
                                    break;
                                }
                                current_indent.pop();
                            }
                        }
                    }
                }
            }
        }

        current_indent
    }

    /// Delete every selection as one batch. Collapsed cursors are first
    /// expanded to a deletion range by `collapsed_target` and non-empty
    /// selections delete their own range.
    ///
    /// `collapsed_intent` is the intent to record when every cursor is
    /// collapsed, which is what makes a run of single-character deletes undo
    /// as one gesture. Deleting a real selection is always atomic.
    fn delete_selections(
        &mut self,
        silent: bool,
        collapsed_intent: EditIntent,
        mut collapsed_target: impl FnMut(&mut Self, usize) -> Range<usize>,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        if !self.is_editable() {
            return;
        }
        let cursors: Vec<CursorSelection> = self.selections.iter().copied().collect();
        let intent = if cursors.iter().all(|sel| sel.is_empty()) {
            collapsed_intent
        } else {
            EditIntent::Atomic
        };
        let mut new_selections: Vec<CursorSelection> = Vec::with_capacity(cursors.len());
        for sel in &cursors {
            let range = if sel.is_empty() {
                collapsed_target(self, sel.cursor_offset())
            } else {
                sel.start..sel.end
            };
            let (start, end) = (range.start.min(range.end), range.start.max(range.end));
            let mut selection = *sel;
            selection.start = start;
            selection.end = end;
            new_selections.push(selection);
        }
        // Capture the user's selections before expanding or merging deletion
        // ranges. The edit ranges cannot reconstruct their original carets.
        self.undo_manager.begin_transaction_with(intent);
        self.undo_manager
            .record_selections(cursors.clone(), cursors.clone());
        self.selections.replace_all(new_selections);
        self.undo_manager.set_pending_intent(intent);

        let was_silent = self.silent_replace_text;
        self.silent_replace_text = silent;
        self.replace_text_in_range(None, "", window, cx);
        self.silent_replace_text = was_silent;
        self.undo_manager
            .record_selections(cursors, self.selections.iter().copied().collect());
        self.undo_manager.commit_transaction();
        self.pause_blink_cursor(cx);
    }

    /// Decide pairing against the pre-edit text, before an opening quote can
    /// change its own syntax context. Ordinary characters never query syntax.
    fn auto_close_target(&self, range: &Range<usize>, text: &str) -> Option<(usize, SharedString)> {
        if self.silent_replace_text
            || self.ime_marked_range.is_some()
            || !self.selections.is_single()
            || !self.active_selection().is_empty()
            || !range.is_empty()
            || range.start != self.cursor()
            || text.chars().count() != 1
            || !self.mode.is_auto_close()
        {
            return None;
        }
        let rules = self.mode.language_config()?;
        if self
            .text
            .chars_at(range.start)
            .next()
            .is_some_and(|c| !c.is_whitespace() && !rules.auto_close_before.contains(c))
        {
            return None;
        }
        for (open, close, not_in) in rules.closing_pairs() {
            let Some(prefix) = open.strip_suffix(text) else {
                continue;
            };
            if !self.text_before_matches(range.start, prefix) {
                continue;
            }
            let start = range.start - prefix.len();
            if open == close
                && (self.is_escaped_at(start)
                    || self
                        .text
                        .chars_at(start)
                        .reversed()
                        .next()
                        .is_some_and(|c| c.is_alphanumeric() || c == '_'))
            {
                continue;
            }
            if not_in.contains(&M::editing_syntax_context(self, start)) {
                continue;
            }
            return Some((open.len(), close.into()));
        }
        None
    }

    fn text_before_matches(&self, offset: usize, text: &str) -> bool {
        offset >= text.len()
            && self.text.is_char_boundary(offset - text.len())
            && self.text.slice(offset - text.len()..offset) == text
    }

    fn text_after_matches(&self, offset: usize, text: &str) -> bool {
        offset + text.len() <= self.text.len()
            && self.text.is_char_boundary(offset + text.len())
            && self.text.slice(offset..offset + text.len()) == text
    }

    fn is_escaped_at(&self, offset: usize) -> bool {
        self.text
            .chars_at(offset)
            .reversed()
            .take_while(|c| *c == '\\')
            .count()
            % 2
            == 1
    }

    /// Cursor target when a typed closer should skip over an existing one.
    ///
    /// Returns `Some(offset)` when `new_text` is a single closer from the
    /// active [`LanguageConfig`](crate::input::language_config::LanguageConfig) that already follows the collapsed cursor and is
    /// not escaped. The caller then moves the cursor without editing text or
    /// history. `None` means insert normally.
    fn skip_over_target(&self, new_text: &str) -> Option<usize> {
        if !self.mode.is_auto_close() || new_text.chars().count() != 1 {
            return None;
        }
        let rules = self.mode.language_config()?;
        let cursor = self.cursor();
        for (open, close, not_in) in rules.closing_pairs() {
            for (index, _) in close.char_indices() {
                if !close[index..].starts_with(new_text)
                    || !self.text_before_matches(cursor, &close[..index])
                    || !self.text_after_matches(cursor, &close[index..])
                {
                    continue;
                }
                let context = M::editing_syntax_context(self, cursor);
                let generated =
                    self.mode
                        .auto_closed_pairs()
                        .contains_closer(cursor, index, close.len());
                if !generated
                    && not_in.contains(&context)
                    && !(context == crate::input::SyntaxContext::String && open == close)
                {
                    continue;
                }
                if self.is_escaped_at(cursor - index) {
                    continue;
                }
                return Some(cursor + new_text.len());
            }
        }
        None
    }

    pub(super) fn backspace(&mut self, _: &Backspace, window: &mut Window, cx: &mut Context<Self>) {
        // Nothing to delete at the start of the text. Propagate so an ancestor
        // (e.g. a command palette navigating back a level) can act on it.
        // This is harmless when nothing upstream is bound to backspace. With multiple
        // cursors the others can still delete, so only the lone-cursor case
        // propagates.
        if self.selections.is_single() && self.active_selection().is_empty() && self.cursor() == 0 {
            cx.propagate();
            return;
        }

        // Pair deletion follows automatic closing rules, independently of
        // structural brackets used by Enter.
        if self.mode.is_auto_close()
            && self.selections.is_single()
            && self.active_selection().is_empty()
        {
            let off = self.cursor();
            let deletion = self.mode.language_config().and_then(|rules| {
                rules.closing_pairs().find_map(|(open, close, not_in)| {
                    if !self.text_before_matches(off, open) || !self.text_after_matches(off, close)
                    {
                        return None;
                    }
                    let start = off - open.len();
                    let generated = self
                        .mode
                        .auto_closed_pairs()
                        .contains(start..off, off..off + close.len());
                    if self.is_escaped_at(start)
                        || (!generated && not_in.contains(&M::editing_syntax_context(self, start)))
                    {
                        return None;
                    }
                    Some(start..off + close.len())
                })
            });
            if let Some(range) = deletion {
                let utf16 = self.range_to_utf16(&range);
                self.replace_text_in_range_silent(Some(utf16), "", window, cx);
                return;
            }
        }

        self.delete_selections(
            false,
            EditIntent::Backspace,
            |s, offset| s.previous_boundary(offset)..offset,
            window,
            cx,
        );
    }

    pub(super) fn delete(&mut self, _: &Delete, window: &mut Window, cx: &mut Context<Self>) {
        self.delete_selections(
            false,
            EditIntent::DeleteForward,
            |s, offset| offset..s.next_boundary(offset),
            window,
            cx,
        );
    }

    pub(super) fn delete_to_beginning_of_line(
        &mut self,
        _: &DeleteToBeginningOfLine,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        self.delete_selections(
            true,
            EditIntent::Atomic,
            |s, offset| {
                let mut start = s.start_of_line_at(offset, s.line_end_affinity_at(offset));
                if start == offset {
                    start = start.saturating_sub(1);
                }
                start..offset
            },
            window,
            cx,
        );
    }

    pub(super) fn delete_to_end_of_line(
        &mut self,
        _: &DeleteToEndOfLine,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        self.delete_selections(
            true,
            EditIntent::Atomic,
            |s, offset| {
                let mut end = s.end_of_line_at(offset, s.line_end_affinity_at(offset));
                if end == offset {
                    end = (end + 1).clamp(0, s.text.len());
                }
                offset..end
            },
            window,
            cx,
        );
    }

    pub(super) fn delete_previous_word(
        &mut self,
        _: &DeleteToPreviousWordStart,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        self.delete_selections(
            true,
            EditIntent::Atomic,
            |s, offset| s.previous_start_of_word_at(offset)..offset,
            window,
            cx,
        );
    }

    pub(super) fn delete_next_word(
        &mut self,
        _: &DeleteToNextWordEnd,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        self.delete_selections(
            true,
            EditIntent::Atomic,
            |s, offset| offset..s.next_end_of_word_at(offset),
            window,
            cx,
        );
    }

    pub(super) fn enter(&mut self, action: &Enter, window: &mut Window, cx: &mut Context<Self>) {
        if M::handle_context_menu_action(self, Box::new(action.clone()), window, cx) {
            return;
        }

        // Clear inline completion on enter (user chose not to accept it)
        if M::has_inline_completion(self) {
            M::clear_inline_completion(self, cx);
        }

        // In multi-line mode with `submit_on_enter` enabled, a plain `Enter`
        // (without Shift) is treated as submit: propagate the action and emit
        // PressEnter without inserting a newline. `Shift+Enter` still inserts
        // a newline.
        let insert_newline = self.is_multi_line() && (!self.submit_on_enter || action.shift);

        if insert_newline {
            if !self.selections.is_single() {
                // Insert a newline (with per-line indent) at every cursor.
                self.selections.merge_overlapping();
                let selections: Vec<CursorSelection> = self.selections.iter().copied().collect();
                let mut edits: Vec<(Range<usize>, String)> = Vec::with_capacity(selections.len());
                for sel in &selections {
                    let indent = if self.is_code_editor() {
                        self.indent_of_next_line_at(sel.cursor_offset())
                    } else {
                        String::new()
                    };
                    edits.push((sel.start..sel.end, format!("\n{}", indent)));
                }
                edits.sort_by_key(|(range, _)| range.start);
                self.replace_text_in_ranges(&edits, window, cx);
                self.pause_blink_cursor(cx);
            } else {
                // Bracket split: Enter between `{|}` produces `{\n  \n}`
                // with the cursor on the middle line. Controlled by smart_indent,
                // independently of automatic closing.
                // Skipped inside strings and comments: splitting there would
                // restructure literal text.
                let mut split = false;
                if self.is_code_editor() && self.active_selection().is_empty() {
                    if let Some(rules) = self.mode.language_config() {
                        if self.mode.is_smart_indent()
                            && M::editing_syntax_context(self, self.cursor())
                                == crate::input::SyntaxContext::Code
                        {
                            let off = self.cursor();
                            let is_pair = rules.brackets.iter().any(|p| {
                                !p.open.is_empty()
                                    && !p.close.is_empty()
                                    && p.open != p.close
                                    && self.text_before_matches(off, p.open.as_ref())
                                    && self.text_after_matches(off, p.close.as_ref())
                            });
                            if is_pair {
                                // Base indent: leading whitespace only.
                                let line_end_affinity = self.line_end_affinity_at(off);
                                let line_start = self.start_of_line_at(off, line_end_affinity);
                                let mut indent = String::new();
                                for c in self.text.slice(line_start..).chars() {
                                    if !c.is_whitespace() || c == '\n' || c == '\r' {
                                        break;
                                    }
                                    indent.push(c);
                                }
                                // Extra level only with smart indent enabled.
                                let mut inner = indent.clone();
                                if self.mode.is_smart_indent() {
                                    let tab = self.mode.tab_size();
                                    if tab.hard_tabs {
                                        inner.push('\t');
                                    } else {
                                        for _ in 0..tab.tab_size {
                                            inner.push(' ');
                                        }
                                    }
                                }
                                let new_line_text = format!("\n{inner}\n{indent}");
                                self.replace_text_in_range_silent(None, &new_line_text, window, cx);
                                self.set_cursor_to(off + 1 + inner.len());
                                self.update_preferred_column();
                                let cursors = self.selections.iter().copied().collect::<Vec<_>>();
                                self.undo_manager
                                    .record_selections(cursors.clone(), cursors);
                                self.pause_blink_cursor(cx);
                                split = true;
                            }
                        }
                    }
                }
                if !split {
                    // Get current line indent
                    let indent = if self.is_code_editor() {
                        self.indent_of_next_line()
                    } else {
                        "".to_string()
                    };

                    // Add newline and indent
                    let new_line_text = format!("\n{}", indent);
                    self.replace_text_in_range_silent(None, &new_line_text, window, cx);
                    self.pause_blink_cursor(cx);
                }
            }
        } else {
            // Single line input or submit-on-enter: just emit the event
            // (e.g.: in a dialog to confirm, or a chat textarea to send).
            self.undo_manager.break_transaction_coalescing();
            cx.propagate();
        }

        cx.emit(InputEvent::PressEnter {
            secondary: action.secondary,
            shift: action.shift,
        });
    }

    pub fn clean(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        self.replace_text("", window, cx);
        self.set_selection(0, 0);
        self.scroll_to(0, None, cx);
    }

    pub(super) fn escape(&mut self, action: &Escape, window: &mut Window, cx: &mut Context<Self>) {
        if M::handle_context_menu_action(self, Box::new(action.clone()), window, cx) {
            return;
        }

        // Escape also dismisses a request whose popup has not arrived yet.
        M::hide_context_menu(self, cx);

        // Collapse extra cursors back to the active one first.
        if !self.selections.is_single() {
            self.undo_manager.break_transaction_coalescing();
            self.selections.remove_all_but_active();
            cx.notify();
            return;
        }

        // Clear inline completion on escape
        if M::has_inline_completion(self) {
            M::clear_inline_completion(self, cx);
            return; // Consume the escape, don't propagate
        }
        M::clear_inline_completion(self, cx);

        // The handles and the edit menu are the topmost surface to dismiss.
        if self.touch_selection().is_some() {
            self.dismiss_touch_selection(cx);
            return;
        }

        if self.ime_marked_range.is_some() {
            self.unmark_text(window, cx);
        }

        // Android delivers its back button as escape, and back leaves a field's
        // text alone: it closes what is open or navigates.
        if self.clean_on_escape && !cfg!(target_os = "android") {
            return self.clean(window, cx);
        }

        cx.propagate();
    }

    /// Show the right-click context menu as a native OS menu.
    pub(crate) fn handle_right_click_menu(
        &mut self,
        position: Point<Pixels>,
        offset: usize,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        if self.disabled {
            return;
        }
        if crate::GlobalState::is_in_deferred_context(cx) {
            return;
        }

        if !self.active_selection().contains(offset) {
            self.move_to(offset, None, cx);
        }

        if self.is_code_editor() {
            M::on_hover_definition(self, offset, window, cx);
        }

        if let Some(handler) = self.context_menu_handler.clone() {
            let capabilities = self.context_menu_capabilities();
            let input = cx.weak_entity();
            // The handler runs with the input released, so a custom builder can
            // read it (cursor, selection, text) to build its items.
            window.defer(cx, move |window, cx| {
                if input.upgrade().is_none() {
                    return;
                }
                let previous_focus = window.focused(cx);
                handler(NativeMenu::new(), capabilities, position, window, cx);
                // A drawn menu takes focus synchronously; native menus leave it
                // on the input. Capture it here rather than in the handler.
                input
                    .update(cx, |this, cx| {
                        if window.focused(cx) == previous_focus
                            && !this.focus_handle.is_focused(window)
                            && this.has_selection_focus(window, cx)
                        {
                            // A custom handler can reuse an already-focused popup.
                            return;
                        }
                        let menu_focus = window.focused(cx).filter(|focus| {
                            Some(focus) != previous_focus.as_ref() && *focus != this.focus_handle
                        });
                        this.set_selection_focus(menu_focus, cx);
                    })
                    .ok();
            });
        }
    }

    pub(super) fn add_cursor_above(
        &mut self,
        _: &AddCursorAbove,
        _: &mut Window,
        cx: &mut Context<Self>,
    ) {
        self.add_cursor_vertical(-1, cx);
    }

    pub(super) fn add_cursor_below(
        &mut self,
        _: &AddCursorBelow,
        _: &mut Window,
        cx: &mut Context<Self>,
    ) {
        self.add_cursor_vertical(1, cx);
    }

    /// Add a new cursor one display line above (`move_lines < 0`) or below each
    /// existing cursor, preserving the column. Cursors that would not move (at
    /// the first/last display row) or that would duplicate an existing cursor
    /// are skipped.
    fn add_cursor_vertical(&mut self, move_lines: isize, cx: &mut Context<Self>) {
        if !self.is_multi_line() {
            return;
        }

        self.pause_blink_cursor(cx);
        // Changing the cursor set ends the editing gesture that came before it.
        self.undo_manager.break_transaction_coalescing();

        let sources: Vec<(usize, Option<(Pixels, usize)>, bool)> = self
            .selections
            .iter()
            .map(|sel| {
                (
                    sel.cursor_offset(),
                    sel.column_anchor,
                    self.line_end_affinity_for(sel),
                )
            })
            .collect();
        let mut offsets: std::collections::HashSet<usize> =
            sources.iter().map(|(offset, _, _)| *offset).collect();

        let mut newest: Option<usize> = None;
        for (offset, anchor, line_end_affinity) in sources {
            let anchor = anchor.or_else(|| self.preferred_column_for(offset));
            let (target, _) = self.vertical_target(offset, anchor, line_end_affinity, move_lines);
            if target == offset || offsets.contains(&target) {
                continue;
            }
            offsets.insert(target);
            let id = self.selections.generate_id();
            let mut cursor = CursorSelection::new(id, target, target);
            cursor.column_anchor = anchor;
            self.selections.add(cursor);
            newest = Some(target);
        }

        if let Some(newest) = newest {
            self.scroll_to(newest, None, cx);
        }
        cx.notify();
    }

    /// Add an additional collapsed cursor at `offset`.
    ///
    /// Rejected when `offset` lands inside an existing selection or exactly on
    /// an existing cursor.
    pub(super) fn add_cursor_at(&mut self, offset: usize, cx: &mut Context<Self>) {
        if !self.is_multi_line() {
            return;
        }

        for sel in self.selections.iter() {
            if sel.contains(offset) {
                return;
            }
            if sel.is_collapsed() && sel.cursor_offset() == offset {
                return;
            }
        }

        self.undo_manager.break_transaction_coalescing();
        let id = self.selections.generate_id();
        let mut selection = CursorSelection::new(id, offset, offset);
        selection.column_anchor = self.preferred_column_for(offset);
        self.selections.add(selection);
        cx.notify();
    }

    /// Build a columnar (block) selection spanning the rows between the two
    /// points, one selection per display row at the same column span.
    ///
    /// The span keeps the columns the pointer sat past the end of a short row, so a row
    /// that runs out of text does not narrow the block for the rows that do reach that
    /// far. Each row is then clipped to its own end, selecting as much of the span as it
    /// actually has.
    pub(super) fn build_columnar_selection(
        &mut self,
        start: ColumnarPoint,
        end: ColumnarPoint,
        cx: &mut Context<Self>,
    ) {
        if !self.is_multi_line() {
            return;
        }

        self.undo_manager.break_transaction_coalescing();

        let (start_row, start_col) = self.columnar_row_column(start);
        let (end_row, end_col) = self.columnar_row_column(end);
        let (start_row, end_row) = (start_row.min(end_row), start_row.max(end_row));
        let (start_col, end_col) = (start_col.min(end_col), start_col.max(end_col));

        let mut new_selections = Vec::with_capacity(end_row - start_row + 1);
        for row in start_row..=end_row {
            let sel_start = self
                .display_map
                .display_row_column_to_offset(row, start_col);
            let sel_end = self.display_map.display_row_column_to_offset(row, end_col);
            let id = self.selections.generate_id();
            let sel_start = self.text.clip_offset(sel_start, Bias::Left);
            let sel_end = self.text.clip_offset(sel_end, Bias::Left);
            new_selections.push(CursorSelection::new(id, sel_start, sel_end));
        }

        self.selections.replace_all(new_selections);
        cx.notify();
    }

    /// Resolve a columnar point to the display row it is on and the column it reaches,
    /// counting the columns beyond the row's end so a short row keeps the full span.
    fn columnar_row_column(&self, point: ColumnarPoint) -> (usize, usize) {
        let display_point = self.display_map.offset_to_wrap_display_point(point.offset);
        let row = self
            .display_map
            .wrap_row_to_display_row(display_point.row)
            .unwrap_or_else(|| {
                self.display_map
                    .nearest_visible_display_row(display_point.row)
            });

        (row, display_point.column + point.columns_past_line_end)
    }

    pub(super) fn on_mouse_down(
        &mut self,
        event: &MouseDownEvent,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        // A token that consumed the press (a double click selecting it) must
        // not also place the caret.
        if window.default_prevented() {
            return;
        }
        // A tap asks for the virtual keyboard. Focus alone does not when it
        // moves from another input, or stays here, after the user hid it.
        if event.button == MouseButton::Left
            && crate::GlobalState::is_touch_press(cx)
            && !self.disabled
            && !self.readonly
        {
            window.request_virtual_keyboard();
        }
        self.undo_manager.break_transaction_coalescing();
        // Treat every press like a cursor move: take focus now rather than
        // after GPUI's focus observer runs, show the caret at once and restart
        // the idle delay, whatever phase the blink was in.
        if !self.disabled {
            self.focus(window, cx);
            self.pause_blink_cursor(cx);
        }
        // Input has its own text selection; suppress the window-level text
        // selection (Root) so it does not start a drag from here.
        crate::global_state::GlobalState::suppress_text_selection(cx);

        // Clear inline completion on any mouse interaction
        M::clear_inline_completion(self, cx);
        // A tap on the touch selection asks for its menu back. Any other press
        // places the caret or starts a new drag, and the handles and the menu
        // no longer belong to what is selected.
        if event.button == MouseButton::Left
            && event.click_count == 1
            && self.reopen_edit_menu_at(event.position, cx)
        {
            return;
        }
        self.dismiss_touch_selection(cx);

        // If there have IME marked range and is empty (Means pressed Esc to abort IME typing)
        // Clear the marked range.
        if let Some(ime_marked_range) = &self.ime_marked_range {
            if ime_marked_range.len() == 0 {
                self.ime_marked_range = None;
            }
        }

        self.selecting = true;
        let (offset, line_end_affinity, columns_past_line_end) =
            self.resolve_mouse_position(event.position);

        if M::on_click(self, event, offset, window, cx) {
            return;
        }

        // Triple click to select line
        if event.button == MouseButton::Left && event.click_count >= 3 {
            self.select_line(offset, window, cx);
            return;
        }

        // Double click to select word
        if event.button == MouseButton::Left && event.click_count == 2 {
            self.select_word(offset, window, cx);
            // A double tap is touch's other way to select a word, and it
            // gets the handles and the menu like a long press does.
            if crate::GlobalState::is_touch_press(cx) {
                self.keep_touch_selection(cx);
            }
            return;
        }

        // Show Mouse context menu
        if event.button == MouseButton::Right {
            if self.enable_context_menu {
                if !self.active_selection().contains(offset) {
                    self.move_to(offset, None, cx);
                }
                self.pending_context_menu = Some((event.position, offset));
            }
            return;
        }

        // Multi-cursor placement, multi-line only.
        if self.is_multi_line() && event.button == MouseButton::Left {
            if event.modifiers.alt
                && (event.modifiers.shift || (cfg!(target_os = "linux") && event.modifiers.control))
            {
                // Alt+Shift starts a block; Linux also accepts Ghostty's Ctrl+Alt.
                // Mark selecting so the drag handler extends the block.
                self.column_select_start = Some(ColumnarPoint::new(offset, columns_past_line_end));
                self.selecting = true;
                self.move_to_with_affinity(offset, None, line_end_affinity, cx);
                return;
            } else if event.modifiers.alt {
                self.add_cursor_at(offset, cx);
                // Keep click-to-add behavior, but use this press as the block
                // anchor if the user continues dragging with the left button.
                self.column_select_start = Some(ColumnarPoint::new(offset, columns_past_line_end));
                return;
            }
        }

        if event.modifiers.shift {
            self.select_to_with_affinity(offset, line_end_affinity, cx);
        } else {
            self.move_to_with_affinity(offset, None, line_end_affinity, cx)
        }
    }

    pub(super) fn on_mouse_up(
        &mut self,
        event: &MouseUpEvent,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        if event.button == MouseButton::Right {
            if let Some((position, offset)) = self.pending_context_menu.take() {
                self.handle_right_click_menu(position, offset, window, cx);
            }
        }
        if self.active_selection().is_empty() {
            self.active_selection_mut().reversed = false;
        }
        self.selecting = false;
        self.selected_word_range = None;
        self.column_select_start = None;
        self.auto_scroll.stop();
    }

    pub(super) fn on_mouse_move(
        &mut self,
        event: &MouseMoveEvent,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        // `last_bounds` is moved by the scroll offset; `input_bounds` is the visible area.
        let within_bounds = self.input_bounds.contains(&event.position);

        if !within_bounds {
            // Clear hover when mouse leaves the input
            M::clear_hover_state(self, cx);
            return;
        }

        // Show diagnostic popover on mouse move
        let (offset, _) = self.index_for_mouse_position(event.position);
        M::on_mouse_move(self, offset, event, window, cx);

        if self.is_code_editor() {
            // Keep the current popover while the pointer stays on the same
            // diagnostic, so moving over a squiggle neither repaints nor
            // rebuilds the popover.
            match self
                .mode
                .diagnostics()
                .and_then(|set| set.for_offset(offset))
            {
                Some(diagnostic) => {
                    if self.diagnostic_popover.as_deref() != Some(diagnostic) {
                        self.diagnostic_popover = Some(Rc::new(diagnostic.clone()));
                        cx.notify();
                    }
                }
                None => {
                    if self.diagnostic_popover.take().is_some() {
                        cx.notify();
                    }
                }
            }
        }
    }

    pub(super) fn on_scroll_wheel(
        &mut self,
        event: &ScrollEvent,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        let line_height = self
            .last_layout
            .as_ref()
            .map(|layout| layout.line_height)
            .unwrap_or(window.line_height());
        let delta = event.delta.pixel_delta(line_height);

        let old_offset = self.scroll_handle.offset();
        let precise = matches!(event.delta, gpui::ScrollDelta::Pixels(_));
        if !precise || !self.scroll_bounce || cx.reduce_motion() || !self.overflows_vertically() {
            let displaced = self.overscroll.offset() != 0.;
            self.overscroll.reset();
            if displaced {
                cx.notify();
            }
        }
        let bounces = self.scroll_bounce
            && precise
            && !cx.reduce_motion()
            && delta.y.abs() >= delta.x.abs()
            && self.overflows_vertically();
        if bounces {
            let mut overscroll = std::mem::take(&mut self.overscroll);
            let stretched = overscroll.packet(
                delta.y.as_f32(),
                event.touch_phase,
                self.input_bounds.size.height.as_f32(),
                cx.background_executor().now(),
                |dy| {
                    let before = self.scroll_handle.offset();
                    self.update_scroll_offset(
                        Some(point(before.x + delta.x, before.y + px(dy))),
                        cx,
                    );
                    (self.scroll_handle.offset().y - before.y).as_f32()
                },
            );
            self.overscroll = overscroll;
            if stretched {
                cx.notify();
            }
        } else {
            // Axis drift must not drop the end of a vertical drag.
            if matches!(
                event.touch_phase,
                gpui::TouchPhase::Ended | gpui::TouchPhase::Cancelled
            ) && self.overscroll.offset() != 0.
            {
                self.overscroll.packet(
                    0.,
                    event.touch_phase,
                    self.input_bounds.size.height.as_f32(),
                    cx.background_executor().now(),
                    |_| 0.,
                );
                cx.notify();
            }
            self.update_scroll_offset(Some(old_offset + delta), cx);
        }

        // Text that has room to scroll keeps a scroll over it even where the
        // text ends, so reaching the end does not scroll the region around the
        // input; text that fits leaves the scroll to that region.
        if self.scroll_handle.offset() != old_offset || self.overflows_along(delta) {
            cx.stop_propagation();
        }

        if self.diagnostic_popover.take().is_some() {
            cx.notify();
        }
        // The handles follow the text; the menu would sit over whatever
        // scrolls underneath it, so it steps aside until the finger lifts.
        self.edit_menu_on_scroll(event.touch_phase, cx);
    }

    /// Whether the text takes a wheel event moving by `delta` from the
    /// scroll areas around it: it has room to scroll along the axis the
    /// event mostly moves on. Unlike [`Self::overflows_along`], an event that
    /// moves on neither axis, such as a gesture's start or end, goes to text
    /// that can scroll vertically.
    pub(super) fn takes_scroll(&self, delta: Point<Pixels>) -> bool {
        if delta.y.abs() >= delta.x.abs() {
            self.overflows_vertically()
        } else {
            self.scroll_size.width > self.input_bounds.size.width
        }
    }

    /// Whether the text has room to scroll along the axis `delta` mostly
    /// moves on. A trackpad swipe drifts a little off its axis, so the drift
    /// alone does not claim the scroll.
    fn overflows_along(&self, delta: Point<Pixels>) -> bool {
        if delta.y.abs() >= delta.x.abs() {
            delta.y != px(0.) && self.overflows_vertically()
        } else {
            self.scroll_size.width > self.input_bounds.size.width
        }
    }

    /// Whether multi-line text is taller than the input.
    fn overflows_vertically(&self) -> bool {
        self.is_multi_line() && self.scroll_size.height > self.input_bounds.size.height
    }

    pub(super) fn update_scroll_offset(
        &mut self,
        offset: Option<Point<Pixels>>,
        cx: &mut Context<Self>,
    ) {
        let mut offset = offset.unwrap_or(self.scroll_handle.offset());
        let safe_y_range =
            (-self.scroll_size.height + self.input_bounds.size.height).min(px(0.0))..px(0.);

        offset.y = if self.is_single_line() {
            px(0.)
        } else {
            offset.y.clamp(safe_y_range.start, safe_y_range.end)
        };
        offset.x = clamp_horizontal_scroll_offset(
            offset.x,
            self.scroll_size.width,
            self.input_bounds.size.width,
            self.text_align,
        );
        if self.scroll_handle.offset() != offset {
            self.scroll_handle.set_offset(offset);
            cx.notify();
        }
    }

    /// Scroll to make the given offset visible.
    ///
    /// If `direction` is Some, will keep edges at the same side.
    pub(crate) fn scroll_to(
        &mut self,
        offset: usize,
        direction: Option<MoveDirection>,
        cx: &mut Context<Self>,
    ) {
        let padding = if direction.is_some() {
            ScrollPadding::SurroundingLines
        } else {
            ScrollPadding::Minimal
        };
        self.scroll_to_with_padding(offset, direction, padding, cx);
    }

    /// Reveal an offset with independently chosen direction restriction and padding.
    /// Search uses surrounding lines without restricting movement to match order.
    pub(crate) fn scroll_to_with_padding(
        &mut self,
        offset: usize,
        direction: Option<MoveDirection>,
        padding: ScrollPadding,
        cx: &mut Context<Self>,
    ) {
        let Some(last_layout) = self.last_layout.as_ref() else {
            return;
        };
        let Some(bounds) = self.last_bounds.as_ref() else {
            return;
        };

        let mut scroll_offset = self.scroll_handle.offset();
        let was_offset = scroll_offset;
        let line_height = last_layout.line_height;

        let point = self.text.offset_to_point(offset);

        let row = point.row;

        // Resolve the wrapped row even when the target is outside the last layout.
        let display_row = self
            .display_map
            .offset_to_display_row(offset, self.line_end_affinity_at(offset));
        let row_offset_y = line_height * display_row;

        // For Right alignment use 0 margin: the cursor indicator is clamped inside bounds
        // in layout_cursors, so shifting the text here would cause a first-click visual jump.
        let safety_margin = match last_layout.text_align {
            TextAlign::Left => RIGHT_MARGIN,
            TextAlign::Right => px(0.),
            TextAlign::Center => CURSOR_WIDTH,
        };
        if let Some(vi) = last_layout
            .visible_buffer_lines
            .iter()
            .position(|&line| line == row)
        {
            let line = &last_layout.lines[vi];
            let local_offset = offset.saturating_sub(last_layout.visible_line_byte_offsets[vi]);
            if let Some(pos) = line.position_for_index(local_offset, last_layout, false) {
                let bounds_width = bounds.size.width - last_layout.line_number_width;
                let col_offset_x = pos.x;
                if col_offset_x - safety_margin < -scroll_offset.x {
                    // If the position is out of the visible area, scroll to make it visible
                    scroll_offset.x = -col_offset_x + safety_margin;
                } else if col_offset_x + safety_margin > -scroll_offset.x + bounds_width {
                    scroll_offset.x = -(col_offset_x - bounds_width + safety_margin);
                }
            }
        }

        // Scroll the row into view. Use the same edge clearance helper as
        // `TextElement::layout_cursors` so both scroll-into-view paths agree
        // (a mismatch flickered on `Down` at end-of-buffer with a small
        // `cursor_surrounding_lines` override).
        let edge_height =
            if matches!(padding, ScrollPadding::SurroundingLines) && self.is_code_editor() {
                super::element::cursor_surrounding_padding(
                    self.mode.is_auto_grow(),
                    self.cursor_surrounding_lines,
                    super::element::viewport_visible_lines(bounds.size.height, line_height),
                    line_height,
                )
            } else {
                px(0.)
            };
        scroll_offset.y = super::element::reveal_row(
            scroll_offset.y,
            row_offset_y,
            line_height,
            bounds.size.height,
            edge_height,
        );

        // Avoid necessary scroll, when it was already in the correct position.
        if direction == Some(MoveDirection::Up) {
            scroll_offset.y = scroll_offset.y.max(was_offset.y);
        } else if direction == Some(MoveDirection::Down) {
            scroll_offset.y = scroll_offset.y.min(was_offset.y);
        }

        // Clamp the deferred target into the same safe range that
        // `update_scroll_offset` enforces on persist, so paint never shows an
        // over-scrolled frame before the post-paint clamp pulls it back.
        let safe_y_min = (-self.scroll_size.height + self.input_bounds.size.height).min(px(0.));
        scroll_offset.x = scroll_offset.x.min(px(0.));
        scroll_offset.y = scroll_offset.y.clamp(safe_y_min, px(0.));
        self.deferred_scroll_offset = Some(scroll_offset);
        cx.notify();
    }

    pub(super) fn show_character_palette(
        &mut self,
        _: &ShowCharacterPalette,
        window: &mut Window,
        _: &mut Context<Self>,
    ) {
        window.show_character_palette();
    }

    /// The text of every non-empty selection, in document order.
    fn selected_texts(&self) -> Vec<String> {
        let mut selections: Vec<CursorSelection> = self
            .selections
            .iter()
            .copied()
            .filter(|sel| !sel.is_empty())
            .collect();
        selections.sort_by_key(|sel| sel.start);
        selections
            .iter()
            .map(|sel| self.text.slice(*sel).to_string())
            .collect()
    }

    pub(super) fn copy(&mut self, _: &Copy, _: &mut Window, cx: &mut Context<Self>) {
        if !self.is_copyable() {
            return;
        }

        let texts = self.selected_texts();

        cx.write_to_clipboard(ClipboardItem::new_string(texts.join("\n")));
    }

    pub(super) fn cut(&mut self, _: &Cut, window: &mut Window, cx: &mut Context<Self>) {
        if !self.is_copyable() {
            return;
        }

        let texts = self.selected_texts();

        cx.write_to_clipboard(ClipboardItem::new_string(texts.join("\n")));

        self.undo_manager.set_pending_intent(EditIntent::Atomic);
        self.replace_text_in_range_silent(None, "", window, cx);
    }

    pub(super) fn paste(&mut self, _: &Paste, window: &mut Window, cx: &mut Context<Self>) {
        if !self.is_editable() {
            return;
        }
        if let Some(clipboard) = cx.read_from_clipboard() {
            self.insert_clipboard(clipboard, window, cx);
            return;
        }
        // The synchronous read is empty on platforms whose clipboard is
        // asynchronous and permission-gated (the web), so fall back to the
        // real read. It has to start here, still inside the user activation
        // that dispatched `Paste`, or the browser refuses the read.
        let read = cx.read_from_clipboard_async();
        let target = self.paste_target();
        cx.spawn_in(window, async move |this, cx| match read.await {
            Ok(Some(clipboard)) => {
                this.update_in(cx, |this, window, cx| {
                    // The read can sit behind a permission prompt for as
                    // long as the user likes. If they edited, moved the
                    // caret or left the input meanwhile, the paste would
                    // land where they no longer mean it to; drop it, as the
                    // browser's own paste event only reaches the focused
                    // input too.
                    if this.is_editable()
                        && this.focus_handle.is_focused(window)
                        && this.paste_target() == target
                    {
                        this.insert_clipboard(clipboard, window, cx);
                    }
                })
                .ok();
            }
            Ok(None) => {}
            Err(error) => tracing::warn!("failed to read the clipboard for paste: {error}"),
        })
        .detach();
    }

    /// Where a paste would go right now: the document as edited so far and
    /// the selections it would replace. Two equal targets mean an edit made
    /// for one still applies to the other.
    fn paste_target(&self) -> PasteTarget {
        PasteTarget {
            document_revision: self.document_revision,
            selections: self.selections.iter().copied().collect(),
        }
    }

    /// Inserts the clipboard text the way `Paste` does: one atomic edit,
    /// newlines dropped on a single-line input, one line per selection when
    /// the counts match on a multi-line one. A clipboard without text (an
    /// image, say) is left alone rather than replacing the selection with
    /// nothing.
    fn insert_clipboard(
        &mut self,
        clipboard: ClipboardItem,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        let Some(mut new_text) = clipboard.text().filter(|text| !text.is_empty()) else {
            return;
        };
        // A paste is one atomic edit, never part of a typing run.
        self.undo_manager.set_pending_intent(EditIntent::Atomic);

        if !self.is_multi_line() {
            new_text = new_text.replace('\n', "");
            self.replace_text_in_range_silent(None, &new_text, window, cx);
            self.scroll_to(self.cursor(), None, cx);
            return;
        }

        // Distribute one clipboard line per selection when the counts match.
        // Otherwise insert the whole clipboard text at each cursor.
        if !self.selections.is_single() {
            self.selections.merge_overlapping();
        }
        let lines: Vec<String> = new_text.split('\n').map(|s| s.to_string()).collect();
        let count = self.selections.len();
        if count > 1 && lines.len() == count {
            let mut selections: Vec<CursorSelection> = self.selections.iter().copied().collect();
            selections.sort_by_key(|sel| sel.start);
            let edits: Vec<(Range<usize>, String)> = selections
                .iter()
                .zip(lines)
                .map(|(sel, line)| (sel.start..sel.end, line))
                .collect();
            self.replace_text_in_ranges(&edits, window, cx);
        } else {
            self.replace_text_in_range_silent(None, &new_text, window, cx);
        }
        self.scroll_to(self.cursor(), None, cx);
    }

    /// The intent of a batch the caller did not label: inserting text at
    /// collapsed cursors is typing, anything else stands on its own.
    fn typing_intent(&self, edits: &[(Range<usize>, String)], new_text: &str) -> EditIntent {
        if !new_text.is_empty()
            && !new_text.contains(['\n', '\r'])
            && edits.iter().all(|(range, _)| range.is_empty())
        {
            EditIntent::Typing
        } else {
            EditIntent::Atomic
        }
    }

    /// Where a cursor stood before an edit made with this intent.
    ///
    /// Backspace and forward delete expand a collapsed cursor over the text
    /// they are about to remove, so the recorded cursor has to collapse back to
    /// the side it came from for undo to restore it where the user left it.
    fn collapse_for_intent(
        intent: EditIntent,
        mut selection: CursorSelection,
        range: &Range<usize>,
    ) -> CursorSelection {
        match intent {
            EditIntent::Backspace => selection.place_at(range.end, None),
            EditIntent::DeleteForward => selection.place_at(range.start, None),
            EditIntent::Typing | EditIntent::Atomic => {}
        }
        selection
    }

    /// Whether an edit rewrites the character before a collapsed cursor, as the
    /// macOS Korean IME does on each keystroke instead of marking text.
    fn rewrites_typed_char(
        &self,
        selection: CursorSelection,
        range: &Range<usize>,
        old_text: &str,
        new_text: &str,
    ) -> bool {
        !self.silent_replace_text
            && selection.is_collapsed()
            && selection.cursor_offset() == range.end
            && old_text.chars().count() == 1
            && !old_text.contains(['\n', '\r'])
            && !new_text.contains(['\n', '\r'])
    }

    fn push_history(
        &mut self,
        text: &Rope,
        range: &Range<usize>,
        new_text: &str,
        requested_intent: Option<EditIntent>,
        selection_before: CursorSelection,
        selection_after: Option<CursorSelection>,
    ) -> bool {
        self.document_revision = self.document_revision.wrapping_add(1);
        let token_delta = self.edit_tokens(range, new_text.len());
        if self.undo_manager.is_ignoring() {
            return false;
        }

        let range =
            text.clip_offset(range.start, Bias::Left)..text.clip_offset(range.end, Bias::Right);
        let old_text = text.slice(range.clone()).to_string();
        let new_range = range.start..range.start + new_text.len();

        let intent = requested_intent.unwrap_or_else(|| {
            if range.is_empty()
                && old_text.is_empty()
                && !new_text.is_empty()
                && !new_text.contains(['\n', '\r'])
                || self.rewrites_typed_char(selection_before, &range, &old_text, new_text)
            {
                EditIntent::Typing
            } else {
                EditIntent::Atomic
            }
        });

        let selection_before = Self::collapse_for_intent(intent, selection_before, &range);
        let selection_after =
            selection_after.unwrap_or_else(|| (new_range.end..new_range.end).into());

        let open_transaction = self.undo_manager.has_open_transaction();
        let mut change = Change::new(range, &old_text, new_range, new_text);
        change.token_delta = token_delta;
        let recorded = self.undo_manager.record_transaction(change, intent);
        // A batch records its own cursor sets. This covers a change that is a
        // transaction on its own.
        if recorded && !open_transaction {
            self.undo_manager
                .record_selections(vec![selection_before], vec![selection_after]);
        }
        recorded
    }

    pub(super) fn undo(&mut self, _: &Undo, window: &mut Window, cx: &mut Context<Self>) {
        self.replay_history(true, window, cx);
    }

    pub(super) fn redo(&mut self, _: &Redo, window: &mut Window, cx: &mut Context<Self>) {
        self.replay_history(false, window, cx);
    }

    fn replay_history(&mut self, undo: bool, window: &mut Window, cx: &mut Context<Self>) {
        if !self.is_editable() {
            return;
        }
        let replay = if undo {
            self.undo_manager.undo()
        } else {
            self.undo_manager.redo()
        };
        let Some(replay) = replay else {
            return;
        };
        let token_aware = self.inline_tokens.is_some()
            || replay
                .changes
                .iter()
                .any(|change| change.token_delta.is_some());
        let emit_events = self.emit_events;
        if token_aware {
            self.emit_events = false;
            self.last_input_edits.clear();
        }
        self.replaying_history = token_aware;
        self.undo_manager.set_ignoring(true);
        for change in &replay.changes {
            let (range, text) = if undo {
                (change.new_range.into(), &change.old_text)
            } else {
                (change.old_range.into(), &change.new_text)
            };
            let range_utf16 = self.range_to_utf16(&range);
            self.replace_text_in_range_silent(Some(range_utf16), text, window, cx);
            self.replay_tokens(&range, text.len(), change.token_delta.as_deref(), undo);
        }
        self.restore_selections(replay.selections);
        self.mode
            .restore_auto_closed_pairs(replay.auto_closed_pairs.unwrap_or_default());
        if token_aware {
            // Token replay bypasses IME normalization; a stale marked range
            // would otherwise describe text that no longer exists.
            self.ime_marked_range = None;
        }
        self.undo_manager.set_ignoring(false);
        self.replaying_history = false;
        self.emit_events = emit_events;
        if token_aware {
            if emit_events {
                self.emit_change(cx);
            } else {
                self.last_input_edits.clear();
            }
        }
        cx.notify();
    }

    /// Restore a set of selections captured in a transaction, clamping offsets
    /// to the current text length. `None` leaves the current selections as the
    /// replay left them.
    fn restore_selections(&mut self, selections: Option<Vec<CursorSelection>>) {
        let Some(selections) = selections else {
            return;
        };

        let len = self.text.len();
        let restored: Vec<CursorSelection> = selections
            .into_iter()
            .map(|mut sel| {
                sel.start = sel.start.min(len);
                sel.end = sel.end.min(len);
                sel
            })
            .collect();
        self.selections.replace_all(restored);
        self.selections.merge_overlapping();
    }

    /// Get byte offset of the cursor.
    ///
    /// The offset is the UTF-8 offset.
    pub fn cursor(&self) -> usize {
        if let Some(ime_marked_range) = &self.ime_marked_range {
            return ime_marked_range.end;
        }

        self.selections.active().cursor_offset()
    }

    /// Returns the active selection.
    pub(super) fn active_selection(&self) -> &CursorSelection {
        self.selections.active()
    }

    /// Returns a mutable reference to the active selection.
    pub(super) fn active_selection_mut(&mut self) -> &mut CursorSelection {
        self.selections.active_mut()
    }

    /// Sets the active selection to the given range, keeping its `reversed`
    /// and `column_anchor` state untouched.
    pub(super) fn set_selection(&mut self, start: usize, end: usize) {
        let range = self.normalize_token_range(start..end);
        let (start, end) = (range.start, range.end);
        let active = self.active_selection_mut();
        active.start = start;
        active.end = end;
    }

    /// Collapses the active selection to a cursor at the given offset,
    /// clearing `reversed`.
    pub(super) fn set_cursor_to(&mut self, offset: usize) {
        let offset = self.token_boundary(offset, Bias::Right);
        let active = self.active_selection_mut();
        active.start = offset;
        active.end = offset;
        active.reversed = false;
    }

    /// Visible row range in the last laid-out viewport, `None` before first layout.
    pub fn visible_row_range(&self) -> Option<std::ops::Range<usize>> {
        self.last_layout.as_ref().map(|l| l.visible_range.clone())
    }

    /// Current scroll offset of the editor viewport.
    pub fn scroll_offset(&self) -> gpui::Point<gpui::Pixels> {
        self.scroll_handle.offset()
    }

    /// Set scroll offset of the editor viewport.
    ///
    /// The offset will be clamped to the valid range, and applied after the next layout.
    pub fn set_scroll_offset(&mut self, offset: gpui::Point<gpui::Pixels>, cx: &mut Context<Self>) {
        self.deferred_scroll_offset = Some(offset);
        cx.notify();
    }

    /// Laid-out line height; `None` before first layout.
    pub fn line_height(&self) -> Option<gpui::Pixels> {
        self.last_layout.as_ref().map(|l| l.line_height)
    }

    /// Returns the active selection as a byte range into the text.
    ///
    /// With multiple cursors, this reads only the active selection.
    ///
    /// The range is empty (`start == end`) when no text is selected; in
    /// that case the offset equals `cursor()`. Byte offsets are measured
    /// in the underlying rope's byte units.
    pub fn selected_range(&self) -> std::ops::Range<usize> {
        (*self.selections.active()).into()
    }

    /// Whether the active selection's caret is at the start of its range.
    ///
    /// Collapsed selections are not reversed. Use this with [`Self::selected_range`]
    /// and [`Self::set_selected_range_with_direction`] to restore a selection.
    pub fn is_selection_reversed(&self) -> bool {
        let selection = self.selections.active();
        !selection.is_empty() && selection.reversed
    }

    pub fn select_all(&mut self, _: &mut Window, cx: &mut Context<Self>) {
        self.undo_manager.break_transaction_coalescing();
        self.selections.remove_all_but_active();
        self.set_selection(0, self.text.len());
        cx.notify();
    }

    /// Set the selected range using UTF-8 byte offsets, removing additional cursors.
    ///
    /// Non-empty ranges expand to character boundaries. Empty ranges remain empty and are
    /// clipped to the preceding character boundary.
    pub fn set_selected_range(&mut self, range: Range<usize>, cx: &mut Context<Self>) {
        self.set_selected_range_with_direction(range, false, cx);
    }

    /// Set the selected UTF-8 byte range and the active caret direction.
    ///
    /// With `reversed`, the caret is at the start and the anchor is at the end.
    /// Empty ranges collapse to a caret regardless of direction. Range clipping,
    /// token boundaries and removal of additional cursors follow
    /// [`Self::set_selected_range`].
    pub fn set_selected_range_with_direction(
        &mut self,
        range: Range<usize>,
        reversed: bool,
        cx: &mut Context<Self>,
    ) {
        let range = self.normalize_token_range(range);
        let end_bias = if range.start == range.end {
            Bias::Left
        } else {
            Bias::Right
        };
        let start = self.text.clip_offset(range.start, Bias::Left);
        let end = self.text.clip_offset(range.end, end_bias);

        let (anchor, head) = if reversed { (end, start) } else { (start, end) };
        self.move_to(anchor, None, cx);
        self.active_selection_mut().reversed = false;
        self.selected_word_range = None;
        self.select_to(head, cx);
    }

    /// Add `range` as an additional selection, keeping the existing ones —
    /// the programmatic equivalent of Alt-clicking another cursor into the
    /// text.
    ///
    /// The range is clipped to the text and expanded to character
    /// boundaries, like [`Self::set_selected_range`]. A range already
    /// covered by a selection adds nothing. Overlapping selections are merged.
    /// On a single-line input there is no second cursor to add, so the call
    /// replaces the selection instead.
    /// The view scrolls to the new selection.
    pub fn add_selection(&mut self, range: Range<usize>, cx: &mut Context<Self>) {
        if !self.is_multi_line() {
            self.set_selected_range(range, cx);
            return;
        }

        let range = self.normalize_token_range(range);
        let end_bias = if range.start == range.end {
            Bias::Left
        } else {
            Bias::Right
        };
        let start = self.cursor_boundary(range.start, Bias::Left);
        // Match set_selected_range: expand UTF-8 boundaries first, then place
        // the selection endpoint without splitting a CRLF newline.
        let end = self.cursor_boundary(self.text.clip_offset(range.end, end_bias), Bias::Left);

        for sel in self.selections.iter() {
            if sel.start <= start && end <= sel.end {
                return;
            }
        }

        self.undo_manager.break_transaction_coalescing();
        self.selected_word_range = None;
        self.pause_blink_cursor(cx);
        M::hide_context_menu(self, cx);
        M::clear_inline_completion(self, cx);
        let id = self.selections.generate_id();
        let mut selection = CursorSelection::new(id, start, end);
        selection.column_anchor = self.preferred_column_for(end);
        self.selections.add(selection);
        self.selections.merge_overlapping();
        self.scroll_to(end, None, cx);
        cx.notify();
    }

    /// Resolve a mouse position to a byte offset in the text.
    ///
    /// Also reports the caret's line-end affinity for that offset: `true` when the position
    /// landed on the wrap boundary of a non-final visual row, meaning the caret belongs at the
    /// end of that row rather than at the start of the next one. Callers that place or extend a
    /// selection must pass it on, or clicking past the last glyph of a wrapped row leaves a
    /// caret one row below the pointer.
    pub(crate) fn index_for_mouse_position(&self, position: Point<Pixels>) -> (usize, bool) {
        let (offset, line_end_affinity, _) = self.resolve_mouse_position(position);
        (offset, line_end_affinity)
    }

    /// Resolve a mouse position to a text offset, the caret affinity to use for it, and
    /// how many columns the pointer sits past the end of that row.
    ///
    /// Only a columnar selection needs the third value; everywhere else a position past
    /// the end of a row means the end of that row, and
    /// [`Self::index_for_mouse_position`] is the call to make.
    pub(super) fn resolve_mouse_position(&self, position: Point<Pixels>) -> (usize, bool, usize) {
        // If the text is empty, always return 0
        if self.text.len() == 0 {
            return (0, false, 0);
        }

        let (Some(bounds), Some(last_layout)) =
            (self.last_bounds.as_ref(), self.last_layout.as_ref())
        else {
            return (0, false, 0);
        };

        let line_height = last_layout.line_height;
        let line_number_width = last_layout.line_number_width;

        // TIP: About the IBeam cursor
        //
        // If cursor style is IBeam, the mouse mouse position is in the middle of the cursor (This is special in OS)

        // The position is relative to the bounds of the text input
        //
        // bounds.origin:
        //
        // - included the input padding.
        // - included the scroll offset.
        let inner_position = position - bounds.origin - point(line_number_width, px(0.));

        let mut y_offset = last_layout.visible_top;
        // Position relative to the last line walked, kept for a pointer that ends up
        // below every line.
        let mut last_line_pos = None;

        // Traverse visible buffer lines (compact, no hidden entries)
        for (vi, (line_layout, _buffer_line)) in last_layout
            .lines
            .iter()
            .zip(last_layout.visible_buffer_lines.iter())
            .enumerate()
        {
            let line_start_offset = last_layout.visible_line_byte_offsets[vi];

            // Calculate line origin for this display row
            let line_origin = point(px(0.), y_offset);
            let pos = inner_position - line_origin;

            // Return offset by use closest_index_for_x if is single line mode.
            if self.is_single_line() {
                let local_index = line_layout.closest_index_for_x(pos.x, last_layout);
                // A single line never wraps, so there is no boundary to disambiguate.
                return (
                    self.resolve_index(line_start_offset + local_index),
                    false,
                    0,
                );
            }

            // Check if mouse is in this line's bounds
            if let Some((local_index, line_end_affinity)) =
                line_layout.closest_index_for_position(pos, last_layout)
            {
                return (
                    self.resolve_index(line_start_offset + local_index),
                    line_end_affinity,
                    line_layout.columns_past_line_end(pos, last_layout),
                );
            } else if pos.y < px(0.) {
                // Mouse is above this line, return start of this line
                return (self.resolve_index(line_start_offset), false, 0);
            }

            y_offset += line_layout.size(line_height).height;
            last_line_pos = Some(pos);
        }

        // Clamp to the last laid-out row. Returning the end of the whole document
        // would select unseen text before drag autoscroll has reached it.
        let last_position = last_layout
            .lines
            .last()
            .zip(last_line_pos)
            .zip(last_layout.visible_line_byte_offsets.last())
            .map(|((line_layout, pos), line_start)| {
                let last_row_top = (line_layout.size(line_height).height - line_height).max(px(0.));
                let pos = point(pos.x, last_row_top);
                (
                    self.resolve_index(line_start + line_layout.len()),
                    false,
                    line_layout.columns_past_line_end(pos, last_layout),
                )
            });

        last_position.unwrap_or((self.text.len(), false, 0))
    }

    /// Map a display byte index back to a text offset, undoing the mask expansion when the input
    /// is masked.
    fn resolve_index(&self, index: usize) -> usize {
        if self.masked {
            self.text.char_index_to_offset(index / MASK_CHAR.len_utf8())
        } else {
            index.min(self.text.len())
        }
    }

    /// Returns a y offsetted point for the line origin.
    /// Select the text from the current cursor position to the given offset.
    ///
    /// The offset is the UTF-8 offset.
    ///
    /// Ensure the offset use self.next_boundary or self.previous_boundary to get the correct offset.
    /// Extend a single selection so its moving end lands at `offset`, flipping
    /// `reversed` when the ends cross. When a sticky `word_range` is given the
    /// selection is kept covering it.
    fn extend_selection(
        sel: &mut CursorSelection,
        offset: usize,
        word_range: Option<CursorSelection>,
    ) {
        if sel.reversed {
            sel.start = offset;
        } else {
            sel.end = offset;
        }

        if sel.end < sel.start {
            sel.reversed = !sel.reversed;
            std::mem::swap(&mut sel.start, &mut sel.end);
        }

        if let Some(word_range) = word_range {
            if sel.start > word_range.start {
                sel.start = word_range.start;
            }
            if sel.end < word_range.end {
                sel.end = word_range.end;
            }
        }
    }

    /// Extend only the active selection to `offset`. Used by mouse drag.
    pub(crate) fn select_to(&mut self, offset: usize, cx: &mut Context<Self>) {
        self.select_to_with_affinity(offset, false, cx);
    }

    /// Like [`Self::select_to`], but also carries the caret's line-end affinity.
    ///
    /// See [`Self::move_to_with_affinity`] for why the affinity travels with the offset. Note
    /// that plain [`Self::select_to`] clears the affinity: every offset it is given came from
    /// the text rather than from a visual position, so the caret has no reason to keep sticking
    /// to the end of a wrapped row.
    pub(crate) fn select_to_with_affinity(
        &mut self,
        offset: usize,
        line_end_affinity: bool,
        cx: &mut Context<Self>,
    ) {
        M::clear_inline_completion(self, cx);

        self.cursor_line_end_affinity = line_end_affinity;
        let offset = self.cursor_boundary(offset, Bias::Left);
        let word_range = self.selected_word_range;
        Self::extend_selection(self.active_selection_mut(), offset, word_range);
        let range = self.normalize_token_range(self.selected_range());
        self.set_selection(range.start, range.end);

        if self.active_selection().is_empty() {
            self.update_preferred_column();
        }
        cx.notify()
    }

    /// Extend every selection to the offset produced by `f`, then merge any
    /// selections that now overlap. Used by keyboard selection commands.
    fn select_all_cursors_to(
        &mut self,
        f: impl Fn(&Self, &CursorSelection) -> usize,
        cx: &mut Context<Self>,
    ) {
        self.select_all_cursors_to_with_affinity(|s, sel| (f(s, sel), false), false, cx);
    }

    /// Extend selections with caret affinity, preserving their column anchors even
    /// when vertical movement collapses a selection to a cursor.
    fn select_all_cursors_to_with_affinity(
        &mut self,
        f: impl Fn(&Self, &CursorSelection) -> (usize, bool),
        preserve_column: bool,
        cx: &mut Context<Self>,
    ) {
        self.pause_blink_cursor(cx);
        self.undo_manager.break_transaction_coalescing();
        M::clear_inline_completion(self, cx);

        let mut active_affinity = false;
        let new_selections: Vec<CursorSelection> = self
            .selections
            .iter()
            .map(|sel| {
                let (offset, affinity) = f(self, sel);
                if sel.id == self.active_selection().id {
                    active_affinity = affinity;
                }
                let offset = self.cursor_boundary(offset, Bias::Left);
                let mut new_sel = *sel;
                Self::extend_selection(&mut new_sel, offset, None);
                let range = self.normalize_token_range(new_sel.start..new_sel.end);
                new_sel.start = range.start;
                new_sel.end = range.end;
                if !preserve_column {
                    new_sel.column_anchor =
                        self.preferred_column_for_with_affinity(new_sel.cursor_offset(), affinity);
                } else if new_sel.column_anchor.is_none() {
                    new_sel.column_anchor = self.preferred_column_for_with_affinity(
                        sel.cursor_offset(),
                        self.line_end_affinity_for(sel),
                    );
                }
                new_sel
            })
            .collect();
        self.cursor_line_end_affinity = active_affinity;
        self.selections.replace_all(new_selections);
        self.selections.merge_overlapping();

        self.scroll_to(self.cursor(), None, cx);
        cx.notify()
    }

    /// Unselects the currently selected text.
    pub fn unselect(&mut self, _: &mut Window, cx: &mut Context<Self>) {
        self.undo_manager.break_transaction_coalescing();
        let offset = self.cursor();
        self.set_cursor_to(offset);
        cx.notify()
    }

    #[inline]
    pub(super) fn offset_from_utf16(&self, offset: usize) -> usize {
        self.text.offset_utf16_to_offset(offset)
    }

    #[inline]
    pub(super) fn offset_to_utf16(&self, offset: usize) -> usize {
        self.text.offset_to_offset_utf16(offset)
    }

    #[inline]
    pub(crate) fn range_to_utf16(&self, range: &Range<usize>) -> Range<usize> {
        self.offset_to_utf16(range.start)..self.offset_to_utf16(range.end)
    }

    #[inline]
    pub(super) fn range_from_utf16(&self, range_utf16: &Range<usize>) -> Range<usize> {
        self.offset_from_utf16(range_utf16.start)..self.offset_from_utf16(range_utf16.end)
    }

    /// If offset falls on a hidden (folded) line, clamp backward to the end of
    /// the fold header line (last visible position before the fold).
    fn clamp_offset_to_visible_backward(&self, offset: usize) -> usize {
        let line = self.text.offset_to_point(offset).row;
        if self.display_map.is_buffer_line_hidden(line) {
            for fold in self.display_map.folded_ranges() {
                if line > fold.start_line && line <= fold.end_line {
                    return self.text.line_end_offset(fold.start_line);
                }
            }
        }
        offset
    }

    /// If offset falls on a hidden (folded) line, clamp forward to the start of
    /// the fold end line (first visible position after the fold).
    fn clamp_offset_to_visible_forward(&self, offset: usize) -> usize {
        let line = self.text.offset_to_point(offset).row;
        if self.display_map.is_buffer_line_hidden(line) {
            for fold in self.display_map.folded_ranges() {
                if line > fold.start_line && line <= fold.end_line {
                    return self.text.line_start_offset(fold.end_line);
                }
            }
        }
        offset
    }

    /// Clip a cursor/selection offset without splitting a CRLF newline. This does
    /// not alter the rope or its byte/UTF-16 conversion used for exact source APIs.
    pub(super) fn cursor_boundary(&self, offset: usize, bias: Bias) -> usize {
        let offset = self.token_boundary(self.text.clip_offset(offset, bias), bias);
        if offset > 0
            && self.text.char_at(offset - 1) == Some('\r')
            && self.text.char_at(offset) == Some('\n')
        {
            if bias == Bias::Left {
                offset - 1
            } else {
                offset + 1
            }
        } else {
            offset
        }
    }

    pub(super) fn previous_boundary(&self, offset: usize) -> usize {
        let offset = self.cursor_boundary(offset.saturating_sub(1), Bias::Left);
        self.clamp_offset_to_visible_backward(offset)
    }

    pub(super) fn next_boundary(&self, offset: usize) -> usize {
        let offset = self.cursor_boundary(offset.saturating_add(1), Bias::Right);
        self.clamp_offset_to_visible_forward(offset)
    }

    /// Returns the true to let InputElement to render cursor, when Input is focused and current BlinkCursor is visible.
    pub(crate) fn show_cursor(&self, window: &Window, cx: &App) -> bool {
        (self.focus_handle.is_focused(window) || M::is_context_menu_open(self, cx))
            && !self.disabled
            && self.blink_cursor.read(cx).visible()
            && window.is_window_active()
    }

    fn on_focus(&mut self, _: &mut Window, cx: &mut Context<Self>) {
        self.blink_cursor.update(cx, |cursor, cx| {
            cursor.start(cx);
        });
        cx.emit(InputEvent::Focus);
    }

    fn on_blur(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        self.revealed_viewport = None;
        if M::is_context_menu_open(self, cx) {
            return;
        }

        M::hide_context_menu(self, cx);
        self.undo_manager.break_transaction_coalescing();

        // NOTE: Do not cancel select, when blur.
        // Because maybe user want to copy the selected text by AppMenuBar (will take focus handle).

        M::clear_hover_state(self, cx);
        self.diagnostic_popover = None;
        M::clear_inline_completion(self, cx);
        self.dismiss_touch_selection(cx);
        self.blink_cursor.update(cx, |cursor, cx| {
            cursor.stop(cx);
        });
        self.clamp_number_value(window, cx);
        cx.emit(InputEvent::Blur);
        cx.notify();
    }

    /// Clamp the number value to the `min`/`max` range, used on blur.
    ///
    /// Out-of-range values are allowed while typing (e.g. `1` is an
    /// intermediate state of `15` when min is 10), and clamped on blur.
    fn clamp_number_value(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        if !self.is_single_line() {
            return;
        }
        if !matches!(self.mask_pattern, MaskPattern::Number { .. }) {
            return;
        }
        if self.number_min.is_none() && self.number_max.is_none() {
            return;
        }

        let Ok(value) = self.unmask_value().parse::<f64>() else {
            return;
        };

        let clamped = match (self.number_min, self.number_max) {
            (Some(min), _) if value < min => min,
            (_, Some(max)) if value > max => max,
            _ => return,
        };

        // The clamped value must pass the `pattern`/`validate` check,
        // otherwise keep the value as is.
        let new_text = clamped.to_string();
        if !self.is_valid_input(&new_text, cx) {
            return;
        }

        let range = self.range_to_utf16(&(0..self.text.len()));
        self.replace_text_in_range_silent(Some(range), &new_text, window, cx);
    }

    pub(super) fn pause_blink_cursor(&mut self, cx: &mut Context<Self>) {
        self.blink_cursor.update(cx, |cursor, cx| {
            cursor.pause(cx);
        });
    }

    pub(super) fn on_drag_move(
        &mut self,
        event: &MouseMoveEvent,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        if self.text.len() == 0 {
            return;
        }

        if self.last_layout.is_none() {
            return;
        }

        if !self.focus_handle.is_focused(window) {
            return;
        }

        if !self.selecting {
            return;
        }

        self.auto_scroll.last_drag_position = Some(event.position);
        let (offset, line_end_affinity, columns_past_line_end) =
            self.resolve_mouse_position(event.position);
        if let Some(start) = self.column_select_start {
            let end = ColumnarPoint::new(offset, columns_past_line_end);
            self.build_columnar_selection(start, end, cx);
        } else {
            self.select_to_with_affinity(offset, line_end_affinity, cx);
        }

        if !self.is_single_line() {
            let delta = AutoScroll::compute_delta(event.position.y, self.input_bounds);
            // Input's ScrollHandle uses negative-y-is-down; negate the positive-towards-bottom delta.
            let scroll_delta = delta.map(|d| -d);
            self.auto_scroll.set(scroll_delta, cx, |delta, state, cx| {
                let current = state.scroll_handle.offset();
                state.update_scroll_offset(Some(point(current.x, current.y + delta)), cx);
                if let Some(pos) = state.auto_scroll.last_drag_position {
                    let (offset, line_end_affinity, columns_past_line_end) =
                        state.resolve_mouse_position(pos);
                    if let Some(start) = state.column_select_start {
                        let end = ColumnarPoint::new(offset, columns_past_line_end);
                        state.build_columnar_selection(start, end, cx);
                    } else {
                        state.select_to_with_affinity(offset, line_end_affinity, cx);
                    }
                }
            });
        }
    }

    /// Normalize the inserted text before applying it to the input.
    ///
    /// For number inputs (with [`MaskPattern::Number`]), this converts
    /// full-width number characters into their ASCII equivalents,
    /// e.g. `12。5` -> `12.5`.
    pub(super) fn normalize_input<'a>(&self, new_text: &'a str) -> Cow<'a, str> {
        let normalized = if matches!(self.mask_pattern, MaskPattern::Number { .. }) {
            normalize_number_input(new_text)
        } else {
            Cow::Borrowed(new_text)
        };

        if self.is_single_line() && normalized.contains(['\n', '\r']) {
            Cow::Owned(normalized.replace(['\n', '\r'], ""))
        } else {
            normalized
        }
    }

    pub(crate) fn is_valid_input(&self, new_text: &str, cx: &mut Context<Self>) -> bool {
        if new_text.is_empty() {
            return true;
        }

        if let Some(validate) = &self.validate {
            if !validate(new_text, cx) {
                return false;
            }
        }

        if !self.mask_pattern.is_valid(new_text) {
            return false;
        }

        let Some(pattern) = &self.pattern else {
            return true;
        };

        pattern.is_match(new_text)
    }

    /// Set the mask pattern for formatting the input text.
    ///
    /// The pattern can contain:
    /// - 9: Any digit or dot
    /// - A: Any letter
    /// - *: Any character
    /// - Other characters will be treated as literal mask characters
    ///
    /// Example: "(999)999-999" for phone numbers
    pub fn mask_pattern(mut self, pattern: impl Into<MaskPattern>) -> Self {
        self.mask_pattern = pattern.into();
        self.mask_pattern_set = true;
        if let Some(placeholder) = self.mask_pattern.placeholder() {
            self.placeholder = placeholder.into();
        }
        self
    }

    pub fn set_mask_pattern(
        &mut self,
        pattern: impl Into<MaskPattern>,
        _: &mut Window,
        cx: &mut Context<Self>,
    ) {
        self.mask_pattern = pattern.into();
        self.mask_pattern_set = true;
        if let Some(placeholder) = self.mask_pattern.placeholder() {
            self.placeholder = placeholder.into();
        }
        cx.notify();
    }

    /// Apply the default numeric mask unless the caller explicitly selected a mask.
    pub fn ensure_number_mask(&mut self) {
        if self.mask_pattern_set {
            return;
        }
        self.mask_pattern = MaskPattern::Number {
            separator: None,
            fraction: None,
        };
    }

    pub(super) fn set_input_bounds(&mut self, new_bounds: Bounds<Pixels>, cx: &mut Context<Self>) {
        let wrap_width_changed = self.input_bounds.size.width != new_bounds.size.width;
        self.input_bounds = new_bounds;

        // Update display_map wrap_width if changed.
        if let Some(last_layout) = self.last_layout.as_ref() {
            if wrap_width_changed {
                let wrap_width = if !self.soft_wrap {
                    // None to disable wrapping (will use Pixels::MAX)
                    None
                } else {
                    last_layout.wrap_width
                };

                self.display_map.on_layout_changed(wrap_width, cx);
                if self.is_multi_line() {
                    self.mode.update_auto_grow(&self.display_map);
                }
                cx.notify();
            }
        }
    }

    /// Return the active selection's text, borrowed out of the [`Rope`]
    /// the state owns.
    ///
    /// See [`Self::selected_value`] when an owned string is wanted.
    pub fn selected_text(&self) -> RopeSlice<'_> {
        let range_utf16 = self.range_to_utf16(&self.selected_range());
        let range = self.range_from_utf16(&range_utf16);
        self.text.slice(range)
    }

    /// Return the rendered bounds for a UTF-8 byte range in the current input contents.
    ///
    /// Returns `None` when the requested range is not currently laid out or visible.
    pub fn range_to_bounds(&self, range: &Range<usize>) -> Option<Bounds<Pixels>> {
        let Some(last_layout) = self.last_layout.as_ref() else {
            return None;
        };

        let Some(last_bounds) = self.last_bounds else {
            return None;
        };

        let (_, _, start_pos) = self.line_and_position_for_offset(range.start);
        let (_, _, end_pos) = self.line_and_position_for_offset(range.end);

        let Some(start_pos) = start_pos else {
            return None;
        };
        let Some(end_pos) = end_pos else {
            return None;
        };

        Some(Bounds::from_corners(
            last_bounds.origin + start_pos,
            last_bounds.origin + end_pos + point(px(0.), last_layout.line_height),
        ))
    }

    /// Replace text in range in silent.
    ///
    /// This will not trigger any UI interaction, such as auto-completion.
    pub(crate) fn replace_text_in_range_silent(
        &mut self,
        range_utf16: Option<Range<usize>>,
        new_text: &str,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        self.silent_replace_text = true;
        self.replace_text_in_range(range_utf16, new_text, window, cx);
        self.silent_replace_text = false;
    }

    /// Apply a batch of edits as one atomic history transaction.
    ///
    /// `edits` are `(byte range in the current pre-edit document, replacement)`
    /// pairs.
    pub(crate) fn replace_text_in_ranges(
        &mut self,
        edits: &[(Range<usize>, String)],
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        if !self.is_editable() || edits.is_empty() {
            return;
        }

        // Every edit invalidates provider responses for the previous document,
        // including deletion and indentation which do not trigger completion.
        M::hide_context_menu(self, cx);
        M::clear_inline_completion(self, cx);

        // Sort descending by start so applying front-of-vec first edits the
        // highest offsets first, leaving lower offsets unchanged.
        let mut sorted: Vec<(Range<usize>, &str)> = edits
            .iter()
            .map(|(range, text)| (self.normalize_token_range(range.clone()), text.as_str()))
            .collect();
        sorted.sort_by_key(|edit| std::cmp::Reverse(edit.0.start));
        if !self.token_spans().is_empty() {
            let mut merged: Vec<(Range<usize>, &str)> = Vec::with_capacity(sorted.len());
            for (range, text) in sorted {
                if let Some(last) = merged
                    .last_mut()
                    .filter(|last| range.end > last.0.start || range == last.0)
                {
                    last.0.start = range.start.min(last.0.start);
                    last.0.end = range.end.max(last.0.end);
                } else {
                    merged.push((range, text));
                }
            }
            sorted = merged;
        }

        #[cfg(debug_assertions)]
        for pair in sorted.windows(2) {
            debug_assert!(
                pair[1].0.end <= pair[0].0.start,
                "replace_text_in_ranges requires disjoint ranges"
            );
        }

        // Wrap multiple edits in one explicit transaction so they undo as a
        // unit. A single edit records directly, which keeps it eligible for
        // the undo manager's typing coalescing.
        let requested_intent = self.undo_manager.take_pending_intent();
        let selection_before = *self.active_selection();
        let original_selections: Vec<CursorSelection> = self.selections.iter().copied().collect();
        // Snapshot the cursors before applying, so undo can restore them. A
        // delete has already expanded them over the text it removes, so they
        // collapse back to where the user left them.
        let selections_before: Vec<CursorSelection> = self
            .selections
            .iter()
            .map(|selection| {
                Self::collapse_for_intent(
                    requested_intent.unwrap_or(EditIntent::Atomic),
                    *selection,
                    &(selection.start..selection.end),
                )
            })
            .collect();
        let group = sorted.len() > 1;
        if group {
            self.undo_manager.begin_transaction();
        }

        let auto_closed_pairs_before = self.mode.auto_closed_pairs().clone();
        let mut recorded = false;
        // Several edits reach the highlighter as one batch, so it reparses
        // once for the change instead of once per edit.
        let mut highlighter_edits = Vec::new();
        // Token-aware history replay applies several replacements but emits one
        // `Change` at the end, so its edits accumulate instead of being
        // discarded with each silent replacement.
        let accumulate_replay_edits = self.replaying_history && !self.emit_events;
        if !accumulate_replay_edits {
            self.last_input_edits.clear();
        }
        for (range, new_text) in &sorted {
            let old_text = self.text.clone();
            self.mode.adjust_auto_closed_pair(range, new_text.len());
            self.text.replace(range.clone(), new_text);

            M::adjust_annotations(self, range, new_text.len());
            recorded |= self.push_history(
                &old_text,
                range,
                new_text,
                requested_intent,
                selection_before,
                None,
            );

            // Incremental, single-range updates must run per edit.
            self.display_map
                .adjust_folds_for_edit(&old_text, range, new_text);
            self.display_map
                .on_text_changed(&self.text, range, &Rope::from(*new_text), cx);

            let edit = super::mode::replacement_input_edit(&old_text, &self.text, range, new_text);
            if self.emit_events || self.replaying_history {
                self.last_input_edits.push((edit, self.text.clone()));
            }

            if group {
                if self.is_code_editor() {
                    highlighter_edits.push((edit, self.text.clone()));
                }
            } else {
                self.mode.update_highlighter(
                    super::mode::HighlighterUpdate {
                        selected_range: range,
                        old_text: &old_text,
                        new_text: &self.text,
                        change_text: new_text,
                        force: true,
                        input_edit: Some(edit),
                    },
                    window,
                    cx,
                );

                self.update_fold_candidates_incremental(range, new_text);
            }
        }

        if group {
            self.mode
                .update_highlighter_batch::<M>(&highlighter_edits, window, cx);

            // Fold candidates are read from the reparsed document, so each
            // edit is located where it ended up once every edit was applied.
            // `sorted` runs from the highest offset down.
            let mut shift = 0isize;
            for (range, new_text) in sorted.iter().rev() {
                let start = (range.start as isize + shift) as usize;
                self.update_fold_candidates_incremental(&(start..start), new_text);
                shift += new_text.len() as isize - range.len() as isize;
            }

            self.undo_manager.commit_transaction();
        }

        // One observable update per batch instead of one per edit.
        if let Some(diagnostics) = self.mode.diagnostics_mut() {
            diagnostics.reset(&self.text)
        }
        M::refresh_language_features(self, window, cx);
        self.update_search(cx);

        // Compute the resulting cursors.
        // One collapsed cursor per edit, at the end of its inserted text.
        let mut ascending: Vec<(Range<usize>, &str)> = sorted.clone();
        ascending.sort_by_key(|edit| edit.0.start);
        let text_len = self.text.len();
        let mut delta: isize = 0;
        let mut edit_results = Vec::with_capacity(ascending.len());
        for (range, new_text) in &ascending {
            let offset = ((range.start as isize + delta) as usize + new_text.len()).min(text_len);
            edit_results.push((range.clone(), offset));
            delta += new_text.len() as isize - (range.end as isize - range.start as isize);
        }

        let mut used = vec![false; edit_results.len()];
        let mut new_selections: Vec<CursorSelection> = Vec::with_capacity(ascending.len());
        for selection in original_selections {
            if let Ok(index) = edit_results
                .binary_search_by_key(&(selection.start, selection.end), |(range, _)| {
                    (range.start, range.end)
                })
                && !used[index]
            {
                let offset = edit_results[index].1;
                used[index] = true;
                let mut selection = selection;
                selection.place_at(offset, None);
                new_selections.push(selection);
            }
        }
        for (index, (_, offset)) in edit_results.into_iter().enumerate() {
            if !used[index] {
                new_selections.push(CursorSelection::new(
                    self.selections.generate_id(),
                    offset,
                    offset,
                ));
            }
        }
        self.selections.replace_all(new_selections);
        self.selections.merge_overlapping();

        // Record the cursor snapshots for undo/redo restore.
        let selections_after: Vec<CursorSelection> = self.selections.iter().copied().collect();
        if recorded {
            self.undo_manager.record_auto_closed_pairs(
                auto_closed_pairs_before,
                self.mode.auto_closed_pairs().clone(),
            );
            self.undo_manager
                .record_selections(selections_before, selections_after);
        }

        self.ime_marked_range.take();
        self.update_preferred_column();
        self.dismiss_touch_selection(cx);
        if self.is_multi_line() {
            self.mode.update_auto_grow(&self.display_map);
        }
        if self.emit_events {
            self.emit_change(cx);
        }
        cx.notify();
    }

    /// Update fold candidates from tree-sitter syntax tree (full extraction).
    /// Used only on initial load or language changes.
    fn update_fold_candidates(&mut self) {
        if !self.mode.is_folding() {
            return;
        }

        let Some(highlighter_rc) = self.mode.highlighter() else {
            return;
        };

        let highlighter = highlighter_rc.borrow();
        let Some(highlighter) = highlighter.as_ref() else {
            return;
        };

        let fold_ranges = highlighter.fold_ranges(&self.text);
        self.display_map.set_fold_candidates(fold_ranges);
    }

    /// Incrementally update fold candidates after a text edit.
    /// Only traverses the edited region of the syntax tree instead of the full tree.
    fn update_fold_candidates_incremental(&mut self, edit_range: &Range<usize>, new_text: &str) {
        if !self.mode.is_folding() {
            return;
        }

        let Some(highlighter_rc) = self.mode.highlighter() else {
            return;
        };

        let highlighter = highlighter_rc.borrow();
        let Some(highlighter) = highlighter.as_ref() else {
            return;
        };

        // The new byte range in the updated text after the edit
        let new_end = edit_range.start + new_text.len();
        self.display_map.update_fold_candidates_for_edit(
            |range, text| highlighter.fold_ranges_for_edit(range, text),
            edit_range.start..new_end,
            &self.text,
        );
    }
}

impl<M: InputModeKind> EntityInputHandler for InputBaseState<M> {
    fn text_for_range(
        &mut self,
        range_utf16: Range<usize>,
        adjusted_range: &mut Option<Range<usize>>,
        _window: &mut Window,
        _cx: &mut Context<Self>,
    ) -> Option<String> {
        let range = self.range_from_utf16(&range_utf16);
        adjusted_range.replace(self.range_to_utf16(&range));
        Some(self.text.slice(range).to_string())
    }

    fn selected_text_range(
        &mut self,
        _ignore_disabled_input: bool,
        _window: &mut Window,
        _cx: &mut Context<Self>,
    ) -> Option<UTF16Selection> {
        Some(UTF16Selection {
            range: self.range_to_utf16(&self.selected_range()),
            reversed: self.active_selection().reversed,
        })
    }

    /// Select the given range, as the platform's own text UI asks when it
    /// drives the selection: a native selection handle, or the macOS IME.
    ///
    /// The end that moved becomes the cursor, so dragging the start handle
    /// leaves a reversed selection and keeps the moving end in view. Text and
    /// undo history are left alone.
    fn set_selected_text_range(
        &mut self,
        range_utf16: Range<usize>,
        _window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        let previous = self.selected_range();
        let was_reversed = self.active_selection().reversed;
        let range = self.range_from_utf16(&range_utf16);
        let range = range.start.min(range.end)..range.start.max(range.end);
        self.set_selected_range(range, cx);

        let range = self.selected_range();
        let reversed = if range == previous {
            was_reversed
        } else if !range.is_empty() && range.end == previous.start {
            true
        } else if !range.is_empty() && range.start == previous.end {
            false
        } else {
            !range.is_empty() && range.start != previous.start && range.end == previous.end
        };
        self.active_selection_mut().reversed = reversed;
        self.scroll_to(self.cursor(), None, cx);
        cx.notify();
    }

    fn marked_text_range(
        &self,
        _window: &mut Window,
        _cx: &mut Context<Self>,
    ) -> Option<Range<usize>> {
        self.ime_marked_range
            .map(|range| self.range_to_utf16(&range.into()))
    }

    fn unmark_text(&mut self, _window: &mut Window, _cx: &mut Context<Self>) {
        self.ime_marked_range = None;
        self.undo_manager.commit_transaction();
    }

    /// Replace text in range.
    ///
    /// - If the new text is invalid, it will not be replaced.
    /// - If `range_utf16` is not provided, the current selected range will be used.
    fn replace_text_in_range(
        &mut self,
        range_utf16: Option<Range<usize>>,
        new_text: &str,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        let requested_intent = self.undo_manager.take_pending_intent();
        if !self.is_editable() {
            return;
        }
        let selection_before = *self.active_selection();
        // Committing a composition ends the transaction it opened, whether or
        // not the platform follows up with `unmark_text`.
        let ends_composition = self.ime_marked_range.is_some();

        self.pause_blink_cursor(cx);

        // NOTE: The normalization keeps the UTF-16 length, but may change the
        // UTF-8 byte length, so all the byte-offset calculations below must
        // use the normalized text.
        let new_text = if self.replaying_history {
            Cow::Borrowed(new_text)
        } else {
            self.normalize_input(new_text)
        };
        let new_text: &str = &new_text;

        let range = range_utf16
            .as_ref()
            .map(|range_utf16| self.range_from_utf16(range_utf16))
            .or(self.ime_marked_range.map(|range| {
                let range = self.range_to_utf16(&(range.start..range.end));
                self.range_from_utf16(&range)
            }))
            .unwrap_or(self.selected_range());
        let range = self.normalize_token_range(range);

        // Skip-over as a pure cursor move: a typed closer that already follows
        // the cursor moves past it without touching text or history, so Undo
        // never exposes a transient duplicate. Only for interactive single
        // keystrokes (current selection, no IME mark, not silent replays).
        // `take_pending_intent` above already consumed any request.
        if range.is_empty()
            && range.start == self.cursor()
            && self.ime_marked_range.is_none()
            && !self.silent_replace_text
            && self.is_code_editor()
            && self.selections.is_single()
            && self.active_selection().is_empty()
        {
            if let Some(target) = self.skip_over_target(new_text) {
                self.set_cursor_to(target);
                self.update_preferred_column();
                cx.notify();
                return;
            }
        }

        if self.is_multi_line() {
            let multi_cursor = range_utf16.is_none()
                && self.ime_marked_range.is_none()
                && !self.selections.is_single();
            if multi_cursor {
                self.selections.merge_overlapping();
                let mut edits: Vec<(Range<usize>, String)> = self
                    .selections
                    .iter()
                    .map(|sel| (sel.start..sel.end, new_text.to_string()))
                    .collect();
                edits.sort_by_key(|(range, _)| range.start);
                // One keystroke across several cursors is one batch, committed
                // with the intent of the keystroke so a run of them coalesces
                // into one undo just like single-cursor typing.
                let intent =
                    requested_intent.unwrap_or_else(|| self.typing_intent(&edits, new_text));
                self.undo_manager.begin_transaction_with(intent);
                self.undo_manager.set_pending_intent(intent);
                self.replace_text_in_ranges(&edits, window, cx);
                self.undo_manager.commit_transaction();
            } else {
                if range_utf16.is_some() {
                    self.selections.remove_all_but_active();
                }
                if let Some(intent) = requested_intent {
                    self.undo_manager.set_pending_intent(intent);
                }
                if let Some((open_len, closer)) = self.auto_close_target(&range, new_text) {
                    // One edit keeps the pair atomic even at undo coalescing limits.
                    let replacement = format!("{new_text}{closer}");
                    self.replace_text_in_ranges(&[(range.clone(), replacement)], window, cx);
                    let cursor = range.start + new_text.len();
                    self.mode.track_auto_closed_pair(
                        cursor - open_len..cursor,
                        cursor..cursor + closer.len(),
                    );
                    self.undo_manager
                        .record_auto_closed_pairs_after(self.mode.auto_closed_pairs().clone());
                    self.set_cursor_to(cursor);
                    self.update_preferred_column();
                    self.undo_manager.record_selections(
                        vec![selection_before],
                        self.selections.iter().copied().collect(),
                    );
                } else {
                    self.replace_text_in_ranges(
                        &[(range.clone(), new_text.to_string())],
                        window,
                        cx,
                    );
                }
            }
            if ends_composition {
                self.undo_manager.commit_transaction();
            }

            if !self.silent_replace_text {
                M::on_text_typed(self, &range, new_text, window, cx);
            }
            return;
        }

        // Single-line path
        let old_text = self.text.clone();
        // Token-aware history replay applies several replacements but emits one
        // `Change` at the end, so its edits accumulate instead of being
        // discarded with each silent replacement.
        let accumulate_replay_edits = self.replaying_history && !self.emit_events;
        if !accumulate_replay_edits {
            self.last_input_edits.clear();
        }
        self.mode.adjust_auto_closed_pair(&range, new_text.len());
        self.text.replace(range.clone(), new_text);

        let mut new_offset = (range.start + new_text.len()).min(self.text.len());

        // True if the mask has changed the text, e.g. regrouping the
        // separators or completing a leading dot.
        let mut mask_changed = false;

        if self.is_single_line() {
            let pending_text = self.text.to_string();
            // Check if the new text is valid.
            //
            // Only reject the edit if the old text was valid, to avoid
            // trapping a pre-existing invalid text (e.g. a `default_value`
            // that does not conform), the user can still edit to fix it.
            if !self.replaying_history
                && !self.validated_token_edit
                && !self.is_valid_input(&pending_text, cx)
                && self.is_valid_input(&old_text.to_string(), cx)
            {
                self.text = old_text;
                return;
            }

            if !self.replaying_history && !self.mask_pattern.is_none() {
                let mask_text = self.mask_pattern.mask(&pending_text);
                mask_changed = mask_text.as_str() != pending_text;
                self.text = Rope::from(mask_text.as_str());
                let new_text_len =
                    (new_text.len() + mask_text.len()).saturating_sub(pending_text.len());
                new_offset = (range.start + new_text_len).min(mask_text.len());
            }
        }

        if mask_changed {
            // Masking rewrites the whole document, so ranges recorded against
            // the old text no longer point at anything.
            M::reset_annotations(self);
        } else {
            M::adjust_annotations(self, &range, new_text.len());
        }
        if mask_changed {
            // A segment-based history entry no longer matches the masked
            // document, record a whole-document change instead, so that
            // undo/redo can restore the text exactly.
            self.push_history(
                &old_text,
                &(0..old_text.len()),
                &self.text.to_string(),
                Some(EditIntent::Atomic),
                selection_before,
                Some((new_offset..new_offset).into()),
            );
        } else {
            self.push_history(
                &old_text,
                &range,
                &new_text,
                requested_intent,
                selection_before,
                None,
            );
        }
        if let Some(diagnostics) = self.mode.diagnostics_mut() {
            diagnostics.reset(&self.text)
        }
        // Adjust folds before updating wrap map: remove overlapping folds and shift others
        self.display_map
            .adjust_folds_for_edit(&old_text, &range, new_text);
        self.display_map
            .on_text_changed(&self.text, &range, &Rope::from(new_text), cx);

        let edit = if mask_changed {
            Self::full_input_edit(&old_text, &self.text)
        } else {
            super::mode::replacement_input_edit(&old_text, &self.text, &range, new_text)
        };
        if self.emit_events || self.replaying_history {
            self.last_input_edits.push((edit, self.text.clone()));
        }

        self.mode.update_highlighter::<M>(
            super::mode::HighlighterUpdate {
                selected_range: &range,
                old_text: &old_text,
                new_text: &self.text,
                change_text: &new_text,
                force: true,
                input_edit: Some(edit),
            },
            window,
            cx,
        );

        self.update_fold_candidates_incremental(&range, new_text);
        M::refresh_language_features(self, window, cx);
        self.set_cursor_to(new_offset);
        self.ime_marked_range.take();
        // A commit ends the IME composition: macOS delivers `insertText:` for
        // the confirmed candidate without a following `unmarkText`, so close
        // the transaction here. Leaving it open would keep merging every later
        // edit into the same change, which then carries the text and selection
        // of the first composition.
        if ends_composition {
            self.undo_manager
                .record_selections(vec![selection_before], vec![*self.active_selection()]);
            self.undo_manager.commit_transaction();
        }
        self.update_preferred_column();
        self.update_search(cx);
        self.dismiss_touch_selection(cx);
        if self.is_multi_line() {
            self.mode.update_auto_grow(&self.display_map);
        }
        if !self.silent_replace_text {
            M::on_text_typed(self, &range, &new_text, window, cx);
        }
        if self.emit_events {
            self.emit_change(cx);
        }
        cx.notify();
    }

    /// Mark text is the IME temporary insert on typing.
    fn replace_and_mark_text_in_range(
        &mut self,
        range_utf16: Option<Range<usize>>,
        new_text: &str,
        new_selected_range_utf16: Option<Range<usize>>,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        let requested_intent = self.undo_manager.take_pending_intent();
        if !self.is_editable() {
            return;
        }
        let selection_before = *self.active_selection();

        let starts_composition = self.ime_marked_range.is_none();
        if starts_composition {
            // Even a canceled preedit separates the typing gestures on either
            // side; its no-op transaction must not reconnect those gestures.
            self.undo_manager.break_transaction_coalescing();
            self.undo_manager.begin_transaction();
        }

        // Collapse any extra cursors so we never leave stale secondary cursors behind.
        self.selections.remove_all_but_active();

        M::reset_language_features(self);

        // See the same NOTE in `replace_text_in_range`.
        let new_text = if self.replaying_history {
            Cow::Borrowed(new_text)
        } else {
            self.normalize_input(new_text)
        };
        let new_text: &str = &new_text;

        let range = range_utf16
            .as_ref()
            .map(|range_utf16| self.range_from_utf16(range_utf16))
            .or(self.ime_marked_range.map(|range| {
                let range = self.range_to_utf16(&(range.start..range.end));
                self.range_from_utf16(&range)
            }))
            .unwrap_or(self.selected_range());
        let range = self.normalize_token_range(range);

        let auto_closed_pairs_before = self.mode.auto_closed_pairs().clone();
        let old_text = self.text.clone();
        // Marked text does not emit `InputEvent::Change`, so no edit belongs to
        // the most recent change after it.
        self.last_input_edits.clear();
        self.mode.adjust_auto_closed_pair(&range, new_text.len());
        self.text.replace(range.clone(), new_text);

        if self.is_single_line() {
            let pending_text = self.text.to_string();
            // See the same NOTE in `replace_text_in_range`.
            if !self.replaying_history
                && !self.validated_token_edit
                && !self.is_valid_input(&pending_text, cx)
                && self.is_valid_input(&old_text.to_string(), cx)
            {
                self.text = old_text;
                if starts_composition {
                    self.undo_manager.commit_transaction();
                }
                return;
            }
        }

        if self.ime_original_text.is_none() {
            self.ime_original_text = Some(old_text.clone());
        }
        M::adjust_annotations(self, &range, new_text.len());
        if let Some(diagnostics) = self.mode.diagnostics_mut() {
            diagnostics.reset(&self.text)
        }
        // Adjust folds before updating wrap map: remove overlapping folds and shift others
        self.display_map
            .adjust_folds_for_edit(&old_text, &range, new_text);
        self.display_map
            .on_text_changed(&self.text, &range, &Rope::from(new_text), cx);

        self.mode.update_highlighter::<M>(
            super::mode::HighlighterUpdate {
                selected_range: &range,
                old_text: &old_text,
                new_text: &self.text,
                change_text: &new_text,
                force: true,
                input_edit: None,
            },
            window,
            cx,
        );

        self.update_fold_candidates_incremental(&range, new_text);
        M::refresh_language_features(self, window, cx);
        if new_text.is_empty() {
            // Cancel selection, when cancel IME input.
            self.set_cursor_to(range.start);
            self.ime_marked_range = None;
        } else {
            self.ime_marked_range = Some((range.start..range.start + new_text.len()).into());
            let new_range = new_selected_range_utf16
                .as_ref()
                .map(|range_utf16| {
                    let new_text = Rope::from(new_text);
                    range.start + new_text.offset_utf16_to_offset(range_utf16.start)
                        ..range.start + new_text.offset_utf16_to_offset(range_utf16.end)
                })
                .unwrap_or_else(|| range.start + new_text.len()..range.start + new_text.len());
            self.set_selection(new_range.start, new_range.end);
        }
        if self.is_multi_line() {
            self.mode.update_auto_grow(&self.display_map);
        }
        if self.push_history(
            &old_text,
            &range,
            new_text,
            requested_intent,
            selection_before,
            Some(*self.active_selection()),
        ) {
            self.undo_manager
                .record_selections(vec![selection_before], vec![*self.active_selection()]);
            self.undo_manager.record_auto_closed_pairs(
                auto_closed_pairs_before,
                self.mode.auto_closed_pairs().clone(),
            );
        }
        if new_text.is_empty() {
            self.undo_manager.commit_transaction();
        }
        cx.notify();
    }

    /// Used to position IME candidates.
    fn bounds_for_range(
        &mut self,
        range_utf16: Range<usize>,
        bounds: Bounds<Pixels>,
        _window: &mut Window,
        _cx: &mut Context<Self>,
    ) -> Option<Bounds<Pixels>> {
        let last_layout = self.last_layout.as_ref()?;
        let line_height = last_layout.line_height;
        let line_number_width = last_layout.line_number_width;
        let range = self.range_from_utf16(&range_utf16);

        let mut start_origin = None;
        let mut end_origin = None;
        let line_number_origin = point(line_number_width, px(0.));
        let mut y_offset = last_layout.visible_top;

        for (vi, line) in last_layout.lines.iter().enumerate() {
            if start_origin.is_some() && end_origin.is_some() {
                break;
            }

            let index_offset = last_layout.visible_line_byte_offsets[vi];

            if start_origin.is_none() {
                if let Some(p) = line.position_for_index(
                    range.start.saturating_sub(index_offset),
                    last_layout,
                    false,
                ) {
                    start_origin = Some(p + point(px(0.), y_offset));
                }
            }

            if end_origin.is_none() {
                if let Some(p) = line.position_for_index(
                    range.end.saturating_sub(index_offset),
                    last_layout,
                    false,
                ) {
                    end_origin = Some(p + point(px(0.), y_offset));
                }
            }

            y_offset += line.size(line_height).height;
        }

        let start_origin = start_origin.or_else(|| {
            let offset = self.last_cursor.or(Some(self.cursor()))?;
            let (_, _, origin) = self.line_and_position_for_offset(offset);
            origin.map(|origin| origin - line_number_origin)
        })?;
        let mut end_origin = end_origin.unwrap_or(start_origin);
        // Ensure at same line.
        end_origin.y = start_origin.y;

        Some(Bounds::from_corners(
            bounds.origin + line_number_origin + start_origin,
            // + line_height for show IME panel under the cursor line.
            bounds.origin + line_number_origin + point(end_origin.x, end_origin.y + line_height),
        ))
    }

    fn character_index_for_point(
        &mut self,
        point: gpui::Point<Pixels>,
        _window: &mut Window,
        _cx: &mut Context<Self>,
    ) -> Option<usize> {
        let last_layout = self.last_layout.as_ref()?;
        let line_point = self.last_bounds?.localize(&point)?;

        for (vi, line) in last_layout.lines.iter().enumerate() {
            let offset = last_layout.visible_line_byte_offsets[vi];
            if let Some(utf8_index) = line.index_for_position(line_point, last_layout) {
                return Some(self.offset_to_utf16(offset + utf8_index));
            }
        }

        None
    }

    fn text_input_configuration(
        &mut self,
        _window: &mut Window,
        _cx: &mut Context<Self>,
    ) -> TextInputConfiguration {
        InputBaseState::text_input_configuration(self)
    }
}

impl<M: InputModeKind> Focusable for InputBaseState<M> {
    fn focus_handle(&self, _cx: &App) -> FocusHandle {
        self.focus_handle.clone()
    }
}

impl<M: InputModeKind> Render for InputBaseState<M> {
    fn render(&mut self, window: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        // Before anything reads it: the element resolves this style during
        // layout and paint, and both happen after this call in the same frame.
        self.editor_style = self
            .projected_editor_style
            .resolved(&crate::Theme::global(cx).tokens);
        let entity = cx.entity();
        if self._pending_update {
            self.mode.update_highlighter::<M>(
                super::mode::HighlighterUpdate {
                    selected_range: &(0..0),
                    old_text: &self.text,
                    new_text: &self.text,
                    change_text: "",
                    force: false,
                    input_edit: None,
                },
                window,
                cx,
            );

            self.update_fold_candidates();
            M::refresh_language_features(self, window, cx);
            self._pending_update = false;
        }

        let element = div()
            .id(EDITOR_ELEMENT_ID)
            .key_context(CONTEXT)
            .when_some(self.accessibility.as_ref(), |this, accessibility| {
                this.when_some(accessibility.role, |this, role| this.role(role))
                    .when_some(accessibility.label.clone(), |this, label| {
                        this.aria_label(label)
                    })
                    .when_some(accessibility.placeholder.clone(), |this, placeholder| {
                        this.aria_placeholder(placeholder)
                    })
                    .when_some(accessibility.accessibility_id.clone(), |this, id| {
                        this.accessibility_id(id)
                    })
                    .when(
                        accessibility.value_exposed
                            && !self.masked
                            && (window.is_a11y_active() || cfg!(feature = "test-support")),
                        |this| this.aria_value(self.text.to_string()),
                    )
                    .on_a11y_action(gpui::AccessibleAction::Focus, {
                        let entity = entity.clone();
                        move |_, window, cx| {
                            entity.update(cx, |state, cx| {
                                state.handle_accessibility_focus(window, cx)
                            });
                        }
                    })
                    .when(self.is_editable(), |this| {
                        this.on_a11y_action(gpui::AccessibleAction::SetValue, {
                            let entity = entity.clone();
                            move |data, window, cx| {
                                entity.update(cx, |state, cx| {
                                    state.handle_accessibility_set_value(data, window, cx)
                                });
                            }
                        })
                    })
            })
            .when(self.is_editable(), |this| {
                this.on_action(window.listener_for(&entity, InputBaseState::backspace))
                    .on_action(window.listener_for(&entity, InputBaseState::delete))
                    .on_action(
                        window.listener_for(&entity, InputBaseState::delete_to_beginning_of_line),
                    )
                    .on_action(window.listener_for(&entity, InputBaseState::delete_to_end_of_line))
                    .on_action(window.listener_for(&entity, InputBaseState::delete_previous_word))
                    .on_action(window.listener_for(&entity, InputBaseState::delete_next_word))
                    .on_action(window.listener_for(&entity, InputBaseState::enter))
                    .on_action(window.listener_for(&entity, InputBaseState::escape))
                    .on_action(window.listener_for(&entity, InputBaseState::paste))
                    .on_action(window.listener_for(&entity, InputBaseState::cut))
                    .on_action(window.listener_for(&entity, InputBaseState::undo))
                    .on_action(window.listener_for(&entity, InputBaseState::redo))
                    .when(self.is_multi_line(), |this| {
                        this.on_action(window.listener_for(&entity, InputBaseState::indent_inline))
                            .on_action(window.listener_for(&entity, InputBaseState::outdent_inline))
                            .on_action(window.listener_for(&entity, InputBaseState::indent_block))
                            .on_action(window.listener_for(&entity, InputBaseState::outdent_block))
                    })
            })
            .on_action(window.listener_for(&entity, InputBaseState::left))
            .on_action(window.listener_for(&entity, InputBaseState::right))
            .on_action(window.listener_for(&entity, InputBaseState::select_left))
            .on_action(window.listener_for(&entity, InputBaseState::select_right))
            .when(self.is_multi_line(), |this| {
                this.on_action(window.listener_for(&entity, InputBaseState::up))
                    .on_action(window.listener_for(&entity, InputBaseState::down))
                    .on_action(window.listener_for(&entity, InputBaseState::select_up))
                    .on_action(window.listener_for(&entity, InputBaseState::select_down))
                    .on_action(window.listener_for(&entity, InputBaseState::page_up))
                    .on_action(window.listener_for(&entity, InputBaseState::page_down))
                    .on_action(window.listener_for(&entity, InputBaseState::add_cursor_above))
                    .on_action(window.listener_for(&entity, InputBaseState::add_cursor_below))
            })
            .on_action(window.listener_for(&entity, InputBaseState::on_action_select_all))
            .on_action(window.listener_for(&entity, InputBaseState::select_to_start_of_line))
            .on_action(window.listener_for(&entity, InputBaseState::select_to_end_of_line))
            .on_action(window.listener_for(&entity, InputBaseState::select_to_previous_word))
            .on_action(window.listener_for(&entity, InputBaseState::select_to_next_word))
            .on_action(window.listener_for(&entity, InputBaseState::home))
            .on_action(window.listener_for(&entity, InputBaseState::end))
            .on_action(window.listener_for(&entity, InputBaseState::move_to_start))
            .on_action(window.listener_for(&entity, InputBaseState::move_to_end))
            .on_action(window.listener_for(&entity, InputBaseState::move_to_previous_word))
            .on_action(window.listener_for(&entity, InputBaseState::move_to_next_word))
            .on_action(window.listener_for(&entity, InputBaseState::select_to_start))
            .on_action(window.listener_for(&entity, InputBaseState::select_to_end))
            .on_action(window.listener_for(&entity, InputBaseState::show_character_palette))
            .on_action({
                let entity = entity.clone();
                move |_: &ActivateToken, window, cx| {
                    let state = entity.read(cx);
                    let activation = state
                        .token_spans()
                        .iter()
                        .find(|span| span.range() == state.selected_range())
                        .and_then(|span| {
                            state.range_to_bounds(&span.range()).and_then(|bounds| {
                                state.token_activation(
                                    span.range().start,
                                    bounds,
                                    gpui::ClickEvent::Keyboard(gpui::KeyboardClickEvent {
                                        bounds,
                                        ..Default::default()
                                    }),
                                )
                            })
                        });
                    if let Some((listener, event)) = activation {
                        listener(&event, window, cx);
                    }
                }
            })
            .on_action(window.listener_for(&entity, InputBaseState::copy))
            .on_action(window.listener_for(&entity, InputBaseState::on_action_search))
            .on_action(window.listener_for(&entity, InputBaseState::on_action_replace))
            .on_mouse_down(
                MouseButton::Left,
                window.listener_for(&entity, InputBaseState::on_mouse_down),
            )
            .on_mouse_down(
                MouseButton::Right,
                window.listener_for(&entity, InputBaseState::on_mouse_down),
            )
            .on_mouse_up(
                MouseButton::Left,
                window.listener_for(&entity, InputBaseState::on_mouse_up),
            )
            .on_mouse_up(
                MouseButton::Right,
                window.listener_for(&entity, InputBaseState::on_mouse_up),
            )
            .on_mouse_move(window.listener_for(&entity, InputBaseState::on_mouse_move))
            .on_scroll(window.listener_for(&entity, InputBaseState::on_scroll_wheel))
            .when(self.is_multi_line() && !self.disabled, |this| {
                this.on_modifiers_changed(cx.listener(|_, _, _, cx| cx.notify()))
            })
            .when(!self.disabled, |this| {
                if self.is_multi_line() && window.modifiers().alt {
                    this.cursor_crosshair()
                } else {
                    this.cursor_text()
                }
            })
            .flex_1()
            // A single line fills the frame and sits at its vertical center,
            // so the frame needs no layout of its own to hold it. It is never
            // shorter than its line, though: this root clips (overflow-x
            // hidden clips both axes), and a frame whose padding leaves less
            // than a line, like Component's Input, would cut off descenders.
            .map(|this| {
                if self.is_multi_line() {
                    this.h_full()
                } else {
                    this.min_h_full().flex().items_center()
                }
            })
            .flex_grow_1()
            .overflow_x_hidden()
            .when(self.is_multi_line(), |this| {
                this.pt(self.editor_paddings.top)
                    .pr(self.editor_paddings.right)
                    .pb(self.editor_paddings.bottom)
                    .pl(self.editor_paddings.left)
            })
            .child(TextElement::new(entity.clone()).placeholder(self.placeholder.clone()))
            .when(self.shows_scrollbar(), |this| {
                this.child(EditorScrollbar::new(entity.clone()))
            });

        // Actions only one mode handles are registered by that mode, where
        // `Self` is concrete enough to name its own entity type.
        M::register_actions(element, &entity, window)
            .test_support()
            .track_focus(&self.focus_handle)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[gpui::test]
    fn accessibility_actions_recheck_live_editability(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let (state, cx) = cx.add_window_view(|window, cx| {
            crate::input::InputState::new(window, cx).default_value("initial")
        });
        let changes = Rc::new(Cell::new(0));
        let observed = changes.clone();
        let _subscription = cx.update(|_, cx| {
            cx.subscribe(&state, move |_, event: &InputEvent, _| {
                if matches!(event, InputEvent::Change) {
                    observed.set(observed.get() + 1);
                }
            })
        });
        cx.update(|window, cx| {
            state.update(cx, |state, cx| {
                state.handle_accessibility_set_value(None, window, cx);
                state.handle_accessibility_focus(window, cx);
                assert!(state.focus_handle.is_focused(window));
            });
            window.draw(cx).clear(cx);
        });
        assert_eq!(state.read_with(cx, |state, _| state.value()), "initial");
        assert_eq!(changes.get(), 0);

        let action = gpui::accesskit::ActionData::Value("updated🦀".into());
        cx.update(|window, cx| {
            state.update(cx, |state, cx| {
                state.handle_accessibility_set_value(Some(&action), window, cx)
            });
        });
        assert_eq!(state.read_with(cx, |state, _| state.value()), "updated🦀");
        assert_eq!(changes.get(), 1);
        for disabled in [false, true] {
            cx.update(|window, cx| {
                window.blur(cx);
                state.update(cx, |state, cx| {
                    state.set_disabled(disabled, cx);
                    state.set_readonly(!disabled, cx);
                    state.handle_accessibility_focus(window, cx);
                    assert_eq!(state.focus_handle.is_focused(window), !disabled);
                    let rejected = gpui::accesskit::ActionData::Value("rejected".into());
                    state.handle_accessibility_set_value(Some(&rejected), window, cx);
                });
            });
            assert_eq!(state.read_with(cx, |state, _| state.value()), "updated🦀");
            assert_eq!(changes.get(), 1);
        }
        cx.update(|window, cx| {
            state.update(cx, |state, cx| {
                state.set_disabled(false, cx);
                state.set_readonly(false, cx);
                state.handle_accessibility_focus(window, cx);
            });
            window.draw(cx).clear(cx);
            window.dispatch_action(Box::new(Undo), cx);
        });
        assert_eq!(state.read_with(cx, |state, _| state.value()), "initial");
        cx.update(|window, cx| {
            state.update(cx, |state, cx| {
                state.set_masked(true, window, cx);
                state.handle_accessibility_set_value(Some(&action), window, cx);
            });
        });
        assert_eq!(state.read_with(cx, |state, _| state.value()), "updated🦀");
    }

    #[gpui::test]
    fn accessibility_set_value_preserves_exact_editor_text(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let (editor, cx) = cx.add_window_view(|window, cx| {
            crate::input::EditorState::new(window, cx).language("rust")
        });
        let action = gpui::accesskit::ActionData::Value("(".into());
        cx.update(|window, cx| {
            editor.update(cx, |editor, cx| {
                editor.handle_accessibility_set_value(Some(&action), window, cx)
            });
        });
        assert_eq!(editor.read_with(cx, |editor, _| editor.value()), "(");
    }

    #[gpui::test]
    fn revealing_a_password_keeps_text_assistance_disabled(cx: &mut TestAppContext) {
        cx.update(crate::init);
        cx.open_window(size(px(400.), px(100.)), |window, cx| {
            let state = cx.new(|cx| crate::input::InputState::new(window, cx).masked(true));
            let hidden = state.read(cx).text_input_configuration();
            assert!(!hidden.autocorrect && !hidden.suggestions);
            assert_eq!(hidden.autocapitalize, Autocapitalize::None);

            // The component's reveal button uses this same state transition.
            state.update(cx, |state, cx| state.toggle_masked(window, cx));
            assert_eq!(state.read(cx).text_input_configuration(), hidden);
            state.update(cx, |state, cx| state.toggle_masked(window, cx));
            assert_eq!(state.read(cx).text_input_configuration(), hidden);
            gpui::EmptyView
        });
    }

    #[gpui::test]
    fn text_input_configuration_follows_the_input(cx: &mut TestAppContext) {
        use crate::input::{InputState, TextareaState};

        cx.update(crate::init);
        let mut states = None;
        cx.open_window(size(px(400.), px(100.)), |window, cx| {
            states = Some((
                cx.new(|cx| InputState::new(window, cx)),
                cx.new(|cx| InputState::new(window, cx).masked(true)),
                cx.new(|cx| TextareaState::new(window, cx)),
                cx.new(|cx| {
                    InputState::new(window, cx)
                        .input_action(TextInputAction::Search)
                        .autocorrect(true)
                        .autocapitalize(Autocapitalize::Words)
                }),
            ));
            gpui::EmptyView
        });
        let (plain, masked, textarea, search) = states.unwrap();

        cx.read(|cx| {
            assert_eq!(
                plain.read(cx).text_input_configuration(),
                TextInputConfiguration {
                    input_action: TextInputAction::Done,
                    ..Default::default()
                }
            );
            assert_eq!(
                masked.read(cx).text_input_configuration(),
                TextInputConfiguration {
                    input_action: TextInputAction::Done,
                    ..Default::default()
                }
            );
            assert_eq!(
                textarea.read(cx).text_input_configuration(),
                TextInputConfiguration {
                    input_action: TextInputAction::Enter,
                    ..Default::default()
                }
            );
            let search = search.read(cx).text_input_configuration();
            assert_eq!(search.input_action, TextInputAction::Search);
            assert_eq!(search.autocapitalize, Autocapitalize::Words);
            assert!(search.autocorrect);
            assert!(search.suggestions);
        });
    }

    #[gpui::test]
    fn test_multicursor_unicode_completion_uses_post_edit_start(cx: &mut TestAppContext) {
        use crate::input::{CompletionProvider, EditorState};
        use gpui::Task;
        use lsp_types::{CompletionContext, CompletionResponse};
        use std::cell::RefCell;

        #[derive(Default)]
        struct Provider {
            starts: RefCell<Vec<usize>>,
            queries: RefCell<Vec<(usize, String)>>,
        }

        impl CompletionProvider for Provider {
            fn is_completion_trigger(&self, offset: usize, _: &str, _: &mut App) -> bool {
                self.starts.borrow_mut().push(offset);
                true
            }

            fn completions(
                &self,
                _: &Rope,
                offset: usize,
                trigger: CompletionContext,
                _: &mut Window,
                _: &mut App,
            ) -> Task<anyhow::Result<CompletionResponse>> {
                self.queries
                    .borrow_mut()
                    .push((offset, trigger.trigger_character.unwrap()));
                Task::ready(Ok(CompletionResponse::Array(vec![])))
            }
        }

        cx.update(crate::init);
        let mut editor = None;
        let window = cx.open_window(size(px(400.), px(100.)), |window, cx| {
            editor = Some(cx.new(|cx| EditorState::new(window, cx).default_value("aa")));
            gpui::EmptyView
        });
        let editor = editor.unwrap();
        let provider = Rc::new(Provider::default());
        window
            .update(cx, |_, window, cx| {
                editor.update(cx, |state, cx| {
                    state.extras.lsp.completion_provider = Some(provider.clone());
                    state
                        .extras
                        .context_menu_content
                        .completion
                        .trigger_start_offset = Some(0);
                    state.extras.context_menu_content.completion.query = "aa".into();
                    state.set_cursor_to(1);
                    state.add_cursor_at(0, cx);

                    state.replace_text_in_range(None, "中", window, cx);

                    assert_eq!(state.value(), "中a中a");
                    assert_eq!(provider.starts.borrow().as_slice(), &[4]);
                    assert_eq!(provider.queries.borrow().as_slice(), &[(7, "中".into())]);
                });
            })
            .unwrap();
    }

    #[gpui::test]
    fn selected_range_restores_unicode_direction_without_splitting_characters(
        cx: &mut TestAppContext,
    ) {
        use crate::input::EditorState;
        cx.update(crate::init);
        cx.open_window(size(px(400.), px(100.)), |window, cx| {
            let _state = cx.new(|cx| {
                let mut state = EditorState::new(window, cx).default_value("中😀a");
                state.set_selected_range_with_direction(3..8, true, cx);
                let selected = state.selected_text_range(false, window, cx).unwrap();
                assert_eq!(selected.range, 1..4);
                assert!(selected.reversed);
                assert_eq!(state.selected_range(), 3..8);
                assert!(state.is_selection_reversed());
                let range = state.selected_range();
                let reversed = state.is_selection_reversed();
                state.set_selected_range_with_direction(range, reversed, cx);
                assert!(state.is_selection_reversed());
                state.set_selected_range(3..8, cx);
                let selected = state.selected_text_range(false, window, cx).unwrap();
                assert_eq!(selected.range, 1..4);
                assert!(!selected.reversed);
                assert!(!state.is_selection_reversed());
                // A reversed Rust Range remains empty for existing callers.
                state.set_selected_range(Range { start: 8, end: 3 }, cx);
                assert_eq!(state.selected_range(), 8..8);
                assert!(!state.is_selection_reversed());
                state.set_selected_range_with_direction(4..4, true, cx);
                assert!(!state.is_selection_reversed());
                assert_eq!(
                    state.selected_text_range(false, window, cx).unwrap().range,
                    1..1
                );
                state
            });
            gpui::EmptyView
        });
    }

    #[gpui::test]
    fn test_inline_token_wrap_and_size_refresh(cx: &mut TestAppContext) {
        use crate::input::{InlineToken, InlineTokenPresentation};
        let width = Rc::new(Cell::new(4000.));
        let render_width = width.clone();
        let view = InputView::build_textarea(cx, |state| state.rows(4).default_value("@a@b"));
        view.window_handle
            .update(cx, |_, window, cx| {
                view.input.update(cx, |state, cx| {
                    state
                        .replace_range_with_token(0..2, InlineToken::new("a", "@a"), window, cx)
                        .unwrap();
                    state
                        .replace_range_with_token(2..4, InlineToken::new("b", "@b"), window, cx)
                        .unwrap();
                    state.set_token_presentation(
                        InlineTokenPresentation::default()
                            .token(move |_, _, _| div().w(px(render_width.get()))),
                    );
                });
            })
            .unwrap();
        let mut visual = VisualTestContext::from_window(view.window_handle.into(), cx);
        visual.update(|window, cx| window.draw(cx).clear(cx));
        view.input.read_with(&visual, |state, _| {
            assert_eq!(state.display_map.wrap_row_count(), 2);
            let first = state.range_to_bounds(&(0..2)).unwrap();
            let second = state.range_to_bounds(&(2..4)).unwrap();
            assert!(second.origin.y > first.origin.y);
            assert_eq!(
                state.last_layout.as_ref().unwrap().lines[0].wrapped_lines[0].len,
                2
            );
        });
        width.set(100.);
        view.input.update(&mut visual, |_, cx| cx.notify());
        visual.update(|window, cx| window.draw(cx).clear(cx));
        view.input.read_with(&visual, |state, _| {
            assert_eq!(state.display_map.wrap_row_count(), 1)
        });
    }

    #[gpui::test]
    fn test_inline_token_geometry_and_reentrant_activation(cx: &mut TestAppContext) {
        use crate::input::{InlineToken, InlineTokenPresentation};
        let view = InputView::build(cx, |state| state.default_value("before @alice after"));
        let target = view.input.clone();
        view.window_handle
            .update(cx, |_, window, cx| {
                view.input.update(cx, |state, cx| {
                    state
                        .replace_range_with_token(
                            7..13,
                            InlineToken::new("a", "@alice"),
                            window,
                            cx,
                        )
                        .unwrap();
                    state.set_token_presentation(
                        InlineTokenPresentation::default()
                            .token(|_, _, _| div().w(px(100.)).h(px(20.)))
                            .on_token_click(move |_, window, cx| {
                                target.update(cx, |state, cx| {
                                    state.set_value("activated", window, cx)
                                })
                            }),
                    );
                    state.focus(window, cx);
                    state.set_selected_range(7..13, cx);
                });
            })
            .unwrap();
        let mut visual = VisualTestContext::from_window(view.window_handle.into(), cx);
        visual.update(|window, cx| window.draw(cx).clear(cx));
        visual.update(|window, cx| {
            let state = view.input.read(cx);
            let bounds = state.range_to_bounds(&(7..13)).unwrap();
            assert!((bounds.size.width - px(100.)).abs() < px(1.), "{bounds:?}");
            let (left, _) = state.index_for_mouse_position(bounds.origin + point(px(10.), px(5.)));
            let (right, _) = state.index_for_mouse_position(bounds.origin + point(px(90.), px(5.)));
            assert_eq!((left, right), (7, 13));
            window.dispatch_action(Box::new(ActivateToken), cx);
        });
        visual.run_until_parked();
        view.input.read_with(&visual, |state, _| {
            assert_eq!(state.value().as_ref(), "activated")
        });
    }

    #[gpui::test]
    fn test_inline_token_click_selects_it(cx: &mut TestAppContext) {
        use crate::input::InlineToken;
        cx.update(crate::init);
        let view = InputView::build(cx, |state| state.default_value("before @alice after"));
        view.window_handle
            .update(cx, |_, window, cx| {
                view.input.update(cx, |state, cx| {
                    state
                        .replace_range_with_token(
                            7..13,
                            InlineToken::new("a", "@alice"),
                            window,
                            cx,
                        )
                        .unwrap();
                    state.set_selected_range(0..0, cx);
                });
            })
            .unwrap();
        let mut visual = VisualTestContext::from_window(view.window_handle.into(), cx);
        visual.update(|window, cx| window.draw(cx).clear(cx));
        let bounds = view
            .input
            .read_with(&visual, |state, _| state.range_to_bounds(&(7..13)).unwrap());
        visual.simulate_click(bounds.center(), gpui::Modifiers::default());
        visual.run_until_parked();
        view.input.read_with(&visual, |state, _| {
            assert_eq!(state.selected_range(), 7..13, "a click selects the token");
        });
    }

    #[gpui::test]
    fn test_inline_token_hover_reports_presence_without_selecting(cx: &mut TestAppContext) {
        use crate::input::{InlineToken, InlineTokenPresentation};
        use gpui::{Bounds, point, px, size};
        cx.update(crate::init);
        let view = InputView::build(cx, |state| state.default_value("before @alice after"));
        let bounds = Bounds::new(point(px(10.), px(20.)), size(px(100.), px(20.)));
        view.window_handle
            .update(cx, |_, window, cx| {
                view.input.update(cx, |state, cx| {
                    state
                        .replace_range_with_token(
                            7..13,
                            InlineToken::new("a", "@alice"),
                            window,
                            cx,
                        )
                        .unwrap();
                    state.set_token_presentation(
                        InlineTokenPresentation::default().on_token_hover(|_, _, _| {}),
                    );
                    state.set_selected_range(0..0, cx);
                });
            })
            .unwrap();
        view.window_handle
            .update(cx, |_, _, cx| {
                view.input.update(cx, |state, _| {
                    let (_, entered) = state
                        .token_hover(7, bounds, true, None)
                        .expect("hover enters an enabled token");
                    assert!(entered.is_hovered());
                    assert_eq!(entered.token().id().as_ref(), "a");
                    assert_eq!(entered.range(), 7..13);
                    assert_eq!(entered.bounds(), bounds);
                    let (_, left) = state
                        .token_hover(7, bounds, false, None)
                        .expect("hover leaves the same token");
                    assert!(!left.is_hovered());
                    assert_eq!(state.selected_range(), 0..0, "hover never selects");
                    assert!(state.token_hover(99, bounds, true, None).is_none());
                });
            })
            .unwrap();

        // Disabled tokens suppress hover, matching click; readonly allows it.
        view.window_handle
            .update(cx, |_, _, cx| {
                view.input.update(cx, |state, cx| {
                    state.set_disabled(true, cx);
                });
            })
            .unwrap();
        view.window_handle
            .update(cx, |_, _, cx| {
                view.input.update(cx, |state, _| {
                    assert!(state.token_hover(7, bounds, true, None).is_none())
                })
            })
            .unwrap();
        view.window_handle
            .update(cx, |_, _, cx| {
                view.input.update(cx, |state, cx| {
                    state.set_disabled(false, cx);
                    state.set_readonly(true, cx);
                });
            })
            .unwrap();
        view.window_handle
            .update(cx, |_, _, cx| {
                view.input.update(cx, |state, _| {
                    assert!(state.token_hover(7, bounds, true, None).is_some())
                })
            })
            .unwrap();

        // Without a hover listener there is no hover activation.
        view.window_handle
            .update(cx, |_, _, cx| {
                view.input.update(cx, |state, _| {
                    state.set_token_presentation(InlineTokenPresentation::default());
                });
            })
            .unwrap();
        view.window_handle
            .update(cx, |_, _, cx| {
                view.input.update(cx, |state, _| {
                    assert!(state.token_hover(7, bounds, true, None).is_none())
                })
            })
            .unwrap();
    }

    #[gpui::test]
    fn test_inline_token_hover_exit_delivered_when_token_removed(cx: &mut TestAppContext) {
        use crate::input::{InlineToken, InlineTokenPresentation};
        use std::cell::RefCell;
        use std::rc::Rc;
        cx.update(crate::init);
        let view = InputView::build(cx, |state| state.default_value("before @alice after"));
        let events: Rc<RefCell<Vec<(SharedString, bool)>>> = Rc::new(RefCell::new(Vec::new()));
        let sink = events.clone();
        view.window_handle
            .update(cx, |_, window, cx| {
                view.input.update(cx, |state, cx| {
                    state
                        .replace_range_with_token(
                            7..13,
                            InlineToken::new("a", "@alice"),
                            window,
                            cx,
                        )
                        .unwrap();
                    state.set_token_presentation(
                        InlineTokenPresentation::default()
                            .token(|_, _, _| div().w(px(100.)).h(px(20.)))
                            .on_token_hover(move |event, _, _| {
                                sink.borrow_mut()
                                    .push((event.token().id().clone(), event.is_hovered()));
                            }),
                    );
                });
            })
            .unwrap();
        let mut visual = VisualTestContext::from_window(view.window_handle.into(), cx);
        visual.update(|window, cx| window.draw(cx).clear(cx));
        let known_bounds = view.input.read_with(&visual, |state, _| {
            state
                .token_bounds
                .get(&7)
                .copied()
                .expect("placed token bounds")
        });
        visual.simulate_mouse_move(known_bounds.center(), None, gpui::Modifiers::default());
        visual.run_until_parked();
        visual.update(|window, cx| window.draw(cx).clear(cx));
        assert_eq!(events.borrow().as_slice(), &[("a".into(), true)]);

        // Remove the token while the pointer is still over its stale row: the
        // exit must fire even though the token element that owns the hover
        // mask is gone.
        view.window_handle
            .update(cx, |_, window, cx| {
                view.input
                    .update(cx, |state, cx| state.set_value("no tokens", window, cx));
            })
            .unwrap();
        visual.run_until_parked();
        visual.update(|window, cx| window.draw(cx).clear(cx));
        assert_eq!(
            events.borrow().as_slice(),
            &[("a".into(), true), ("a".into(), false)]
        );
    }

    #[gpui::test]
    fn test_inline_token_hover_bounds_stay_single_row_at_wrap_boundary(cx: &mut TestAppContext) {
        use crate::input::{InlineToken, InlineTokenPresentation};
        cx.update(crate::init);
        let view = InputView::build_textarea(cx, |state| {
            state
                .rows(4)
                .default_value("aaaa bbbb cccc dddd @alice eeee ffff")
        });
        view.window_handle
            .update(cx, |_, window, cx| {
                view.input.update(cx, |state, cx| {
                    state
                        .replace_range_with_token(
                            20..26,
                            InlineToken::new("a", "@alice"),
                            window,
                            cx,
                        )
                        .unwrap();
                    state.set_token_presentation(
                        InlineTokenPresentation::default()
                            .token(|_, _, _| div().w(px(60.)).h(px(20.))),
                    );
                });
            })
            .unwrap();
        let mut visual = VisualTestContext::from_window(view.window_handle.into(), cx);
        visual.update(|window, cx| window.draw(cx).clear(cx));
        let (placed, ranged, line_height) = view.input.read_with(&visual, |state, _| {
            (
                state
                    .token_bounds
                    .get(&20)
                    .copied()
                    .expect("placed token bounds"),
                state.range_to_bounds(&(20..26)),
                state.last_layout.as_ref().unwrap().line_height,
            )
        });
        // The laid-out element always occupies exactly one row of height, even
        // when the range-extent path resolves the same end boundary onto the
        // next visual row at a soft-wrap edge.
        assert!(placed.size.height <= line_height + px(1.), "{placed:?}");
        assert!(
            placed.size.width <= px(61.) && placed.size.width > px(0.),
            "{placed:?}"
        );
        if let Some(ranged) = ranged {
            assert!(
                ranged.size.height >= placed.size.height - px(1.),
                "{ranged:?} vs {placed:?}"
            );
        }
    }

    #[gpui::test]
    fn test_inline_token_hover_same_offset_replacement_exits_predecessor(cx: &mut TestAppContext) {
        use crate::input::{InlineToken, InlineTokenPresentation};
        use std::{cell::RefCell, rc::Rc};
        cx.update(crate::init);
        let view = InputView::build(cx, |state| state.default_value("@alice!"));
        let events = Rc::new(RefCell::new(Vec::new()));
        let sink = events.clone();
        view.window_handle
            .update(cx, |_, window, cx| {
                view.input.update(cx, |state, cx| {
                    state
                        .replace_range_with_token(0..6, InlineToken::new("a", "@alice"), window, cx)
                        .unwrap();
                    state.set_token_presentation(
                        InlineTokenPresentation::default()
                            .token(|_, _, _| div().w(px(100.)).h(px(20.)))
                            .on_token_hover(move |event, _, _| {
                                sink.borrow_mut()
                                    .push((event.token().id().clone(), event.is_hovered()));
                            }),
                    );
                });
            })
            .unwrap();
        let mut visual = VisualTestContext::from_window(view.window_handle.into(), cx);
        visual.update(|window, cx| window.draw(cx).clear(cx));
        let bounds = view
            .input
            .read_with(&visual, |state, _| state.token_bounds[&0]);
        visual.simulate_mouse_move(bounds.center(), None, gpui::Modifiers::default());
        visual.run_until_parked();
        visual.update(|window, cx| window.draw(cx).clear(cx));
        assert_eq!(events.borrow().as_slice(), &[("a".into(), true)]);

        view.window_handle
            .update(cx, |_, window, cx| {
                view.input.update(cx, |state, cx| {
                    state
                        .replace_range_with_token(0..6, InlineToken::new("b", "@alice"), window, cx)
                        .unwrap();
                });
            })
            .unwrap();
        visual.run_until_parked();
        visual.update(|window, cx| window.draw(cx).clear(cx));
        visual.simulate_mouse_move(
            bounds.center() + gpui::point(px(1.), px(0.)),
            None,
            gpui::Modifiers::default(),
        );
        visual.run_until_parked();
        visual.update(|window, cx| window.draw(cx).clear(cx));
        assert_eq!(
            events.borrow().as_slice(),
            &[("a".into(), true), ("a".into(), false), ("b".into(), true)]
        );
        // Disabling keeps the token mounted; re-enabling must reset GPUI's
        // retained hover state even with a stationary pointer.
        view.input
            .update(&mut visual, |state, cx| state.set_disabled(true, cx));
        visual.update(|window, cx| window.draw(cx).clear(cx));
        visual.run_until_parked();
        assert_eq!(events.borrow().last(), Some(&("b".into(), false)));
        view.input
            .update(&mut visual, |state, cx| state.set_disabled(false, cx));
        visual.update(|window, cx| window.draw(cx).clear(cx));
        visual.run_until_parked();
        visual.simulate_mouse_move(bounds.center(), None, gpui::Modifiers::default());
        visual.run_until_parked();
        assert_eq!(
            events.borrow().as_slice(),
            &[
                ("a".into(), true),
                ("a".into(), false),
                ("b".into(), true),
                ("b".into(), false),
                ("b".into(), true)
            ]
        );
        visual.simulate_mouse_move(
            bounds.bottom_right() + gpui::point(px(10.), px(10.)),
            None,
            gpui::Modifiers::default(),
        );
        visual.run_until_parked();
        assert_eq!(
            events.borrow().as_slice(),
            &[
                ("a".into(), true),
                ("a".into(), false),
                ("b".into(), true),
                ("b".into(), false),
                ("b".into(), true),
                ("b".into(), false)
            ]
        );
    }

    #[gpui::test]
    fn test_inline_token_hover_older_exit_keeps_newer_snapshot(cx: &mut TestAppContext) {
        use crate::input::{InlineToken, InlineTokenPresentation};
        use gpui::{Bounds, point, px, size};
        cx.update(crate::init);
        let view = InputView::build(cx, |state| state.default_value("@a @b"));
        let bounds = Bounds::new(point(px(10.), px(20.)), size(px(100.), px(20.)));
        view.window_handle
            .update(cx, |_, window, cx| {
                view.input.update(cx, |state, cx| {
                    state
                        .replace_range_with_token(0..2, InlineToken::new("a", "@a"), window, cx)
                        .unwrap();
                    state
                        .replace_range_with_token(3..5, InlineToken::new("b", "@b"), window, cx)
                        .unwrap();
                    state.set_token_presentation(
                        InlineTokenPresentation::default().on_token_hover(|_, _, _| {}),
                    );
                    // The pointer moves A -> B; GPUI dispatches B's enter
                    // before A's exit.
                    state
                        .token_hover(0, bounds, true, None)
                        .expect("hover enters A");
                    state
                        .token_hover(3, bounds, true, None)
                        .expect("hover enters B");
                    let (_, exit_a) = state.token_hover(0, bounds, false, None).expect("A exits");
                    assert!(!exit_a.is_hovered());
                    // B's snapshot must survive A's late exit.
                    assert_eq!(
                        state
                            .hovered_token
                            .as_ref()
                            .expect("B still hovered")
                            .span
                            .token()
                            .id()
                            .as_ref(),
                        "b"
                    );
                    // Removing B afterwards still produces B's reconciled exit.
                    state.set_value("no tokens", window, cx);
                    state.token_bounds.clear();
                    let (listener, exit_b) = state.reconcile_token_hover().expect("B must exit");
                    assert!(!exit_b.is_hovered());
                    assert_eq!(exit_b.token().id().as_ref(), "b");
                    drop(listener);
                });
            })
            .unwrap();
    }

    #[gpui::test]
    fn test_inline_token_hover_late_exit_matches_replaced_token(cx: &mut TestAppContext) {
        use crate::input::{InlineToken, InlineTokenPresentation};
        cx.update(crate::init);
        let view = InputView::build(cx, |state| state.default_value("@a"));
        view.window_handle
            .update(cx, |_, window, cx| {
                view.input.update(cx, |state, cx| {
                    let a = InlineToken::new("a", "@a");
                    let b = InlineToken::new("b", "@a");
                    state
                        .replace_range_with_token(0..2, a.clone(), window, cx)
                        .unwrap();
                    state.set_token_presentation(
                        InlineTokenPresentation::default().on_token_hover(|_, _, _| {}),
                    );
                    let bounds = gpui::Bounds::default();
                    state.token_hover(0, bounds, true, Some(&a)).unwrap();
                    state
                        .replace_range_with_token(0..2, b.clone(), window, cx)
                        .unwrap();
                    state.token_hover(0, bounds, true, Some(&b)).unwrap();
                    let (_, exit_a) = state.token_hover(0, bounds, false, Some(&a)).unwrap();
                    assert_eq!(exit_a.token().id().as_ref(), "a");
                    assert_eq!(state.hovered_token.as_ref().unwrap().span.token(), &b);
                    let (_, exit_b) = state.token_hover(0, bounds, false, Some(&b)).unwrap();
                    assert_eq!(exit_b.token().id().as_ref(), "b");
                    assert!(state.pending_token_hover_exits.is_empty());
                });
            })
            .unwrap();
    }

    #[gpui::test]
    fn test_inline_token_hover_exit_keeps_entry_utf16_after_edit(cx: &mut TestAppContext) {
        use crate::input::{InlineToken, InlineTokenPresentation};
        use gpui::EntityInputHandler as _;
        cx.update(crate::init);
        let view = InputView::build(cx, |state| state.default_value("🙂 @a"));
        view.window_handle
            .update(cx, |_, window, cx| {
                view.input.update(cx, |state, cx| {
                    state
                        .replace_range_with_token(5..7, InlineToken::new("a", "@a"), window, cx)
                        .unwrap();
                    state.set_token_presentation(
                        InlineTokenPresentation::default().on_token_hover(|_, _, _| {}),
                    );
                    let bounds = gpui::Bounds::default();
                    let (_, enter) = state.token_hover(5, bounds, true, None).unwrap();
                    assert_eq!(enter.range_utf16(), (3, 5));
                    state.replace_text_in_range(Some(0..2), "abcd", window, cx);
                    assert_eq!(state.token_spans()[0].range(), 5..7);
                    let (_, exit) = state.token_hover(5, bounds, false, None).unwrap();
                    assert_eq!(exit.range_utf16(), (3, 5));
                });
            })
            .unwrap();
    }

    #[gpui::test]
    fn test_set_selected_text_range(cx: &mut TestAppContext) {
        use gpui::EntityInputHandler as _;
        cx.update(crate::init);
        // "🙂" is 2 UTF-16 units and 4 bytes.
        let view = InputView::build(cx, |state| state.default_value("🙂 hello world"));
        view.window_handle
            .update(cx, |_, window, cx| {
                view.input.update(cx, |state, cx| {
                    fn selection(
                        state: &mut InputBaseState<InputMode>,
                        window: &mut Window,
                        cx: &mut Context<InputBaseState<InputMode>>,
                    ) -> (Range<usize>, bool) {
                        let selection = state.selected_text_range(false, window, cx).unwrap();
                        (selection.range, selection.reversed)
                    }

                    state.set_selected_text_range(3..8, window, cx);
                    assert_eq!(state.selected_range(), 5..10);
                    assert_eq!(selection(state, window, cx), (3..8, false));

                    // Dragging the end handle keeps the selection forward.
                    state.set_selected_text_range(3..14, window, cx);
                    assert_eq!(selection(state, window, cx), (3..14, false));
                    assert_eq!(state.cursor(), 16);

                    // Dragging the start handle reverses it, so the start is the cursor.
                    state.set_selected_text_range(9..14, window, cx);
                    assert_eq!(selection(state, window, cx), (9..14, true));
                    assert_eq!(state.cursor(), 11);

                    // A repeated range keeps its direction.
                    state.set_selected_text_range(9..14, window, cx);
                    assert_eq!(selection(state, window, cx), (9..14, true));

                    // Out of range clamps; a backwards range is normalized.
                    state.set_selected_text_range(100..9, window, cx);
                    assert_eq!(selection(state, window, cx), (9..14, true));

                    // Either handle can cross the stationary end.
                    state.set_selected_text_range(3..8, window, cx);
                    state.set_selected_text_range(2..3, window, cx);
                    assert_eq!(selection(state, window, cx), (2..3, true));
                    assert_eq!(state.cursor(), 4);
                    state.set_selected_text_range(3..8, window, cx);
                    state.set_selected_text_range(8..9, window, cx);
                    assert_eq!(selection(state, window, cx), (8..9, false));
                    assert_eq!(state.cursor(), 11);

                    // Collapsing places a forward cursor and leaves the text alone.
                    state.set_selected_text_range(2..2, window, cx);
                    assert_eq!(selection(state, window, cx), (2..2, false));
                    assert_eq!(state.value(), "🙂 hello world");
                });
            })
            .unwrap();
    }

    #[gpui::test]
    fn test_inline_token_hover_callback_edit_preserves_both_exits(cx: &mut TestAppContext) {
        use crate::input::{InlineToken, InlineTokenPresentation};
        cx.update(crate::init);
        let view = InputView::build(cx, |state| state.default_value("@a @b"));
        view.window_handle
            .update(cx, |_, window, cx| {
                view.input.update(cx, |state, cx| {
                    state
                        .replace_range_with_token(0..2, InlineToken::new("a", "@a"), window, cx)
                        .unwrap();
                    state
                        .replace_range_with_token(3..5, InlineToken::new("b", "@b"), window, cx)
                        .unwrap();
                    state.set_token_presentation(
                        InlineTokenPresentation::default().on_token_hover(|_, _, _| {}),
                    );
                    let bounds = gpui::Bounds::default();
                    state.token_hover(0, bounds, true, None).unwrap();
                    state.token_hover(3, bounds, true, None).unwrap();
                    // Model an edit in B's enter callback before A's queued exit.
                    state.set_value("gone", window, cx);
                    let (_, exit_a) = state.token_hover(0, bounds, false, None).unwrap();
                    assert_eq!(exit_a.token().id().as_ref(), "a");
                    let (_, exit_b) = state.reconcile_token_hover().unwrap();
                    assert_eq!(exit_b.token().id().as_ref(), "b");
                    assert!(state.token_hover(0, bounds, false, None).is_none());
                    assert!(state.reconcile_token_hover().is_none());
                });
            })
            .unwrap();
    }

    #[gpui::test]
    fn test_inline_token_edit_history_and_validation(cx: &mut TestAppContext) {
        let view = InputView::build(cx, |state| state.default_value("问 @alice!"));
        view.window_handle
            .update(cx, |_, window, cx| {
                view.input.update(cx, |state, cx| {
                    let token =
                        crate::input::InlineToken::new("alice-1", "@alice").with_label("Alice");
                    state
                        .replace_range_with_token(4..10, token.clone(), window, cx)
                        .unwrap();
                    assert_eq!(state.value().as_ref(), "问 @alice!");
                    assert_eq!(state.tokens()[0].range(), 4..10);
                    assert_eq!(state.next_end_of_word_at(4), 10);
                    assert_eq!(state.previous_start_of_word_at(10), 4);
                    state.undo(&Undo, window, cx);
                    assert!(
                        state.tokens().is_empty(),
                        "identity-only association is undoable"
                    );
                    assert_eq!(state.value().as_ref(), "问 @alice!");
                    state.redo(&Redo, window, cx);
                    assert_eq!(state.tokens()[0].token(), &token);
                    state.set_selected_range(6..7, cx);
                    assert_eq!(state.selected_range(), 4..10);
                    state.replace("", window, cx);
                    assert_eq!(state.value().as_ref(), "问 !");
                    assert!(state.tokens().is_empty());
                    state.undo(&Undo, window, cx);
                    assert_eq!(state.tokens()[0].token(), &token);
                    state.set_selected_range(0..0, cx);
                    state.replace("🙂", window, cx);
                    assert_eq!(state.tokens()[0].range(), 8..14);
                    state.undo(&Undo, window, cx);
                    assert_eq!(state.tokens()[0].range(), 4..10);
                    let before = state.content();
                    state
                        .replace_range_with_token(0..0, token.clone(), window, cx)
                        .expect("the same reference may occur twice");
                    assert_eq!(state.value().as_ref(), "@alice问 @alice!");
                    assert_eq!(state.tokens().len(), 2);
                    assert_eq!(state.tokens()[1].token(), &token);
                    state.undo(&Undo, window, cx);
                    assert_eq!(state.content(), before);
                    state.set_value(before.text().clone(), window, cx);
                    assert!(state.tokens().is_empty());
                    assert!(!state.undo_manager.has_undos());
                });
            })
            .unwrap();
    }

    #[gpui::test]
    fn test_inline_token_textarea_ime_and_modes(cx: &mut TestAppContext) {
        use crate::input::{InlineToken, InlineTokenError, InputContent};
        let view = InputView::build_textarea(cx, |state| state);
        view.window_handle
            .update(cx, |_, window, cx| {
                view.input.update(cx, |state, cx| {
                    let content = InputContent::new("@a@b\n后面")
                        .with_token(0..2, InlineToken::new("a", "@a"))
                        .unwrap()
                        .with_token(2..4, InlineToken::new("b", "@b"))
                        .unwrap();
                    state.set_value(content.clone(), window, cx);
                    state.set_selected_range(2..2, cx);
                    assert_eq!(state.previous_boundary(2), 0);
                    assert_eq!(state.next_boundary(2), 4);
                    state.replace_and_mark_text_in_range(Some(1..2), "中", Some(1..1), window, cx);
                    assert_eq!(state.value().as_ref(), "中@b\n后面");
                    assert_eq!(state.tokens().len(), 1);
                    assert_eq!(
                        state.replace_with_token(InlineToken::new("x", "x"), window, cx),
                        Err(InlineTokenError::CompositionActive)
                    );
                    state.replace_text_in_range(None, "中文", window, cx);
                    state.undo(&Undo, window, cx);
                    assert_eq!(state.content(), content);
                    state.redo(&Redo, window, cx);
                    assert_eq!(state.value().as_ref(), "中文@b\n后面");
                    state.undo(&Undo, window, cx);
                    state.replace_all("plain", window, cx);
                    assert!(state.tokens().is_empty());
                    state.undo(&Undo, window, cx);
                    assert_eq!(state.content(), content);
                });
            })
            .unwrap();
        let view = InputView::build(cx, |state| state);
        view.window_handle
            .update(cx, |_, window, cx| {
                view.input.update(cx, |state, cx| {
                    assert_eq!(
                        InputContent::new("a\u{301}")
                            .with_token(0..1, InlineToken::new("bad", "a"))
                            .err(),
                        Some(InlineTokenError::InvalidBoundary)
                    );
                    assert_eq!(
                        InputContent::new("@a@a")
                            .with_token(0..2, InlineToken::new("a", "@a"))
                            .unwrap()
                            .with_token(1..3, InlineToken::new("x", "a@"))
                            .err(),
                        Some(InlineTokenError::OverlappingTokens)
                    );
                    state
                        .replace_with_token(InlineToken::new("a", "@a"), window, cx)
                        .unwrap();
                    let before = state.content();
                    state.set_masked(true, window, cx);
                    assert!(!state.tokens_visible());
                    assert_eq!(
                        state.replace_with_token(InlineToken::new("b", "b"), window, cx),
                        Err(InlineTokenError::UnsupportedMode)
                    );
                    assert_eq!(state.content(), before);
                    state.undo(&Undo, window, cx);
                    assert!(state.tokens().is_empty());
                    state.redo(&Redo, window, cx);
                    assert_eq!(state.content(), before);
                    assert!(!state.tokens_visible());
                });
            })
            .unwrap();
    }

    use crate::theme::Theme;
    use gpui::{TestAppContext, VisualTestContext, size};

    use crate::input::{EditorMode, EditorState, InputMode, LanguageConfig, TabSize, TextareaMode};

    fn set_test_syntax_provider(
        provider: Rc<dyn crate::input::SyntaxContextProvider>,
        cx: &mut App,
    ) {
        struct TestLanguages(Rc<dyn crate::input::SyntaxContextProvider>);
        impl crate::input::LanguageProvider for TestLanguages {
            fn syntax_context_provider(
                &self,
                _: &str,
            ) -> Option<Rc<dyn crate::input::SyntaxContextProvider>> {
                Some(self.0.clone())
            }
        }
        crate::input::set_language_provider(Rc::new(TestLanguages(provider)), cx);
    }

    struct TestRoot<M: InputModeKind>(Entity<InputBaseState<M>>);

    impl<M: InputModeKind> Render for TestRoot<M> {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            div().size_full().child(self.0.clone())
        }
    }

    struct InputView<M: InputModeKind> {
        input: Entity<InputBaseState<M>>,
        window_handle: gpui::WindowHandle<TestRoot<M>>,
    }

    /// Helper to open a state of one mode in a window for testing.
    impl<M: InputModeKind> InputView<M> {
        fn build_with(
            cx: &mut TestAppContext,
            make: impl FnOnce(&mut Window, &mut Context<InputBaseState<M>>) -> InputBaseState<M>
            + 'static,
        ) -> Self {
            let mut input: Option<Entity<InputBaseState<M>>> = None;

            let window = cx.update(|cx| {
                cx.open_window(Default::default(), |window, cx| {
                    // Set up the theme first
                    cx.set_global(Theme::default());
                    // Initialize input keybindings
                    super::super::init(cx);

                    input = Some(cx.new(|cx| make(window, cx)));

                    cx.new(|_| TestRoot(input.clone().unwrap()))
                })
                .unwrap()
            });

            Self {
                input: input.clone().unwrap(),
                window_handle: window,
            }
        }
    }

    impl InputView<EditorMode> {
        /// An editor state, for the tests that exercise code-editor behavior.
        fn new(cx: &mut TestAppContext) -> Self {
            Self::build_editor(cx, |state| state)
        }

        fn build_editor(
            cx: &mut TestAppContext,
            f: impl FnOnce(InputBaseState<EditorMode>) -> InputBaseState<EditorMode> + 'static,
        ) -> Self {
            Self::build_with(cx, move |window, cx| {
                f(crate::input::EditorState::new(window, cx).language("sql"))
            })
        }
    }

    impl InputView<TextareaMode> {
        fn build_textarea(
            cx: &mut TestAppContext,
            f: impl FnOnce(InputBaseState<TextareaMode>) -> InputBaseState<TextareaMode> + 'static,
        ) -> Self {
            Self::build_with(cx, move |window, cx| {
                f(crate::input::TextareaState::new(window, cx))
            })
        }
    }

    impl InputView<InputMode> {
        /// A single-line state, the default these tests were written against.
        fn build(
            cx: &mut TestAppContext,
            f: impl FnOnce(InputBaseState<InputMode>) -> InputBaseState<InputMode> + 'static,
        ) -> Self {
            Self::build_with(cx, move |window, cx| {
                f(crate::input::InputState::new(window, cx))
            })
        }
    }

    /// Sends one trackpad packet straight to the input.
    fn swipe<M: InputModeKind>(
        view: &InputView<M>,
        cx: &mut VisualTestContext,
        dy: f32,
        phase: gpui::TouchPhase,
    ) {
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| {
                state.on_scroll_wheel(
                    &ScrollEvent {
                        delta: gpui::ScrollDelta::Pixels(point(px(0.), px(dy))),
                        touch_phase: phase,
                        ..Default::default()
                    },
                    window,
                    cx,
                )
            })
        });
    }

    fn long_text() -> String {
        (0..60)
            .map(|n| format!("line {n}"))
            .collect::<Vec<_>>()
            .join("\n")
    }

    #[gpui::test]
    fn test_scroll_bounce_stretches_past_the_end_and_springs_back(cx: &mut TestAppContext) {
        use gpui::TouchPhase::{Ended, Moved, Started};

        let view = InputView::build_textarea(cx, |state| {
            state.scroll_bounce(true).default_value(long_text())
        });
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        cx.update(|window, cx| window.draw(cx).clear(cx));
        let drawn_at = |cx: &mut VisualTestContext| {
            view.input
                .read_with(cx, |state, _| state.last_bounds.unwrap().origin.y)
        };

        swipe(&view, &mut cx, -20., Started);
        swipe(&view, &mut cx, -100_000., Moved);
        let (end, stretch) = view.input.read_with(&cx, |state, _| {
            (state.scroll_handle.offset().y, state.overscroll.offset())
        });
        assert!(end < px(0.), "the text scrolled to its end");
        assert!(stretch < 0., "the rest stretched the edge: {stretch}");
        cx.update(|window, cx| window.draw(cx).clear(cx));
        let stretched_at = drawn_at(&mut cx);

        swipe(&view, &mut cx, 0., Ended);
        for _ in 0..120 {
            cx.executor()
                .advance_clock(std::time::Duration::from_millis(16));
            cx.update(|window, cx| window.draw(cx).clear(cx));
        }
        view.input.read_with(&cx, |state, _| {
            assert_eq!(state.overscroll.offset(), 0., "the edge sprang back");
            assert_eq!(
                state.scroll_handle.offset().y,
                end,
                "scrolling stayed exact"
            );
        });
        let moved = (stretched_at - drawn_at(&mut cx)).as_f32();
        assert!(
            (moved - stretch).abs() < 0.001,
            "the stretch only moved where the text was drawn: {moved} vs {stretch}"
        );
    }

    /// Swipes far past the end of the text and returns where the text
    /// scrolled to and how far its edge stretched.
    fn swipe_past_the_end(
        view: &InputView<TextareaMode>,
        cx: &mut VisualTestContext,
    ) -> (Pixels, f32) {
        use gpui::TouchPhase::{Moved, Started};

        cx.update(|window, cx| window.draw(cx).clear(cx));
        swipe(view, cx, -20., Started);
        swipe(view, cx, -100_000., Moved);
        view.input.read_with(cx, |state, _| {
            (state.scroll_handle.offset().y, state.overscroll.offset())
        })
    }

    #[gpui::test]
    fn test_scroll_bounce_stays_put_under_reduced_motion(cx: &mut TestAppContext) {
        cx.update(|cx| cx.set_reduce_motion(true));
        let view = InputView::build_textarea(cx, |state| {
            state.scroll_bounce(true).default_value(long_text())
        });
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        let (end, stretch) = swipe_past_the_end(&view, &mut cx);
        assert!(end < px(0.), "the text still scrolls");
        assert_eq!(stretch, 0., "the edge does not stretch");
    }

    #[gpui::test]
    fn test_scroll_bounce_follows_the_platform_by_default(cx: &mut TestAppContext) {
        let view = InputView::build_textarea(cx, |state| state.default_value(long_text()));
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        let (end, stretch) = swipe_past_the_end(&view, &mut cx);
        assert!(end < px(0.), "the text scrolls");
        assert_eq!(
            stretch != 0.,
            crate::ScrollBounce::enabled_by_default(),
            "the edge stretches where the platform's scroll views do"
        );
    }

    #[gpui::test]
    fn test_scroll_bounce_leaves_text_that_fits(cx: &mut TestAppContext) {
        let view = InputView::build_textarea(cx, |state| {
            state.scroll_bounce(true).default_value("one line")
        });
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        let (end, stretch) = swipe_past_the_end(&view, &mut cx);
        assert_eq!((end, stretch), (px(0.), 0.));
    }

    #[gpui::test]
    fn test_scroll_bounce_resets_when_replacement_text_fits(cx: &mut TestAppContext) {
        let view = InputView::build_textarea(cx, |state| {
            state.scroll_bounce(true).default_value(long_text())
        });
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        let (_, stretch) = swipe_past_the_end(&view, &mut cx);
        assert!(stretch < 0.);
        cx.update(|window, cx| {
            view.input
                .update(cx, |state, cx| state.set_value("short", window, cx));
            window.draw(cx).clear(cx);
        });
        swipe(&view, &mut cx, 0., gpui::TouchPhase::Ended);
        view.input.read_with(&cx, |state, _| {
            assert_eq!(state.overscroll.offset(), 0.);
            assert_eq!(state.scroll_handle.offset().y, px(0.));
        });
    }

    #[gpui::test]
    fn test_scroll_bounce_releases_when_the_end_packet_is_horizontal(cx: &mut TestAppContext) {
        let view = InputView::build_textarea(cx, |state| {
            state.scroll_bounce(true).default_value(long_text())
        });
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        let (_, stretch) = swipe_past_the_end(&view, &mut cx);
        assert!(stretch < 0.);
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| {
                state.on_scroll_wheel(
                    &ScrollEvent {
                        delta: gpui::ScrollDelta::Pixels(point(px(1.), px(0.))),
                        touch_phase: gpui::TouchPhase::Ended,
                        ..Default::default()
                    },
                    window,
                    cx,
                );
            });
        });
        for _ in 0..120 {
            cx.executor()
                .advance_clock(std::time::Duration::from_millis(16));
            cx.update(|window, cx| window.draw(cx).clear(cx));
        }
        assert_eq!(
            view.input
                .read_with(&cx, |state, _| state.overscroll.offset()),
            0.
        );
    }

    #[gpui::test]
    fn test_scroll_bounce_ordinary_mouse_wheel_does_not_stretch(cx: &mut TestAppContext) {
        let view = InputView::build_textarea(cx, |state| {
            state.scroll_bounce(true).default_value(long_text())
        });
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        cx.update(|window, cx| {
            window.draw(cx).clear(cx);
            view.input.update(cx, |state, cx| {
                state.on_scroll_wheel(
                    &ScrollEvent {
                        delta: gpui::ScrollDelta::Lines(point(0., -100_000.)),
                        touch_phase: gpui::TouchPhase::Moved,
                        ..Default::default()
                    },
                    window,
                    cx,
                );
                assert!(state.scroll_handle.offset().y < px(0.));
                assert_eq!(state.overscroll.offset(), 0.);
            });
        });
    }

    #[gpui::test]
    fn test_scroll_bounce_new_wheel_input_interrupts_the_return(cx: &mut TestAppContext) {
        let view = InputView::build_textarea(cx, |state| {
            state.scroll_bounce(true).default_value(long_text())
        });
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        let (end, stretch) = swipe_past_the_end(&view, &mut cx);
        assert!(stretch < 0.);
        swipe(&view, &mut cx, 0., gpui::TouchPhase::Ended);
        cx.executor()
            .advance_clock(std::time::Duration::from_millis(16));
        cx.update(|window, cx| {
            window.draw(cx).clear(cx);
            view.input.update(cx, |state, cx| {
                state.on_scroll_wheel(
                    &ScrollEvent {
                        delta: gpui::ScrollDelta::Lines(point(0., 2.)),
                        touch_phase: gpui::TouchPhase::Moved,
                        ..Default::default()
                    },
                    window,
                    cx,
                );
                assert!(state.scroll_handle.offset().y > end);
                assert_eq!(state.overscroll.offset(), 0.);
            });
        });
    }

    #[gpui::test]
    fn test_turning_scroll_bounce_off_drops_the_stretch(cx: &mut TestAppContext) {
        let view = InputView::build_textarea(cx, |state| {
            state.scroll_bounce(true).default_value(long_text())
        });
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        let (_, stretch) = swipe_past_the_end(&view, &mut cx);
        assert!(stretch < 0., "the edge stretched: {stretch}");
        view.input
            .update(&mut cx, |state, cx| state.set_scroll_bounce(false, cx));
        assert_eq!(
            view.input
                .read_with(&cx, |state, _| state.overscroll.offset()),
            0.
        );
    }

    /// The frame is laid out by the application, which should not have to
    /// center a single line inside it.
    #[gpui::test]
    fn single_line_is_centered_in_a_taller_frame(cx: &mut TestAppContext) {
        struct Frame(Entity<InputBaseState<InputMode>>);
        impl Render for Frame {
            fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
                crate::input::InputBase::new("frame")
                    .h(px(60.))
                    .child(crate::input::Input::new(&self.0))
            }
        }

        cx.update(crate::init);
        let mut input = None;
        let window = cx.open_window(size(px(400.), px(100.)), |window, cx| {
            let state = cx.new(|cx| crate::input::InputState::new(window, cx).default_value("a"));
            input = Some(state.clone());
            Frame(state)
        });
        let input = input.unwrap();
        let mut cx = VisualTestContext::from_window(window.into(), cx);
        cx.update(|window, cx| window.draw(cx).clear(cx));

        input.read_with(&cx, |state, _| {
            let line = state.input_bounds;
            assert_eq!(line.center().y, px(30.), "line {line:?}");
        });
    }

    #[gpui::test]
    fn test_noop_scroll_notifies_diagnostic_dismissal(cx: &mut TestAppContext) {
        use std::{cell::Cell, rc::Rc};

        cx.update(crate::init);
        let mut input = None;
        let window = cx.open_window(size(px(400.), px(100.)), |window, cx| {
            input = Some(cx.new(|cx| crate::input::EditorState::new(window, cx)));
            gpui::EmptyView
        });
        let input = input.unwrap();
        input.update(cx, |state, cx| {
            state.input_bounds = Bounds::new(Point::default(), size(px(100.), px(20.)));
            state.scroll_size = size(px(100.), px(20.));
            state.present_diagnostic(crate::input::DiagnosticEntry::default(), cx);
        });
        let notifications = Rc::new(Cell::new(0));
        let count = notifications.clone();
        let _subscription =
            cx.update(|cx| cx.observe(&input, move |_, _| count.set(count.get() + 1)));

        window
            .update(cx, |_, window, cx| {
                input.update(cx, |state, cx| {
                    state.on_scroll_wheel(
                        &ScrollEvent {
                            delta: gpui::ScrollDelta::Pixels(point(px(0.), px(-40.))),
                            ..Default::default()
                        },
                        window,
                        cx,
                    );
                    assert_eq!(state.scroll_handle.offset(), Point::default());
                    assert!(state.diagnostic_popover().is_none());
                });
            })
            .unwrap();
        assert_eq!(
            notifications.get(),
            1,
            "clearing a diagnostic must notify even when scrolling is clamped"
        );
        window
            .update(cx, |_, window, cx| {
                input.update(cx, |state, cx| {
                    state.on_scroll_wheel(
                        &ScrollEvent {
                            delta: gpui::ScrollDelta::Pixels(point(px(0.), px(-40.))),
                            ..Default::default()
                        },
                        window,
                        cx,
                    );
                });
            })
            .unwrap();
        assert_eq!(notifications.get(), 1, "an unchanged input must stay quiet");
    }

    /// Hover must reach the whole visible editor after scrolling, not only
    /// the part that overlaps the unscrolled text bounds.
    #[gpui::test]
    fn test_hover_reaches_bottom_of_scrolled_editor(cx: &mut TestAppContext) {
        use crate::input::{Diagnostic, Position};
        struct Frame(Entity<crate::input::EditorState>);
        impl Render for Frame {
            fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
                crate::input::InputBase::new("frame")
                    .h(px(100.))
                    .child(crate::input::Editor::new(&self.0))
            }
        }

        cx.update(crate::init);
        let text = (0..100).map(|i| format!("line {i}\n")).collect::<String>();
        let mut input = None;
        let window = cx.open_window(size(px(400.), px(100.)), |window, cx| {
            let state = cx.new(|cx| crate::input::EditorState::new(window, cx).default_value(text));
            input = Some(state.clone());
            Frame(state)
        });
        let input = input.unwrap();
        let mut cx = VisualTestContext::from_window(window.into(), cx);
        input.update(&mut cx, |state, _| {
            state.diagnostics_mut().unwrap().push(Diagnostic::new(
                Position::new(0, 0)..Position::new(100, 0),
                "everywhere",
            ));
        });
        cx.update(|window, cx| window.draw(cx).clear(cx));
        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.on_scroll_wheel(
                    &ScrollEvent {
                        delta: gpui::ScrollDelta::Pixels(point(px(0.), px(-400.))),
                        ..Default::default()
                    },
                    window,
                    cx,
                );
            })
        });
        cx.update(|window, cx| window.draw(cx).clear(cx));

        let bounds = input.read_with(&cx, |state, _| state.input_bounds);
        cx.simulate_mouse_move(
            point(bounds.center().x, bounds.bottom() - px(5.)),
            None,
            gpui::Modifiers::default(),
        );
        assert!(
            input.read_with(&cx, |state, _| state.diagnostic_popover().is_some()),
            "no hover at the bottom of a scrolled editor, bounds {bounds:?}"
        );
    }

    #[gpui::test]
    fn test_cursor_layout_consumer_updates_after_selection(cx: &mut TestAppContext) {
        use std::{cell::Cell, rc::Rc};
        struct Panel {
            input: Entity<crate::input::EditorState>,
            observed: Rc<Cell<Option<(Bounds<Pixels>, Pixels)>>>,
        }
        impl Render for Panel {
            fn render(&mut self, _: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
                self.observed.set(self.input.read(cx).cursor_layout());
                div().size_full().child(self.input.clone())
            }
        }
        struct Root(Entity<Panel>);
        impl Render for Root {
            fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
                div().size_full().child(
                    self.0
                        .clone()
                        .cached(gpui::StyleRefinement::default().size_full()),
                )
            }
        }
        cx.update(crate::init);
        let observed = Rc::new(Cell::new(None));
        let mut input = None;
        let window = cx.open_window(size(px(400.), px(100.)), |window, cx| {
            let state = cx.new(|cx| {
                let mut state = crate::input::EditorState::new(window, cx);
                state.set_value("abcdefgh", window, cx);
                state
            });
            input = Some(state.clone());
            Root(cx.new(|_| Panel {
                input: state,
                observed: observed.clone(),
            }))
        });
        cx.run_until_parked();
        let input = input.unwrap();
        let before = input.read_with(cx, |state, _| state.cursor_layout());
        // The caret geometry only exists once the input has painted, and a
        // notify sent from inside a draw marks the view dirty without asking
        // for another frame, so the consumer reads the geometry on the next
        // invalidation rather than during the paint that produced it.
        input.update(cx, |_, cx| cx.notify());
        cx.run_until_parked();
        assert_eq!(observed.get(), before);
        window
            .update(cx, |_, _, cx| {
                input.update(cx, |state, cx| state.select_to_with_affinity(3, false, cx));
            })
            .unwrap();
        cx.run_until_parked();
        window.update(cx, |_, _, cx| cx.notify()).unwrap();
        let after = input.read_with(cx, |state, _| state.cursor_layout());
        assert_ne!(after, before, "the caret must actually move");
        assert_eq!(
            observed.get(),
            after,
            "render consumers must receive the newly painted caret geometry"
        );
    }

    #[gpui::test]
    fn test_input_scroll_offset_notifies_only_on_change(cx: &mut TestAppContext) {
        use std::{cell::Cell, rc::Rc};

        cx.update(crate::init);
        let mut input = None;
        let _window = cx.open_window(size(px(400.), px(100.)), |window, cx| {
            input = Some(cx.new(|cx| crate::input::InputState::new(window, cx)));
            gpui::EmptyView
        });
        let input = input.unwrap();
        let notifications = Rc::new(Cell::new(0));
        let count = notifications.clone();
        let _subscription =
            cx.update(|cx| cx.observe(&input, move |_, _| count.set(count.get() + 1)));

        input.update(cx, |state, _| {
            state.input_bounds = Bounds::new(Point::default(), size(px(100.), px(20.)));
            state.scroll_size = size(px(300.), px(20.));
        });
        for target in [
            None,
            Some(point(px(0.), px(0.))),
            Some(point(px(20.), px(50.))),
        ] {
            input.update(cx, |state, cx| state.update_scroll_offset(target, cx));
            assert_eq!(
                notifications.get(),
                0,
                "an unchanged clamped offset must stay quiet"
            );
        }
        input.update(cx, |state, cx| {
            state.update_scroll_offset(Some(point(px(-40.), px(0.))), cx);
            assert_eq!(state.scroll_handle.offset(), point(px(-40.), px(0.)));
        });
        assert_eq!(notifications.get(), 1, "a scroll must notify");
        input.update(cx, |state, cx| {
            state.update_scroll_offset(Some(point(px(-400.), px(50.))), cx);
            assert_eq!(state.scroll_handle.offset(), point(px(-200.), px(0.)));
        });
        assert_eq!(notifications.get(), 2);
        input.update(cx, |state, cx| {
            state.update_scroll_offset(Some(point(px(-500.), px(0.))), cx);
        });
        assert_eq!(
            notifications.get(),
            2,
            "clamping to the current offset must stay quiet"
        );
        input.update(cx, |state, cx| {
            state.scroll_size.width = px(110.);
            state.update_scroll_offset(None, cx);
            assert_eq!(state.scroll_handle.offset(), point(px(-10.), px(0.)));
        });
        assert_eq!(
            notifications.get(),
            3,
            "a smaller scroll range must clamp and notify"
        );
    }

    #[gpui::test]
    fn test_set_line_number_notifies_only_on_change(cx: &mut TestAppContext) {
        use std::{cell::Cell, rc::Rc};

        cx.update(crate::init);
        let mut input = None;
        let window = cx.open_window(size(px(400.), px(100.)), |window, cx| {
            input = Some(cx.new(|cx| crate::input::EditorState::new(window, cx)));
            gpui::EmptyView
        });
        let input = input.unwrap();
        let shown = input.read_with(cx, |state, _| state.mode.line_number());
        let notifications = Rc::new(Cell::new(0));
        let count = notifications.clone();
        let _subscription =
            cx.update(|cx| cx.observe(&input, move |_, _| count.set(count.get() + 1)));

        window
            .update(cx, |_, window, cx| {
                input.update(cx, |state, cx| state.set_line_number(shown, window, cx))
            })
            .unwrap();
        assert_eq!(notifications.get(), 0);

        window
            .update(cx, |_, window, cx| {
                input.update(cx, |state, cx| state.set_line_number(!shown, window, cx))
            })
            .unwrap();
        assert_eq!(notifications.get(), 1);
        assert_eq!(
            input.read_with(cx, |state, _| state.mode.line_number()),
            !shown
        );
    }

    #[gpui::test]
    fn test_set_value_on_unfocused_input_stays_quiet(cx: &mut TestAppContext) {
        use std::{cell::Cell, rc::Rc};

        cx.update(crate::init);
        let mut input = None;
        let window = cx.open_window(size(px(400.), px(100.)), |window, cx| {
            input = Some(cx.new(|cx| crate::input::InputState::new(window, cx)));
            gpui::EmptyView
        });
        let input = input.unwrap();
        cx.run_until_parked();

        let notifications = Rc::new(Cell::new(0));
        let count = notifications.clone();
        let _subscription =
            cx.update(|cx| cx.observe(&input, move |_, _| count.set(count.get() + 1)));
        cx.run_until_parked();

        // Seeding a form is a write, so it notifies once. The input is not
        // focused and draws no caret, so nothing may notify after that.
        window
            .update(cx, |_, window, cx| {
                input.update(cx, |state, cx| state.set_value("seeded", window, cx));
            })
            .unwrap();
        cx.run_until_parked();
        let settled = notifications.get();

        cx.executor()
            .advance_clock(std::time::Duration::from_secs(3));
        cx.run_until_parked();

        assert_eq!(
            notifications.get(),
            settled,
            "an unfocused input is blinking, and every blink repaints the view it is in"
        );
    }

    #[gpui::test]
    fn test_input_does_not_invalidate_cached_parent_during_paint(cx: &mut TestAppContext) {
        use std::{cell::Cell, rc::Rc};

        struct Panel {
            input: Entity<crate::input::InputState>,
            renders: Rc<Cell<usize>>,
        }
        impl Render for Panel {
            fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
                self.renders.set(self.renders.get() + 1);
                div().size_full().child(self.input.clone())
            }
        }
        struct Root(Entity<Panel>);
        impl Render for Root {
            fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
                div().size_full().child(
                    self.0
                        .clone()
                        .cached(gpui::StyleRefinement::default().size_full()),
                )
            }
        }

        cx.update(crate::init);
        let renders = Rc::new(Cell::new(0));
        let mut input = None;
        let window = cx.open_window(size(px(400.), px(100.)), |window, cx| {
            let state = cx.new(|cx| crate::input::InputState::new(window, cx));
            input = Some(state.clone());
            Root(cx.new(|_| Panel {
                input: state,
                renders: renders.clone(),
            }))
        });
        cx.run_until_parked();
        let before = renders.get();
        assert!(before > 0);
        for _ in 0..60 {
            window.update(cx, |_, _, cx| cx.notify()).unwrap();
        }
        assert_eq!(
            renders.get(),
            before,
            "an idle input must not invalidate its cached parent"
        );

        let input = input.unwrap();
        window
            .update(cx, |_, window, cx| {
                input.update(cx, |state, cx| state.set_value("changed", window, cx));
            })
            .unwrap();
        assert!(
            renders.get() > before,
            "text changes must invalidate the parent"
        );
        // The first paint reports the changed text extent to layout consumers.
        window.update(cx, |_, _, cx| cx.notify()).unwrap();
        let before = renders.get();
        for _ in 0..60 {
            window.update(cx, |_, _, cx| cx.notify()).unwrap();
        }
        assert_eq!(renders.get(), before, "the edited input must settle again");

        cx.simulate_window_resize(window.into(), size(px(240.), px(100.)));
        cx.run_until_parked();
        assert!(renders.get() > before, "resizing must invalidate layout");
    }

    #[gpui::test]
    fn textarea_cursor_treats_crlf_as_one_newline(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let view = InputView::build_textarea(cx, |state| state);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| {
                for original in ["\r\nlast", "\u{feff}first\r\nlast\n", "first\nlast\r\n"] {
                    state.set_value(original, window, cx);
                    let newline = original.find('\n').unwrap();
                    let end = if original.as_bytes()[newline.saturating_sub(1)] == b'\r' {
                        newline - 1
                    } else {
                        newline
                    };
                    state.end(&MoveEnd, window, cx);
                    assert_eq!(state.cursor(), end);
                    state.right(&MoveRight, window, cx);
                    assert_eq!(state.cursor(), newline + 1);
                    state.left(&MoveLeft, window, cx);
                    assert_eq!(state.cursor(), end);
                    state.select_to_end_of_line(&SelectToEndOfLine, window, cx);
                    assert_eq!(state.selected_range(), end..end);
                    state.move_to_end(&MoveToEnd, window, cx);
                    assert_eq!(state.cursor(), original.len());
                    state.move_to_start(&MoveToStart, window, cx);
                    assert_eq!(state.cursor(), 0);
                    assert_eq!(state.value().as_bytes(), original.as_bytes());
                }
                // A lone CR is an ordinary character; it must not skip its neighbour.
                state.set_value("a\rb", window, cx);
                state.right(&MoveRight, window, cx);
                assert_eq!(state.cursor(), 1);
                state.right(&MoveRight, window, cx);
                assert_eq!(state.cursor(), 2);
            })
        });
    }

    #[gpui::test]
    fn only_a_multi_line_input_paints_scrollbars(cx: &mut TestAppContext) {
        cx.update(crate::init);

        // A single-line input keeps its caret in view by moving its own offset;
        // it has no viewport to drag, so a scrollbar in a text field is a
        // control that does not exist.
        let single = InputView::build(cx, |state| state);
        single
            .input
            .update(cx, |state, _| assert!(!state.shows_scrollbar()));

        let multi = InputView::build_textarea(cx, |state| state);
        multi
            .input
            .update(cx, |state, _| assert!(state.shows_scrollbar()));
    }

    #[gpui::test]
    fn context_menu_handler_is_deferred_and_respects_disabled(cx: &mut TestAppContext) {
        use std::{cell::Cell, rc::Rc};
        cx.update(crate::init);
        let input_view = InputView::new(cx);
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;
        let calls = Rc::new(Cell::new(0usize));
        let items = Rc::new(Cell::new(0usize));
        let menu_focus = cx.update(|_, cx| cx.focus_handle());

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                let calls2 = calls.clone();
                let items2 = items.clone();
                let menu_focus = menu_focus.clone();
                state.on_context_menu(Rc::new(move |menu, _, _, window, cx| {
                    calls2.set(calls2.get() + 1);
                    items2.set(menu.items.len());
                    menu_focus.focus(window, cx);
                }));
                state.handle_right_click_menu(point(px(0.), px(0.)), 0, window, cx);
            })
        });
        assert_eq!(calls.get(), 1);
        assert_eq!(items.get(), 0);
        input.read_with(&cx, |state, _| {
            assert_eq!(
                state
                    .selection_focus
                    .as_ref()
                    .and_then(WeakFocusHandle::upgrade)
                    .as_ref(),
                Some(&menu_focus),
                "the menu callback must retain selection without reborrowing its input"
            );
        });

        // A custom handler may keep using the same, already-focused menu.
        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.handle_right_click_menu(point(px(0.), px(0.)), 0, window, cx);
            });
        });
        assert_eq!(calls.get(), 2);
        cx.update(|window, cx| {
            assert!(input.read(cx).has_selection_focus(window, cx));
        });

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.disabled = true;
                state.handle_right_click_menu(point(px(0.), px(0.)), 0, window, cx);
            })
        });
        assert_eq!(calls.get(), 2);
    }

    #[gpui::test]
    fn context_menu_handler_can_read_its_input(cx: &mut TestAppContext) {
        use std::{cell::Cell, rc::Rc};
        cx.update(crate::init);
        let input_view = InputView::new(cx);
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;
        let cursor = Rc::new(Cell::new(None));

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.set_value("hello", window, cx);
                let weak = cx.weak_entity();
                let cursor = cursor.clone();
                state.on_context_menu(Rc::new(move |_, _, _, _, cx| {
                    cursor.set(weak.upgrade().map(|input| input.read(cx).cursor()));
                }));
                state.handle_right_click_menu(point(px(0.), px(0.)), 2, window, cx);
            })
        });
        assert_eq!(cursor.get(), Some(2));
    }

    #[gpui::test]
    fn test_readonly_rejects_user_edits_only(cx: &mut TestAppContext) {
        let input_view = InputView::new(cx);
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.set_value("hello", window, cx);
                state.set_readonly(true, cx);
            });
        });

        cx.update(|_, cx| {
            input.read_with(cx, |state, _| {
                assert!(!state.is_editable());
                assert!(!state.is_replaceable());
            });
        });

        // Typing (and IME) goes through the input handler, it must be rejected.
        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.replace_text_in_range(None, " world", window, cx);
                state.replace_and_mark_text_in_range(None, "あ", None, window, cx);
            });
        });
        cx.update(|_, cx| {
            input.read_with(cx, |state, _| assert_eq!(state.value(), "hello"));
        });

        // The programmatic APIs are not limited by the readonly mode.
        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.insert(" world", window, cx);
                state.set_value("changed", window, cx);
            });
        });
        cx.update(|_, cx| {
            input.read_with(cx, |state, _| assert_eq!(state.value(), "changed"));
        });

        // And the user can edit again after leaving the readonly mode.
        // The caret is at the start, because `set_value` has reset the selection.
        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.set_readonly(false, cx);
                state.replace_text_in_range(None, "!", window, cx);
            });
        });
        cx.update(|_, cx| {
            input.read_with(cx, |state, _| {
                assert!(state.is_editable());
                assert_eq!(state.value(), "!changed");
            });
        });
    }

    /// Regression test: editing at a caret that sits far outside the viewport
    /// must reveal it in one frame. The cursor-follow in `layout_cursors` runs
    /// only on the frame the selection changes, so its old one-line step left
    /// the caret offscreen after typing at the end of a long paste.
    #[gpui::test]
    fn test_edit_reveals_far_offscreen_caret(cx: &mut TestAppContext) {
        let mut input = None;
        let window = cx.open_window(size(px(720.), px(400.)), |window, cx| {
            cx.set_global(Theme::default());
            super::super::init(cx);
            let state = cx.new(|cx| crate::input::TextareaState::new(window, cx).auto_grow(1, 6));
            input = Some(state.clone());
            TestRoot(state)
        });
        let mut cx = VisualTestContext::from_window(window.into(), cx);
        let input = input.unwrap();

        let text: String = (1..=100)
            .map(|i| format!("line {i}"))
            .collect::<Vec<_>>()
            .join("\n");
        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.set_value(text, window, cx);
                let end = state.text.len();
                state.set_selection(end, end);
            });
        });
        cx.run_until_parked();

        // The user scrolled back to the top to read the pasted text.
        cx.update(|_, cx| {
            input.update(cx, |state, cx| {
                state.scroll_handle.set_offset(point(px(0.), px(0.)));
                cx.notify();
            });
        });
        cx.run_until_parked();

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.replace_text_in_range(None, "X", window, cx);
            });
        });
        cx.run_until_parked();

        cx.update(|_, cx| {
            input.read_with(cx, |state, _| {
                assert!(state.value().ends_with("line 100X"));
                let (caret, _) = state.cursor_layout().expect("caret painted");
                let viewport = state.input_bounds();
                let scroll_y = state.scroll_handle.offset().y;
                let top = caret.origin.y - viewport.origin.y + scroll_y;
                assert!(
                    top >= px(0.) && top + caret.size.height <= viewport.size.height,
                    "caret top {top:?} outside viewport height {:?} (scroll {scroll_y:?})",
                    viewport.size.height,
                );
            });
        });
    }

    /// Regression test: changing the auto-grow limits keeps the rows fitted to
    /// the text. `set_auto_grow` used to start over at `min_rows`, and the rows
    /// were counted again only on the next edit or wrap width change.
    #[gpui::test]
    fn test_set_auto_grow_keeps_rows_fitted(cx: &mut TestAppContext) {
        let mut input = None;
        let window = cx.open_window(size(px(720.), px(400.)), |window, cx| {
            cx.set_global(Theme::default());
            super::super::init(cx);
            let state = cx.new(|cx| crate::input::TextareaState::new(window, cx).auto_grow(1, 10));
            input = Some(state.clone());
            TestRoot(state)
        });
        let mut cx = VisualTestContext::from_window(window.into(), cx);
        let input = input.unwrap();

        let text: String = (1..=8)
            .map(|i| format!("line {i}"))
            .collect::<Vec<_>>()
            .join("\n");
        cx.update(|window, cx| {
            input.update(cx, |state, cx| state.set_value(text, window, cx));
        });
        cx.run_until_parked();
        cx.update(|_, cx| input.read_with(cx, |state, _| assert_eq!(state.mode.rows(), 8)));

        // A larger maximum keeps all eight rows.
        cx.update(|_, cx| input.update(cx, |state, cx| state.set_auto_grow(1, 12, cx)));
        cx.run_until_parked();
        cx.update(|_, cx| input.read_with(cx, |state, _| assert_eq!(state.mode.rows(), 8)));

        // A smaller maximum caps them.
        cx.update(|_, cx| input.update(cx, |state, cx| state.set_auto_grow(1, 4, cx)));
        cx.run_until_parked();
        cx.update(|_, cx| input.read_with(cx, |state, _| assert_eq!(state.mode.rows(), 4)));
    }

    /// Regression test: `scroll_to` at end-of-buffer must produce a deferred
    /// scroll target within the safe scroll range, so the painted frame
    /// matches what `update_scroll_offset` persists (no jitter). A small
    /// `cursor_surrounding_lines` override used to mismatch the hardcoded
    /// 3-line edge clearance in `scroll_to`, overshooting `safe_y_min`.
    #[gpui::test]
    fn test_scroll_to_eob_does_not_overshoot_safe_range(cx: &mut TestAppContext) {
        let input_view = InputView::new(cx);
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;

        // JetBrains-style: 1 trailing empty row + 1-line cursor surrounding.
        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.set_scroll_beyond_last_line(Some(1), window, cx);
                state.set_cursor_surrounding_lines(Some(1), window, cx);
                let text: String = (1..=50)
                    .map(|i| format!("line {i}"))
                    .collect::<Vec<_>>()
                    .join("\n");
                state.set_value(text, window, cx);
            });
        });
        cx.run_until_parked();

        // Sanity: paint populated `scroll_size` and `input_bounds` — without
        // these, `safe_y_min` below collapses to 0 and the assertion is vacuous.
        cx.update(|_, cx| {
            input.read_with(cx, |state, _| {
                assert!(
                    state.scroll_size.height > px(0.),
                    "scroll_size not populated by initial paint"
                );
                assert!(
                    state.input_bounds.size.height > px(0.),
                    "input_bounds not populated by initial paint"
                );
            });
        });

        // Move cursor to end with downward direction — same code path as a
        // `Down` keystroke at EOB. `scroll_to` runs synchronously inside
        // `move_to`; inspect `deferred_scroll_offset` in the same closure
        // before the next paint consumes and clears it.
        cx.update(|_, cx| {
            input.update(cx, |state, cx| {
                let end = state.text.len();
                state.move_to(end, Some(MoveDirection::Down), cx);

                let deferred = state
                    .deferred_scroll_offset
                    .expect("scroll_to should populate deferred_scroll_offset");
                let safe_y_min =
                    (-state.scroll_size.height + state.input_bounds.size.height).min(px(0.));

                assert!(
                    deferred.y >= safe_y_min,
                    "deferred_scroll_offset.y = {:?} below safe_y_min = {:?} \
                     — paint would jitter (Bug C regression)",
                    deferred.y,
                    safe_y_min,
                );
            });
        });
    }

    #[gpui::test]
    fn test_next_search_match_reveals_with_padding_after_manual_scroll(cx: &mut TestAppContext) {
        assert_search_reveals_with_padding_after_manual_scroll(false, cx);
    }

    #[gpui::test]
    fn test_previous_search_match_reveals_with_padding_after_manual_scroll(
        cx: &mut TestAppContext,
    ) {
        assert_search_reveals_with_padding_after_manual_scroll(true, cx);
    }

    fn assert_search_reveals_with_padding_after_manual_scroll(
        previous: bool,
        cx: &mut TestAppContext,
    ) {
        let input_view = InputView::new(cx);
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;
        let text = (0..160)
            .map(|row| {
                if matches!(row, 20 | 60 | 100) {
                    format!("match on row {row}")
                } else {
                    format!("line {row}")
                }
            })
            .collect::<Vec<_>>()
            .join("\n");
        let start = text.match_indices("match").nth(1).unwrap().0;
        let expected_match = start..start + "match".len();
        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.set_cursor_surrounding_lines(Some(3), window, cx);
                state.set_value(text, window, cx);
                state.set_search_query("match", true, cx);
                if previous {
                    state.search_session.matcher.next();
                    state.search_session.matcher.next();
                }
            });
        });
        cx.run_until_parked();
        cx.update(|_, cx| {
            input.update(cx, |state, cx| {
                let line_height = state.last_layout.as_ref().unwrap().line_height;
                let y = if previous { px(0.) } else { -line_height * 80. };
                state.set_scroll_offset(point(px(0.), y), cx);
            });
        });
        cx.run_until_parked();
        input.read_with(&cx, |state, _| {
            let visible = state.visible_row_range().unwrap();
            if previous {
                assert!(visible.end <= 60, "target must be below the viewport");
            } else {
                assert!(visible.start > 60, "target must be above the viewport");
            }
        });
        cx.update(|_, cx| {
            input.update(cx, |state, cx| {
                let range = if previous {
                    state.previous_search_match(cx)
                } else {
                    state.next_search_match(cx)
                };
                assert_eq!(range, Some(expected_match));
                assert_eq!(state.search_session.matcher.label(), "2/3");
            });
        });
        cx.run_until_parked();
        input.read_with(&cx, |state, _| {
            assert!(state.visible_row_range().unwrap().contains(&60));
            let line_height = state.last_layout.as_ref().unwrap().line_height;
            let target_y = line_height * 60. + state.scroll_handle.offset().y;
            // Three lines of edge clearance include the matched line itself.
            assert!(target_y >= line_height * 2. - px(0.1));
            assert!(
                target_y + line_height * 3.
                    <= state.last_bounds.as_ref().unwrap().size.height + px(0.1),
                "search must preserve the configured surrounding-line padding"
            );
        });
    }

    /// A host that wants the search shortcut for its own search UI.
    struct SearchHost {
        editor: Entity<InputBaseState<EditorMode>>,
        search_requests: Rc<Cell<usize>>,
    }

    impl Render for SearchHost {
        fn render(&mut self, _: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
            let search_requests = self.search_requests.clone();
            div()
                .size_full()
                .on_action(cx.listener(move |_, _: &Search, _, _| {
                    search_requests.set(search_requests.get() + 1);
                }))
                .child(self.editor.clone())
        }
    }

    /// Opens an editor inside [`SearchHost`], focused, and presses the search
    /// shortcut once. Returns the editor and the host's request count.
    fn press_search_shortcut(
        cx: &mut TestAppContext,
        searchable: bool,
    ) -> (Entity<InputBaseState<EditorMode>>, Rc<Cell<usize>>) {
        let search_requests = Rc::new(Cell::new(0));
        let mut editor = None;
        let window = cx.update(|cx| {
            cx.open_window(Default::default(), |window, cx| {
                cx.set_global(Theme::default());
                super::super::init(cx);
                let state =
                    cx.new(|cx| crate::input::EditorState::new(window, cx).searchable(searchable));
                editor = Some(state.clone());
                cx.new(|_| SearchHost {
                    editor: state,
                    search_requests: search_requests.clone(),
                })
            })
            .unwrap()
        });
        let editor = editor.unwrap();
        let mut cx = VisualTestContext::from_window(window.into(), cx);
        cx.update(|window, cx| {
            editor.update(cx, |state, cx| state.focus(window, cx));
        });
        cx.run_until_parked();
        #[cfg(target_os = "macos")]
        cx.simulate_keystrokes("cmd-f");
        #[cfg(not(target_os = "macos"))]
        cx.simulate_keystrokes("ctrl-f");
        cx.run_until_parked();
        (editor, search_requests)
    }

    #[gpui::test]
    fn test_search_shortcut_reaches_the_host_when_not_searchable(cx: &mut TestAppContext) {
        let (editor, search_requests) = press_search_shortcut(cx, false);
        assert_eq!(search_requests.get(), 1);
        editor.read_with(cx, |state, _| {
            assert!(!state.search_session().open);
            assert!(!state.search_session().is_active());
        });
    }

    #[gpui::test]
    fn test_search_shortcut_opens_the_panel_when_searchable(cx: &mut TestAppContext) {
        let (editor, search_requests) = press_search_shortcut(cx, true);
        assert_eq!(search_requests.get(), 0);
        editor.read_with(cx, |state, _| {
            assert!(state.search_session().open);
            assert!(state.search_session().is_active());
        });
    }

    #[gpui::test]
    fn test_set_search_query_highlights_without_the_panel(cx: &mut TestAppContext) {
        let input_view = InputView::build_editor(cx, |state| state.searchable(false));
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;
        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.set_value("foo bar foo", window, cx);
                state.set_search_query("foo", true, cx);
            });
        });
        cx.run_until_parked();
        input.read_with(&cx, |state, _| {
            let session = state.search_session();
            assert!(session.is_active());
            assert!(!session.open);
            assert_eq!(session.matcher.len(), 2);
        });
        cx.update(|_, cx| {
            input.update(cx, |state, cx| state.close_search(cx));
        });
        input.read_with(&cx, |state, _| {
            assert!(!state.search_session().is_active());
        });
    }

    /// A closed search skips rescanning on edits, so every path that reads
    /// the matches again must see the edited text, not the text at close.
    #[gpui::test]
    fn test_closed_search_resyncs_matches_after_edits(cx: &mut TestAppContext) {
        let input_view = InputView::build_editor(cx, |state| state.searchable(false));
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;
        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.set_value("foo bar foo", window, cx);
                state.set_search_query("foo", true, cx);
                state.close_search(cx);

                state.set_value("bar foo", window, cx);
                assert_eq!(state.next_search_match(cx), Some(4..7));

                state.set_value("foo foo foo", window, cx);
                state.set_search_query("foo", true, cx);
                assert_eq!(state.search_session().matcher.len(), 3);
            });
        });
    }

    #[gpui::test]
    fn test_search_reveals_offscreen_wrapped_match(cx: &mut TestAppContext) {
        let input_view = InputView::new(cx);
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;
        let text = format!(
            "match\n{}\n{}match\n{}",
            "line\n".repeat(80),
            "wrapped text ".repeat(500),
            "line\n".repeat(80)
        );
        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.set_cursor_surrounding_lines(Some(3), window, cx);
                state.set_value(text, window, cx);
                state.set_search_query("match", true, cx);
            });
        });
        cx.run_until_parked();
        cx.update(|_, cx| {
            input.update(cx, |state, cx| {
                state.next_search_match(cx).unwrap();
            });
        });
        cx.run_until_parked();
        input.read_with(&cx, |state, _| {
            let range = state.search_session.matcher.matched_ranges()[1].clone();
            let layout = state.last_layout.as_ref().unwrap();
            let (_, _, position) = state.line_and_position_for_offset(range.end);
            let y = position.expect("wrapped match must be laid out").y
                + state.scroll_handle.offset().y;
            assert!(y >= layout.line_height * 2. - px(0.1));
            assert!(
                y + layout.line_height * 3. <= state.last_bounds.unwrap().size.height + px(0.1),
                "wrapped match must retain surrounding display rows"
            );
        });
    }

    #[gpui::test]
    fn test_number_step(cx: &mut TestAppContext) {
        let input = InputView::build(cx, |state| state).input;

        cx.update(|cx| {
            input.update(cx, |_state, cx| {
                assert_eq!(
                    NumberStep::from(5.).value(123., StepAction::Increment, cx),
                    5.
                );

                // The step can differ by direction at a boundary: at 1.0 it
                // is 0.1 going down and 0.5 going up.
                let step = NumberStep::by_value(|value, action, _cx| {
                    let below = match action {
                        StepAction::Increment => value < 1.0,
                        StepAction::Decrement => value <= 1.0,
                    };
                    if below { 0.1 } else { 0.5 }
                });
                assert_eq!(step.value(0.5, StepAction::Increment, cx), 0.1);
                assert_eq!(step.value(1.0, StepAction::Increment, cx), 0.5);
                assert_eq!(step.value(1.0, StepAction::Decrement, cx), 0.1);
                assert_eq!(step.value(2.0, StepAction::Decrement, cx), 0.5);
            });
        });
    }

    #[gpui::test]
    fn test_number_input_normalization(cx: &mut TestAppContext) {
        let input_view = InputView::build(cx, |state| {
            state.mask_pattern(MaskPattern::Number {
                separator: None,
                fraction: None,
            })
        });
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;

        // Full-width digits and the ideographic full stop are normalized,
        // and the cursor is at the end (in normalized bytes, not the
        // original 12 bytes).
        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.replace_text_in_range(None, "12。5", window, cx);
            });
        });
        cx.run_until_parked();
        cx.update(|_, cx| {
            input.read_with(cx, |state, _| {
                assert_eq!(state.value(), "12.5");
                let cursor: Range<usize> = state.selected_range();
                assert_eq!(cursor, 4..4);
            });
        });

        // Non-numeric input is rejected.
        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.replace_text_in_range(None, "abc", window, cx);
            });
        });
        cx.run_until_parked();
        cx.update(|_, cx| {
            input.read_with(cx, |state, _| {
                assert_eq!(state.value(), "12.5");
            });
        });

        // A bare leading dot is kept as-is (normalized from the ideographic
        // full stop), not completed to "0.", so it stays editable.
        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                let range = state.range_to_utf16(&(0..state.text.len()));
                state.replace_text_in_range(Some(range), "。", window, cx);
            });
        });
        cx.run_until_parked();
        cx.update(|_, cx| {
            input.read_with(cx, |state, _| {
                assert_eq!(state.value(), ".");
                let cursor: Range<usize> = state.selected_range();
                assert_eq!(cursor, 1..1);
            });
        });
    }

    #[gpui::test]
    fn test_mask_pattern_accepts_non_ascii_text(cx: &mut TestAppContext) {
        let input_view = InputView::build(cx, |state| state.mask_pattern("9999年99月"));
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.replace_text_in_range(None, "2024年12月", window, cx);
            });
        });
        cx.run_until_parked();
        cx.update(|_, cx| {
            input.read_with(cx, |state, _| {
                assert_eq!(state.value(), "2024年12月");
            });
        });
    }

    #[gpui::test]
    fn test_number_input_normalization_with_separator(cx: &mut TestAppContext) {
        let input_view = InputView::build(cx, |state| {
            state.mask_pattern(MaskPattern::Number {
                separator: Some(','),
                fraction: Some(2),
            })
        });
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.replace_text_in_range(None, "1234", window, cx);
            });
        });
        cx.run_until_parked();
        cx.update(|_, cx| {
            input.read_with(cx, |state, _| {
                assert_eq!(state.value(), "1,234");
                assert_eq!(state.unmask_value(), "1234");
            });
        });
    }

    #[gpui::test]
    fn test_number_input_clamp_on_blur(cx: &mut TestAppContext) {
        let input_view = InputView::build(cx, |state| {
            state
                .mask_pattern(MaskPattern::Number {
                    separator: None,
                    fraction: None,
                })
                .min(10.)
                .max(100.)
        });
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;

        // Out-of-range values are allowed while typing, and clamped on blur.
        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.replace_text_in_range(None, "1000", window, cx);
                assert_eq!(state.value(), "1000");
                state.clamp_number_value(window, cx);
                assert_eq!(state.value(), "100");

                let range = state.range_to_utf16(&(0..state.text.len()));
                state.replace_text_in_range(Some(range), "1", window, cx);
                assert_eq!(state.value(), "1");
                state.clamp_number_value(window, cx);
                assert_eq!(state.value(), "10");
            });
        });
    }

    #[gpui::test]
    fn test_number_input_undo_with_mask(cx: &mut TestAppContext) {
        let input_view = InputView::build(cx, |state| {
            state.mask_pattern(MaskPattern::Number {
                separator: Some(','),
                fraction: None,
            })
        });
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;

        // When the mask changes the text (regrouping separators), a
        // whole-document change is recorded, so undo/redo can restore it.
        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.replace_text_in_range(None, "1234", window, cx);
                assert_eq!(state.value(), "1,234");
                state.replace_text_in_range(None, "5", window, cx);
                assert_eq!(state.value(), "12,345");

                // Each whole-document mask rewrite is an atomic undo step.
                // Before the whole-document history fix, undo produced a
                // corrupted value like "1,2344".
                state.undo(&Undo, window, cx);
                assert_eq!(state.value(), "1,234");
                state.undo(&Undo, window, cx);
                assert_eq!(state.value(), "");
                state.redo(&Redo, window, cx);
                assert_eq!(state.value(), "1,234");
                state.redo(&Redo, window, cx);
                assert_eq!(state.value(), "12,345");
            });
        });
    }

    #[gpui::test]
    fn test_undo_manager_coalesces_adjacent_typing_transactions(cx: &mut TestAppContext) {
        let input_view = InputView::build(cx, |state| state);
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.replace_text_in_range(None, "a", window, cx);
                state.replace_text_in_range(None, "b", window, cx);
                assert_eq!(state.value(), "ab");

                state.undo(&Undo, window, cx);
                assert_eq!(state.value(), "");
            });
        });
    }

    #[gpui::test]
    fn test_undo_manager_cursor_movement_splits_typing(cx: &mut TestAppContext) {
        let input_view = InputView::build(cx, |state| state);
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.replace_text_in_range(None, "a", window, cx);
                state.replace_text_in_range(None, "b", window, cx);
                state.left(&MoveLeft, window, cx);
                state.replace_text_in_range(None, "x", window, cx);
                assert_eq!(state.value(), "axb");

                state.undo(&Undo, window, cx);
                assert_eq!(state.value(), "ab");
                state.undo(&Undo, window, cx);
                assert_eq!(state.value(), "");
            });
        });
    }

    #[gpui::test]
    fn test_undo_manager_splits_backward_and_forward_delete(cx: &mut TestAppContext) {
        let input_view = InputView::build(cx, |state| state);
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.set_value("abcd", window, cx);
                state.set_selected_range(2..2, cx);
                state.backspace(&Backspace, window, cx);
                state.delete(&Delete, window, cx);
                assert_eq!(state.value(), "ad");

                state.undo(&Undo, window, cx);
                assert_eq!(state.value(), "acd");
                state.undo(&Undo, window, cx);
                assert_eq!(state.value(), "abcd");
            });
        });
    }

    #[gpui::test]
    fn test_undo_manager_coalesces_directional_character_deletes(cx: &mut TestAppContext) {
        let input_view = InputView::build(cx, |state| state);
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.set_value("abcd", window, cx);
                state.backspace(&Backspace, window, cx);
                state.backspace(&Backspace, window, cx);
                assert_eq!(state.value(), "ab");
                state.undo(&Undo, window, cx);
                assert_eq!(state.value(), "abcd");
                assert_eq!(state.selected_range(), 4..4);

                state.set_value("abcd", window, cx);
                state.set_selected_range(1..1, cx);
                state.delete(&Delete, window, cx);
                state.delete(&Delete, window, cx);
                assert_eq!(state.value(), "ad");
                state.undo(&Undo, window, cx);
                assert_eq!(state.value(), "abcd");
                assert_eq!(state.selected_range(), 1..1);
            });
        });
    }

    #[gpui::test]
    fn test_undo_manager_atomic_paste_isolated_from_typing(cx: &mut TestAppContext) {
        let input_view = InputView::build(cx, |state| state);
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;

        cx.update(|window, cx| {
            cx.write_to_clipboard(ClipboardItem::new_string("P".to_string()));
            input.update(cx, |state, cx| {
                state.replace_text_in_range(None, "a", window, cx);
                state.paste(&Paste, window, cx);
                state.replace_text_in_range(None, "b", window, cx);
                assert_eq!(state.value(), "aPb");

                state.undo(&Undo, window, cx);
                assert_eq!(state.value(), "aP");
                state.undo(&Undo, window, cx);
                assert_eq!(state.value(), "a");
                state.undo(&Undo, window, cx);
                assert_eq!(state.value(), "");
            });
        });
    }

    #[gpui::test]
    fn test_undo_manager_programmatic_insert_is_atomic(cx: &mut TestAppContext) {
        let input_view = InputView::build(cx, |state| state);
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.replace_text_in_range(None, "a", window, cx);
                state.insert("P", window, cx);
                state.replace_text_in_range(None, "b", window, cx);
                assert_eq!(state.value(), "aPb");

                state.undo(&Undo, window, cx);
                assert_eq!(state.value(), "aP");
                state.undo(&Undo, window, cx);
                assert_eq!(state.value(), "a");
            });
        });
    }

    #[gpui::test]
    fn test_undo_manager_selection_round_trip_splits_typing(cx: &mut TestAppContext) {
        let input_view = InputView::build(cx, |state| state);
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.replace_text_in_range(None, "a", window, cx);
                state.replace_text_in_range(None, "b", window, cx);
                state.select_all(window, cx);
                state.unselect(window, cx);
                state.replace_text_in_range(None, "c", window, cx);

                state.undo(&Undo, window, cx);
                assert_eq!(state.value(), "ab");
                state.undo(&Undo, window, cx);
                assert_eq!(state.value(), "");
            });
        });
    }

    #[gpui::test]
    fn test_undo_manager_enter_is_atomic(cx: &mut TestAppContext) {
        let input_view = InputView::build_textarea(cx, |state| state);
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.replace_text_in_range(None, "a", window, cx);
                state.enter(
                    &Enter {
                        secondary: false,
                        shift: false,
                    },
                    window,
                    cx,
                );
                state.replace_text_in_range(None, "b", window, cx);

                state.undo(&Undo, window, cx);
                assert_eq!(state.value(), "a\n");
                state.undo(&Undo, window, cx);
                assert_eq!(state.value(), "a");
                state.undo(&Undo, window, cx);
                assert_eq!(state.value(), "");
            });
        });
    }

    #[gpui::test]
    fn test_undo_manager_single_line_return_commits_the_typing_session(cx: &mut TestAppContext) {
        let input_view = InputView::build(cx, |state| state);
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                for part in ["a", "b", "c"] {
                    state.replace_text_in_range(None, part, window, cx);
                }
                state.enter(
                    &Enter {
                        secondary: false,
                        shift: false,
                    },
                    window,
                    cx,
                );
                for part in ["d", "e", "f"] {
                    state.replace_text_in_range(None, part, window, cx);
                }
                assert_eq!(state.value(), "abcdef");

                state.undo(&Undo, window, cx);
                assert_eq!(state.value(), "abc");
                state.undo(&Undo, window, cx);
                assert_eq!(state.value(), "");
            });
        });
    }

    #[gpui::test]
    fn test_undo_manager_submit_on_enter_commits_the_textarea_session(cx: &mut TestAppContext) {
        let input_view = InputView::build_textarea(cx, |state| state.submit_on_enter(true));
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.replace_text_in_range(None, "before submit", window, cx);
                state.enter(
                    &Enter {
                        secondary: false,
                        shift: false,
                    },
                    window,
                    cx,
                );
                state.replace_text_in_range(None, " after submit", window, cx);
                assert_eq!(state.value(), "before submit after submit");

                state.undo(&Undo, window, cx);
                assert_eq!(state.value(), "before submit");
                state.undo(&Undo, window, cx);
                assert_eq!(state.value(), "");
            });
        });
    }

    #[gpui::test]
    fn test_undo_manager_blur_commits_the_typing_session(cx: &mut TestAppContext) {
        let input_view = InputView::build(cx, |state| state);
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.replace_text_in_range(None, "before blur", window, cx);
                state.on_blur(window, cx);
                state.on_focus(window, cx);
                state.replace_text_in_range(None, " after focus", window, cx);
                assert_eq!(state.value(), "before blur after focus");

                state.undo(&Undo, window, cx);
                assert_eq!(state.value(), "before blur");
                state.undo(&Undo, window, cx);
                assert_eq!(state.value(), "");
            });
        });
    }

    #[gpui::test]
    fn test_undo_manager_keeps_rapid_lines_in_distinct_transactions(cx: &mut TestAppContext) {
        let input_view = InputView::build_textarea(cx, |state| state);
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                let enter = Enter {
                    secondary: false,
                    shift: false,
                };
                state.replace_text_in_range(None, "a", window, cx);
                state.enter(&enter, window, cx);
                state.replace_text_in_range(None, "b", window, cx);
                state.enter(&enter, window, cx);
                state.replace_text_in_range(None, "c", window, cx);
                assert_eq!(state.value(), "a\nb\nc");

                for expected in ["a\nb\n", "a\nb", "a\n", "a", ""] {
                    state.undo(&Undo, window, cx);
                    assert_eq!(state.value(), expected);
                }
            });
        });
    }

    #[gpui::test]
    fn test_undo_manager_coalesces_long_unicode_typing_without_a_timer(cx: &mut TestAppContext) {
        let input_view = InputView::build_textarea(cx, |state| state);
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;
        let parts = [
            "The ",
            "quick ",
            "brown fox, ",
            "你好，世界 ",
            "🦀 jumps over 13 lazy dogs.",
        ];
        let expected = parts.concat();

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                for part in parts {
                    state.replace_text_in_range(None, part, window, cx);
                }
                assert_eq!(state.value(), expected);

                state.undo(&Undo, window, cx);
                assert_eq!(state.value(), "");
                state.redo(&Redo, window, cx);
                assert_eq!(state.value(), expected);
            });
        });
    }

    #[gpui::test]
    fn test_undo_manager_long_multiline_sequence_has_structural_boundaries(
        cx: &mut TestAppContext,
    ) {
        let input_view = InputView::build_textarea(cx, |state| state);
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;
        let enter = Enter {
            secondary: false,
            shift: false,
        };

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                for (index, line) in [
                    "first line with punctuation!",
                    "第二行包含 Unicode 🦀",
                    "third line has several words",
                ]
                .into_iter()
                .enumerate()
                {
                    for chunk in line.split_inclusive(' ') {
                        state.replace_text_in_range(None, chunk, window, cx);
                    }
                    if index < 2 {
                        state.enter(&enter, window, cx);
                    }
                }

                assert_eq!(
                    state.value(),
                    "first line with punctuation!\n第二行包含 Unicode 🦀\nthird line has several words"
                );
                state.undo(&Undo, window, cx);
                assert_eq!(
                    state.value(),
                    "first line with punctuation!\n第二行包含 Unicode 🦀\n"
                );
                state.undo(&Undo, window, cx);
                assert_eq!(
                    state.value(),
                    "first line with punctuation!\n第二行包含 Unicode 🦀"
                );
                state.undo(&Undo, window, cx);
                assert_eq!(state.value(), "first line with punctuation!\n");
            });
        });
    }

    #[gpui::test]
    fn test_masked_input_keeps_its_value_out_of_the_clipboard(cx: &mut TestAppContext) {
        let input_view = InputView::build(cx, |state| state);
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.set_value("hunter2", window, cx);
                state.set_masked(true, window, cx);
                state.select_all(window, cx);
                cx.write_to_clipboard(ClipboardItem::new_string("sentinel".into()));

                state.copy(&Copy, window, cx);
                assert_eq!(
                    cx.read_from_clipboard().and_then(|item| item.text()),
                    Some("sentinel".to_string())
                );

                // Cut neither copies nor deletes.
                state.cut(&Cut, window, cx);
                assert_eq!(state.value(), "hunter2");
                assert_eq!(
                    cx.read_from_clipboard().and_then(|item| item.text()),
                    Some("sentinel".to_string())
                );

                // Revealing the value restores both.
                state.set_masked(false, window, cx);
                state.copy(&Copy, window, cx);
                assert_eq!(
                    cx.read_from_clipboard().and_then(|item| item.text()),
                    Some("hunter2".to_string())
                );
            });
        });
    }

    #[gpui::test]
    fn test_masked_input_collapses_word_boundaries(cx: &mut TestAppContext) {
        let input_view = InputView::build(cx, |state| state);
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.set_value("aaa bbb ccc", window, cx);
                state.set_masked(true, window, cx);
                state.set_selected_range(7..7, cx);

                // The mask hides word boundaries, so a word delete takes
                // everything before the caret and leaves the rest.
                state.delete_previous_word(&DeleteToPreviousWordStart, window, cx);
                assert_eq!(state.value(), " ccc");
                assert_eq!(state.selected_range(), 0..0);

                state.delete_next_word(&DeleteToNextWordEnd, window, cx);
                assert_eq!(state.value(), "");

                // A double click takes the whole value, not one word.
                state.set_value("aaa bbb ccc", window, cx);
                state.select_word(9, window, cx);
                assert_eq!(state.selected_range(), 0..11);

                // Unmasked, the same delete only takes one word.
                state.set_masked(false, window, cx);
                state.set_value("aaa bbb ccc", window, cx);
                state.set_selected_range(11..11, cx);
                state.delete_previous_word(&DeleteToPreviousWordStart, window, cx);
                assert_eq!(state.value(), "aaa bbb ");

                state.set_value("aaa bbb ccc", window, cx);
                state.select_word(9, window, cx);
                assert_eq!(state.selected_range(), 8..11);
            });
        });
    }

    #[gpui::test]
    fn test_masked_input_disables_the_copy_context_menu_items(cx: &mut TestAppContext) {
        let input_view = InputView::build(cx, |state| state);
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.set_value("hunter2", window, cx);
                state.select_all(window, cx);
                assert!(state.context_menu_capabilities().is_copyable());

                state.set_masked(true, window, cx);
                let capabilities = state.context_menu_capabilities();
                assert!(capabilities.is_masked());
                assert!(capabilities.has_selection());
                assert!(!capabilities.is_copyable());
            });
        });
    }

    #[gpui::test]
    fn test_undo_manager_cut_and_repeated_pastes_are_distinct_transactions(
        cx: &mut TestAppContext,
    ) {
        let input_view = InputView::build(cx, |state| state);
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.replace_text_in_range(None, "alpha beta gamma", window, cx);
                state.set_selected_range(6..10, cx);
                state.cut(&Cut, window, cx);
                assert_eq!(state.value(), "alpha  gamma");

                state.paste(&Paste, window, cx);
                state.paste(&Paste, window, cx);
                assert_eq!(state.value(), "alpha betabeta gamma");

                state.undo(&Undo, window, cx);
                assert_eq!(state.value(), "alpha beta gamma");
                state.undo(&Undo, window, cx);
                assert_eq!(state.value(), "alpha  gamma");
                state.undo(&Undo, window, cx);
                assert_eq!(state.value(), "alpha beta gamma");
            });
        });
    }

    #[gpui::test]
    fn test_undo_manager_word_and_line_deletes_do_not_coalesce(cx: &mut TestAppContext) {
        let input_view = InputView::build_textarea(cx, |state| state);
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.set_value("one two three\nfour five", window, cx);
                state.set_selected_range(13..13, cx);
                state.delete_previous_word(&DeleteToPreviousWordStart, window, cx);
                assert_eq!(state.value(), "one two \nfour five");
                state.delete_to_end_of_line(&DeleteToEndOfLine, window, cx);
                assert_eq!(state.value(), "one two four five");

                state.undo(&Undo, window, cx);
                assert_eq!(state.value(), "one two \nfour five");
                state.undo(&Undo, window, cx);
                assert_eq!(state.value(), "one two three\nfour five");
            });
        });
    }

    #[gpui::test]
    fn test_undo_manager_multiline_replacement_is_one_atomic_transaction(cx: &mut TestAppContext) {
        let input_view = InputView::build_textarea(cx, |state| state);
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.replace_text_in_range(None, "before", window, cx);
                state.set_selected_range(0..6, cx);
                state.replace_text_in_range(None, "line one\nline two\n第三行", window, cx);
                assert_eq!(state.value(), "line one\nline two\n第三行");

                state.undo(&Undo, window, cx);
                assert_eq!(state.value(), "before");
                assert_eq!(state.selected_range(), 0..6);
                state.redo(&Redo, window, cx);
                assert_eq!(state.value(), "line one\nline two\n第三行");
            });
        });
    }

    #[gpui::test]
    fn test_undo_manager_composition_isolated_from_long_typing(cx: &mut TestAppContext) {
        let input_view = InputView::build(cx, |state| state);
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.replace_text_in_range(None, "prefix ", window, cx);
                state.replace_and_mark_text_in_range(None, "n", None, window, cx);
                state.replace_and_mark_text_in_range(None, "ni", None, window, cx);
                state.replace_and_mark_text_in_range(None, "你", None, window, cx);
                state.unmark_text(window, cx);
                state.replace_text_in_range(None, " suffix", window, cx);
                assert_eq!(state.value(), "prefix 你 suffix");

                state.undo(&Undo, window, cx);
                assert_eq!(state.value(), "prefix 你");
                state.undo(&Undo, window, cx);
                assert_eq!(state.value(), "prefix ");
                state.undo(&Undo, window, cx);
                assert_eq!(state.value(), "");
            });
        });
    }

    #[gpui::test]
    fn test_undo_manager_selected_replacement_is_atomic(cx: &mut TestAppContext) {
        let input_view = InputView::build(cx, |state| state);
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.replace_text_in_range(None, "abc", window, cx);
                state.set_selected_range(1..2, cx);
                state.replace_text_in_range(None, "X", window, cx);
                state.replace_text_in_range(None, "z", window, cx);
                assert_eq!(state.value(), "aXzc");

                state.undo(&Undo, window, cx);
                assert_eq!(state.value(), "aXc");
                state.undo(&Undo, window, cx);
                assert_eq!(state.value(), "abc");
                state.undo(&Undo, window, cx);
                assert_eq!(state.value(), "");
            });
        });
    }

    #[gpui::test]
    fn test_number_input_leading_dot_editable(cx: &mut TestAppContext) {
        let input_view = InputView::build(cx, |state| {
            state.mask_pattern(MaskPattern::Number {
                separator: None,
                fraction: None,
            })
        });
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.replace_text_in_range(None, "1.2", window, cx);

                // Delete the integer part "1": the value keeps the leading dot
                // (".2"), not completed to "0.2", so the digits before the dot
                // stay editable.
                let range = state.range_to_utf16(&(0..1));
                state.replace_text_in_range(Some(range), "", window, cx);
                assert_eq!(state.value(), ".2");
                let cursor: Range<usize> = state.selected_range();
                assert_eq!(cursor, 0..0);

                // The user can type a new integer part.
                state.replace_text_in_range(Some(0..0), "3", window, cx);
                assert_eq!(state.value(), "3.2");
            });
        });
    }

    #[gpui::test]
    fn test_number_input_escape_invalid_text(cx: &mut TestAppContext) {
        // A pre-existing invalid text (e.g. a `default_value` that does not
        // conform) must not trap the user, the edit is allowed to fix it.
        let input_view = InputView::build(cx, |state| {
            state
                .mask_pattern(MaskPattern::Number {
                    separator: None,
                    fraction: None,
                })
                .default_value("1,234")
        });
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                // Delete the last char, the pending text "1,23" is still
                // invalid, but the edit is allowed since the old text was
                // already invalid.
                let range = state.range_to_utf16(&(4..5));
                state.replace_text_in_range(Some(range), "", window, cx);
                assert_eq!(state.value(), "1,23");

                // Once the text becomes valid, the validation works as usual.
                let range = state.range_to_utf16(&(1..2));
                state.replace_text_in_range(Some(range), "", window, cx);
                assert_eq!(state.value(), "123");
                state.replace_text_in_range(None, "a", window, cx);
                assert_eq!(state.value(), "123");
            });
        });
    }

    /// After `set_value` on a single-line input the caret sits at the end (like
    /// HTML `<input>`), yet the view is scrolled back to the start so a long
    /// value shows its beginning instead of its tail.
    #[gpui::test]
    fn test_set_value_single_line_caret_at_end_view_at_start(cx: &mut TestAppContext) {
        let input_view = InputView::build(cx, |state| state);
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;

        // Long enough to overflow any reasonable single-line input width.
        let value = format!("https://example.com/v1/users?{}", "x=1&".repeat(120));
        let len = value.len();

        // Right after `set_value`, before the next paint consumes the deferred
        // offset: caret is at the end, and the view is forced back to the start.
        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.set_value(value.clone(), window, cx);

                assert_eq!(
                    state.selected_range(),
                    len..len,
                    "single-line caret should be at the end after set_value"
                );
                assert_eq!(
                    state.deferred_scroll_offset,
                    Some(point(px(0.), px(0.))),
                    "the view should be forced back to the start"
                );
            });
        });

        // After a paint, the steady-state view stays at the start (x == 0) even
        // though the caret is at the far end.
        cx.run_until_parked();
        cx.update(|_, cx| {
            input.read_with(cx, |state, _| {
                assert!(
                    state.scroll_size.width > state.input_bounds.size.width,
                    "value must overflow the input width or this test is vacuous"
                );
                assert_eq!(
                    state.scroll_handle.offset().x,
                    px(0.),
                    "long value should display from its start, not its tail"
                );
            });
        });
    }

    /// `replace_all` on a single-line input replaces the text, puts the
    /// caret at the end, and — like `set_value` — snaps the view back to the
    /// start so a long value shows its beginning instead of its tail.
    #[gpui::test]
    fn test_replace_all_single_line(cx: &mut TestAppContext) {
        let input_view = InputView::build(cx, |state| state);
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;

        // Long enough to overflow any reasonable single-line input width.
        let value = format!("https://example.com/v1/users?{}", "x=1&".repeat(120));
        let len = value.len();

        // Right after `replace_all`, before the next paint consumes the
        // deferred offset: caret is at the end, and the view is forced back
        // to the start.
        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.set_value("hello", window, cx);
                state.replace_all(value.clone(), window, cx);
                assert_eq!(state.value(), value);
                assert_eq!(
                    state.selected_range(),
                    len..len,
                    "single-line caret should be at the end after replace_all"
                );
                assert_eq!(
                    state.scroll_handle.offset(),
                    point(px(0.), px(0.)),
                    "the scroll offset should be reset to the start"
                );
                assert_eq!(
                    state.deferred_scroll_offset,
                    Some(point(px(0.), px(0.))),
                    "single-line should set a deferred scroll offset to keep the start visible"
                );
            });
        });

        // After a paint, the steady-state view stays at the start (x == 0)
        // even though the caret is at the far end.
        cx.run_until_parked();
        cx.update(|_, cx| {
            input.read_with(cx, |state, _| {
                assert!(
                    state.scroll_size.width > state.input_bounds.size.width,
                    "value must overflow the input width or this test is vacuous"
                );
                assert_eq!(
                    state.scroll_handle.offset().x,
                    px(0.),
                    "long value should display from its start, not its tail"
                );
            });
        });
    }

    #[gpui::test]
    fn test_single_line_removes_newlines(cx: &mut TestAppContext) {
        let input_view = InputView::build(cx, |state| state.default_value("default\nvalue"));
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                assert_eq!(state.value(), "defaultvalue");

                state.set_value("first\nsecond\r\nthird\rfourth", window, cx);
                assert_eq!(state.value(), "firstsecondthirdfourth");

                state.set_value("", window, cx);
                state.insert("a\nb", window, cx);
                assert_eq!(state.value(), "ab");
            });

            cx.write_to_clipboard(ClipboardItem::new_string("a\r\nb\nc\rd".to_string()));
            input.update(cx, |state, cx| {
                state.set_value("", window, cx);
                state.paste(&Paste, window, cx);
                assert_eq!(state.value(), "abcd");
            });
        });

        cx.run_until_parked();
    }

    /// `replace_all` on a multi-line (non-code-editor) input clears the
    /// selection to `0..0` and resets the scroll offset, but does not set a
    /// deferred scroll offset (single-line only).
    #[gpui::test]
    fn test_replace_all_multi_line(cx: &mut TestAppContext) {
        let input_view = InputView::build_textarea(cx, |state| state);
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.set_value("foo\nbar", window, cx);
                state.replace_all("baz\nqux", window, cx);
                assert_eq!(state.value(), "baz\nqux");
                assert_eq!(
                    state.selected_range(),
                    0..0,
                    "multi-line selection should be cleared after replace_all"
                );
                assert_eq!(
                    state.scroll_handle.offset(),
                    point(px(0.), px(0.)),
                    "the scroll offset should be reset to the start"
                );
                assert!(
                    state.deferred_scroll_offset.is_none(),
                    "multi-line should not set a deferred scroll offset"
                );
            });
        });
    }

    /// Unlike `set_value`, `replace_all` records the change so the user can
    /// undo it back to the previous text and redo to the new text.
    #[gpui::test]
    fn test_replace_all_preserves_undo_history(cx: &mut TestAppContext) {
        let input_view = InputView::build(cx, |state| state);
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                // Seed with a value and clear history so the baseline is clean.
                state.set_value("first", window, cx);
                assert!(
                    !state.undo_manager.has_undos(),
                    "history should be empty after set_value"
                );

                // replace_all records a single undoable change.
                state.replace_all("second", window, cx);
                assert_eq!(state.value(), "second");
                assert!(
                    state.undo_manager.has_undos(),
                    "replace_all should record an undo step"
                );

                // Undo restores the previous text.
                state.undo(&Undo, window, cx);
                assert_eq!(state.value(), "first");

                // Redo reapplies the replacement.
                state.redo(&Redo, window, cx);
                assert_eq!(state.value(), "second");
            });
        });
    }

    /// `replace_all` on a code editor marks a pending update and resets LSP
    /// state, so diagnostics/completions refresh against the new text.
    #[gpui::test]
    fn test_replace_all_code_editor(cx: &mut TestAppContext) {
        let input_view = InputView::new(cx);
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                // Plant a pending-update flag and some LSP state to verify reset.
                state.set_value("select 1", window, cx);
                state._pending_update = false;

                state.replace_all("select 2", window, cx);
                assert_eq!(state.value(), "select 2");
                assert!(
                    state._pending_update,
                    "replace_all on a code editor should request a pending update"
                );
            });
        });
    }

    #[gpui::test]
    fn test_set_selected_range(cx: &mut TestAppContext) {
        let input_view = InputView::build(cx, |state| state.default_value("hello world"));
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;

        cx.update(|_, cx| {
            input.update(cx, |s, cx| {
                s.set_selected_range(0..5, cx);
                assert_eq!(s.selected_range(), 0..5);
                assert_eq!(s.selected_text().to_string(), "hello");

                s.set_selected_range(6..11, cx);
                assert_eq!(s.selected_text().to_string(), "world");

                // clamped + collapsed
                s.set_selected_range(100..100, cx);
                assert_eq!(s.selected_range(), 11..11);
            });
        });
    }

    /// A single-edit batch round-trips through undo/redo.
    #[gpui::test]
    fn test_replace_text_in_ranges_single_edit(cx: &mut TestAppContext) {
        let input_view = InputView::build_textarea(cx, |state| state.default_value("hello world"));
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;

        cx.update(|window, cx| {
            input.update(cx, |s, cx| {
                s.replace_text_in_ranges(&[(0..5, "HELLO".to_string())], window, cx);
                assert_eq!(s.value(), "HELLO world");

                s.undo(&Undo, window, cx);
                assert_eq!(s.value(), "hello world");

                s.redo(&Redo, window, cx);
                assert_eq!(s.value(), "HELLO world");
            });
        });
    }

    /// A single undo restores the exact original text and a single redo
    /// re-applies all edits, verifying the back-to-front application ordering.
    #[gpui::test]
    fn test_replace_text_in_ranges_multi_edit_transaction(cx: &mut TestAppContext) {
        let input_view = InputView::build_textarea(cx, |state| state.default_value("aaa bbb ccc"));
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;

        cx.update(|window, cx| {
            input.update(cx, |s, cx| {
                // Two edits at different positions, given in pre-edit
                // coordinates and in arbitrary (non-sorted) order.
                s.replace_text_in_ranges(
                    &[(0..3, "X".to_string()), (8..11, "Y".to_string())],
                    window,
                    cx,
                );
                assert_eq!(s.value(), "X bbb Y");

                // One collapsed cursor per edit, at the end of each inserted text.
                let cursors: Vec<usize> =
                    s.selections.iter().map(|sel| sel.cursor_offset()).collect();
                assert_eq!(cursors, vec![1, 7]);

                // The whole batch is a single undo transaction.
                assert_eq!(s.undo_manager.undo_count(), 1);

                // One undo restores the exact original text.
                s.undo(&Undo, window, cx);
                assert_eq!(s.value(), "aaa bbb ccc");

                // One redo re-applies all edits.
                s.redo(&Redo, window, cx);
                assert_eq!(s.value(), "X bbb Y");
            });
        });
    }

    /// A multi-edit change reaches the highlighter once, with every edit in
    /// application order and the text right after each, which is what the
    /// default `update_batch` replays through `update` one edit at a time.
    #[gpui::test]
    fn test_replace_text_in_ranges_drives_the_highlighter_once(cx: &mut TestAppContext) {
        use crate::input::{FoldRange, HighlightStyleResolver, InputEdit, InputHighlighter};
        use gpui::HighlightStyle;
        use std::cell::RefCell;

        struct RecordingHighlighter(Rc<RefCell<Vec<Vec<String>>>>);

        impl InputHighlighter for RecordingHighlighter {
            fn language(&self) -> SharedString {
                "recording".into()
            }

            fn update(
                &mut self,
                _: Option<InputEdit>,
                text: &Rope,
                _: bool,
                _: &mut Window,
                _: &mut Context<EditorState>,
            ) {
                self.0.borrow_mut().push(vec![text.to_string()]);
            }

            fn update_batch(
                &mut self,
                edits: &[(InputEdit, Rope)],
                _: bool,
                _: &mut Window,
                _: &mut Context<EditorState>,
            ) {
                let texts = edits.iter().map(|(_, text)| text.to_string()).collect();
                self.0.borrow_mut().push(texts);
            }

            fn styles(
                &self,
                range: &Range<usize>,
                _: &dyn HighlightStyleResolver,
            ) -> Vec<(Range<usize>, HighlightStyle)> {
                vec![(range.clone(), HighlightStyle::default())]
            }

            fn fold_ranges(&self, _: &Rope) -> Vec<FoldRange> {
                Vec::new()
            }
        }

        let updates = Rc::new(RefCell::new(Vec::new()));
        let input_view = InputView::new(cx);
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;

        cx.update(|window, cx| {
            input.update(cx, |s, cx| {
                s.set_value("aaa bbb ccc", window, cx);
                let recorded = updates.clone();
                s.set_highlighter_factory(
                    Rc::new(move |_: &str| {
                        let highlighter: Box<dyn InputHighlighter> =
                            Box::new(RecordingHighlighter(recorded.clone()));
                        Some(highlighter)
                    }),
                    cx,
                );
                s.replace_text_in_ranges(
                    &[(0..3, "X".to_string()), (8..11, "Y".to_string())],
                    window,
                    cx,
                );
            });
        });

        assert_eq!(
            *updates.borrow(),
            vec![vec!["aaa bbb Y".to_string(), "X bbb Y".to_string()]]
        );
    }

    /// One keypress records a single edit with the text right after it.
    #[gpui::test]
    fn test_last_input_edits_single_insert(cx: &mut TestAppContext) {
        let input_view = InputView::build_textarea(cx, |state| state.default_value("hello world"));
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.replace_text_in_ranges(&[(5..5, " big".to_string())], window, cx);

                let edits = state.last_input_edits.as_slice();
                assert_eq!(edits.len(), 1);
                let (edit, text_after) = &edits[0];
                assert_eq!(edit.start_byte, 5);
                assert_eq!(edit.old_end_byte, 5);
                assert_eq!(edit.new_end_byte, 9);
                assert_eq!(edit.start_position, crate::input::Point::new(0, 5));
                assert_eq!(edit.old_end_position, crate::input::Point::new(0, 5));
                assert_eq!(edit.new_end_position, crate::input::Point::new(0, 9));
                assert_eq!(text_after.to_string(), "hello big world");
            });
        });
    }

    /// Deletion and a multi-line paste each describe their whole replacement.
    #[gpui::test]
    fn test_last_input_edits_delete_and_paste(cx: &mut TestAppContext) {
        let input_view = InputView::build_textarea(cx, |state| state.default_value("hello world"));
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.replace_text_in_ranges(&[(5..11, String::new())], window, cx);
                assert_eq!(state.value(), "hello");

                let edits = state.last_input_edits.as_slice();
                assert_eq!(edits.len(), 1);
                let (edit, text_after) = &edits[0];
                assert_eq!(edit.start_byte, 5);
                assert_eq!(edit.old_end_byte, 11);
                assert_eq!(edit.new_end_byte, 5);
                assert_eq!(text_after.to_string(), "hello");

                state.replace_text_in_ranges(&[(5..5, "\nnext".to_string())], window, cx);
                assert_eq!(state.value(), "hello\nnext");

                let edits = state.last_input_edits.as_slice();
                assert_eq!(edits.len(), 1);
                let (edit, text_after) = &edits[0];
                assert_eq!(edit.start_byte, 5);
                assert_eq!(edit.old_end_byte, 5);
                assert_eq!(edit.new_end_byte, 10);
                assert_eq!(edit.start_position, crate::input::Point::new(0, 5));
                assert_eq!(edit.old_end_position, crate::input::Point::new(0, 5));
                assert_eq!(edit.new_end_position, crate::input::Point::new(1, 4));
                assert_eq!(text_after.to_string(), "hello\nnext");
            });
        });
    }

    /// A grouped change records every applied edit in application order.
    #[gpui::test]
    fn test_last_input_edits_grouped_change(cx: &mut TestAppContext) {
        let input_view = InputView::build_textarea(cx, |state| state.default_value("aaa bbb ccc"));
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.replace_text_in_ranges(
                    &[(0..3, "X".to_string()), (8..11, "Y".to_string())],
                    window,
                    cx,
                );
                assert_eq!(state.value(), "X bbb Y");

                let edits = state.last_input_edits.as_slice();
                assert_eq!(edits.len(), 2);
                // The higher offset is applied first, before the lower one.
                assert_eq!(edits[0].0.start_byte, 8);
                assert_eq!(edits[0].0.old_end_byte, 11);
                assert_eq!(edits[0].0.new_end_byte, 9);
                assert_eq!(edits[0].0.start_position, crate::input::Point::new(0, 8));
                assert_eq!(edits[0].0.old_end_position, crate::input::Point::new(0, 11));
                assert_eq!(edits[0].0.new_end_position, crate::input::Point::new(0, 9));
                assert_eq!(edits[0].1.to_string(), "aaa bbb Y");

                assert_eq!(edits[1].0.start_byte, 0);
                assert_eq!(edits[1].0.old_end_byte, 3);
                assert_eq!(edits[1].0.new_end_byte, 1);
                assert_eq!(edits[1].0.start_position, crate::input::Point::new(0, 0));
                assert_eq!(edits[1].0.old_end_position, crate::input::Point::new(0, 3));
                assert_eq!(edits[1].0.new_end_position, crate::input::Point::new(0, 1));
                assert_eq!(edits[1].1.to_string(), "X bbb Y");
            });
        });
    }

    /// Edits are recorded even when no highlighter can be installed.
    #[gpui::test]
    fn test_last_input_edits_without_a_highlighter(cx: &mut TestAppContext) {
        let input_view = InputView::new(cx);
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.set_value("fn main() {}", window, cx);
                let no_highlighter: InputHighlighterFactory = Rc::new(|_: &str| None);
                state.set_highlighter_factory(no_highlighter, cx);
                assert!(state.last_input_edits.as_slice().is_empty());

                state.replace_text_in_ranges(&[(12..12, "\n".to_string())], window, cx);
                assert_eq!(state.value(), "fn main() {}\n");

                let edits = state.last_input_edits.as_slice();
                assert_eq!(edits.len(), 1);
                let (edit, text_after) = &edits[0];
                assert_eq!(edit.start_byte, 12);
                assert_eq!(edit.old_end_byte, 12);
                assert_eq!(edit.new_end_byte, 13);
                assert_eq!(edit.start_position, crate::input::Point::new(0, 12));
                assert_eq!(edit.old_end_position, crate::input::Point::new(0, 12));
                assert_eq!(edit.new_end_position, crate::input::Point::new(1, 0));
                assert_eq!(text_after.to_string(), "fn main() {}\n");
            });
        });
    }

    /// `set_value` is silent and leaves no edits behind for the next change.
    #[gpui::test]
    fn test_last_input_edits_cleared_by_set_value(cx: &mut TestAppContext) {
        let input_view = InputView::build_textarea(cx, |state| state.default_value("hello"));
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.replace_text_in_ranges(&[(5..5, "!".to_string())], window, cx);
                assert_eq!(state.last_input_edits.as_slice().len(), 1);

                state.set_value("replaced", window, cx);
                assert!(state.last_input_edits.as_slice().is_empty());

                state.replace_text_in_ranges(&[(8..8, "?".to_string())], window, cx);
                let edits = state.last_input_edits.as_slice();
                assert_eq!(edits.len(), 1);
                assert_eq!(edits[0].1.to_string(), "replaced?");
            });
        });
    }

    /// Apply an emitted batch as an incremental consumer would and verify every snapshot.
    fn replay_input_edits(text: &mut String, event: &InputEditsEvent) {
        for (edit, after) in event.edits() {
            let replacement = after.slice(edit.start_byte..edit.new_end_byte).to_string();
            text.replace_range(edit.start_byte..edit.old_end_byte, &replacement);
            assert_eq!(*text, after.to_string());
        }
    }

    #[gpui::test]
    fn input_edits_events_preserve_queued_changes_and_undo(cx: &mut TestAppContext) {
        let view = InputView::build_textarea(cx, |state| state.default_value("hello"));
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        let input = view.input;
        let observed = Rc::new(std::cell::RefCell::new(Vec::<InputEditsEvent>::new()));
        let seen = observed.clone();
        let _subscription = cx.update(|_, cx| {
            cx.subscribe(&input, move |_, event: &InputEditsEvent, _| {
                seen.borrow_mut().push(event.clone());
            })
        });
        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.replace_text_in_ranges(&[(5..5, "!".into())], window, cx);
                state.replace_text_in_ranges(&[(6..6, "?".into())], window, cx);
                state.undo(&Undo, window, cx);
            });
        });
        let events = observed.borrow();
        assert!(events.len() >= 3);
        let mut text = "hello".to_string();
        for event in events.iter() {
            replay_input_edits(&mut text, event);
        }
        assert_eq!(
            text,
            input.read_with(&cx, |state, _| state.value().to_string())
        );
        assert_eq!(events[0].edits()[0].1.to_string(), "hello!");
        assert_eq!(events[1].edits()[0].1.to_string(), "hello!?");
    }

    #[gpui::test]
    fn input_edits_event_replays_ime_commit(cx: &mut TestAppContext) {
        let view = InputView::build_textarea(cx, |state| state.default_value(""));
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        let input = view.input;
        let observed = Rc::new(std::cell::RefCell::new(Vec::<InputEditsEvent>::new()));
        let seen = observed.clone();
        let _subscription = cx.update(|_, cx| {
            cx.subscribe(&input, move |_, event: &InputEditsEvent, _| {
                seen.borrow_mut().push(event.clone());
            })
        });
        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.replace_and_mark_text_in_range(None, "n", Some(1..1), window, cx);
                state.replace_and_mark_text_in_range(None, "ni", Some(2..2), window, cx);
                state.replace_text_in_range(None, "你", window, cx);
            });
        });
        let events = observed.borrow();
        assert_eq!(events.len(), 1);
        let mut text = String::new();
        replay_input_edits(&mut text, &events[0]);
        assert_eq!(text, "你");
    }

    #[gpui::test]
    fn input_edits_event_replays_after_cancelled_composition(cx: &mut TestAppContext) {
        let view = InputView::build_textarea(cx, |state| state.default_value(""));
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        let input = view.input;
        let observed = Rc::new(std::cell::RefCell::new(Vec::<InputEditsEvent>::new()));
        let seen = observed.clone();
        let _subscription = cx.update(|_, cx| {
            cx.subscribe(&input, move |_, event: &InputEditsEvent, _| {
                seen.borrow_mut().push(event.clone());
            })
        });
        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.replace_and_mark_text_in_range(None, "n", Some(1..1), window, cx);
                state.replace_and_mark_text_in_range(None, "", None, window, cx);
                state.replace_text_in_range(None, "x", window, cx);
            });
        });
        let events = observed.borrow();
        assert_eq!(events.len(), 1);
        let mut text = String::new();
        replay_input_edits(&mut text, &events[0]);
        assert_eq!(text, "x");
    }

    #[gpui::test]
    fn input_edits_event_replays_mask_rewrite(cx: &mut TestAppContext) {
        let view = InputView::build(cx, |state| {
            state
                .mask_pattern(MaskPattern::Number {
                    separator: Some(','),
                    fraction: None,
                })
                .default_value("999")
        });
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        let input = view.input;
        let observed = Rc::new(std::cell::RefCell::new(Vec::<InputEditsEvent>::new()));
        let seen = observed.clone();
        let _subscription = cx.update(|_, cx| {
            cx.subscribe(&input, move |_, event: &InputEditsEvent, _| {
                seen.borrow_mut().push(event.clone());
            })
        });
        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.set_cursor_to(3);
                state.replace_text_in_range(None, "9", window, cx)
            });
        });
        let events = observed.borrow();
        assert_eq!(events.len(), 1);
        let mut text = "999".to_string();
        replay_input_edits(&mut text, &events[0]);
        assert_eq!(text, "9,999");
    }

    /// An IME composition (marking then commit) undoes as a single unit.
    #[gpui::test]
    fn test_ime_composition_undoes_as_one_unit(cx: &mut TestAppContext) {
        let input_view = InputView::build_textarea(cx, |state| state.default_value(""));
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;

        cx.update(|window, cx| {
            input.update(cx, |s, cx| {
                // Simulate an IME composition: mark, refine, then commit.
                s.replace_and_mark_text_in_range(None, "n", Some(1..1), window, cx);
                s.replace_and_mark_text_in_range(None, "ni", Some(2..2), window, cx);
                s.replace_text_in_range(None, "你", window, cx);
                assert_eq!(s.value(), "你");

                // The entire composition is one undo transaction.
                assert_eq!(s.undo_manager.undo_count(), 1);

                s.undo(&Undo, window, cx);
                assert_eq!(s.value(), "");

                s.redo(&Redo, window, cx);
                assert_eq!(s.value(), "你");
            });
        });
    }

    /// A keystroke right after a committed composition must be its own undo
    /// entry, not merged into the (finalized) composition transaction.
    #[gpui::test]
    fn test_edit_after_composition_is_separate_undo(cx: &mut TestAppContext) {
        let input_view = InputView::build_textarea(cx, |state| state.default_value(""));
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;

        cx.update(|window, cx| {
            input.update(cx, |s, cx| {
                s.replace_and_mark_text_in_range(None, "n", Some(1..1), window, cx);
                s.replace_text_in_range(None, "你", window, cx);
                assert_eq!(s.value(), "你");
                assert_eq!(s.undo_manager.undo_count(), 1);

                // Typing after the commit is a distinct transaction.
                s.replace_text_in_range(None, "x", window, cx);
                assert_eq!(s.value(), "你x");
                assert_eq!(s.undo_manager.undo_count(), 2);

                s.undo(&Undo, window, cx);
                assert_eq!(s.value(), "你");
                s.undo(&Undo, window, cx);
                assert_eq!(s.value(), "");
            });
        });
    }

    /// Canceling a composition via `unmark_text` closes its transaction so it
    /// does not leak and swallow a later edit.
    #[gpui::test]
    fn test_composition_cancel_via_unmark_does_not_leak(cx: &mut TestAppContext) {
        let input_view = InputView::build_textarea(cx, |state| state.default_value(""));
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;

        cx.update(|window, cx| {
            input.update(cx, |s, cx| {
                // Start a composition, then cancel it via unmark.
                s.replace_and_mark_text_in_range(None, "n", Some(1..1), window, cx);
                s.unmark_text(window, cx);
                let after_cancel = s.undo_manager.undo_count();

                // A later edit is recorded independently.
                s.replace_text_in_range(None, "x", window, cx);
                assert_eq!(s.undo_manager.undo_count(), after_cancel + 1);
            });
        });
    }

    #[gpui::test]
    fn test_set_selected_range_clips_to_utf8_boundaries(cx: &mut TestAppContext) {
        let input_view = InputView::build(cx, |state| state.default_value("éx"));
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.set_selected_range(0..1, cx);
                assert_eq!(state.selected_range(), 0..2);
                state.copy(&Copy, window, cx);

                state.set_selected_range(1..1, cx);
                assert_eq!(state.selected_range(), 0..0);
            });
        });
    }

    #[gpui::test]
    fn test_ime_selection_is_relative_to_replacement_start(cx: &mut TestAppContext) {
        let input_view = InputView::build(cx, |state| state.default_value("你好 "));
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.set_selected_range(7..7, cx);
                state.replace_and_mark_text_in_range(None, "s", Some(1..1), window, cx);
                state.replace_and_mark_text_in_range(None, "sh", Some(2..2), window, cx);

                assert_eq!(state.value(), "你好 sh");
                assert_eq!(state.selected_range(), 9..9);
                assert_eq!(state.ime_marked_range, Some((7..9).into()));
            });
        });
    }

    #[gpui::test]
    fn test_undo_manager_composition_is_one_undo_group(cx: &mut TestAppContext) {
        let input_view = InputView::build(cx, |state| state);
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.set_value("a", window, cx);
                state.replace_and_mark_text_in_range(None, "s", None, window, cx);
                state.replace_and_mark_text_in_range(None, "sh", None, window, cx);
                state.replace_text_in_range(None, "是", window, cx);
                assert_eq!(state.value(), "a是");

                state.undo(&Undo, window, cx);
                assert_eq!(state.value(), "a");
                state.redo(&Redo, window, cx);
                assert_eq!(state.value(), "a是");
            });
        });
    }

    #[gpui::test]
    fn test_undo_manager_consecutive_compositions_are_separate_groups(cx: &mut TestAppContext) {
        let input_view = InputView::build(cx, |state| state);
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                // First composition: "jin" -> "今天"
                state.replace_and_mark_text_in_range(None, "j", None, window, cx);
                state.replace_and_mark_text_in_range(None, "jin", None, window, cx);
                state.replace_text_in_range(None, "今天", window, cx);
                // Second composition: "wo" -> "我们"
                state.replace_and_mark_text_in_range(None, "w", None, window, cx);
                state.replace_and_mark_text_in_range(None, "wo", None, window, cx);
                state.replace_text_in_range(None, "我们", window, cx);
                assert_eq!(state.value(), "今天我们");
                assert_eq!(state.selected_range(), 12..12);

                state.undo(&Undo, window, cx);
                assert_eq!(state.value(), "今天");
                assert_eq!(state.selected_range(), 6..6);

                state.undo(&Undo, window, cx);
                assert_eq!(state.value(), "");
                assert_eq!(state.selected_range(), 0..0);

                state.redo(&Redo, window, cx);
                assert_eq!(state.value(), "今天");
                assert_eq!(state.selected_range(), 6..6);

                state.redo(&Redo, window, cx);
                assert_eq!(state.value(), "今天我们");
                assert_eq!(state.selected_range(), 12..12);
            });
        });
    }

    #[gpui::test]
    fn test_undo_manager_typing_after_composition_is_a_separate_group(cx: &mut TestAppContext) {
        let input_view = InputView::build(cx, |state| state);
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.replace_and_mark_text_in_range(None, "n", None, window, cx);
                state.replace_text_in_range(None, "你", window, cx);
                state.undo_manager.set_pending_intent(EditIntent::Typing);
                state.replace_text_in_range(None, "a", window, cx);
                state.undo_manager.set_pending_intent(EditIntent::Typing);
                state.replace_text_in_range(None, "b", window, cx);
                assert_eq!(state.value(), "你ab");

                state.undo(&Undo, window, cx);
                assert_eq!(state.value(), "你");

                state.undo(&Undo, window, cx);
                assert_eq!(state.value(), "");
            });
        });
    }

    #[gpui::test]
    fn test_undo_manager_composition_cancel_leaves_no_entry(cx: &mut TestAppContext) {
        let input_view = InputView::build(cx, |state| state);
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.set_value("a", window, cx);
                state.replace_and_mark_text_in_range(None, "s", None, window, cx);
                state.replace_and_mark_text_in_range(None, "", None, window, cx);

                assert_eq!(state.value(), "a");
                assert!(!state.undo_manager.has_undos());
            });
        });
    }

    /// The macOS Korean IME rewrites the character it just inserted.
    #[gpui::test]
    fn test_undo_manager_ime_rewrites_of_typed_char_are_one_group(cx: &mut TestAppContext) {
        let input_view = InputView::build(cx, |state| state);
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.set_value("é ", window, cx);
                state.set_selected_range(3..3, cx);
                // g k s r m f: "ㅎ" -> "하" -> "한", then "ㄱ" -> "그" -> "글"
                state.replace_text_in_range(None, "ㅎ", window, cx);
                state.replace_text_in_range(Some(2..3), "하", window, cx);
                state.replace_text_in_range(Some(2..3), "한", window, cx);
                state.replace_text_in_range(None, "ㄱ", window, cx);
                state.replace_text_in_range(Some(3..4), "그", window, cx);
                state.replace_text_in_range(Some(3..4), "글", window, cx);
                assert_eq!(state.value(), "é 한글");
                assert_eq!(state.undo_manager.undo_count(), 1);

                state.undo(&Undo, window, cx);
                assert_eq!(state.value(), "é ");
                assert_eq!(state.selected_range(), 3..3);

                state.redo(&Redo, window, cx);
                assert_eq!(state.value(), "é 한글");
                assert_eq!(state.selected_range(), 9..9);
            });
        });
    }

    #[gpui::test]
    fn test_undo_manager_rewrite_after_cursor_movement_is_separate(cx: &mut TestAppContext) {
        let input_view = InputView::build(cx, |state| state);
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.replace_text_in_range(None, "c", window, cx);
                state.replace_text_in_range(None, "e", window, cx);
                state.left(&MoveLeft, window, cx);
                state.right(&MoveRight, window, cx);
                state.replace_text_in_range(Some(1..2), "é", window, cx);
                assert_eq!(state.value(), "cé");

                state.undo(&Undo, window, cx);
                assert_eq!(state.value(), "ce");
                state.undo(&Undo, window, cx);
                assert_eq!(state.value(), "");
            });
        });
    }

    #[gpui::test]
    fn test_undo_manager_selection_restored_by_undo_and_redo(cx: &mut TestAppContext) {
        let input_view = InputView::build(cx, |state| state);
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.set_value("abc", window, cx);
                state.set_selected_range(1..2, cx);
                state.replace_text_in_range(None, "X", window, cx);

                state.undo(&Undo, window, cx);
                assert_eq!(state.value(), "abc");
                assert_eq!(state.selected_range(), 1..2);

                state.redo(&Redo, window, cx);
                assert_eq!(state.value(), "aXc");
                assert_eq!(state.selected_range(), 2..2);
            });
        });
    }

    #[gpui::test]
    fn test_undo_manager_forward_delete_restores_cursor(cx: &mut TestAppContext) {
        let input_view = InputView::build(cx, |state| state);
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.set_value("abc", window, cx);
                state.set_selected_range(1..1, cx);
                state.delete(&Delete, window, cx);

                state.undo(&Undo, window, cx);
                assert_eq!(state.value(), "abc");
                assert_eq!(state.selected_range(), 1..1);
            });
        });
    }

    #[gpui::test]
    fn test_undo_manager_selection_movement_preserves_redo(cx: &mut TestAppContext) {
        let input_view = InputView::build(cx, |state| state);
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.replace_text_in_range(None, "ab", window, cx);
                state.undo(&Undo, window, cx);
                state.set_selected_range(0..0, cx);
                state.redo(&Redo, window, cx);
                assert_eq!(state.value(), "ab");

                state.undo(&Undo, window, cx);
                state.replace_text_in_range(None, "x", window, cx);
                state.redo(&Redo, window, cx);
                assert_eq!(state.value(), "x");
            });
        });
    }

    #[gpui::test]
    fn test_undo_manager_noop_edit_preserves_redo(cx: &mut TestAppContext) {
        let input_view = InputView::build(cx, |state| state);
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.replace_text_in_range(None, "a", window, cx);
                state.move_to(0, None, cx);
                state.replace_text_in_range(None, "", window, cx);
                state.undo(&Undo, window, cx);
                assert_eq!(state.value(), "");
                state.redo(&Redo, window, cx);
                assert_eq!(state.value(), "a");
                assert_eq!(state.cursor(), 1);
            });
        });
    }

    #[gpui::test]
    fn test_cursor_round_trip_stops_typing_coalescing(cx: &mut TestAppContext) {
        let input_view = InputView::build(cx, |state| state);
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.replace_text_in_range(None, "a", window, cx);
                state.left(&MoveLeft, window, cx);
                state.right(&MoveRight, window, cx);
                state.replace_text_in_range(None, "b", window, cx);

                state.undo(&Undo, window, cx);
                assert_eq!(state.value(), "a");
                state.undo(&Undo, window, cx);
                assert_eq!(state.value(), "");
            });
        });
    }

    #[gpui::test]
    fn test_undo_manager_noop_edit_breaks_coalescing_without_clearing_history(
        cx: &mut TestAppContext,
    ) {
        let input_view = InputView::build(cx, |state| state);
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.replace_text_in_range(None, "alpha", window, cx);
                state.replace_text_in_range(None, "", window, cx);
                state.replace_text_in_range(None, "beta", window, cx);
                assert_eq!(state.value(), "alphabeta");

                state.undo(&Undo, window, cx);
                assert_eq!(state.value(), "alpha");
                state.undo(&Undo, window, cx);
                assert_eq!(state.value(), "");
            });
        });
    }

    #[gpui::test]
    fn test_undo_manager_masked_redo_restores_actual_cursor(cx: &mut TestAppContext) {
        let input_view = InputView::build(cx, |state| {
            state.mask_pattern(MaskPattern::Number {
                separator: Some(','),
                fraction: None,
            })
        });
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.set_value("12345", window, cx);
                state.set_selected_range(2..2, cx);
                state.replace_text_in_range(None, "9", window, cx);
                let selection_after_edit = state.selected_range();
                assert_ne!(selection_after_edit.end, state.value().len());

                state.undo(&Undo, window, cx);
                state.redo(&Redo, window, cx);
                assert_eq!(state.selected_range(), selection_after_edit);
            });
        });
    }

    /// Unfolding at a position opens exactly the folds hiding it.
    ///
    /// A fold keeps its own first and last line visible, so a position on
    /// either of them opens nothing. Nested folds all open at once, sibling
    /// folds stay closed, and the opened ranges stay fold candidates.
    #[gpui::test]
    fn test_unfold_at(cx: &mut TestAppContext) {
        use crate::input::{FoldRange, Position};

        let view = InputView::<EditorMode>::new(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        let input = view.input;

        // An outer fold over lines 0..=5, a fold nested inside it, and a
        // sibling fold that must never be touched.
        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.set_value("a\nb\nc\nd\ne\nf\ng\nh\ni\nj\nk\nl", window, cx);
                state.apply_highlighter_fold_candidates(
                    vec![
                        FoldRange::new(0, 5),
                        FoldRange::new(2, 4),
                        FoldRange::new(7, 10),
                    ],
                    cx,
                );
                state.display_map.set_folded(0, true);
                state.display_map.set_folded(2, true);
                state.display_map.set_folded(7, true);
            });
        });

        // The outer fold's own first and last line stay visible, so neither
        // position opens anything.
        for line in [0, 5] {
            cx.update(|_, cx| {
                input.update(cx, |state, cx| {
                    assert!(!state.display_map.is_buffer_line_hidden(line));
                    assert!(!state.unfold_at(Position::new(line as u32, 0), cx));
                });
                input.read_with(cx, |state, _| {
                    assert!(state.display_map.is_folded_at(0));
                    assert!(state.display_map.is_folded_at(2));
                    assert!(state.display_map.is_folded_at(7));
                });
            });
        }

        // Line 3 is hidden by both the outer and the nested fold, so both
        // open; the sibling fold does not.
        cx.update(|_, cx| {
            input.update(cx, |state, cx| {
                assert!(state.unfold_at(Position::new(3, 0), cx));
            });
            input.read_with(cx, |state, _| {
                assert!(!state.display_map.is_buffer_line_hidden(3));
                assert!(!state.display_map.is_folded_at(0));
                assert!(!state.display_map.is_folded_at(2));
                assert!(state.display_map.is_folded_at(7));
                // The opened ranges are still candidates for refolding.
                assert!(state.display_map.is_fold_candidate(0));
                assert!(state.display_map.is_fold_candidate(2));
            });
        });

        // Nothing is hidden there any more, so a second call is a no-op.
        cx.update(|_, cx| {
            input.update(cx, |state, cx| {
                assert!(!state.unfold_at(Position::new(3, 0), cx));
            });
        });
    }

    /// Losing focus hides the hover popover but keeps the decorations.
    ///
    /// Both used to be dropped by one call, so clicking away threw away
    /// decorations the application had installed and never asked to remove.
    #[gpui::test]
    fn test_blur_keeps_decorations(cx: &mut TestAppContext) {
        let view = InputView::<EditorMode>::new(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        let input = view.input;

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.set_value("select 1", window, cx);
                let _collection = state.create_decorations_collection(
                    vec![crate::input::TextDecoration::new(
                        0..6,
                        gpui::HighlightStyle {
                            font_weight: Some(gpui::FontWeight::BOLD),
                            ..Default::default()
                        },
                    )],
                    cx,
                );
                state.present_hover(
                    0..6,
                    lsp_types::Hover {
                        contents: lsp_types::HoverContents::Scalar(
                            lsp_types::MarkedString::String("docs".into()),
                        ),
                        range: None,
                    },
                    cx,
                );
                assert!(state.hover_popover().is_some());

                state.on_blur(window, cx);

                assert!(
                    state.hover_popover().is_none(),
                    "blur should hide the hover popover"
                );
                let decorations = state.extras.decoration_layers();
                assert!(
                    decorations.iter().any(|layer| !layer.is_empty()),
                    "blur must not discard decorations"
                );
            });
        });
    }

    /// The mode marker is the only source of truth for the kind of input.
    ///
    /// An auto-growing textarea capped at one row used to report itself as
    /// single-line, because the answer was derived from the row counts.
    #[gpui::test]
    fn test_kind_does_not_follow_the_row_count(cx: &mut TestAppContext) {
        let view = InputView::build_textarea(cx, |state| state.auto_grow(1, 1));
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        view.input.read_with(&mut cx, |state, _| {
            assert!(state.is_multi_line());
            assert!(!state.is_single_line());
            assert!(!state.is_code_editor());
        });
    }

    #[gpui::test]
    fn test_textarea_prewrap_prepares_content_rows_before_layout(cx: &mut TestAppContext) {
        cx.update(crate::init);
        for (value, expected_rows) in [("", 1), ("one\ntwo", 2)] {
            cx.open_window(size(px(400.), px(100.)), |window, cx| {
                let font = window.text_style().font();
                cx.new(|cx| {
                    let mut state = crate::input::TextareaState::new(window, cx)
                        .rows(12)
                        .default_value(value);
                    assert_eq!(state.display_map().wrap_row_count(), 0);
                    state.prewrap(font, px(14.), px(120.), cx);
                    assert_eq!(state.display_map().wrap_row_count(), expected_rows);
                    assert_eq!(state.value(), value);
                    state
                });
                gpui::EmptyView
            });
        }
    }

    #[gpui::test]
    fn test_textarea_prewrap_respects_soft_wrap_before_layout(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let value = "select id, name, email, phone from users where active\nlimit 10";
        for soft_wrap in [true, false] {
            cx.open_window(size(px(400.), px(100.)), |window, cx| {
                let font = window.text_style().font();
                cx.new(|cx| {
                    let mut state = crate::input::TextareaState::new(window, cx)
                        .rows(1)
                        .soft_wrap(soft_wrap)
                        .default_value(value);
                    state.prewrap(font, px(14.), px(120.), cx);
                    let rows = state.display_map().wrap_row_count();
                    if soft_wrap {
                        assert!(rows > 2, "the first logical line must wrap");
                    } else {
                        assert_eq!(rows, 2);
                    }
                    assert_eq!(state.value(), value);
                    state
                });
                gpui::EmptyView
            });
        }
    }

    #[gpui::test]
    fn test_prewrap_counts_wrapped_rows_before_the_first_paint(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let text = "select id, name, email, phone from users where active\nlimit 10";
        for (soft_wrap, wraps) in [(true, true), (false, false)] {
            let mut input = None;
            cx.open_window(size(px(400.), px(100.)), |window, cx| {
                let font = window.text_style().font();
                let editor = cx.new(|cx| {
                    let mut state = crate::input::EditorState::new(window, cx)
                        .soft_wrap(soft_wrap)
                        .default_value(text);
                    state.prewrap(font, px(14.), px(120.), cx);
                    state
                });
                input = Some(editor);
                gpui::EmptyView
            });
            let rows = input
                .unwrap()
                .read_with(cx, |state, _| state.display_map().wrap_row_count());
            // Two lines; at 120px the first wraps unless soft wrap is off.
            assert_eq!(rows > 2, wraps, "soft_wrap({soft_wrap}): {rows} rows");
            if !wraps {
                assert_eq!(rows, 2);
            }
        }
    }

    #[gpui::test]
    fn test_prewrap_uses_the_configured_tab_stops(cx: &mut TestAppContext) {
        cx.update(crate::init);
        cx.open_window(size(px(400.), px(100.)), |window, cx| {
            let font = window.text_style().font();
            let font_size = px(14.);
            let font_id = window.text_system().resolve_font(&font);
            let space_width = window.text_system().layout_width(font_id, font_size, ' ');
            cx.new(|cx| {
                let mut state = crate::input::EditorState::new(window, cx)
                    .tab_size(TabSize {
                        tab_size: 4,
                        hard_tabs: true,
                    })
                    .default_value("\t\t");
                for (tab_size, expected_rows) in [(4, 2), (2, 1), (8, 2)] {
                    state.set_tab_size(
                        TabSize {
                            tab_size,
                            hard_tabs: true,
                        },
                        cx,
                    );
                    state.prewrap(font.clone(), font_size, space_width * 5. + RIGHT_MARGIN, cx);
                    assert_eq!(state.display_map().wrap_row_count(), expected_rows);
                }
                state
            });
            gpui::EmptyView
        });
    }

    /// Prewrap counts with the state's wrapping indent, as the first layout
    /// does: continuation rows indented as deep as their line take more rows.
    #[gpui::test]
    fn test_prewrap_wraps_with_the_wrapping_indent(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let text = "            select id, name, email, phone from users where active";
        let mut rows = Vec::new();
        for indent in [WrappingIndent::Same, WrappingIndent::None] {
            let mut input = None;
            cx.open_window(size(px(400.), px(100.)), |window, cx| {
                let font = window.text_style().font();
                input = Some(cx.new(|cx| {
                    let mut state = crate::input::EditorState::new(window, cx)
                        .wrapping_indent(indent)
                        .default_value(text);
                    state.prewrap(font, px(14.), px(200.), cx);
                    state
                }));
                gpui::EmptyView
            });
            rows.push(
                input
                    .unwrap()
                    .read_with(cx, |state, _| state.display_map().wrap_row_count()),
            );
        }
        assert!(rows[0] > rows[1], "rows with Same, None: {rows:?}");
    }

    /// Once the editor is laid out, layout owns the wrap and prewrap leaves it.
    #[gpui::test]
    fn test_prewrap_does_nothing_once_laid_out(cx: &mut TestAppContext) {
        struct Frame(Entity<crate::input::EditorState>);
        impl Render for Frame {
            fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
                crate::input::InputBase::new("frame")
                    .h(px(100.))
                    .child(crate::input::Editor::new(&self.0))
            }
        }

        cx.update(crate::init);
        let text = "select id, name, email, phone from users where active\nlimit 10";
        let mut input = None;
        let window = cx.open_window(size(px(400.), px(100.)), |window, cx| {
            let state = cx.new(|cx| crate::input::EditorState::new(window, cx).default_value(text));
            input = Some(state.clone());
            Frame(state)
        });
        let input = input.unwrap();
        let mut cx = VisualTestContext::from_window(window.into(), cx);
        cx.update(|window, cx| window.draw(cx).clear(cx));

        let laid_out = input.read_with(&cx, |state, _| state.display_map().wrap_row_count());
        assert!(laid_out >= 2, "laid out to {laid_out} rows");
        let font = cx.update(|window, _| window.text_style().font());
        input.update(&mut cx, |state, cx| {
            state.prewrap(font, px(14.), px(60.), cx)
        });
        assert_eq!(
            input.read_with(&cx, |state, _| state.display_map().wrap_row_count()),
            laid_out
        );
    }

    /// Soft wrap is on by default, for every mode that can wrap.
    ///
    /// The default lives in the shared constructor, where a mode-specific
    /// `new` can silently fail to restore it; this pins it down.
    #[gpui::test]
    fn test_soft_wrap_is_enabled_by_default(cx: &mut TestAppContext) {
        let textarea = InputView::build_textarea(cx, |state| state);
        let mut textarea_cx = VisualTestContext::from_window(textarea.window_handle.into(), cx);
        textarea
            .input
            .read_with(&mut textarea_cx, |state, _| assert!(state.soft_wrap));

        let editor = InputView::<EditorMode>::new(cx);
        let mut editor_cx = VisualTestContext::from_window(editor.window_handle.into(), cx);
        editor
            .input
            .read_with(&mut editor_cx, |state, _| assert!(state.soft_wrap));
    }

    /// Parse a cursor spec into `(text, cursor_offsets)`. Non-empty lines are
    /// joined with `\n` plus a trailing `\n`. `|` marks a cursor. Leading
    /// whitespace is kept, so a spec can express indentation.
    fn parse_cursor_spec(input: &str) -> (String, Vec<usize>) {
        let mut full_text = String::new();
        let mut cursor_offsets = Vec::new();
        let non_empty_lines: Vec<&str> = input.lines().filter(|l| !l.is_empty()).collect();

        for (line_idx, line) in non_empty_lines.iter().enumerate() {
            let mut positions = Vec::new();
            let mut text = String::new();
            for ch in line.chars() {
                if ch == '|' {
                    positions.push(text.len());
                } else {
                    text.push(ch);
                }
            }

            if line_idx > 0 {
                full_text.push('\n');
            }
            let line_start = full_text.len();
            for pos in positions {
                cursor_offsets.push(line_start + pos);
            }
            full_text.push_str(&text);
        }
        full_text.push('\n');

        (full_text, cursor_offsets)
    }

    /// Build a multi-line input for multi-cursor tests.
    fn multi_line(cx: &mut TestAppContext) -> InputView<TextareaMode> {
        InputView::build_textarea(cx, |state| state)
    }

    /// Set the text and cursor positions from a spec (see [`parse_cursor_spec`]).
    fn setup_cursors<M: InputModeKind>(
        cx: &mut VisualTestContext,
        input: &Entity<InputBaseState<M>>,
        spec: &str,
    ) {
        let (full_text, offsets) = parse_cursor_spec(spec);
        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.set_value(&full_text, window, cx);
                let selections = offsets
                    .into_iter()
                    .map(|offset| {
                        CursorSelection::new(state.selections.generate_id(), offset, offset)
                    })
                    .collect();
                state.selections.replace_all(selections);
                cx.notify();
            });
        });
    }

    /// Assert the text and cursor positions match a spec.
    #[track_caller]
    fn assert_cursors<M: InputModeKind>(
        cx: &mut VisualTestContext,
        input: &Entity<InputBaseState<M>>,
        spec: &str,
    ) {
        let (expected_text, mut expected_cursors) = parse_cursor_spec(spec);
        expected_cursors.sort();

        let (actual_text, mut actual_cursors) = input.read_with(cx, |state, _| {
            (
                state.text.to_string(),
                state
                    .selections
                    .iter()
                    .map(|s| s.cursor_offset())
                    .collect::<Vec<_>>(),
            )
        });
        actual_cursors.sort();

        assert_eq!(
            actual_text, expected_text,
            "Text mismatch:\nExpected: {expected_text:?}\nActual:   {actual_text:?}"
        );
        assert_eq!(
            actual_cursors, expected_cursors,
            "Cursor mismatch:\nExpected: {expected_cursors:?}\nActual:   {actual_cursors:?}"
        );
    }

    #[gpui::test]
    fn test_alt_drag_selects_a_block_and_replaces_each_row(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let view = InputView::<EditorMode>::new(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        for modifiers in [
            gpui::Modifiers {
                alt: true,
                ..Default::default()
            },
            gpui::Modifiers {
                alt: true,
                shift: true,
                ..Default::default()
            },
            #[cfg(target_os = "linux")]
            gpui::Modifiers {
                alt: true,
                control: true,
                ..Default::default()
            },
        ] {
            setup_cursors(&mut cx, &view.input, "|abcd\nabcd\nabcd");
            cx.update(|window, cx| {
                view.input.update(cx, |state, cx| state.focus(window, cx));
            });
            let (start, end) = view.input.read_with(&cx, |state, _| {
                let layout = state.last_layout.as_ref().unwrap();
                let origin = state.last_bounds.unwrap().origin;
                let position = |row: usize, col| {
                    let local = layout.lines[row]
                        .position_for_index(col, layout, false)
                        .unwrap();
                    origin
                        + point(
                            layout.line_number_width + local.x,
                            layout.line_height * (row as f32 + 0.5),
                        )
                };
                (position(0, 1), position(2, 3))
            });
            // Land inside the third column instead of exactly on its trailing
            // glyph boundary, where pixel rounding can select the next column.
            let end = point(end.x - px(0.5), end.y);
            // A cached Ctrl-hover definition must not steal a column gesture.
            cx.update(|_, cx| {
                view.input.update(cx, |state, _| {
                    state.extras.hover_definition.update(
                        0..4,
                        vec![lsp_types::LocationLink {
                            origin_selection_range: None,
                            target_uri: "file:///tmp/column-selection.rs".parse().unwrap(),
                            target_range: Default::default(),
                            target_selection_range: Default::default(),
                        }],
                    );
                });
            });
            cx.simulate_mouse_down(start, MouseButton::Left, modifiers);
            cx.simulate_mouse_move(end, MouseButton::Left, modifiers);
            cx.simulate_mouse_up(end, MouseButton::Left, modifiers);
            view.input.read_with(&cx, |state, _| {
                let ranges: Vec<_> = state
                    .selections
                    .iter()
                    .map(|sel| sel.start..sel.end)
                    .collect();
                assert_eq!(ranges, vec![1..3, 6..8, 11..13]);
            });
            // Moving after release must leave the block intact.
            cx.simulate_mouse_move(start, None, modifiers);
            cx.simulate_keystrokes("x");
            assert_cursors(&mut cx, &view.input, "ax|d\nax|d\nax|d");
        }
    }

    #[gpui::test]
    fn test_alt_drag_extends_upward_from_an_existing_cursor(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let view = InputView::<EditorMode>::new(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        setup_cursors(&mut cx, &view.input, "abcd\nabcd\na|bcd");
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| state.focus(window, cx));
        });
        let (start, end) = view.input.read_with(&cx, |state, _| {
            let layout = state.last_layout.as_ref().unwrap();
            let origin = state.last_bounds.unwrap().origin;
            let local = layout.lines[0]
                .position_for_index(1, layout, false)
                .unwrap();
            let x = layout.line_number_width + local.x;
            (
                origin + point(x, layout.line_height * 2.5),
                origin + point(x, layout.line_height * 0.5),
            )
        });
        let modifiers = gpui::Modifiers {
            alt: true,
            ..Default::default()
        };
        cx.simulate_mouse_down(start, MouseButton::Left, modifiers);
        cx.simulate_mouse_move(end, MouseButton::Left, modifiers);
        cx.simulate_mouse_up(end, MouseButton::Left, modifiers);
        assert_cursors(&mut cx, &view.input, "a|bcd\na|bcd\na|bcd");
    }

    #[gpui::test]
    fn test_alt_drag_over_a_short_row_keeps_the_block_width(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let view = InputView::<EditorMode>::new(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        setup_cursors(&mut cx, &view.input, "abcdef\nab\nabcdef");
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| state.focus(window, cx));
        });
        // Drag from row 0 column 1 down to row 1, at the x of row 0's column 5. Row 1
        // only has two characters, so the pointer ends past its end.
        let (start, end) = view.input.read_with(&cx, |state, _| {
            let layout = state.last_layout.as_ref().unwrap();
            let origin = state.last_bounds.unwrap().origin;
            let x_of = |index| {
                layout.line_number_width
                    + layout.lines[0]
                        .position_for_index(index, layout, false)
                        .unwrap()
                        .x
            };
            (
                origin + point(x_of(1), layout.line_height * 0.5),
                origin + point(x_of(5), layout.line_height * 1.5),
            )
        });
        let modifiers = gpui::Modifiers {
            alt: true,
            shift: true,
            ..Default::default()
        };
        cx.simulate_mouse_down(start, MouseButton::Left, modifiers);
        cx.simulate_mouse_move(end, MouseButton::Left, modifiers);
        cx.simulate_mouse_up(end, MouseButton::Left, modifiers);

        // The short row is clipped to its own end; the long row keeps the full span.
        view.input.read_with(&cx, |state, _| {
            let ranges: Vec<_> = state.selections.iter().map(|s| (s.start, s.end)).collect();
            assert_eq!(ranges, vec![(1, 5), (8, 9)]);
        });
    }

    #[gpui::test]
    fn test_alt_mouse_release_outside_editor_ends_column_selection(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let view = InputView::<EditorMode>::new(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        setup_cursors(&mut cx, &view.input, "|abcd\nabcd");
        let position = view.input.read_with(&cx, |state, _| {
            let layout = state.last_layout.as_ref().unwrap();
            state.last_bounds.unwrap().origin
                + point(layout.line_number_width + px(2.), layout.line_height * 0.5)
        });
        let modifiers = gpui::Modifiers {
            alt: true,
            ..Default::default()
        };
        cx.simulate_mouse_down(position, MouseButton::Left, modifiers);
        cx.simulate_mouse_up(point(px(-100.), px(-100.)), MouseButton::Left, modifiers);
        view.input.read_with(&cx, |state, _| {
            assert!(!state.selecting);
            assert!(state.column_select_start.is_none());
        });
    }

    #[gpui::test]
    fn test_consumed_keystrokes_keep_cursor_visible(cx: &mut TestAppContext) {
        let view = InputView::<EditorMode>::new(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        setup_cursors(&mut cx, &view.input, "a|b");
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| {
                state.focus(window, cx);
                state.pause_blink_cursor(cx);
            });
        });
        cx.run_until_parked();
        cx.executor()
            .advance_clock(std::time::Duration::from_millis(300));
        cx.run_until_parked();
        view.input.read_with(&cx, |state, cx| {
            assert!(!state.blink_cursor.read(cx).visible());
        });
        // Copy consumes its shortcut without editing text or moving selections.
        for _ in 0..5 {
            #[cfg(target_os = "macos")]
            cx.simulate_keystrokes("cmd-c");
            #[cfg(not(target_os = "macos"))]
            cx.simulate_keystrokes("ctrl-c");
            cx.run_until_parked();
            cx.executor()
                .advance_clock(std::time::Duration::from_millis(200));
            cx.run_until_parked();
            view.input.read_with(&cx, |state, cx| {
                assert!(state.blink_cursor.read(cx).visible());
            });
        }
    }

    #[gpui::test]
    fn test_mouse_down_shows_cursor_like_a_cursor_move(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let view = InputView::<EditorMode>::new(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        setup_cursors(&mut cx, &view.input, "abcd|efgh");
        let position = |offset: Pixels, cx: &mut VisualTestContext| {
            view.input.read_with(cx, |state, _| {
                let layout = state.last_layout.as_ref().unwrap();
                state.last_bounds.unwrap().origin
                    + point(layout.line_number_width + offset, layout.line_height * 0.5)
            })
        };
        let visible = |cx: &mut VisualTestContext| {
            view.input
                .read_with(cx, |state, cx| state.blink_cursor.read(cx).visible())
        };

        // The press itself shows the caret, without waiting for the focus
        // observer, and the idle delay holds it there like a cursor move.
        let first = position(px(2.), &mut cx);
        cx.simulate_mouse_down(first, MouseButton::Left, Default::default());
        assert!(visible(&mut cx));
        cx.simulate_mouse_up(first, MouseButton::Left, Default::default());
        cx.run_until_parked();

        // Pressing elsewhere in the focused input, in the hidden phase of the
        // blink, shows the caret again at the press.
        cx.executor()
            .advance_clock(std::time::Duration::from_millis(400));
        cx.run_until_parked();
        assert!(!visible(&mut cx));
        let second = position(px(30.), &mut cx);
        cx.simulate_mouse_down(second, MouseButton::Left, Default::default());
        assert!(visible(&mut cx));
        cx.executor()
            .advance_clock(std::time::Duration::from_millis(250));
        cx.run_until_parked();
        assert!(visible(&mut cx));
        cx.simulate_mouse_up(second, MouseButton::Left, Default::default());
    }

    #[gpui::test]
    fn test_multi_cursor_actions_reveal_hidden_carets(cx: &mut TestAppContext) {
        let view = InputView::<EditorMode>::new(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        setup_cursors(&mut cx, &view.input, "ab\na|b\nab");
        // Start each action in the hidden phase without depending on a
        // key-down listener: actions and text input also arrive directly.
        for action in 0..6 {
            cx.update(|_, cx| {
                view.input.update(cx, |state, cx| {
                    state.blink_cursor = cx.new(BlinkCursor::new);
                    state.blink_cursor.update(cx, |cursor, cx| cursor.start(cx));
                });
            });
            cx.run_until_parked();
            cx.executor()
                .advance_clock(std::time::Duration::from_millis(500));
            cx.run_until_parked();
            view.input.read_with(&cx, |state, cx| {
                assert!(!state.blink_cursor.read(cx).visible(), "action {action}");
            });

            cx.update(|window, cx| {
                view.input.update(cx, |state, cx| {
                    match action {
                        0 => state.add_cursor_above(&AddCursorAbove, window, cx),
                        1 => state.add_cursor_below(&AddCursorBelow, window, cx),
                        2 => state.select_up(&SelectUp, window, cx),
                        3 => state.select_down(&SelectDown, window, cx),
                        4 => state.replace_text_in_range(None, "x", window, cx),
                        _ => state.backspace(&Backspace, window, cx),
                    }
                    assert!(state.blink_cursor.read(cx).visible(), "action {action}");
                });
            });
        }
    }

    #[gpui::test]
    fn test_multi_cursor_keyboard_dispatch(cx: &mut TestAppContext) {
        let view = InputView::<EditorMode>::new(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        setup_cursors(&mut cx, &view.input, "ab\na|b\nab");
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| state.focus(window, cx));
        });
        #[cfg(target_os = "macos")]
        cx.simulate_keystrokes("cmd-alt-up");
        #[cfg(target_os = "windows")]
        cx.simulate_keystrokes("ctrl-alt-up");
        #[cfg(not(any(target_os = "macos", target_os = "windows")))]
        cx.simulate_keystrokes("alt-shift-up");
        view.input
            .read_with(&cx, |state, _| assert_eq!(state.selections.len(), 2));
        #[cfg(target_os = "macos")]
        cx.simulate_keystrokes("cmd-alt-down");
        #[cfg(target_os = "windows")]
        cx.simulate_keystrokes("ctrl-alt-down");
        #[cfg(not(any(target_os = "macos", target_os = "windows")))]
        cx.simulate_keystrokes("alt-shift-down");
        view.input
            .read_with(&cx, |state, _| assert_eq!(state.selections.len(), 3));
        cx.simulate_keystrokes("x");
        assert_cursors(&mut cx, &view.input, "ax|b\nax|b\nax|b");
    }

    #[gpui::test]
    fn test_multi_cursor_platform_word_selection_dispatch(cx: &mut TestAppContext) {
        let view = InputView::<EditorMode>::new(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        setup_cursors(&mut cx, &view.input, "one |two\none |two");
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| state.focus(window, cx));
        });
        #[cfg(any(target_os = "macos", target_os = "linux"))]
        cx.simulate_keystrokes("alt-shift-right");
        #[cfg(not(any(target_os = "macos", target_os = "linux")))]
        cx.simulate_keystrokes("ctrl-shift-right");
        cx.simulate_keystrokes("x");
        assert_cursors(&mut cx, &view.input, "one x|\none x|");
        setup_cursors(&mut cx, &view.input, "one two|\none two|");
        #[cfg(any(target_os = "macos", target_os = "linux"))]
        cx.simulate_keystrokes("alt-shift-left");
        #[cfg(not(any(target_os = "macos", target_os = "linux")))]
        cx.simulate_keystrokes("ctrl-shift-left");
        cx.simulate_keystrokes("x");
        assert_cursors(&mut cx, &view.input, "one x|\none x|");
    }

    #[cfg(not(target_os = "macos"))]
    #[gpui::test]
    fn test_multi_cursor_horizontal_selection_dispatch(cx: &mut TestAppContext) {
        let view = InputView::<EditorMode>::new(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        setup_cursors(&mut cx, &view.input, "ab\na|b");
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| state.focus(window, cx));
        });
        #[cfg(target_os = "windows")]
        cx.simulate_keystrokes("ctrl-alt-up");
        #[cfg(not(target_os = "windows"))]
        cx.simulate_keystrokes("alt-shift-up");
        #[cfg(target_os = "linux")]
        cx.simulate_keystrokes("shift-right");
        #[cfg(not(target_os = "linux"))]
        cx.simulate_keystrokes("alt-shift-right");
        view.input.read_with(&cx, |state, _| {
            assert_eq!(
                state
                    .selections
                    .iter()
                    .map(|s| s.start..s.end)
                    .collect::<Vec<_>>(),
                vec![4..5, 1..2]
            );
        });
        #[cfg(target_os = "linux")]
        cx.simulate_keystrokes("shift-left shift-left");
        #[cfg(not(target_os = "linux"))]
        cx.simulate_keystrokes("alt-shift-left alt-shift-left");
        view.input.read_with(&cx, |state, _| {
            assert_eq!(
                state
                    .selections
                    .iter()
                    .map(|s| s.start..s.end)
                    .collect::<Vec<_>>(),
                vec![3..4, 0..1]
            );
        });
        cx.simulate_keystrokes("x");
        assert_cursors(&mut cx, &view.input, "x|b\nx|b");
    }

    #[gpui::test]
    fn test_multi_cursor_alt_click_dispatch(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let view = InputView::<EditorMode>::new(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        setup_cursors(&mut cx, &view.input, "a|b\nab\nab");
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| state.focus(window, cx));
        });
        let position = view.input.read_with(&cx, |state, _| {
            let bounds = state.last_bounds.unwrap();
            let layout = state.last_layout.as_ref().unwrap();
            bounds.origin + point(layout.line_number_width + px(2.), layout.line_height * 1.5)
        });
        cx.simulate_click(
            position,
            gpui::Modifiers {
                alt: true,
                ..Default::default()
            },
        );
        view.input
            .read_with(&cx, |state, _| assert_eq!(state.selections.len(), 2));
    }

    #[gpui::test]
    fn test_add_selection(cx: &mut TestAppContext) {
        let view = InputView::<EditorMode>::new(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| {
                state.focus(window, cx);
                state.set_value("foo bar foo", window, cx);
                state.set_selected_range(0..3, cx);
                // The programmatic second cursor: the next occurrence.
                state.add_selection(8..11, cx);
                // Adding a range that is already selected changes nothing.
                state.add_selection(0..3, cx);
            });
        });
        view.input.read_with(&cx, |state, _| {
            let mut ranges: Vec<Range<usize>> =
                state.selections.iter().map(|s| s.start..s.end).collect();
            ranges.sort_by_key(|r| r.start);
            assert_eq!(ranges, vec![0..3, 8..11]);
        });
        // Typing replaces every selection at once.
        cx.simulate_keystrokes("x");
        view.input.read_with(&cx, |state, _| {
            assert_eq!(state.text.to_string(), "x bar x")
        });
    }

    #[gpui::test]
    fn test_add_selection_preserves_crlf_boundaries(cx: &mut TestAppContext) {
        let view = InputView::build_textarea(cx, |state| state.default_value("a\r\nb"));
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| {
                state.focus(window, cx);
                state.set_selected_range(4..4, cx);
                state.add_selection(2..2, cx);
                let ranges: Vec<_> = state.selections.iter().map(|s| s.start..s.end).collect();
                assert_eq!(ranges, vec![4..4, 1..1]);
            });
        });
        cx.simulate_keystrokes("x");
        view.input.read_with(&cx, |state, _| {
            assert_eq!(state.value(), "ax\r\nbx");
        });
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| {
                state.set_value("a\r\nb", window, cx);
                state.set_selected_range(4..4, cx);
                state.add_selection(2..3, cx);
                state.cut(&Cut, window, cx);
                assert_eq!(cx.read_from_clipboard().unwrap().text().unwrap(), "\r\n");
                assert_eq!(state.value(), "ab");
            });
        });
    }

    #[gpui::test]
    fn test_add_selection_merges_overlaps_before_copy_and_cut(cx: &mut TestAppContext) {
        let view = InputView::<EditorMode>::new(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| {
                // Cover partial overlaps, a containing range, and a bridge
                // between two previously disjoint selections.
                for additions in [vec![2..5], vec![0..5], vec![4..5, 2..4]] {
                    state.set_value("abcdef", window, cx);
                    state.set_selected_range(0..3, cx);
                    let active_id = state.active_selection().id;
                    for range in additions {
                        state.add_selection(range, cx);
                    }
                    assert_eq!(state.active_selection().id, active_id);
                    assert_eq!(state.selected_range(), 0..5);
                    assert_eq!(state.selections.len(), 1);
                    state.copy(&Copy, window, cx);
                    assert_eq!(cx.read_from_clipboard().unwrap().text().unwrap(), "abcde");
                    state.cut(&Cut, window, cx);
                    assert_eq!(cx.read_from_clipboard().unwrap().text().unwrap(), "abcde");
                    assert_eq!(state.value(), "f");
                    state.undo(&Undo, window, cx);
                    assert_eq!(state.value(), "abcdef");
                    assert_eq!(state.selected_range(), 0..5);
                }
            });
        });
    }

    #[gpui::test]
    fn test_add_selection_clears_inline_completion(cx: &mut TestAppContext) {
        use crate::input::CompletionProvider;
        use gpui::Task;
        use lsp_types::{
            CompletionContext, CompletionResponse, InlineCompletionContext, InlineCompletionItem,
            InlineCompletionResponse,
        };
        use std::time::Duration;

        struct Provider(Rc<Cell<usize>>);

        impl CompletionProvider for Provider {
            fn is_completion_trigger(&self, _: usize, _: &str, _: &mut App) -> bool {
                false
            }

            fn completions(
                &self,
                _: &Rope,
                _: usize,
                _: CompletionContext,
                _: &mut Window,
                _: &mut App,
            ) -> Task<anyhow::Result<CompletionResponse>> {
                Task::ready(Ok(CompletionResponse::Array(vec![])))
            }

            fn inline_completion(
                &self,
                _: &Rope,
                _: usize,
                _: InlineCompletionContext,
                _: &mut Window,
                _: &mut App,
            ) -> Task<anyhow::Result<InlineCompletionResponse>> {
                self.0.set(self.0.get() + 1);
                Task::ready(Ok(InlineCompletionResponse::Array(vec![])))
            }
        }

        let view = InputView::<EditorMode>::new(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        let calls = Rc::new(Cell::new(0));
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| {
                state.focus(window, cx);
                state.set_value("aa\naa", window, cx);
                state.set_selected_range(2..2, cx);
                state.extras.inline_completion.item = Some(InlineCompletionItem {
                    insert_text: "suggestion".into(),
                    filter_text: None,
                    range: None,
                    command: None,
                    insert_text_format: None,
                });
                state.add_selection(5..5, cx);
                assert!(!state.has_inline_completion());
                state.indent_inline(&IndentInline, window, cx);
                assert_eq!(state.value(), "aa  \naa  ");
                assert_eq!(state.selections.len(), 2);

                // The active cursor stays put, so only canceling the task
                // prevents this pending request from fetching a suggestion.
                state.set_value("aa\naa", window, cx);
                state.set_selected_range(2..2, cx);
                state.extras.lsp.completion_provider = Some(Rc::new(Provider(calls.clone())));
                state.schedule_inline_completion(window, cx);
            });
        });
        cx.run_until_parked();
        cx.update(|_, cx| {
            view.input
                .update(cx, |state, cx| state.add_selection(5..5, cx));
        });
        cx.executor().advance_clock(Duration::from_secs(1));
        cx.run_until_parked();
        assert_eq!(calls.get(), 0);
        view.input.read_with(&cx, |state, _| {
            assert!(!state.has_inline_completion());
            assert_eq!(state.selections.len(), 2);
            assert_eq!(state.value(), "aa\naa");
        });
    }

    #[gpui::test]
    fn test_word_delete_undo_restores_caret(cx: &mut TestAppContext) {
        let view = multi_line(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        setup_cursors(&mut cx, &view.input, "hello|");
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| {
                state.delete_previous_word(&DeleteToPreviousWordStart, window, cx);
                state.undo(&Undo, window, cx);
                assert_eq!(state.selected_range(), 5..5);
            });
        });
    }

    #[gpui::test]
    fn test_merged_delete_undo_restores_all_carets(cx: &mut TestAppContext) {
        let view = multi_line(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        setup_cursors(&mut cx, &view.input, "a|b|c");
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| {
                state.backspace(&Backspace, window, cx);
                state.undo(&Undo, window, cx);
            });
        });
        assert_cursors(&mut cx, &view.input, "a|b|c");
    }

    #[gpui::test]
    fn test_shift_end_respects_soft_wrap_end(cx: &mut TestAppContext) {
        let view = InputView::<EditorMode>::new(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| {
                state.set_value("abcdef ".repeat(30), window, cx);
                state.display_map.on_layout_changed(Some(px(60.)), cx);
                let line = state.display_map.line(0).unwrap();
                assert!(line.wrapped_lines.len() > 1);
                let boundary = line.wrapped_lines[0].end;
                state.move_to_with_affinity(boundary, None, true, cx);
                state.select_to_end_of_line(&SelectToEndOfLine, window, cx);
                assert_eq!(state.selected_range(), boundary..state.text.len());
            });
        });
    }

    #[gpui::test]
    fn test_outdent_unindented_unicode_is_unchanged(cx: &mut TestAppContext) {
        let view = multi_line(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        setup_cursors(&mut cx, &view.input, "|你好\n|世界");
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| {
                state.outdent(false, window, cx);
                state.outdent(true, window, cx);
            });
        });
        assert_cursors(&mut cx, &view.input, "|你好\n|世界");
    }

    #[gpui::test]
    fn test_column_selection_stays_on_unicode_boundaries(cx: &mut TestAppContext) {
        let view = multi_line(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        setup_cursors(&mut cx, &view.input, "ab\n你好\ncd");
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| {
                state.build_columnar_selection(
                    ColumnarPoint::new(1, 0),
                    ColumnarPoint::new(11, 0),
                    cx,
                );
                let text = state.value();
                for sel in state.selections.iter() {
                    assert!(text.is_char_boundary(sel.start));
                    assert!(text.is_char_boundary(sel.end));
                }
                state.replace_text_in_range(None, "X", window, cx);
            });
        });
    }

    #[gpui::test]
    fn test_editor_decorations_follow_typing(cx: &mut TestAppContext) {
        let view = InputView::<EditorMode>::new(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| {
                state.set_value("abc def", window, cx);
                state.create_decorations_collection(
                    vec![crate::input::TextDecoration::new(
                        4..7,
                        gpui::HighlightStyle::default(),
                    )],
                    cx,
                );
                state.set_selected_range(0..0, cx);
                state.replace_text_in_range(None, "X", window, cx);
                let layers = state.extras.decoration_layers();
                assert_eq!(layers.into_iter().flatten().next().unwrap().range, 5..8);
            });
        });
    }

    #[gpui::test]
    fn test_backspace_preserves_escaped_quote_terminator(cx: &mut TestAppContext) {
        let view = InputView::<EditorMode>::new(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        setup_cursors(&mut cx, &view.input, r#"{"s":"\"|"}"#);
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| {
                set_test_syntax_provider(std::rc::Rc::new(StringAllProvider), cx);
                state.backspace(&Backspace, window, cx);
            });
        });
        assert_cursors(&mut cx, &view.input, r#"{"s":"\|"}"#);
    }

    #[gpui::test]
    fn test_ordinary_typing_does_not_query_syntax(cx: &mut TestAppContext) {
        struct UnexpectedQuery;
        impl crate::input::SyntaxContextProvider for UnexpectedQuery {
            fn context_at(&self, _: &ropey::Rope, _: usize) -> crate::input::SyntaxContext {
                panic!("ordinary typing must not query syntax");
            }
        }
        let view = InputView::<EditorMode>::new(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        setup_cursors(&mut cx, &view.input, "|");
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| {
                set_test_syntax_provider(std::rc::Rc::new(UnexpectedQuery), cx);
                for c in ["a", "b", "c"] {
                    state.replace_text_in_range(None, c, window, cx);
                }
            });
        });
        assert_cursors(&mut cx, &view.input, "abc|");
    }

    #[gpui::test]
    fn test_auto_close_is_atomic_at_history_limit(cx: &mut TestAppContext) {
        let view = InputView::<EditorMode>::new(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        setup_cursors(&mut cx, &view.input, "|");
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| {
                for _ in 0..999 {
                    state.replace_text_in_range(None, "a", window, cx);
                }
                state.replace_text_in_range(None, "(", window, cx);
                state.undo(&Undo, window, cx);
                assert!(!state.text.to_string().contains('('));
                assert!(!state.text.to_string().contains(')'));
                state.redo(&Redo, window, cx);
            });
        });
        assert_cursors(&mut cx, &view.input, &format!("{}(|)", "a".repeat(999)));
    }

    #[gpui::test]
    fn test_comment_closer_is_inserted_literally(cx: &mut TestAppContext) {
        let view = InputView::<EditorMode>::new(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        setup_cursors(&mut cx, &view.input, "// (|)");
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| {
                set_test_syntax_provider(std::rc::Rc::new(CommentAllProvider), cx);
                state.replace_text_in_range(None, ")", window, cx);
            });
        });
        assert_cursors(&mut cx, &view.input, "// ()|)");
    }

    #[gpui::test]
    fn test_explicit_range_skip_does_not_delete_existing_closer_on_undo(cx: &mut TestAppContext) {
        let view = InputView::<EditorMode>::new(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        setup_cursors(&mut cx, &view.input, "(a|)");
        let before = view.input.read_with(&cx, |state, _| state.text.to_string());
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| {
                state.replace_text_in_range(Some(2..2), ")", window, cx);
            });
        });
        assert_cursors(&mut cx, &view.input, "(a)|");
        cx.update(|window, cx| {
            view.input
                .update(cx, |state, cx| state.undo(&Undo, window, cx));
        });
        view.input.read_with(&cx, |state, _| {
            assert_eq!(
                state.text.to_string(),
                before,
                "skip must not remove an existing closer on undo"
            );
        });
    }

    #[gpui::test]
    fn test_pair_redo_restores_interior_cursor(cx: &mut TestAppContext) {
        let view = InputView::<EditorMode>::new(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        setup_cursors(&mut cx, &view.input, "|");
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| {
                state.replace_text_in_range(None, "(", window, cx);
            });
        });
        assert_cursors(&mut cx, &view.input, "(|)");
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| {
                state.undo(&Undo, window, cx);
                state.redo(&Redo, window, cx);
            });
        });
        assert_cursors(&mut cx, &view.input, "(|)");
    }

    #[gpui::test]
    fn test_pair_enter_redo_restores_interior_cursor(cx: &mut TestAppContext) {
        let view = InputView::<EditorMode>::new(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        setup_cursors(&mut cx, &view.input, "{|}");
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| {
                state.enter(
                    &Enter {
                        secondary: false,
                        shift: false,
                    },
                    window,
                    cx,
                );
            });
        });
        assert_cursors(&mut cx, &view.input, "{\n  |\n}");
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| {
                state.undo(&Undo, window, cx);
            });
        });
        assert_cursors(&mut cx, &view.input, "{|}");
        cx.update(|window, cx| {
            view.input
                .update(cx, |state, cx| state.redo(&Redo, window, cx));
        });
        assert_cursors(&mut cx, &view.input, "{\n  |\n}");
    }

    #[gpui::test]
    fn test_auto_close_parens(cx: &mut TestAppContext) {
        let view = InputView::<EditorMode>::new(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        setup_cursors(&mut cx, &view.input, "|");
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| {
                state.replace_text_in_range(None, "(", window, cx);
            });
        });
        assert_cursors(&mut cx, &view.input, "(|)");
        // Selection must be collapsed: typing next must insert, not replace.
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| {
                state.replace_text_in_range(None, "x", window, cx);
            });
        });
        assert_cursors(&mut cx, &view.input, "(x|)");
    }

    #[gpui::test]
    fn test_auto_close_skip_over_closer(cx: &mut TestAppContext) {
        let view = InputView::<EditorMode>::new(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        setup_cursors(&mut cx, &view.input, "(|)");
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| {
                state.replace_text_in_range(None, ")", window, cx);
            });
        });
        // No duplicate closer, cursor moves past the existing one.
        assert_cursors(&mut cx, &view.input, "()|");
        // Selection must be collapsed, not covering blank space.
        view.input.read_with(&cx, |state, _| {
            assert!(state.active_selection().is_empty());
        });
    }

    #[gpui::test]
    fn test_auto_close_no_pair_inside_word(cx: &mut TestAppContext) {
        let view = InputView::<EditorMode>::new(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        setup_cursors(&mut cx, &view.input, "don|");
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| {
                state.replace_text_in_range(None, "'", window, cx);
            });
        });
        // Contraction: no auto-close.
        assert_cursors(&mut cx, &view.input, "don'|");
    }

    #[gpui::test]
    fn test_auto_close_quote_after_cjk(cx: &mut TestAppContext) {
        let view = InputView::<EditorMode>::new(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        // Unicode-safe previous-char lookup: must not panic on multi-byte prefix.
        // CJK counts as word-like, so no pairing — single quote inserted.
        setup_cursors(&mut cx, &view.input, "中|");
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| {
                state.replace_text_in_range(None, "'", window, cx);
            });
        });
        assert_cursors(&mut cx, &view.input, "中'|");
    }

    #[gpui::test]
    fn test_auto_close_closer_skips_at_string_end(cx: &mut TestAppContext) {
        let view = InputView::<EditorMode>::new(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        // Cursor before existing closing quote: typing `"` skips past it.
        setup_cursors(&mut cx, &view.input, "\"hello|\"");
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| {
                state.replace_text_in_range(None, "\"", window, cx);
            });
        });
        assert_cursors(&mut cx, &view.input, "\"hello\"|");
        view.input.read_with(&cx, |state, _| {
            assert!(state.active_selection().is_empty());
        });
    }

    #[gpui::test]
    fn test_backspace_pair_with_cjk_prefix(cx: &mut TestAppContext) {
        let view = InputView::<EditorMode>::new(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        // UTF-16 conversion: deleting `()` after CJK must not touch neighbors.
        setup_cursors(&mut cx, &view.input, "中(|)abc");
        cx.update(|window, cx| {
            view.input
                .update(cx, |state, cx| state.backspace(&Backspace, window, cx));
        });
        assert_cursors(&mut cx, &view.input, "中|abc");
    }

    #[gpui::test]
    fn test_enter_split_respects_smart_indent_off(cx: &mut TestAppContext) {
        let view = InputView::<EditorMode>::new(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        setup_cursors(&mut cx, &view.input, "{|}");
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| {
                state.set_smart_indent(false, window, cx);
                state.enter(
                    &Enter {
                        secondary: false,
                        shift: false,
                    },
                    window,
                    cx,
                );
            });
        });
        // Smart indent controls both structural splitting and extra indentation.
        assert_cursors(&mut cx, &view.input, "{\n|}");
    }

    #[gpui::test]
    fn test_enter_split_is_independent_of_auto_close(cx: &mut TestAppContext) {
        let view = InputView::<EditorMode>::new(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        setup_cursors(&mut cx, &view.input, "{|}");
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| {
                state.set_auto_close(false, window, cx);
                state.enter(
                    &Enter {
                        secondary: false,
                        shift: false,
                    },
                    window,
                    cx,
                );
            });
        });
        // Disabling automatic insertion does not disable structural indentation.
        assert_cursors(&mut cx, &view.input, "{\n  |\n}");
    }

    #[gpui::test]
    fn test_language_config_applies_before_render_and_on_language_change(cx: &mut TestAppContext) {
        use crate::input::{AutoClosingPair, set_language_config};
        let view = InputView::<EditorMode>::new(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        cx.update(|window, cx| {
            set_language_config(
                "alpha",
                LanguageConfig::default().auto_closing_pairs([AutoClosingPair::new("«", "»")]),
                cx,
            );
            set_language_config(
                "beta",
                LanguageConfig::default().auto_closing_pairs([AutoClosingPair::new("‹", "›")]),
                cx,
            );
            let first = cx.new(|cx| EditorState::new(window, cx).language("ALPHA"));
            let second = cx.new(|cx| EditorState::new(window, cx).language("beta"));
            first.update(cx, |state, cx| {
                state.replace_text_in_range(None, "«", window, cx);
                assert_eq!(state.text().to_string(), "«»");
                state.set_value("", window, cx);
                state.set_smart_indent(false, window, cx);
                state.set_highlighter("beta", cx);
                assert!(!state.mode.is_smart_indent());
                state.replace_text_in_range(None, "‹", window, cx);
                assert_eq!(state.text().to_string(), "‹›");
                state.set_value("", window, cx);
                state.set_highlighter("unknown", cx);
                state.replace_text_in_range(None, "(", window, cx);
                assert_eq!(state.text().to_string(), "()");
            });
            second.update(cx, |state, cx| {
                state.replace_text_in_range(None, "‹", window, cx);
                assert_eq!(state.text().to_string(), "‹›");
            });
        });
    }

    #[gpui::test]
    fn test_language_service_replacement_updates_syntax_without_render(cx: &mut TestAppContext) {
        use crate::input::{LanguageProvider, SyntaxContextProvider, set_language_provider};
        struct StringLanguages(Rc<Cell<usize>>);
        impl LanguageProvider for StringLanguages {
            fn syntax_context_provider(&self, _: &str) -> Option<Rc<dyn SyntaxContextProvider>> {
                self.0.set(self.0.get() + 1);
                Some(Rc::new(StringAllProvider))
            }
        }
        struct CodeLanguages;
        impl LanguageProvider for CodeLanguages {}
        let view = InputView::<EditorMode>::new(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        cx.update(|window, cx| {
            let creations = Rc::new(Cell::new(0));
            set_language_provider(Rc::new(StringLanguages(creations.clone())), cx);
            view.input.update(cx, |state, cx| {
                state.replace_text_in_range(None, "(", window, cx);
                state.replace_text_in_range(None, "[", window, cx);
                assert_eq!(state.text().to_string(), "([");
                assert_eq!(
                    creations.get(),
                    1,
                    "retain the document provider between edits"
                );
            });
            set_language_provider(Rc::new(CodeLanguages), cx);
            view.input.update(cx, |state, cx| {
                state.replace_text_in_range(None, "{", window, cx);
                assert_eq!(state.text().to_string(), "([{}");
            });
        });
    }

    #[gpui::test]
    fn test_language_config_updates_existing_editors(cx: &mut TestAppContext) {
        use crate::input::{AutoClosingPair, set_language_config};
        let view = InputView::<EditorMode>::new(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        setup_cursors(&mut cx, &view.input, "|");
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| {
                state.set_highlighter("CUSTOM", cx);
                state.set_auto_close(false, window, cx);
                state.set_smart_indent(false, window, cx);
            });
            set_language_config(
                "custom",
                LanguageConfig::default().auto_closing_pairs([AutoClosingPair::new("«", "»")]),
                cx,
            );
            // Batched registrations must update every affected language.
            set_language_config("other", LanguageConfig::default(), cx);
            view.input.update(cx, |state, cx| {
                assert!(!state.mode.is_auto_close());
                assert!(!state.mode.is_smart_indent());
                state.set_auto_close(true, window, cx);
                state.replace_text_in_range(None, "«", window, cx);
            });
        });
        assert_cursors(&mut cx, &view.input, "«|»");
    }

    #[gpui::test]
    fn test_auto_close_before_is_language_configurable(cx: &mut TestAppContext) {
        let view = InputView::<EditorMode>::new(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        setup_cursors(&mut cx, &view.input, "|word");
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| {
                state.replace_text_in_range(None, "(", window, cx)
            });
        });
        assert_cursors(&mut cx, &view.input, "(|word");
        setup_cursors(&mut cx, &view.input, "|word");
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| {
                crate::input::set_language_config(
                    state.language_name(),
                    LanguageConfig::default().auto_close_before("w"),
                    cx,
                );
                state.replace_text_in_range(None, "(", window, cx);
            });
        });
        assert_cursors(&mut cx, &view.input, "(|)word");
    }

    #[gpui::test]
    fn test_pair_context_restrictions_are_per_pair(cx: &mut TestAppContext) {
        use crate::input::{AutoClosingPair, SyntaxContext};
        let view = InputView::<EditorMode>::new(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        setup_cursors(&mut cx, &view.input, "|");
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| {
                set_test_syntax_provider(std::rc::Rc::new(CommentAllProvider), cx);
                crate::input::set_language_config(
                    state.language_name(),
                    LanguageConfig::default().auto_closing_pairs([
                        AutoClosingPair::new("(", ")").not_in([SyntaxContext::String]),
                        AutoClosingPair::new("[", "]").not_in([SyntaxContext::Comment]),
                    ]),
                    cx,
                );
                state.replace_text_in_range(None, "(", window, cx);
                state.replace_text_in_range(None, "[", window, cx);
            });
        });
        assert_cursors(&mut cx, &view.input, "([|)");
    }

    #[gpui::test]
    fn test_multichar_delimiters_insert_delete_and_skip(cx: &mut TestAppContext) {
        use crate::input::{AutoClosingPair, SyntaxContext};
        struct BlockComment;
        impl crate::input::SyntaxContextProvider for BlockComment {
            fn context_at(&self, text: &ropey::Rope, _: usize) -> SyntaxContext {
                if text.to_string().contains("/*") {
                    SyntaxContext::Comment
                } else {
                    SyntaxContext::Code
                }
            }
        }
        let view = InputView::<EditorMode>::new(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        setup_cursors(&mut cx, &view.input, "|");
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| {
                set_test_syntax_provider(std::rc::Rc::new(BlockComment), cx);
                crate::input::set_language_config(
                    state.language_name(),
                    LanguageConfig::default()
                        .auto_closing_pairs([AutoClosingPair::new("/*", "*/")
                            .not_in([SyntaxContext::String, SyntaxContext::Comment])]),
                    cx,
                );
                state.replace_text_in_range(None, "/", window, cx);
                state.replace_text_in_range(None, "*", window, cx);
            });
        });
        assert_cursors(&mut cx, &view.input, "/*|*/");
        cx.update(|window, cx| {
            view.input
                .update(cx, |state, cx| state.backspace(&Backspace, window, cx));
        });
        assert_cursors(&mut cx, &view.input, "|");
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| {
                state.undo(&Undo, window, cx);
                state.replace_text_in_range(None, "*", window, cx);
                state.replace_text_in_range(None, "/", window, cx);
            });
        });
        assert_cursors(&mut cx, &view.input, "/**/|");
    }

    #[gpui::test]
    fn test_auto_closed_pairs_fallback_and_explicit_disable(cx: &mut TestAppContext) {
        use crate::input::BracketPair;
        let view = InputView::<EditorMode>::new(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        setup_cursors(&mut cx, &view.input, "|");
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| {
                let mut rules = LanguageConfig::default().brackets([BracketPair::new("«", "»")]);
                rules.auto_closing_pairs = None;
                crate::input::set_language_config(state.language_name(), rules.clone(), cx);
                state.replace_text_in_range(None, "«", window, cx);
                crate::input::set_language_config(
                    state.language_name(),
                    rules.auto_closing_pairs([]),
                    cx,
                );
                state.replace_text_in_range(None, "«", window, cx);
            });
        });
        assert_cursors(&mut cx, &view.input, "««|»");
    }

    #[gpui::test]
    fn test_undo_open_composition_preserves_generated_pairs(cx: &mut TestAppContext) {
        use crate::input::{AutoClosingPair, SyntaxContext};
        let view = InputView::<EditorMode>::new(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        setup_cursors(&mut cx, &view.input, "|");
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| {
                crate::input::set_language_config(
                    state.language_name(),
                    LanguageConfig::default()
                        .auto_closing_pairs([
                            AutoClosingPair::new("/*", "*/").not_in([SyntaxContext::Comment])
                        ]),
                    cx,
                );
                state.replace_text_in_range(None, "/", window, cx);
                state.replace_text_in_range(None, "*", window, cx);
                set_test_syntax_provider(std::rc::Rc::new(CommentAllProvider), cx);
                state.replace_and_mark_text_in_range(None, "x", Some(1..1), window, cx);
                state.undo(&Undo, window, cx);
                state.replace_text_in_range(None, "*", window, cx);
                state.replace_text_in_range(None, "/", window, cx);
            });
        });
        assert_cursors(&mut cx, &view.input, "/**/|");
    }

    #[gpui::test]
    fn test_undo_does_not_promote_literal_comment_delimiters(cx: &mut TestAppContext) {
        use crate::input::{AutoClosingPair, SyntaxContext};
        let view = InputView::<EditorMode>::new(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        setup_cursors(&mut cx, &view.input, "/*|*/");
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| {
                set_test_syntax_provider(std::rc::Rc::new(CommentAllProvider), cx);
                crate::input::set_language_config(
                    state.language_name(),
                    LanguageConfig::default()
                        .auto_closing_pairs([
                            AutoClosingPair::new("/*", "*/").not_in([SyntaxContext::Comment])
                        ]),
                    cx,
                );
                state.delete_to_end_of_line(&DeleteToEndOfLine, window, cx);
                state.undo(&Undo, window, cx);
                state.backspace(&Backspace, window, cx);
            });
        });
        assert_cursors(&mut cx, &view.input, "/|*/");
    }

    #[gpui::test]
    fn test_multiple_generated_pairs_retain_their_identity(cx: &mut TestAppContext) {
        use crate::input::{AutoClosingPair, SyntaxContext};
        struct CommentScope;
        impl crate::input::SyntaxContextProvider for CommentScope {
            fn context_at(&self, text: &ropey::Rope, offset: usize) -> SyntaxContext {
                if text
                    .to_string()
                    .find("*/")
                    .is_some_and(|end| offset < end + 2)
                {
                    SyntaxContext::Comment
                } else {
                    SyntaxContext::Code
                }
            }
        }
        let view = InputView::<EditorMode>::new(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        setup_cursors(&mut cx, &view.input, "|");
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| {
                set_test_syntax_provider(std::rc::Rc::new(CommentScope), cx);
                crate::input::set_language_config(
                    state.language_name(),
                    LanguageConfig::default().auto_closing_pairs([
                        AutoClosingPair::new("/*", "*/").not_in([SyntaxContext::Comment]),
                        AutoClosingPair::new("(", ")").not_in([SyntaxContext::Comment]),
                    ]),
                    cx,
                );
                state.replace_text_in_range(None, "/", window, cx);
                state.replace_text_in_range(None, "*", window, cx);
                state.set_selected_range(4..4, cx);
                state.replace_text_in_range(None, "(", window, cx);
                state.set_selected_range(2..2, cx);
                state.replace_text_in_range(None, "*", window, cx);
                state.replace_text_in_range(None, "/", window, cx);
            });
        });
        assert_cursors(&mut cx, &view.input, "/**/|()");
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| {
                state.set_selected_range(2..2, cx);
                state.backspace(&Backspace, window, cx);
                state.undo(&Undo, window, cx);
                state.redo(&Redo, window, cx);
            });
        });
        assert_cursors(&mut cx, &view.input, "|()");
    }

    #[gpui::test]
    fn test_replacing_generated_opener_invalidates_the_pair(cx: &mut TestAppContext) {
        use crate::input::{AutoClosingPair, SyntaxContext};
        let view = InputView::<EditorMode>::new(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        setup_cursors(&mut cx, &view.input, "|");
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| {
                crate::input::set_language_config(
                    state.language_name(),
                    LanguageConfig::default()
                        .auto_closing_pairs([
                            AutoClosingPair::new("/*", "*/").not_in([SyntaxContext::Comment])
                        ]),
                    cx,
                );
                state.replace_text_in_range(None, "/", window, cx);
                state.replace_text_in_range(None, "*", window, cx);
                state.replace_text_in_range(Some(0..2), "//", window, cx);
                set_test_syntax_provider(std::rc::Rc::new(CommentAllProvider), cx);
                state.replace_text_in_range(None, "*", window, cx);
            });
        });
        assert_cursors(&mut cx, &view.input, "//*|*/");
    }

    #[gpui::test]
    fn test_configuration_preserves_compiled_regex_options(cx: &mut TestAppContext) {
        use crate::input::IndentationRules;
        let view = InputView::<EditorMode>::new(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        setup_cursors(&mut cx, &view.input, "BEGIN|");
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| {
                let rules = |insensitive| {
                    LanguageConfig::default().indentation_rules(IndentationRules::new(
                        regex::RegexBuilder::new("begin$")
                            .case_insensitive(insensitive)
                            .build()
                            .unwrap(),
                        regex::Regex::new("^end").unwrap(),
                    ))
                };
                crate::input::set_language_config(state.language_name(), rules(false), cx);
                crate::input::set_language_config(state.language_name(), rules(true), cx);
                state.enter(
                    &Enter {
                        secondary: false,
                        shift: false,
                    },
                    window,
                    cx,
                );
            });
        });
        assert_cursors(&mut cx, &view.input, "BEGIN\n  |");
    }

    #[gpui::test]
    fn test_indent_patterns_are_applied_on_enter(cx: &mut TestAppContext) {
        use crate::input::IndentationRules;
        let view = InputView::<EditorMode>::new(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        let rules = LanguageConfig::default().indentation_rules(IndentationRules::new(
            regex::Regex::new(r"\bbegin\s*$").unwrap(),
            regex::Regex::new(r"^\s*end\b").unwrap(),
        ));
        for (before, expected) in [("begin|", "begin\n  |"), ("  |end", "  \n|end")] {
            setup_cursors(&mut cx, &view.input, before);
            cx.update(|window, cx| {
                view.input.update(cx, |state, cx| {
                    crate::input::set_language_config(state.language_name(), rules.clone(), cx);
                    state.enter(
                        &Enter {
                            secondary: false,
                            shift: false,
                        },
                        window,
                        cx,
                    );
                });
            });
            assert_cursors(&mut cx, &view.input, expected);
        }
    }

    #[gpui::test]
    fn test_custom_language_config(cx: &mut TestAppContext) {
        let view = InputView::<EditorMode>::new(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        cx.update(|_window, cx| {
            view.input.update(cx, |state, cx| {
                crate::input::set_language_config(
                    state.language_name(),
                    crate::input::language_config::LanguageConfig::default()
                        .brackets([crate::input::BracketPair::new("«", "»")])
                        .auto_closing_pairs([crate::input::AutoClosingPair::new("«", "»")]),
                    cx,
                );
            });
        });
        // Custom pair closes.
        setup_cursors(&mut cx, &view.input, "|");
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| {
                state.replace_text_in_range(None, "«", window, cx);
            });
        });
        assert_cursors(&mut cx, &view.input, "«|»");
        // Default `(` no longer pairs under custom rules.
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| {
                state.set_value("\n", window, cx);
                state.set_selected_range(0..0, cx);
                state.replace_text_in_range(None, "(", window, cx);
            });
        });
        assert_cursors(&mut cx, &view.input, "(|");
    }

    #[gpui::test]
    fn test_skip_records_no_history(cx: &mut TestAppContext) {
        let view = InputView::<EditorMode>::new(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        setup_cursors(&mut cx, &view.input, "(a|)");
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| {
                // Type a normal char (recorded), then skip over `)`.
                state.replace_text_in_range(None, "b", window, cx);
            });
        });
        assert_cursors(&mut cx, &view.input, "(ab|)");
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| {
                state.replace_text_in_range(None, ")", window, cx);
            });
        });
        // Skip is a pure cursor move: no history entry of its own.
        assert_cursors(&mut cx, &view.input, "(ab)|");
        // Undo removes `b`, never exposing a transient `())`.
        cx.update(|window, cx| {
            view.input
                .update(cx, |state, cx| state.undo(&Undo, window, cx));
        });
        assert_cursors(&mut cx, &view.input, "(a|)");
    }

    #[gpui::test]
    fn test_pair_insert_undo_removes_both(cx: &mut TestAppContext) {
        let view = InputView::<EditorMode>::new(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        setup_cursors(&mut cx, &view.input, "|");
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| {
                state.replace_text_in_range(None, "(", window, cx);
            });
        });
        assert_cursors(&mut cx, &view.input, "(|)");
        // One undo removes the whole pair (typing coalescing).
        cx.update(|window, cx| {
            view.input
                .update(cx, |state, cx| state.undo(&Undo, window, cx));
        });
        assert_cursors(&mut cx, &view.input, "|");
    }

    #[gpui::test]
    fn test_escaped_quote_does_not_skip(cx: &mut TestAppContext) {
        let view = InputView::<EditorMode>::new(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        // Odd backslashes: the typed quote is escaped, insert literally.
        setup_cursors(&mut cx, &view.input, "\"hello\\|\"");
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| {
                state.replace_text_in_range(None, "\"", window, cx);
            });
        });
        assert_cursors(&mut cx, &view.input, "\"hello\\\"|\"");
    }

    #[gpui::test]
    fn test_even_backslashes_still_skip(cx: &mut TestAppContext) {
        let view = InputView::<EditorMode>::new(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        // Even backslashes: quote is not escaped, skip over the terminator.
        setup_cursors(&mut cx, &view.input, "\"hello\\\\|\"");
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| {
                state.replace_text_in_range(None, "\"", window, cx);
            });
        });
        assert_cursors(&mut cx, &view.input, "\"hello\\\\\"|");
    }

    #[gpui::test]
    fn test_editor_options_survive_configuration_replacement(cx: &mut TestAppContext) {
        use crate::input::{BracketPair, LanguageConfig};

        let view = InputView::<EditorMode>::new(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| {
                // Language changes update rules without changing editor preferences.
                state.set_smart_indent(false, window, cx);
                crate::input::set_language_config(
                    state.language_name(),
                    LanguageConfig::default().brackets([BracketPair::new("«", "»")]),
                    cx,
                );
            });
        });
        view.input.read_with(&cx, |state, _| {
            assert!(!state.mode.is_smart_indent(), "editor option preserved");
            assert!(state.mode.is_auto_close());
            let pairs = &state.mode.language_config().unwrap().brackets;
            assert_eq!(pairs.len(), 1, "pairs follow configuration");
            assert_eq!(pairs[0].open.as_ref(), "«");
        });
    }

    struct CommentAllProvider;
    impl crate::input::SyntaxContextProvider for CommentAllProvider {
        fn context_at(&self, _text: &ropey::Rope, _offset: usize) -> crate::input::SyntaxContext {
            crate::input::SyntaxContext::Comment
        }
    }

    struct StringAllProvider;
    impl crate::input::SyntaxContextProvider for StringAllProvider {
        fn context_at(&self, _text: &ropey::Rope, _offset: usize) -> crate::input::SyntaxContext {
            crate::input::SyntaxContext::String
        }
    }

    #[gpui::test]
    fn test_smart_indent_suppressed_in_strings(cx: &mut TestAppContext) {
        use std::rc::Rc;

        let view = InputView::<EditorMode>::new(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        cx.update(|_window, cx| {
            set_test_syntax_provider(Rc::new(StringAllProvider), cx);
        });
        // Trigger `{` inside a string: no extra level, base indent only.
        setup_cursors(&mut cx, &view.input, "  x = {|");
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| {
                state.enter(
                    &Enter {
                        secondary: false,
                        shift: false,
                    },
                    window,
                    cx,
                );
            });
        });
        assert_cursors(&mut cx, &view.input, "  x = {\n  |");
    }

    #[gpui::test]
    fn test_split_suppressed_in_strings(cx: &mut TestAppContext) {
        use std::rc::Rc;

        let view = InputView::<EditorMode>::new(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        cx.update(|_window, cx| {
            set_test_syntax_provider(Rc::new(StringAllProvider), cx);
        });
        // No three-way split inside strings: plain newline instead.
        setup_cursors(&mut cx, &view.input, "{|}");
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| {
                state.enter(
                    &Enter {
                        secondary: false,
                        shift: false,
                    },
                    window,
                    cx,
                );
            });
        });
        assert_cursors(&mut cx, &view.input, "{\n|}");
    }

    #[gpui::test]
    fn test_comment_context_disables_pairing(cx: &mut TestAppContext) {
        use std::rc::Rc;

        let view = InputView::<EditorMode>::new(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        cx.update(|_window, cx| {
            set_test_syntax_provider(Rc::new(CommentAllProvider), cx);
        });
        setup_cursors(&mut cx, &view.input, "|");
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| {
                state.replace_text_in_range(None, "(", window, cx);
            });
        });
        // In comments every character is literal.
        assert_cursors(&mut cx, &view.input, "(|");
    }

    #[gpui::test]
    fn test_backspace_deletes_empty_pair(cx: &mut TestAppContext) {
        let view = InputView::<EditorMode>::new(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        setup_cursors(&mut cx, &view.input, "{|}");
        cx.update(|window, cx| {
            view.input
                .update(cx, |state, cx| state.backspace(&Backspace, window, cx));
        });
        assert_cursors(&mut cx, &view.input, "|");
    }

    #[gpui::test]
    fn test_backspace_keeps_closer_with_content(cx: &mut TestAppContext) {
        let view = InputView::<EditorMode>::new(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        setup_cursors(&mut cx, &view.input, "{d|}");
        cx.update(|window, cx| {
            view.input
                .update(cx, |state, cx| state.backspace(&Backspace, window, cx));
        });
        // Only `d` is deleted, the closing brace stays.
        assert_cursors(&mut cx, &view.input, "{|}");
    }

    #[gpui::test]
    fn test_enter_splits_brackets(cx: &mut TestAppContext) {
        let view = InputView::<EditorMode>::new(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        setup_cursors(&mut cx, &view.input, "{|}");
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| {
                state.enter(
                    &Enter {
                        secondary: false,
                        shift: false,
                    },
                    window,
                    cx,
                );
            });
        });
        assert_cursors(&mut cx, &view.input, "{\n  |\n}");
        // Selection must be collapsed: typing next must insert, not replace.
        view.input.read_with(&cx, |state, _| {
            assert!(state.active_selection().is_empty());
        });
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| {
                state.replace_text_in_range(None, "x", window, cx);
            });
        });
        assert_cursors(&mut cx, &view.input, "{\n  x|\n}");
    }

    #[gpui::test]
    fn test_enter_smart_indent_after_brace(cx: &mut TestAppContext) {
        let view = InputView::<EditorMode>::new(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        setup_cursors(&mut cx, &view.input, "fn main() {|");
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| {
                state.enter(
                    &Enter {
                        secondary: false,
                        shift: false,
                    },
                    window,
                    cx,
                );
            });
        });
        assert_cursors(&mut cx, &view.input, "fn main() {\n  |");
    }

    #[gpui::test]
    fn test_block_indent_tracks_all_preceding_edits(cx: &mut TestAppContext) {
        let view = multi_line(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        setup_cursors(&mut cx, &view.input, "|ab\n|cd\n|ef");
        cx.update(|window, cx| {
            view.input
                .update(cx, |state, cx| state.indent(true, window, cx));
        });
        assert_cursors(&mut cx, &view.input, "  |ab\n  |cd\n  |ef");
        cx.update(|window, cx| {
            view.input
                .update(cx, |state, cx| state.outdent(true, window, cx));
        });
        assert_cursors(&mut cx, &view.input, "|ab\n|cd\n|ef");
    }

    #[gpui::test]
    fn test_block_outdent_clamps_cursor_inside_indent(cx: &mut TestAppContext) {
        let view = multi_line(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        setup_cursors(&mut cx, &view.input, "ab\n | cd");
        cx.update(|window, cx| {
            view.input
                .update(cx, |state, cx| state.outdent(true, window, cx));
        });
        assert_cursors(&mut cx, &view.input, "ab\n|cd");
    }

    #[gpui::test]
    fn test_ime_restores_original_selection(cx: &mut TestAppContext) {
        let view = InputView::build(cx, |state| state);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| {
                state.set_value("abc", window, cx);
                state.set_selected_range(1..2, cx);
                state.replace_and_mark_text_in_range(None, "ni", None, window, cx);
                state.replace_text_in_range(None, "你", window, cx);
                state.undo(&Undo, window, cx);
                assert_eq!(state.value(), "abc");
                assert_eq!(state.selected_range(), 1..2);
                state.redo(&Redo, window, cx);
                assert_eq!(state.selected_range(), 4..4);
            });
        });
    }

    #[gpui::test]
    fn test_noop_does_not_change_redo_selection(cx: &mut TestAppContext) {
        let view = multi_line(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        cx.update(|window, cx| {
            view.input.update(cx, |state, cx| {
                state.set_value("abc", window, cx);
                state.set_selected_range(1..1, cx);
                state.replace_text_in_range(None, "X", window, cx);
                state.set_selected_range(0..0, cx);
                state.replace_text_in_range(None, "", window, cx);
                state.undo(&Undo, window, cx);
                state.redo(&Redo, window, cx);
                assert_eq!(state.value(), "aXbc");
                assert_eq!(state.selected_range(), 2..2);
            });
        });
    }

    #[gpui::test]
    fn test_multi_cursor_insert_text(cx: &mut TestAppContext) {
        let view = multi_line(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        let input = view.input;

        setup_cursors(&mut cx, &input, "|hello |world|");
        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.replace_text_in_range(None, ">>>", window, cx);
            });
        });
        assert_cursors(&mut cx, &input, ">>>|hello >>>|world>>>|");
    }

    #[gpui::test]
    fn test_multi_cursor_delete_backward(cx: &mut TestAppContext) {
        let view = multi_line(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        let input = view.input;

        setup_cursors(&mut cx, &input, "|islands| cars|");
        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.backspace(&Backspace, window, cx);
            });
        });
        // The first cursor has nothing to delete. The others delete an `s`.
        assert_cursors(&mut cx, &input, "|island| car|");
    }

    #[gpui::test]
    fn test_multi_cursor_delete_forward_merges(cx: &mut TestAppContext) {
        let view = multi_line(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        let input = view.input;

        setup_cursors(&mut cx, &input, "hello| |world");
        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.delete(&Delete, window, cx);
            });
        });
        // Adjacent deletions merge into a single cursor.
        assert_cursors(&mut cx, &input, "hello|orld");
    }

    #[gpui::test]
    fn test_multi_cursor_multiline_insert_and_delete(cx: &mut TestAppContext) {
        let view = multi_line(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        let input = view.input;

        setup_cursors(&mut cx, &input, "|1\n|2\n|3");
        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.replace_text_in_range(None, "a", window, cx);
            });
        });
        assert_cursors(&mut cx, &input, "a|1\na|2\na|3");

        // The whole multi-edit insert is a single undo transaction.
        input.read_with(&cx, |state, _| {
            assert_eq!(state.undo_manager.undo_count(), 1);
        });

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.backspace(&Backspace, window, cx);
            });
        });
        assert_cursors(&mut cx, &input, "|1\n|2\n|3");
    }

    #[gpui::test]
    fn test_add_cursor_below_preserves_column(cx: &mut TestAppContext) {
        let view = multi_line(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        let input = view.input;

        setup_cursors(&mut cx, &input, "ab|cd\nabcd");
        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.add_cursor_below(&AddCursorBelow, window, cx);
            });
        });
        assert_cursors(&mut cx, &input, "ab|cd\nab|cd");
    }

    #[gpui::test]
    fn test_add_cursor_at_rejects_duplicates(cx: &mut TestAppContext) {
        let view = multi_line(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        let input = view.input;

        setup_cursors(&mut cx, &input, "he|llo");
        cx.update(|_, cx| {
            input.update(cx, |state, cx| {
                // Duplicate of the existing cursor is rejected.
                state.add_cursor_at(2, cx);
                assert_eq!(state.selections.len(), 1);
                // A distinct offset adds a cursor.
                state.add_cursor_at(4, cx);
                assert_eq!(state.selections.len(), 2);
            });
        });
    }

    #[gpui::test]
    fn test_multi_cursor_undo_redo_restores_selections(cx: &mut TestAppContext) {
        let view = multi_line(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        let input = view.input;

        setup_cursors(&mut cx, &input, "|1\n|2\n|3");
        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.replace_text_in_range(None, "a", window, cx);
            });
        });
        assert_cursors(&mut cx, &input, "a|1\na|2\na|3");

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.undo(&Undo, window, cx);
            });
        });
        assert_cursors(&mut cx, &input, "|1\n|2\n|3");

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.redo(&Redo, window, cx);
            });
        });
        assert_cursors(&mut cx, &input, "a|1\na|2\na|3");
    }

    #[gpui::test]
    fn test_multi_cursor_undo_redo_different_line_lengths(cx: &mut TestAppContext) {
        let view = multi_line(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        let input = view.input;

        setup_cursors(&mut cx, &input, "abc123|\nabc12345|\nabc1234567|");
        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.replace_text_in_range(None, "a", window, cx);
            });
        });
        assert_cursors(&mut cx, &input, "abc123a|\nabc12345a|\nabc1234567a|");

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.undo(&Undo, window, cx);
            });
        });
        assert_cursors(&mut cx, &input, "abc123|\nabc12345|\nabc1234567|");

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.redo(&Redo, window, cx);
            });
        });
        assert_cursors(&mut cx, &input, "abc123a|\nabc12345a|\nabc1234567a|");
    }

    #[gpui::test]
    fn test_multi_cursor_undo_multiple_inserts(cx: &mut TestAppContext) {
        let view = multi_line(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        let input = view.input;

        setup_cursors(&mut cx, &input, "|1\n|2\n|3");
        for ch in ['a', 'b', 'c'] {
            cx.update(|window, cx| {
                input.update(cx, |state, cx| {
                    state.replace_text_in_range(None, &ch.to_string(), window, cx);
                });
            });
        }
        assert_cursors(&mut cx, &input, "abc|1\nabc|2\nabc|3");

        // The repeated keystrokes form one typing gesture.
        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                assert_eq!(state.undo_manager.undo_count(), 1);
                state.undo(&Undo, window, cx);
            });
        });
        assert_cursors(&mut cx, &input, "|1\n|2\n|3");

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.redo(&Redo, window, cx);
            });
        });
        assert_cursors(&mut cx, &input, "abc|1\nabc|2\nabc|3");
    }

    #[gpui::test]
    fn test_multi_cursor_backspace_run_is_one_undo(cx: &mut TestAppContext) {
        let view = multi_line(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        let input = view.input;

        setup_cursors(&mut cx, &input, "abc|1\nabc|2\nabc|3");
        for _ in 0..3 {
            cx.update(|window, cx| {
                input.update(cx, |state, cx| {
                    state.backspace(&Backspace, window, cx);
                });
            });
        }
        assert_cursors(&mut cx, &input, "|1\n|2\n|3");

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                assert_eq!(state.undo_manager.undo_count(), 1);
                state.undo(&Undo, window, cx);
            });
        });
        assert_cursors(&mut cx, &input, "abc|1\nabc|2\nabc|3");
    }

    #[gpui::test]
    fn test_adding_a_cursor_splits_the_typing_gesture(cx: &mut TestAppContext) {
        let view = multi_line(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        let input = view.input;

        setup_cursors(&mut cx, &input, "|1\n2\n3");
        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.replace_text_in_range(None, "a", window, cx);
                state.add_cursor_below(&AddCursorBelow, window, cx);
                state.replace_text_in_range(None, "b", window, cx);
            });
        });
        assert_cursors(&mut cx, &input, "ab|1\n2b|\n3");

        // The keystroke after the cursor was added is its own undo entry.
        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.undo(&Undo, window, cx);
            });
        });
        assert_cursors(&mut cx, &input, "a|1\n2|\n3");
    }

    #[gpui::test]
    fn test_multi_cursor_indent_is_one_undo(cx: &mut TestAppContext) {
        let view = multi_line(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        let input = view.input;

        setup_cursors(&mut cx, &input, "|1\n|2\n|3");
        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.indent_inline(&IndentInline, window, cx);
                assert_eq!(state.undo_manager.undo_count(), 1);
                state.undo(&Undo, window, cx);
            });
        });
        assert_cursors(&mut cx, &input, "|1\n|2\n|3");
    }

    #[gpui::test]
    fn test_multi_cursor_indent_then_outdent_roundtrips(cx: &mut TestAppContext) {
        let view = multi_line(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        let input = view.input;

        // Cursors at line starts.
        setup_cursors(&mut cx, &input, "|1\n|2\n|3");
        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.indent(false, window, cx);
            });
        });
        assert_cursors(&mut cx, &input, "  |1\n  |2\n  |3");

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.outdent(false, window, cx);
            });
        });
        assert_cursors(&mut cx, &input, "|1\n|2\n|3");
    }

    #[gpui::test]
    fn test_inline_outdent_only_removes_line_indentation(cx: &mut TestAppContext) {
        let view = multi_line(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        let input = view.input;

        // A mid-line indent lands at the cursor, and the outdent does not
        // take it back: it only ever removes leading line indentation.
        setup_cursors(&mut cx, &input, "1|2\n1|2");
        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.indent(false, window, cx);
            });
        });
        assert_cursors(&mut cx, &input, "1  |2\n1  |2");

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.outdent(false, window, cx);
            });
        });
        assert_cursors(&mut cx, &input, "1  |2\n1  |2");

        // A line with leading indentation loses that, wherever the cursor is.
        setup_cursors(&mut cx, &input, "  1|2\n  1|2");
        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.outdent(false, window, cx);
            });
        });
        assert_cursors(&mut cx, &input, "1|2\n1|2");
    }

    #[gpui::test]
    fn test_readonly_multi_cursor_commands_leave_state_unchanged(cx: &mut TestAppContext) {
        let view = multi_line(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        let input = view.input;

        setup_cursors(&mut cx, &input, "a|b\nc|d");
        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                let before: Vec<_> = state.selections.iter().copied().collect();
                state.set_readonly(true, cx);
                state.backspace(&Backspace, window, cx);
                state.indent_inline(&IndentInline, window, cx);

                assert_eq!(state.value(), "ab\ncd\n");
                assert_eq!(state.selections.iter().copied().collect::<Vec<_>>(), before);
            });
        });
    }

    #[gpui::test]
    fn test_multi_cursor_edit_preserves_the_active_cursor(cx: &mut TestAppContext) {
        let view = multi_line(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        let input = view.input;

        setup_cursors(&mut cx, &input, "x|\n|y");
        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                let mut selections: Vec<_> = state.selections.iter().copied().collect();
                selections.swap(0, 1);
                state.selections.replace_all(selections);
                let active_id = state.active_selection().id;
                state.replace_text_in_range(None, "!", window, cx);
                assert_eq!(state.active_selection().id, active_id);
            });
        });
    }

    #[gpui::test]
    fn test_block_indent_outdent_with_selection(cx: &mut TestAppContext) {
        let view = multi_line(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        let input = view.input;

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.set_value("line1\nline2\nline3", window, cx);
                let id = state.selections.generate_id();
                state
                    .selections
                    .replace_all(vec![CursorSelection::new(id, 0, 17)]);
                cx.notify();
            });
        });

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.indent(true, window, cx);
            });
        });
        input.read_with(&cx, |state, _| {
            assert_eq!(state.text.to_string(), "  line1\n  line2\n  line3");
        });

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.outdent(true, window, cx);
            });
        });
        input.read_with(&cx, |state, _| {
            assert_eq!(state.text.to_string(), "line1\nline2\nline3");
        });
    }

    #[gpui::test]
    fn test_multi_cursor_word_movement(cx: &mut TestAppContext) {
        let view = multi_line(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        let input = view.input;

        setup_cursors(
            &mut cx,
            &input,
            "on|e two three\none t|wo three\non|e two three",
        );

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.move_to_next_word(&MoveToNextWord, window, cx);
            });
        });
        assert_cursors(
            &mut cx,
            &input,
            "one| two three\none two| three\none| two three",
        );

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.move_to_previous_word(&MoveToPreviousWord, window, cx);
            });
        });
        assert_cursors(
            &mut cx,
            &input,
            "|one two three\none |two three\n|one two three",
        );

        // Move to end/start of document collapses to a single cursor.
        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.move_to_end(&MoveToEnd, window, cx);
            });
        });
        input.read_with(&cx, |state, _| {
            let cursors: Vec<usize> = state.selections.iter().map(|s| s.cursor_offset()).collect();
            assert_eq!(cursors, vec![state.text.len()]);
        });

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.move_to_start(&MoveToStart, window, cx);
            });
        });
        input.read_with(&cx, |state, _| {
            let cursors: Vec<usize> = state.selections.iter().map(|s| s.cursor_offset()).collect();
            assert_eq!(cursors, vec![0]);
        });
    }

    #[gpui::test]
    fn test_multi_cursor_selection_commands(cx: &mut TestAppContext) {
        let view = multi_line(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        let input = view.input;

        setup_cursors(
            &mut cx,
            &input,
            "on|e two three\none t|wo three\non|e two three",
        );
        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.select_to_start_of_line(&SelectToStartOfLine, window, cx);
            });
        });
        assert_cursors(
            &mut cx,
            &input,
            "|one two three\n|one two three\n|one two three",
        );

        // Select to document start collapses to the active cursor only.
        setup_cursors(
            &mut cx,
            &input,
            "on|e two three\none t|wo three\non|e two three",
        );
        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.select_to_start(&SelectToStart, window, cx);
            });
        });
        input.read_with(&cx, |state, _| {
            let cursors: Vec<usize> = state.selections.iter().map(|s| s.cursor_offset()).collect();
            assert_eq!(cursors, vec![0]);
        });
    }

    #[gpui::test]
    fn test_multi_cursor_replace_selection(cx: &mut TestAppContext) {
        let view = multi_line(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        let input = view.input;

        setup_cursors(&mut cx, &input, "|a\n|b\n|c");
        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.select_right(&SelectRight, window, cx);
            });
        });
        input.read_with(&cx, |state, _| {
            let ranges: Vec<_> = state.selections.iter().map(|s| (s.start, s.end)).collect();
            assert_eq!(ranges, vec![(0, 1), (2, 3), (4, 5)]);
        });

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.replace_text_in_range(None, "x", window, cx);
            });
        });
        assert_cursors(&mut cx, &input, "x|\nx|\nx|");
    }

    #[gpui::test]
    fn test_multi_cursor_escape_collapses(cx: &mut TestAppContext) {
        let view = multi_line(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        let input = view.input;

        setup_cursors(&mut cx, &input, "|a\n|b\n|c");
        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.escape(&Escape, window, cx);
            });
        });
        input.read_with(&cx, |state, _| {
            assert_eq!(state.selections.len(), 1);
        });
    }

    #[gpui::test]
    fn test_build_columnar_selection(cx: &mut TestAppContext) {
        let view = multi_line(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        let input = view.input;

        setup_cursors(&mut cx, &input, "abcd\nabcd\nabcd");
        cx.update(|_, cx| {
            input.update(cx, |state, cx| {
                // From row 0 col 1 to row 2 col 3.
                state.build_columnar_selection(
                    ColumnarPoint::new(1, 0),
                    ColumnarPoint::new(13, 0),
                    cx,
                );
                let ranges: Vec<_> = state.selections.iter().map(|s| (s.start, s.end)).collect();
                assert_eq!(ranges, vec![(1, 3), (6, 8), (11, 13)]);
            });
        });
    }

    #[gpui::test]
    fn test_columnar_selection_keeps_width_over_short_rows(cx: &mut TestAppContext) {
        let view = multi_line(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        let input = view.input;

        setup_cursors(&mut cx, &input, "abcdef\nab\nabcdef");
        cx.update(|_, cx| {
            input.update(cx, |state, cx| {
                // Ends on the short row, 3 columns past its end: the block still spans
                // columns 1..5, and only that row is clipped to what it has.
                state.build_columnar_selection(
                    ColumnarPoint::new(1, 0),
                    ColumnarPoint::new(9, 3),
                    cx,
                );
                let ranges: Vec<_> = state.selections.iter().map(|s| (s.start, s.end)).collect();
                assert_eq!(ranges, vec![(1, 5), (8, 9)]);
            });
        });
    }

    #[gpui::test]
    fn test_multi_cursor_paste_distributes_lines(cx: &mut TestAppContext) {
        let view = multi_line(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        let input = view.input;

        setup_cursors(&mut cx, &input, "|1\n|2\n|3");
        cx.update(|_, cx| {
            cx.write_to_clipboard(ClipboardItem::new_string("x\ny\nz".to_string()));
        });
        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.paste(&Paste, window, cx);
            });
        });
        // One clipboard line per cursor.
        assert_cursors(&mut cx, &input, "x|1\ny|2\nz|3");
    }

    #[gpui::test]
    fn test_paste_without_text_leaves_the_selection_alone(cx: &mut TestAppContext) {
        use gpui::{ClipboardEntry, Image, ImageFormat};

        let input_view = InputView::build(cx, |state| state);
        let mut cx = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        let input = input_view.input;

        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.set_value("hello world", window, cx);
                state.select_all(window, cx);
                cx.write_to_clipboard(ClipboardItem {
                    entries: vec![ClipboardEntry::Image(Image::from_bytes(
                        ImageFormat::Png,
                        vec![0x89, b'P', b'N', b'G'],
                    ))],
                });

                // An image-only clipboard must not replace the selection
                // with nothing.
                state.paste(&Paste, window, cx);
                assert_eq!(state.value(), "hello world");
                assert_eq!(state.selected_range(), 0..11);
            });
        });
    }

    #[gpui::test]
    fn test_paste_target_tracks_edits_and_selections(cx: &mut TestAppContext) {
        let view = multi_line(cx);
        let mut cx = VisualTestContext::from_window(view.window_handle.into(), cx);
        let input = view.input;

        setup_cursors(&mut cx, &input, "ab|c");
        let target = input.read_with(&cx, |state, _| state.paste_target());
        // Nothing happened: a paste asked for then still applies.
        assert_eq!(
            input.read_with(&cx, |state, _| state.paste_target()),
            target
        );

        // Moving the caret changes where the paste would go.
        cx.update(|_, cx| {
            input.update(cx, |state, cx| {
                let id = state.selections.generate_id();
                state
                    .selections
                    .replace_all(vec![CursorSelection::new(id, 1, 1)]);
                cx.notify();
            });
        });
        let moved = input.read_with(&cx, |state, _| state.paste_target());
        assert_ne!(moved, target);

        // Editing the text changes it too, even with the caret put back.
        cx.update(|window, cx| {
            input.update(cx, |state, cx| {
                state.replace_text_in_range_silent(None, "x", window, cx);
                let id = state.selections.generate_id();
                state
                    .selections
                    .replace_all(vec![CursorSelection::new(id, 1, 1)]);
            });
        });
        assert_ne!(input.read_with(&cx, |state, _| state.paste_target()), moved);
    }

    #[gpui::test]
    fn test_ime_candidate_bounds_fallback_before_repaint(cx: &mut TestAppContext) {
        let input_view = InputView::build_textarea(cx, |state| {
            state.default_value("这是一段已经输入的中文文字")
        });
        let mut visual = VisualTestContext::from_window(input_view.window_handle.into(), cx);
        visual.update(|window, cx| window.draw(cx).clear(cx));

        visual.update(|window, cx| {
            input_view.input.update(cx, |state, cx| {
                state.focus(window, cx);
                let len = state.text.len();
                state.set_cursor_to(len);
            });
        });
        visual.update(|window, cx| window.draw(cx).clear(cx));

        visual.update(|window, cx| {
            input_view.input.update(cx, |state, cx| {
                let bounds = state.text_bounds().unwrap_or_default();
                let before = state.selected_text_range(false, window, cx).unwrap().range;
                let previous = state
                    .bounds_for_range(before.end..before.end, bounds, window, cx)
                    .unwrap();

                state.replace_and_mark_text_in_range(None, "n", None, window, cx);

                let after = state.selected_text_range(false, window, cx).unwrap().range;
                let pending = state
                    .bounds_for_range(after.end..after.end, bounds, window, cx)
                    .unwrap();

                assert!(
                    (pending.origin.x - previous.origin.x).abs() < px(40.0),
                    "pending origin.x {:?} must remain close to previous origin.x {:?}",
                    pending.origin.x,
                    previous.origin.x
                );

                let range_bounds = state
                    .bounds_for_range(before.end..after.end, bounds, window, cx)
                    .unwrap();
                assert!(
                    (range_bounds.origin.x - previous.origin.x).abs() < px(40.0),
                    "range_bounds origin.x {:?} must remain close to previous origin.x {:?}",
                    range_bounds.origin.x,
                    previous.origin.x
                );
                assert!(range_bounds.size.width >= px(0.0));
            });
        });
    }
}

/// Methods that only a single-line input offers.
impl InputBaseState<crate::input::InputMode> {
    /// Create a single-line text input state.
    pub fn new(window: &mut Window, cx: &mut Context<Self>) -> Self {
        Self::new_in_mode(window, cx)
    }

    /// Set a custom step function of the [`super::NumberInput`].
    ///
    /// The `f` receives the current value and the [`StepAction`], and returns
    /// the step to apply, so the step can vary with the value.
    ///
    /// # Example
    ///
    /// ```ignore
    /// // At the boundary 1.0 the step is 0.1 going down and 0.5 going up.
    /// InputState::new(window, cx).step_by(|value, action, _cx| match action {
    ///     StepAction::Increment => if value < 1.0 { 0.1 } else { 0.5 },
    ///     StepAction::Decrement => if value <= 1.0 { 0.1 } else { 0.5 },
    /// })
    /// ```
    pub fn step_by(mut self, f: impl Fn(f64, StepAction, &mut App) -> f64 + 'static) -> Self {
        self.number_step = Some(NumberStep::by_value(f));
        self
    }

    /// Set with password masked state.
    pub fn masked(mut self, masked: bool) -> Self {
        self.masked = masked;
        self
    }

    /// Set the password masked state of the input field.
    pub fn set_masked(&mut self, masked: bool, _: &mut Window, cx: &mut Context<Self>) {
        self.masked = masked;
        cx.notify();
    }

    /// Set the regular expression pattern of the input field.
    pub fn pattern(mut self, pattern: regex::Regex) -> Self {
        self.pattern = Some(pattern);
        self
    }

    /// Set the regular expression pattern of the input field with reference.
    pub fn set_pattern(
        &mut self,
        pattern: regex::Regex,
        _window: &mut Window,
        _cx: &mut Context<Self>,
    ) {
        self.pattern = Some(pattern);
    }

    /// Set the validation function of the input field.
    pub fn validate(mut self, f: impl Fn(&str, &mut App) -> bool + 'static) -> Self {
        self.validate = Some(Box::new(f));
        self
    }

    pub fn set_validator(
        &mut self,
        validate: impl Fn(&str, &mut App) -> bool + 'static,
        _cx: &mut Context<Self>,
    ) {
        self.validate = Some(Box::new(validate));
    }

    /// Set the step value of the [`super::NumberInput`] for increment/decrement.
    ///
    /// If any of `step`, `min`, `max` is set, the [`super::NumberInput`] will
    /// update the value internally (step by `step`, default 1, clamp to the
    /// `min`/`max` range and emit [`InputEvent::Change`]) instead of emitting
    /// [`super::NumberInputEvent::Step`].
    ///
    /// See also [`Self::step_by`] to calculate the step value
    /// based on the current value.
    pub fn step(mut self, step: impl Into<NumberStep>) -> Self {
        self.number_step = Some(step.into());
        self
    }

    /// Set the minimum value of the [`super::NumberInput`].
    ///
    /// The value will be clamped to the minimum value on stepping and on
    /// blur (only if the clamped value passes the `pattern`/`validate` check).
    /// See also [`Self::step`].
    pub fn min(mut self, min: f64) -> Self {
        self.number_min = Some(min);
        self
    }

    /// Set the maximum value of the [`super::NumberInput`].
    ///
    /// The value will be clamped to the maximum value on stepping and on
    /// blur (only if the clamped value passes the `pattern`/`validate` check).
    /// See also [`Self::step`].
    pub fn max(mut self, max: f64) -> Self {
        self.number_max = Some(max);
        self
    }

    /// Update the step value after construction, `None` to fall back to
    /// emitting [`super::NumberInputEvent::Step`] (if `min`, `max` are unset).
    ///
    /// See [`Self::step`] and [`Self::step_by`].
    pub fn set_step(
        &mut self,
        step: impl Into<Option<NumberStep>>,
        _: &mut Window,
        _: &mut Context<Self>,
    ) {
        self.number_step = step.into();
    }

    /// Update the minimum value after construction. See [`Self::min`].
    pub fn set_min(&mut self, min: Option<f64>, _: &mut Window, _: &mut Context<Self>) {
        self.number_min = min;
    }

    /// Update the maximum value after construction. See [`Self::max`].
    pub fn set_max(&mut self, max: Option<f64>, _: &mut Window, _: &mut Context<Self>) {
        self.number_max = max;
    }

    /// Set true to show spinner at the input right.
    pub fn set_loading(&mut self, loading: bool, _: &mut Window, cx: &mut Context<Self>) {
        self.loading = loading;
        cx.notify();
    }
}

/// Methods shared by the two multi-line modes, and reachable on neither a
/// single-line input nor anything else.
impl<M: crate::input::MultiLineMode> InputBaseState<M> {
    /// Set whether text taller than the input stretches past its top and
    /// bottom and springs back when precise trackpad or Magic Mouse scrolling
    /// or its momentum runs into an end. Ordinary line-wheel scrolling does
    /// not bounce. The default follows
    /// [`crate::ScrollBounce::enabled_by_default`]: on on iOS, Android and
    /// macOS, off elsewhere. Under reduced motion the text stops at its ends
    /// without stretching.
    pub fn scroll_bounce(mut self, scroll_bounce: bool) -> Self {
        self.scroll_bounce = scroll_bounce;
        self
    }

    /// Update whether the text stretches past its ends, see
    /// [`InputBaseState::scroll_bounce`]. Turning it off drops a stretch in
    /// progress.
    pub fn set_scroll_bounce(&mut self, scroll_bounce: bool, cx: &mut Context<Self>) {
        if self.scroll_bounce != scroll_bounce {
            self.scroll_bounce = scroll_bounce;
            self.overscroll.reset();
            cx.notify();
        }
    }

    /// Whether the built-in search panel and its shortcut are enabled. Off by
    /// default, on for the code editor.
    ///
    /// This only concerns the panel. An input that is not searchable still
    /// answers [`InputBaseState::set_search_query`] and the other search
    /// methods, and lets `Ctrl-F` / `Cmd-F` bubble up to its ancestors, so an
    /// application can put its own search UI on top of the same engine.
    pub fn searchable(mut self, searchable: bool) -> Self {
        self.searchable = searchable;
        self
    }

    /// See [`InputBaseState::searchable`].
    pub fn set_searchable(&mut self, searchable: bool, cx: &mut Context<Self>) {
        self.searchable = searchable;
        cx.notify();
    }

    /// Set the soft wrap mode, default is true.
    #[doc(hidden)]
    pub fn soft_wrap(mut self, wrap: bool) -> Self {
        self.soft_wrap = wrap;
        self
    }

    /// Update the soft wrap mode, default is true.
    pub fn set_soft_wrap(&mut self, wrap: bool, _: &mut Window, cx: &mut Context<Self>) {
        self.soft_wrap = wrap;
        if wrap {
            let wrap_width = self
                .last_layout
                .as_ref()
                .and_then(|b| b.wrap_width)
                .unwrap_or(self.input_bounds.size.width);

            self.display_map.on_layout_changed(Some(wrap_width), cx);

            // Reset scroll to left 0
            let mut offset = self.scroll_handle.offset();
            offset.x = px(0.);
            self.scroll_handle.set_offset(offset);
        } else {
            self.display_map.on_layout_changed(None, cx);
        }
        cx.notify();
    }

    /// Set how soft-wrapped continuation lines are indented, default is [`WrappingIndent::Same`]
    #[doc(hidden)]
    pub fn wrapping_indent(mut self, wrapping_indent: WrappingIndent) -> Self {
        self.wrapping_indent = wrapping_indent;
        self
    }

    /// Update how soft-wrapped continuation lines are indented.
    pub fn set_wrapping_indent(
        &mut self,
        wrapping_indent: WrappingIndent,
        _: &mut Window,
        cx: &mut Context<Self>,
    ) {
        self.wrapping_indent = wrapping_indent;
        self.display_map.set_wrapping_indent(wrapping_indent, cx);
        cx.notify();
    }
}

/// Methods that only ordinary multi-line text offers.
impl InputBaseState<crate::input::TextareaMode> {
    /// Create a multi-line text state.
    ///
    /// Being multi-line is carried by the mode, not by the layout, so the
    /// default plain-text layout needs no adjustment here.
    pub fn new(window: &mut Window, cx: &mut Context<Self>) -> Self {
        Self::new_in_mode(window, cx)
    }

    pub fn set_auto_grow(&mut self, min_rows: usize, max_rows: usize, cx: &mut Context<Self>) {
        self.mode = LayoutMode::auto_grow(min_rows, max_rows.max(min_rows));
        self.mode.update_auto_grow(&self.display_map);
        cx.notify();
    }

    /// Set the number of rows for the multi-line Textarea.
    ///
    /// This is only used when `multi_line` is set to true. The input is at least
    /// this many lines tall.
    ///
    /// default: 1
    #[doc(hidden)]
    pub fn rows(mut self, rows: usize) -> Self {
        match &mut self.mode {
            LayoutMode::PlainText { rows: r, .. } | LayoutMode::CodeEditor { rows: r, .. } => {
                *r = rows
            }
            LayoutMode::AutoGrow {
                max_rows: max_r,
                rows: r,
                ..
            } => {
                *r = rows;
                *max_r = rows;
            }
        }
        self
    }

    pub fn set_rows(&mut self, rows: usize, cx: &mut Context<Self>) {
        match &mut self.mode {
            LayoutMode::PlainText { rows: value, .. }
            | LayoutMode::CodeEditor { rows: value, .. } => *value = rows,
            LayoutMode::AutoGrow {
                rows: value,
                max_rows,
                ..
            } => {
                *value = rows;
                *max_rows = rows;
            }
        }
        cx.notify();
    }

    /// Grow with the content from `min_rows` through `max_rows`.
    pub fn auto_grow(mut self, min_rows: usize, max_rows: usize) -> Self {
        self.mode = LayoutMode::auto_grow(min_rows, max_rows);
        self
    }
}

/// Methods that only a source-code editor offers.
impl InputBaseState<crate::input::EditorMode> {
    /// Create a source-code editor state.
    ///
    /// Default options: line numbers on, tab size 2 with soft tabs, indent
    /// guides on, multi-line, and search enabled. Set the language for syntax
    /// highlighting with [`Self::language`]; without one the text is shown
    /// unhighlighted.
    ///
    /// The editor aims at simple code editing or display, not at being a
    /// full-featured code editor. It offers syntax highlighting, auto indent,
    /// line numbers, and handles large text up to about 50K lines.
    pub fn new(window: &mut Window, cx: &mut Context<Self>) -> Self {
        let mut state = Self::new_in_mode(window, cx);
        state.mode = LayoutMode::code_editor(super::EditorLanguage::new(cx));
        state.searchable = true;
        state
    }

    /// Set the language to highlight, e.g. `"rust"`.
    ///
    /// See [`Self::set_highlighter`] to change it after construction.
    pub fn language(mut self, language: impl Into<SharedString>) -> Self {
        if let LayoutMode::CodeEditor {
            language: l,
            highlighter,
            ..
        } = &mut self.mode
        {
            l.set_name(language.into());
            *highlighter.borrow_mut() = None;
        }
        self
    }

    /// The current language name, e.g. `"rust"`.
    pub fn language_name(&self) -> SharedString {
        match &self.mode {
            LayoutMode::CodeEditor { language, .. } => language.name(),
            _ => SharedString::default(),
        }
    }

    /// Set enable/disable code folding.
    ///
    /// Default: true
    #[doc(hidden)]
    pub fn folding(mut self, folding: bool) -> Self {
        if let LayoutMode::CodeEditor { folding: f, .. } = &mut self.mode {
            *f = folding;
        }
        self
    }

    /// Set code folding at runtime.
    ///
    /// When disabling, all existing folds are cleared.
    pub fn set_folding(&mut self, folding: bool, _: &mut Window, cx: &mut Context<Self>) {
        if let LayoutMode::CodeEditor { folding: f, .. } = &mut self.mode {
            *f = folding;
        }
        if !folding {
            self.display_map.clear_folds();
        }
        cx.notify();
    }

    /// Unfold any folded ranges that hide the given position.
    ///
    /// Use this to reveal a position before acting on it (e.g. before
    /// [`Self::set_cursor_position`], which stops at a fold boundary),
    /// without touching folds elsewhere in the buffer. Fold candidates are
    /// kept, so the opened ranges can be folded again from the gutter.
    ///
    /// A fold keeps its own first and last line visible, so a position on
    /// either of them opens nothing. Nested folds all open, since opening
    /// only the outermost would leave the position hidden.
    ///
    /// Returns whether any fold was opened.
    pub fn unfold_at(&mut self, position: impl Into<Position>, cx: &mut Context<Self>) -> bool {
        let offset = self.text.position_to_offset(&position.into());
        let line = self.text.offset_to_point(offset).row;
        // A fold hides start_line + 1 ..= end_line - 1, so a line is hidden
        // exactly when some folded range strictly contains it.
        let covering: Vec<usize> = self
            .display_map
            .folded_ranges()
            .iter()
            .filter(|fold| line > fold.start_line && line < fold.end_line)
            .map(|fold| fold.start_line)
            .collect();
        if covering.is_empty() {
            return false;
        }

        for start_line in covering {
            self.display_map.set_folded(start_line, false);
        }
        cx.notify();
        true
    }

    /// Set enable/disable line number.
    #[doc(hidden)]
    pub fn line_number(mut self, line_number: bool) -> Self {
        if let LayoutMode::CodeEditor { line_number: l, .. } = &mut self.mode {
            *l = line_number;
        }
        self
    }

    /// Set line number.
    pub fn set_line_number(&mut self, line_number: bool, _: &mut Window, cx: &mut Context<Self>) {
        if let LayoutMode::CodeEditor { line_number: l, .. } = &mut self.mode {
            if *l == line_number {
                return;
            }
            *l = line_number;
        }
        cx.notify();
    }

    /// Set enable/disable automatic closing brackets and quotes.
    ///
    /// When enabled, typing an opener from [`LanguageConfig::auto_closing_pairs`](crate::input::language_config::LanguageConfig::auto_closing_pairs) inserts the
    /// matching closer and places the cursor inside. Typing a closer that is
    /// already present just moves past it. Default: true
    #[doc(hidden)]
    pub fn auto_close(mut self, auto_close: bool) -> Self {
        self.mode.set_auto_close(auto_close);
        self
    }

    /// Set automatic closing brackets and quotes at runtime.
    pub fn set_auto_close(&mut self, auto_close: bool, _: &mut Window, cx: &mut Context<Self>) {
        self.mode.set_auto_close(auto_close);
        cx.notify();
    }

    /// Set enable/disable smart indent on Enter.
    ///
    /// When enabled, Enter uses structural brackets and
    /// [`LanguageConfig::indentation_rules`](crate::input::language_config::LanguageConfig::indentation_rules) to choose indentation.
    /// Default: true
    #[doc(hidden)]
    pub fn smart_indent(mut self, smart_indent: bool) -> Self {
        self.mode.set_smart_indent(smart_indent);
        self
    }

    /// Set smart indent on Enter at runtime.
    pub fn set_smart_indent(&mut self, smart_indent: bool, _: &mut Window, cx: &mut Context<Self>) {
        self.mode.set_smart_indent(smart_indent);
        cx.notify();
    }
}
