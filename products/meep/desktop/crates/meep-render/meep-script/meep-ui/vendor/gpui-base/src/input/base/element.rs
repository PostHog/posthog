use crate::input::{DisplayMap, FoldRange, InputExtras as _, InputModeKind, OverviewRulerLane};
use gpui::Corners;
use gpui::Half;
use gpui::{
    AnyElement, App, Bounds, Edges, Element, ElementId, ElementInputHandler, Entity,
    GlobalElementId,
};
use gpui::{
    HighlightStyle, Hitbox, HitboxBehavior, Hsla, InteractiveElement, IntoElement, LayoutId,
    LongPressEvent, MouseButton, MouseMoveEvent, MouseUpEvent, PaintQuad, ParentElement as _, Path,
    Pixels, Point, Position, ShapedLine, SharedString, Size, Style, Styled as _, TextAlign,
    TextRun, TextStyle, TouchDragEvent, TouchPhase, UnderlineStyle, Window, fill, point, px,
    relative, size,
};
use ropey::Rope;
use smallvec::SmallVec;
use std::{ops::Range, rc::Rc};

use crate::{
    Scrollbar,
    input::{RopeExt as _, blink_cursor::CURSOR_WIDTH, display_map::LineLayout},
};

use super::{
    InputBaseState, PrepaintCaretGeometry, RangeDecorationStyle, TextDecoration,
    layout::{LastLayout, WhitespaceIndicators},
    mode::LayoutMode,
    tab_stops::{expand_tabs, expanded_width, tab_stop_width},
};

fn diagnostic_highlight_style(
    severity: crate::input::DiagnosticSeverity,
    colors: crate::input::DiagnosticColors,
) -> HighlightStyle {
    let color = match severity {
        crate::input::DiagnosticSeverity::Error => colors.error,
        crate::input::DiagnosticSeverity::Warning => colors.warning,
        crate::input::DiagnosticSeverity::Info => colors.info,
        crate::input::DiagnosticSeverity::Hint => colors.hint,
    };
    HighlightStyle {
        underline: Some(UnderlineStyle {
            color: Some(color),
            thickness: px(1.),
            wavy: true,
        }),
        ..Default::default()
    }
}

const BOTTOM_MARGIN_ROWS: usize = 3;
pub(super) const RIGHT_MARGIN: Pixels = px(10.);
pub(super) const LINE_NUMBER_RIGHT_MARGIN: Pixels = px(6.);
const FOLD_ICON_WIDTH: Pixels = px(14.);
const FOLD_ICON_HITBOX_WIDTH: Pixels = px(18.);
/// Space between the gutter decoration strip and the line numbers.
const GUTTER_DECORATION_GAP: Pixels = px(4.);
/// Height of the pill an empty gutter decoration paints on a line boundary.
const GUTTER_BOUNDARY_MARK_HEIGHT: Pixels = px(8.);
const MIN_OVERVIEW_RULER_MARK_HEIGHT: Pixels = px(6.);
const MAX_HIGHLIGHT_LINE_LENGTH: usize = 10_000;
const MIN_LINE_NUMBER_DIGITS: usize = 3;
const MAX_LINE_NUMBER_DIGITS: usize = 7;
const MAX_DISPLAYED_LINE_NUMBER: usize = 9_999_999;

fn line_number_len(total_lines: usize) -> usize {
    (total_lines.max(1).ilog10() as usize + 1).clamp(MIN_LINE_NUMBER_DIGITS, MAX_LINE_NUMBER_DIGITS)
}

fn displayed_line_number(number: usize) -> usize {
    number.min(MAX_DISPLAYED_LINE_NUMBER)
}
const FOLD_CHEVRON_RIGHT_SVG: &[u8] = br#"<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m9 18 6-6-6-6"/></svg>"#;
const FOLD_CHEVRON_DOWN_SVG: &[u8] = br#"<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg>"#;

fn compose_decorations(
    mut styles: Vec<(Range<usize>, HighlightStyle)>,
    decorations: impl IntoIterator<Item = (Range<usize>, HighlightStyle)>,
    visible_byte_range: Range<usize>,
) -> Option<Vec<(Range<usize>, HighlightStyle)>> {
    let mut visible_decorations = decorations
        .into_iter()
        .filter_map(|(range, style)| {
            let range =
                range.start.max(visible_byte_range.start)..range.end.min(visible_byte_range.end);
            (!range.is_empty()).then_some((range, style))
        })
        .peekable();

    if visible_decorations.peek().is_none() {
        return (!styles.is_empty()).then_some(styles);
    }
    if styles.is_empty() {
        styles.push((visible_byte_range.clone(), HighlightStyle::default()));
    }

    // Decorations are application-authored overrides and must win over syntax
    // and semantic highlighting when both set the same style property.
    Some(gpui::combine_highlights(styles, visible_decorations).collect())
}

fn compose_decoration_collections<'a>(
    mut styles: Vec<(Range<usize>, HighlightStyle)>,
    collections: impl IntoIterator<Item = &'a [TextDecoration]>,
    visible_byte_range: Range<usize>,
) -> Option<Vec<(Range<usize>, HighlightStyle)>> {
    // Apply collections in reverse creation order so the first collection is
    // composed last and retains its documented precedence.
    let collections = collections.into_iter().collect::<Vec<_>>();
    for decorations in collections.into_iter().rev() {
        styles = compose_decorations(
            styles,
            decorations
                .iter()
                .map(|decoration| (decoration.range.clone(), decoration.style)),
            visible_byte_range.clone(),
        )
        .unwrap_or_default();
    }

    (!styles.is_empty()).then_some(styles)
}

#[derive(Clone, Copy, Debug, PartialEq)]
struct EditorScrollbarLayout {
    bounds: Bounds<Pixels>,
    scroll_size: Size<Pixels>,
    // Excludes editor padding from scroll range while the track still includes it.
    scroll_viewport_size: Size<Pixels>,
}

/// What the unwrapped width of the longest line depends on. While it holds,
/// prepaint reuses the stored width instead of copying the line and asking
/// the text system for it again on every frame.
#[derive(Clone, Debug, PartialEq)]
pub(super) struct LongestLineKey {
    document_revision: u64,
    row: usize,
    len: usize,
    font: gpui::Font,
    text_size: Pixels,
    wrap_width: Option<Pixels>,
    tab_size: usize,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub(super) struct EditorScrollbarSnapshot {
    layout: EditorScrollbarLayout,
    cursor_scroll_offset: Point<Pixels>,
    soft_wrap: bool,
    line_height: Pixels,
    padding_top: Pixels,
    wrap_width: Option<Pixels>,
}

impl EditorScrollbarSnapshot {
    fn new<M: InputModeKind>(
        input_bounds: Bounds<Pixels>,
        last_layout: &LastLayout,
        scroll_size: Size<Pixels>,
        cursor_scroll_offset: Point<Pixels>,
        state: &InputBaseState<M>,
    ) -> Self {
        Self {
            layout: EditorScrollbarLayout::new(
                input_bounds,
                last_layout.line_number_width,
                scroll_size,
                state.editor_paddings,
            ),
            cursor_scroll_offset,
            soft_wrap: state.soft_wrap,
            line_height: last_layout.line_height,
            padding_top: state.editor_paddings.top,
            wrap_width: last_layout.wrap_width,
        }
    }
}

impl EditorScrollbarLayout {
    fn new(
        input_bounds: Bounds<Pixels>,
        line_number_width: Pixels,
        scroll_size: Size<Pixels>,
        paddings: Edges<Pixels>,
    ) -> Self {
        let left = if line_number_width == px(0.) {
            px(0.)
        } else {
            paddings.left + line_number_width - LINE_NUMBER_RIGHT_MARGIN
        };

        let bounds = Bounds::new(
            point(
                input_bounds.origin.x + left,
                input_bounds.origin.y - paddings.top,
            ),
            size(
                input_bounds.size.width - left + paddings.right,
                input_bounds.size.height + paddings.top + paddings.bottom,
            ),
        );

        Self {
            bounds,
            scroll_size: size(
                scroll_size.width - left + paddings.right + RIGHT_MARGIN,
                scroll_size.height,
            ),
            scroll_viewport_size: size(bounds.size.width, input_bounds.size.height),
        }
    }
}

pub(super) struct EditorScrollbar<M: InputModeKind> {
    state: Entity<InputBaseState<M>>,
}

impl<M: InputModeKind> EditorScrollbar<M> {
    pub(super) fn new(state: Entity<InputBaseState<M>>) -> Self {
        Self { state }
    }
}

impl<M: InputModeKind> IntoElement for EditorScrollbar<M> {
    type Element = Self;

    fn into_element(self) -> Self::Element {
        self
    }
}

impl<M: InputModeKind> Element for EditorScrollbar<M> {
    type RequestLayoutState = ();
    type PrepaintState = (Vec<PaintQuad>, Option<AnyElement>);

    fn id(&self) -> Option<ElementId> {
        Some("editor-scrollbar".into())
    }

    fn source_location(&self) -> Option<&'static std::panic::Location<'static>> {
        None
    }

    fn request_layout(
        &mut self,
        _: Option<&GlobalElementId>,
        _: Option<&gpui::InspectorElementId>,
        window: &mut Window,
        cx: &mut App,
    ) -> (LayoutId, Self::RequestLayoutState) {
        let mut style = Style::default();
        style.position = Position::Absolute;
        style.size.width = relative(1.).into();
        style.size.height = relative(1.).into();

        (window.request_layout(style, [], cx), ())
    }

    fn prepaint(
        &mut self,
        _: Option<&GlobalElementId>,
        _: Option<&gpui::InspectorElementId>,
        _: Bounds<Pixels>,
        _: &mut Self::RequestLayoutState,
        window: &mut Window,
        cx: &mut App,
    ) -> Self::PrepaintState {
        let state = self.state.read(cx);
        let Some(snapshot) = state.editor_scrollbar_snapshot.get() else {
            return (Vec::new(), None);
        };
        // Marks follow the track the theme gives the scrollbar.
        let ruler = layout_overview_ruler(state, &snapshot, Scrollbar::themed_track_width(cx));
        let scroll_handle = state.scroll_handle.clone();

        if scroll_handle.offset() != snapshot.cursor_scroll_offset {
            scroll_handle.set_offset(snapshot.cursor_scroll_offset);
        }

        let renderer = state.scrollbar_renderer.clone();
        let mut scrollbar = if let Some(renderer) = renderer {
            let presentation = super::EditorScrollbarContext {
                handle: scroll_handle,
                viewport: snapshot.layout.bounds,
                scroll_viewport: snapshot.layout.scroll_viewport_size,
                content: snapshot.layout.scroll_size,
                axis: if snapshot.soft_wrap {
                    crate::ScrollbarAxis::Vertical
                } else {
                    crate::ScrollbarAxis::Both
                },
            };
            renderer(presentation, window, cx)
        } else {
            if !snapshot.soft_wrap {
                Scrollbar::new(&scroll_handle)
            } else {
                Scrollbar::vertical(&scroll_handle)
            }
            .viewport_bounds(snapshot.layout.bounds)
            .scroll_viewport_size(snapshot.layout.scroll_viewport_size)
            .scroll_size(snapshot.layout.scroll_size)
            .into_any_element()
        };

        scrollbar.prepaint_as_root(
            snapshot.layout.bounds.origin,
            snapshot.layout.bounds.size.into(),
            window,
            cx,
        );
        (ruler, Some(scrollbar))
    }

    fn paint(
        &mut self,
        _: Option<&GlobalElementId>,
        _: Option<&gpui::InspectorElementId>,
        _: Bounds<Pixels>,
        _: &mut Self::RequestLayoutState,
        prepaint: &mut Self::PrepaintState,
        window: &mut Window,
        cx: &mut App,
    ) {
        // Beneath the scrollbar, so its thumb passes over the marks and fades
        // without taking them along.
        for mark in std::mem::take(&mut prepaint.0) {
            window.paint_quad(mark);
        }
        if let Some(scrollbar) = prepaint.1.as_mut() {
            scrollbar.paint(window, cx);
        }
    }
}

// Prepaint and retained state must use the same range, including after content shrinks.
pub(super) fn clamp_horizontal_scroll_offset(
    offset: Pixels,
    scroll_width: Pixels,
    input_width: Pixels,
    text_align: TextAlign,
) -> Pixels {
    let caret_clearance = if text_align == TextAlign::Left {
        px(0.)
    } else {
        -CURSOR_WIDTH
    };
    let min_offset = (input_width - scroll_width + caret_clearance).min(caret_clearance);
    offset.clamp(min_offset, px(0.))
}

fn clamp_vertical_scroll_offset(
    scroll_top: Pixels,
    scroll_height: Pixels,
    input_height: Pixels,
) -> Pixels {
    scroll_top.clamp((input_height - scroll_height).min(px(0.)), px(0.))
}

fn editor_gutter_bounds(
    input_bounds: Bounds<Pixels>,
    line_number_width: Pixels,
    ghost_lines_height: Pixels,
    paddings: Edges<Pixels>,
) -> Bounds<Pixels> {
    Bounds {
        origin: point(
            input_bounds.origin.x - paddings.left,
            input_bounds.origin.y - paddings.top,
        ),
        size: size(
            line_number_width + paddings.left,
            input_bounds.size.height + ghost_lines_height + paddings.top + paddings.bottom,
        ),
    }
}

/// Where a gutter or overview ruler decoration sits, in display rows.
#[derive(Clone, Debug, PartialEq)]
enum DecorationRows {
    /// The rows of every line the range touches. A range that starts inside a fold
    /// begins on the fold's row, which `folded_start` flags.
    Lines {
        rows: Range<usize>,
        folded_start: bool,
    },
    /// The boundary at the top of this row, for an empty range.
    Boundary(usize),
}

fn decoration_rows(text: &Rope, display_map: &DisplayMap, range: &Range<usize>) -> DecorationRows {
    let start_line = text.offset_to_point(range.start).row;
    let folded_start = display_map.is_buffer_line_hidden(start_line);
    let start = display_map.buffer_line_to_display_row(start_line);
    if range.is_empty() && !folded_start {
        let rows = display_map
            .buffer_line_to_display_row_range(start_line)
            .unwrap_or_default();
        // At a line's start the boundary is above it; anywhere else, such as the
        // end of a document without a final newline, below it.
        return DecorationRows::Boundary(if text.line_start_offset(start_line) == range.start {
            rows.start
        } else {
            rows.end
        });
    }
    let mut end_line = text.offset_to_point(range.end).row;
    // A half-open range ending at a line's start does not touch that line.
    if end_line > start_line && text.line_start_offset(end_line) == range.end {
        end_line -= 1;
    }
    let end = match display_map.buffer_line_to_display_row_range(end_line) {
        Some(rows) => rows.end,
        None => display_map.buffer_line_to_display_row(end_line) + 1,
    };
    DecorationRows::Lines {
        rows: start..end.max(start + 1),
        folded_start,
    }
}

/// The buffer bytes behind the visible rows, folded text included, so a query
/// finds every decoration that can paint in them. The end is the start of the
/// first line below the viewport, so it also takes a fold whose row is the last
/// one shown.
fn visible_buffer_span(
    text: &Rope,
    display_map: &DisplayMap,
    visible_range: &Range<usize>,
) -> Range<usize> {
    if visible_range.is_empty() {
        return 0..0;
    }
    let last_row = display_map.buffer_line_to_display_row(visible_range.end - 1);
    let end = if last_row + 1 < display_map.display_row_count() {
        text.line_start_offset(display_map.display_row_to_buffer_line(last_row + 1))
    } else {
        text.len()
    };
    text.line_start_offset(visible_range.start)..end
}

/// Overview ruler marks in display rows, sorted by lane and row. Painting keeps
/// them while the decorations, the text, the folds and the wrapping stay the same,
/// and only maps them onto the track each frame.
#[derive(Default)]
pub(super) struct OverviewRulerRows {
    key: Option<OverviewRulerKey>,
    rows: Vec<(OverviewRulerLane, Option<Hsla>, Range<usize>)>,
}

#[derive(PartialEq)]
struct OverviewRulerKey {
    decorations: u64,
    document: u64,
    wrap_rows: usize,
    display_rows: usize,
    wrap_width: Option<Pixels>,
    folds: Vec<FoldRange>,
}

impl OverviewRulerKey {
    fn matches<M: InputModeKind>(
        &self,
        state: &InputBaseState<M>,
        snapshot: &EditorScrollbarSnapshot,
    ) -> bool {
        self.decorations == state.extras.overview_ruler_revision()
            && self.document == state.document_revision
            && self.wrap_rows == state.display_map.wrap_row_count()
            && self.display_rows == state.display_map.display_row_count()
            && self.wrap_width == snapshot.wrap_width
            && self.folds.as_slice() == state.display_map.folded_ranges()
    }
}

fn lane_index(lane: OverviewRulerLane) -> u8 {
    match lane {
        OverviewRulerLane::Left => 0,
        OverviewRulerLane::Center => 1,
        OverviewRulerLane::Right => 2,
        OverviewRulerLane::Full => 3,
    }
}

/// Overview ruler marks on the vertical track, `track_width` wide, at the right of
/// the scrollbar's bounds.
fn layout_overview_ruler<M: InputModeKind>(
    state: &InputBaseState<M>,
    snapshot: &EditorScrollbarSnapshot,
    track_width: Pixels,
) -> Vec<PaintQuad> {
    let layout = &snapshot.layout;
    // The content height the thumb maps onto the track, padding included.
    let content_height =
        layout.scroll_size.height + layout.bounds.size.height - layout.scroll_viewport_size.height;
    if content_height <= px(0.) {
        return Vec::new();
    }
    let mut cache = state.overview_ruler_rows.borrow_mut();
    if !cache
        .key
        .as_ref()
        .is_some_and(|key| key.matches(state, snapshot))
    {
        let mut rows: Vec<_> = state
            .extras
            .overview_ruler_decorations()
            .into_iter()
            .map(|decoration| {
                let rows =
                    match decoration_rows(&state.text, &state.display_map, decoration.range()) {
                        DecorationRows::Lines { rows, .. } => rows,
                        DecorationRows::Boundary(row) => row..row,
                    };
                (decoration.lane(), decoration.color(), rows)
            })
            .collect();
        rows.sort_by_key(|(lane, _, rows)| (lane_index(*lane), rows.start));
        *cache = OverviewRulerRows {
            key: Some(OverviewRulerKey {
                decorations: state.extras.overview_ruler_revision(),
                document: state.document_revision,
                wrap_rows: state.display_map.wrap_row_count(),
                display_rows: state.display_map.display_row_count(),
                wrap_width: snapshot.wrap_width,
                folds: state.display_map.folded_ranges().to_vec(),
            }),
            rows,
        };
    }
    if cache.rows.is_empty() {
        return Vec::new();
    }

    let track = Bounds::new(
        point(layout.bounds.right() - track_width, layout.bounds.top()),
        size(track_width, layout.bounds.size.height),
    );
    let scale = track.size.height / content_height;
    let y = |row: usize| {
        track.top() + (snapshot.padding_top + snapshot.line_height * row as f32) * scale
    };
    let foreground = state.editor_style.foreground;
    let mut merged: Vec<(OverviewRulerLane, Hsla, Pixels, Pixels)> = Vec::new();
    for (lane, color, rows) in &cache.rows {
        let (top, bottom) = (y(rows.start), y(rows.end));
        // A short mark grows around its centre and stays inside the track.
        let height = (bottom - top).max(MIN_OVERVIEW_RULER_MARK_HEIGHT);
        let top = (top + (bottom - top - height).half())
            .clamp(track.top(), (track.bottom() - height).max(track.top()));
        let color = color.unwrap_or(foreground);
        match merged.last_mut() {
            Some(last) if last.0 == *lane && last.1 == color && top <= last.3 + px(1.) => {
                last.3 = last.3.max(top + height);
            }
            _ => merged.push((*lane, color, top, top + height)),
        }
    }

    let third = track.size.width / 3.;
    merged
        .into_iter()
        .map(|(lane, color, top, bottom)| {
            let (left, width) = match lane {
                OverviewRulerLane::Left => (px(0.), third),
                OverviewRulerLane::Center => (third, third),
                OverviewRulerLane::Right => (third * 2., third),
                OverviewRulerLane::Full => (px(0.), track.size.width),
            };
            fill(
                Bounds::new(point(track.left() + left, top), size(width, bottom - top)),
                color,
            )
        })
        .collect()
}

use super::MASK_CHAR;

/// Convert a byte offset in the original text to a byte offset in the masked display string.
///
/// The masked string consists of `MASK_CHAR` repeated once per character in the original text.
/// Since `MASK_CHAR` may be multi-byte in UTF-8, the byte offset in the masked string is
/// `char_index * MASK_CHAR.len_utf8()`.
fn masked_display_offset(text: &Rope, original_offset: usize) -> usize {
    text.offset_to_char_index(original_offset) * MASK_CHAR.len_utf8()
}

/// Move the IME marked range (tracked against the original text) into the display text
/// coordinate space, so that a run boundary can't land inside a multi-byte `MASK_CHAR`
/// and panic text shaping on a non-char-boundary slice.
fn ime_marked_display_range(
    text: &Rope,
    marked_range: Option<Range<usize>>,
    masked: bool,
) -> Option<Range<usize>> {
    let marked = marked_range?;
    if masked {
        Some(masked_display_offset(text, marked.start)..masked_display_offset(text, marked.end))
    } else {
        Some(marked)
    }
}

/// Viewport capacity in display rows, independent of logical buffer lines.
///
/// Shared by both scroll-into-view paths (`layout_cursors` and
/// `scroll_to_with_padding`) so they agree on the visible-line count even
/// when soft-wrapped lines make logical and display rows diverge.
pub(super) fn viewport_visible_lines(viewport_height: Pixels, line_height: Pixels) -> usize {
    (viewport_height / line_height) as usize
}

/// Minimum pixel padding the cursor is kept clear of the viewport's
/// top/bottom edges before auto-scroll engages. Backs
/// [`InputBaseState::cursor_surrounding_lines`].
///
/// Auto-grow uses one line. Otherwise `None` falls back to the historical
/// heuristic ([`BOTTOM_MARGIN_ROWS`] lines, or one line on small
/// viewports); `Some(n)` uses `n` lines. The result is saturated against
/// half the viewport so an oversized override can't invert the
/// top/bottom thresholds into a scroll feedback loop. `visible_lines` is the
/// viewport capacity in display rows, independent of logical buffer lines.
pub(super) fn cursor_surrounding_padding(
    is_auto_grow: bool,
    override_lines: Option<usize>,
    visible_lines: usize,
    line_height: Pixels,
) -> Pixels {
    if is_auto_grow {
        return line_height;
    }
    let raw = match override_lines {
        Some(lines) => lines as f32 * line_height,
        None => {
            if visible_lines < BOTTOM_MARGIN_ROWS * 8 {
                line_height
            } else {
                BOTTOM_MARGIN_ROWS * line_height
            }
        }
    };
    // Saturate against half the viewport so top + bottom margins can coexist.
    let viewport_half = (visible_lines as f32 * line_height).half();
    raw.min(viewport_half)
}

/// Reveal the whole visual row without changing the usual edge clearance.
/// Reserve the row's height below its insertion position before allocating
/// top padding. A viewport shorter than a row can only align its start.
pub(super) fn reveal_row(
    offset: Pixels,
    row_top: Pixels,
    line_height: Pixels,
    viewport_height: Pixels,
    edge_padding: Pixels,
) -> Pixels {
    let row_height = line_height.min(viewport_height);
    let bottom = edge_padding.max(row_height).min(viewport_height);
    let top = edge_padding.min(viewport_height - bottom);
    offset
        .clamp(top - row_top, viewport_height - bottom - row_top)
        .min(px(0.))
}

/// Pixel height of the empty area below the last line in the editor's
/// scrollable region. Backs [`InputBaseState::scroll_beyond_last_line`].
///
/// `0` outside code-editor mode. Inside it, `None` is half the viewport
/// (floored at [`BOTTOM_MARGIN_ROWS`] line-heights); `Some(n)` is exactly
/// `n` line-heights.
fn empty_bottom_height(
    is_code_editor: bool,
    override_rows: Option<usize>,
    viewport_height: Pixels,
    line_height: Pixels,
) -> Pixels {
    if !is_code_editor {
        return px(0.);
    }
    match override_rows {
        Some(rows) => rows as f32 * line_height,
        None => viewport_height.half().max(BOTTOM_MARGIN_ROWS * line_height),
    }
}

/// Layout information for fold icons.
struct FoldIconLayout {
    /// Hitbox for the line number area (used for hover detection)
    line_number_hitbox: Hitbox,
    /// List of (display_row, is_folded, icon_element) pairs for each fold candidate
    icons: Vec<(usize, bool, gpui::AnyElement)>,
}

pub(super) struct TextElement<M: InputModeKind> {
    pub(crate) state: Entity<InputBaseState<M>>,
    placeholder: SharedString,
}

impl<M: InputModeKind> TextElement<M> {
    pub(super) fn new(state: Entity<InputBaseState<M>>) -> Self {
        Self {
            state,
            placeholder: SharedString::default(),
        }
    }

    /// Set the placeholder text of the input field.
    pub(super) fn placeholder(mut self, placeholder: impl Into<SharedString>) -> Self {
        self.placeholder = placeholder.into();
        self
    }

    fn paint_mouse_listeners(&mut self, hitbox: &Hitbox, window: &mut Window, _: &mut App) {
        // Text with room to scroll keeps the wheel from the scroll areas
        // around it; its own listener scrolls it in the bubble phase.
        window.on_mouse_event({
            let state = self.state.clone();
            let hitbox = hitbox.id;
            move |event: &gpui::ScrollEvent, phase, window, cx| {
                if phase.capture()
                    && hitbox.should_handle_scroll(window)
                    && state
                        .read(cx)
                        .takes_scroll(event.delta.pixel_delta(window.line_height()))
                {
                    crate::scroll_bounce::claim_scroll(hitbox, cx);
                }
            }
        });

        // Every touch is offered as a drag first; that is how a tap's mouse
        // events are later told apart from a mouse's.
        window.on_mouse_event(move |event: &TouchDragEvent, phase, _, cx| {
            if phase.capture() && event.phase == TouchPhase::Started {
                crate::GlobalState::note_touch(cx);
            }
        });

        // A long press is touch's way to select: the word under the finger,
        // then whatever the finger sweeps over. Claiming it keeps the moves
        // out of the pan recognizer, so the input does not scroll instead.
        window.on_mouse_event({
            let state = self.state.clone();
            let hitbox = hitbox.clone();
            move |event: &LongPressEvent, phase, window, cx| {
                if !phase.bubble() {
                    return;
                }
                if event.phase == TouchPhase::Started {
                    if window.default_prevented() || !hitbox.is_hovered(window) {
                        return;
                    }
                    if !state.update(cx, |state, cx| state.on_long_press(event, window, cx)) {
                        return;
                    }
                    window.capture_long_press(&state);
                } else if !window.has_long_press_capture(&state) {
                    return;
                } else {
                    state.update(cx, |state, cx| {
                        state.on_long_press(event, window, cx);
                    });
                }
                window.prevent_default();
                cx.stop_propagation();
            }
        });

        window.on_mouse_event({
            let state = self.state.clone();

            move |event: &MouseMoveEvent, _, window, cx| {
                if event.pressed_button == Some(MouseButton::Left) {
                    state.update(cx, |state, cx| {
                        state.on_drag_move(event, window, cx);
                    });
                }
            }
        });

        window.on_mouse_event({
            let state = self.state.clone();
            move |_: &MouseUpEvent, phase, _, cx| {
                if !phase.bubble() {
                    return;
                }

                // Stop auto-scroll when mouse up, and also stop selecting.
                state.update(cx, |state, _| {
                    state.auto_scroll.stop();
                    state.selecting = false;
                    state.column_select_start = None;
                });
            }
        });
    }

    /// Lays out the carets and updates the scroll position for the active one.
    fn layout_cursors(
        &self,
        last_layout: &LastLayout,
        bounds: &mut Bounds<Pixels>,
        scroll_size: Size<Pixels>,
        window: &mut Window,
        cx: &mut App,
    ) -> (Vec<CursorRenderInfo>, Point<Pixels>, Option<usize>, bool) {
        let state = self.state.read(cx);

        let line_height = last_layout.line_height;
        let visible_range = &last_layout.visible_range;
        let lines = &last_layout.lines;
        let line_number_width = last_layout.line_number_width;

        let active_id = state.active_selection().id;
        let mut scroll_offset = state.scroll_handle.offset();
        let mut current_row = None;
        let mut resize_reveal_owned = false;
        let mut cursor_infos: Vec<CursorRenderInfo> = Vec::with_capacity(state.selections.len());

        // Padding kept between the cursor and the viewport's top/bottom
        // edges, used by the auto-scroll-into-view computation below.
        let top_bottom_margin = cursor_surrounding_padding(
            state.mode.is_auto_grow(),
            state.cursor_surrounding_lines,
            viewport_visible_lines(bounds.size.height, line_height),
            line_height,
        );

        // Keep a visible, focused caret visible when its viewport reflows, but
        // do not undo deliberate scrolling away from an unchanged selection.
        let resized = state.last_bounds.is_some_and(|old| old.size != bounds.size)
            || state
                .last_layout
                .as_ref()
                .is_some_and(|old| old.line_height != line_height);
        let reveal_on_resize = resized
            && state.deferred_scroll_offset.is_none()
            && state.focus_handle.is_focused(window)
            && state.prepaint_caret_geometry.is_some_and(|old| {
                // An unshaped caret has provisional x until the notified
                // repaint. Consecutive resize frames retain ownership only
                // while no intervening scroll changed the viewport.
                if old.resize_reveal_owned {
                    return old.scroll_offset() == scroll_offset;
                }
                let caret = old.cursor_bounds();
                let viewport = old.input_bounds();
                let top = caret.top() + scroll_offset.y;
                // Cached x already contains its painted scroll; account only
                // for a wheel offset change since that geometry was produced.
                let left = caret.left() + scroll_offset.x - old.scroll_offset().x;
                top >= viewport.top()
                    && top + caret.size.height <= viewport.bottom()
                    && left >= viewport.left()
                    && left + caret.size.width <= viewport.right()
            });

        // Resolve a cursor or selection endpoint to a content-space position.
        let visible_buffer_lines = &last_layout.visible_buffer_lines;
        let caret_for = |row: usize, offset: usize, affinity: bool| -> Point<Pixels> {
            // y of the top of buffer line `row` in content space.
            let top = line_height * state.display_map.buffer_line_to_display_row(row);
            let line_origin = point(px(0.), top);

            if let Some(vi) = visible_buffer_lines.iter().position(|&bl| bl == row) {
                let line = &lines[vi];
                let line_start = last_layout.visible_line_byte_offsets[vi];
                let local = offset.saturating_sub(line_start);
                if let Some(pos) = line.position_for_index(local, last_layout, affinity) {
                    return line_origin + pos;
                }
            }
            if state.masked {
                return line_origin;
            }
            point(
                px(0.),
                line_height * state.display_map.offset_to_display_row(offset, affinity),
            )
        };

        let cursor_height = 0.85 * line_height;

        for selection in state.selections.iter() {
            let is_active = selection.id == active_id;

            let mut selected_range = *selection;
            let mut cursor = selection.cursor_offset();
            if is_active {
                if let Some(ime_marked_range) = &state.ime_marked_range {
                    selected_range = (ime_marked_range.end..ime_marked_range.end).into();
                    cursor = ime_marked_range.end;
                }
            }
            let is_selected_all = selected_range.len() == state.text.len();

            // Buffer rows from the raw (pre-mask) offsets, used to locate the cursor line.
            let cursor_row = state.text.offset_to_point(cursor).row;

            // Skip inactive cursors that are far outside the visible range. The
            // active cursor is always processed so scroll tracking keeps working.
            if !is_active
                && (cursor_row + 2 < visible_range.start || cursor_row > visible_range.end + 2)
            {
                continue;
            }

            let sel_start_row = state.text.offset_to_point(selected_range.start).row;
            let sel_end_row = state.text.offset_to_point(selected_range.end).row;
            if state.masked {
                selected_range.start = masked_display_offset(&state.text, selected_range.start);
                selected_range.end = masked_display_offset(&state.text, selected_range.end);
                cursor = masked_display_offset(&state.text, cursor);
            }

            let affinity = is_active && state.cursor_line_end_affinity;
            let cursor_pos = caret_for(cursor_row, cursor, affinity);
            let cursor_start = caret_for(sel_start_row, selected_range.start, false);
            let cursor_end = caret_for(sel_end_row, selected_range.end, false);

            if is_active {
                current_row = Some(cursor_row);

                let selection_changed = state.last_selected_range != Some(selected_range);
                let auto_scrolling = state.auto_scroll.is_active();
                if (selection_changed || reveal_on_resize) && !is_selected_all {
                    // Resize-follow owns only vertical visibility. An unshaped
                    // target has no reliable x; retain the existing x offset.
                    if selection_changed {
                        // Right-aligned carets are clamped instead of scrolling.
                        let safety_margin = match last_layout.text_align {
                            TextAlign::Left => RIGHT_MARGIN,
                            TextAlign::Right => px(0.),
                            TextAlign::Center => CURSOR_WIDTH,
                        };
                        scroll_offset.x = if scroll_offset.x + cursor_pos.x
                            > (bounds.size.width - line_number_width - safety_margin)
                        {
                            bounds.size.width - line_number_width - safety_margin - cursor_pos.x
                        } else if scroll_offset.x + cursor_pos.x < px(0.) {
                            -cursor_pos.x
                        } else {
                            scroll_offset.x
                        };
                    }

                    // Vertical cursor-follow is suppressed while auto-scroll manages the y axis,
                    // to prevent fighting the background scroll task.
                    if !auto_scrolling {
                        scroll_offset.y = reveal_row(
                            scroll_offset.y,
                            cursor_pos.y,
                            line_height,
                            bounds.size.height,
                            top_bottom_margin,
                        );
                        resize_reveal_owned = reveal_on_resize;
                    }

                    // For selection to move scroll
                    if selection.reversed {
                        if selection_changed && scroll_offset.x + cursor_start.x < px(0.) {
                            // selection start is out of left
                            scroll_offset.x = -cursor_start.x;
                        }
                        if !auto_scrolling && scroll_offset.y + cursor_start.y < px(0.) {
                            // selection start is out of top
                            scroll_offset.y = -cursor_start.y;
                        }
                    } else {
                        // TODO: Consider to remove this part,
                        // maybe is not necessary (But selection_reversed is needed).
                        if selection_changed && scroll_offset.x + cursor_end.x <= px(0.) {
                            // selection end is out of left
                            scroll_offset.x = -cursor_end.x;
                        }
                        if !auto_scrolling && scroll_offset.y + cursor_end.y <= px(0.) {
                            // selection end is out of top
                            scroll_offset.y = -cursor_end.y;
                        }
                    }
                }
            }

            // Apply the final horizontal offset to every caret after cursor-follow and
            // deferred scrolling have been resolved, regardless of selection order.
            let cursor_x = bounds.left() + cursor_pos.x + line_number_width;
            cursor_infos.push(CursorRenderInfo {
                bounds: Bounds::new(
                    point(
                        cursor_x,
                        bounds.top() + cursor_pos.y + ((line_height - cursor_height) / 2.),
                    ),
                    size(CURSOR_WIDTH, cursor_height),
                ),
                is_active,
            });
        }

        if let Some(deferred_scroll_offset) = state.deferred_scroll_offset {
            scroll_offset = deferred_scroll_offset;
        }
        scroll_offset.x = clamp_horizontal_scroll_offset(
            scroll_offset.x,
            scroll_size.width,
            bounds.size.width,
            last_layout.text_align,
        );
        for info in &mut cursor_infos {
            info.bounds.origin.x += scroll_offset.x;
            // Right-aligned text keeps the caret inside the viewport edge.
            if last_layout.text_align == TextAlign::Right {
                info.bounds.origin.x = info.bounds.origin.x.min(bounds.right() - CURSOR_WIDTH);
            }
        }
        scroll_offset.y =
            clamp_vertical_scroll_offset(scroll_offset.y, scroll_size.height, bounds.size.height);

        bounds.origin = bounds.origin + scroll_offset;

        (
            cursor_infos,
            scroll_offset,
            current_row,
            resize_reveal_owned,
        )
    }

    /// Layout the match range to a Path.
    pub(crate) fn layout_match_range(
        range: Range<usize>,
        last_layout: &LastLayout,
        bounds: &Bounds<Pixels>,
    ) -> Option<Path<Pixels>> {
        let corners = Self::layout_range_corners(&range, last_layout)?;
        let points = frame_outline_points(&corners);
        let origin = bounds.origin + point(last_layout.line_number_width, px(0.));
        let mut builder = gpui::PathBuilder::fill();
        builder.move_to(origin + *points.first()?);
        for point in points.iter().skip(1) {
            builder.line_to(origin + *point);
        }
        builder.close();
        builder.build().ok()
    }

    /// Project a buffer range through the visible (non-folded) shaped lines.
    /// Half-open intersections give soft-wrap ends their trailing affinity and
    /// prevent ranges on later lines from painting an earlier line's first glyph.
    fn layout_range_corners(
        range: &Range<usize>,
        last_layout: &LastLayout,
    ) -> Option<Vec<Corners<Point<Pixels>>>> {
        let range = range.start.max(last_layout.visible_range_offset.start)
            ..range.end.min(last_layout.visible_range_offset.end);
        if range.is_empty() {
            return None;
        }

        let mut y = last_layout.visible_top;
        let mut corners = Vec::new();
        for (&line_offset, line) in last_layout
            .visible_line_byte_offsets
            .iter()
            .zip(last_layout.lines.iter())
        {
            let mut offset = line_offset;
            let alignment = last_layout.alignment_offset(line.longest_width);
            for (row, shaped) in line.wrapped_lines.iter().enumerate() {
                let end = offset + shaped.len;
                let start_ix = range.start.max(offset);
                let end_ix = range.end.min(end);
                let is_last = row + 1 == line.wrapped_lines.len();
                // A selected newline has a one-space cell, including empty lines.
                // A wrap boundary is not a newline and must not get such a cell.
                let newline = is_last && range.start <= end && range.end > end;
                if start_ix < end_ix || newline {
                    let indent = if row == 0 { px(0.) } else { line.wrap_indent };
                    let left = alignment + indent + shaped.x_for_index(start_ix.min(end) - offset);
                    let right = alignment
                        + indent
                        + if newline {
                            shaped.width + last_layout.space_width
                        } else {
                            shaped.x_for_index(end_ix - offset)
                        };
                    corners.push(Corners {
                        top_left: point(left, y),
                        top_right: point(right, y),
                        bottom_left: point(left, y + last_layout.line_height),
                        bottom_right: point(right, y + last_layout.line_height),
                    });
                }
                offset = end;
                y += last_layout.line_height;
            }
        }
        (!corners.is_empty()).then_some(corners)
    }

    fn layout_range_decorations(
        &self,
        last_layout: &LastLayout,
        bounds: &Bounds<Pixels>,
        window: &Window,
        content_mask: Bounds<Pixels>,
        cx: &App,
    ) -> (Vec<(Path<Pixels>, Hsla)>, Vec<(Path<Pixels>, Hsla)>) {
        let state = self.state.read(cx);
        let mut fills = Vec::new();
        let mut frames = Vec::new();
        // Query separate buffer spans across folds instead of scanning annotations
        // in the hidden text between the first and last visible buffer offsets.
        let mut visible_spans: Vec<Range<usize>> = Vec::new();
        for (&offset, line) in last_layout
            .visible_line_byte_offsets
            .iter()
            .zip(last_layout.lines.iter())
        {
            let end = (offset + line.len() + 1).min(last_layout.visible_range_offset.end);
            if let Some(previous) = visible_spans.last_mut().filter(|span| span.end == offset) {
                previous.end = end;
            } else if offset < end {
                visible_spans.push(offset..end);
            }
        }
        for decoration in state.extras.range_decorations(&visible_spans) {
            match decoration.style() {
                RangeDecorationStyle::Fill => {
                    let color = decoration
                        .color()
                        .unwrap_or(state.editor_style.foreground.opacity(0.12));
                    if let Some(path) =
                        Self::layout_match_range(decoration.range().clone(), last_layout, bounds)
                    {
                        fills.push((path, color));
                    }
                }
                RangeDecorationStyle::Frame => {
                    let color = decoration.color().unwrap_or(state.editor_style.foreground);
                    let Some(corners) = Self::layout_range_corners(decoration.range(), last_layout)
                    else {
                        continue;
                    };
                    let origin = bounds.origin + point(last_layout.line_number_width, px(0.));
                    let corners = pad_frame_corners(&corners, px(1.));
                    let points = frame_outline_points(&corners)
                        .into_iter()
                        .map(|point| origin + point)
                        .collect::<Vec<_>>();
                    let (stroke_width, points) =
                        snap_frame_outline(&points, px(1.), window.scale_factor());
                    let points = clamp_frame_to_content_mask(points, stroke_width, content_mask);
                    let Some(first) = points.first().copied() else {
                        continue;
                    };
                    let mut builder = gpui::PathBuilder::stroke(stroke_width);
                    builder.move_to(first);
                    for point in points.iter().skip(1) {
                        builder.line_to(*point);
                    }
                    builder.close();
                    if let Ok(path) = builder.build() {
                        frames.push((path, color));
                    }
                }
            }
        }
        (fills, frames)
    }

    fn layout_search_matches(
        &self,
        last_layout: &LastLayout,
        bounds: &Bounds<Pixels>,
        cx: &mut App,
    ) -> Vec<(Path<Pixels>, bool)> {
        let state = self.state.read(cx);
        if !state.search_session.is_active() {
            return vec![];
        }
        let ranges = state.search_session.matcher.matched_ranges();
        let current_match_ix = state.search_session.matcher.current_match_index();

        // Matches are sorted and do not overlap, so only the ones that reach
        // into the visible range need a layout.
        let visible_range = &last_layout.visible_range_offset;
        let first = ranges.partition_point(|range| range.end <= visible_range.start);
        let mut paths = Vec::new();
        for (index, range) in ranges
            .iter()
            .enumerate()
            .skip(first)
            .take_while(|(_, range)| range.start < visible_range.end)
        {
            if let Some(path) = Self::layout_match_range(range.clone(), last_layout, bounds) {
                paths.push((path, current_match_ix == index));
            }
        }

        paths
    }

    fn layout_hover_highlight(
        &self,
        last_layout: &LastLayout,
        bounds: &Bounds<Pixels>,
        cx: &mut App,
    ) -> Option<Path<Pixels>> {
        let state = self.state.read(cx);
        let Some(symbol_range) = state.extras.hover_symbol_range() else {
            return None;
        };

        Self::layout_match_range(symbol_range, last_layout, bounds)
    }

    fn layout_document_colors(
        &self,
        document_colors: &[(Range<usize>, Hsla)],
        last_layout: &LastLayout,
        bounds: &Bounds<Pixels>,
        _cx: &mut App,
    ) -> Vec<(Path<Pixels>, Hsla)> {
        let mut paths = vec![];
        for (range, color) in document_colors.iter() {
            if let Some(path) = Self::layout_match_range(range.clone(), last_layout, bounds) {
                paths.push((path, *color));
            }
        }

        paths
    }

    fn layout_selections(
        &self,
        last_layout: &LastLayout,
        bounds: &mut Bounds<Pixels>,
        window: &mut Window,
        cx: &mut App,
    ) -> Vec<Path<Pixels>> {
        let state = self.state.read(cx);
        if !state.has_selection_focus(window, cx) {
            return vec![];
        }

        let active_id = state.active_selection().id;
        let mut paths = Vec::new();

        for selection in state.selections.iter() {
            let is_active = selection.id == active_id;
            let mut selected_range = *selection;

            // IME composition replaces the active selection with a collapsed
            // caret, so it never paints a selection highlight.
            if is_active {
                if let Some(ime_marked_range) = &state.ime_marked_range {
                    if !ime_marked_range.is_empty() {
                        selected_range = (ime_marked_range.end..ime_marked_range.end).into();
                    }
                }
            }
            if selected_range.is_empty() {
                continue;
            }

            if state.masked {
                selected_range.start = masked_display_offset(&state.text, selected_range.start);
                selected_range.end = masked_display_offset(&state.text, selected_range.end);
            }

            let (start_ix, end_ix) = if selected_range.start < selected_range.end {
                (selected_range.start, selected_range.end)
            } else {
                (selected_range.end, selected_range.start)
            };

            let range = start_ix.max(last_layout.visible_range_offset.start)
                ..end_ix.min(last_layout.visible_range_offset.end);

            if range.is_empty() {
                continue;
            }

            // A selected token shows its own selected state, so the text
            // highlight stops at its edges instead of painting behind it.
            let mut start = range.start;
            if state.tokens_visible() {
                let spans = state.token_spans();
                let first = spans.partition_point(|s| s.range().end <= range.start);
                for span in spans[first..]
                    .iter()
                    .take_while(|s| s.range().start < range.end)
                {
                    if start < span.range().start {
                        paths.extend(Self::layout_match_range(
                            start..span.range().start,
                            last_layout,
                            bounds,
                        ));
                    }
                    start = span.range().end.max(start);
                }
            }
            if start < range.end {
                paths.extend(Self::layout_match_range(
                    start..range.end,
                    last_layout,
                    bounds,
                ));
            }
        }

        paths
    }

    /// Calculate the visible range of lines in the viewport.
    ///
    /// Returns
    ///
    /// - visible_range: The visible range is based on unwrapped lines (Zero based).
    /// - visible_buffer_lines: Indices of non-hidden buffer lines within the visible range.
    /// - visible_top: The top position of the first visible line in the scroll viewport.
    fn calculate_visible_range(
        &self,
        state: &InputBaseState<M>,
        line_height: Pixels,
        input_height: Pixels,
    ) -> (Range<usize>, Vec<usize>, Pixels) {
        // Add extra rows to avoid showing empty space when scroll to bottom.
        let extra_rows = 1;
        if state.is_single_line() {
            return (0..1, vec![0], px(0.));
        }

        let total_lines = state.display_map.wrap_row_count();
        let display_count = state.display_map.display_row_count();
        let buffer_line_count = state.display_map.buffer_line_count();
        if display_count == 0 || buffer_line_count == 0 {
            return (0..0, Vec::new(), px(0.));
        }

        let mut scroll_top = if let Some(deferred_scroll_offset) = state.deferred_scroll_offset {
            deferred_scroll_offset.y
        } else {
            state.scroll_handle.offset().y
        };
        // Clamp as `layout_cursors` does, so we lay out the rows we paint.
        // Ghost lines are left out: a tighter clamp only lays out extra rows
        // above, and the last row stays in range.
        let scroll_height = line_height * total_lines
            + empty_bottom_height(
                state.is_code_editor(),
                state.scroll_beyond_last_line,
                input_height,
                line_height,
            );
        scroll_top = clamp_vertical_scroll_offset(scroll_top, scroll_height, input_height);

        // Display rows are uniformly `line_height` tall, so the visible window maps
        // directly to a display-row range.
        let viewport_top = (-scroll_top).max(px(0.));
        let viewport_bottom = viewport_top + input_height;
        let line_height_f = f32::from(line_height);
        let first_display =
            ((f32::from(viewport_top) / line_height_f).floor() as usize).min(display_count - 1);
        let last_display =
            ((f32::from(viewport_bottom) / line_height_f).ceil() as usize).min(display_count - 1);

        let start_line = state.display_map.display_row_to_buffer_line(first_display);
        let end_line = state.display_map.display_row_to_buffer_line(last_display);

        // y of the top of the first visible buffer line (in content space).
        let visible_top = match state
            .display_map
            .buffer_line_to_display_row_range(start_line)
        {
            Some(range) => line_height * range.start,
            None => line_height * first_display,
        };

        let visible_range = start_line..(end_line + 1 + extra_rows).min(buffer_line_count);

        // Collect non-hidden buffer lines within the visible range
        let mut visible_buffer_lines = Vec::with_capacity(visible_range.len());
        for ix in visible_range.clone() {
            if state.display_map.visible_wrap_row_count_for_buffer_line(ix) > 0 {
                visible_buffer_lines.push(ix);
            }
        }

        (visible_range, visible_buffer_lines, visible_top)
    }

    /// Return (line_number_width, line_number_len)
    fn layout_line_numbers(
        state: &InputBaseState<M>,
        text: &Rope,
        font_size: Pixels,
        style: &TextStyle,
        window: &mut Window,
    ) -> (Pixels, usize) {
        let total_lines = text.lines_len();
        // Reserve three digits for small documents, then follow the actual
        // line count up to seven digits.
        let line_number_len = line_number_len(total_lines);

        let mut line_number_width = if state.mode.line_number() {
            let empty_line_number = window.text_system().shape_line(
                "+".repeat(line_number_len).into(),
                font_size,
                &[TextRun {
                    len: line_number_len,
                    font: style.font(),
                    color: gpui::black(),
                    background_color: None,
                    underline: None,
                    strikethrough: None,
                }],
                None,
            );

            empty_line_number.width + LINE_NUMBER_RIGHT_MARGIN
        } else if state.is_code_editor() {
            LINE_NUMBER_RIGHT_MARGIN
        } else {
            px(0.)
        };

        if state.mode.is_folding() {
            // Add extra space for fold icons
            line_number_width += FOLD_ICON_HITBOX_WIDTH
        }

        if let Some(width) = state.extras.gutter_decorations_width() {
            line_number_width += width + GUTTER_DECORATION_GAP;
        }

        (line_number_width, line_number_len)
    }

    /// Layout shaped lines for whitespace indicators (space and tab).
    ///
    /// Returns `WhitespaceIndicators` with shaped lines for space and tab characters.
    fn layout_whitespace_indicators(
        state: &InputBaseState<M>,
        text_size: Pixels,
        style: &TextStyle,
        window: &mut Window,
        _cx: &App,
    ) -> Option<WhitespaceIndicators> {
        if !state.show_whitespaces {
            return None;
        }

        let invisible_color = state
            .editor_style
            .editor_invisible
            .unwrap_or(state.editor_style.muted_foreground);

        let space_font_size = text_size.half();
        let tab_font_size = text_size;

        let space_text = SharedString::new_static("•");
        let space = window.text_system().shape_line(
            space_text.clone(),
            space_font_size,
            &[TextRun {
                len: space_text.len(),
                font: style.font(),
                color: invisible_color,
                background_color: None,
                underline: None,
                strikethrough: None,
            }],
            None,
        );

        let tab_text = SharedString::new_static("→");
        let tab = window.text_system().shape_line(
            tab_text.clone(),
            tab_font_size,
            &[TextRun {
                len: tab_text.len(),
                font: style.font(),
                color: invisible_color,
                background_color: None,
                underline: None,
                strikethrough: None,
            }],
            None,
        );

        Some(WhitespaceIndicators { space, tab })
    }

    /// Compute inline completion ghost lines for rendering.
    ///
    /// Returns (first_line, ghost_lines) where:
    /// - first_line: Shaped text for the first line (goes after cursor on same line)
    /// - ghost_lines: Shaped lines for subsequent lines (shift content down)
    fn layout_inline_completion(
        state: &InputBaseState<M>,
        visible_range: &Range<usize>,
        font_size: Pixels,
        window: &mut Window,
        _cx: &App,
    ) -> (Option<ShapedLine>, Vec<ShapedLine>) {
        // Must be focused to show inline completion
        if !state.focus_handle.is_focused(window) {
            return (None, vec![]);
        }

        let Some(completion_item) = state.extras.inline_completion_item() else {
            return (None, vec![]);
        };

        // Get cursor row from cursor position
        let cursor_row = state.cursor_position().line as usize;

        // Only show if cursor row is visible
        if cursor_row < visible_range.start || cursor_row >= visible_range.end {
            return (None, vec![]);
        }

        let completion_text = &completion_item.insert_text;
        let completion_color = state.editor_style.muted_foreground.opacity(0.5);

        let text_style = window.text_style();
        let font = text_style.font();

        let lines: Vec<&str> = completion_text.split('\n').collect();
        if lines.is_empty() {
            return (None, vec![]);
        }

        // Shape first line (goes after cursor)
        let first_text: SharedString = lines[0].to_string().into();
        let first_line = if !first_text.is_empty() {
            let first_run = TextRun {
                len: first_text.len(),
                font: font.clone(),
                color: completion_color,
                background_color: None,
                underline: None,
                strikethrough: None,
            };
            Some(
                window
                    .text_system()
                    .shape_line(first_text, font_size, &[first_run], None),
            )
        } else {
            None
        };

        // Shape ghost lines (lines 2+ that shift content down)
        let ghost_lines: Vec<ShapedLine> = lines[1..]
            .iter()
            .map(|line_text| {
                let text: SharedString = line_text.to_string().into();
                let len = text.len().max(1); // Ensure at least 1 for empty lines
                let run = TextRun {
                    len,
                    font: font.clone(),
                    color: completion_color,
                    background_color: None,
                    underline: None,
                    strikethrough: None,
                };
                // Use space for empty lines so they take up height
                let shaped_text = if text.is_empty() { " ".into() } else { text };
                window
                    .text_system()
                    .shape_line(shaped_text, font_size, &[run], None)
            })
            .collect();

        (first_line, ghost_lines)
    }

    /// Return (line_number_width, line_number_len)
    /// Layout fold icon hitboxes during prepaint phase.
    ///
    /// This creates hitboxes for the fold icon area, positioned to the right of line numbers.
    /// Icons are created and prepainted here to avoid panics.
    /// Bars and boundary pills for gutter decorations, in the strip at `origin_x`
    /// before the line numbers. Rows below `ghost_rows.0` move down by the
    /// inline completion's ghost lines, `ghost_rows.1` tall, as line numbers do.
    fn layout_gutter_decorations(
        &self,
        origin_x: Pixels,
        bounds: &Bounds<Pixels>,
        viewport: &Bounds<Pixels>,
        last_layout: &LastLayout,
        ghost_rows: Option<(usize, Pixels)>,
        cx: &App,
    ) -> Vec<PaintQuad> {
        let state = self.state.read(cx);
        let Some(width) = state.extras.gutter_decorations_width() else {
            return Vec::new();
        };
        let line_height = last_layout.line_height;
        let span = visible_buffer_span(&state.text, &state.display_map, &last_layout.visible_range);
        let top = |row: usize| {
            let ghost = ghost_rows
                .filter(|(after, _)| row > *after)
                .map_or(px(0.), |(_, height)| height);
            bounds.origin.y + line_height * row as f32 + ghost
        };
        let bar = |rows: Range<usize>, color: Hsla| {
            let bottom = top(rows.end.saturating_sub(1).max(rows.start)) + line_height;
            fill(
                Bounds::from_corners(
                    point(origin_x, top(rows.start)),
                    point(origin_x + width, bottom),
                ),
                color,
            )
        };

        let foreground = state.editor_style.foreground;
        state
            .extras
            // One past the end, so a boundary below the last visible line is found.
            .gutter_decorations(span.start..span.end + 1)
            .into_iter()
            .flat_map(|decoration| {
                let color = decoration.color().unwrap_or(foreground);
                let mut marks = SmallVec::<[PaintQuad; 2]>::new();
                match decoration_rows(&state.text, &state.display_map, decoration.range()) {
                    DecorationRows::Lines {
                        rows,
                        folded_start: false,
                    } => marks.push(bar(rows, color)),
                    // The fold's row takes the folded color, the visible rest the
                    // decoration's own.
                    DecorationRows::Lines {
                        rows,
                        folded_start: true,
                    } => {
                        let folded = decoration.folded_color().unwrap_or(color);
                        marks.push(bar(rows.start..rows.start + 1, folded));
                        if rows.len() > 1 {
                            marks.push(bar(rows.start + 1..rows.end, color));
                        }
                    }
                    DecorationRows::Boundary(row) => marks.push(
                        fill(
                            Bounds::new(
                                point(origin_x, top(row) - GUTTER_BOUNDARY_MARK_HEIGHT.half()),
                                size(width, GUTTER_BOUNDARY_MARK_HEIGHT),
                            ),
                            color,
                        )
                        .corner_radii(width.half()),
                    ),
                }
                marks
            })
            .filter(|mark| {
                mark.bounds.bottom() >= viewport.top() && mark.bounds.top() <= viewport.bottom()
            })
            .collect()
    }

    fn layout_fold_icons(
        &self,
        origin_x: Pixels,
        bounds: &Bounds<Pixels>,
        last_layout: &LastLayout,
        window: &mut Window,
        cx: &mut App,
    ) -> FoldIconLayout {
        // First pass: collect fold information from state
        struct FoldInfo {
            buffer_line: usize,
            is_folded: bool,
            display_row: usize,
            offset_y: Pixels,
        }

        let line_number_hitbox = window.insert_hitbox(
            Bounds::new(
                point(origin_x, bounds.origin.y + last_layout.visible_top),
                size(last_layout.line_number_width, bounds.size.height),
            ),
            HitboxBehavior::Normal,
        );

        let mut icon_layout = FoldIconLayout {
            line_number_hitbox,
            icons: vec![],
        };

        let fold_infos: Vec<FoldInfo> = {
            let state = self.state.read(cx);
            if !state.mode.is_folding() {
                return icon_layout;
            }

            let mut infos = Vec::with_capacity(last_layout.visible_buffer_lines.len());
            let mut offset_y = last_layout.visible_top;

            for (line, &buffer_line) in last_layout
                .lines
                .iter()
                .zip(last_layout.visible_buffer_lines.iter())
            {
                if state.display_map.is_fold_candidate(buffer_line) {
                    let is_folded = state.display_map.is_folded_at(buffer_line);
                    infos.push(FoldInfo {
                        buffer_line,
                        is_folded,
                        display_row: buffer_line,
                        offset_y,
                    });
                }

                offset_y += line.wrapped_lines.len() * last_layout.line_height;
            }

            infos
        }; // state is dropped here

        // Second pass: create and prepaint icons
        let line_height = last_layout.line_height;
        let line_number_width =
            last_layout.line_number_width - LINE_NUMBER_RIGHT_MARGIN - FOLD_ICON_HITBOX_WIDTH;
        let icon_relative_pos = point(
            (FOLD_ICON_HITBOX_WIDTH - FOLD_ICON_WIDTH).half(),
            (line_height - FOLD_ICON_WIDTH).half(),
        );

        for (ix, info) in fold_infos.iter().enumerate() {
            // Position fold icon to the right of line numbers.
            // Use origin_x (unscrolled) so icons stay fixed in the gutter during horizontal scroll.
            let fold_icon_bounds = Bounds::new(
                point(
                    origin_x + icon_relative_pos.x + line_number_width,
                    bounds.origin.y + icon_relative_pos.y + info.offset_y,
                ),
                size(FOLD_ICON_HITBOX_WIDTH, line_height),
            );

            // Create and prepaint icon
            let child = self
                .state
                .read(cx)
                .editor_style
                .fold_icon_renderer
                .as_ref()
                .map(|render| render(ix, info.is_folded))
                .unwrap_or_else(|| {
                    let (path, svg) = if info.is_folded {
                        ("input-fold-chevron-right", FOLD_CHEVRON_RIGHT_SVG)
                    } else {
                        ("input-fold-chevron-down", FOLD_CHEVRON_DOWN_SVG)
                    };
                    gpui::canvas(
                        |_, _, _| {},
                        move |bounds, _, window, cx| {
                            let color = window.text_style().color;
                            let _ = window.paint_svg(
                                bounds,
                                path.into(),
                                Some(svg),
                                gpui::TransformationMatrix::default(),
                                color,
                                cx,
                            );
                        },
                    )
                    .size(FOLD_ICON_WIDTH)
                    .into_any_element()
                });
            let mut icon = gpui::div()
                .id(("fold", ix))
                .size(FOLD_ICON_WIDTH)
                .child(child)
                .on_mouse_down(MouseButton::Left, {
                    let state = self.state.clone();
                    let buffer_line = info.buffer_line;
                    move |_, _: &mut Window, cx: &mut App| {
                        cx.stop_propagation();

                        state.update(cx, |state, cx| {
                            state.display_map.toggle_fold(buffer_line);
                            cx.notify();
                        });
                    }
                })
                .into_any_element();

            icon.prepaint_as_root(
                fold_icon_bounds.origin,
                fold_icon_bounds.size.into(),
                window,
                cx,
            );

            icon_layout
                .icons
                .push((info.display_row, info.is_folded, icon));
        }

        icon_layout
    }

    /// Paint fold icons using prepaint hitboxes.
    ///
    /// This handles:
    /// - Rendering fold icons (chevron-right for folded, chevron-down for expanded)
    /// - Mouse click handling to toggle fold state
    /// - Cursor style changes on hover
    /// - Only show icon on hover or for current line
    fn paint_fold_icons(
        &mut self,
        fold_icon_layout: &mut FoldIconLayout,
        current_row: Option<usize>,
        window: &mut Window,
        cx: &mut App,
    ) {
        let is_hovered = fold_icon_layout.line_number_hitbox.is_hovered(window);
        if !fold_icon_layout.icons.is_empty() {
            // Mouse moves do not repaint the editor, so repaint when the pointer
            // enters or leaves the gutter to show or hide the hover chevrons.
            let hitbox = fold_icon_layout.line_number_hitbox.clone();
            let entity_id = self.state.entity_id();
            window.on_mouse_event(move |_: &MouseMoveEvent, phase, window, cx| {
                if phase.bubble() && hitbox.is_hovered(window) != is_hovered {
                    cx.notify(entity_id);
                }
            });
        }
        for (display_row, is_folded, icon) in fold_icon_layout.icons.iter_mut() {
            let is_current_line = current_row == Some(*display_row);

            if !is_hovered && !is_current_line && !*is_folded {
                continue;
            }

            icon.paint(window, cx);
        }
    }

    fn token_element(
        &self,
        token: &super::InlineTokenContext,
        window: &mut Window,
        cx: &mut App,
    ) -> AnyElement {
        use gpui::{
            InteractiveElement as _, StatefulInteractiveElement as _, prelude::FluentBuilder as _,
        };
        let presentation = self.state.read(cx).token_presentation.clone();
        let child = presentation.render(token, window, cx);
        // Preserve interaction state only for the same token occurrence and
        // hover eligibility. Replacements and re-enabling start fresh.
        let start = token.range().start;
        let down_state = self.state.clone();
        let click_state = self.state.clone();
        let move_state = self.state.clone();
        let hover_state = self.state.clone();
        let hover_token = token.token().clone();
        let disabled = token.is_disabled();
        let hover_enabled = presentation.has_hover_listener() && !disabled;
        let id = gpui::ElementId::from(("inline-token", start));
        let id = gpui::ElementId::from((id, token.token().id().clone()));
        let id = gpui::ElementId::from((id, token.token().text().clone()));
        let id = gpui::ElementId::from((id, token.token().label().clone()));
        let id = gpui::ElementId::from((
            id,
            gpui::SharedString::from(if hover_enabled {
                "hover-enabled"
            } else {
                "hover-disabled"
            }),
        ));
        let accessible = presentation.has_listener() && !disabled;
        let accessible_state = self.state.clone();
        gpui::div()
            .id(id)
            .flex()
            .items_center()
            .h(token.line_height())
            .max_w(token.available_width())
            .overflow_hidden()
            // A token is an object, not text: the arrow, never the I-beam.
            .cursor_default()
            .when(accessible, |this| {
                this.role(gpui::Role::Button)
                    .aria_label(token.token().label().clone())
                    .on_a11y_action(gpui::AccessibleAction::Click, move |_, window, cx| {
                        let state = accessible_state.read(cx);
                        let activation = state
                            .token_spans()
                            .iter()
                            .find(|s| s.range().start == start)
                            .and_then(|span| {
                                state.range_to_bounds(&span.range()).and_then(|bounds| {
                                    state.token_activation(
                                        start,
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
                    })
            })
            .capture_any_mouse_down(move |_, window, cx| {
                if disabled {
                    window.prevent_default();
                    cx.stop_propagation();
                }
            })
            .capture_any_mouse_up(move |_, window, cx| {
                if disabled {
                    window.prevent_default();
                    cx.stop_propagation();
                }
            })
            .capture_key_down(move |_, _, cx| {
                if disabled {
                    cx.stop_propagation();
                }
            })
            .on_mouse_down(MouseButton::Left, move |event, window, cx| {
                if window.default_prevented() {
                    return;
                }
                down_state.update(cx, |state, cx| {
                    state.pressed_token = None;
                    if event.click_count == 2 {
                        if let Some(span) = state
                            .token_spans()
                            .iter()
                            .find(|s| s.range().start == start)
                        {
                            state.set_selected_range(span.range(), cx);
                            state.focus(window, cx);
                            window.prevent_default();
                        }
                    } else if event.click_count == 1
                        && !event.modifiers.shift
                        && !event.modifiers.alt
                    {
                        state.pressed_token =
                            Some((start, state.document_revision, event.position));
                    }
                });
            })
            .on_mouse_move(move |event, _, cx| {
                move_state.update(cx, |state, _| {
                    if state.pressed_token.as_ref().is_some_and(|(_, _, p)| {
                        (event.position.x - p.x).abs() + (event.position.y - p.y).abs() > px(4.)
                    }) {
                        state.pressed_token = None;
                    }
                });
            })
            .on_click(move |event, window, cx| {
                let activation = click_state.update(cx, |state, cx| {
                    let (pressed, revision, _) = state.pressed_token.take()?;
                    if pressed != start || revision != state.document_revision {
                        return None;
                    }
                    if event.modifiers().shift || event.modifiers().alt {
                        return None;
                    }
                    let span = state
                        .token_spans()
                        .iter()
                        .find(|s| s.range().start == start)?
                        .clone();
                    // A click selects the whole token; opening it is the
                    // listener's decision.
                    state.set_selected_range(span.range(), cx);
                    let bounds = state.range_to_bounds(&span.range())?;
                    state.token_activation(start, bounds, event.clone())
                });
                if let Some((listener, event)) = activation {
                    listener(&event, window, cx);
                }
            })
            .on_hover(move |hovered, window, cx| {
                // Hover never selects or edits; it only reports presence so the
                // application can show a tooltip or run custom logic.
                let hovered = *hovered;
                let activation = hover_state.update(cx, |state, _| {
                    // Anchor to the real laid-out token rect, not the
                    // range-to-bounds guess: a token at a soft-wrap boundary
                    // would otherwise report a zero/negative width or a
                    // two-row height.
                    let bounds = if hovered {
                        state.token_bounds.get(&start).copied()?
                    } else {
                        // Exits use entry geometry even if an earlier callback
                        // removed the token and its current bounds.
                        Bounds::default()
                    };
                    state.token_hover(start, bounds, hovered, Some(&hover_token))
                });
                if let Some((listener, event)) = activation {
                    listener(&event, window, cx);
                }
            })
            .child(child)
            .into_any_element()
    }

    fn measure_tokens(
        &self,
        width: Pixels,
        line_height: Pixels,
        viewport: Pixels,
        window: &mut Window,
        cx: &mut App,
    ) -> std::collections::HashMap<usize, (AnyElement, Size<Pixels>)> {
        let style = window.text_style();
        let state = self.state.read(cx);
        let key = (
            style.font(),
            style.font_size.to_pixels(window.rem_size()),
            width,
            line_height,
            state.is_single_line() || !state.soft_wrap,
        );
        if !state.tokens_visible() {
            if state.token_layout_cache.is_none() {
                let mut exit = self.state.update(cx, |state, _| {
                    state.token_bounds.clear();
                    state.reconcile_token_hover()
                });
                while let Some((listener, event)) = exit {
                    listener(&event, window, cx);
                    exit = self
                        .state
                        .update(cx, |state, _| state.reconcile_token_hover());
                }
                return Default::default();
            }
            self.state.update(cx, |state, cx| {
                state.display_map.set_inline_metrics(Rc::from([]), cx)
            });
            let mut exit = self.state.update(cx, |state, _| {
                state.token_bounds.clear();
                state.reconcile_token_hover()
            });
            while let Some((listener, event)) = exit {
                listener(&event, window, cx);
                exit = self
                    .state
                    .update(cx, |state, _| state.reconcile_token_hover());
            }
            return Default::default();
        }
        let revision = state.document_revision;
        let cache = state.token_layout_cache.as_ref();
        let all = cache.is_none_or(|cache| {
            cache.key.as_ref() != Some(&key)
                || cache.revision != revision
                || state
                    .token_spans()
                    .iter()
                    .any(|span| !cache.widths.contains_key(span.token()))
        });
        let (visible, _, _) = self.calculate_visible_range(state, line_height, viewport);
        let start = state.text.line_start_offset(visible.start);
        let end = state.text.line_end_offset(visible.end.saturating_sub(1));
        let spans = state.token_spans();
        let first = if all {
            0
        } else {
            spans.partition_point(|s| s.range().end <= start)
        };
        let contexts: Vec<_> = spans[first..]
            .iter()
            .take_while(|s| all || s.range().start <= end)
            .filter(|span| {
                let range = span.range();
                (range.start <= end && range.end >= start)
                    || cache.is_none_or(|cache| {
                        cache.key.as_ref() != Some(&key) || !cache.widths.contains_key(span.token())
                    })
            })
            .map(|span| state.token_context(span, line_height, width))
            .collect();
        let mut elements = std::collections::HashMap::new();
        let mut measured = Vec::new();
        for token in contexts {
            let mut element = self.token_element(&token, window, cx);
            let size = element.layout_as_root(
                size(
                    gpui::AvailableSpace::MaxContent,
                    gpui::AvailableSpace::Definite(line_height),
                ),
                window,
                cx,
            );
            measured.push((token.token().clone(), size.width.min(width).max(px(1.))));
            elements.insert(token.range().start, (element, size));
        }
        self.state.update(cx, |state, cx| {
            let mut cache = state.token_layout_cache.take().unwrap_or_default();
            let mut changed = cache.key.as_ref() != Some(&key) || cache.revision != revision;
            if cache.key.as_ref() != Some(&key) {
                cache.widths.clear();
            }
            for (token, width) in measured {
                changed |= cache.widths.get(&token) != Some(&width);
                cache.widths.insert(token, width);
            }
            cache.key = Some(key);
            if changed {
                let spans = state.token_spans();
                let tokens: std::collections::HashSet<_> =
                    spans.iter().map(|s| s.token()).collect();
                cache.widths.retain(|token, _| tokens.contains(token));
                cache.metrics = spans
                    .iter()
                    .filter_map(|span| {
                        cache
                            .widths
                            .get(span.token())
                            .map(|width| (span.range(), *width))
                    })
                    .collect();
                cache.revision = revision;
                if state.is_single_line() || !state.soft_wrap {
                    let mut rows: Vec<_> = spans
                        .iter()
                        .map(|s| state.text.offset_to_point(s.range().start).row)
                        .collect();
                    rows.push(state.display_map.longest_row());
                    rows.sort_unstable();
                    rows.dedup();
                    cache.unwrapped_width = rows
                        .into_iter()
                        .map(|row| {
                            let start = state.text.line_start_offset(row);
                            let text = state.text.slice_line(row).to_string();
                            let mut offset = 0;
                            let mut width = px(0.);
                            let first = spans.partition_point(|s| s.range().end <= start);
                            for span in spans[first..]
                                .iter()
                                .take_while(|s| s.range().start < start + text.len())
                            {
                                let local = span.range().start - start..span.range().end - start;
                                let part = &text[offset..local.start];
                                width += window
                                    .text_system()
                                    .shape_line(
                                        part.to_owned().into(),
                                        style.font_size.to_pixels(window.rem_size()),
                                        &[style.to_run(part.len())],
                                        None,
                                    )
                                    .width;
                                width +=
                                    cache.widths.get(span.token()).copied().unwrap_or_default();
                                offset = local.end;
                            }
                            let part = &text[offset..];
                            width
                                + window
                                    .text_system()
                                    .shape_line(
                                        part.to_owned().into(),
                                        style.font_size.to_pixels(window.rem_size()),
                                        &[style.to_run(part.len())],
                                        None,
                                    )
                                    .width
                        })
                        .max()
                        .unwrap_or_default();
                }
            }
            let metrics = cache.metrics.clone();
            state.token_layout_cache = Some(cache);
            state.display_map.set_inline_metrics(metrics, cx);
            if state.mode.is_auto_grow() {
                let rows = state.mode.rows();
                state.mode.update_auto_grow(&state.display_map);
                if state.mode.rows() != rows {
                    cx.notify();
                }
            }
        });
        elements
    }

    fn layout_token_lines(
        state: &InputBaseState<M>,
        last_layout: &LastLayout,
        font_size: Pixels,
        runs: &[TextRun],
        window: &mut Window,
    ) -> Vec<LineLayout> {
        use crate::input::display_map::{InlineFragment, InputLine};
        let spans = state.token_spans();
        let cache = state
            .token_layout_cache
            .as_ref()
            .expect("tokens measured before shaping");
        let mut run_offset = 0;
        last_layout
            .visible_buffer_lines
            .iter()
            .map(|&row| {
                let line_start = state.text.line_start_offset(row);
                let text: String = state.text.slice_line(row).into();
                let ranges = if state.is_single_line() {
                    smallvec::smallvec![0..text.len()]
                } else {
                    state
                        .display_map
                        .line(row)
                        .expect("prepared line")
                        .wrapped_lines
                        .clone()
                };
                let mut lines: SmallVec<[InputLine; 1]> = SmallVec::new();
                for range in ranges {
                    let mut fragments = Vec::new();
                    let mut offset = range.start;
                    let mut x = px(0.);
                    let first =
                        spans.partition_point(|s| s.range().end <= line_start + range.start);
                    for span in spans[first..]
                        .iter()
                        .take_while(|s| s.range().start < line_start + range.end)
                    {
                        let local = span.range().start - line_start..span.range().end - line_start;
                        if offset < local.start {
                            let part = offset..local.start;
                            let shaped = window.text_system().shape_line(
                                text[part.clone()].to_owned().into(),
                                font_size,
                                &runs_for_range(runs, run_offset, &part),
                                None,
                            );
                            let width = shaped.width;
                            fragments.push(InlineFragment {
                                range: part.start - range.start..part.end - range.start,
                                x,
                                width,
                                text: Some(shaped),
                            });
                            x += width;
                        }
                        let width = cache.widths.get(span.token()).copied().unwrap_or_default();
                        fragments.push(InlineFragment {
                            range: local.start - range.start..local.end - range.start,
                            x,
                            width,
                            text: None,
                        });
                        x += width;
                        offset = local.end;
                    }
                    if offset < range.end {
                        let part = offset..range.end;
                        let shaped = window.text_system().shape_line(
                            text[part.clone()].to_owned().into(),
                            font_size,
                            &runs_for_range(runs, run_offset, &part),
                            None,
                        );
                        let width = shaped.width;
                        fragments.push(InlineFragment {
                            range: part.start - range.start..part.end - range.start,
                            x,
                            width,
                            text: Some(shaped),
                        });
                    }
                    lines.push(InputLine::inline(text[range].to_owned().into(), fragments));
                }
                let indent = state.display_map.line(row).map_or(0, |line| line.indent);
                let wrap_indent = if indent > 0 && lines.len() > 1 {
                    let bytes = text
                        .char_indices()
                        .nth(indent as usize)
                        .map_or(text.len(), |(ix, _)| ix);
                    lines[0].x_for_index(bytes)
                } else {
                    px(0.)
                };
                run_offset += text.len() + 1;
                LineLayout::new()
                    .inline_lines(lines)
                    .wrap_indent(wrap_indent)
            })
            .collect()
    }

    /// Asks the scroll containers around a focused input to bring it into
    /// view, once when it gains focus and again whenever the fully visible
    /// part of the window changes, so manual scrolling in between is left
    /// alone. Ancestors must support autoscroll requests; inset-only keyboard
    /// avoidance additionally requires the ancestor to use the fully visible
    /// viewport for its scrolling bounds and scroll range. Stock GPUI's List
    /// uses layout bounds and does not avoid inset-only occlusion.
    ///
    /// A single-line input asks for all of itself. A taller one asks for the
    /// line with the caret, or its top part when it has no caret.
    fn request_reveal(
        &self,
        input_bounds: Bounds<Pixels>,
        cursor_infos: &[CursorRenderInfo],
        cursor_scroll_offset: Point<Pixels>,
        line_height: Pixels,
        window: &mut Window,
        cx: &mut App,
    ) {
        /// Room left around the request for the field's padding and border.
        const REVEAL_MARGIN: Pixels = px(8.);
        /// How much of a caretless multi-line input is revealed.
        const REVEAL_MAX_HEIGHT: Pixels = px(120.);

        let focused = self.state.read(cx).focus_handle.is_focused(window);
        let viewport = window.fully_visible_bounds();
        let reveal = self.state.update(cx, |state, _| {
            let target = focused.then_some(viewport);
            let changed = state.revealed_viewport != target;
            state.revealed_viewport = target;
            focused && changed
        });
        if !reveal || input_bounds.size.height <= px(0.) {
            return;
        }

        let (top, height) = if !self.state.read(cx).is_multi_line() {
            (input_bounds.top(), input_bounds.size.height)
        } else if let Some(caret) = cursor_infos.iter().find(|info| info.is_active) {
            let top = (caret.bounds.top() + cursor_scroll_offset.y)
                .clamp(input_bounds.top(), input_bounds.bottom());
            (top, line_height.min(input_bounds.bottom() - top))
        } else {
            (
                input_bounds.top(),
                input_bounds.size.height.min(REVEAL_MAX_HEIGHT),
            )
        };
        let request = Bounds::new(
            point(input_bounds.left(), top),
            size(input_bounds.size.width, height),
        );
        window.request_autoscroll(request.dilate(REVEAL_MARGIN));
    }

    fn prepaint_tokens(
        &self,
        layout: &LastLayout,
        bounds: Bounds<Pixels>,
        mut measured: std::collections::HashMap<usize, (AnyElement, Size<Pixels>)>,
        window: &mut Window,
        cx: &mut App,
    ) -> Vec<AnyElement> {
        let state = self.state.read(cx);
        if !state.tokens_visible() {
            let mut exit = self.state.update(cx, |state, _| {
                state.token_bounds.clear();
                state.reconcile_token_hover()
            });
            while let Some((listener, event)) = exit {
                listener(&event, window, cx);
                exit = self
                    .state
                    .update(cx, |state, _| state.reconcile_token_hover());
            }
            return vec![];
        }
        let width = state
            .token_layout_cache
            .as_ref()
            .and_then(|c| c.key.as_ref())
            .map_or(bounds.size.width, |k| k.2);
        let mut placements = Vec::new();
        let mut y = layout.visible_top;
        for (ix, &row) in layout.visible_buffer_lines.iter().enumerate() {
            let start = state.text.line_start_offset(row);
            let end = state.text.line_end_offset(row);
            let spans = state.token_spans();
            let first = spans.partition_point(|s| s.range().end <= start);
            for span in spans[first..].iter().take_while(|s| s.range().start < end) {
                if let Some(position) =
                    layout.lines[ix].position_for_index(span.range().start - start, layout, false)
                {
                    placements.push((
                        state.token_context(span, layout.line_height, width),
                        bounds.origin + position + point(layout.line_number_width, y),
                    ));
                }
            }
            y += layout.lines[ix].size(layout.line_height).height;
        }
        let mut out = Vec::new();
        let mut token_bounds = std::collections::HashMap::new();
        for (token, origin) in placements {
            let (mut element, element_size) = match measured.remove(&token.range().start) {
                Some(found) => found,
                None => {
                    let mut element = self.token_element(&token, window, cx);
                    let element_size = element.layout_as_root(
                        size(
                            gpui::AvailableSpace::MaxContent,
                            gpui::AvailableSpace::Definite(layout.line_height),
                        ),
                        window,
                        cx,
                    );
                    (element, element_size)
                }
            };
            element.prepaint_at(origin, window, cx);
            token_bounds.insert(token.range().start, Bounds::new(origin, element_size));
            out.push(element);
        }
        let mut exit = self.state.update(cx, |state, _| {
            state.token_bounds = token_bounds;
            state.reconcile_token_hover()
        });
        while let Some((listener, event)) = exit {
            listener(&event, window, cx);
            exit = self
                .state
                .update(cx, |state, _| state.reconcile_token_hover());
        }
        out
    }

    #[allow(clippy::too_many_arguments)]
    fn layout_lines(
        state: &InputBaseState<M>,
        display_text: &Rope,
        last_layout: &LastLayout,
        font_size: Pixels,
        runs: &[TextRun],
        bg_segments: &[(Range<usize>, Hsla)],
        whitespace_indicators: Option<WhitespaceIndicators>,
        window: &mut Window,
    ) -> Vec<LineLayout> {
        let is_single_line = state.is_single_line();
        if state.tokens_visible() {
            return Self::layout_token_lines(state, last_layout, font_size, runs, window);
        }

        let tab_stop = tab_stop_width(
            window.text_system(),
            &window.text_style().font(),
            font_size,
            state.mode.tab_size().tab_size,
        );

        if is_single_line {
            let text: SharedString = display_text.to_string().into();
            let aligned_runs = align_runs_to_char_boundaries(&text, runs);
            let line_runs = aligned_runs.as_deref().unwrap_or(runs);
            let mut shaped_line = window
                .text_system()
                .shape_line(text, font_size, line_runs, None);
            expand_tabs(&mut shaped_line, tab_stop);

            let line_layout = LineLayout::new()
                .lines(smallvec::smallvec![shaped_line])
                .with_background(has_background(line_runs))
                .with_whitespaces(whitespace_indicators);
            return vec![line_layout];
        }

        // Empty to use placeholder, the placeholder is not in the wrapper map.
        if state.text.len() == 0 {
            let placeholder_text = display_text.to_string();
            let mut placeholder_lines = SmallVec::new();
            let mut line_has_background = false;

            for (line, line_runs) in placeholder_line_runs(&placeholder_text, runs) {
                let shaped_line = window.text_system().shape_line(
                    line.to_string().into(),
                    font_size,
                    &line_runs,
                    None,
                );
                line_has_background |= has_background(&line_runs);
                placeholder_lines.push(shaped_line);
            }

            // Keep placeholder lines in a single layout to stay parallel with visible_* metadata.
            let line_layout = LineLayout::new()
                .lines(placeholder_lines)
                .with_background(line_has_background)
                .with_whitespaces(whitespace_indicators);
            return vec![line_layout];
        }

        let mut lines = Vec::with_capacity(last_layout.visible_buffer_lines.len());
        // run_offset tracks position in the runs vec coordinate space (only visible line bytes).
        // This is separate from the visible_text offset because runs from highlight_lines
        // only cover visible (non-folded) lines.
        let mut run_offset = 0;

        for (vi, &buffer_line) in last_layout.visible_buffer_lines.iter().enumerate() {
            let line_text: String = display_text.slice_line(buffer_line).into();
            let line_item = state
                .display_map
                .line(buffer_line)
                .expect("line should exists in wrapper");

            debug_assert_eq!(line_item.len(), line_text.len());

            let mut wrapped_lines: SmallVec<[ShapedLine; 1]> = SmallVec::with_capacity(1);
            let mut line_has_background = false;

            for range in &line_item.wrapped_lines {
                let line_runs = runs_for_range(runs, run_offset, &range);
                let line_runs = if bg_segments.is_empty() {
                    line_runs
                } else {
                    split_runs_by_bg_segments(
                        last_layout.visible_line_byte_offsets[vi] + (range.start),
                        &line_runs,
                        bg_segments,
                    )
                };

                let sub_line: SharedString = line_text[range.clone()].to_string().into();
                let line_runs =
                    align_runs_to_char_boundaries(&sub_line, &line_runs).unwrap_or(line_runs);
                let mut shaped_line = window
                    .text_system()
                    .shape_line(sub_line, font_size, &line_runs, None);
                expand_tabs(&mut shaped_line, tab_stop);

                line_has_background |= has_background(&line_runs);
                wrapped_lines.push(shaped_line);
            }

            // Use the first visual line's indentation width for continuation lines.
            let wrap_indent = if line_item.indent > 0 && wrapped_lines.len() > 1 {
                let indent_byte_len = line_text
                    .char_indices()
                    .nth(line_item.indent as usize)
                    .map(|(ix, _)| ix)
                    .unwrap_or(line_text.len());
                wrapped_lines[0].x_for_index(indent_byte_len)
            } else {
                px(0.)
            };

            let line_layout = LineLayout::new()
                .lines(wrapped_lines)
                .wrap_indent(wrap_indent)
                .with_background(line_has_background)
                .with_whitespaces(whitespace_indicators.clone());
            lines.push(line_layout);

            // +1 for the `\n`
            run_offset += line_text.len() + 1;
        }

        lines
    }

    /// First usize is the offset of skipped.
    fn highlight_lines(
        &mut self,
        visible_buffer_lines: &[usize],
        _visible_top: Pixels,
        visible_byte_range: Range<usize>,
        cx: &mut App,
    ) -> Option<Vec<(Range<usize>, HighlightStyle)>> {
        let state = self.state.read(cx);
        let text = &state.text;
        let is_multi_line = state.is_multi_line();

        let (mut highlighter, diagnostics) = match &state.mode {
            LayoutMode::CodeEditor {
                highlighter,
                diagnostics,
                ..
            } => (highlighter.borrow_mut(), diagnostics),
            _ => {
                return (!state.masked)
                    .then(|| {
                        compose_decoration_collections(
                            Vec::new(),
                            state.extras.decoration_layers().into_iter(),
                            visible_byte_range,
                        )
                    })
                    .flatten();
            }
        };
        let Some(highlighter) = highlighter.as_mut() else {
            return (!state.masked)
                .then(|| {
                    compose_decoration_collections(
                        Vec::new(),
                        state.extras.decoration_layers().into_iter(),
                        visible_byte_range,
                    )
                })
                .flatten();
        };

        let mut styles = Vec::with_capacity(visible_buffer_lines.len());
        // Byte ranges of the flushed line groups; the composed styles are
        // clipped to these at the end so the resulting runs cover exactly the
        // visible (non-folded) lines' bytes.
        let mut group_ranges: Vec<Range<usize>> = Vec::new();

        // Helper to flush a contiguous range of lines. These ranges are disjoint,
        // so appending avoids repeatedly cloning and recombining prior styles.
        let mut flush_range =
            |start_line: usize, end_line: usize, skip: bool, styles: &mut Vec<_>| {
                let byte_start = text.line_start_offset(start_line);
                let byte_end = if is_multi_line {
                    // +1 for `\n`
                    text.line_start_offset(end_line + 1)
                } else {
                    text.line_end_offset(end_line)
                };
                let range_styles = if skip {
                    vec![(byte_start..byte_end, HighlightStyle::default())]
                } else {
                    highlighter.styles(
                        &(byte_start..byte_end),
                        state.editor_style.highlight_styles.as_ref(),
                    )
                };

                group_ranges.push(byte_start..byte_end);
                styles.extend(range_styles);
            };

        // Group contiguous visible lines into ranges and call styles() once per range
        let mut visible_iter = visible_buffer_lines.iter().peekable();
        let mut range_start: Option<usize> = None;

        while let Some(&line) = visible_iter.next() {
            // Check if this line is too long for highlighting
            let line_len = text.slice_line(line).len();
            if line_len > MAX_HIGHLIGHT_LINE_LENGTH {
                // Flush any accumulated range first
                if let Some(start) = range_start.take() {
                    flush_range(start, line - 1, false, &mut styles);
                }

                flush_range(line, line, true, &mut styles);
                continue;
            }

            range_start.get_or_insert(line);

            // Check if next line is contiguous, if so keep accumulating
            if visible_iter
                .peek()
                .map(|&&next| next == line + 1)
                .unwrap_or(false)
            {
                continue;
            }

            // Flush the contiguous range
            let start_line = range_start.take().unwrap();
            flush_range(start_line, line, false, &mut styles);
        }

        let diagnostic_styles: Vec<_> = diagnostics
            .range(visible_byte_range.clone())
            .map(|entry| {
                (
                    entry.range.clone(),
                    diagnostic_highlight_style(entry.severity, state.editor_style.diagnostics),
                )
            })
            .collect();

        // Range semantic tokens, resolved from the LSP provider's cached
        // result through the active highlight theme so it shares the same
        // colour vocabulary as the tree-sitter path. Empty Vec when no
        // provider is set, so `combine_highlights` short-circuits.
        let custom_styles = state.extras.semantic_token_styles(
            text,
            &visible_byte_range,
            state.editor_style.highlight_styles.as_ref(),
        );

        // hover definition style
        if let Some(hover_style) = M::hover_definition_style(self.state.read(cx), cx) {
            styles.push(hover_style);
        }

        // Compose tree-sitter, semantic, application, then diagnostic styles.
        styles = gpui::combine_highlights(custom_styles, styles).collect();
        if !state.masked {
            styles = compose_decoration_collections(
                styles,
                state.extras.decoration_layers().into_iter(),
                visible_byte_range.clone(),
            )
            .unwrap_or_default();
        }
        styles = gpui::combine_highlights(diagnostic_styles, styles).collect();

        // Some sources reach outside the flushed groups — a diagnostic
        // straddling the viewport edge, or any range inside a folded region —
        // which would inject extra bytes into the runs coordinate space and
        // shift every later run boundary (see `layout_lines`). Clip the
        // composed styles back to the groups.
        styles = clip_styles_to_ranges(styles, &group_ranges);

        Some(styles)
    }
}

/// Layout data for a single caret, produced by [`TextElement::layout_cursors`].
#[derive(Clone, Debug)]
struct CursorRenderInfo {
    bounds: Bounds<Pixels>,
    is_active: bool,
}

pub(super) struct PrepaintState {
    /// The lines of entire lines.
    last_layout: LastLayout,
    token_elements: Vec<AnyElement>,
    /// The lines only contains the visible lines in the viewport, based on `visible_range`.
    ///
    /// The child is the soft lines.
    line_numbers: Option<Vec<SmallVec<[ShapedLine; 1]>>>,
    /// Size of the scrollable area by entire lines.
    scroll_size: Size<Pixels>,
    /// Caret bounds for every selection, active flagged.
    cursor_infos: Vec<CursorRenderInfo>,
    cursor_scroll_offset: Point<Pixels>,
    /// row index (zero based), no wrap, same line as the cursor.
    current_row: Option<usize>,
    selection_paths: Vec<Path<Pixels>>,
    hover_highlight_path: Option<Path<Pixels>>,
    search_match_paths: Vec<(Path<Pixels>, bool)>,
    document_color_paths: Vec<(Path<Pixels>, Hsla)>,
    range_decoration_fills: Vec<(Path<Pixels>, Hsla)>,
    range_decoration_frames: Vec<(Path<Pixels>, Hsla)>,
    gutter_decorations: Vec<PaintQuad>,
    /// How far the gutter decoration strip pushes the line numbers right.
    line_number_offset: Pixels,
    hover_definition_hitbox: Option<Hitbox>,
    indent_guides_path: Option<Path<Pixels>>,
    /// The whole input, for deciding whether a long press started in it.
    hitbox: Hitbox,
    bounds: Bounds<Pixels>,
    /// Fold icon layout data
    fold_icon_layout: FoldIconLayout,
    // Inline completion rendering data
    /// Shaped ghost lines to paint after cursor row (completion lines 2+)
    ghost_lines: Vec<ShapedLine>,
    /// First line of inline completion (painted after cursor on same line)
    ghost_first_line: Option<ShapedLine>,
    ghost_lines_height: Pixels,
}

impl PrepaintState {
    /// Returns all cursor infos adjusted for scroll offset.
    fn cursor_infos_with_scroll(&self) -> Vec<CursorRenderInfo> {
        self.cursor_infos
            .iter()
            .map(|info| {
                let mut bounds = info.bounds;
                bounds.origin.y += self.cursor_scroll_offset.y;
                CursorRenderInfo {
                    bounds,
                    is_active: info.is_active,
                }
            })
            .collect()
    }
}

/// Align a caret to whole device pixels.
///
/// Text positions are fractional, and a one-pixel caret at a fractional x is
/// spread over two device pixels by antialiasing, which draws it faint and
/// thin. Rounding its edges to the device grid keeps every caret crisp.
fn snap_caret_to_device_pixels(bounds: Bounds<Pixels>, scale_factor: f32) -> Bounds<Pixels> {
    let x = (bounds.origin.x * scale_factor).round() / scale_factor;
    let width = (bounds.size.width * scale_factor).round().max(px(1.)) / scale_factor;
    Bounds::new(point(x, bounds.origin.y), size(width, bounds.size.height))
}

impl<M: InputModeKind> IntoElement for TextElement<M> {
    type Element = Self;

    fn into_element(self) -> Self::Element {
        self
    }
}

/// A debug function to print points as SVG path.
#[allow(unused)]
fn print_points_as_svg_path(
    line_corners: &Vec<gpui::Corners<Pixels>>,
    points: &Vec<Point<Pixels>>,
) {
    for corners in line_corners {
        println!(
            "tl: ({}, {}), tr: ({}, {}), bl: ({}, {}), br: ({}, {})",
            corners.top_left.as_f32() as i32,
            corners.top_left.as_f32() as i32,
            corners.top_right.as_f32() as i32,
            corners.top_right.as_f32() as i32,
            corners.bottom_left.as_f32() as i32,
            corners.bottom_left.as_f32() as i32,
            corners.bottom_right.as_f32() as i32,
            corners.bottom_right.as_f32() as i32,
        );
    }

    if points.len() > 0 {
        println!(
            "M{},{}",
            points[0].x.as_f32() as i32,
            points[0].y.as_f32() as i32
        );
        for p in points.iter().skip(1) {
            println!("L{},{}", p.x.as_f32() as i32, p.y.as_f32() as i32);
        }
    }
}

fn frame_outline_points(corners: &[Corners<Point<Pixels>>]) -> Vec<Point<Pixels>> {
    let rects = corners
        .iter()
        .map(|corners| (corners.top_left, corners.bottom_right))
        .collect::<Vec<_>>();
    let mut points = Vec::with_capacity(rects.len() * 4);
    let first = rects[0];
    let last = rects[rects.len() - 1];
    points.push(first.0);
    points.push(point(first.1.x, first.0.y));
    for pair in rects.windows(2) {
        let current = pair[0];
        let next = pair[1];
        points.push(current.1);
        points.push(point(next.1.x, current.1.y));
        points.push(point(next.1.x, next.1.y));
    }
    if points.last() != Some(&last.1) {
        points.push(last.1);
    }
    points.push(point(last.0.x, last.1.y));
    for pair in rects.windows(2).rev() {
        let current = pair[1];
        let next = pair[0];
        points.push(point(current.0.x, current.0.y));
        points.push(point(next.0.x, current.0.y));
        points.push(point(next.0.x, next.0.y));
    }
    if points.last() != points.first() {
        points.push(points[0]);
    }
    points
}

fn pad_frame_corners(
    corners: &[Corners<Point<Pixels>>],
    horizontal_padding: Pixels,
) -> Vec<Corners<Point<Pixels>>> {
    corners
        .iter()
        .map(|corners| Corners {
            top_left: point(corners.top_left.x - horizontal_padding, corners.top_left.y),
            top_right: point(
                corners.top_right.x + horizontal_padding,
                corners.top_right.y,
            ),
            bottom_left: point(
                corners.bottom_left.x - horizontal_padding,
                corners.bottom_left.y,
            ),
            bottom_right: point(
                corners.bottom_right.x + horizontal_padding,
                corners.bottom_right.y,
            ),
        })
        .collect()
}

fn snap_frame_outline(
    points: &[Point<Pixels>],
    stroke_width: Pixels,
    scale_factor: f32,
) -> (Pixels, Vec<Point<Pixels>>) {
    let physical_width = ((stroke_width.as_f32() * scale_factor).abs() - 0.5)
        .ceil()
        .max(1.);
    let stroke_width = px(physical_width / scale_factor);
    let center_offset = if physical_width % 2. == 0. { 0. } else { 0.5 };
    let snap = |value: Pixels| {
        px(
            ((value.as_f32() * scale_factor - center_offset).round() + center_offset)
                / scale_factor,
        )
    };
    (
        stroke_width,
        points
            .iter()
            .map(|point| point.map(snap))
            .collect::<Vec<_>>(),
    )
}

fn clamp_frame_to_content_mask(
    points: Vec<Point<Pixels>>,
    stroke_width: Pixels,
    content_mask: Bounds<Pixels>,
) -> Vec<Point<Pixels>> {
    let half_width = stroke_width / 2.;
    let min_x = content_mask.left() + half_width;
    let max_x = (content_mask.right() - half_width).max(min_x);
    points
        .into_iter()
        .map(|p| point(p.x.max(min_x).min(max_x), p.y))
        .collect()
}

impl<M: InputModeKind> Element for TextElement<M> {
    type RequestLayoutState = ();
    type PrepaintState = PrepaintState;

    fn id(&self) -> Option<ElementId> {
        None
    }

    fn source_location(&self) -> Option<&'static std::panic::Location<'static>> {
        None
    }

    fn request_layout(
        &mut self,
        _id: Option<&GlobalElementId>,
        _: Option<&gpui::InspectorElementId>,
        window: &mut Window,
        cx: &mut App,
    ) -> (LayoutId, Self::RequestLayoutState) {
        let state = self.state.read(cx);
        let line_height = window.line_height();

        let mut style = Style::default();
        style.size.width = relative(1.).into();
        if state.is_multi_line() {
            style.flex_grow = 1.0;
            style.size.height = relative(1.).into();
            // At least `rows` tall (auto grow: the content's rows, capped at
            // `max_rows`); a taller parent still fills it.
            let rows = state.mode.max_rows().min(state.mode.rows());
            style.min_size.height = (rows * line_height).into();
        } else {
            // For single-line inputs, the minimum height should be the line height
            style.size.height = line_height.into();
        };

        (window.request_layout(style, [], cx), ())
    }

    fn prepaint(
        &mut self,
        _id: Option<&GlobalElementId>,
        _: Option<&gpui::InspectorElementId>,
        bounds: Bounds<Pixels>,
        _request_layout: &mut Self::RequestLayoutState,
        window: &mut Window,
        cx: &mut App,
    ) -> Self::PrepaintState {
        let style = window.text_style();
        let font = style.font();
        let text_size = style.font_size.to_pixels(window.rem_size());
        // Past the end of a line there are no glyphs to hit-test against, so a pointer
        // out there is measured in spaces instead.
        let space_width = {
            let font_id = window.text_system().resolve_font(&font);
            window.text_system().layout_width(font_id, text_size, ' ')
        };

        // Text stretched past an end is drawn that far from where it scrolled
        // to, inside the frame that clips it, and springs back over the next
        // frames. Scrolling and everything measured from it stay exact.
        let mut stretch = self.state.update(cx, |state, cx| {
            state.display_map.set_font(font, text_size, cx);
            let tab_size = state.mode.tab_size().tab_size;
            state.display_map.set_tab_size(tab_size, cx);
            state.display_map.ensure_text_prepared(&state.text, cx);
            if cx.reduce_motion() {
                state.overscroll.reset();
            } else if state.overscroll.step(cx.background_executor().now()) {
                window.request_animation_frame();
            }
            state.overscroll.offset()
        });

        let state = self.state.read(cx);
        let multi_line = state.is_multi_line();
        let text = state.text.clone();
        let is_empty = text.len() == 0;
        let placeholder = self.placeholder.clone();

        let text_style = window.text_style();
        let disabled = state.disabled;
        let dim = |color: Hsla| if disabled { color.opacity(0.5) } else { color };
        let fg = dim(text_style.color);
        let (display_text, text_color) = if is_empty {
            (
                &Rope::from(placeholder.as_str()),
                dim(state.editor_style.muted_foreground),
            )
        } else if state.masked {
            (
                &Rope::from(MASK_CHAR.to_string().repeat(text.chars().count())),
                fg,
            )
        } else {
            (&text, fg)
        };

        // Calculate the width of the line numbers
        let (line_number_width, line_number_len) =
            Self::layout_line_numbers(&state, &text, text_size, &text_style, window);

        let mut bounds = bounds;
        let wrap_width = if multi_line && state.soft_wrap {
            Some(bounds.size.width - line_number_width - RIGHT_MARGIN)
        } else {
            None
        };

        let wrapping_indent = state.wrapping_indent;
        let wrap_width_changed = state
            .last_layout
            .as_ref()
            .map(|l| l.wrap_width != wrap_width)
            .unwrap_or(true);

        let wrapping_indent_changed = state
            .last_layout
            .as_ref()
            .map(|l| l.wrapping_indent != wrapping_indent)
            .unwrap_or(true);

        if wrap_width_changed || wrapping_indent_changed {
            self.state.update(cx, |state, cx| {
                state.display_map.on_layout_changed(wrap_width, cx);
                state.display_map.set_wrapping_indent(wrapping_indent, cx);
            });
        }

        let line_height = window.line_height();
        let token_elements = self.measure_tokens(
            (bounds.size.width - line_number_width - RIGHT_MARGIN).max(px(1.)),
            line_height,
            bounds.size.height,
            window,
            cx,
        );
        let state = self.state.read(cx);

        let (visible_range, visible_buffer_lines, visible_top) =
            self.calculate_visible_range(&state, line_height, bounds.size.height);
        let visible_start_offset = state.text.line_start_offset(visible_range.start);
        let visible_end_offset = state
            .text
            .line_end_offset(visible_range.end.saturating_sub(1));

        let highlight_styles = self.highlight_lines(
            &visible_buffer_lines,
            visible_top,
            visible_start_offset..visible_end_offset,
            cx,
        );

        let state = self.state.read(cx);

        let visible_line_byte_offsets: Vec<usize> = visible_buffer_lines
            .iter()
            .map(|&bl| state.text.line_start_offset(bl))
            .collect();

        // For password input (masked: true), convert byte offsets to masked display byte offsets so that
        // layout_match_range and position_for_index work in the correct coordinate space.
        let (visible_line_byte_offsets, visible_range_offset) = if state.masked {
            let offsets = visible_line_byte_offsets
                .iter()
                .map(|&o| masked_display_offset(&text, o))
                .collect();
            let range_offset = masked_display_offset(&text, visible_start_offset)
                ..masked_display_offset(&text, visible_end_offset);
            (offsets, range_offset)
        } else {
            (
                visible_line_byte_offsets,
                visible_start_offset..visible_end_offset,
            )
        };

        let mut last_layout = LastLayout {
            visible_range,
            visible_buffer_lines,
            visible_line_byte_offsets,
            visible_top,
            visible_range_offset,
            line_height,
            wrap_width,
            wrapping_indent,
            line_number_width,
            space_width,
            lines: Rc::new(vec![]),
            cursor_bounds: None,
            text_align: state.text_align,
            content_width: bounds.size.width,
        };

        let run = TextRun {
            len: display_text.len(),
            font: style.font(),
            color: text_color,
            background_color: None,
            underline: None,
            strikethrough: None,
        };
        let marked_run = TextRun {
            len: 0,
            font: style.font(),
            color: text_color,
            background_color: None,
            underline: Some(UnderlineStyle {
                thickness: px(1.),
                color: Some(text_color),
                wavy: false,
            }),
            strikethrough: None,
        };

        let ime_marked_range = ime_marked_display_range(
            &text,
            state.ime_marked_range.as_ref().map(|m| m.start..m.end),
            state.masked,
        );

        let runs = if let (false, Some(highlight_styles)) = (is_empty, highlight_styles) {
            let mut runs = Vec::with_capacity(highlight_styles.len() + 2);

            for (range, style) in &highlight_styles {
                let mut run = text_style.clone().highlight(*style).to_run(range.len());
                if disabled {
                    run.color = run.color.opacity(0.5);
                }

                runs.extend(split_run_for_ime_underline(
                    run,
                    range.clone(),
                    ime_marked_range.clone(),
                    marked_run.underline,
                ));
            }
            runs
        } else {
            split_run_for_ime_underline(
                run,
                0..display_text.len(),
                ime_marked_range,
                marked_run.underline,
            )
            .into_vec()
        };

        let document_colors = state
            .extras
            .document_color_swatches(&text, &last_layout.visible_range);

        // Create shaped lines for whitespace indicators before layout
        let whitespace_indicators =
            Self::layout_whitespace_indicators(&state, text_size, &text_style, window, cx);

        let lines = Self::layout_lines(
            &state,
            &display_text,
            &last_layout,
            text_size,
            &runs,
            &document_colors,
            whitespace_indicators,
            window,
        );

        let mut longest_line_width = wrap_width.unwrap_or(px(0.));
        // 1. Single line
        // 2. Multi-line with soft wrap disabled.
        if state.is_single_line() || !state.soft_wrap {
            // The longest line by byte length is only a candidate: a shorter
            // line can render wider (wide glyphs, proportional fonts). The
            // visible lines have already been shaped, so keep their widest
            // measured width as a lower bound. Caching it with the candidate
            // keeps the scroll extent stable while scrolling the line away.
            // Empty inputs lay out the placeholder, which is not scrollable content.
            let widest_laid_out_line = if is_empty {
                px(0.)
            } else {
                lines
                    .iter()
                    .map(|line| line.longest_width)
                    .max()
                    .unwrap_or(px(0.))
            };

            let longest_row = state.display_map.longest_row();
            let longest_line = state.text.slice_line(longest_row);
            let key = LongestLineKey {
                document_revision: state.document_revision,
                row: longest_row,
                len: longest_line.len(),
                font: style.font(),
                text_size,
                wrap_width,
                tab_size: state.mode.tab_size().tab_size,
            };
            let cached = state
                .longest_line_width
                .take()
                .filter(|(cached_key, _)| *cached_key == key);
            longest_line_width = match cached {
                Some((_, width)) => width.max(widest_laid_out_line),
                None => {
                    let longest_line: SharedString = longest_line.to_string().into();
                    let tab_stop =
                        tab_stop_width(window.text_system(), &key.font, text_size, key.tab_size);
                    let shaped = window.text_system().shape_line(
                        longest_line.clone(),
                        text_size,
                        &[TextRun {
                            len: longest_line.len(),
                            font: key.font.clone(),
                            color: gpui::black(),
                            background_color: None,
                            underline: None,
                            strikethrough: None,
                        }],
                        wrap_width,
                    );
                    expanded_width(&shaped, &longest_line, tab_stop).max(widest_laid_out_line)
                }
            };
            state
                .longest_line_width
                .set(Some((key, longest_line_width)));
        }
        if state.tokens_visible() {
            longest_line_width = if let Some(width) = wrap_width {
                width
            } else {
                state
                    .token_layout_cache
                    .as_ref()
                    .map_or(px(0.), |cache| cache.unwrapped_width)
            };
        }
        last_layout.lines = Rc::new(lines);

        let (ghost_first_line, ghost_lines) = Self::layout_inline_completion(
            state,
            &last_layout.visible_range,
            text_size,
            window,
            cx,
        );
        let ghost_line_count = ghost_lines.len();
        let ghost_lines_height = ghost_line_count as f32 * line_height;

        let total_wrapped_lines = state.display_map.wrap_row_count();
        let empty_bottom_height = empty_bottom_height(
            state.is_code_editor(),
            state.scroll_beyond_last_line,
            bounds.size.height,
            line_height,
        );

        // Empty bottom and ghost lines both describe extra height past the
        // last content row, so take the max rather than summing — summing
        // left a band of empty space the cursor could never reach.
        let mut scroll_size = size(
            if longest_line_width + line_number_width + RIGHT_MARGIN > bounds.size.width {
                longest_line_width + line_number_width + RIGHT_MARGIN
            } else {
                longest_line_width
            },
            (total_wrapped_lines as f32 * line_height
                + empty_bottom_height.max(ghost_lines_height))
            .max(bounds.size.height),
        );

        // TODO: should be add some gap to right, to convenient to focus on boundary position
        if last_layout.text_align == TextAlign::Right || last_layout.text_align == TextAlign::Center
        {
            scroll_size.width = longest_line_width + line_number_width;
        }

        // `position_for_index` for example
        //
        // #### text
        //
        // Hello 世界，this is GPUI component.
        // The GPUI Component is a collection of UI components for
        // GPUI framework, including Button, Input, Checkbox, Radio,
        // Dropdown, Tab, and more...
        //
        // wrap_width: 444px, line_height: 20px
        //
        // #### lines[0]
        //
        // | index | pos              | line |
        // |-------|------------------|------|
        // | 5     | (37 px, 0.0)     | 0    |
        // | 38    | (261.7 px, 20.0) | 0    |
        // | 40    | None             | -    |
        //
        // #### lines[1]
        //
        // | index | position              | line |
        // |-------|-----------------------|------|
        // | 5     | (43.578125 px, 0.0)   | 0    |
        // | 56    | (422.21094 px, 0.0)   | 0    |
        // | 57    | (11.6328125 px, 20.0) | 1    |
        // | 114   | (429.85938 px, 20.0)  | 1    |
        // | 115   | (11.3125 px, 40.0)    | 2    |

        // Calculate the scroll offset to keep the cursor in view

        // Save the unscrolled x before layout_cursors modifies bounds.origin with scroll_offset.
        // Fold icons and their hitboxes must use this value so they stay fixed in the gutter
        // regardless of horizontal scroll position.
        let input_bounds = bounds;
        let original_x = bounds.origin.x;
        // Resolved content and viewport sizes can change during a gesture.
        // A non-scrolling input must not retain a drag that will no longer
        // receive its Ended packet through the overscroll path.
        if scroll_size.height <= input_bounds.size.height {
            self.state.update(cx, |state, _| state.overscroll.reset());
            stretch = 0.;
        }
        // Keep viewport geometry for scrollbars and hitboxes fixed; only
        // text, its carets, selections, and gutter contents are displaced.
        bounds.origin.y += px(stretch);

        let (cursor_infos, cursor_scroll_offset, current_row, resize_reveal_owned) =
            self.layout_cursors(&last_layout, &mut bounds, scroll_size, window, cx);
        // Completion/code-action menus position at the active caret.
        last_layout.cursor_bounds = cursor_infos
            .iter()
            .find(|info| info.is_active)
            .map(|info| info.bounds);

        // Stash the fresh caret geometry for caret-anchored popups. Their
        // deferred prepaint runs after this prepaint but before paint, so
        // they anchor to the current frame's caret instead of the previous
        // frame's. Only the positioning geometry is stashed here; the rest
        // of the paint-time state updates stay where they are.
        let caret_geometry = last_layout.cursor_bounds.map(|cursor_bounds| {
            let mut scroll_offset = cursor_scroll_offset;
            // Mirror update_scroll_offset's clamping with the fresh values,
            // so the stash matches what paint will publish.
            let state = self.state.read(cx);
            let safe_y_range = (-scroll_size.height + input_bounds.size.height).min(px(0.))..px(0.);
            scroll_offset.y = if state.is_single_line() {
                px(0.)
            } else {
                scroll_offset.y.clamp(safe_y_range.start, safe_y_range.end)
            };
            scroll_offset.x = clamp_horizontal_scroll_offset(
                scroll_offset.x,
                scroll_size.width,
                input_bounds.size.width,
                last_layout.text_align,
            );
            let mut geometry =
                PrepaintCaretGeometry::new(cursor_bounds, line_height, input_bounds, scroll_offset);
            geometry.resize_reveal_owned = resize_reveal_owned;
            geometry
        });
        self.state.update(cx, |state, _| {
            state.prepaint_caret_geometry = caret_geometry;
        });

        let search_match_paths = self.layout_search_matches(&last_layout, &mut bounds, cx);
        let selection_paths = self.layout_selections(&last_layout, &mut bounds, window, cx);
        let hover_highlight_path = self.layout_hover_highlight(&last_layout, &mut bounds, cx);
        let document_color_paths =
            self.layout_document_colors(&document_colors, &last_layout, &bounds, cx);
        let (range_decoration_fills, range_decoration_frames) = self.layout_range_decorations(
            &last_layout,
            &bounds,
            window,
            window.content_mask().bounds,
            cx,
        );

        let state = self.state.read(cx);
        let line_numbers = if state.mode.line_number() {
            let mut line_numbers = Vec::with_capacity(last_layout.visible_buffer_lines.len());
            let other_line_runs = vec![TextRun {
                len: line_number_len,
                font: style.font(),
                color: state.editor_style.muted_foreground,
                background_color: None,
                underline: None,
                strikethrough: None,
            }];
            let current_line_runs = vec![TextRun {
                len: line_number_len,
                font: style.font(),
                color: state.editor_style.foreground,
                background_color: None,
                underline: None,
                strikethrough: None,
            }];

            // build line numbers
            for (line, &buffer_line) in last_layout
                .lines
                .iter()
                .zip(last_layout.visible_buffer_lines.iter())
            {
                let line_no: SharedString = format!(
                    "{:>width$}",
                    displayed_line_number(buffer_line + 1),
                    width = line_number_len
                )
                .into();

                let runs = if current_row == Some(buffer_line) {
                    &current_line_runs
                } else {
                    &other_line_runs
                };

                let mut sub_lines: SmallVec<[ShapedLine; 1]> = SmallVec::new();
                sub_lines.push(
                    window
                        .text_system()
                        .shape_line(line_no, text_size, &runs, None),
                );
                for _ in 0..line.wrapped_lines.len().saturating_sub(1) {
                    sub_lines.push(ShapedLine::default());
                }
                line_numbers.push(sub_lines);
            }
            Some(line_numbers)
        } else {
            None
        };

        let hover_definition_hitbox = M::hover_definition_hitbox(state, window, cx);
        let indent_guides_path =
            self.layout_indent_guides(state, &bounds, &last_layout, &text_style, window);
        state
            .editor_scrollbar_snapshot
            .set(Some(EditorScrollbarSnapshot::new(
                input_bounds,
                &last_layout,
                scroll_size,
                cursor_scroll_offset,
                state,
            )));
        let fold_icon_layout =
            self.layout_fold_icons(original_x, &bounds, &last_layout, window, cx);
        let ghost_rows = current_row.filter(|_| !ghost_lines.is_empty()).map(|row| {
            let display_map = &self.state.read(cx).display_map;
            let rows = display_map
                .buffer_line_to_display_row_range(row)
                .unwrap_or_default();
            (rows.end.saturating_sub(1), ghost_lines_height)
        });
        let gutter_decorations = self.layout_gutter_decorations(
            original_x,
            &bounds,
            &input_bounds,
            &last_layout,
            ghost_rows,
            cx,
        );
        let line_number_offset = self
            .state
            .read(cx)
            .extras
            .gutter_decorations_width()
            .map_or(px(0.), |width| width + GUTTER_DECORATION_GAP);
        let hitbox = window.insert_hitbox(input_bounds, HitboxBehavior::Normal);
        self.request_reveal(
            input_bounds,
            &cursor_infos,
            cursor_scroll_offset,
            line_height,
            window,
            cx,
        );

        let token_elements = self.prepaint_tokens(&last_layout, bounds, token_elements, window, cx);
        PrepaintState {
            token_elements,
            hitbox,
            bounds,
            last_layout,
            scroll_size,
            line_numbers,
            cursor_infos,
            cursor_scroll_offset,
            current_row,
            selection_paths,
            search_match_paths,
            hover_highlight_path,
            hover_definition_hitbox,
            document_color_paths,
            range_decoration_fills,
            range_decoration_frames,
            gutter_decorations,
            line_number_offset,
            indent_guides_path,
            fold_icon_layout,
            ghost_first_line,
            ghost_lines,
            ghost_lines_height,
        }
    }

    fn paint(
        &mut self,
        _id: Option<&GlobalElementId>,
        _: Option<&gpui::InspectorElementId>,
        input_bounds: Bounds<Pixels>,
        _request_layout: &mut Self::RequestLayoutState,
        prepaint: &mut Self::PrepaintState,
        window: &mut Window,
        cx: &mut App,
    ) {
        let (focus_handle, show_cursor, disabled, selected_range, editor_style, editor_paddings) = {
            let state = self.state.read(cx);
            (
                state.focus_handle.clone(),
                state.show_cursor(window, cx),
                state.disabled,
                *state.active_selection(),
                state.editor_style.clone(),
                state.editor_paddings,
            )
        };
        let focused = focus_handle.is_focused(window);
        let bounds = prepaint.bounds;
        let text_align = prepaint.last_layout.text_align;

        window.handle_input(
            &focus_handle,
            ElementInputHandler::new(bounds, self.state.clone()),
            cx,
        );

        // Paint multi line text
        let line_height = window.line_height();
        let origin = bounds.origin;

        let invisible_top_padding = prepaint.last_layout.visible_top;
        let active_line_color = editor_style
            .editor_active_line
            .map(|color| if disabled { color.opacity(0.5) } else { color });
        let editor_background = if disabled {
            editor_style.background.opacity(0.5)
        } else {
            editor_style.background
        };

        // Paint active line
        let mut offset_y = px(0.);
        if let Some(line_numbers) = prepaint.line_numbers.as_ref() {
            offset_y += invisible_top_padding;

            // Each item is the normal lines.
            for (lines, &buffer_line) in line_numbers
                .iter()
                .zip(prepaint.last_layout.visible_buffer_lines.iter())
            {
                let is_active = prepaint.current_row == Some(buffer_line);
                let p = point(input_bounds.origin.x, origin.y + offset_y);
                let height = line_height * lines.len() as f32;
                // Paint the current line background
                if is_active {
                    if let Some(bg_color) = active_line_color {
                        window.paint_quad(fill(
                            Bounds::new(p, size(bounds.size.width, height)),
                            bg_color,
                        ));
                    }
                }
                offset_y += height;
            }
        }

        // Keep scrollbar offset always be positive，Start from the left position
        let scroll_offset = if text_align == TextAlign::Right {
            (prepaint.scroll_size.width - prepaint.bounds.size.width).max(px(0.))
        } else if text_align == TextAlign::Center {
            (prepaint.scroll_size.width - prepaint.bounds.size.width)
                .half()
                .max(px(0.))
        } else {
            px(0.)
        };

        // Paint glyph backgrounds
        //
        // gpui's `paint` only draws glyphs, underlines, and strikethroughs, so decoration
        // backgrounds need their own pass. It runs ahead of the indent guides, selections,
        // and text so a highlighted range sits under them instead of covering them.
        let mut offset_y = invisible_top_padding;
        for (line, &buffer_line) in prepaint
            .last_layout
            .lines
            .iter()
            .zip(prepaint.last_layout.visible_buffer_lines.iter())
        {
            let p = point(
                origin.x + prepaint.last_layout.line_number_width + scroll_offset,
                origin.y + offset_y,
            );

            line.paint_background(
                p,
                line_height,
                text_align,
                Some(prepaint.last_layout.content_width),
                window,
                cx,
            );

            offset_y += line.size(line_height).height;

            // Ghost lines shift every later line down.
            if Some(buffer_line) == prepaint.current_row {
                offset_y += prepaint.ghost_lines_height;
            }
        }

        // Paint indent guides
        if let Some(path) = prepaint.indent_guides_path.take() {
            window.paint_path(path, editor_style.border.opacity(0.85));
        }

        // Application decorations sit below the user's selection.
        for (path, color) in &prepaint.range_decoration_fills {
            window.paint_path(path.clone(), *color);
        }
        for (path, color) in &prepaint.range_decoration_frames {
            window.paint_path(path.clone(), *color);
        }

        // Paint selections
        if window.is_window_active() {
            let secondary_selection = Hsla {
                s: 0.1,
                ..editor_style.selection
            };
            for (path, is_active) in prepaint.search_match_paths.iter() {
                window.paint_path(path.clone(), secondary_selection);

                if *is_active {
                    window.paint_path(path.clone(), editor_style.selection);
                }
            }

            for path in prepaint.selection_paths.drain(..) {
                window.paint_path(path, editor_style.selection);
            }

            // Paint hover highlight
            if let Some(path) = prepaint.hover_highlight_path.take() {
                window.paint_path(path, secondary_selection);
            }
        }

        // Paint document colors
        for (path, color) in prepaint.document_color_paths.iter() {
            let color = if disabled { color.opacity(0.5) } else { *color };
            window.paint_path(path.clone(), color);
        }

        // Paint text with inline completion ghost line support
        let mut offset_y = invisible_top_padding;
        let ghost_lines = &prepaint.ghost_lines;
        let has_ghost_lines = !ghost_lines.is_empty();

        // Track the y-position of the cursor row for positioning the first line suffix
        let mut cursor_row_y = None;

        for (line, &buffer_line) in prepaint
            .last_layout
            .lines
            .iter()
            .zip(prepaint.last_layout.visible_buffer_lines.iter())
        {
            let row = buffer_line;
            let line_y = origin.y + offset_y;
            let p = point(
                origin.x + prepaint.last_layout.line_number_width + (scroll_offset),
                line_y,
            );

            // Paint the actual line
            _ = line.paint(
                p,
                line_height,
                text_align,
                Some(prepaint.last_layout.content_width),
                window,
                cx,
            );
            offset_y += line.size(line_height).height;

            if Some(row) == prepaint.current_row {
                cursor_row_y = Some(line_y);
            }

            // After the cursor row, paint ghost lines (which shifts subsequent content down)
            if has_ghost_lines && Some(row) == prepaint.current_row {
                let ghost_x = origin.x + prepaint.last_layout.line_number_width;

                for ghost_line in ghost_lines {
                    let ghost_p = point(ghost_x, origin.y + offset_y);

                    // Paint semi-transparent background for ghost line
                    let ghost_bounds = Bounds::new(
                        ghost_p,
                        size(
                            bounds.size.width - prepaint.last_layout.line_number_width,
                            line_height,
                        ),
                    );
                    window.paint_quad(fill(ghost_bounds, editor_background));

                    // Paint ghost line text
                    _ = ghost_line.paint(
                        ghost_p,
                        line_height,
                        text_align,
                        Some(prepaint.last_layout.content_width),
                        window,
                        cx,
                    );
                    offset_y += line_height;
                }
            }
        }

        for element in &mut prepaint.token_elements {
            element.paint(window, cx);
        }

        // Paint blinking cursors (shared blink state for all carets)
        if focused && show_cursor {
            for cursor_info in prepaint.cursor_infos_with_scroll() {
                window.paint_quad(fill(
                    snap_caret_to_device_pixels(cursor_info.bounds, window.scale_factor()),
                    editor_style.caret,
                ));
            }
        }

        // Paint line numbers
        let mut offset_y = px(0.);
        if let Some(line_numbers) = prepaint.line_numbers.as_ref() {
            offset_y += invisible_top_padding;

            // The gutter is a fixed overlay above horizontally scrolling text.
            // Always give it an opaque editor background when the theme does not
            // provide a dedicated gutter color, and cover the complete gutter so
            // text cannot show through its right-side spacing/fold-icon area.
            let gutter_bg = editor_style
                .editor_gutter_background
                .unwrap_or(editor_background);
            let gutter_bounds = editor_gutter_bounds(
                input_bounds,
                prepaint.last_layout.line_number_width,
                prepaint.ghost_lines_height,
                editor_paddings,
            );
            window.paint_quad(fill(gutter_bounds, gutter_bg));

            // Each item is the normal lines.
            for (lines, &buffer_line) in line_numbers
                .iter()
                .zip(prepaint.last_layout.visible_buffer_lines.iter())
            {
                let p = point(input_bounds.origin.x, origin.y + offset_y);
                let is_active = prepaint.current_row == Some(buffer_line);

                let height = line_height * lines.len() as f32;
                // paint active line number background
                if is_active {
                    if let Some(bg_color) = active_line_color {
                        window.paint_quad(fill(
                            Bounds::new(
                                point(gutter_bounds.origin.x, p.y),
                                size(gutter_bounds.size.width, height),
                            ),
                            bg_color,
                        ));
                    }
                }

                let p = point(p.x + prepaint.line_number_offset, p.y);
                for line in lines {
                    _ = line.paint(p, line_height, TextAlign::Left, None, window, cx);
                    offset_y += line_height;
                }

                // Add ghost line height after cursor row for line numbers alignment
                if !prepaint.ghost_lines.is_empty() && prepaint.current_row == Some(buffer_line) {
                    offset_y += prepaint.ghost_lines_height;
                }
            }
        }

        for mark in std::mem::take(&mut prepaint.gutter_decorations) {
            window.paint_quad(mark);
        }

        // Paint fold icons (only visible on hover or for current line)
        self.paint_fold_icons(
            &mut prepaint.fold_icon_layout,
            prepaint.current_row,
            window,
            cx,
        );

        self.state.update(cx, |state, cx| {
            let geometry_changed = state.last_bounds != Some(bounds)
                || state.input_bounds != input_bounds
                || state.scroll_size != prepaint.scroll_size
                || state.last_layout.as_ref().is_none_or(|layout| {
                    layout.cursor_bounds != prepaint.last_layout.cursor_bounds
                        || layout.line_height != prepaint.last_layout.line_height
                });
            state.last_layout = Some(prepaint.last_layout.clone());
            state.last_bounds = Some(bounds);
            state.last_cursor = Some(state.cursor());
            state.set_input_bounds(input_bounds, cx);
            state.last_selected_range = Some(selected_range);
            state.scroll_size = prepaint.scroll_size;
            state.update_scroll_offset(Some(prepaint.cursor_scroll_offset), cx);
            state.deferred_scroll_offset = None;

            // Layout consumers need changed geometry, not another notification
            // for every paint of an unchanged input.
            if geometry_changed {
                cx.notify();
            }
        });

        if let Some(hitbox) = prepaint.hover_definition_hitbox.as_ref()
            && !window.modifiers().alt
        {
            window.set_cursor_style(gpui::CursorStyle::PointingHand, &hitbox);
        }

        // Paint inline completion first line suffix (after cursor on same line)
        if focused {
            if let Some(first_line) = &prepaint.ghost_first_line {
                let active_cursor = prepaint
                    .cursor_infos_with_scroll()
                    .into_iter()
                    .find(|info| info.is_active);
                if let (Some(cursor_info), Some(cursor_row_y)) = (active_cursor, cursor_row_y) {
                    let cursor_bounds = cursor_info.bounds;
                    let first_line_x = cursor_bounds.origin.x + cursor_bounds.size.width;
                    let p = point(first_line_x, cursor_row_y);

                    // Paint background to cover any existing text
                    let bg_bounds = Bounds::new(p, size(first_line.width + px(4.), line_height));
                    window.paint_quad(fill(bg_bounds, editor_background));

                    // Paint first line completion text
                    _ = first_line.paint(p, line_height, text_align, None, window, cx);
                }
            }
        }

        self.paint_mouse_listeners(&prepaint.hitbox, window, cx);
    }
}

/// Split placeholder text into display lines and trim runs to each line.
fn placeholder_line_runs<'a>(
    display_text: &'a str,
    runs: &[TextRun],
) -> Vec<(&'a str, Vec<TextRun>)> {
    let mut result = Vec::new();
    let mut line_offset = 0;

    for line in display_text.split('\n') {
        let line_runs = runs_for_range(runs, line_offset, &(0..line.len()));
        debug_assert_eq!(
            line_runs.iter().map(|run| run.len).sum::<usize>(),
            line.len()
        );
        result.push((line, line_runs));
        // Advance in the whole-placeholder coordinate space, including the separator.
        line_offset += line.len() + 1;
    }

    result
}

/// Get the runs for the given range.
///
/// The range is the byte range of the wrapped line.
pub(super) fn runs_for_range(
    runs: &[TextRun],
    line_offset: usize,
    range: &Range<usize>,
) -> Vec<TextRun> {
    let mut result = vec![];
    let range = (line_offset + range.start)..(line_offset + range.end);
    let mut cursor = 0;

    for run in runs {
        let run_start = cursor;
        let run_end = cursor + run.len;

        if run_end <= range.start {
            cursor = run_end;
            continue;
        }

        if run_start >= range.end {
            break;
        }

        let start = range.start.max(run_start) - run_start;
        let end = range.end.min(run_end) - run_start;
        let len = end - start;

        if len > 0 {
            result.push(TextRun { len, ..run.clone() });
        }

        cursor = run_end;
    }

    result
}

/// Clip sorted `styles` to the sorted, disjoint `ranges`, splitting styles
/// that span several ranges and dropping coverage in the gaps between them.
fn clip_styles_to_ranges(
    styles: Vec<(Range<usize>, HighlightStyle)>,
    ranges: &[Range<usize>],
) -> Vec<(Range<usize>, HighlightStyle)> {
    let mut result = Vec::with_capacity(styles.len());
    let mut range_ix = 0;

    for (style_range, style) in styles {
        while range_ix < ranges.len() && ranges[range_ix].end <= style_range.start {
            range_ix += 1;
        }

        let mut ix = range_ix;
        while ix < ranges.len() && ranges[ix].start < style_range.end {
            let start = style_range.start.max(ranges[ix].start);
            let end = style_range.end.min(ranges[ix].end);
            if start < end {
                result.push((start..end, style));
            }
            ix += 1;
        }
    }

    result
}

/// Snap run boundaries to char boundaries of `text` and cap them at its
/// length. Style ranges are byte offsets that can drift off char boundaries
/// (a stale syntax tree, a range in the wrong coordinate space) and the
/// platform text system panics when a run splits a multi-byte character.
///
/// Returns `None` when the runs are already aligned (the common case).
pub(super) fn align_runs_to_char_boundaries(text: &str, runs: &[TextRun]) -> Option<Vec<TextRun>> {
    let mut end = 0;
    let aligned = runs.iter().all(|run| {
        end += run.len;
        end <= text.len() && text.is_char_boundary(end)
    });
    if aligned {
        return None;
    }

    let mut result = Vec::with_capacity(runs.len());
    let mut cursor = 0;
    let mut raw_end = 0;
    for run in runs {
        raw_end = (raw_end + run.len).min(text.len());
        let mut end = raw_end;
        while !text.is_char_boundary(end) {
            end += 1;
        }
        if end > cursor {
            result.push(TextRun {
                len: end - cursor,
                ..run.clone()
            });
            cursor = end;
        }
    }

    Some(result)
}

fn split_run_for_ime_underline(
    run: TextRun,
    run_range: Range<usize>,
    marked_range: Option<Range<usize>>,
    marked_underline: Option<UnderlineStyle>,
) -> SmallVec<[TextRun; 3]> {
    if run.len == 0 {
        return SmallVec::new();
    }

    let Some(marked) = marked_range else {
        return [run].into_iter().collect();
    };

    let intersection_start = run_range.start.max(marked.start);
    let intersection_end = run_range.end.min(marked.end);
    if intersection_start >= intersection_end {
        return [run].into_iter().collect();
    }

    [
        TextRun {
            len: intersection_start - run_range.start,
            ..run.clone()
        },
        TextRun {
            len: intersection_end - intersection_start,
            underline: marked_underline,
            ..run.clone()
        },
        TextRun {
            len: run_range.end - intersection_end,
            ..run
        },
    ]
    .into_iter()
    .filter(|run| run.len > 0)
    .collect()
}

/// Whether any of these runs paints a glyph background, used to skip the background
/// paint pass for lines without highlights.
fn has_background(runs: &[TextRun]) -> bool {
    runs.iter().any(|run| run.background_color.is_some())
}

fn split_runs_by_bg_segments(
    start_offset: usize,
    runs: &[TextRun],
    bg_segments: &[(Range<usize>, Hsla)],
) -> Vec<TextRun> {
    let mut result = vec![];

    let mut cursor = start_offset;
    for run in runs {
        let mut run_start = cursor;
        let run_end = cursor + run.len;

        for (bg_range, bg_color) in bg_segments {
            if run_end <= bg_range.start || run_start >= bg_range.end {
                continue;
            }

            // Overlap exists
            if run_start < bg_range.start {
                // Add the part before the background range
                result.push(TextRun {
                    len: bg_range.start - run_start,
                    ..run.clone()
                });
            }

            // Add the overlapping part with background color
            let overlap_start = run_start.max(bg_range.start);
            let overlap_end = run_end.min(bg_range.end);
            let text_color = if bg_color.l >= 0.5 {
                gpui::black()
            } else {
                gpui::white()
            };

            let run_len = overlap_end.saturating_sub(overlap_start);
            if run_len > 0 {
                result.push(TextRun {
                    len: run_len,
                    color: text_color,
                    ..run.clone()
                });

                cursor = bg_range.end;
                run_start = cursor;
            }
        }

        if run_end > cursor {
            // Add the part after the background range
            result.push(TextRun {
                len: run_end - cursor,
                ..run.clone()
            });
        }

        cursor = run_end;
    }

    result
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::input::{
        EditorMode, EditorState, FoldRange, GutterDecoration, GutterDecorationCollection,
        OverviewRulerDecoration, OverviewRulerDecorationCollection, RangeDecoration, Redo, Undo,
    };
    use gpui::{
        AppContext as _, Context, EntityInputHandler as _, ListAlignment, ListOffset, ListState,
        Render, TestAppContext, VisualTestContext, div, list, prelude::FluentBuilder as _,
    };

    #[test]
    fn line_number_column_stays_at_three_digits_then_grows_up_to_seven() {
        assert_eq!(line_number_len(1), 3);
        assert_eq!(line_number_len(9), 3);
        assert_eq!(line_number_len(10), 3);
        assert_eq!(line_number_len(999), 3);
        assert_eq!(line_number_len(1_000), 4);
        assert_eq!(line_number_len(999_999), 6);
        assert_eq!(line_number_len(9_999_999), 7);
        assert_eq!(line_number_len(10_000_000), 7);
    }

    #[test]
    fn displayed_line_number_stays_within_seven_digits() {
        assert_eq!(displayed_line_number(42), 42);
        assert_eq!(displayed_line_number(9_999_999), 9_999_999);
        assert_eq!(displayed_line_number(10_000_000), 9_999_999);
    }

    struct DecorationHarness(Entity<EditorState>);

    impl Render for DecorationHarness {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            div().size_full().child(self.0.clone())
        }
    }

    fn decoration_editor(
        cx: &mut TestAppContext,
        text: &str,
        wrap: bool,
    ) -> (Entity<EditorState>, gpui::WindowHandle<DecorationHarness>) {
        cx.update(crate::init);
        let mut editor = None;
        let window = cx.open_window(size(px(240.), px(140.)), |window, cx| {
            let state = cx.new(|cx| {
                EditorState::new(window, cx)
                    .soft_wrap(wrap)
                    .folding(true)
                    .default_value(text)
            });
            editor = Some(state.clone());
            DecorationHarness(state)
        });
        (editor.unwrap(), window)
    }

    /// A list as tall as the window, whose second item is an input that
    /// starts 180 px down, so its bottom is cut off by the window's edge.
    struct RevealHarness {
        input: Entity<crate::input::InputState>,
        list: ListState,
        show_input: bool,
    }

    impl Render for RevealHarness {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            let input = self.input.clone();
            let show_input = self.show_input;
            list(self.list.clone(), move |ix, _, _| {
                if ix == 0 {
                    div().h(px(180.)).into_any_element()
                } else {
                    div()
                        .when(show_input, |this| this.child(input.clone()))
                        .into_any_element()
                }
            })
            .size_full()
        }
    }

    #[gpui::test]
    fn focused_input_asks_its_scroll_container_to_reveal_it(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let list_state = ListState::new(2, ListAlignment::Top, px(0.));
        let mut input = None;
        let window = cx.open_window(size(px(240.), px(200.)), |window, cx| {
            let state = cx.new(|cx| crate::input::InputState::new(window, cx));
            input = Some(state.clone());
            RevealHarness {
                input: state,
                list: list_state.clone(),
                show_input: true,
            }
        });
        let input = input.unwrap();
        let view = window.root(cx).unwrap();
        let mut cx = VisualTestContext::from_window(window.into(), cx);
        cx.update(|window, _| window.activate_window());
        cx.run_until_parked();
        let draw = |cx: &mut VisualTestContext| {
            cx.update(|window, cx| {
                window.refresh();
                window.draw(cx).clear(cx);
            })
        };
        let revealed = |cx: &mut VisualTestContext| {
            cx.update(|window, cx| {
                let bounds = input.read(cx).input_bounds();
                bounds.top() >= px(0.) && bounds.bottom() <= window.viewport_size().height
            })
        };
        let at_top = || {
            list_state.logical_scroll_top().item_ix == 0
                && list_state.logical_scroll_top().offset_in_item == px(0.)
        };

        draw(&mut cx);
        assert!(at_top());
        assert!(!revealed(&mut cx));

        // Gaining focus reveals the input.
        cx.update(|window, cx| input.update(cx, |state, cx| state.focus(window, cx)));
        draw(&mut cx);
        draw(&mut cx);
        assert!(!at_top());
        assert!(revealed(&mut cx));

        // Scrolling away while focused is left alone.
        list_state.scroll_to(ListOffset::default());
        draw(&mut cx);
        draw(&mut cx);
        assert!(at_top());

        // A temporarily unmounted input does not prepaint while unfocused.
        // Its blur event must still reset the reveal cache before remounting.
        cx.update(|window, cx| {
            view.update(cx, |view, cx| {
                view.show_input = false;
                window.blur(cx);
                cx.notify();
            });
        });
        draw(&mut cx);
        input.read_with(&cx, |state, _| assert!(state.revealed_viewport.is_none()));
        cx.update(|window, cx| {
            view.update(cx, |view, cx| {
                view.show_input = true;
                input.update(cx, |state, cx| state.focus(window, cx));
                cx.notify();
            });
        });
        draw(&mut cx);
        draw(&mut cx);
        assert!(!at_top());
        assert!(revealed(&mut cx));

        list_state.scroll_to(ListOffset::default());
        draw(&mut cx);
        draw(&mut cx);
        assert!(at_top());

        // A smaller visible area (an on-screen keyboard) reveals it again.
        cx.simulate_resize(size(px(240.), px(195.)));
        draw(&mut cx);
        draw(&mut cx);
        assert!(!at_top());
        assert!(revealed(&mut cx));
    }

    struct TextareaHarness(Entity<crate::input::TextareaState>);

    #[gpui::test]
    fn scroll_bounce_keeps_the_scrollbar_viewport_fixed(cx: &mut TestAppContext) {
        let text = (0..60)
            .map(|line| format!("line {line}"))
            .collect::<Vec<_>>()
            .join("\n");
        let (editor, window) = decoration_editor(cx, &text, false);
        let mut cx = VisualTestContext::from_window(window.into(), cx);
        cx.update(|window, cx| {
            window.draw(cx).clear(cx);
            let viewport = editor
                .read(cx)
                .editor_scrollbar_snapshot
                .get()
                .unwrap()
                .layout
                .bounds;
            let text_origin = editor.read(cx).last_bounds.unwrap().origin;
            editor.update(cx, |state, cx| {
                state.set_scroll_bounce(true, cx);
                state.on_scroll_wheel(
                    &gpui::ScrollEvent {
                        delta: gpui::ScrollDelta::Pixels(point(px(0.), px(60.))),
                        touch_phase: gpui::TouchPhase::Started,
                        ..Default::default()
                    },
                    window,
                    cx,
                );
            });
            window.draw(cx).clear(cx);
            let state = editor.read(cx);
            let stretch = state.overscroll.offset();
            assert!(stretch > 0.);
            assert_eq!(
                state.editor_scrollbar_snapshot.get().unwrap().layout.bounds,
                viewport
            );
            assert_eq!(
                state.last_bounds.unwrap().origin.y,
                text_origin.y + px(stretch)
            );
        });
    }

    /// A scrollbar supplied through `set_scrollbar_renderer` gets the editor's own
    /// scroll range through the standard ScrollbarHandle contract, so a
    /// scrollbar can drag to the same end as wheel scrolling.
    #[gpui::test]
    fn scrollbar_renderer_receives_the_editors_scroll_range(cx: &mut TestAppContext) {
        use crate::ScrollbarHandle as _;

        let text = (0..60)
            .map(|line| format!("line {line}"))
            .collect::<Vec<_>>()
            .join("\n");
        let (editor, window) = decoration_editor(cx, &text, true);
        let presented = std::rc::Rc::new(std::cell::RefCell::new(None));
        let mut cx = VisualTestContext::from_window(window.into(), cx);
        cx.update(|window, cx| {
            editor.update(cx, |state, cx| {
                state.set_scroll_bounce(false, cx);
                state.set_editor_paddings(Edges {
                    top: px(10.),
                    bottom: px(10.),
                    ..Default::default()
                });
                let presented = presented.clone();
                state.set_scrollbar_renderer(Some(std::rc::Rc::new(move |context, _, _| {
                    *presented.borrow_mut() = Some(context.clone());
                    Scrollbar::vertical(&context)
                        .mode(crate::ScrollbarMode::Always)
                        .into_any_element()
                })));
            });
            window.draw(cx).clear(cx);
            editor.update(cx, |state, cx| {
                state.on_scroll_wheel(
                    &gpui::ScrollEvent {
                        delta: gpui::ScrollDelta::Pixels(point(px(0.), px(-10_000.))),
                        touch_phase: gpui::TouchPhase::Moved,
                        ..Default::default()
                    },
                    window,
                    cx,
                );
            });
            window.draw(cx).clear(cx);
        });

        let context = presented.borrow().clone().unwrap();
        let track = context.viewport_bounds();
        let wheel_end = context.offset();
        assert!(wheel_end.y < px(0.));
        assert_eq!(
            track.size.height - context.scroll_viewport_size().height,
            px(20.)
        );
        cx.update(|window, cx| {
            context.set_offset(Point::default());
            window.refresh();
            window.draw(cx).clear(cx);
        });

        let grab = point(track.right() - px(5.), track.top() + px(10.));
        let end = point(grab.x, track.bottom() - px(1.));
        cx.simulate_mouse_down(grab, gpui::MouseButton::Left, gpui::Modifiers::default());
        cx.update(|window, cx| window.draw(cx).clear(cx));
        cx.simulate_mouse_move(
            end,
            Some(gpui::MouseButton::Left),
            gpui::Modifiers::default(),
        );
        cx.update(|window, cx| window.draw(cx).clear(cx));
        cx.simulate_mouse_up(end, gpui::MouseButton::Left, gpui::Modifiers::default());

        assert_eq!(
            editor.read_with(&cx, |state, _| state.scroll_offset()),
            wheel_end
        );
        assert_eq!(
            context.content_size().height - track.size.height,
            -wheel_end.y
        );
    }

    impl Render for TextareaHarness {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            div().size_full().child(self.0.clone())
        }
    }

    /// A textarea 100 px down a taller bouncing scroll area.
    struct NestedTextarea(Entity<crate::input::TextareaState>, gpui::ScrollHandle);
    use gpui::StatefulInteractiveElement as _;

    impl Render for NestedTextarea {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            crate::ScrollBounce::new(
                "outer",
                &self.1,
                div()
                    .id("outer-viewport")
                    .w(px(240.))
                    .h(px(300.))
                    .overflow_y_scroll()
                    .track_scroll(&self.1)
                    .child(div().h(px(100.)))
                    .child(div().h(px(120.)).child(self.0.clone()))
                    .child(div().h(px(600.))),
            )
            .enabled(true)
        }
    }

    #[gpui::test]
    fn a_textarea_keeps_its_scroll_from_the_area_around_it(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let text = (1..=40)
            .map(|line| format!("line {line}"))
            .collect::<Vec<_>>()
            .join("\n");
        let outer = gpui::ScrollHandle::new();
        let mut textarea = None;
        let window = cx.open_window(size(px(240.), px(400.)), |window, cx| {
            let state =
                cx.new(|cx| crate::input::TextareaState::new(window, cx).default_value(text));
            textarea = Some(state.clone());
            NestedTextarea(state, outer.clone())
        });
        let textarea = textarea.unwrap();
        let mut cx = VisualTestContext::from_window(window.into(), cx);
        cx.update(|window, cx| window.draw(cx).clear(cx));
        let swipe = |cx: &mut VisualTestContext, y: f32| {
            cx.simulate_event(gpui::ScrollEvent {
                position: point(px(100.), px(y)),
                delta: gpui::ScrollDelta::Pixels(point(px(0.), px(-40.))),
                touch_phase: gpui::TouchPhase::Moved,
                ..Default::default()
            });
            cx.update(|window, cx| window.draw(cx).clear(cx));
        };
        swipe(&mut cx, 160.);
        let scrolled = cx.update(|_, cx| textarea.read(cx).scroll_handle.offset().y);
        assert!(scrolled < px(0.), "the textarea scrolls");
        assert_eq!(outer.offset().y, px(0.), "the area around it does not");
        swipe(&mut cx, 40.);
        assert_eq!(outer.offset().y, px(-40.), "outside the textarea it does");
    }

    #[gpui::test]
    fn set_scroll_offset_past_the_end_is_clamped(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let text = (1..=40)
            .map(|line| format!("line {line}"))
            .collect::<Vec<_>>()
            .join("\n");
        let mut textarea = None;
        let window = cx.open_window(size(px(240.), px(400.)), |window, cx| {
            let state =
                cx.new(|cx| crate::input::TextareaState::new(window, cx).default_value(text));
            textarea = Some(state.clone());
            TextareaHarness(state)
        });
        let textarea = textarea.unwrap();
        let mut cx = VisualTestContext::from_window(window.into(), cx);
        cx.update(|window, cx| {
            window.draw(cx).clear(cx);
            textarea.update(cx, |state, cx| {
                state.set_scroll_offset(point(px(0.), px(-10_000.)), cx)
            });
            window.draw(cx).clear(cx);

            let state = textarea.read(cx);
            let painted = state
                .editor_scrollbar_snapshot
                .get()
                .unwrap()
                .cursor_scroll_offset;
            let furthest = (state.input_bounds.size.height - state.scroll_size.height).min(px(0.));
            assert!(furthest < px(0.));
            assert_eq!(painted.y, furthest);

            let layout = state.last_layout.as_ref().unwrap();
            let rows = viewport_visible_lines(state.input_bounds.size.height, layout.line_height);
            assert!(layout.visible_range.len() >= rows);
        });
    }

    #[gpui::test]
    fn set_scroll_offset_past_the_end_is_clamped_in_a_code_editor(cx: &mut TestAppContext) {
        let text = (1..=40)
            .map(|line| format!("line {line}"))
            .collect::<Vec<_>>()
            .join("\n");
        let (editor, window) = decoration_editor(cx, &text, false);
        let mut cx = VisualTestContext::from_window(window.into(), cx);
        cx.update(|window, cx| {
            window.draw(cx).clear(cx);
            editor.update(cx, |state, cx| {
                state.set_scroll_offset(point(px(0.), px(-10_000.)), cx)
            });
            window.draw(cx).clear(cx);

            let state = editor.read(cx);
            let painted = state
                .editor_scrollbar_snapshot
                .get()
                .unwrap()
                .cursor_scroll_offset;
            // The furthest offset includes the room below the last line.
            let furthest = state.input_bounds.size.height - state.scroll_size.height;
            assert!(-furthest > state.input_bounds.size.height);
            assert_eq!(painted.y, furthest);
        });
    }

    #[gpui::test]
    fn selection_paths_follow_the_input_and_its_menu_focus(cx: &mut TestAppContext) {
        let (editor, window) = decoration_editor(cx, "alpha beta", false);
        let mut cx = VisualTestContext::from_window(window.into(), cx);
        cx.update(|window, cx| {
            let menu_focus = cx.focus_handle();
            let other_focus = cx.focus_handle();
            editor.update(cx, |state, cx| {
                state.set_selected_range(0..5, cx);
                state.focus(window, cx);
            });

            let selection_paths = |window: &mut Window, cx: &mut App| {
                window.draw(cx).clear(cx);
                let state = editor.read(cx);
                let layout = state.last_layout.clone().unwrap();
                let mut bounds = state.input_bounds;
                TextElement::new(editor.clone()).layout_selections(&layout, &mut bounds, window, cx)
            };
            let focused_paths = selection_paths(window, cx).len();
            assert!(focused_paths > 0);

            editor.update(cx, |state, cx| {
                state.set_selection_focus(Some(menu_focus.clone()), cx);
            });
            menu_focus.focus(window, cx);
            assert!(!editor.read(cx).focus_handle.is_focused(window));
            assert_eq!(selection_paths(window, cx).len(), focused_paths);
            // The opening frame can still use the input's old focus. Check
            // another frame with the menu already focused as well.
            assert_eq!(selection_paths(window, cx).len(), focused_paths);

            other_focus.focus(window, cx);
            assert!(selection_paths(window, cx).is_empty());
            assert_eq!(editor.read(cx).selected_range(), 0..5);

            menu_focus.focus(window, cx);
            editor.update(cx, |state, cx| state.set_selection_focus(None, cx));
            assert!(selection_paths(window, cx).is_empty());
            editor.update(cx, |state, cx| state.focus(window, cx));
            assert_eq!(selection_paths(window, cx).len(), focused_paths);

            // Retaining the input must not keep a removed menu alive.
            let weak_menu = menu_focus.downgrade();
            editor.update(cx, |state, cx| {
                state.set_selection_focus(Some(menu_focus.clone()), cx);
            });
            menu_focus.focus(window, cx);
            drop(menu_focus);
            assert!(weak_menu.upgrade().is_none());
            assert!(selection_paths(window, cx).is_empty());
        });
    }

    #[gpui::test]
    fn horizontal_scroll_is_clamped_before_text_and_caret_layout(cx: &mut TestAppContext) {
        let (editor, window) = decoration_editor(cx, "short text", false);
        let mut cx = VisualTestContext::from_window(window.into(), cx);
        cx.update(|window, cx| {
            window.draw(cx).clear(cx);
            let state = editor.read(cx);
            let layout = state.last_layout.clone().unwrap();
            let input_bounds = state.input_bounds;
            let scroll_size = input_bounds.size;
            let element = TextElement::new(editor.clone());
            let mut bounds = input_bounds;
            let (baseline, _, _, _) =
                element.layout_cursors(&layout, &mut bounds, scroll_size, window, cx);

            // Both a stale offset after deletion and a deferred scroll target must
            // be limited before either text or carets are positioned this frame.
            for deferred in [None, Some(point(px(-80.), px(0.)))] {
                editor.update(cx, |state, _| {
                    state.scroll_handle.set_offset(point(px(-40.), px(0.)));
                    state.deferred_scroll_offset = deferred;
                });
                let mut bounds = input_bounds;
                let (carets, offset, _, _) =
                    element.layout_cursors(&layout, &mut bounds, scroll_size, window, cx);
                assert_eq!(offset.x, px(0.));
                assert_eq!(bounds.origin.x, input_bounds.origin.x);
                assert_eq!(carets.len(), baseline.len());
                for (caret, original) in carets.iter().zip(&baseline) {
                    assert_eq!(caret.bounds.origin.x, original.bounds.origin.x);
                }
                editor.update(cx, |state, cx| {
                    state.scroll_size = scroll_size;
                    state.update_scroll_offset(Some(offset), cx);
                    assert_eq!(state.scroll_handle.offset().x, offset.x);
                });
            }
        });
    }

    /// Scroll to the far right and assert the caret at `end` lands inside the
    /// viewport, so the line ending there can be revealed completely.
    fn assert_horizontal_scroll_reaches_line_end(
        editor: &Entity<EditorState>,
        end: usize,
        window: &mut Window,
        cx: &mut App,
    ) {
        let (layout, input_bounds, scroll_size) = {
            let state = editor.read(cx);
            (
                state.last_layout.clone().expect("layout"),
                state.input_bounds,
                state.scroll_size,
            )
        };

        editor.update(cx, |state, cx| {
            state.set_selected_range(end..end, cx);
            state.deferred_scroll_offset = Some(point(px(-1_000_000.), px(0.)));
        });

        let element = TextElement::new(editor.clone());
        let mut bounds = input_bounds;
        let (carets, offset, _, _) =
            element.layout_cursors(&layout, &mut bounds, scroll_size, window, cx);
        let caret = carets.first().expect("a caret").bounds;
        assert!(
            caret.left() <= input_bounds.right() + px(1.),
            "scrolling to the end ({offset:?}) leaves the caret at {caret:?} past {:?}",
            input_bounds.right()
        );
    }

    #[gpui::test]
    fn horizontal_scroll_extent_excludes_placeholder(cx: &mut TestAppContext) {
        let (editor, window) = decoration_editor(cx, "", false);
        let mut cx = VisualTestContext::from_window(window.into(), cx);
        cx.update(|window, cx| {
            window.draw(cx).clear(cx);
            let empty_width = editor.read(cx).scroll_size.width;

            for placeholder in ["W".repeat(300), "Short hint".to_string()] {
                editor.update(cx, |state, cx| {
                    state.set_placeholder(placeholder, window, cx);
                });
                window.draw(cx).clear(cx);
                assert_eq!(
                    editor.read(cx).scroll_size.width,
                    empty_width,
                    "placeholder must not create horizontal scrollable content"
                );
            }
        });
    }

    #[gpui::test]
    fn horizontal_scroll_extent_covers_the_widest_laid_out_line(cx: &mut TestAppContext) {
        // The first line is longest by bytes, but the second renders wider.
        let narrow = format!("e{}", "\u{301}".repeat(200));
        let wide = "W".repeat(300);
        let text = format!("{narrow}\n{wide}");
        let (editor, window) = decoration_editor(cx, &text, false);
        let mut cx = VisualTestContext::from_window(window.into(), cx);
        cx.update(|window, cx| {
            window.draw(cx).clear(cx);
            assert_horizontal_scroll_reaches_line_end(&editor, text.len(), window, cx);

            // Editing the wider line invalidates the cached measurement.
            let wider = "W".repeat(400);
            let edited = format!("{narrow}\n{wider}");
            editor.update(cx, |state, cx| state.set_value(edited.as_str(), window, cx));
            window.draw(cx).clear(cx);
            assert_horizontal_scroll_reaches_line_end(&editor, edited.len(), window, cx);

            // A larger font must widen the extent instead of reusing the old
            // measurement.
            let before = editor.read(cx).scroll_size.width;
            window.set_rem_size(px(24.));
            window.draw(cx).clear(cx);
            let after = editor.read(cx).scroll_size.width;
            assert!(
                after > before,
                "growing the font should widen the scroll extent: {after} > {before}"
            );
            assert_horizontal_scroll_reaches_line_end(&editor, edited.len(), window, cx);
        });
    }

    #[gpui::test]
    fn aligned_horizontal_scroll_clamps_deferred_targets(cx: &mut TestAppContext) {
        let (editor, window) = decoration_editor(cx, &"wide text ".repeat(80), false);
        let mut cx = VisualTestContext::from_window(window.into(), cx);
        cx.update(|window, cx| {
            window.draw(cx).clear(cx);
            let mut layout = editor.read(cx).last_layout.clone().unwrap();
            let input_bounds = editor.read(cx).input_bounds;
            let element = TextElement::new(editor.clone());

            for alignment in [TextAlign::Left, TextAlign::Right, TextAlign::Center] {
                layout.text_align = alignment;
                for overflow in [px(0.), px(120.)] {
                    let scroll_size =
                        size(input_bounds.size.width + overflow, input_bounds.size.height);
                    let minimum = if alignment == TextAlign::Left {
                        -overflow
                    } else {
                        -overflow - CURSOR_WIDTH
                    };
                    editor.update(cx, |state, _| {
                        state.text_align = alignment;
                        state.last_selected_range = Some(*state.active_selection());
                        state.deferred_scroll_offset = Some(point(minimum, px(0.)));
                    });
                    let mut bounds = input_bounds;
                    let (expected, _, _, _) =
                        element.layout_cursors(&layout, &mut bounds, scroll_size, window, cx);

                    for target in [minimum - px(100.), px(100.)] {
                        editor.update(cx, |state, _| {
                            state.deferred_scroll_offset = Some(point(target, px(0.)));
                        });
                        let mut bounds = input_bounds;
                        let (carets, offset, _, _) =
                            element.layout_cursors(&layout, &mut bounds, scroll_size, window, cx);
                        let expected_offset = if target < minimum { minimum } else { px(0.) };
                        assert_eq!(offset.x, expected_offset);
                        assert_eq!(bounds.left(), input_bounds.left() + expected_offset);
                        if target < minimum {
                            assert_eq!(carets[0].bounds, expected[0].bounds);
                        }
                        if alignment == TextAlign::Right {
                            assert!(carets[0].bounds.right() <= input_bounds.right());
                        }
                        editor.update(cx, |state, cx| {
                            state.scroll_size = scroll_size;
                            state.update_scroll_offset(Some(offset), cx);
                            assert_eq!(state.scroll_handle.offset().x, expected_offset);
                        });
                    }
                }
            }
        });
    }

    #[gpui::test]
    fn deferred_horizontal_scroll_moves_every_caret(cx: &mut TestAppContext) {
        use super::super::{cursor::CursorSelection, selection::CursorId};

        let (editor, window) = decoration_editor(cx, &"wide text ".repeat(80), false);
        let mut cx = VisualTestContext::from_window(window.into(), cx);
        cx.update(|window, cx| {
            window.draw(cx).clear(cx);
            let layout = editor.read(cx).last_layout.clone().unwrap();
            let input_bounds = editor.read(cx).input_bounds;
            let scroll_size = size(input_bounds.size.width + px(120.), input_bounds.size.height);
            let element = TextElement::new(editor.clone());

            for offsets in [[0, 2, 4], [0, 4, 2], [4, 0, 2]] {
                editor.update(cx, |state, _| {
                    state.selections.replace_all(
                        offsets
                            .into_iter()
                            .enumerate()
                            .map(|(id, offset)| {
                                CursorSelection::new(CursorId::new(id), offset, offset)
                            })
                            .collect(),
                    );
                    state.last_selected_range = Some(*state.active_selection());
                    state.scroll_handle.set_offset(point(px(0.), px(0.)));
                    state.deferred_scroll_offset = None;
                });
                let mut bounds = input_bounds;
                let (baseline, _, _, _) =
                    element.layout_cursors(&layout, &mut bounds, scroll_size, window, cx);
                editor.update(cx, |state, _| {
                    state.deferred_scroll_offset = Some(point(px(-60.), px(0.)));
                });
                let mut bounds = input_bounds;
                let (carets, offset, _, _) =
                    element.layout_cursors(&layout, &mut bounds, scroll_size, window, cx);
                assert_eq!(offset.x, px(-60.));
                assert_eq!(carets.len(), 3);
                for (caret, original) in carets.iter().zip(baseline) {
                    assert_eq!(caret.bounds.left(), original.bounds.left() - px(60.));
                }
            }
        });
    }

    #[gpui::test]
    fn editor_line_number_gutter_resizes_with_document_lines(cx: &mut TestAppContext) {
        let (editor, window) = decoration_editor(cx, &"x\n".repeat(8), false);
        let mut cx = VisualTestContext::from_window(window.into(), cx);
        cx.update(|window, cx| {
            window.draw(cx).clear(cx);
            let narrow = editor
                .read(cx)
                .last_layout
                .as_ref()
                .unwrap()
                .line_number_width;

            let longer_text = "x\n".repeat(99);
            editor.update(cx, |state, cx| {
                state.set_value(longer_text.as_str(), window, cx)
            });
            window.draw(cx).clear(cx);
            let middle = editor
                .read(cx)
                .last_layout
                .as_ref()
                .unwrap()
                .line_number_width;
            assert_eq!(middle, narrow, "one to three digits must share a width");

            let longest_text = "x\n".repeat(999);
            editor.update(cx, |state, cx| {
                state.set_value(longest_text.as_str(), window, cx)
            });
            window.draw(cx).clear(cx);
            let wide = editor
                .read(cx)
                .last_layout
                .as_ref()
                .unwrap()
                .line_number_width;

            assert!(
                wide > narrow,
                "more line-number digits must widen the gutter"
            );
        });
    }

    #[gpui::test]
    fn geometric_decorations_clip_scrolled_viewport_and_cull_offscreen_ranges(
        cx: &mut TestAppContext,
    ) {
        let text = "abcdefghij\n".repeat(100);
        let (editor, window) = decoration_editor(cx, &text, false);
        let mut cx = VisualTestContext::from_window(window.into(), cx);
        cx.update(|window, cx| {
            editor.update(cx, |state, cx| {
                state.create_range_decorations_collection(
                    vec![
                        RangeDecoration::new(0..text.len()).with_style(RangeDecorationStyle::Fill),
                        RangeDecoration::new(0..text.len()),
                        RangeDecoration::new(0..3),
                        RangeDecoration::new(text.len() - 3..text.len()),
                    ],
                    cx,
                );
            });
            window.draw(cx).clear(cx);
            editor.update(cx, |state, cx| {
                let height = state.last_layout.as_ref().unwrap().line_height;
                state.set_scroll_offset(point(px(0.), -height * 40.), cx);
            });
            // Deferred scroll is committed by prepaint and reflected next frame.
            window.draw(cx).clear(cx);
            window.draw(cx).clear(cx);
            let state = editor.read(cx);
            let layout = state.last_layout.as_ref().unwrap();
            assert!(layout.visible_range_offset.start > 0);
            assert!(layout.visible_range_offset.end < text.len());
            let all =
                TextElement::<EditorMode>::layout_range_corners(&(0..text.len()), layout).unwrap();
            let clipped = TextElement::<EditorMode>::layout_range_corners(
                &layout.visible_range_offset,
                layout,
            )
            .unwrap();
            assert_eq!(all, clipped);
            assert!(!all.is_empty());
            assert!(TextElement::<EditorMode>::layout_range_corners(&(0..3), layout).is_none());
            // Also execute the production path building seam, not just the corner helper.
            let (fills, frames) = TextElement::new(editor.clone()).layout_range_decorations(
                layout,
                &state.input_bounds,
                window,
                state.input_bounds,
                cx,
            );
            assert_eq!(fills.len(), 1);
            assert_eq!(frames.len(), 1);
        });
    }

    #[gpui::test]
    fn geometric_decorations_use_shaped_wrap_boundaries_and_newline_cells(cx: &mut TestAppContext) {
        let text = "    héllo world héllo world héllo world héllo world\n\nlast";
        let (editor, window) = decoration_editor(cx, text, true);
        let mut cx = VisualTestContext::from_window(window.into(), cx);
        cx.update(|window, cx| {
            window.draw(cx).clear(cx);
            let state = editor.read(cx);
            let layout = state.last_layout.as_ref().unwrap();
            let first = &layout.lines[0];
            assert!(first.wrapped_lines.len() > 1);
            assert!(first.wrap_indent > px(0.));
            let boundary = first.wrapped_lines[0].len;
            let first_row =
                TextElement::<EditorMode>::layout_range_corners(&(0..boundary), layout).unwrap();
            assert_eq!(
                first_row.len(),
                1,
                "a wrap end must not open the next visual row"
            );
            assert_eq!(first_row[0].top_right.x, first.wrapped_lines[0].width);
            let rest =
                TextElement::<EditorMode>::layout_range_corners(&(boundary..first.len()), layout)
                    .unwrap();
            assert_eq!(rest.len(), first.wrapped_lines.len() - 1);
            assert_eq!(rest[0].top_left.y, layout.visible_top + layout.line_height);
            for (index, corners) in rest.iter().enumerate() {
                assert_eq!(
                    corners.top_right.x,
                    first.wrap_indent + first.wrapped_lines[index + 1].width
                );
                assert_eq!(
                    corners.bottom_left.y - corners.top_left.y,
                    layout.line_height
                );
            }
            let blank_offset = text.find("\n\n").unwrap() + 1;
            let blank = TextElement::<EditorMode>::layout_range_corners(
                &(blank_offset..blank_offset + 1),
                layout,
            )
            .unwrap();
            assert_eq!(blank.len(), 1);
            assert_eq!(
                blank[0].top_right.x - blank[0].top_left.x,
                layout.space_width
            );
            // A later-line decoration cannot paint the first row via saturating_sub.
            let last_offset = text.rfind("last").unwrap();
            let last =
                TextElement::<EditorMode>::layout_range_corners(&(last_offset..text.len()), layout)
                    .unwrap();
            assert_eq!(last.len(), 1);
            assert!(last[0].top_left.y > rest.last().unwrap().top_left.y);
        });
    }

    #[gpui::test]
    fn geometric_decorations_include_crlf_boundaries(cx: &mut TestAppContext) {
        let text = "one\r\ntwo\r\nthree";
        let (editor, window) = decoration_editor(cx, text, false);
        let mut cx = VisualTestContext::from_window(window.into(), cx);
        cx.update(|window, cx| {
            editor.update(cx, |state, cx| {
                state.create_range_decorations_collection(
                    vec![
                        RangeDecoration::new(0..8),
                        RangeDecoration::new(3..5),
                        RangeDecoration::new(4..5),
                        RangeDecoration::new(5..8),
                        RangeDecoration::new(9..10),
                    ],
                    cx,
                );
            });
            window.draw(cx).clear(cx);
            let state = editor.read(cx);
            let layout = state.last_layout.as_ref().unwrap();
            // Shaping retains '\r'; only '\n' needs an additional newline cell.
            assert_eq!(layout.lines[0].len(), "one\r".len());
            assert_eq!(layout.visible_line_byte_offsets, vec![0, 5, 10]);
            let spanning =
                TextElement::<EditorMode>::layout_range_corners(&(0..8), layout).unwrap();
            assert_eq!(spanning.len(), 2);
            for range in [3..5, 4..5, 9..10] {
                let corners =
                    TextElement::<EditorMode>::layout_range_corners(&range, layout).unwrap();
                assert_eq!(corners.len(), 1);
                assert!(corners[0].top_right.x > corners[0].top_left.x);
            }
            let (fills, frames) = TextElement::new(editor.clone()).layout_range_decorations(
                layout,
                &state.input_bounds,
                window,
                state.input_bounds,
                cx,
            );
            assert!(fills.is_empty());
            assert_eq!(frames.len(), 5);
        });
    }

    #[gpui::test]
    fn gutter_decorations_reserve_a_strip_and_mark_lines_and_boundaries(cx: &mut TestAppContext) {
        let text = "one\ntwo\nthree\nfour";
        let (editor, window) = decoration_editor(cx, text, false);
        let mut cx = VisualTestContext::from_window(window.into(), cx);
        cx.update(|window, cx| {
            let gutter_width = |cx: &App| {
                editor
                    .read(cx)
                    .last_layout
                    .as_ref()
                    .unwrap()
                    .line_number_width
            };
            window.draw(cx).clear(cx);
            let without = gutter_width(cx);
            let collection = editor.update(cx, |state, cx| {
                state.create_gutter_decorations_collection(Vec::new(), cx)
            });
            window.draw(cx).clear(cx);
            assert_eq!(
                gutter_width(cx),
                without + px(3.) + GUTTER_DECORATION_GAP,
                "an empty collection still reserves the strip"
            );

            let two = text.find("two").unwrap();
            let four = text.find("four").unwrap();
            collection.set(
                vec![
                    GutterDecoration::new(two..four).with_color(gpui::red()),
                    GutterDecoration::new(four..four),
                    GutterDecoration::new(text.len()..text.len()),
                ],
                cx,
            );
            window.draw(cx).clear(cx);
            {
                let state = editor.read(cx);
                let rows: Vec<_> = state
                    .extras
                    .gutter_decorations(0..usize::MAX)
                    .into_iter()
                    .map(|decoration| {
                        decoration_rows(&state.text, &state.display_map, decoration.range())
                    })
                    .collect();
                // A range ending at a line's start leaves that line alone, and the
                // end of a document without a final newline is below its last line.
                assert_eq!(
                    rows,
                    vec![
                        DecorationRows::Lines {
                            rows: 1..3,
                            folded_start: false
                        },
                        DecorationRows::Boundary(3),
                        DecorationRows::Boundary(4),
                    ]
                );
                let layout = state.last_layout.as_ref().unwrap();
                let line_height = layout.line_height;
                let bounds = state.input_bounds;
                let marks = TextElement::new(editor.clone()).layout_gutter_decorations(
                    bounds.origin.x,
                    &bounds,
                    &bounds,
                    layout,
                    None,
                    cx,
                );
                assert_eq!(
                    marks[0].bounds,
                    Bounds::new(
                        point(bounds.origin.x, bounds.origin.y + line_height),
                        size(px(3.), line_height * 2.)
                    )
                );
                assert_eq!(marks[0].background, gpui::red().into());
                assert_eq!(
                    marks[1].bounds.center().y,
                    bounds.origin.y + line_height * 3.
                );
                assert_eq!(
                    marks[2].bounds.center().y,
                    bounds.origin.y + line_height * 4.
                );
            }

            collection.dispose(cx);
            window.draw(cx).clear(cx);
            assert_eq!(gutter_width(cx), without, "no collection, no strip");
        });
    }

    #[gpui::test]
    fn gutter_decorations_starting_in_a_fold_mark_its_row_and_the_rest(cx: &mut TestAppContext) {
        let text = "top\nhidden one\nhidden two\nend\nlast";
        let (editor, window) = decoration_editor(cx, text, false);
        let mut cx = VisualTestContext::from_window(window.into(), cx);
        cx.update(|window, cx| {
            let hidden = 4..text.find("end").unwrap();
            let into_end = 4..text.find("last").unwrap();
            let boundary = text.find("hidden two").unwrap();
            editor.update(cx, |state, cx| {
                state.apply_highlighter_fold_candidates(vec![FoldRange::new(0, 3)], cx);
                state.display_map.set_folded(0, true);
                state.create_gutter_decorations_collection(
                    vec![
                        GutterDecoration::new(hidden)
                            .with_color(gpui::red())
                            .with_folded_color(gpui::blue()),
                        GutterDecoration::new(into_end)
                            .with_color(gpui::red())
                            .with_folded_color(gpui::blue()),
                        GutterDecoration::new(boundary..boundary),
                        GutterDecoration::new(0..text.len()),
                    ],
                    cx,
                );
            });
            window.draw(cx).clear(cx);
            let state = editor.read(cx);
            let rows: Vec<_> = state
                .extras
                .gutter_decorations(0..usize::MAX)
                .into_iter()
                .map(|decoration| {
                    decoration_rows(&state.text, &state.display_map, decoration.range())
                })
                .collect();
            // Rows 0, 1 and 2 show "top" (the fold), "end" and "last".
            let lines =
                |rows: Range<usize>, folded_start| DecorationRows::Lines { rows, folded_start };
            assert_eq!(
                rows,
                vec![
                    lines(0..1, true),
                    lines(0..2, true),
                    lines(0..1, true),
                    lines(0..3, false),
                ]
            );
            let layout = state.last_layout.as_ref().unwrap();
            let line_height = layout.line_height;
            let bounds = state.input_bounds;
            let marks = TextElement::new(editor.clone()).layout_gutter_decorations(
                bounds.origin.x,
                &bounds,
                &bounds,
                layout,
                None,
                cx,
            );
            let colors: Vec<_> = marks.iter().map(|mark| mark.background).collect();
            assert_eq!(
                colors[..3],
                [gpui::blue().into(), gpui::blue().into(), gpui::red().into()],
                "the fold's row takes the folded color and the rest of the range its own"
            );
            assert_eq!(marks[0].bounds.size.height, line_height);
            assert_eq!(marks[2].bounds.top(), bounds.origin.y + line_height);
            assert_eq!(marks[2].bounds.size.height, line_height);
        });
    }

    #[gpui::test]
    fn gutter_decorations_only_lay_out_the_visible_rows(cx: &mut TestAppContext) {
        let text = "x\n".repeat(100);
        let (editor, window) = decoration_editor(cx, &text, false);
        let mut cx = VisualTestContext::from_window(window.into(), cx);
        cx.update(|window, cx| {
            let line = |n: usize| n * 2;
            editor.update(cx, |state, cx| {
                let mut decorations: Vec<_> = (0..100)
                    .map(|n| GutterDecoration::new(line(n)..line(n + 1)))
                    .collect();
                decorations.push(GutterDecoration::new(line(40)..line(40)));
                state.create_gutter_decorations_collection(decorations, cx);
            });
            window.draw(cx).clear(cx);
            editor.update(cx, |state, cx| {
                let height = state.last_layout.as_ref().unwrap().line_height;
                state.set_scroll_offset(point(px(0.), -height * 40.), cx);
            });
            window.draw(cx).clear(cx);
            window.draw(cx).clear(cx);
            let state = editor.read(cx);
            let layout = state.last_layout.as_ref().unwrap();
            assert_eq!(layout.visible_range.start, 40);
            let span = visible_buffer_span(&state.text, &state.display_map, &layout.visible_range);
            let found = state.extras.gutter_decorations(span.start..span.end + 1);
            assert!(found.len() < 20, "queried {} of 101 marks", found.len());
            assert!(
                found
                    .iter()
                    .any(|decoration| decoration.range() == &(line(40)..line(40))),
                "a boundary at the first visible line's start is found"
            );
            assert!(
                found
                    .iter()
                    .all(|decoration| decoration.range().start >= line(39))
            );

            // Prepaint hands over the text bounds moved by the scroll offset.
            let mut scrolled = state.input_bounds;
            scrolled.origin.y -= layout.line_height * 40.;
            let marks = TextElement::new(editor.clone()).layout_gutter_decorations(
                state.input_bounds.origin.x,
                &scrolled,
                &state.input_bounds,
                layout,
                None,
                cx,
            );
            assert!(!marks.is_empty() && marks.len() <= found.len());
            assert!(marks.iter().all(|mark| {
                mark.bounds.bottom() >= state.input_bounds.top()
                    && mark.bounds.top() <= state.input_bounds.bottom()
            }));
        });
    }

    #[gpui::test]
    fn default_decoration_collections_address_no_editor(cx: &mut TestAppContext) {
        assert_eq!(GutterDecoration::default().range(), &(0..0));
        assert_eq!(
            OverviewRulerDecoration::default().lane(),
            OverviewRulerLane::Center
        );
        cx.update(|cx| {
            let gutter = GutterDecorationCollection::default();
            gutter.set(vec![GutterDecoration::new(0..1)], cx);
            gutter.append(vec![GutterDecoration::new(1..2)], cx);
            assert!(gutter.get_ranges(cx).is_empty());
            gutter.clear(cx);
            gutter.dispose(cx);

            let ruler = OverviewRulerDecorationCollection::default();
            ruler.set(vec![OverviewRulerDecoration::new(0..1)], cx);
            assert!(ruler.get_ranges(cx).is_empty());
            ruler.dispose(cx);
        });
    }

    #[gpui::test]
    fn overview_ruler_marks_follow_the_content_height_and_merge(cx: &mut TestAppContext) {
        let text = "x\n".repeat(99) + "x";
        let (editor, window) = decoration_editor(cx, &text, false);
        let mut cx = VisualTestContext::from_window(window.into(), cx);
        cx.update(|window, cx| {
            let line = |n: usize| n * 2;
            let (green, red, blue) = (gpui::green(), gpui::red(), gpui::blue());
            editor.update(cx, |state, cx| {
                state.create_overview_ruler_decorations_collection(
                    vec![
                        OverviewRulerDecoration::new(line(0)..line(50))
                            .with_lane(OverviewRulerLane::Left)
                            .with_color(green),
                        OverviewRulerDecoration::new(line(80)..line(80))
                            .with_lane(OverviewRulerLane::Left)
                            .with_color(red),
                        OverviewRulerDecoration::new(line(50)..line(60))
                            .with_lane(OverviewRulerLane::Left)
                            .with_color(green),
                        OverviewRulerDecoration::new(line(10)..line(11)).with_color(blue),
                    ],
                    cx,
                );
            });
            window.draw(cx).clear(cx);
            let state = editor.read(cx);
            let snapshot = state.editor_scrollbar_snapshot.get().unwrap();
            let layout = &snapshot.layout;
            let content_height = layout.scroll_size.height + layout.bounds.size.height
                - layout.scroll_viewport_size.height;
            assert!(content_height > layout.bounds.size.height);
            let y = |row: usize| {
                layout.bounds.top()
                    + (snapshot.padding_top + snapshot.line_height * row as f32)
                        * (layout.bounds.size.height / content_height)
            };
            let track_left = layout.bounds.right() - Scrollbar::width();
            let third = Scrollbar::width() / 3.;

            let marks = layout_overview_ruler(state, &snapshot, Scrollbar::width());
            assert_eq!(marks.len(), 3, "touching marks of one color merge");
            // Left lane, in document order: the merged run, then the boundary.
            assert_eq!(
                marks[0].bounds,
                Bounds::new(point(track_left, y(0)), size(third, y(60) - y(0)))
            );
            assert_eq!(marks[0].background, green.into());
            assert_eq!(marks[1].bounds.size.height, MIN_OVERVIEW_RULER_MARK_HEIGHT);
            assert!((marks[1].bounds.center().y - y(80)).abs() < px(0.01));
            assert_eq!(marks[1].background, red.into());
            // The center lane is the default.
            assert_eq!(marks[2].bounds.left(), track_left + third);
            assert_eq!(marks[2].bounds.size.height, MIN_OVERVIEW_RULER_MARK_HEIGHT);

            // A wider themed track moves and widens the lanes with it.
            let wide = layout_overview_ruler(state, &snapshot, px(21.));
            assert_eq!(wide[0].bounds.left(), layout.bounds.right() - px(21.));
            assert_eq!(wide[0].bounds.size.width, px(7.));
        });
    }

    #[gpui::test]
    fn overview_ruler_marks_follow_edits_folds_and_new_decorations(cx: &mut TestAppContext) {
        let text = "x\n".repeat(99) + "x";
        let (editor, window) = decoration_editor(cx, &text, false);
        let mut cx = VisualTestContext::from_window(window.into(), cx);
        cx.update(|window, cx| {
            let line = |n: usize| n * 2;
            let ruler = editor.update(cx, |state, cx| {
                state.create_overview_ruler_decorations_collection(
                    vec![OverviewRulerDecoration::new(line(50)..line(51))],
                    cx,
                )
            });
            let top = |window: &mut Window, cx: &mut App| {
                window.draw(cx).clear(cx);
                let state = editor.read(cx);
                let snapshot = state.editor_scrollbar_snapshot.get().unwrap();
                let marks = layout_overview_ruler(state, &snapshot, Scrollbar::width());
                assert_eq!(marks.len(), 1);
                marks[0].bounds.top()
            };
            let start = top(window, cx);
            assert_eq!(top(window, cx), start, "nothing changed, nothing moves");

            editor.update(cx, |state, cx| {
                state.replace_text_in_range(Some(0..0), &"y\n".repeat(10), window, cx)
            });
            let edited = top(window, cx);
            assert!(
                edited > start,
                "ten lines inserted above move the mark down"
            );

            editor.update(cx, |state, cx| {
                state.apply_highlighter_fold_candidates(vec![FoldRange::new(0, 30)], cx);
                state.display_map.set_folded(0, true);
                cx.notify();
            });
            let folded = top(window, cx);
            assert!(folded < edited, "folding rows above moves the mark up");

            ruler.set(vec![OverviewRulerDecoration::new(line(90)..line(91))], cx);
            assert!(
                top(window, cx) > folded,
                "new decorations replace the old marks"
            );
        });
    }

    #[gpui::test]
    fn geometric_decorations_project_folds_without_changing_tracked_ranges(
        cx: &mut TestAppContext,
    ) {
        let text = "top\nhidden one\nhidden two\nend\nlast";
        let (editor, window) = decoration_editor(cx, text, false);
        let mut cx = VisualTestContext::from_window(window.into(), cx);
        cx.update(|window, cx| {
            let hidden = 4..text.find("end").unwrap();
            let collection = editor.update(cx, |state, cx| {
                state.apply_highlighter_fold_candidates(vec![FoldRange::new(0, 3)], cx);
                state.display_map.set_folded(0, true);
                state.create_range_decorations_collection(
                    vec![RangeDecoration::new(hidden.clone())],
                    cx,
                )
            });
            window.draw(cx).clear(cx);
            {
                let state = editor.read(cx);
                let layout = state.last_layout.as_ref().unwrap();
                assert_eq!(layout.visible_buffer_lines, vec![0, 3, 4]);
                assert!(TextElement::<EditorMode>::layout_range_corners(&hidden, layout).is_none());
                let (_, frames) = TextElement::new(editor.clone()).layout_range_decorations(
                    layout,
                    &state.input_bounds,
                    window,
                    state.input_bounds,
                    cx,
                );
                assert!(frames.is_empty());
                let spanning =
                    TextElement::<EditorMode>::layout_range_corners(&(0..text.len()), layout)
                        .unwrap();
                assert_eq!(spanning.len(), 3);
                assert_eq!(spanning[1].top_left.y, spanning[0].bottom_left.y);
            }
            assert_eq!(collection.get_ranges(cx), vec![hidden.clone()]);
            editor.update(cx, |state, cx| {
                state.display_map.set_folded(0, false);
                cx.notify();
            });
            window.draw(cx).clear(cx);
            let state = editor.read(cx);
            let layout = state.last_layout.as_ref().unwrap();
            let revealed =
                TextElement::<EditorMode>::layout_range_corners(&hidden, layout).unwrap();
            assert_eq!(revealed.len(), 2);
            assert_eq!(collection.get_ranges(cx), vec![hidden]);
        });
    }

    #[gpui::test]
    fn geometric_decorations_track_edits_history_replacement_and_owner_lifetime(
        cx: &mut TestAppContext,
    ) {
        let (editor, window) = decoration_editor(cx, "abc def", false);
        let mut cx = VisualTestContext::from_window(window.into(), cx);
        cx.update(|window, cx| {
            let (first, second) = editor.update(cx, |state, cx| {
                (
                    state.create_range_decorations_collection(vec![RangeDecoration::new(4..7)], cx),
                    state.create_range_decorations_collection(vec![RangeDecoration::new(0..3)], cx),
                )
            });
            editor.update(cx, |state, cx| {
                state.set_selected_range(0..0, cx);
                state.replace_text_in_range(None, "\n", window, cx);
            });
            assert_eq!(first.get_ranges(cx), vec![5..8]);
            editor.update(cx, |state, cx| state.undo(&Undo, window, cx));
            assert_eq!(first.get_ranges(cx), vec![4..7]);
            editor.update(cx, |state, cx| state.redo(&Redo, window, cx));
            assert_eq!(first.get_ranges(cx), vec![5..8]);
            first.clear(cx);
            assert_eq!(second.get_ranges(cx), vec![1..4]);
            first.append(vec![RangeDecoration::new(5..8)], cx);
            editor.update(cx, |state, cx| state.replace_all("formatted", window, cx));
            assert_eq!(first.get_ranges(cx), vec![0..9]);
            editor.update(cx, |state, cx| state.undo(&Undo, window, cx));
            // Annotations are transformed, not snapshotted in undo history.
            assert_eq!(first.get_ranges(cx), vec![0..8]);
            editor.update(cx, |state, cx| state.set_value("new", window, cx));
            assert_eq!(first.get_ranges(cx), vec![0..3]);
            let clone = first.clone();
            first.dispose(cx);
            clone.append(vec![RangeDecoration::new(0..1)], cx);
            assert!(clone.get_ranges(cx).is_empty());
            assert_eq!(second.get_ranges(cx), vec![0..3]);
            editor.update(cx, |state, cx| state.set_value("", window, cx));
            assert!(second.get_ranges(cx).is_empty());
            window.draw(cx).clear(cx);
        });
    }

    #[test]
    fn frame_outline_is_continuous_across_different_line_widths() {
        let corners = [
            Corners {
                top_left: point(px(2.), px(0.)),
                top_right: point(px(20.), px(0.)),
                bottom_left: point(px(2.), px(10.)),
                bottom_right: point(px(20.), px(10.)),
            },
            Corners {
                top_left: point(px(0.), px(10.)),
                top_right: point(px(12.), px(10.)),
                bottom_left: point(px(0.), px(20.)),
                bottom_right: point(px(12.), px(20.)),
            },
        ];

        assert_eq!(
            frame_outline_points(&corners),
            vec![
                point(px(2.), px(0.)),
                point(px(20.), px(0.)),
                point(px(20.), px(10.)),
                point(px(12.), px(10.)),
                point(px(12.), px(20.)),
                point(px(0.), px(20.)),
                point(px(0.), px(10.)),
                point(px(2.), px(10.)),
                point(px(2.), px(0.)),
            ]
        );
    }

    #[test]
    fn frame_outline_keeps_horizontal_space_between_the_stroke_and_text() {
        let corners = [Corners {
            top_left: point(px(2.), px(0.)),
            top_right: point(px(20.), px(0.)),
            bottom_left: point(px(2.), px(10.)),
            bottom_right: point(px(20.), px(10.)),
        }];

        assert_eq!(
            pad_frame_corners(&corners, px(1.)),
            vec![Corners {
                top_left: point(px(1.), px(0.)),
                top_right: point(px(21.), px(0.)),
                bottom_left: point(px(1.), px(10.)),
                bottom_right: point(px(21.), px(10.)),
            }]
        );

        let points = frame_outline_points(&corners);
        assert_eq!(points.first(), points.last());
    }

    #[test]
    fn frame_outline_stroke_is_aligned_to_physical_pixels_at_each_scale_factor() {
        let points = vec![point(px(0.2), px(1.8)), point(px(10.7), px(20.3))];

        for (scale_factor, expected_width, expected_points) in [
            (
                1.,
                px(1.),
                vec![point(px(0.5), px(1.5)), point(px(10.5), px(20.5))],
            ),
            (
                1.5,
                px(2. / 3.),
                vec![
                    point(px(1. / 3.), px(5. / 3.)),
                    point(px(11.), px(61. / 3.)),
                ],
            ),
            (
                2.,
                px(1.),
                vec![point(px(0.), px(2.)), point(px(10.5), px(20.5))],
            ),
        ] {
            let (width, snapped) = snap_frame_outline(&points, px(1.), scale_factor);
            assert_eq!(width, expected_width);
            assert_eq!(snapped, expected_points);
        }
    }

    #[test]
    fn frame_outline_keeps_its_vertical_edges_inside_the_content_mask() {
        let points = vec![
            point(px(9.5), px(2.5)),
            point(px(20.5), px(2.5)),
            point(px(20.5), px(10.5)),
            point(px(9.5), px(10.5)),
            point(px(9.5), px(2.5)),
        ];
        let mask = Bounds::new(point(px(10.), px(0.)), size(px(10.), px(20.)));

        assert_eq!(
            clamp_frame_to_content_mask(points, px(1.), mask),
            vec![
                point(px(10.5), px(2.5)),
                point(px(19.5), px(2.5)),
                point(px(19.5), px(10.5)),
                point(px(10.5), px(10.5)),
                point(px(10.5), px(2.5)),
            ]
        );
    }

    #[test]
    fn test_plain_text_decorations_include_unstyled_gaps() {
        let decoration = HighlightStyle {
            background_color: Some(gpui::red()),
            ..Default::default()
        };
        let styles = compose_decorations(Vec::new(), [(2..5, decoration)], 0..10).unwrap();

        assert_eq!(
            styles
                .iter()
                .map(|(range, _)| range.clone())
                .collect::<Vec<_>>(),
            vec![0..2, 2..5, 5..10]
        );
        assert_eq!(styles[0].1, HighlightStyle::default());
        assert_eq!(styles[1].1.background_color, Some(gpui::red()));
        assert_eq!(styles[2].1, HighlightStyle::default());
    }

    #[test]
    fn test_first_decoration_collection_has_precedence() {
        let first = [TextDecoration::new(
            0..4,
            HighlightStyle {
                background_color: Some(gpui::red()),
                ..Default::default()
            },
        )];
        let second = [TextDecoration::new(
            0..4,
            HighlightStyle {
                background_color: Some(gpui::blue()),
                ..Default::default()
            },
        )];

        let styles =
            compose_decoration_collections(Vec::new(), [&first[..], &second[..]], 0..4).unwrap();

        assert_eq!(styles.len(), 1);
        assert_eq!(styles[0].1.background_color, Some(gpui::red()));
    }

    #[test]
    fn test_decorations_override_syntax_highlights() {
        let syntax = vec![(
            0..8,
            HighlightStyle {
                color: Some(gpui::blue()),
                ..Default::default()
            },
        )];
        let decoration = HighlightStyle {
            color: Some(gpui::red()),
            font_style: Some(gpui::FontStyle::Italic),
            ..Default::default()
        };

        let styles = compose_decorations(syntax, [(2..6, decoration)], 0..8).unwrap();

        assert_eq!(styles[1].0, 2..6);
        assert_eq!(styles[1].1.color, Some(gpui::red()));
        assert_eq!(styles[1].1.font_style, Some(gpui::FontStyle::Italic));
    }

    #[test]
    fn test_editor_scrollbar_layout_uses_current_scroll_size() {
        let input_bounds = Bounds::new(point(px(10.), px(20.)), size(px(300.), px(80.)));
        let paddings = Edges {
            top: px(2.),
            right: px(3.),
            bottom: px(5.),
            left: px(7.),
        };

        let layout =
            EditorScrollbarLayout::new(input_bounds, px(40.), size(px(1000.), px(200.)), paddings);

        assert_eq!(
            layout.bounds,
            Bounds::new(point(px(51.), px(18.)), size(px(262.), px(87.)))
        );
        assert_eq!(layout.scroll_size, size(px(972.), px(200.)));
        assert_eq!(layout.scroll_viewport_size, size(px(262.), px(80.)));

        let layout_without_gutter =
            EditorScrollbarLayout::new(input_bounds, px(0.), size(px(500.), px(120.)), paddings);

        assert_eq!(
            layout_without_gutter.bounds,
            Bounds::new(point(px(10.), px(18.)), size(px(303.), px(87.)))
        );
        assert_eq!(layout_without_gutter.scroll_size, size(px(513.), px(120.)));
        assert_eq!(
            layout_without_gutter.scroll_viewport_size,
            size(px(303.), px(80.))
        );
    }

    #[test]
    fn test_editor_gutter_covers_the_complete_fixed_column() {
        let input_bounds = Bounds::new(point(px(10.), px(20.)), size(px(300.), px(80.)));

        assert_eq!(
            editor_gutter_bounds(
                input_bounds,
                px(48.),
                px(16.),
                Edges {
                    top: px(2.),
                    right: px(3.),
                    bottom: px(5.),
                    left: px(7.),
                },
            ),
            Bounds::new(point(px(3.), px(18.)), size(px(55.), px(103.)))
        );
    }

    #[test]
    fn test_vertical_scroll_offset_is_clamped_to_current_viewport() {
        assert_eq!(
            clamp_vertical_scroll_offset(px(-260.), px(340.), px(160.)),
            px(-180.)
        );
        assert_eq!(
            clamp_vertical_scroll_offset(px(-40.), px(340.), px(160.)),
            px(-40.)
        );
        assert_eq!(
            clamp_vertical_scroll_offset(px(20.), px(340.), px(160.)),
            px(0.)
        );
        assert_eq!(
            clamp_vertical_scroll_offset(px(-40.), px(100.), px(160.)),
            px(0.)
        );
    }

    #[test]
    fn test_runs_for_range() {
        let run = TextRun {
            len: 0,
            font: gpui::font(".SystemUIFont"),
            color: gpui::black(),
            background_color: None,
            underline: None,
            strikethrough: None,
        };

        // use hello this-is-test
        let runs = vec![
            // use
            TextRun {
                len: 3,
                ..run.clone()
            },
            // \s
            TextRun {
                len: 1,
                ..run.clone()
            },
            // hello
            TextRun {
                len: 5,
                ..run.clone()
            },
            // \s
            TextRun {
                len: 1,
                ..run.clone()
            },
            // this-is-test
            TextRun {
                len: 12,
                ..run.clone()
            },
        ];

        #[track_caller]
        fn assert_runs(actual: Vec<TextRun>, expected: &[usize]) {
            let left = actual.iter().map(|run| run.len).collect::<Vec<_>>();
            assert_eq!(left, expected);
        }

        assert_runs(runs_for_range(&runs, 0, &(0..0)), &[]);
        assert_runs(runs_for_range(&runs, 0, &(0..100)), &[3, 1, 5, 1, 12]);

        assert_runs(runs_for_range(&runs, 0, &(0..6)), &[3, 1, 2]);
        assert_runs(runs_for_range(&runs, 0, &(1..6)), &[2, 1, 2]);
        assert_runs(runs_for_range(&runs, 0, &(3..10)), &[1, 5, 1]);
        assert_runs(runs_for_range(&runs, 0, &(5..8)), &[3]);
        assert_runs(runs_for_range(&runs, 3, &(0..3)), &[1, 2]);
        assert_runs(runs_for_range(&runs, 3, &(2..10)), &[4, 1, 3]);
        assert_runs(runs_for_range(&runs, 9, &(0..8)), &[1, 7]);
    }

    #[test]
    fn test_split_runs_preserve_ime_underline_across_highlight_boundaries() {
        let underline = UnderlineStyle {
            thickness: px(1.),
            color: Some(gpui::black()),
            wavy: false,
        };

        let runs = [0..4, 4..10]
            .into_iter()
            .flat_map(|range| {
                split_run_for_ime_underline(
                    TextStyle::default().to_run(range.len()),
                    range,
                    Some(2..7),
                    Some(underline),
                )
            })
            .collect::<Vec<_>>();

        assert_eq!(
            runs.iter()
                .map(|run| (run.len, run.underline.is_some()))
                .collect::<Vec<_>>(),
            vec![(2, false), (2, true), (3, true), (3, false)]
        );
    }

    #[test]
    fn test_split_run_applies_ime_underline_without_highlighting() {
        let underline = UnderlineStyle {
            thickness: px(1.),
            color: Some(gpui::black()),
            wavy: false,
        };

        let runs = split_run_for_ime_underline(
            TextStyle::default().to_run(10),
            0..10,
            Some(2..7),
            Some(underline),
        );

        assert_eq!(
            runs.iter()
                .map(|run| (run.len, run.underline.is_some()))
                .collect::<Vec<_>>(),
            vec![(2, false), (5, true), (3, false)]
        );
        assert!(
            split_run_for_ime_underline(TextStyle::default().to_run(0), 0..0, None, None)
                .is_empty()
        );
    }

    #[test]
    fn test_masked_ime_underline_splits_on_mask_char_boundaries() {
        let underline = UnderlineStyle {
            thickness: px(1.),
            color: Some(gpui::black()),
            wavy: false,
        };
        let text = Rope::from("abcdef");
        let mask_len = MASK_CHAR.len_utf8();

        assert_eq!(
            ime_marked_display_range(&text, Some(4..6), false),
            Some(4..6)
        );
        assert_eq!(ime_marked_display_range(&text, None, true), None);
        assert_eq!(
            ime_marked_display_range(&text, Some(4..6), true),
            Some(4 * mask_len..6 * mask_len)
        );

        let display_text = MASK_CHAR.to_string().repeat(text.chars().count());
        let runs = split_run_for_ime_underline(
            TextStyle::default().to_run(display_text.len()),
            0..display_text.len(),
            ime_marked_display_range(&text, Some(4..6), true),
            Some(underline),
        );

        let mut offset = 0;
        for run in &runs {
            assert!(display_text.is_char_boundary(offset));
            offset += run.len;
        }
        assert_eq!(offset, display_text.len());
    }

    #[test]
    fn test_placeholder_line_runs() {
        let run = TextRun {
            len: 0,
            font: gpui::font(".SystemUIFont"),
            color: gpui::black(),
            background_color: None,
            underline: None,
            strikethrough: None,
        };

        let runs = vec![
            TextRun {
                len: 2,
                ..run.clone()
            },
            TextRun {
                len: 2,
                ..run.clone()
            },
            TextRun { len: 1, ..run },
        ];

        let placeholder_runs = placeholder_line_runs("ab\n\nc", &runs);

        let lines = placeholder_runs
            .iter()
            .map(|(line, _)| *line)
            .collect::<Vec<_>>();
        assert_eq!(lines, vec!["ab", "", "c"]);

        let run_lengths = placeholder_runs
            .iter()
            .map(|(_, line_runs)| line_runs.iter().map(|run| run.len).collect::<Vec<_>>())
            .collect::<Vec<_>>();
        assert_eq!(run_lengths, vec![vec![2], vec![], vec![1]]);
    }

    #[test]
    fn test_align_runs_to_char_boundaries() {
        let run = TextRun {
            len: 0,
            font: gpui::font(".SystemUIFont"),
            color: gpui::blue(),
            background_color: None,
            underline: None,
            strikethrough: None,
        };
        let runs = |lens: &[usize]| {
            lens.iter()
                .map(|&len| TextRun { len, ..run.clone() })
                .collect::<Vec<_>>()
        };
        let lens = |runs: &[TextRun]| runs.iter().map(|run| run.len).collect::<Vec<_>>();

        // "你好，世界" is 15 bytes; boundaries at 0, 3, 6, 9, 12, 15.
        let text = "你好，世界";

        // Aligned runs pass through untouched.
        assert_eq!(align_runs_to_char_boundaries(text, &runs(&[3, 12])), None);

        // A mid-char boundary (4) snaps up to the next boundary (6).
        let aligned = align_runs_to_char_boundaries(text, &runs(&[4, 11])).unwrap();
        assert_eq!(lens(&aligned), vec![6, 9]);

        // Several boundaries inside the same char collapse into one run.
        let aligned = align_runs_to_char_boundaries(text, &runs(&[1, 1, 13])).unwrap();
        assert_eq!(lens(&aligned), vec![3, 12]);

        // Overshooting runs are capped at the text length.
        let aligned = align_runs_to_char_boundaries(text, &runs(&[3, 20])).unwrap();
        assert_eq!(lens(&aligned), vec![3, 12]);

        // Undershooting runs keep the shortfall (the tail is left unshaped,
        // matching `runs_for_range` clipping).
        assert_eq!(align_runs_to_char_boundaries(text, &runs(&[3, 3])), None);
    }

    #[test]
    fn test_clip_styles_to_ranges() {
        let style = HighlightStyle::default();
        let styles = vec![(0..4, style), (4..10, style), (12..20, style)];

        // Ranges with a gap (a folded region) drop the gap coverage and split
        // styles that span a range edge.
        let clipped = clip_styles_to_ranges(styles.clone(), &[2..6, 14..18]);
        assert_eq!(
            clipped
                .iter()
                .map(|(range, _)| range.clone())
                .collect::<Vec<_>>(),
            vec![2..4, 4..6, 14..18]
        );

        // Styles fully inside the ranges are unchanged.
        let clipped = clip_styles_to_ranges(styles.clone(), &[0..20]);
        assert_eq!(
            clipped
                .iter()
                .map(|(range, _)| range.clone())
                .collect::<Vec<_>>(),
            vec![0..4, 4..10, 12..20]
        );

        // A single style spanning several ranges splits into one piece per range.
        let clipped = clip_styles_to_ranges(vec![(0..30, style)], &[5..10, 20..25]);
        assert_eq!(
            clipped
                .iter()
                .map(|(range, _)| range.clone())
                .collect::<Vec<_>>(),
            vec![5..10, 20..25]
        );

        assert!(clip_styles_to_ranges(styles, &[]).is_empty());
    }

    #[test]
    fn test_split_runs_by_bg_segments() {
        let run = TextRun {
            len: 0,
            font: gpui::font(".SystemUIFont"),
            color: gpui::blue(),
            background_color: None,
            underline: None,
            strikethrough: None,
        };

        let runs = vec![
            TextRun {
                len: 5,
                ..run.clone()
            },
            TextRun {
                len: 7,
                ..run.clone()
            },
            TextRun {
                len: 24,
                ..run.clone()
            },
        ];

        let bg_segments = vec![(8..12, gpui::red()), (12..18, gpui::blue())];
        let result = split_runs_by_bg_segments(5, &runs, &bg_segments);
        assert_eq!(
            result.iter().map(|run| run.len).collect::<Vec<_>>(),
            vec![3, 2, 2, 5, 1, 23]
        );
        assert_eq!(result[0].color, gpui::blue());
        assert_eq!(result[1].color, gpui::black());
        assert_eq!(result[2].color, gpui::black());
        assert_eq!(result[3].color, gpui::black());
        assert_eq!(result[4].color, gpui::black());
        assert_eq!(result[5].color, gpui::blue());
    }

    #[test]
    fn test_empty_bottom_height_outside_code_editor() {
        // Single-line / plain-text / auto-grow modes never reserve empty
        // bottom space, regardless of any override.
        for override_rows in [None, Some(0), Some(3), Some(99)] {
            assert_eq!(
                empty_bottom_height(false, override_rows, px(800.), px(20.)),
                px(0.),
            );
        }
    }

    #[test]
    fn test_empty_bottom_height_code_editor_default() {
        // `None`: roughly half the viewport, floored at
        // `BOTTOM_MARGIN_ROWS * line_height` so the empty area never
        // collapses to "less than a few lines" on tiny viewports.
        let line_height = px(20.);

        // Viewport much taller than the floor → half-viewport wins.
        assert_eq!(
            empty_bottom_height(true, None, px(800.), line_height),
            px(400.),
        );

        // Viewport shorter than 2 × floor → floor wins.
        let floor = BOTTOM_MARGIN_ROWS * line_height;
        assert_eq!(empty_bottom_height(true, None, px(40.), line_height), floor);
    }

    #[test]
    fn test_empty_bottom_height_explicit_row_count() {
        // `Some(n)`: exactly `n` line-heights. Caller fully controls
        // the trailing empty space; viewport size doesn't amplify it.
        let line_height = px(20.);

        for rows in [0_usize, 1, 3, 8, 64] {
            let expected = rows as f32 * line_height;
            assert_eq!(
                empty_bottom_height(true, Some(rows), px(800.), line_height),
                expected,
            );
            // Tiny viewport: still exactly `n × line_height`, no floor
            // applied when caller supplied an explicit count.
            assert_eq!(
                empty_bottom_height(true, Some(rows), px(20.), line_height),
                expected,
            );
        }
    }

    #[test]
    fn row_reveal_contains_the_whole_row_and_has_a_stable_offset() {
        let line_height = px(20.);
        let row_top = px(1000.);
        for viewport_height in [px(20.), px(30.), px(600.)] {
            for auto_grow in [false, true] {
                for surrounding in [None, Some(0), Some(50)] {
                    let padding = cursor_surrounding_padding(
                        auto_grow,
                        surrounding,
                        viewport_visible_lines(viewport_height, line_height),
                        line_height,
                    );
                    for previous in [px(-1500.), px(-1000.), px(0.)] {
                        let offset =
                            reveal_row(previous, row_top, line_height, viewport_height, padding);
                        assert!(row_top + offset >= px(0.));
                        assert!(row_top + offset + line_height <= viewport_height);
                        assert_eq!(
                            reveal_row(offset, row_top, line_height, viewport_height, padding),
                            offset,
                            "unchanged caret must not oscillate",
                        );
                    }
                }
            }
        }
    }

    #[test]
    fn undersized_row_reveal_aligns_the_start_without_oscillating() {
        let offset = reveal_row(px(0.), px(80.), px(20.), px(10.), px(60.));
        assert_eq!(px(80.) + offset, px(0.));
        assert_eq!(
            reveal_row(offset, px(80.), px(20.), px(10.), px(60.)),
            offset
        );
    }
}
