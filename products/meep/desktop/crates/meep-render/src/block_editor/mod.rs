//! A Notion-style block editor: one GPUI entity over a list of blocks, with
//! one selection, one undo history and its own text element.
//!
//! - `model`: blocks, marks, positions and the edits on them (pure).
//! - `markdown`: Markdown, plain text and HTML in and out.
//! - `layout`: each block shaped once into wrapped lines, then cached.
//! - `element`: the custom element that lays out, paints and hit-tests.
//! - `editing`: every command (typing, Enter, Backspace, moving, formatting,
//!   clipboard, undo).
//! - `input`: IME and dictation through `EntityInputHandler`.
//! - `menus`: the slash menu, the block menu, the link field and the format bar.
//!
//! Per-frame work never scales with the document: layouts are cached per
//! block, block positions are recomputed only after an edit, and painting
//! touches only the visible blocks.
mod clipboard;
mod editing;
pub mod element;
mod input;
pub mod layout;
mod navigation;
mod structure;
pub use meep_script::block_editor::markdown;
mod menus;
pub use meep_script::block_editor::model;

use gpui_kit::*;
use layout::{BlockLayout, Colors};
use model::{Doc, Kind, Pos, Selection, Style};
use std::collections::HashMap;
use std::ops::Range;
use std::rc::Rc;
use std::time::Duration;
#[cfg(not(target_family = "wasm"))]
use std::time::Instant;
#[cfg(target_family = "wasm")]
use web_time::Instant;

actions!(
    block_editor,
    [
        MoveLeft,
        MoveRight,
        MoveUp,
        MoveDown,
        SelectLeft,
        SelectRight,
        SelectUp,
        SelectDown,
        MoveWordLeft,
        MoveWordRight,
        SelectWordLeft,
        SelectWordRight,
        MoveLineStart,
        MoveLineEnd,
        SelectLineStart,
        SelectLineEnd,
        MoveDocStart,
        MoveDocEnd,
        SelectDocStart,
        SelectDocEnd,
        MoveBlockStart,
        MoveBlockEnd,
        SelectBlockStart,
        SelectBlockEnd,
        Backspace,
        Delete,
        DeleteWordLeft,
        DeleteWordRight,
        DeleteLineLeft,
        DeleteLineRight,
        Enter,
        SoftBreak,
        ModEnter,
        Tab,
        ShiftTab,
        Escape,
        SelectAll,
        Undo,
        Redo,
        Copy,
        Cut,
        Paste,
        PastePlain,
        Bold,
        Italic,
        InlineCode,
        Strike,
        Link,
        TurnText,
        TurnH1,
        TurnH2,
        TurnH3,
        TurnTodo,
        TurnBullet,
        TurnNumbered,
        TurnCode,
        Duplicate,
        MoveBlocksUp,
        MoveBlocksDown,
    ]
);

const CONTEXT: &str = "BlockEditor";

/// Key bindings, active only while a block editor has focus.
pub fn bind_keys(cx: &mut App) {
    let c = Some(CONTEXT);
    cx.bind_keys([
        KeyBinding::new("left", MoveLeft, c),
        KeyBinding::new("right", MoveRight, c),
        KeyBinding::new("up", MoveUp, c),
        KeyBinding::new("down", MoveDown, c),
        KeyBinding::new("ctrl-b", MoveLeft, c),
        KeyBinding::new("ctrl-f", MoveRight, c),
        KeyBinding::new("ctrl-p", MoveUp, c),
        KeyBinding::new("ctrl-n", MoveDown, c),
        KeyBinding::new("shift-left", SelectLeft, c),
        KeyBinding::new("shift-right", SelectRight, c),
        KeyBinding::new("shift-up", SelectUp, c),
        KeyBinding::new("shift-down", SelectDown, c),
        KeyBinding::new("alt-left", MoveWordLeft, c),
        KeyBinding::new("alt-right", MoveWordRight, c),
        KeyBinding::new("alt-shift-left", SelectWordLeft, c),
        KeyBinding::new("alt-shift-right", SelectWordRight, c),
        KeyBinding::new("cmd-left", MoveLineStart, c),
        KeyBinding::new("cmd-right", MoveLineEnd, c),
        KeyBinding::new("home", MoveLineStart, c),
        KeyBinding::new("end", MoveLineEnd, c),
        KeyBinding::new("ctrl-a", MoveLineStart, c),
        KeyBinding::new("ctrl-e", MoveLineEnd, c),
        KeyBinding::new("cmd-shift-left", SelectLineStart, c),
        KeyBinding::new("cmd-shift-right", SelectLineEnd, c),
        KeyBinding::new("shift-home", SelectLineStart, c),
        KeyBinding::new("shift-end", SelectLineEnd, c),
        KeyBinding::new("cmd-up", MoveDocStart, c),
        KeyBinding::new("cmd-down", MoveDocEnd, c),
        KeyBinding::new("shift-ctrl-home", SelectDocStart, c),
        KeyBinding::new("shift-ctrl-end", SelectDocEnd, c),
        KeyBinding::new("alt-up", MoveBlockStart, c),
        KeyBinding::new("alt-down", MoveBlockEnd, c),
        KeyBinding::new("alt-shift-up", SelectBlockStart, c),
        KeyBinding::new("alt-shift-down", SelectBlockEnd, c),
        KeyBinding::new("backspace", Backspace, c),
        KeyBinding::new("shift-backspace", Backspace, c),
        KeyBinding::new("ctrl-h", Backspace, c),
        KeyBinding::new("delete", Delete, c),
        KeyBinding::new("ctrl-d", Delete, c),
        KeyBinding::new("alt-backspace", DeleteWordLeft, c),
        KeyBinding::new("alt-delete", DeleteWordRight, c),
        KeyBinding::new("cmd-backspace", DeleteLineLeft, c),
        KeyBinding::new("cmd-delete", DeleteLineRight, c),
        KeyBinding::new("ctrl-k", DeleteLineRight, c),
        KeyBinding::new("enter", Enter, c),
        KeyBinding::new("shift-enter", SoftBreak, c),
        KeyBinding::new("cmd-enter", ModEnter, c),
        KeyBinding::new("tab", Tab, c),
        KeyBinding::new("shift-tab", ShiftTab, c),
        KeyBinding::new("escape", Escape, c),
        KeyBinding::new("cmd-a", SelectAll, c),
        KeyBinding::new("cmd-z", Undo, c),
        KeyBinding::new("cmd-shift-z", Redo, c),
        KeyBinding::new("cmd-y", Redo, c),
        KeyBinding::new("cmd-c", Copy, c),
        KeyBinding::new("cmd-x", Cut, c),
        KeyBinding::new("cmd-v", Paste, c),
        KeyBinding::new("cmd-shift-v", PastePlain, c),
        KeyBinding::new("cmd-b", Bold, c),
        KeyBinding::new("cmd-i", Italic, c),
        KeyBinding::new("cmd-e", InlineCode, c),
        KeyBinding::new("cmd-shift-s", Strike, c),
        KeyBinding::new("cmd-shift-x", Strike, c),
        KeyBinding::new("cmd-k", Link, c),
        KeyBinding::new("cmd-alt-0", TurnText, c),
        KeyBinding::new("cmd-alt-1", TurnH1, c),
        KeyBinding::new("cmd-alt-2", TurnH2, c),
        KeyBinding::new("cmd-alt-3", TurnH3, c),
        KeyBinding::new("cmd-alt-4", TurnTodo, c),
        KeyBinding::new("cmd-alt-5", TurnBullet, c),
        KeyBinding::new("cmd-alt-6", TurnNumbered, c),
        KeyBinding::new("cmd-alt-8", TurnCode, c),
        KeyBinding::new("cmd-d", Duplicate, c),
        // Notion moves blocks with ⌘⇧↑ and ⌘⇧↓.
        KeyBinding::new("cmd-shift-up", MoveBlocksUp, c),
        KeyBinding::new("cmd-shift-down", MoveBlocksDown, c),
    ]);
    menus::bind_keys(cx);
}

pub enum BlockEditorEvent {
    /// The document changed: sent after typing pauses, and on blur.
    Change,
}

impl EventEmitter<BlockEditorEvent> for BlockEditor {}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub(crate) enum EditKind {
    Typing,
    Deleting,
    Other,
}

#[derive(Clone)]
struct Snapshot {
    blocks: Vec<Rc<model::Block>>,
    selection: Selection,
}

struct Entry {
    before: Snapshot,
    after: Selection,
    kind: EditKind,
    at: Instant,
}

#[derive(Default)]
struct History {
    undo: Vec<Entry>,
    redo: Vec<Entry>,
}

const HISTORY: usize = 500;

/// Block positions for the current document and width, rebuilt only after
/// an edit, a resize or a theme change.
#[derive(Default)]
pub struct Geometry {
    generation: u64,
    width: Pixels,
    colors: u64,
    pub layouts: Vec<Rc<BlockLayout>>,
    /// Top of each block's box (after its margin), from the content top.
    pub tops: Vec<Pixels>,
    pub numbers: Vec<u32>,
    pub(crate) markers: Vec<Pixels>,
    pub(crate) total: Pixels,
    valid: bool,
}

/// What the pointer is over in the left gutter.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub(crate) enum GutterPart {
    None,
    Plus,
    Handle,
}

#[derive(Clone, Copy)]
pub(crate) struct Hover {
    pub(crate) block: usize,
    pub(crate) part: GutterPart,
    pub(crate) since: Instant,
    pub(crate) checkbox: bool,
}

/// A pointer gesture in progress.
pub(crate) enum Gesture {
    /// Selecting text: by character, word or block from where it started.
    Select { unit: u8, origin: Selection },
    /// Pressed the handle: a click opens the block menu, a drag moves.
    Handle {
        block: usize,
        start: Point<Pixels>,
        moving: bool,
        span: Range<usize>,
        target: usize,
        pointer: Point<Pixels>,
        indicator: Option<Pixels>,
    },
}

/// The open popover, if any.
pub enum Menu {
    /// `/` typed at `offset` in `block`.
    Slash {
        block: usize,
        offset: usize,
        selected: usize,
    },
    /// The handle's menu for a block.
    Block { block: usize, selected: usize },
    /// The link field (⌘K or the format bar).
    Link {
        input: Entity<gpui_kit::component::input::InputState>,
        ranges: Vec<(usize, Range<usize>)>,
        _subscription: Subscription,
    },
}

pub struct BlockEditor {
    pub(crate) doc: Doc,
    pub(crate) sel: Selection,
    /// The caret at a soft wrap is drawn at the end of the row above.
    pub(crate) upstream: bool,
    /// The column Up and Down keep, from the content's left edge.
    pub(crate) goal_x: Option<Pixels>,
    /// IME composition: block and range of the marked text.
    pub(crate) marked: Option<(usize, Range<usize>)>,
    /// Styles the next typed text takes (⌘B with nothing selected, or after
    /// a Markdown shortcut closed a mark).
    pub(crate) pending: Option<Vec<Style>>,
    history: History,
    pub(crate) focus: FocusHandle,
    pub(crate) focused: bool,
    pub(crate) read_only: bool,
    pub(crate) placeholder: Option<SharedString>,
    pub(crate) gutter: bool,
    /// Bumped by every change to the document or composition.
    generation: u64,
    cache: HashMap<Rc<str>, Rc<BlockLayout>>,
    pub(crate) geo: Geometry,
    pub(crate) colors: Colors,
    pub(crate) caret_on: bool,
    blink_epoch: u64,
    _blink: Option<Task<()>>,
    pub(crate) hover: Option<Hover>,
    pub(crate) gesture: Option<Gesture>,
    pub(crate) menu: Option<Menu>,
    /// The document element's last bounds, in window coordinates.
    pub(crate) bounds: Bounds<Pixels>,
    pub(crate) scroll: ScrollHandle,
    pub(crate) menu_scroll: ScrollHandle,
    /// Scroll the caret into view on the next render.
    pub(crate) autoscroll: bool,
    changed: bool,
    _debounce: Option<Task<()>>,
    _subscriptions: Vec<Subscription>,
    /// Typing hides the gutter controls until the pointer moves.
    pub(crate) typing: bool,
}

impl BlockEditor {
    pub fn new(window: &mut Window, cx: &mut Context<Self>) -> Self {
        let _ = window;
        let focus = cx.focus_handle();
        let subscriptions = Vec::new();
        Self {
            doc: Doc::new(vec![]),
            sel: Selection::default(),
            upstream: false,
            goal_x: None,
            marked: None,
            pending: None,
            history: History::default(),
            focus,
            focused: false,
            read_only: false,
            placeholder: None,
            gutter: true,
            generation: 1,
            cache: HashMap::new(),
            geo: Geometry::default(),
            colors: Colors::current(),
            caret_on: true,
            blink_epoch: 0,
            _blink: None,
            hover: None,
            gesture: None,
            menu: None,
            bounds: Bounds::default(),
            scroll: ScrollHandle::new(),
            menu_scroll: ScrollHandle::new(),
            autoscroll: false,
            changed: false,
            _debounce: None,
            _subscriptions: subscriptions,
            typing: false,
        }
    }

    // ---- The script's side ----------------------------------------------------

    pub fn to_json(&self) -> serde_json::Value {
        self.doc.to_json()
    }
    pub fn markdown(&self) -> String {
        markdown::to_markdown(&self.doc.blocks)
    }
    /// Replaces the document (the script set a new value). The caret stays
    /// where it was as far as the new document allows.
    pub fn set_doc(&mut self, doc: Doc, cx: &mut Context<Self>) {
        self.doc = doc;
        self.doc.ensure_nonempty();
        self.history = History::default();
        self.marked = None;
        self.menu = None;
        self.gesture = None;
        self.sel = Selection::range(
            self.doc.clamp(self.sel.anchor),
            self.doc.clamp(self.sel.head),
        );
        self.bump();
        cx.notify();
    }
    pub fn set_json(&mut self, value: &serde_json::Value, cx: &mut Context<Self>) {
        self.set_doc(Doc::from_json(value), cx);
    }
    pub fn set_markdown(&mut self, source: &str, cx: &mut Context<Self>) {
        self.set_doc(Doc::new(markdown::from_markdown(source)), cx);
    }
    pub fn set_read_only(&mut self, read_only: bool, cx: &mut Context<Self>) {
        if self.read_only != read_only {
            self.read_only = read_only;
            self.gutter = !read_only;
            self.menu = None;
            self.geo.valid = false;
            cx.notify();
        }
    }
    pub fn set_placeholder(&mut self, placeholder: Option<SharedString>, cx: &mut Context<Self>) {
        if self.placeholder != placeholder {
            self.placeholder = placeholder;
            cx.notify();
        }
    }
    pub fn focus_handle(&self) -> FocusHandle {
        self.focus.clone()
    }

    // ---- Bookkeeping ------------------------------------------------------------

    fn bump(&mut self) {
        self.generation += 1;
        self.geo.valid = false;
    }

    /// Tell the script after typing pauses, never once per keystroke.
    fn schedule_change(&mut self, cx: &mut Context<Self>) {
        self.changed = true;
        self._debounce = Some(cx.spawn(async move |this, cx| {
            cx.background_executor()
                .timer(Duration::from_millis(350))
                .await;
            let _ = this.update(cx, |this, cx| this.flush_change(cx));
        }));
    }

    pub fn flush_change(&mut self, cx: &mut Context<Self>) {
        self._debounce = None;
        if self.changed {
            self.changed = false;
            cx.emit(BlockEditorEvent::Change);
        }
    }

    /// Follows keyboard focus, checked as the document paints: focus
    /// listeners registered while a script view renders never fired.
    pub(crate) fn sync_focus(&mut self, window: &Window, cx: &mut Context<Self>) {
        let focused = self.focus.is_focused(window);
        if focused == self.focused {
            return;
        }
        self.focused = focused;
        if focused {
            self.restart_blink(cx);
        } else {
            self.marked = None;
            self.gesture = None;
            if matches!(
                self.menu,
                Some(Menu::Slash { .. }) | Some(Menu::Block { .. })
            ) {
                self.menu = None;
            }
            self.flush_change(cx);
        }
        cx.notify();
    }

    pub(crate) fn restart_blink(&mut self, cx: &mut Context<Self>) {
        self.caret_on = true;
        self.blink_epoch += 1;
        let epoch = self.blink_epoch;
        self._blink = Some(cx.spawn(async move |this, cx| {
            loop {
                cx.background_executor()
                    .timer(Duration::from_millis(530))
                    .await;
                let go = this
                    .update(cx, |this, cx| {
                        if this.blink_epoch != epoch || !this.focused {
                            return false;
                        }
                        this.caret_on = !this.caret_on;
                        cx.notify();
                        true
                    })
                    .unwrap_or(false);
                if !go {
                    break;
                }
            }
        }));
    }

    /// The layout of every block at `width` (the document element's width),
    /// reusing every block that has not changed.
    pub(crate) fn ensure_layout(&mut self, width: Pixels, window: &mut Window) {
        let colors = Colors::current();
        if self.geo.valid
            && self.geo.generation == self.generation
            && self.geo.width == width
            && self.geo.colors == colors.key
        {
            return;
        }
        self.colors = colors;
        let gutter = self.gutter_width();
        let content = (width - gutter).max(px(80.));
        let n = self.doc.len();
        let mut layouts = Vec::with_capacity(n);
        let mut tops = Vec::with_capacity(n);
        let mut numbers = Vec::with_capacity(n);
        let mut markers = Vec::with_capacity(n);
        let mut y = px(0.);
        // Numbers per depth, restarting after any other block at that depth.
        let mut counters: Vec<u32> = Vec::new();
        let mut digit_widths: HashMap<usize, Pixels> = HashMap::new();
        let mut prev_margin = px(0.);
        for i in 0..n {
            let block = self.doc.blocks[i].clone();
            let depth = block.indent as usize;
            if counters.len() > depth + 1 {
                counters.truncate(depth + 1);
            }
            while counters.len() <= depth {
                counters.push(0);
            }
            let number = if block.kind == Kind::Numbered {
                counters[depth] += 1;
                counters[depth]
            } else {
                if !(block.kind == Kind::Paragraph && depth > 0) {
                    counters[depth] = 0;
                }
                0
            };
            let marker = if block.kind == Kind::Numbered {
                let label = numbered_label(number, block.indent);
                let w = *digit_widths.entry(label.len()).or_insert_with(|| {
                    let sample: String = "8".repeat(label.len().saturating_sub(1)) + ".";
                    layout::shape_line(&sample, 16., colors.ink, FontWeight::NORMAL, window).width()
                });
                (w + px(8.)).max(px(layout::MARKER))
            } else {
                px(layout::MARKER)
            };
            let indent = px(layout::INDENT * block.indent as f32);
            let key = layout::LayoutKey {
                rev: block.rev,
                width: content - indent,
                colors: colors.key,
                marker,
                marked: self
                    .marked
                    .as_ref()
                    .filter(|(b, _)| *b == i)
                    .map(|(_, r)| r.clone()),
            };
            let cached = self
                .cache
                .get(&block.id)
                .filter(|l| l.key == key && l.kind == block.kind)
                .cloned();
            let laid = match cached {
                Some(l) => l,
                None => {
                    let l = Rc::new(layout::layout_block(&block, key, &colors, window));
                    self.cache.insert(block.id.clone(), l.clone());
                    l
                }
            };
            let m = laid.metrics;
            if i > 0 {
                y += prev_margin + px(m.margin_top);
            }
            prev_margin = px(m.margin_bottom);
            tops.push(y);
            y += laid.height;
            layouts.push(laid);
            numbers.push(number);
            markers.push(marker);
        }
        if self.cache.len() > n * 2 + 64 {
            let ids: std::collections::HashSet<&str> =
                self.doc.blocks.iter().map(|b| &*b.id).collect();
            self.cache.retain(|id, _| ids.contains(&**id));
        }
        self.geo = Geometry {
            generation: self.generation,
            width,
            colors: colors.key,
            layouts,
            tops,
            numbers,
            markers,
            total: y + prev_margin,
            valid: true,
        };
    }

    pub(crate) fn gutter_width(&self) -> Pixels {
        if self.gutter && !self.read_only {
            px(layout::GUTTER)
        } else {
            px(0.)
        }
    }

    /// A block's left edge (after indent), from the element's left.
    pub(crate) fn block_left(&self, i: usize) -> Pixels {
        self.gutter_width() + px(layout::INDENT * self.doc.blocks[i].indent as f32)
    }

    /// A block's text origin, from the element's top-left.
    pub(crate) fn text_origin(&self, i: usize) -> Point<Pixels> {
        let l = &self.geo.layouts[i];
        point(self.block_left(i) + l.text_x, self.geo.tops[i] + l.text_y)
    }

    /// The caret's top-left and height, from the element's top-left.
    pub fn caret_rect(&self, pos: Pos, upstream: bool) -> Option<Bounds<Pixels>> {
        let l = self.geo.layouts.get(pos.block)?;
        let origin = self.text_origin(pos.block);
        let at = l.caret(pos.offset, upstream);
        let h = l.caret_height();
        let y = origin.y + at.y + (l.line_height - h) / 2.;
        Some(Bounds::new(point(origin.x + at.x, y), size(px(2.), h)))
    }

    /// The block at y (from the element's top), nearest when between blocks.
    pub(crate) fn block_at_y(&self, y: Pixels) -> usize {
        let tops = &self.geo.tops;
        if tops.is_empty() {
            return 0;
        }
        let i = tops.partition_point(|t| *t <= y).saturating_sub(1);
        let bottom = tops[i] + self.geo.layouts[i].height;
        if y > bottom && i + 1 < tops.len() {
            let gap_mid = (bottom + tops[i + 1]) / 2.;
            if y >= gap_mid {
                return i + 1;
            }
        }
        i
    }

    /// The text position at a point (from the element's top-left).
    pub(crate) fn pos_at(&self, p: Point<Pixels>) -> (Pos, bool) {
        if self.geo.layouts.is_empty() {
            return (Pos::default(), false);
        }
        if p.y > self.geo.total {
            return (self.doc.end(), false);
        }
        let i = self.block_at_y(p.y);
        let l = &self.geo.layouts[i];
        if l.kind == Kind::Divider {
            return (Pos::new(i, 0), false);
        }
        let origin = self.text_origin(i);
        let row = l.row_at(p.y - origin.y);
        let (offset, upstream) = l.offset_at(row, p.x - origin.x);
        (Pos::new(i, offset), upstream)
    }

    /// Visible block range for a y-range (from the element's top).
    pub(crate) fn visible(&self, y0: Pixels, y1: Pixels) -> Range<usize> {
        let tops = &self.geo.tops;
        let n = tops.len();
        if n == 0 {
            return 0..0;
        }
        let first = tops.partition_point(|t| *t <= y0).saturating_sub(1);
        let mut last = tops.partition_point(|t| *t < y1);
        last = last.clamp(first + 1, n);
        // A tall block that starts above the view still shows.
        first.min(n - 1)..last
    }

    /// Scrolls the editor so the caret stays in view (when it scrolls itself).
    fn scroll_caret_into_view(&mut self, window: &mut Window) {
        let viewport = self.scroll.bounds();
        if viewport.size.height <= px(0.) || self.bounds.size.width <= px(0.) {
            return;
        }
        self.ensure_layout(self.bounds.size.width, window);
        let Some(caret) = self.caret_rect(self.sel.head, self.upstream) else {
            return;
        };
        let offset = self.scroll.offset();
        // Content y of the caret relative to the scroll container's top.
        let doc_top = self.bounds.origin.y - viewport.origin.y - offset.y;
        let top = doc_top + caret.origin.y;
        let bottom = top + caret.size.height;
        let margin = px(24.);
        let height = viewport.size.height;
        let mut y = -offset.y;
        if top - margin < y {
            y = (top - margin).max(px(0.));
        } else if bottom + margin > y + height {
            y = bottom + margin - height;
        }
        let max = self.scroll.max_offset().y;
        let y = y.clamp(px(0.), max.max(px(0.)));
        if y != -offset.y {
            self.scroll.set_offset(point(offset.x, -y));
        }
    }
}

pub fn numbered_label(n: u32, indent: u8) -> String {
    match indent % 3 {
        1 => {
            // a. b. … z. aa.
            let mut n = n.max(1) - 1;
            let mut s = String::new();
            loop {
                s.insert(0, (b'a' + (n % 26) as u8) as char);
                if n < 26 {
                    break;
                }
                n = n / 26 - 1;
            }
            format!("{s}.")
        }
        2 => format!("{}.", roman(n)),
        _ => format!("{n}."),
    }
}

fn roman(mut n: u32) -> String {
    let table = [
        (1000, "m"),
        (900, "cm"),
        (500, "d"),
        (400, "cd"),
        (100, "c"),
        (90, "xc"),
        (50, "l"),
        (40, "xl"),
        (10, "x"),
        (9, "ix"),
        (5, "v"),
        (4, "iv"),
        (1, "i"),
    ];
    let mut s = String::new();
    for (v, r) in table {
        while n >= v {
            s.push_str(r);
            n -= v;
        }
    }
    s
}

impl Focusable for BlockEditor {
    fn focus_handle(&self, _: &App) -> FocusHandle {
        self.focus.clone()
    }
}

impl Render for BlockEditor {
    fn render(&mut self, window: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        if self.autoscroll {
            self.autoscroll = false;
            self.scroll_caret_into_view(window);
        }
        let entity = cx.entity();
        let editor = div()
            .id("block-editor")
            .key_context(CONTEXT)
            .track_focus(&self.focus)
            .w_full()
            .h_full()
            .min_h_0()
            .overflow_y_scroll()
            .track_scroll(&self.scroll)
            .on_action(
                cx.listener(|e, _: &MoveLeft, w, cx| e.horizontal(false, false, false, w, cx)),
            )
            .on_action(
                cx.listener(|e, _: &MoveRight, w, cx| e.horizontal(true, false, false, w, cx)),
            )
            .on_action(
                cx.listener(|e, _: &SelectLeft, w, cx| e.horizontal(false, true, false, w, cx)),
            )
            .on_action(
                cx.listener(|e, _: &SelectRight, w, cx| e.horizontal(true, true, false, w, cx)),
            )
            .on_action(
                cx.listener(|e, _: &MoveWordLeft, w, cx| e.horizontal(false, false, true, w, cx)),
            )
            .on_action(
                cx.listener(|e, _: &MoveWordRight, w, cx| e.horizontal(true, false, true, w, cx)),
            )
            .on_action(
                cx.listener(|e, _: &SelectWordLeft, w, cx| e.horizontal(false, true, true, w, cx)),
            )
            .on_action(
                cx.listener(|e, _: &SelectWordRight, w, cx| e.horizontal(true, true, true, w, cx)),
            )
            .on_action(cx.listener(|e, _: &MoveUp, w, cx| e.vertical(false, false, w, cx)))
            .on_action(cx.listener(|e, _: &MoveDown, w, cx| e.vertical(true, false, w, cx)))
            .on_action(cx.listener(|e, _: &SelectUp, w, cx| e.vertical(false, true, w, cx)))
            .on_action(cx.listener(|e, _: &SelectDown, w, cx| e.vertical(true, true, w, cx)))
            .on_action(cx.listener(|e, _: &MoveLineStart, w, cx| e.line_edge(false, false, w, cx)))
            .on_action(cx.listener(|e, _: &MoveLineEnd, w, cx| e.line_edge(true, false, w, cx)))
            .on_action(cx.listener(|e, _: &SelectLineStart, w, cx| e.line_edge(false, true, w, cx)))
            .on_action(cx.listener(|e, _: &SelectLineEnd, w, cx| e.line_edge(true, true, w, cx)))
            .on_action(cx.listener(|e, _: &MoveDocStart, w, cx| e.doc_edge(false, false, w, cx)))
            .on_action(cx.listener(|e, _: &MoveDocEnd, w, cx| e.doc_edge(true, false, w, cx)))
            .on_action(cx.listener(|e, _: &SelectDocStart, w, cx| e.doc_edge(false, true, w, cx)))
            .on_action(cx.listener(|e, _: &SelectDocEnd, w, cx| e.doc_edge(true, true, w, cx)))
            .on_action(
                cx.listener(|e, _: &MoveBlockStart, w, cx| e.block_edge(false, false, w, cx)),
            )
            .on_action(cx.listener(|e, _: &MoveBlockEnd, w, cx| e.block_edge(true, false, w, cx)))
            .on_action(
                cx.listener(|e, _: &SelectBlockStart, w, cx| e.block_edge(false, true, w, cx)),
            )
            .on_action(cx.listener(|e, _: &SelectBlockEnd, w, cx| e.block_edge(true, true, w, cx)))
            .on_action(cx.listener(|e, _: &Backspace, w, cx| e.backspace(w, cx)))
            .on_action(cx.listener(|e, _: &Delete, w, cx| e.delete_forward(w, cx)))
            .on_action(cx.listener(|e, _: &DeleteWordLeft, w, cx| {
                e.delete_by(editing::Unit::Word, false, w, cx)
            }))
            .on_action(cx.listener(|e, _: &DeleteWordRight, w, cx| {
                e.delete_by(editing::Unit::Word, true, w, cx)
            }))
            .on_action(cx.listener(|e, _: &DeleteLineLeft, w, cx| {
                e.delete_by(editing::Unit::Line, false, w, cx)
            }))
            .on_action(cx.listener(|e, _: &DeleteLineRight, w, cx| {
                e.delete_by(editing::Unit::Line, true, w, cx)
            }))
            .on_action(cx.listener(|e, _: &Enter, w, cx| e.enter(w, cx)))
            .on_action(cx.listener(|e, _: &SoftBreak, w, cx| e.soft_break(w, cx)))
            .on_action(cx.listener(|e, _: &ModEnter, w, cx| e.mod_enter(w, cx)))
            .on_action(cx.listener(|e, _: &Tab, w, cx| e.tab(false, w, cx)))
            .on_action(cx.listener(|e, _: &ShiftTab, w, cx| e.tab(true, w, cx)))
            .on_action(cx.listener(|e, _: &Escape, w, cx| e.escape(w, cx)))
            .on_action(cx.listener(|e, _: &SelectAll, w, cx| e.select_all(w, cx)))
            .on_action(cx.listener(|e, _: &Undo, w, cx| e.undo(w, cx)))
            .on_action(cx.listener(|e, _: &Redo, w, cx| e.redo(w, cx)))
            .on_action(cx.listener(|e, _: &Copy, w, cx| e.copy(false, w, cx)))
            .on_action(cx.listener(|e, _: &Cut, w, cx| e.copy(true, w, cx)))
            .on_action(cx.listener(|e, _: &Paste, w, cx| e.paste(false, w, cx)))
            .on_action(cx.listener(|e, _: &PastePlain, w, cx| e.paste(true, w, cx)))
            .on_action(cx.listener(|e, _: &Bold, w, cx| e.toggle_style(Style::Bold, w, cx)))
            .on_action(cx.listener(|e, _: &Italic, w, cx| e.toggle_style(Style::Italic, w, cx)))
            .on_action(cx.listener(|e, _: &InlineCode, w, cx| e.toggle_style(Style::Code, w, cx)))
            .on_action(cx.listener(|e, _: &Strike, w, cx| e.toggle_style(Style::Strike, w, cx)))
            .on_action(cx.listener(|e, _: &Link, w, cx| e.open_link(w, cx)))
            .on_action(cx.listener(|e, _: &TurnText, w, cx| e.turn_into(Kind::Paragraph, w, cx)))
            .on_action(cx.listener(|e, _: &TurnH1, w, cx| e.turn_into(Kind::H1, w, cx)))
            .on_action(cx.listener(|e, _: &TurnH2, w, cx| e.turn_into(Kind::H2, w, cx)))
            .on_action(cx.listener(|e, _: &TurnH3, w, cx| e.turn_into(Kind::H3, w, cx)))
            .on_action(cx.listener(|e, _: &TurnTodo, w, cx| e.turn_into(Kind::Todo, w, cx)))
            .on_action(cx.listener(|e, _: &TurnBullet, w, cx| e.turn_into(Kind::Bullet, w, cx)))
            .on_action(cx.listener(|e, _: &TurnNumbered, w, cx| e.turn_into(Kind::Numbered, w, cx)))
            .on_action(cx.listener(|e, _: &TurnCode, w, cx| e.turn_into(Kind::Code, w, cx)))
            .on_action(cx.listener(|e, _: &Duplicate, w, cx| e.duplicate(w, cx)))
            .on_action(cx.listener(|e, _: &MoveBlocksUp, w, cx| e.move_blocks(false, w, cx)))
            .on_action(cx.listener(|e, _: &MoveBlocksDown, w, cx| e.move_blocks(true, w, cx)))
            .child(element::DocumentElement::new(entity));
        div()
            .relative()
            .w_full()
            .h_full()
            .min_h_0()
            .flex()
            .flex_col()
            .child(editor)
            .children(self.render_overlays(window, cx))
    }
}
