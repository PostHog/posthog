use std::{
    cell::{Cell, RefCell},
    collections::HashMap,
    ops::Range,
    rc::Rc,
    sync::atomic::{AtomicU64, Ordering},
};

use gpui::{
    App, AppContext as _, Bounds, Context, Element, ElementId, Entity, EntityId, EventEmitter,
    Global, GlobalElementId, Half, Hitbox, HitboxBehavior, Hsla, InputEvent as _,
    InspectorElementId, IntoElement, LayoutId, LongPressEvent, MouseButton, MouseDownEvent,
    MouseMoveEvent, MouseUpEvent, Pixels, Point, ScrollDelta, ScrollEvent, SharedString, Style,
    Subscription, TextLayout, TouchDragEvent, TouchPhase, WeakEntity, Window, point, px,
};

use crate::text_boundary::{line_range_at, word_range_at};
use crate::touch_selection::{
    EdgeDrag, SelectionEdge, TouchHandle, TouchSelectionSnapshot, caret_in_view, caret_line_box,
};
use crate::{AutoScroll, GlobalState};

/// An opaque selection layer identifier.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Hash)]
pub struct TextSelectionScopeId(u64);

impl TextSelectionScopeId {
    /// Allocates a process-unique scope identifier.
    ///
    /// Keep the returned identifier for the semantic lifetime of the scope;
    /// do not allocate a new identifier on every frame.
    pub fn new() -> Self {
        static NEXT_SCOPE_ID: AtomicU64 = AtomicU64::new(1);
        let value = NEXT_SCOPE_ID
            .try_update(Ordering::Relaxed, Ordering::Relaxed, |value| {
                value.checked_add(1)
            })
            .expect("text selection scope identifiers exhausted");
        Self(value)
    }

    #[cfg(test)]
    const fn from_raw(value: u64) -> Self {
        Self(value)
    }
}

/// Stable participant-defined identity for virtualized participant content.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub struct TextSelectionContentKey(u64);

impl TextSelectionContentKey {
    /// Creates a key from a participant-defined stable content identity.
    pub const fn new(value: u64) -> Self {
        Self(value)
    }

    /// Returns the participant-defined value.
    pub const fn value(self) -> u64 {
        self.0
    }
}

/// A selection endpoint anchored to a participant's content coordinates.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct TextSelectionEndpoint {
    entity_id: Option<EntityId>,
    point: Point<Pixels>,
    content_key: Option<TextSelectionContentKey>,
}

impl TextSelectionEndpoint {
    /// Creates an endpoint at a participant-relative content point.
    pub(crate) const fn new(entity_id: Option<EntityId>, point: Point<Pixels>) -> Self {
        Self {
            entity_id,
            point,
            content_key: None,
        }
    }

    /// Sets participant-defined endpoint metadata.
    pub(crate) const fn with_content_key(mut self, content_key: TextSelectionContentKey) -> Self {
        self.content_key = Some(content_key);
        self
    }

    /// Returns the participant which owns this endpoint, when it hit one.
    pub const fn entity_id(&self) -> Option<EntityId> {
        self.entity_id
    }

    /// Returns the participant-relative content point.
    pub const fn content_point(&self) -> Point<Pixels> {
        self.point
    }

    /// Returns participant-defined endpoint metadata captured when it hit a participant.
    pub const fn content_key(&self) -> Option<TextSelectionContentKey> {
        self.content_key
    }
}

/// Window-coordinate anchor and cursor points for painting a selection.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct TextSelectionWindowPoints {
    anchor: Point<Pixels>,
    cursor: Point<Pixels>,
}

impl TextSelectionWindowPoints {
    /// Returns the stable anchor in window coordinates.
    pub const fn anchor(&self) -> Point<Pixels> {
        self.anchor
    }

    /// Returns the moving cursor in window coordinates.
    pub const fn cursor(&self) -> Point<Pixels> {
        self.cursor
    }
}

/// Participant-relative selection endpoints with an optional rendering projection.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct TextSelectionSnapshot {
    anchor: TextSelectionEndpoint,
    cursor: TextSelectionEndpoint,
    is_selecting: bool,
    window_points: Option<TextSelectionWindowPoints>,
    coverage: TextSelectionCoverage,
}

/// How much of one participant participates in a window selection.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum TextSelectionCoverage {
    /// Only the interval between this participant's two endpoints is selected.
    #[default]
    Bounded,
    /// The participant is selected from its beginning through its endpoint.
    FromStart,
    /// The participant is selected from its endpoint through its end.
    ToEnd,
    /// The entire participant lies between endpoints in other participants.
    Full,
}

impl TextSelectionSnapshot {
    /// Creates a snapshot from stable participant-relative endpoints.
    pub(crate) const fn new(anchor: TextSelectionEndpoint, cursor: TextSelectionEndpoint) -> Self {
        Self {
            anchor,
            cursor,
            is_selecting: false,
            window_points: None,
            coverage: TextSelectionCoverage::Bounded,
        }
    }

    /// Sets whether the pointer gesture is still active.
    pub(crate) const fn with_selecting(mut self, is_selecting: bool) -> Self {
        self.is_selecting = is_selecting;
        self
    }

    /// Sets the current window-coordinate rendering projection.
    pub(crate) const fn with_window_points(
        mut self,
        window_points: Option<TextSelectionWindowPoints>,
    ) -> Self {
        self.window_points = window_points;
        self
    }

    /// Sets the portion of the receiving participant covered by this selection.
    #[cfg(test)]
    pub(crate) const fn with_coverage(mut self, coverage: TextSelectionCoverage) -> Self {
        self.coverage = coverage;
        self
    }

    /// Returns the stable anchor endpoint.
    pub const fn anchor(&self) -> TextSelectionEndpoint {
        self.anchor
    }

    /// Returns the moving cursor endpoint.
    pub const fn cursor(&self) -> TextSelectionEndpoint {
        self.cursor
    }

    /// Returns whether the pointer gesture is still active.
    pub const fn is_selecting(&self) -> bool {
        self.is_selecting
    }

    /// Returns the window-coordinate endpoints for participants that need them.
    pub const fn window_points(&self) -> Option<TextSelectionWindowPoints> {
        self.window_points
    }

    /// Returns the portion of the receiving participant covered by this selection.
    pub const fn coverage(&self) -> TextSelectionCoverage {
        self.coverage
    }
}

/// Retained element state proving a participant is still in the window.
///
/// A participant reports its geometry from `paint`, which a cached view
/// (`Entity::cached`) skips: GPUI replays the recorded frame instead. The
/// element's retained state is replayed with it, so this marker outlives the
/// frames whose paint never ran, and dies with the frame that drops the
/// element for good.
struct RenderedMarker;

/// Per-frame geometry reported by a [`TextSelectionHandle`] participant.
pub struct TextSelectionRegistration {
    hitbox: Hitbox,
    bounds: Bounds<Pixels>,
    scroll_offset: Point<Pixels>,
    scope: TextSelectionScopeId,
    document_order: u64,
    paint_order: bool,
    text_bounds: Vec<Bounds<Pixels>>,
    self_scroll: bool,
    selection_edges: Option<(Bounds<Pixels>, Bounds<Pixels>)>,
    rendered: Option<WeakEntity<RenderedMarker>>,
}

impl TextSelectionRegistration {
    /// Creates a registration with default scope, order, and scroll offset.
    pub fn new(hitbox: Hitbox, bounds: Bounds<Pixels>) -> Self {
        Self {
            hitbox,
            bounds,
            scroll_offset: Point::default(),
            scope: TextSelectionScopeId::default(),
            document_order: 0,
            paint_order: false,
            text_bounds: Vec::new(),
            self_scroll: false,
            selection_edges: None,
            rendered: None,
        }
    }

    /// Ties this registration to the retained state of the element reporting
    /// it, so that a frame replayed from that element's cached view keeps it.
    ///
    /// Call this from the reporting element's `prepaint` or `paint`. A
    /// registration made outside a drawing element cannot be tied to one and
    /// is swept the first frame it misses, as every registration used to be.
    pub fn with_rendered_element(
        mut self,
        participant: &TextSelectionHandle,
        window: &mut Window,
        cx: &mut App,
    ) -> Self {
        self.rendered = Some(
            window
                .use_keyed_state(
                    ElementId::NamedInteger(
                        "text-selection-participant".into(),
                        participant.entity_id().as_u64(),
                    ),
                    cx,
                    |_, _| RenderedMarker,
                )
                .downgrade(),
        );
        self
    }

    /// Whether the element that reported this registration is still part of
    /// the window, even if it did not paint the frame that just finished.
    fn is_rendered(&self) -> bool {
        self.rendered
            .as_ref()
            .is_some_and(|marker| marker.upgrade().is_some())
    }

    /// Marks a participant that scrolls its own content in response to
    /// [`TextSelectionEvent::AutoScroll`]. Drag auto-scroll then drives it
    /// directly, measured against its own bounds, instead of synthesizing a
    /// wheel event for the nearest scrollable ancestor.
    pub(crate) fn with_self_scroll(mut self, self_scroll: bool) -> Self {
        self.self_scroll = self_scroll;
        self
    }

    /// Sets the participant's content scroll offset.
    pub fn with_scroll_offset(mut self, scroll_offset: Point<Pixels>) -> Self {
        self.scroll_offset = scroll_offset;
        self
    }

    /// Sets the opaque selection scope.
    pub fn with_scope(mut self, scope: TextSelectionScopeId) -> Self {
        self.scope = scope;
        self
    }

    /// Sets the stable logical document order.
    pub fn with_document_order(mut self, document_order: u64) -> Self {
        self.document_order = document_order;
        self
    }

    /// Uses the order of the TextViews in a complete painted frame. A cached
    /// view keeps that order while only some of its siblings paint again.
    pub(crate) fn in_paint_order(mut self) -> Self {
        self.paint_order = true;
        self
    }

    /// Sets the glyph-bearing bounds used to reject blank-only gestures.
    pub fn with_text_bounds(mut self, text_bounds: Vec<Bounds<Pixels>>) -> Self {
        self.text_bounds = text_bounds;
        self
    }

    /// Sets where the participant painted the two ends of its selection: the
    /// caret line box before its first selected character and the one after
    /// its last, in window coordinates. The touch handles are drawn there.
    pub fn with_selection_edges(mut self, start: Bounds<Pixels>, end: Bounds<Pixels>) -> Self {
        self.selection_edges = Some((start, end));
        self
    }

    /// Returns the participant hitbox.
    pub fn hitbox(&self) -> &Hitbox {
        &self.hitbox
    }

    /// Returns the participant's window-coordinate bounds.
    pub const fn bounds(&self) -> Bounds<Pixels> {
        self.bounds
    }

    /// Returns the participant's content scroll offset.
    pub const fn scroll_offset(&self) -> Point<Pixels> {
        self.scroll_offset
    }

    /// Returns the opaque selection scope.
    pub const fn scope(&self) -> TextSelectionScopeId {
        self.scope
    }

    /// Returns the stable logical document order.
    pub const fn document_order(&self) -> u64 {
        self.document_order
    }

    /// Returns the glyph-bearing bounds used to reject blank-only gestures.
    pub fn text_bounds(&self) -> &[Bounds<Pixels>] {
        &self.text_bounds
    }

    /// Returns the caret line boxes at the participant's selection ends.
    pub const fn selection_edges(&self) -> Option<(Bounds<Pixels>, Bounds<Pixels>)> {
        self.selection_edges
    }
}

/// Laid-out text reported by a plain selection participant during paint.
#[derive(Clone)]
pub struct TextSelectionRun {
    /// Logical order within the containing participant.
    document_order: u64,
    /// The exact text used to produce `layout`.
    text: SharedString,
    /// Laid-out glyph geometry in window coordinates.
    layout: TextLayout,
    /// The run's window-coordinate paint bounds.
    bounds: Bounds<Pixels>,
    /// The boundary a triple-click drag snaps to in this run.
    triple_click: TripleClickSelection,
}

#[derive(Clone, Copy)]
enum TripleClickSelection {
    LogicalLine,
    Paragraph,
    Row(Bounds<Pixels>),
}

impl TextSelectionRun {
    /// Creates a laid-out text run.
    pub fn new(text: impl Into<SharedString>, layout: TextLayout, bounds: Bounds<Pixels>) -> Self {
        Self {
            document_order: 0,
            text: text.into(),
            layout,
            bounds,
            triple_click: TripleClickSelection::LogicalLine,
        }
    }

    /// Sets the run's logical order within the participant.
    pub const fn with_document_order(mut self, document_order: u64) -> Self {
        self.document_order = document_order;
        self
    }

    /// Uses TextView's triple-click boundary: the whole paragraph, or the
    /// laid-out row when this run is one piece of an inline flow.
    pub(crate) const fn with_paragraph(mut self, row: Option<Bounds<Pixels>>) -> Self {
        self.triple_click = match row {
            Some(row) => TripleClickSelection::Row(row),
            None => TripleClickSelection::Paragraph,
        };
        self
    }

    /// Returns the run's logical order within its participant.
    pub const fn document_order(&self) -> u64 {
        self.document_order
    }

    /// Returns the exact text used to produce the layout.
    pub fn text(&self) -> &SharedString {
        &self.text
    }

    /// Returns the laid-out glyph geometry.
    pub fn layout(&self) -> &TextLayout {
        &self.layout
    }

    /// Returns the run's window-coordinate paint bounds.
    pub const fn bounds(&self) -> Bounds<Pixels> {
        self.bounds
    }
}

/// Selection projected onto a participant's laid-out text runs.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct TextSelectionProjection {
    /// Selected UTF-8 byte ranges paired with the input runs.
    ranges: Vec<Option<Range<usize>>>,
    /// Whether the participant participates in the current selection.
    is_active: bool,
}

impl TextSelectionProjection {
    /// Returns selected UTF-8 byte ranges paired with the input runs.
    pub fn ranges(&self) -> &[Option<Range<usize>>] {
        &self.ranges
    }

    /// Returns whether the participant participates in the selection.
    pub const fn is_active(&self) -> bool {
        self.is_active
    }
}

/// Projects a participant selection snapshot onto laid-out plain-text runs.
///
/// The returned states retain the input order so callers can pair every state
/// with its run. The ranges are always character boundaries; `order` is used
/// only when a participant caches selected text for copying.
fn project_ranges(
    snapshot: Option<TextSelectionSnapshot>,
    runs: &[TextSelectionRun],
) -> TextSelectionProjection {
    let Some(snapshot) = snapshot else {
        return TextSelectionProjection {
            ranges: vec![None; runs.len()],
            is_active: false,
        };
    };
    let Some(window_points) = snapshot.window_points() else {
        return TextSelectionProjection {
            ranges: vec![None; runs.len()],
            is_active: true,
        };
    };

    TextSelectionProjection {
        ranges: runs
            .iter()
            .map(|run| selection_range_for_run(run, window_points.anchor, window_points.cursor))
            .collect(),
        is_active: true,
    }
}

fn selection_range_for_run(
    run: &TextSelectionRun,
    selection_start: Point<Pixels>,
    selection_end: Point<Pixels>,
) -> Option<Range<usize>> {
    if run.text.len() != run.layout.len() {
        return None;
    }

    if run.text.is_empty() {
        return None;
    }

    let line_height = run.layout.line_height();
    // Each character is tested with its row's top and height, so a run whose
    // rows all miss the band, or all lie strictly inside it with no endpoint
    // on any row, has the same answer for every character. Decide those
    // without the walk below, which scans the layout twice per character.
    let (rows_top, rows_bottom) = text_rows_extent(&run.layout, line_height);
    let band_top = selection_start.y.min(selection_end.y);
    let band_bottom = selection_start.y.max(selection_end.y);
    if rows_bottom <= band_top || rows_top > band_bottom {
        return None;
    }
    if band_top < rows_top && band_bottom >= rows_bottom {
        return Some(0..run.text.len());
    }

    let mut range = None;
    for (offset, character) in run.text.char_indices() {
        let next_offset = offset + character.len_utf8();
        let Some(position) = run.layout.position_for_index(offset) else {
            continue;
        };

        let char_width = run
            .layout
            .position_for_index(next_offset)
            .filter(|next| next.y == position.y)
            .map_or_else(|| line_height.half(), |next| next.x - position.x);

        if point_in_selection_band(
            position,
            char_width,
            selection_start,
            selection_end,
            line_height,
        ) {
            range.get_or_insert(offset..offset).end = next_offset;
        }
    }
    range
}

/// The top of the first laid-out row of `text_layout` and the bottom of its
/// last one, each row `line_height` tall as a selection band test sees it.
///
/// Both ends are accumulated the way [`TextLayout::position_for_index`] places
/// rows, so comparisons against them agree with a per-character walk to the
/// bit. The last laid-out row may hold no character such a walk tests (a
/// trailing empty line, or a row whose only character is placed at the end of
/// the row before it); callers treat the extent as covering, never as exact.
pub(crate) fn text_rows_extent(text_layout: &TextLayout, line_height: Pixels) -> (Pixels, Pixels) {
    let top = text_layout.bounds().top();
    let layout_line_height = text_layout.line_height();
    let lines = text_layout.line_layouts();
    let mut last_line_top = top;
    for line in lines.iter().take(lines.len().saturating_sub(1)) {
        last_line_top += line.size(layout_line_height).height;
    }
    let last_row_top = lines.last().map_or(top, |line| {
        last_line_top + line.wrap_boundaries.len() as f32 * layout_line_height
    });
    (top, last_row_top + line_height)
}

/// The carets at the two ends of what `click_count` clicks at `position`
/// select: the word under it for two, its line or paragraph for three.
fn carets_for_multi_click(
    runs: &[TextSelectionRun],
    position: Point<Pixels>,
    click_count: usize,
) -> Option<(Bounds<Pixels>, Bounds<Pixels>)> {
    let run = runs.iter().find(|run| run.bounds.contains(&position))?;
    if run.text.len() != run.layout.len() {
        return None;
    }
    let offset = run.layout.index_for_position(position).ok()?;
    unit_carets(run, offset, click_count)
}

/// The carets at the two ends of the word (`click_count` 2) or the run's
/// triple-click boundary (3 or more) at the byte `offset` of `run`.
fn unit_carets(
    run: &TextSelectionRun,
    offset: usize,
    click_count: usize,
) -> Option<(Bounds<Pixels>, Bounds<Pixels>)> {
    let range = match click_count {
        2 => word_range_at(&run.text, offset)?,
        3.. => match run.triple_click {
            TripleClickSelection::LogicalLine => line_range_at(&run.text, offset),
            TripleClickSelection::Paragraph => 0..run.text.len(),
            TripleClickSelection::Row(row) => {
                return Some((
                    caret_line_box(row.origin, row.size.height),
                    caret_line_box(row.top_right(), row.size.height),
                ));
            }
        },
        _ => return None,
    };
    if range.is_empty() {
        return None;
    }
    let line_height = run.layout.line_height();
    Some((
        caret_line_box(run.layout.position_for_index(range.start)?, line_height),
        caret_line_box(run.layout.position_for_index(range.end)?, line_height),
    ))
}

fn point_in_selection_band(
    position: Point<Pixels>,
    char_width: Pixels,
    selection_start: Point<Pixels>,
    selection_end: Point<Pixels>,
    line_height: Pixels,
) -> bool {
    let point_in_line =
        |point: Point<Pixels>| point.y >= position.y && point.y < position.y + line_height;
    let top = selection_start.y.min(selection_end.y);
    let bottom = selection_start.y.max(selection_end.y);
    let x = position.x + char_width.half();

    if position.y + line_height <= top || position.y > bottom {
        return false;
    }

    if point_in_line(selection_start) && point_in_line(selection_end) {
        let left = selection_start.x.min(selection_end.x);
        let right = selection_start.x.max(selection_end.x);
        return x >= left && x <= right;
    }

    let (top_point, bottom_point) = if selection_start.y < selection_end.y {
        (selection_start, selection_end)
    } else {
        (selection_end, selection_start)
    };
    if point_in_line(top_point) {
        x >= top_point.x
    } else if point_in_line(bottom_point) {
        x <= bottom_point.x
    } else {
        true
    }
}

type FocusCallback = Rc<dyn Fn(&mut Window, &mut App)>;
type ClearHandler = Rc<dyn Fn(&mut App)>;
type CopyCallback = Rc<dyn Fn(&mut App) -> String>;
type ContentKeyResolver = Rc<dyn Fn(Point<Pixels>, &App) -> Option<TextSelectionContentKey>>;

/// Notifications emitted by a text-selection participant.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum TextSelectionEvent {
    /// The participant's window-selection projection changed.
    SelectionChanged(Option<TextSelectionSnapshot>),
    /// The active drag requests vertical auto-scroll, or `None` to stop.
    AutoScroll(Option<Pixels>),
    /// Window selection cleared the participant's participant-local state.
    Cleared,
    /// The touch selection the participant takes part in changed: it
    /// appeared, its ends moved, a handle drag began or ended, or it went
    /// away. The participant paints the handles and lays their hitboxes out
    /// from the ends it painted last frame, so it renders once more.
    TouchSelectionChanged,
}

struct CopyItem {
    document_order: u64,
    callback: Option<CopyCallback>,
    fallback: String,
}

fn resolve_copy_items(mut items: Vec<CopyItem>, cx: &mut App) -> String {
    items.sort_by_key(|item| item.document_order);
    items
        .into_iter()
        .map(|item| {
            item.callback
                .map(|callback| callback(cx))
                .unwrap_or(item.fallback)
        })
        .filter(|text| !text.trim().is_empty())
        .collect::<Vec<_>>()
        .join("\n")
}

fn dispatch_clear_handlers(handlers: Vec<ClearHandler>, cx: &mut App) {
    for handler in handlers {
        handler(cx);
    }
}

fn clear_departed_participants(
    participants: Vec<Entity<SelectableTextState>>,
    cx: &mut App,
) -> Vec<ClearHandler> {
    participants
        .into_iter()
        .filter_map(|participant| {
            participant
                .read(cx)
                .has_selection_to_clear()
                .then(|| participant.update(cx, |state, cx| state.clear_state(cx)))
                .flatten()
        })
        .collect()
}

struct SelectableTextState {
    fallback_copy_text: String,
    window_selection: RefCell<Option<WeakEntity<WindowSelectionState>>>,
    /// The selected text as the participant last painted it. Painting
    /// projects it, which is not a change of the participant.
    projected_copy_text: RefCell<Option<String>>,
    /// The participant's text as it last painted it, for hit testing.
    runs: RefCell<Vec<TextSelectionRun>>,
    local_selection: bool,
    snapshot: Option<TextSelectionSnapshot>,
    on_focus: Option<FocusCallback>,
    clear: Option<ClearHandler>,
    copy: Option<CopyCallback>,
    content_key_resolver: Option<ContentKeyResolver>,
}

impl EventEmitter<TextSelectionEvent> for SelectableTextState {}

impl SelectableTextState {
    fn new(fallback_copy_text: impl Into<String>) -> Self {
        Self {
            fallback_copy_text: fallback_copy_text.into(),
            window_selection: RefCell::new(None),
            projected_copy_text: RefCell::new(None),
            runs: RefCell::new(Vec::new()),
            local_selection: false,
            snapshot: None,
            on_focus: None,
            clear: None,
            copy: None,
            content_key_resolver: None,
        }
    }

    /// The current geometry selection snapshot for this participant.
    fn snapshot(&self) -> Option<TextSelectionSnapshot> {
        self.snapshot
    }

    /// Sets the text copied by this participant when it participates in selection.
    fn set_fallback_copy_text(&mut self, text: impl Into<String>) {
        self.fallback_copy_text = text.into();
        *self.projected_copy_text.get_mut() = None;
    }

    /// Marks participant-local selection (for example select-all) as active.
    fn set_local_selection(&mut self, active: bool) {
        self.local_selection = active;
    }

    /// Projects this participant's current snapshot onto plain-text runs and caches
    /// their selected substrings for the window selection query.
    ///
    /// Call this once per painted run. A snapshot change or
    /// Clearing window selection invalidates the cache immediately, so copy
    /// never returns text from a previous projection while waiting to repaint.
    fn update_runs(&self, runs: &[TextSelectionRun]) -> TextSelectionProjection {
        *self.runs.borrow_mut() = runs.to_vec();
        let states = project_ranges(self.snapshot, runs);
        let mut selected_runs = runs
            .iter()
            .zip(states.ranges())
            .enumerate()
            .filter_map(|(index, (run, state))| {
                state.as_ref().map(|range| {
                    debug_assert!(run.text.is_char_boundary(range.start));
                    debug_assert!(run.text.is_char_boundary(range.end));
                    (
                        run.document_order,
                        index,
                        run.text[range.clone()].to_string(),
                    )
                })
            })
            .collect::<Vec<_>>();
        selected_runs.sort_by_key(|(order, index, _)| (*order, *index));
        *self.projected_copy_text.borrow_mut() =
            Some(selected_runs.into_iter().map(|(_, _, text)| text).collect());
        states
    }

    /// Installs the callback which focuses the participant when a drag begins in it.
    fn set_focus_handler(&mut self, callback: impl Fn(&mut Window, &mut App) + 'static) {
        self.on_focus = Some(Rc::new(callback));
    }

    fn clear_with(&mut self, callback: impl Fn(&mut App) + 'static) {
        self.clear = Some(Rc::new(callback));
    }

    /// Installs a participant-specific copy projection.
    fn copy_with(&mut self, callback: impl Fn(&mut App) -> String + 'static) {
        self.copy = Some(Rc::new(callback));
    }

    /// Installs a participant-specific lookup for stable virtualized content keys.
    fn resolve_content_key_with(
        &mut self,
        callback: impl Fn(Point<Pixels>, &App) -> Option<TextSelectionContentKey> + 'static,
    ) {
        self.content_key_resolver = Some(Rc::new(callback));
    }

    fn set_snapshot_quietly(&mut self, snapshot: Option<TextSelectionSnapshot>) -> bool {
        if self.snapshot == snapshot {
            return false;
        }
        self.snapshot = snapshot;
        *self.projected_copy_text.get_mut() = None;
        true
    }

    fn set_snapshot(&mut self, snapshot: Option<TextSelectionSnapshot>, cx: &mut Context<Self>) {
        if self.set_snapshot_quietly(snapshot) {
            cx.emit(TextSelectionEvent::SelectionChanged(snapshot));
        }
    }

    /// Whether clearing the participant would change anything: it is part
    /// of the window selection, or selected on its own.
    fn has_selection_to_clear(&self) -> bool {
        self.snapshot.is_some() || self.local_selection
    }

    fn clear_state(&mut self, cx: &mut Context<Self>) -> Option<ClearHandler> {
        self.snapshot = None;
        *self.projected_copy_text.get_mut() = None;
        self.local_selection = false;
        cx.emit(TextSelectionEvent::Cleared);
        cx.emit(TextSelectionEvent::SelectionChanged(None));
        self.clear.clone()
    }

    fn set_auto_scroll(&self, delta: Option<Pixels>, cx: &mut Context<Self>) {
        cx.emit(TextSelectionEvent::AutoScroll(delta));
    }

    fn focus(&self, window: &mut Window, cx: &mut App) {
        if let Some(callback) = self.on_focus.clone() {
            window.defer(cx, move |window, cx| callback(window, cx));
        }
    }

    fn copy_item(&self, document_order: u64) -> Option<CopyItem> {
        (self.snapshot.is_some() || self.local_selection).then(|| CopyItem {
            document_order,
            callback: self.copy.clone(),
            fallback: self
                .projected_copy_text
                .borrow()
                .clone()
                .unwrap_or_else(|| self.fallback_copy_text.clone()),
        })
    }
}

/// The touch handles a participant laid out for a frame, with their hitboxes.
#[derive(Default)]
pub struct TouchHandleLayout {
    hitboxes: Vec<(SelectionEdge, Hitbox)>,
}

/// A stable, participant-neutral handle for text that participates in window selection.
#[derive(Clone)]
pub struct TextSelectionHandle(Entity<SelectableTextState>);

impl TextSelectionHandle {
    /// Creates a selection participant handle with fallback text for copying.
    pub fn new(fallback_copy_text: impl Into<String>, cx: &mut App) -> Self {
        Self(cx.new(|_| SelectableTextState::new(fallback_copy_text)))
    }

    /// Returns this participant's stable identity.
    pub fn entity_id(&self) -> EntityId {
        self.0.entity_id()
    }

    /// Returns the current geometry selection snapshot for this participant.
    pub fn snapshot(&self, cx: &App) -> Option<TextSelectionSnapshot> {
        self.0.read(cx).snapshot()
    }

    /// Records the anchor cell during prepaint, before any participant paints.
    pub(crate) fn record_table_cell(&self, bounds: Bounds<Pixels>, cx: &App) {
        let Some(state) = self.window_selection(cx) else {
            return;
        };
        let state = state.read(cx);
        if state.touch_select_all {
            return;
        }
        let Some(snapshot) = self.snapshot(cx) else {
            return;
        };
        if snapshot.anchor().entity_id() == Some(self.entity_id())
            && snapshot
                .window_points()
                .is_some_and(|points| bounds.contains(&points.anchor()))
        {
            state
                .table_cell_anchor
                .set(Some((snapshot.anchor(), bounds)));
        }
    }

    /// The current gesture's anchor cell, shared only by participants in its window.
    pub(crate) fn table_cell_selection(&self, cx: &App) -> Option<Bounds<Pixels>> {
        let state = self.window_selection(cx)?;
        let state = state.read(cx);
        if state.touch_select_all {
            return None;
        }
        let (anchor, bounds) = state.table_cell_anchor.get()?;
        (self.snapshot(cx)?.anchor() == anchor).then_some(bounds)
    }

    /// Retires an anchor projection when its participant replaces its content.
    pub(crate) fn clear_table_cell_selection(&self, cx: &App) {
        if let Some(state) = self.window_selection(cx) {
            let state = state.read(cx);
            if state
                .table_cell_anchor
                .get()
                .is_some_and(|(endpoint, _)| endpoint.entity_id() == Some(self.entity_id()))
            {
                state.table_cell_anchor.set(None);
            }
        }
    }

    fn window_selection(&self, cx: &App) -> Option<Entity<WindowSelectionState>> {
        self.0
            .read(cx)
            .window_selection
            .borrow()
            .as_ref()?
            .upgrade()
    }

    /// Sets the fallback text copied while this participant participates.
    pub fn set_fallback_copy_text(&self, text: impl Into<String>, cx: &mut App) {
        self.0
            .update(cx, |state, _| state.set_fallback_copy_text(text));
    }

    /// Marks participant-local selection, such as select-all, as active.
    pub fn set_local_selection(&self, active: bool, cx: &mut App) {
        self.0
            .update(cx, |state, _| state.set_local_selection(active));
    }

    /// Returns whether participant-local selection is active.
    pub fn has_local_selection(&self, cx: &App) -> bool {
        self.0.read(cx).local_selection
    }

    /// Registers this participant and its geometry for the current frame.
    pub fn register(
        &self,
        mut registration: TextSelectionRegistration,
        window: &mut Window,
        cx: &mut App,
    ) {
        if let Some(scope) = current_text_selection_scope(window.window_handle().window_id(), cx) {
            registration.scope = scope;
        }
        let Some(state) = WindowSelectionState::existing(window, cx) else {
            return;
        };
        *self.0.read(cx).window_selection.borrow_mut() = Some(state.downgrade());
        state.read(cx).register_quietly(self, registration);
        let snapshot = state.read(cx).participant_snapshot(self.entity_id());
        if self.snapshot(cx) != snapshot {
            // Plain text projects its runs immediately after registering.
            // Rich text may already have painted, so notify after the frame
            // as well, when another draw can actually be scheduled.
            self.0.update(cx, |participant, _| {
                participant.set_snapshot_quietly(snapshot);
            });
            state
                .read(cx)
                .draw_changed
                .borrow_mut()
                .insert(self.entity_id(), self.downgrade());
        }
        schedule_selection_frame(&state, window, cx);
    }

    /// Projects the current snapshot onto plain-text runs and caches their copy text.
    pub fn update_runs(&self, runs: &[TextSelectionRun], cx: &mut App) -> TextSelectionProjection {
        self.0.read(cx).update_runs(runs)
    }

    /// The projected text this participant adds to the window's selected
    /// text, or `None` when it adds none or copies through its own callback.
    pub(crate) fn projected_copy_text(&self, cx: &App) -> Option<String> {
        self.0
            .read(cx)
            .copy_item(0)
            .filter(|item| item.callback.is_none())
            .map(|item| item.fallback)
    }

    // Rich text renders its own selection; retain geometry only for word hit testing.
    pub(crate) fn set_hit_test_runs(&self, runs: &[TextSelectionRun], cx: &mut App) {
        *self.0.read(cx).runs.borrow_mut() = runs.to_vec();
    }

    /// Lets a drag from a double or triple click that this participant
    /// selected for itself, from the caret `start` to the caret `end` in
    /// window coordinates, extend the selection by the same unit through the
    /// window selection, as a shift-click after it does.
    pub(crate) fn hold_multi_click(
        &self,
        start: Bounds<Pixels>,
        end: Bounds<Pixels>,
        click_count: usize,
        cx: &mut App,
    ) {
        let Some(state) = self.window_selection(cx) else {
            return;
        };
        state.update(cx, |state, cx| {
            if let Some(unit) = state.unit_of(&self.0, start, end, click_count, cx) {
                state.hold_unit(unit, cx);
            }
        });
    }

    /// Subscribes to participant selection notifications.
    pub fn subscribe(
        &self,
        mut callback: impl FnMut(&TextSelectionEvent, &mut App) + 'static,
        cx: &mut App,
    ) -> Subscription {
        cx.subscribe(&self.0, move |_, event, cx| callback(event, cx))
    }

    /// Subscribes `window` to refresh whenever this participant's selection changes.
    #[must_use = "retain the subscription or explicitly detach it"]
    pub fn refresh_window_on_change(&self, window: &Window, cx: &mut App) -> Subscription {
        let window = window.window_handle();
        self.subscribe(
            move |event, cx| {
                if matches!(event, TextSelectionEvent::SelectionChanged(_)) {
                    _ = window.update(cx, |_, window, _| window.refresh());
                }
            },
            cx,
        )
    }

    /// Sets the callback which focuses the participant when a drag begins in it.
    pub fn focus_with(&self, callback: impl Fn(&mut Window, &mut App) + 'static, cx: &mut App) {
        self.0
            .update(cx, |state, _| state.set_focus_handler(callback));
    }

    /// Sets the synchronous participant cleanup command used by window clear.
    pub fn clear_with(&self, callback: impl Fn(&mut App) + 'static, cx: &mut App) {
        self.0.update(cx, |state, _| state.clear_with(callback));
    }

    /// Sets a participant-specific copy projection.
    pub fn copy_with(&self, callback: impl Fn(&mut App) -> String + 'static, cx: &mut App) {
        self.0.update(cx, |state, _| state.copy_with(callback));
    }

    /// Lays out the touch handles at the ends of this participant's
    /// selection, as they were painted last frame, and gives each a hitbox
    /// where the finger takes it. Call during the participant's prepaint;
    /// hand the result to [`Self::paint_touch_handles`].
    pub fn prepaint_touch_handles(&self, window: &mut Window, cx: &App) -> TouchHandleLayout {
        let Some(state) = WindowSelectionState::existing(window, cx) else {
            return TouchHandleLayout::default();
        };
        let hitboxes = state
            .read(cx)
            .touch_handles_of(self.entity_id())
            .into_iter()
            .map(|(edge, caret)| {
                let hitbox = window.insert_hitbox(
                    TouchHandle::hit_bounds(edge, caret),
                    HitboxBehavior::BlockMouse,
                );
                (edge, hitbox)
            })
            .collect();
        TouchHandleLayout { hitboxes }
    }

    /// Paints the touch handles at the ends of this participant's selection,
    /// in `color`, where the participant is in the paint order — so whatever
    /// is drawn over the text is drawn over its handles too. Call at the end
    /// of the participant's paint, after [`Self::register`] for the frame.
    ///
    /// The handles take the finger's drag from there; Base moves the
    /// selection with it.
    pub fn paint_touch_handles(
        &self,
        layout: &TouchHandleLayout,
        color: Hsla,
        window: &mut Window,
        cx: &mut App,
    ) {
        let Some(state) = WindowSelectionState::existing(window, cx) else {
            return;
        };
        for (edge, caret) in state.read(cx).touch_handles_of(self.entity_id()) {
            TouchHandle::paint(edge, caret, color, window);
        }
        let bounds: Vec<Bounds<Pixels>> = layout
            .hitboxes
            .iter()
            .map(|(_, hitbox)| hitbox.bounds)
            .collect();
        if !state.read(cx).handles_painted_at(self.entity_id(), &bounds) {
            state.update(cx, |state, _| {
                state.register_handles(self.entity_id(), bounds)
            });
        }
        for (edge, hitbox) in &layout.hitboxes {
            let edge = *edge;
            // Touch: the drag is offered on the first touch, before it can
            // become a tap, a long press or a pan.
            window.on_mouse_event({
                let hitbox = hitbox.clone();
                let state = state.downgrade();
                move |event: &TouchDragEvent, phase, window, cx| {
                    if !phase.bubble()
                        || event.phase != TouchPhase::Started
                        || window.default_prevented()
                        || !hitbox.is_hovered(window)
                    {
                        return;
                    }
                    let Some(state) = state.upgrade() else {
                        return;
                    };
                    window.prevent_default();
                    cx.stop_propagation();
                    state.update(cx, |state, cx| {
                        state.begin_edge_drag(edge, event.position, window, cx)
                    });
                    WindowSelectionState::resolve_content_keys(&state, cx);
                }
            });
            // Mouse: the same drag for a pointer.
            window.on_mouse_event({
                let hitbox = hitbox.clone();
                let state = state.downgrade();
                move |event: &MouseDownEvent, phase, window, cx| {
                    if !phase.bubble()
                        || event.button != MouseButton::Left
                        || !hitbox.is_hovered(window)
                    {
                        return;
                    }
                    let Some(state) = state.upgrade() else {
                        return;
                    };
                    cx.stop_propagation();
                    state.update(cx, |state, cx| {
                        state.begin_edge_drag(edge, event.position, window, cx)
                    });
                    WindowSelectionState::resolve_content_keys(&state, cx);
                }
            });
        }
    }

    /// Sets a participant-specific lookup for stable virtualized content keys.
    pub fn resolve_content_key_with(
        &self,
        callback: impl Fn(Point<Pixels>, &App) -> Option<TextSelectionContentKey> + 'static,
        cx: &mut App,
    ) {
        self.0
            .update(cx, |state, _| state.resolve_content_key_with(callback));
    }

    fn downgrade(&self) -> WeakEntity<SelectableTextState> {
        self.0.downgrade()
    }
}

#[derive(Clone)]
struct ParticipantRegistration {
    participant: WeakEntity<SelectableTextState>,
    registration: Rc<TextSelectionRegistration>,
    document_order: u64,
    generation: u64,
}

#[derive(Clone)]
struct SelectionEndpoint {
    participant: Option<WeakEntity<SelectableTextState>>,
    point: Point<Pixels>,
    inside: bool,
    inside_text: bool,
    content_key: Option<TextSelectionContentKey>,
    content_key_resolver: Option<(ContentKeyResolver, Point<Pixels>)>,
}

impl SelectionEndpoint {
    fn snapshot(&self) -> TextSelectionEndpoint {
        let snapshot = TextSelectionEndpoint::new(self.entity_id(), self.point);
        if let Some(content_key) = self.content_key {
            snapshot.with_content_key(content_key)
        } else {
            snapshot
        }
    }

    fn resolve(
        &self,
        participants: &HashMap<EntityId, ParticipantRegistration>,
    ) -> Option<Point<Pixels>> {
        let participant = self.participant.as_ref()?;
        let registration = participants.get(&participant.entity_id())?;
        participant.upgrade()?;
        Some(
            self.point
                + registration.registration.scroll_offset
                + registration.registration.bounds.origin,
        )
    }

    fn entity_id(&self) -> Option<EntityId> {
        self.participant
            .as_ref()
            .map(|participant| participant.entity_id())
    }

    /// This endpoint moved by `delta` within its participant, its content
    /// key to be resolved again.
    fn moved(&self, delta: Point<Pixels>) -> Self {
        let point = self.point + delta;
        Self {
            point,
            content_key: None,
            content_key_resolver: self
                .content_key_resolver
                .clone()
                .map(|(resolver, _)| (resolver, point)),
            ..self.clone()
        }
    }
}

/// The word or line a double or triple click selected. A drag from the
/// click, and a shift-click after it, extend the selection by the same unit,
/// and it stays selected whichever way they go.
#[derive(Clone)]
struct SelectionUnit {
    click_count: usize,
    start: SelectionEndpoint,
    end: SelectionEndpoint,
    /// The heights of the rows the unit starts and ends on.
    row_heights: (Pixels, Pixels),
}

/// What a long press left behind: the handles and the edit menu.
///
/// The presentation layer draws both and reports their bounds each frame, so
/// that a press on a handle or a menu item is not taken for a press on the
/// text underneath, which would clear the very selection they belong to.
#[derive(Default)]
struct TouchSelection {
    /// The current selection was made by touch and carries handles.
    active: bool,
    menu_open: bool,
    drag: Option<EdgeDrag>,
    /// Where the menu was painted this frame, and the frame before: a press
    /// arrives between frames, and the surfaces may have moved in the one
    /// that has not painted yet.
    ui_bounds: Vec<Bounds<Pixels>>,
    previous_ui_bounds: Vec<Bounds<Pixels>>,
    /// Where each participant last painted its handles. A participant drawn
    /// from an earlier frame, which does not paint again, still shows its
    /// handles where it painted them; one that paints again replaces them.
    handle_bounds: HashMap<EntityId, Vec<Bounds<Pixels>>>,
    /// The ends as last laid out: `(start, end, start_visible, end_visible)`.
    /// A frame in which no participant paints a selection — the cursor sits
    /// between two characters mid-drag — would otherwise lose the handle the
    /// finger holds, and with it the rest of the drag.
    last_edges: std::cell::Cell<Option<(Bounds<Pixels>, Bounds<Pixels>, bool, bool)>>,
}

impl TouchSelection {
    fn covers(&self, position: Point<Pixels>) -> bool {
        self.active
            && self
                .ui_bounds
                .iter()
                .chain(&self.previous_ui_bounds)
                .chain(self.handle_bounds.values().flatten())
                .any(|bounds| bounds.contains(&position))
    }

    /// Whether the handles or the menu were painted in either of the last
    /// two frames, which [`Self::begin_frame`] has to shift.
    fn painted_any(&self) -> bool {
        !self.ui_bounds.is_empty() || !self.previous_ui_bounds.is_empty()
    }

    /// A new frame begins: what was painted last frame is kept one frame more.
    fn begin_frame(&mut self) {
        self.previous_ui_bounds = std::mem::take(&mut self.ui_bounds);
    }

    /// Drops the handles and the menu; returns whether there were any.
    fn reset(&mut self) -> bool {
        let had = self.active;
        self.handle_bounds.clear();
        self.active = false;
        self.menu_open = false;
        self.drag = None;
        self.last_edges.set(None);
        had
    }
}

/// Automatic order is committed only after all live TextViews have painted.
/// A partial frame is a subsequence of that order, not a new document.
#[derive(Default)]
struct ParticipantPaintOrder {
    next: u64,
    painted: Vec<EntityId>,
    last: Option<u64>,
    dirty: bool,
    refresh_requested: bool,
}

/// Window-local generic text-selection state.
#[derive(Default)]
struct WindowSelectionState {
    /// What each participant painted this frame, or last painted. Painting
    /// reports it without changing the selection: see
    /// [`WindowSelectionState::register_quietly`].
    participants: RefCell<HashMap<EntityId, ParticipantRegistration>>,
    active_scope: TextSelectionScopeId,
    /// A prepaint projection owned by this window and reset with its selection.
    table_cell_anchor: Cell<Option<(TextSelectionEndpoint, Bounds<Pixels>)>>,
    touch_select_all: bool,
    anchor: Option<SelectionEndpoint>,
    cursor: Option<SelectionEndpoint>,
    pending_extension_anchor: Option<SelectionEndpoint>,
    unit: Option<SelectionUnit>,
    is_selecting: bool,
    did_hit_text: bool,
    frame_generation: Cell<u64>,
    finish_frame_scheduled: Cell<bool>,
    layer_painted: Cell<bool>,
    paint_order: RefCell<ParticipantPaintOrder>,
    /// Participants given an updated snapshot while drawing. Their observers
    /// run after the frame, including adapters which registered after paint.
    draw_changed: RefCell<HashMap<EntityId, WeakEntity<SelectableTextState>>>,
    refresh_held_cursor: Cell<bool>,
    touch_edges_moved: Cell<bool>,
    #[cfg(test)]
    snapshot_visits: Cell<usize>,
    mouse_down_prepared: bool,
    auto_scroll: AutoScroll,
    /// Where the anchor's text was when the last synthetic wheel went out,
    /// and how many went out without moving it. A container at its end
    /// cannot scroll further; pushing it on would only make one that
    /// bounces stretch and snap back on every tick.
    auto_scroll_stall: (Option<(Bounds<Pixels>, Point<Pixels>)>, u8),
    touch: TouchSelection,
    /// This entity, so that touch changes can notify observers from paths that
    /// only hold an [`App`].
    entity_id: Option<EntityId>,
}

impl WindowSelectionState {
    fn resolve_content_keys(state: &Entity<Self>, cx: &mut App) {
        let pending = state.read_with(cx, |state, _| {
            [
                state
                    .anchor
                    .as_ref()
                    .and_then(|endpoint| endpoint.content_key_resolver.clone()),
                state
                    .cursor
                    .as_ref()
                    .and_then(|endpoint| endpoint.content_key_resolver.clone()),
            ]
        });
        // Nothing to resolve and no selection to publish: an event that
        // changed nothing does not change the state either.
        if pending.iter().all(Option::is_none) && !state.read(cx).is_active() {
            return;
        }
        let resolved =
            pending.map(|pending| pending.and_then(|(callback, point)| callback(point, cx)));
        state.update(cx, |state, cx| {
            if let (Some(endpoint), Some(key)) = (state.anchor.as_mut(), resolved[0]) {
                endpoint.content_key = Some(key);
                endpoint.content_key_resolver = None;
            }
            if let (Some(endpoint), Some(key)) = (state.cursor.as_mut(), resolved[1]) {
                endpoint.content_key = Some(key);
                endpoint.content_key_resolver = None;
            }
            state.publish_snapshots(cx);
        });
    }
    fn acquire(window_id: gpui::WindowId, cx: &mut App) -> Entity<Self> {
        if !cx.has_global::<SelectionStateRegistry>() {
            cx.set_global(SelectionStateRegistry::default());
        }
        if let Some(state) = cx
            .global::<SelectionStateRegistry>()
            .0
            .get(&window_id)
            .and_then(WeakEntity::upgrade)
        {
            return state;
        }

        let active_scope = if cx.has_global::<PendingTextSelectionScopes>() {
            cx.global_mut::<PendingTextSelectionScopes>()
                .0
                .remove(&window_id)
                .unwrap_or_default()
        } else {
            TextSelectionScopeId::default()
        };

        let state = cx.new(move |cx| {
            let entity_id = cx.entity_id();
            cx.on_release(move |state: &mut WindowSelectionState, cx| {
                let handlers = state.clear_state(cx);
                if cx.has_global::<SelectionStateRegistry>() {
                    let registry = &mut cx.global_mut::<SelectionStateRegistry>().0;
                    if registry
                        .get(&window_id)
                        .is_some_and(|state| state.entity_id() == entity_id)
                    {
                        registry.remove(&window_id);
                    }
                }
                if !handlers.is_empty() {
                    cx.defer(move |cx| dispatch_clear_handlers(handlers, cx));
                }
            })
            .detach();
            Self {
                active_scope,
                entity_id: Some(entity_id),
                ..Self::default()
            }
        });
        cx.global_mut::<SelectionStateRegistry>()
            .0
            .insert(window_id, state.downgrade());
        state
    }

    #[cfg(test)]
    fn ensure(window: &Window, cx: &mut App) -> Entity<Self> {
        Self::acquire(window.window_handle().window_id(), cx)
    }

    fn existing(window: &Window, cx: &App) -> Option<Entity<Self>> {
        if !cx.has_global::<SelectionStateRegistry>() {
            return None;
        }
        cx.global::<SelectionStateRegistry>()
            .0
            .get(&window.window_handle().window_id())
            .and_then(WeakEntity::upgrade)
    }

    /// Updates the active scope. Participants from other scopes cannot participate.
    #[cfg(test)]
    fn set_active_scope(&mut self, scope: TextSelectionScopeId, cx: &mut App) {
        let handlers = self.set_active_scope_state(scope, cx);
        dispatch_clear_handlers(handlers, cx);
    }

    fn set_active_scope_state(
        &mut self,
        scope: TextSelectionScopeId,
        cx: &mut App,
    ) -> Vec<ClearHandler> {
        if self.active_scope == scope {
            return Vec::new();
        }
        let handlers = self.clear_state(cx);
        self.active_scope = scope;
        self.publish_snapshots(cx);
        handlers
    }

    /// Sweeps participants after a rendered frame has completed.
    ///
    /// Registrations are stamped with the current generation while any sibling
    /// is painting. Sweeping only after paint makes registration independent of
    /// whether a participant or the lifecycle element paints first.
    ///
    /// A missed generation alone does not mean the participant left the window:
    /// a cached view replays its recorded frame, painting the same text at the
    /// same place without running any of its elements. Such a participant keeps
    /// the registration it last reported, which still describes what is on
    /// screen; only one whose element GPUI has dropped is swept.
    ///
    /// Removing an endpoint also retires the window's gesture. Clearing only
    /// the participant snapshot would restore that selection if its retained
    /// entity were registered again.
    #[cfg(test)]
    fn finish_frame(&mut self, cx: &mut App) -> Vec<ClearHandler> {
        let stale = self.stale_participants(true);
        let mut handlers = if self.endpoint_departed(&stale) {
            self.clear_state(cx)
        } else {
            Vec::new()
        };
        let departed = self.remove_stale_participants(stale);
        handlers.extend(clear_departed_participants(departed, cx));
        self.finish_registrations();
        self.publish_snapshots(cx);
        handlers
    }

    fn stale_participants(
        &self,
        full_frame: bool,
    ) -> Vec<(EntityId, WeakEntity<SelectableTextState>)> {
        let generation = self.frame_generation.get();
        self.participants
            .borrow()
            .iter()
            .filter_map(|(id, participant)| {
                let registration = &participant.registration;
                let missed_frame = participant.generation != generation
                    && !registration.is_rendered()
                    && (full_frame || registration.rendered.is_some());
                (missed_frame || participant.participant.upgrade().is_none())
                    .then(|| (*id, participant.participant.clone()))
            })
            .collect()
    }

    fn endpoint_departed(&self, stale: &[(EntityId, WeakEntity<SelectableTextState>)]) -> bool {
        stale.iter().any(|(id, _)| {
            [
                self.anchor.as_ref(),
                self.cursor.as_ref(),
                self.pending_extension_anchor.as_ref(),
            ]
            .into_iter()
            .flatten()
            .chain(self.unit.iter().flat_map(|unit| [&unit.start, &unit.end]))
            .any(|endpoint| endpoint.entity_id() == Some(*id))
        })
    }

    fn remove_stale_participants(
        &self,
        stale: Vec<(EntityId, WeakEntity<SelectableTextState>)>,
    ) -> Vec<Entity<SelectableTextState>> {
        let mut participants = self.participants.borrow_mut();
        stale
            .into_iter()
            .filter_map(|(id, participant)| {
                participants.remove(&id);
                participant.upgrade()
            })
            .collect()
    }

    /// Finishes bookkeeping through a read of the window entity. Updating it
    /// would invalidate every retained view that registered a participant.
    /// Returns whether one complete frame is needed to recover paint order.
    fn finish_registrations(&self) -> bool {
        let generation = self.frame_generation.get();
        let mut participants = self.participants.borrow_mut();
        let mut order = self.paint_order.borrow_mut();
        let complete = participants.values().all(|participant| {
            !participant.registration.paint_order || participant.generation == generation
        });
        let refresh = if complete {
            let mut next = 0;
            for id in order.painted.drain(..) {
                if let Some(participant) = participants.get_mut(&id)
                    && participant.registration.paint_order
                {
                    next += 1;
                    participant.document_order = next;
                }
            }
            order.next = next;
            order.dirty = false;
            order.refresh_requested = false;
            false
        } else {
            let refresh = order.dirty && !order.refresh_requested;
            order.refresh_requested |= refresh;
            order.painted.clear();
            refresh
        };
        order.last = None;
        self.finish_frame_scheduled.set(false);
        self.layer_painted.set(false);
        self.frame_generation.set(generation.wrapping_add(1));
        refresh
    }

    fn schedule_finish_frame(&self) -> bool {
        !self.finish_frame_scheduled.replace(true)
    }

    /// Whether there is a selection, or a gesture or touch selection that
    /// may make one: what painting the participants reports can change it.
    fn is_active(&self) -> bool {
        self.anchor.is_some()
            || self.cursor.is_some()
            || self.pending_extension_anchor.is_some()
            || self.is_selecting
            || self.refresh_held_cursor.get()
            || self.touch.active
    }

    /// Records one participant in constant time, even during a selection.
    /// Full publication belongs to input handling or the end of the frame,
    /// never to each participant's draw callback.
    fn register_quietly(
        &self,
        selection: &TextSelectionHandle,
        registration: TextSelectionRegistration,
    ) {
        let mut participants = self.participants.borrow_mut();
        let previous = participants.get(&selection.entity_id());
        if self.is_selecting
            && registration.self_scroll
            && self.anchor.as_ref().and_then(SelectionEndpoint::entity_id)
                == Some(selection.entity_id())
            && previous.is_some_and(|previous| {
                previous.registration.scroll_offset != registration.scroll_offset
                    || previous.registration.bounds != registration.bounds
            })
        {
            self.refresh_held_cursor.set(true);
        }
        // The handles sit on the painted ends; when those moved — a scroll, a
        // reflow, a select-all — whoever draws the handles needs to know.
        if self.touch.active
            && previous.is_none_or(|previous| {
                previous.registration.selection_edges != registration.selection_edges
            })
        {
            self.touch_edges_moved.set(true);
        }
        let generation = self.frame_generation.get();
        let document_order = if registration.paint_order {
            let mut order = self.paint_order.borrow_mut();
            let previous = previous.filter(|previous| previous.registration.paint_order);
            let number = previous.map_or_else(
                || {
                    order.next += 1;
                    order.dirty = true;
                    order.next
                },
                |previous| previous.document_order,
            );
            // Reparenting an element changes its keyed marker and may move it
            // among retained siblings. Geometry alone is not a topology change:
            // scrolling an ancestor moves its text without changing its order.
            if previous.is_some_and(|previous| {
                previous
                    .registration
                    .rendered
                    .as_ref()
                    .map(|marker| marker.entity_id())
                    != registration
                        .rendered
                        .as_ref()
                        .map(|marker| marker.entity_id())
            }) {
                order.dirty = true;
            }
            let inverted = order.last.is_some_and(|last| last > number);
            order.dirty |= inverted;
            order.last = Some(number);
            // As with geometry, a handle painted twice takes its last position.
            order.painted.push(selection.entity_id());
            number
        } else {
            registration.document_order
        };
        participants.insert(
            selection.entity_id(),
            ParticipantRegistration {
                participant: selection.downgrade(),
                registration: Rc::new(registration),
                document_order,
                generation,
            },
        );
    }

    #[cfg(test)]
    fn register_participant(
        &mut self,
        selection: TextSelectionHandle,
        registration: TextSelectionRegistration,
        cx: &mut App,
    ) {
        self.register_quietly(&selection, registration);
        self.publish_snapshots(cx);
    }

    /// Starts a selection gesture using bounds hit testing (useful to adapters/tests).
    #[cfg(test)]
    fn begin(&mut self, position: Point<Pixels>, extend: bool, cx: &mut App) {
        self.begin_impl(position, extend, false, None, cx);
    }

    /// Updates the current gesture using bounds hit testing.
    #[cfg(test)]
    fn update(&mut self, position: Point<Pixels>, cx: &mut App) {
        self.update_impl(position, None, cx);
    }

    /// Ends the current gesture and keeps its selection visible.
    pub fn end(&mut self, cx: &mut App) {
        self.pending_extension_anchor = None;
        if !self.is_selecting {
            return;
        }
        self.is_selecting = false;
        if !self.did_hit_text {
            self.anchor = None;
            self.cursor = None;
        }
        self.stop_anchor_auto_scroll(cx);
        self.publish_snapshots(cx);
    }

    /// Clears both window selection and every participant's local selection.
    pub fn clear(&mut self, cx: &mut App) {
        let handlers = self.clear_state(cx);
        dispatch_clear_handlers(handlers, cx);
    }

    fn clear_state(&mut self, cx: &mut App) -> Vec<ClearHandler> {
        self.draw_changed.get_mut().clear();
        self.table_cell_anchor.set(None);
        self.touch_select_all = false;
        self.stop_anchor_auto_scroll(cx);
        self.anchor = None;
        self.cursor = None;
        self.pending_extension_anchor = None;
        self.unit = None;
        self.is_selecting = false;
        self.did_hit_text = false;
        if self.touch.reset() {
            self.touch_changed(cx);
        }
        self.prune_dead_participants();
        self.participants
            .borrow()
            .values()
            .filter_map(|registration| registration.participant.upgrade())
            .filter_map(|participant| participant.update(cx, |state, cx| state.clear_state(cx)))
            .collect()
    }

    /// Tells whoever draws the handles and the menu that they changed.
    ///
    /// Deferred, because the change may come from a participant painting its
    /// selection ends: a notification raised inside a draw marks the view
    /// dirty but starts no frame, and the handles would sit where they were
    /// until something else redrew the window.
    ///
    /// The participants in the selection hear it too: they paint the
    /// handles, and lay the handles' hitboxes out from the ends they painted
    /// last frame, so they render once more. A participant under a cached
    /// view would otherwise not, and the next frame would replay this one,
    /// with no hitbox where a handle is.
    fn touch_changed(&self, cx: &mut App) {
        let participants = self
            .participants
            .borrow()
            .values()
            .filter_map(|registration| registration.participant.upgrade())
            .filter(|participant| participant.read(cx).snapshot.is_some())
            .collect::<Vec<_>>();
        let entity_id = self.entity_id;
        cx.defer(move |cx| {
            for participant in participants {
                participant.update(cx, |_, cx| {
                    cx.emit(TextSelectionEvent::TouchSelectionChanged)
                });
            }
            if let Some(entity_id) = entity_id {
                cx.notify(entity_id);
            }
        });
    }

    fn copy_items(&self, cx: &App) -> Vec<CopyItem> {
        self.participants
            .borrow()
            .values()
            .filter_map(|registration| {
                let participant = registration.participant.upgrade()?;
                participant.read(cx).copy_item(registration.document_order)
            })
            .collect()
    }

    #[cfg(test)]
    fn selected_text(&self, cx: &mut App) -> String {
        resolve_copy_items(self.copy_items(cx), cx)
    }

    /// Whether the current endpoints take in at least one character of some
    /// participant's painted text, as opposed to two points with nothing
    /// between them.
    fn selects_text(&self, cx: &App) -> bool {
        self.snapshot().is_some()
            && self.participants.borrow().values().any(|registration| {
                registration
                    .participant
                    .upgrade()
                    .is_some_and(|participant| {
                        let participant = participant.read(cx);
                        project_ranges(participant.snapshot, &participant.runs.borrow())
                            .ranges()
                            .iter()
                            .any(|range| range.as_ref().is_some_and(|range| !range.is_empty()))
                    })
            })
    }

    /// Returns whether a drag or a participant-local selection is active.
    pub fn has_selection(&self, cx: &App) -> bool {
        self.snapshot().is_some()
            || self.participants.borrow().values().any(|registration| {
                registration
                    .participant
                    .upgrade()
                    .is_some_and(|participant| participant.read(cx).local_selection)
            })
    }

    /// Returns the current resolved selection endpoints.
    pub fn snapshot(&self) -> Option<TextSelectionSnapshot> {
        if !self.did_hit_text {
            return None;
        }
        let anchor_endpoint = self.anchor.as_ref()?;
        let cursor_endpoint = self.cursor.as_ref()?;
        let anchor = anchor_endpoint.resolve(&self.participants.borrow())?;
        let cursor = cursor_endpoint.resolve(&self.participants.borrow())?;
        (anchor != cursor).then(|| {
            TextSelectionSnapshot::new(anchor_endpoint.snapshot(), cursor_endpoint.snapshot())
                .with_selecting(self.is_selecting)
                .with_window_points(Some(TextSelectionWindowPoints { anchor, cursor }))
        })
    }

    /// Returns whether a drag is currently in progress.
    #[cfg(test)]
    fn is_selecting(&self) -> bool {
        self.is_selecting
    }

    fn prepare_for_mouse_down(&mut self, extend: bool, cx: &mut App) -> Vec<ClearHandler> {
        let pending_extension_anchor = extend.then(|| self.anchor.clone()).flatten();
        let unit = extend.then(|| self.unit.take()).flatten();
        if !extend {
            self.table_cell_anchor.set(None);
            self.touch_select_all = false;
        }
        self.stop_anchor_auto_scroll(cx);
        self.anchor = None;
        self.cursor = None;
        self.pending_extension_anchor = None;
        self.unit = unit;
        self.is_selecting = false;
        self.did_hit_text = false;
        if self.touch.reset() {
            self.touch_changed(cx);
        }
        self.prune_dead_participants();
        let handlers = self
            .participants
            .borrow()
            .values()
            .filter_map(|registration| registration.participant.upgrade())
            .filter_map(|participant| participant.update(cx, |state, cx| state.clear_state(cx)))
            .collect();
        self.pending_extension_anchor = pending_extension_anchor;
        handlers
    }

    /// The touch selection laid out for its handles and edit menu.
    ///
    /// The ends come from the participants: the first selected character of
    /// the earliest participant in document order and the last of the latest.
    /// A participant whose selection is entirely scrolled away paints no ends,
    /// so the handles disappear with the text they mark.
    fn touch_selection(&self) -> Option<TouchSelectionSnapshot> {
        if !self.touch.active {
            return None;
        }
        // Each end with its owner's viewport: an end scrolled out of its
        // participant gets no handle.
        let mut start: Option<(u64, Bounds<Pixels>, bool)> = None;
        let mut end: Option<(u64, Bounds<Pixels>, bool)> = None;
        for registration in self.participants.borrow().values() {
            let geometry = &registration.registration;
            if geometry.scope != self.active_scope || registration.participant.upgrade().is_none() {
                continue;
            }
            let Some((edge_start, edge_end)) = geometry.selection_edges else {
                continue;
            };
            let order = registration.document_order;
            let viewport = geometry.hitbox.bounds;
            if start.is_none_or(|(best, ..)| order < best) {
                start = Some((order, edge_start, caret_in_view(edge_start, viewport)));
            }
            if end.is_none_or(|(best, ..)| order >= best) {
                end = Some((order, edge_end, caret_in_view(edge_end, viewport)));
            }
        }
        let edges = match (start, end) {
            (Some((_, start, start_visible)), Some((_, end, end_visible))) => {
                let edges = (start, end, start_visible, end_visible);
                self.touch.last_edges.set(Some(edges));
                edges
            }
            _ if self.touch.drag.is_some() => self.touch.last_edges.get()?,
            _ => return None,
        };
        let (start, end, start_visible, end_visible) = edges;
        Some(
            TouchSelectionSnapshot::new(start, end)
                .with_edge_visible(SelectionEdge::Start, start_visible)
                .with_edge_visible(SelectionEdge::End, end_visible)
                .with_menu_open(self.touch.menu_open)
                .with_dragging(self.touch.drag.map(|drag| drag.edge())),
        )
    }

    /// The handles `participant` paints: the start when no participant
    /// earlier in document order has a selection end, the end when none
    /// later has. Participants paint in document order, so a later one that
    /// takes the end over has registered its ends by the time it asks.
    fn touch_handles_of(&self, participant: EntityId) -> Vec<(SelectionEdge, Bounds<Pixels>)> {
        if !self.touch.active {
            return Vec::new();
        }
        let Some(own) = self.participants.borrow().get(&participant).cloned() else {
            return Vec::new();
        };
        let Some((start, end)) = own.registration.selection_edges else {
            return Vec::new();
        };
        if start == end {
            return Vec::new();
        }
        let order = own.document_order;
        let participants = self.participants.borrow();
        let others = participants.iter().filter(|(id, registration)| {
            **id != participant
                && registration.registration.scope == self.active_scope
                && registration.registration.selection_edges.is_some()
                && registration.participant.upgrade().is_some()
        });
        let (mut earlier, mut later) = (false, false);
        for (_, registration) in others {
            let other = registration.document_order;
            earlier |= other < order;
            later |= other > order;
        }
        let viewport = own.registration.hitbox.bounds;
        let mut handles = Vec::with_capacity(2);
        if !earlier && caret_in_view(start, viewport) {
            handles.push((SelectionEdge::Start, start));
        }
        if !later && caret_in_view(end, viewport) {
            handles.push((SelectionEdge::End, end));
        }
        handles
    }

    /// Keeps the selection a long press made, and opens the edit menu over it.
    fn keep_touch_selection(&mut self, cx: &mut App) {
        self.touch.active = self.snapshot().is_some();
        self.touch.menu_open = self.touch.active;
        self.touch.drag = None;
        self.touch_changed(cx);
    }

    /// Records where the menu is painted this frame.
    fn register_touch_ui(&mut self, bounds: Bounds<Pixels>) {
        self.touch.ui_bounds.push(bounds);
    }

    /// Whether `bounds` are where `participant` painted its handles last.
    fn handles_painted_at(&self, participant: EntityId, bounds: &[Bounds<Pixels>]) -> bool {
        self.touch
            .handle_bounds
            .get(&participant)
            .map_or(bounds.is_empty(), |painted| painted == bounds)
    }

    /// Records where `participant` painted its handles, which replace those
    /// it painted before.
    fn register_handles(&mut self, participant: EntityId, bounds: Vec<Bounds<Pixels>>) {
        self.touch.handle_bounds.insert(participant, bounds);
    }

    fn close_edit_menu(&mut self, cx: &mut App) {
        if !self.touch.menu_open {
            return;
        }
        self.touch.menu_open = false;
        self.touch_changed(cx);
    }

    /// The handles follow the text, but the menu would sit over whatever
    /// scrolls underneath it: it steps aside while a finger scrolls and comes
    /// back over the handles once the finger lifts.
    fn edit_menu_on_scroll(&mut self, phase: TouchPhase, cx: &mut App) {
        if !self.touch.active || self.touch.drag.is_some() {
            return;
        }
        match phase {
            TouchPhase::Ended | TouchPhase::Cancelled => {
                if !self.touch.menu_open {
                    self.touch.menu_open = true;
                    self.touch_changed(cx);
                }
            }
            _ => self.close_edit_menu(cx),
        }
    }

    /// Selects all of the participant the touch selection started in.
    ///
    /// This stays a point selection — anchored on the participant's first
    /// line of text, ending on its last — rather than switching the
    /// participant to a local select-all: one selection, painted, reported
    /// and copied the one way, with handles that drag on from its ends.
    fn select_all_touched(&mut self, cx: &mut App) {
        if !self.touch.active {
            return;
        }
        let Some((participant, registration)) = self.anchor_registration() else {
            return;
        };
        // From the participant's text runs, not its painted line bounds:
        // those are clipped to the viewport, and a message taller than the
        // screen would only select what is on it.
        let (anchor, cursor) = {
            let runs = &participant.read(cx).runs.borrow();
            let (Some(first), Some(last)) = (
                runs.iter().min_by_key(|run| run.document_order),
                runs.iter().max_by_key(|run| run.document_order),
            ) else {
                return;
            };
            let (Some(start), Some(end)) = (
                first.layout.position_for_index(0),
                last.layout.position_for_index(last.text.len()),
            ) else {
                return;
            };
            // Just inside the first and the last glyph, mid-line, so both
            // land on text.
            let inset = px(1.);
            (
                point(start.x + inset, start.y + first.layout.line_height() / 2.),
                point(end.x - inset, end.y + last.layout.line_height() / 2.),
            )
        };
        let content_key_resolver = participant.read(cx).content_key_resolver.clone();
        let to_endpoint = |window_point: Point<Pixels>| {
            let content_point =
                window_point - registration.bounds.origin - registration.scroll_offset;
            SelectionEndpoint {
                participant: Some(participant.downgrade()),
                point: content_point,
                inside: true,
                inside_text: true,
                content_key: None,
                content_key_resolver: content_key_resolver
                    .clone()
                    .map(|resolver| (resolver, content_point)),
            }
        };
        self.table_cell_anchor.set(None);
        self.touch_select_all = true;
        self.anchor = Some(to_endpoint(anchor));
        self.cursor = Some(to_endpoint(cursor));
        self.did_hit_text = true;
        self.is_selecting = false;
        self.touch.menu_open = true;
        self.publish_snapshots(cx);
        self.touch_changed(cx);
    }

    /// Starts dragging one end of the touch selection from `finger`.
    ///
    /// The selection is rebuilt from the painted ends, anchored at the end that
    /// stays: a select-all or a word selection becomes an ordinary point
    /// selection which the drag then extends.
    fn begin_edge_drag(
        &mut self,
        edge: SelectionEdge,
        finger: Point<Pixels>,
        window: &mut Window,
        cx: &mut App,
    ) {
        let Some(snapshot) = self.touch_selection() else {
            return;
        };
        let handlers = self.prepare_for_mouse_down(false, cx);
        dispatch_clear_handlers(handlers, cx);
        let held = snapshot.edge(edge.opposite());
        // Just inside the held end, so the anchor lands on the character it
        // marks rather than on the boundary between two participants.
        let nudge = px(1.);
        let anchor_point = match edge {
            SelectionEdge::Start => point(held.left() - nudge, held.center().y),
            SelectionEdge::End => point(held.left() + nudge, held.center().y),
        };
        let anchor = self.endpoint(anchor_point, None, cx);
        let drag = EdgeDrag::begin(edge, snapshot.edge(edge), finger);
        let cursor = self.endpoint(drag.text_position(finger), Some(window), cx);
        self.did_hit_text = anchor.inside_text || cursor.inside_text;
        self.anchor = Some(anchor);
        self.cursor = Some(cursor);
        self.is_selecting = true;
        self.touch.active = true;
        self.touch.menu_open = false;
        self.touch.drag = Some(drag);
        self.publish_snapshots(cx);
        self.touch_changed(cx);
    }

    fn update_edge_drag(&mut self, finger: Point<Pixels>, window: &Window, cx: &mut Context<Self>) {
        let Some(drag) = self.touch.drag else {
            return;
        };
        let before = self.cursor.clone();
        self.update_in_window(drag.text_position(finger), window, cx);
        // A handle never collapses the selection: at the other end it stops,
        // and the finger has to pass that end, onto text, to swap the two.
        if !self.selects_text(cx) {
            self.cursor = before;
            self.publish_snapshots(cx);
            return;
        }
        // Dragging one end past the other swaps them: the cursor now lies
        // before the anchor, so the finger holds what became the start.
        if let Some(points) = self
            .snapshot()
            .and_then(|snapshot| snapshot.window_points())
        {
            let (anchor, cursor) = (points.anchor(), points.cursor());
            let cursor_first = cursor.y < anchor.y || (cursor.y == anchor.y && cursor.x < anchor.x);
            let edge = if cursor_first {
                SelectionEdge::Start
            } else {
                SelectionEdge::End
            };
            if let Some(drag) = self.touch.drag.as_mut() {
                drag.set_edge(edge);
            }
        }
        self.touch_changed(cx);
    }

    fn end_edge_drag(&mut self, cx: &mut App) {
        if self.touch.drag.take().is_none() {
            return;
        }
        self.end(cx);
        self.keep_touch_selection(cx);
    }

    fn begin_in_window(
        &mut self,
        position: Point<Pixels>,
        extend: bool,
        window: &mut Window,
        cx: &mut App,
    ) {
        self.begin_impl(position, extend, true, Some(window), cx);
    }

    fn update_in_window(
        &mut self,
        position: Point<Pixels>,
        window: &Window,
        cx: &mut Context<Self>,
    ) {
        if !cx.has_active_drag() {
            self.update_impl(position, Some(window), cx);
            self.update_auto_scroll(position, window, cx);
        }
    }

    /// Selects the word or line under `position`, and returns it.
    fn select_at(
        &mut self,
        position: Point<Pixels>,
        click_count: usize,
        window: &mut Window,
        cx: &mut App,
    ) -> Option<SelectionUnit> {
        GlobalState::init(cx);
        if GlobalState::is_text_selection_suppressed(cx) {
            return None;
        }
        let hit = self.endpoint(position, Some(window), cx);
        if !hit.inside_text {
            return None;
        }
        let participant = hit.participant?.upgrade()?;
        let (start, end) =
            carets_for_multi_click(&participant.read(cx).runs.borrow(), position, click_count)?;
        let unit = self.unit_of(&participant, start, end, click_count, cx)?;
        self.anchor = Some(unit.start.clone());
        self.cursor = Some(unit.end.clone());
        self.did_hit_text = true;
        self.is_selecting = false;
        participant.update(cx, |state, cx| state.focus(window, cx));
        self.publish_snapshots(cx);
        Some(unit)
    }

    /// The word or line of `participant` from the caret `start` to the caret
    /// `end`, both in window coordinates, that `click_count` clicks selected.
    fn unit_of(
        &self,
        participant: &Entity<SelectableTextState>,
        start: Bounds<Pixels>,
        end: Bounds<Pixels>,
        click_count: usize,
        cx: &App,
    ) -> Option<SelectionUnit> {
        let registration = self
            .participants
            .borrow()
            .get(&participant.entity_id())?
            .registration
            .clone();
        let content_key_resolver = participant.read(cx).content_key_resolver.clone();
        let to_endpoint = |point: Point<Pixels>| {
            let content_point = point - registration.bounds.origin - registration.scroll_offset;
            SelectionEndpoint {
                participant: Some(participant.downgrade()),
                point: content_point,
                inside: true,
                inside_text: true,
                content_key: None,
                content_key_resolver: content_key_resolver
                    .clone()
                    .map(|resolver| (resolver, content_point)),
            }
        };
        Some(SelectionUnit {
            click_count,
            start: to_endpoint(start.origin),
            end: to_endpoint(end.origin),
            row_heights: (start.size.height, end.size.height),
        })
    }

    /// Keeps the gesture of the click that selected `unit` going: a drag
    /// from it, until the button is released, and a shift-click after it
    /// extend the selection by the same unit.
    fn hold_unit(&mut self, unit: SelectionUnit, cx: &mut App) {
        self.unit = Some(unit);
        self.is_selecting = true;
        self.publish_snapshots(cx);
    }

    /// Moves the cursor to the edge of the unit at `position`, which
    /// `endpoint` hit, and the anchor to the far edge of `unit`. A pointer
    /// over no text moves the cursor to itself, as a plain drag does.
    fn extend_unit(
        &mut self,
        unit: &SelectionUnit,
        position: Point<Pixels>,
        endpoint: SelectionEndpoint,
        cx: &App,
    ) {
        let (start, end) = {
            let participants = self.participants.borrow();
            (
                unit.start.resolve(&participants),
                unit.end.resolve(&participants),
            )
        };
        let (Some(start), Some(end)) = (start, end) else {
            self.did_hit_text |= endpoint.inside_text;
            self.cursor = Some(endpoint);
            return;
        };
        let (start_height, end_height) = unit.row_heights;
        let before =
            position.y < start.y || (position.y < start.y + start_height && position.x < start.x);
        let after = position.y >= end.y + end_height || (position.y >= end.y && position.x > end.x);
        if !before && !after {
            // A participant's own multi-click selection stands until the
            // pointer leaves it.
            if self.anchor.is_some() {
                self.anchor = Some(unit.start.clone());
                self.cursor = Some(unit.end.clone());
                self.did_hit_text = true;
            }
            return;
        }
        let (edge, anchor) = if before {
            (SelectionEdge::Start, &unit.end)
        } else {
            (SelectionEdge::End, &unit.start)
        };
        let cursor = Self::unit_edge_at(&endpoint, position, unit.click_count, edge, cx);
        self.anchor = Some(anchor.clone());
        self.cursor = Some(cursor.unwrap_or(endpoint));
        self.did_hit_text = true;
    }

    /// `endpoint`, hit at `position`, moved to the `edge` of the word or line
    /// under the pointer.
    fn unit_edge_at(
        endpoint: &SelectionEndpoint,
        position: Point<Pixels>,
        click_count: usize,
        edge: SelectionEdge,
        cx: &App,
    ) -> Option<SelectionEndpoint> {
        if !endpoint.inside {
            return None;
        }
        let participant = endpoint.participant.as_ref()?.upgrade()?;
        let runs = participant.read(cx).runs.borrow();
        let run = runs.iter().find(|run| run.bounds.contains(&position))?;
        if run.text.len() != run.layout.len() {
            return None;
        }
        // Past the end of a row, the pointer takes the character closest to it.
        let offset = run
            .layout
            .index_for_position(position)
            .unwrap_or_else(|closest| closest);
        let (start, end) = unit_carets(run, offset, click_count)?;
        let caret = match edge {
            SelectionEdge::Start => start,
            SelectionEdge::End => end,
        };
        Some(endpoint.moved(caret.origin - position))
    }

    #[cfg(test)]
    fn update_in_window_with_active_drag(
        &mut self,
        position: Point<Pixels>,
        active_drag: bool,
        window: &Window,
        cx: &mut App,
    ) {
        if !active_drag {
            self.update_impl(position, Some(window), cx);
        }
    }

    fn begin_impl(
        &mut self,
        position: Point<Pixels>,
        extend: bool,
        already_prepared: bool,
        window: Option<&mut Window>,
        cx: &mut App,
    ) {
        GlobalState::init(cx);
        if GlobalState::is_text_selection_suppressed(cx) {
            self.pending_extension_anchor = None;
            return;
        }
        let previous_anchor = extend
            .then(|| {
                self.pending_extension_anchor
                    .take()
                    .or_else(|| self.anchor.clone())
            })
            .flatten()
            .filter(|anchor| anchor.resolve(&self.participants.borrow()).is_some());
        if !extend && !already_prepared {
            self.clear(cx);
        }
        let endpoint = self.endpoint(position, window.as_deref(), cx);
        let focus_participant = endpoint
            .inside
            .then(|| endpoint.participant.clone())
            .flatten();
        let anchor = previous_anchor.unwrap_or_else(|| endpoint.clone());
        self.anchor = Some(anchor.clone());
        self.cursor = Some(endpoint.clone());
        self.did_hit_text = anchor.inside_text || endpoint.inside_text;
        self.is_selecting = true;
        // A shift-click after a double or triple click extends by its unit.
        if let Some(unit) = extend.then(|| self.unit.clone()).flatten() {
            self.extend_unit(&unit, position, endpoint, cx);
        }
        if let Some(participant) = focus_participant.and_then(|participant| participant.upgrade()) {
            if let Some(window) = window {
                participant.update(cx, |state, cx| state.focus(window, cx));
            }
        }
        self.publish_snapshots(cx);
    }

    fn update_impl(&mut self, position: Point<Pixels>, window: Option<&Window>, cx: &mut App) {
        if !self.is_selecting {
            return;
        }
        let endpoint = self.endpoint(position, window, cx);
        match self.unit.clone() {
            Some(unit) => self.extend_unit(&unit, position, endpoint, cx),
            None => {
                self.did_hit_text |= endpoint.inside_text;
                self.cursor = Some(endpoint);
            }
        }
        if window.is_none() {
            self.update_participant_auto_scroll(position, cx);
        }
        self.publish_snapshots(cx);
    }

    fn endpoint(
        &mut self,
        position: Point<Pixels>,
        window: Option<&Window>,
        cx: &App,
    ) -> SelectionEndpoint {
        self.prune_dead_participants();
        let mut hit: Option<(ParticipantRegistration, f32)> = None;
        let mut predecessor: Option<ParticipantRegistration> = None;
        let mut first: Option<ParticipantRegistration> = None;

        for registration in self.participants.borrow().values() {
            if registration.registration.scope != self.active_scope
                || registration.participant.upgrade().is_none()
            {
                continue;
            }
            let participant_geometry = &registration.registration;
            let hovered = window.map_or_else(
                || participant_geometry.bounds.contains(&position),
                |window| participant_geometry.hitbox.is_hovered(window),
            );
            if hovered {
                let area = f32::from(participant_geometry.bounds.size.width)
                    * f32::from(participant_geometry.bounds.size.height);
                if hit.as_ref().is_none_or(|(best, best_area)| {
                    area < *best_area
                        || (area == *best_area && registration.document_order < best.document_order)
                }) {
                    hit = Some((registration.clone(), area));
                }
            }
            if participant_geometry.bounds.top() <= position.y
                && predecessor.as_ref().is_none_or(|best| {
                    participant_geometry.bounds.top() > best.registration.bounds.top()
                        || (participant_geometry.bounds.top() == best.registration.bounds.top()
                            && registration.document_order < best.document_order)
                })
            {
                predecessor = Some(registration.clone());
            }
            if first.as_ref().is_none_or(|best| {
                participant_geometry.bounds.top() < best.registration.bounds.top()
                    || (participant_geometry.bounds.top() == best.registration.bounds.top()
                        && registration.document_order < best.document_order)
            }) {
                first = Some(registration.clone());
            }
        }

        let selection = hit.map(|(participant, _)| (participant, true)).or_else(|| {
            predecessor
                .or(first)
                .map(|participant| (participant, false))
        });
        match selection {
            Some((participant, inside)) => {
                let registration = participant.registration;
                let participant = participant.participant;
                let point = position - registration.bounds.origin - registration.scroll_offset;
                let content_key_resolver = participant.upgrade().and_then(|participant| {
                    participant
                        .read(cx)
                        .content_key_resolver
                        .clone()
                        .map(|callback| (callback, point))
                });
                SelectionEndpoint {
                    point,
                    participant: Some(participant),
                    inside,
                    inside_text: inside
                        && registration
                            .text_bounds
                            .iter()
                            .any(|bounds| bounds.contains(&position)),
                    content_key: None,
                    content_key_resolver,
                }
            }
            None => SelectionEndpoint {
                participant: None,
                point: position,
                inside: false,
                inside_text: false,
                content_key: None,
                content_key_resolver: None,
            },
        }
    }

    fn publish_snapshots(&mut self, cx: &mut App) {
        self.prune_dead_participants();
        for (participant, snapshot) in self.changed_snapshots(cx) {
            self.draw_changed.get_mut().remove(&participant.entity_id());
            participant.update(cx, |state, cx| state.set_snapshot(snapshot, cx));
        }
    }

    fn participant_snapshot(&self, id: EntityId) -> Option<TextSelectionSnapshot> {
        #[cfg(test)]
        self.snapshot_visits.set(self.snapshot_visits.get() + 1);

        let participants = self.participants.borrow();
        let registration = participants.get(&id)?;
        (registration.registration.scope == self.active_scope
            && self.participates(id, registration)
            && self.single_participant().is_none_or(|single| single == id))
        .then(|| self.snapshot())
        .flatten()
        .map(|mut snapshot| {
            snapshot.coverage = self.coverage_for(id);
            snapshot
        })
    }

    fn changed_snapshots(
        &self,
        cx: &App,
    ) -> Vec<(Entity<SelectableTextState>, Option<TextSelectionSnapshot>)> {
        self.participants
            .borrow()
            .iter()
            .filter_map(|(id, registration)| {
                let participant = registration.participant.upgrade()?;
                let snapshot = self.participant_snapshot(*id);
                (participant.read(cx).snapshot != snapshot).then_some((participant, snapshot))
            })
            .collect()
    }

    fn coverage_for(&self, id: EntityId) -> TextSelectionCoverage {
        let Some(anchor) = self.anchor.as_ref().and_then(SelectionEndpoint::entity_id) else {
            return TextSelectionCoverage::Bounded;
        };
        let Some(cursor) = self.cursor.as_ref().and_then(SelectionEndpoint::entity_id) else {
            return TextSelectionCoverage::Bounded;
        };
        if anchor == cursor {
            return TextSelectionCoverage::Bounded;
        }
        let anchor_order = self.participants.borrow()[&anchor].document_order;
        let cursor_order = self.participants.borrow()[&cursor].document_order;
        if id != anchor && id != cursor {
            TextSelectionCoverage::Full
        } else if (id == anchor) == (anchor_order < cursor_order) {
            TextSelectionCoverage::ToEnd
        } else {
            TextSelectionCoverage::FromStart
        }
    }

    fn single_participant(&self) -> Option<EntityId> {
        let anchor = self.anchor.as_ref()?.entity_id()?;
        let cursor = self.cursor.as_ref()?.entity_id()?;
        (anchor == cursor).then_some(anchor)
    }

    fn participates(&self, id: EntityId, registration: &ParticipantRegistration) -> bool {
        let Some(anchor) = self.anchor.as_ref().and_then(SelectionEndpoint::entity_id) else {
            return false;
        };
        let Some(cursor) = self.cursor.as_ref().and_then(SelectionEndpoint::entity_id) else {
            return false;
        };
        let Some(anchor_registration) = self.participants.borrow().get(&anchor).cloned() else {
            return false;
        };
        let Some(cursor_registration) = self.participants.borrow().get(&cursor).cloned() else {
            return false;
        };
        let start = anchor_registration
            .document_order
            .min(cursor_registration.document_order);
        let end = anchor_registration
            .document_order
            .max(cursor_registration.document_order);
        (start..=end).contains(&registration.document_order) || id == anchor || id == cursor
    }

    fn update_auto_scroll(
        &mut self,
        position: Point<Pixels>,
        window: &Window,
        cx: &mut Context<Self>,
    ) {
        // A finished gesture keeps its anchor for shift-click extension; only
        // a live drag may scroll.
        if !self.is_selecting {
            return;
        }
        let Some((_, registration)) = self.anchor_registration() else {
            return;
        };
        // Exactly one writer per drag: a participant that scrolls its own
        // content is notified directly; anything else gets a synthetic wheel.
        if registration.self_scroll {
            self.auto_scroll.stop();
            self.update_participant_auto_scroll(position, cx);
            return;
        }
        // The content mask is the nearest clipping viewport established by a
        // scrollable ancestor. It remains stable as the participant itself
        // moves, so selection keeps scrolling the same related region even
        // after the anchor text has moved out of view.
        let visible_bounds = registration.hitbox.content_mask.bounds;
        // Keeps the synthesized wheel event hit-testing inside the mask.
        const HIT_TEST_INSET: Pixels = px(1.);
        // A collapsed mask leaves an empty clamp range below — stop.
        if visible_bounds.size.width < HIT_TEST_INSET * 2.
            || visible_bounds.size.height < HIT_TEST_INSET * 2.
        {
            self.stop_anchor_auto_scroll(cx);
            return;
        }
        let delta = AutoScroll::compute_delta(position.y, visible_bounds);
        let event_position = point(
            position.x.clamp(
                visible_bounds.left() + HIT_TEST_INSET,
                visible_bounds.right() - HIT_TEST_INSET,
            ),
            position.y.clamp(
                visible_bounds.top() + HIT_TEST_INSET,
                visible_bounds.bottom() - HIT_TEST_INSET,
            ),
        );
        self.auto_scroll.last_drag_position = Some(event_position);
        self.auto_scroll_stall = (None, 0);
        let window = window.window_handle();
        self.auto_scroll.set(delta, cx, move |delta, state, cx| {
            let Some(position) = state.auto_scroll.last_drag_position else {
                return;
            };
            // Hold off once the container has shown, over a few ticks, that
            // it has nowhere left to go; the next move of the finger asks
            // again.
            const STALLED_TICKS: u8 = 3;
            let geometry = state
                .anchor_registration()
                .map(|(_, registration)| (registration.bounds, registration.scroll_offset));
            let (last, stalled) = &mut state.auto_scroll_stall;
            if *last == geometry {
                *stalled = stalled.saturating_add(1);
                if *stalled >= STALLED_TICKS {
                    return;
                }
            } else {
                *last = geometry;
                *stalled = 0;
            }
            let window = window;
            cx.defer(move |cx| {
                _ = window.update(cx, |_, window, cx| {
                    window.dispatch_event(
                        ScrollEvent {
                            position,
                            delta: ScrollDelta::Pixels(point(px(0.), -delta)),
                            ..Default::default()
                        }
                        .to_platform_input(),
                        cx,
                    );
                });
            });
        });
    }

    /// Drives the anchor participant's own scrolling, measured against the
    /// visible portion of the participant's element bounds.
    fn update_participant_auto_scroll(&self, position: Point<Pixels>, cx: &mut App) {
        let Some((participant, registration)) = self.anchor_registration() else {
            return;
        };
        let visible_bounds = registration
            .bounds
            .intersect(&registration.hitbox.content_mask.bounds);
        let delta = if visible_bounds.size.width > px(0.) && visible_bounds.size.height > px(0.) {
            AutoScroll::compute_delta(position.y, visible_bounds)
        } else {
            None
        };
        participant.update(cx, |state, cx| state.set_auto_scroll(delta, cx));
    }

    fn stop_anchor_auto_scroll(&mut self, cx: &mut App) {
        self.auto_scroll.stop();
        let Some(participant) = self.anchor_participant() else {
            return;
        };
        participant.update(cx, |state, cx| state.set_auto_scroll(None, cx));
    }

    /// The live participant owning the anchor of the current gesture.
    fn anchor_participant(&self) -> Option<Entity<SelectableTextState>> {
        self.anchor
            .as_ref()
            .filter(|anchor| anchor.inside)?
            .participant
            .as_ref()?
            .upgrade()
    }

    /// The anchor participant together with its current frame registration.
    fn anchor_registration(
        &self,
    ) -> Option<(Entity<SelectableTextState>, Rc<TextSelectionRegistration>)> {
        let participant = self.anchor_participant()?;
        let registration = self
            .participants
            .borrow()
            .get(&participant.entity_id())?
            .clone();
        Some((participant, registration.registration.clone()))
    }

    fn prune_dead_participants(&mut self) {
        self.participants
            .get_mut()
            .retain(|_, registration| registration.participant.upgrade().is_some());
    }
}

#[derive(Default)]
/// Non-owning window locator; retained [`TextSelection`] element state owns
/// each live selection entity.
struct SelectionStateRegistry(HashMap<gpui::WindowId, WeakEntity<WindowSelectionState>>);

impl Global for SelectionStateRegistry {}

#[derive(Default)]
struct PendingTextSelectionScopes(HashMap<gpui::WindowId, TextSelectionScopeId>);

impl Global for PendingTextSelectionScopes {}

#[derive(Default)]
struct TextSelectionScopeStacks(HashMap<gpui::WindowId, Vec<TextSelectionScopeId>>);

impl Global for TextSelectionScopeStacks {}

fn push_text_selection_scope(window_id: gpui::WindowId, scope: TextSelectionScopeId, cx: &mut App) {
    if !cx.has_global::<TextSelectionScopeStacks>() {
        cx.set_global(TextSelectionScopeStacks::default());
    }
    cx.global_mut::<TextSelectionScopeStacks>()
        .0
        .entry(window_id)
        .or_default()
        .push(scope);
}

fn pop_text_selection_scope(window_id: gpui::WindowId, cx: &mut App) {
    let stacks = &mut cx.global_mut::<TextSelectionScopeStacks>().0;
    let remove_stack = stacks.get_mut(&window_id).is_some_and(|stack| {
        stack.pop();
        stack.is_empty()
    });
    if remove_stack {
        stacks.remove(&window_id);
    }
}

fn current_text_selection_scope(
    window_id: gpui::WindowId,
    cx: &App,
) -> Option<TextSelectionScopeId> {
    cx.has_global::<TextSelectionScopeStacks>()
        .then(|| {
            cx.global::<TextSelectionScopeStacks>()
                .0
                .get(&window_id)
                .and_then(|stack| stack.last().copied())
        })
        .flatten()
}

fn with_text_selection_scope<T>(
    window_id: gpui::WindowId,
    scope: TextSelectionScopeId,
    cx: &mut App,
    callback: impl FnOnce(&mut App) -> T,
) -> T {
    push_text_selection_scope(window_id, scope, cx);
    let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| callback(cx)));
    pop_text_selection_scope(window_id, cx);
    match result {
        Ok(result) => result,
        Err(payload) => std::panic::resume_unwind(payload),
    }
}

/// Window-level operations for text selection.
pub struct TextSelection;

impl TextSelection {
    /// Returns whether `position` hits selectable text in the active scope.
    ///
    /// Uses the current frame's registered text geometry and hitboxes without
    /// starting or changing a selection. Blank space and text outside the active
    /// selection scope do not match. A containing control can yield a long press
    /// to the window's text selection before claiming the gesture itself.
    /// Call during pointer dispatch with the event's position, so the hitboxes
    /// reflect the point being queried. Touch-selection controls do not match.
    pub fn is_selectable_at(position: Point<Pixels>, window: &Window, cx: &mut App) -> bool {
        live_text_selection_state(window, cx).is_some_and(|state| {
            state.update(cx, |state, cx| {
                !state.touch.covers(position)
                    && state.endpoint(position, Some(window), cx).inside_text
            })
        })
    }

    /// Returns the currently selected text in logical document order.
    pub fn selected_text(window: &mut Window, cx: &mut App) -> String {
        let Some(state) = live_text_selection_state(window, cx) else {
            return String::new();
        };
        let items = state.read(cx).copy_items(cx);
        resolve_copy_items(items, cx)
    }

    /// Returns whether the window has a geometry selection or any participant
    /// has an active participant-local selection such as select-all.
    pub fn has_selection(window: &mut Window, cx: &mut App) -> bool {
        live_text_selection_state(window, cx).is_some_and(|state| state.read(cx).has_selection(cx))
    }

    /// Clears window selection and every participant's local selection.
    pub fn clear(window: &mut Window, cx: &mut App) {
        if let Some(state) = live_text_selection_state(window, cx) {
            let handlers = state.update(cx, |state, cx| state.clear_state(cx));
            dispatch_clear_handlers(handlers, cx);
        }
    }

    /// Clears selection for a known window identifier.
    ///
    /// Prefer [`Self::clear`] when a window reference is available. This
    /// narrow entry point supports hosts retiring deprecated window wrappers.
    pub fn clear_for_window(window_id: gpui::WindowId, cx: &mut App) {
        clear_window_text_selection(window_id, cx);
    }

    /// Ends the current drag while leaving its selection visible.
    pub fn end(window: &mut Window, cx: &mut App) {
        if let Some(state) = live_text_selection_state(window, cx) {
            state.update(cx, |state, cx| state.end(cx));
        }
    }

    /// Calls `callback` whenever the touch selection changes: it appears, its
    /// handles move, its menu opens or closes, or it goes away. Whoever draws
    /// the handles and the menu re-renders from here.
    pub fn observe_touch_selection(
        window: &Window,
        cx: &mut App,
        callback: impl Fn(&mut App) + 'static,
    ) -> Subscription {
        let state = WindowSelectionState::acquire(window.window_handle().window_id(), cx);
        cx.observe(&state, move |_, cx| callback(cx))
    }

    /// Returns the selection a long press made, laid out for its handles and
    /// edit menu, or `None` when the selection was made with a pointer.
    pub fn touch_selection(window: &Window, cx: &App) -> Option<TouchSelectionSnapshot> {
        WindowSelectionState::existing(window, cx)?
            .read(cx)
            .touch_selection()
    }

    /// Records where a touch handle or the edit menu is painted this frame, so
    /// that pressing it does not clear the selection it belongs to. Call from
    /// paint, every frame the surface is shown.
    pub fn register_touch_ui(bounds: Bounds<Pixels>, window: &Window, cx: &mut App) {
        if let Some(state) = WindowSelectionState::existing(window, cx) {
            state.update(cx, |state, _| state.register_touch_ui(bounds));
        }
    }

    /// Closes the edit menu and keeps the selection with its handles.
    pub fn close_edit_menu(window: &mut Window, cx: &mut App) {
        if let Some(state) = live_text_selection_state(window, cx) {
            state.update(cx, |state, cx| state.close_edit_menu(cx));
        }
    }

    /// Selects all of the text the touch selection started in, keeping the
    /// handles and the edit menu over the result.
    pub fn select_all(window: &mut Window, cx: &mut App) {
        if let Some(state) = live_text_selection_state(window, cx) {
            state.update(cx, |state, cx| state.select_all_touched(cx));
        }
    }

    /// Starts dragging one end of the touch selection from `finger`. The other
    /// end stays; the menu closes until [`Self::end_edge_drag`].
    pub fn begin_edge_drag(
        edge: SelectionEdge,
        finger: Point<Pixels>,
        window: &mut Window,
        cx: &mut App,
    ) {
        if let Some(state) = live_text_selection_state(window, cx) {
            state.update(cx, |state, cx| {
                state.begin_edge_drag(edge, finger, window, cx)
            });
            WindowSelectionState::resolve_content_keys(&state, cx);
        }
    }

    /// Moves the dragged end to the text under `finger`.
    pub fn update_edge_drag(finger: Point<Pixels>, window: &mut Window, cx: &mut App) {
        if let Some(state) = live_text_selection_state(window, cx) {
            state.update(cx, |state, cx| state.update_edge_drag(finger, window, cx));
            WindowSelectionState::resolve_content_keys(&state, cx);
        }
    }

    /// Ends the handle drag and reopens the edit menu over the result.
    pub fn end_edge_drag(window: &mut Window, cx: &mut App) {
        if let Some(state) = live_text_selection_state(window, cx) {
            state.update(cx, |state, cx| state.end_edge_drag(cx));
        }
    }

    /// Activates the opaque selection scope for this window.
    pub fn activate_scope(scope: TextSelectionScopeId, window: &mut Window, cx: &mut App) {
        let Some(state) = WindowSelectionState::existing(window, cx) else {
            if !cx.has_global::<PendingTextSelectionScopes>() {
                cx.set_global(PendingTextSelectionScopes::default());
            }
            cx.global_mut::<PendingTextSelectionScopes>()
                .0
                .insert(window.window_handle().window_id(), scope);
            return;
        };
        if state.read(cx).active_scope == scope {
            return;
        }
        let handlers = state.update(cx, |state, cx| state.set_active_scope_state(scope, cx));
        dispatch_clear_handlers(handlers, cx);
    }
}

/// A zero-sized root layer which enables text selection for a window.
///
/// Mount one as the root's first child. Its stable `"window-text-selection"`
/// element identity retains the window-local selection entity across frames.
pub struct TextSelectionLayer;

pub(crate) fn text_selection_scope(
    scope: TextSelectionScopeId,
    element: impl IntoElement,
) -> impl IntoElement {
    TextSelectionScopeMarker {
        scope,
        element: element.into_element(),
    }
}

struct TextSelectionScopeMarker<E> {
    scope: TextSelectionScopeId,
    element: E,
}

impl<E: Element> IntoElement for TextSelectionScopeMarker<E> {
    type Element = Self;

    fn into_element(self) -> Self::Element {
        self
    }
}

impl<E: Element> Element for TextSelectionScopeMarker<E> {
    type RequestLayoutState = E::RequestLayoutState;
    type PrepaintState = E::PrepaintState;

    fn id(&self) -> Option<ElementId> {
        self.element.id()
    }

    fn source_location(&self) -> Option<&'static std::panic::Location<'static>> {
        self.element.source_location()
    }

    fn request_layout(
        &mut self,
        id: Option<&GlobalElementId>,
        inspector_id: Option<&InspectorElementId>,
        window: &mut Window,
        cx: &mut App,
    ) -> (LayoutId, Self::RequestLayoutState) {
        let window_id = window.window_handle().window_id();
        with_text_selection_scope(window_id, self.scope, cx, |cx| {
            self.element.request_layout(id, inspector_id, window, cx)
        })
    }

    fn prepaint(
        &mut self,
        id: Option<&GlobalElementId>,
        inspector_id: Option<&InspectorElementId>,
        bounds: Bounds<Pixels>,
        request_layout: &mut Self::RequestLayoutState,
        window: &mut Window,
        cx: &mut App,
    ) -> Self::PrepaintState {
        let window_id = window.window_handle().window_id();
        with_text_selection_scope(window_id, self.scope, cx, |cx| {
            self.element
                .prepaint(id, inspector_id, bounds, request_layout, window, cx)
        })
    }

    fn paint(
        &mut self,
        id: Option<&GlobalElementId>,
        inspector_id: Option<&InspectorElementId>,
        bounds: Bounds<Pixels>,
        request_layout: &mut Self::RequestLayoutState,
        prepaint: &mut Self::PrepaintState,
        window: &mut Window,
        cx: &mut App,
    ) {
        let window_id = window.window_handle().window_id();
        with_text_selection_scope(window_id, self.scope, cx, |cx| {
            self.element.paint(
                id,
                inspector_id,
                bounds,
                request_layout,
                prepaint,
                window,
                cx,
            );
        });
    }
}

#[doc(hidden)]
pub struct TextSelectionLayerPrepaintState(Entity<WindowSelectionState>);

impl IntoElement for TextSelectionLayer {
    type Element = Self;

    fn into_element(self) -> Self::Element {
        self
    }
}

impl Element for TextSelectionLayer {
    type RequestLayoutState = ();
    type PrepaintState = TextSelectionLayerPrepaintState;

    fn id(&self) -> Option<ElementId> {
        Some("window-text-selection".into())
    }

    fn source_location(&self) -> Option<&'static std::panic::Location<'static>> {
        None
    }

    fn request_layout(
        &mut self,
        _: Option<&GlobalElementId>,
        _: Option<&InspectorElementId>,
        window: &mut Window,
        cx: &mut App,
    ) -> (LayoutId, Self::RequestLayoutState) {
        (window.request_layout(Style::default(), [], cx), ())
    }

    fn prepaint(
        &mut self,
        global_id: Option<&GlobalElementId>,
        _: Option<&InspectorElementId>,
        _: Bounds<Pixels>,
        _: &mut Self::RequestLayoutState,
        window: &mut Window,
        cx: &mut App,
    ) -> Self::PrepaintState {
        GlobalState::init(cx);
        let state = retain_text_selection_state(global_id, window, cx);
        state.read(cx).layer_painted.set(true);
        // The handles and the menu register again as they paint this frame.
        if state.read(cx).touch.painted_any() {
            state.update(cx, |state, _| state.touch.begin_frame());
        }
        TextSelectionLayerPrepaintState(state)
    }

    fn paint(
        &mut self,
        _: Option<&GlobalElementId>,
        _: Option<&InspectorElementId>,
        _: Bounds<Pixels>,
        _: &mut Self::RequestLayoutState,
        state: &mut Self::PrepaintState,
        window: &mut Window,
        cx: &mut App,
    ) {
        paint_text_selection(&state.0, window, cx);
    }
}

fn retain_text_selection_state(
    global_id: Option<&GlobalElementId>,
    window: &mut Window,
    cx: &mut App,
) -> Entity<WindowSelectionState> {
    let window_id = window.window_handle().window_id();
    let state = window.with_element_state::<Entity<WindowSelectionState>, _>(
        global_id.expect("TextSelection has a stable element id"),
        |retained, _| {
            let state = retained.unwrap_or_else(|| WindowSelectionState::acquire(window_id, cx));
            (state.clone(), state)
        },
    );
    // Registered once: writing the global again every frame would change it,
    // and every view that reads it, on every frame.
    let registered = cx.has_global::<SelectionStateRegistry>()
        && cx
            .global::<SelectionStateRegistry>()
            .0
            .get(&window_id)
            .is_some_and(|registered| registered.entity_id() == state.entity_id());
    if !registered {
        if !cx.has_global::<SelectionStateRegistry>() {
            cx.set_global(SelectionStateRegistry::default());
        }
        cx.global_mut::<SelectionStateRegistry>()
            .0
            .insert(window_id, state.downgrade());
    }
    state
}

fn schedule_selection_frame(
    state: &Entity<WindowSelectionState>,
    window: &mut Window,
    cx: &mut App,
) {
    if state.read(cx).schedule_finish_frame() {
        let state = state.downgrade();
        window.defer(cx, move |window, cx| {
            let Some(state) = state.upgrade() else {
                return;
            };
            let stale = state
                .read(cx)
                .stale_participants(state.read(cx).layer_painted.get());
            // Retiring an endpoint is a real selection change. Ordinary
            // frame publication does not write the shared window entity.
            let mut handlers = if state.read(cx).endpoint_departed(&stale) {
                state.update(cx, |state, cx| state.clear_state(cx))
            } else {
                Vec::new()
            };
            let departed = state.read(cx).remove_stale_participants(stale);
            handlers.extend(clear_departed_participants(departed, cx));
            let refresh_order = state.read(cx).finish_registrations();
            let mut changes = state
                .read(cx)
                .changed_snapshots(cx)
                .into_iter()
                .map(|(participant, snapshot)| (participant.entity_id(), (participant, snapshot)))
                .collect::<HashMap<_, _>>();
            let drawn = std::mem::take(&mut *state.read(cx).draw_changed.borrow_mut());
            for (id, participant) in drawn {
                if let Some(participant) = participant.upgrade() {
                    changes.entry(id).or_insert_with(|| {
                        let snapshot = participant.read(cx).snapshot;
                        (participant, snapshot)
                    });
                }
            }
            for (_, (participant, snapshot)) in changes {
                participant.update(cx, |participant, cx| {
                    participant.set_snapshot_quietly(snapshot);
                    cx.emit(TextSelectionEvent::SelectionChanged(snapshot));
                });
            }
            dispatch_clear_handlers(handlers, cx);
            if refresh_order {
                // GPUI does not expose the position of a replayed subtree in
                // paint order. Recover it once after an incomplete topology
                // change, not on ordinary partial selection redraws.
                window.refresh();
            }
            if state.read(cx).touch_edges_moved.replace(false) {
                state.update(cx, |state, cx| state.touch_changed(cx));
            }
            // Direct participant scrolling produces no wheel event. Refresh
            // the held cursor after paint registers the new scroll geometry.
            if state.read(cx).refresh_held_cursor.replace(false) && state.read(cx).is_selecting {
                state.update(cx, |state, cx| {
                    // A handle drag holds the finger off the text; keep the
                    // same offset, or the cursor would hop between the two.
                    let position = window.mouse_position();
                    let position = state
                        .touch
                        .drag
                        .map_or(position, |drag| drag.text_position(position));
                    state.update_in_window(position, window, cx);
                });
                WindowSelectionState::resolve_content_keys(&state, cx);
            }
        });
    }
}

fn paint_text_selection(state: &Entity<WindowSelectionState>, window: &mut Window, cx: &mut App) {
    schedule_selection_frame(state, window, cx);

    let mouse_down_state = state.downgrade();
    window.on_mouse_event(move |event: &MouseDownEvent, phase, window, cx| {
        if event.button != MouseButton::Left {
            return;
        }
        let Some(state) = mouse_down_state.upgrade() else {
            return;
        };
        // A press on a handle or on the edit menu acts on the selection; it
        // must not clear it.
        if state.read(cx).touch.covers(event.position) {
            return;
        }
        if phase.capture() {
            GlobalState::init(cx);
            GlobalState::reset_text_selection_suppression(cx);
            let handlers = state.update(cx, |state, cx| {
                if state.mouse_down_prepared {
                    return Vec::new();
                }
                state.mouse_down_prepared = true;
                state.prepare_for_mouse_down(event.click_count == 1 && event.modifiers.shift, cx)
            });
            dispatch_clear_handlers(handlers, cx);
        } else if event.click_count == 1 {
            if GlobalState::is_text_selection_suppressed(cx) {
                state.update(cx, |state, _| state.pending_extension_anchor = None);
                return;
            }
            state.update(cx, |state, cx| {
                if !state.is_selecting {
                    state.begin_in_window(event.position, event.modifiers.shift, window, cx)
                }
            });
            WindowSelectionState::resolve_content_keys(&state, cx);
        } else if event.click_count >= 2 {
            if GlobalState::is_text_selection_suppressed(cx) {
                return;
            }
            let touch = GlobalState::is_touch_press(cx);
            state.update(cx, |state, cx| {
                let unit = state.select_at(event.position, event.click_count, window, cx);
                // A double tap is touch's other way to select a word, and it
                // gets the handles and the menu like a long press does.
                if touch {
                    state.keep_touch_selection(cx);
                } else if let Some(unit) = unit {
                    state.hold_unit(unit, cx);
                }
            });
            WindowSelectionState::resolve_content_keys(&state, cx);
        }
    });

    // Every touch is offered as a drag first; that is how a tap's mouse
    // events are later told apart from a mouse's.
    window.on_mouse_event(move |event: &TouchDragEvent, phase, _, cx| {
        if phase.capture() && event.phase == TouchPhase::Started {
            GlobalState::note_touch(cx);
        }
    });

    // Touch panning remains scrolling until a long press actually hits text.
    // Claiming the gesture keeps subsequent moves out of the pan recognizer.
    let long_press_state = state.downgrade();
    window.on_mouse_event(move |event: &LongPressEvent, phase, window, cx| {
        if !phase.bubble() {
            return;
        }
        let Some(state) = long_press_state.upgrade() else {
            return;
        };
        if event.phase == TouchPhase::Started {
            if window.default_prevented()
                || state.read(cx).touch.covers(event.start_position)
                || !state.update(cx, |state, cx| {
                    state
                        .endpoint(event.start_position, Some(window), cx)
                        .inside_text
                })
            {
                return;
            }
            GlobalState::init(cx);
            GlobalState::reset_text_selection_suppression(cx);
            let handlers = state.update(cx, |state, cx| state.prepare_for_mouse_down(false, cx));
            dispatch_clear_handlers(handlers, cx);
            let selected = state.update(cx, |state, cx| {
                state.select_at(event.start_position, 2, window, cx);
                state.anchor.is_some()
            });
            if !selected {
                return;
            }
            window.capture_long_press(&state);
        } else if !window.has_long_press_capture(&state) {
            return;
        } else {
            state.update(cx, |state, cx| match event.phase {
                TouchPhase::Moved => {
                    state.is_selecting = true;
                    state.update_in_window(event.position, window, cx);
                }
                TouchPhase::Ended | TouchPhase::Cancelled => {
                    state.end(cx);
                    // The finger is up; the selection it made gets its
                    // handles and the edit menu.
                    state.keep_touch_selection(cx);
                }
                _ => {}
            });
        }
        window.prevent_default();
        cx.stop_propagation();
        WindowSelectionState::resolve_content_keys(&state, cx);
    });

    // A handle drag in progress follows the finger or the pointer wherever
    // it goes, whether or not the handle it took is laid out this frame.
    let drag_state = state.downgrade();
    window.on_mouse_event(move |event: &TouchDragEvent, phase, window, cx| {
        if !phase.bubble() || event.phase == TouchPhase::Started {
            return;
        }
        let Some(state) = drag_state.upgrade() else {
            return;
        };
        if state.read(cx).touch.drag.is_none() {
            return;
        }
        cx.stop_propagation();
        state.update(cx, |state, cx| match event.phase {
            TouchPhase::Moved => state.update_edge_drag(event.position, window, cx),
            _ => state.end_edge_drag(cx),
        });
        WindowSelectionState::resolve_content_keys(&state, cx);
    });
    let drag_state = state.downgrade();
    window.on_mouse_event(move |event: &MouseMoveEvent, phase, window, cx| {
        if phase.bubble()
            && event.pressed_button == Some(MouseButton::Left)
            && let Some(state) = drag_state.upgrade()
            && state.read(cx).touch.drag.is_some()
        {
            state.update(cx, |state, cx| {
                state.update_edge_drag(event.position, window, cx)
            });
            WindowSelectionState::resolve_content_keys(&state, cx);
        }
    });
    let drag_state = state.downgrade();
    window.on_mouse_event(move |event: &MouseUpEvent, phase, _, cx| {
        if phase.bubble()
            && event.button == MouseButton::Left
            && let Some(state) = drag_state.upgrade()
        {
            state.update(cx, |state, cx| state.end_edge_drag(cx));
        }
    });

    let mouse_move_state = state.downgrade();
    window.on_mouse_event(move |event: &MouseMoveEvent, phase, window, cx| {
        if phase.bubble()
            && let Some(state) = mouse_move_state.upgrade()
            // Moving the pointer only moves a selection being made.
            && state.read(cx).is_selecting
        {
            state.update(cx, |state, cx| {
                // A handle drag maps the pointer through the handle's offset;
                // the raw pointer must not fight it.
                if state.touch.drag.is_some() {
                    return;
                }
                state.update_in_window(event.position, window, cx)
            });
            WindowSelectionState::resolve_content_keys(&state, cx);
        }
    });

    let mouse_up_state = state.downgrade();
    window.on_mouse_event(move |_: &MouseUpEvent, phase, _, cx| {
        if phase.bubble()
            && let Some(state) = mouse_up_state.upgrade()
        {
            state.update(cx, |state, cx| {
                state.mouse_down_prepared = false;
                state.end(cx)
            });
        }
    });

    let scroll_state = state.downgrade();
    window.on_mouse_event(move |event: &ScrollEvent, phase, window, cx| {
        let Some(state) = scroll_state.upgrade() else {
            return;
        };
        // On capture, before a scroll container can stop the event: one
        // stretched past its end swallows the whole stream, the lift
        // included, and the menu would never come back.
        if phase.capture() {
            if state.read(cx).touch.active {
                state.update(cx, |state, cx| {
                    state.edit_menu_on_scroll(event.touch_phase, cx)
                });
            }
            return;
        }
        // A scroll only moves a selection being made under the pointer.
        if phase.bubble() && state.read(cx).is_selecting {
            let position = window.mouse_position();
            state.update(cx, |state, cx| {
                // A handle drag holds the finger off the text; keep its offset.
                let position = state
                    .touch
                    .drag
                    .map_or(position, |drag| drag.text_position(position));
                state.update_in_window(position, window, cx)
            });
            WindowSelectionState::resolve_content_keys(&state, cx);
        }
    });
}

fn live_text_selection_state(
    window: &Window,
    cx: &mut App,
) -> Option<Entity<WindowSelectionState>> {
    WindowSelectionState::existing(window, cx)
}

pub(crate) fn clear_window_text_selection(window_id: gpui::WindowId, cx: &mut App) {
    if !cx.has_global::<SelectionStateRegistry>() {
        return;
    }
    let Some(state) = cx
        .global::<SelectionStateRegistry>()
        .0
        .get(&window_id)
        .and_then(WeakEntity::upgrade)
    else {
        return;
    };
    let handlers = state.update(cx, |state, cx| state.clear_state(cx));
    dispatch_clear_handlers(handlers, cx);
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::ElementExt as _;
    #[cfg(feature = "gpui-fast")]
    use gpui::StatefulInteractiveElement as _;
    use gpui::{
        Bounds, ContentMask, Context, Hitbox, HitboxBehavior, HitboxId, InteractiveElement as _,
        IntoElement, ParentElement as _, Render, SharedString, Styled as _, StyledText,
        TestAppContext, TextLayout, Window, div, point, prelude::FluentBuilder as _, px, size,
    };
    use std::{
        cell::{Cell, RefCell},
        rc::Rc,
    };

    struct FakeParticipant {
        selection: TextSelectionHandle,
    }

    struct WindowSelectionView {
        selection: TextSelectionHandle,
    }

    struct SelectionElementOnlyView;
    struct ToggleSelectionElementView {
        enabled: bool,
        selection: TextSelectionHandle,
    }

    struct DoubleSelectionElementView {
        selection: TextSelectionHandle,
    }

    struct WindowOwnedSelectionView {
        selection: TextSelectionHandle,
    }

    struct FirstFrameScopedSelectionView {
        selection: TextSelectionHandle,
    }

    struct PlainRunLayoutView {
        texts: Vec<SharedString>,
        layouts: Vec<TextLayout>,
    }

    impl Render for WindowSelectionView {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            div()
        }
    }

    impl Render for SelectionElementOnlyView {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            div()
                .size_full()
                .child(TextSelectionLayer)
                .child(
                    div()
                        .size_full()
                        .on_mouse_down(MouseButton::Left, |_, _, cx| {
                            GlobalState::suppress_text_selection(cx);
                        }),
                )
        }
    }

    impl Render for ToggleSelectionElementView {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            let selection = self.selection.clone();
            div().when(self.enabled, |this| {
                this.child(TextSelectionLayer)
                    .child(div().size_full().on_prepaint(move |bounds, window, cx| {
                        let hitbox = window.insert_hitbox(bounds, HitboxBehavior::Normal);
                        selection.register(
                            TextSelectionRegistration::new(hitbox, bounds)
                                .with_text_bounds(vec![bounds]),
                            window,
                            cx,
                        );
                    }))
            })
        }
    }

    impl Render for DoubleSelectionElementView {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            let selection = self.selection.clone();
            div()
                .size_full()
                .child(TextSelectionLayer)
                .child(TextSelectionLayer)
                .on_prepaint(move |bounds, window, cx| {
                    let hitbox = window.insert_hitbox(bounds, HitboxBehavior::Normal);
                    selection.register(
                        TextSelectionRegistration::new(hitbox, bounds)
                            .with_text_bounds(vec![bounds]),
                        window,
                        cx,
                    );
                })
        }
    }

    impl Render for WindowOwnedSelectionView {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            let selection = self.selection.clone();
            div()
                .size_full()
                .child(TextSelectionLayer)
                .child(div().size_full().on_prepaint(move |bounds, window, cx| {
                    let hitbox = window.insert_hitbox(bounds, HitboxBehavior::Normal);
                    selection.register(
                        TextSelectionRegistration::new(hitbox, bounds)
                            .with_text_bounds(vec![bounds]),
                        window,
                        cx,
                    );
                }))
        }
    }

    impl Render for FirstFrameScopedSelectionView {
        fn render(&mut self, window: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
            let scope = TextSelectionScopeId::from_raw(23);
            TextSelection::activate_scope(scope, window, cx);
            let selection = self.selection.clone();

            div().child(TextSelectionLayer).child(
                div()
                    .size_full()
                    .on_prepaint(move |bounds, window, cx| {
                        let hitbox = window.insert_hitbox(bounds, HitboxBehavior::Normal);
                        selection.register(
                            TextSelectionRegistration::new(hitbox, bounds)
                                .with_text_bounds(vec![bounds]),
                            window,
                            cx,
                        );
                    })
                    .text_selection_scope(scope),
            )
        }
    }

    impl Render for PlainRunLayoutView {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            self.layouts.clear();
            let children = self
                .texts
                .iter()
                .enumerate()
                .map(|(index, text)| {
                    let text = StyledText::new(text.clone());
                    self.layouts.push(text.layout().clone());
                    div().absolute().top(px(index as f32 * 40.)).child(text)
                })
                .collect::<Vec<_>>();
            div().size_full().children(children)
        }
    }

    impl FakeParticipant {
        fn new(text: &str, cx: &mut gpui::App) -> Self {
            let selection = TextSelectionHandle::new(text, cx);
            Self { selection }
        }

        fn register(
            &self,
            selection_state: &mut WindowSelectionState,
            y: f32,
            scope: TextSelectionScopeId,
            document_order: u64,
            cx: &mut gpui::App,
        ) {
            let bounds = Bounds::new(point(px(0.), px(y)), size(px(100.), px(10.)));
            selection_state.register_participant(
                self.selection.clone(),
                TextSelectionRegistration::new(
                    Hitbox {
                        id: HitboxId::placeholder(),
                        bounds,
                        content_mask: ContentMask { bounds },
                        behavior: HitboxBehavior::Normal,
                    },
                    bounds,
                )
                .with_scope(scope)
                .with_document_order(document_order)
                .with_text_bounds(vec![bounds]),
                cx,
            );
        }
    }

    fn laid_out_runs(texts: &[&str], cx: &mut TestAppContext) -> Vec<(SharedString, TextLayout)> {
        let texts = texts
            .iter()
            .map(|text| SharedString::from(*text))
            .collect::<Vec<_>>();
        let view = cx.add_window({
            let texts = texts.clone();
            move |_, _| PlainRunLayoutView {
                texts,
                layouts: Vec::new(),
            }
        });
        cx.update_window(*view, |_, window, cx| {
            let _ = window.draw(cx);
        })
        .unwrap();
        let layouts = cx.update(|cx| view.read(cx).unwrap().layouts.clone());
        texts.into_iter().zip(layouts).collect()
    }

    fn plain_snapshot(anchor: Point<Pixels>, cursor: Point<Pixels>) -> TextSelectionSnapshot {
        TextSelectionSnapshot::new(
            TextSelectionEndpoint::new(None, anchor),
            TextSelectionEndpoint::new(None, cursor),
        )
        .with_window_points(Some(TextSelectionWindowPoints { anchor, cursor }))
    }

    #[gpui::test]
    fn scope_stack_is_cleaned_after_panicking_subtree(cx: &mut TestAppContext) {
        let window_id = {
            let (_, window_cx) = cx.add_window_view(|_, _| SelectionElementOnlyView);
            window_cx.update(|window, _| window.window_handle().window_id())
        };
        let scope = TextSelectionScopeId::from_raw(41);

        cx.update(|cx| {
            let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                with_text_selection_scope(window_id, scope, cx, |_| panic!("subtree failed"));
            }));

            assert!(result.is_err());
            assert_eq!(current_text_selection_scope(window_id, cx), None);
        });
    }

    #[gpui::test]
    fn reentrant_scope_from_one_window_does_not_pollute_another(cx: &mut TestAppContext) {
        let first_window_id = {
            let (_, window_cx) = cx.add_window_view(|_, _| SelectionElementOnlyView);
            window_cx.update(|window, _| window.window_handle().window_id())
        };
        let second_window_id = {
            let (_, window_cx) = cx.add_window_view(|_, _| SelectionElementOnlyView);
            window_cx.update(|window, _| window.window_handle().window_id())
        };
        let scope = TextSelectionScopeId::from_raw(42);

        cx.update(|cx| {
            with_text_selection_scope(first_window_id, scope, cx, |cx| {
                assert_eq!(current_text_selection_scope(second_window_id, cx), None);
                assert_eq!(
                    current_text_selection_scope(first_window_id, cx),
                    Some(scope)
                );
            });
        });
    }

    #[gpui::test]
    fn selection_callback_can_reenter_its_selection_state(cx: &mut TestAppContext) {
        let called = Rc::new(Cell::new(false));
        let called_from_callback = called.clone();
        let (selection_state, participant) = cx.update(|cx| {
            let selection_state = cx.new(|_| WindowSelectionState::default());
            let selection_state_for_callback = selection_state.clone();
            let participant = FakeParticipant::new("participant", cx);
            participant
                .selection
                .subscribe(
                    move |event, cx| {
                        if matches!(event, TextSelectionEvent::SelectionChanged(Some(_))) {
                            selection_state_for_callback
                                .update(cx, |_, _| called_from_callback.set(true));
                        }
                    },
                    cx,
                )
                .detach();
            (selection_state, participant)
        });
        cx.run_until_parked();
        cx.update(|cx| {
            selection_state.update(cx, |selection_state, cx| {
                participant.register(selection_state, 0., TextSelectionScopeId::default(), 0, cx);
                selection_state.begin(point(px(1.), px(1.)), false, cx);
                selection_state.update(point(px(20.), px(1.)), cx);
            });
        });
        cx.run_until_parked();
        assert!(called.get());
    }

    #[gpui::test]
    fn selection_events_preserve_snapshot_then_clear_order(cx: &mut TestAppContext) {
        let observed = Rc::new(RefCell::new(Vec::new()));
        let observed_for_callback = observed.clone();
        let selection = cx.update(|cx| {
            let selection = TextSelectionHandle::new("selection", cx);
            selection
                .subscribe(
                    move |event, _| {
                        if let TextSelectionEvent::SelectionChanged(snapshot) = event {
                            observed_for_callback.borrow_mut().push(snapshot.is_some());
                        }
                    },
                    cx,
                )
                .detach();
            selection
        });
        cx.run_until_parked();
        cx.update(|cx| {
            selection.0.update(cx, |state, cx| {
                state.set_snapshot(
                    Some(plain_snapshot(point(px(1.), px(1.)), point(px(8.), px(1.)))),
                    cx,
                );
                state.clear_state(cx);
            });
        });
        cx.run_until_parked();
        assert_eq!(&*observed.borrow(), &[true, false]);
    }

    fn text_run(order: u64, text: SharedString, layout: TextLayout) -> TextSelectionRun {
        let bounds = layout.bounds();
        TextSelectionRun::new(text, layout, bounds).with_document_order(order)
    }

    #[gpui::test]
    fn public_selection_data_uses_builders_and_readers(cx: &mut TestAppContext) {
        let bounds = Bounds::new(point(px(1.), px(2.)), size(px(30.), px(10.)));
        let hitbox = Hitbox {
            id: HitboxId::placeholder(),
            bounds,
            content_mask: ContentMask { bounds },
            behavior: HitboxBehavior::Normal,
        };
        let scope = TextSelectionScopeId::from_raw(7);
        let endpoint = TextSelectionEndpoint::new(None, bounds.origin)
            .with_content_key(TextSelectionContentKey::new(11));
        let snapshot = TextSelectionSnapshot::new(endpoint, endpoint)
            .with_selecting(true)
            .with_window_points(Some(TextSelectionWindowPoints {
                anchor: bounds.origin,
                cursor: bounds.bottom_right(),
            }))
            .with_coverage(TextSelectionCoverage::Full);
        let registration = TextSelectionRegistration::new(hitbox, bounds)
            .with_scroll_offset(point(px(3.), px(4.)))
            .with_scope(scope)
            .with_document_order(9)
            .with_text_bounds(vec![bounds]);

        assert_eq!(endpoint.entity_id(), None);
        assert_eq!(endpoint.content_point(), bounds.origin);
        assert_eq!(
            endpoint.content_key(),
            Some(TextSelectionContentKey::new(11))
        );
        assert_eq!(snapshot.anchor(), endpoint);
        assert_eq!(snapshot.cursor(), endpoint);
        assert!(snapshot.is_selecting());
        assert_eq!(snapshot.coverage(), TextSelectionCoverage::Full);
        assert_eq!(
            snapshot.window_points(),
            Some(TextSelectionWindowPoints {
                anchor: bounds.origin,
                cursor: bounds.bottom_right(),
            })
        );
        assert_eq!(registration.bounds(), bounds);
        assert_eq!(registration.scroll_offset(), point(px(3.), px(4.)));
        assert_eq!(registration.scope(), scope);
        assert_eq!(registration.document_order(), 9);
        assert_eq!(registration.text_bounds(), &[bounds]);

        let (text, layout) = laid_out_runs(&["aé"], cx).pop().unwrap();
        let text_run = TextSelectionRun::new(text.clone(), layout.clone(), layout.bounds())
            .with_document_order(3);
        assert_eq!(text_run.document_order(), 3);
        assert_eq!(text_run.text(), &text);
        assert_eq!(text_run.layout().len(), layout.len());
        assert_eq!(text_run.bounds(), layout.bounds());

        let projection = TextSelectionProjection {
            ranges: vec![Some(1..3)],
            is_active: true,
        };
        assert_eq!(projection.ranges(), &[Some(1..3)]);
        assert!(projection.is_active());
    }

    #[gpui::test]
    fn selection_handle_is_the_public_adapter_seam(cx: &mut TestAppContext) {
        let selected = Rc::new(Cell::new(false));
        let selected_from_callback = selected.clone();
        cx.update(|cx| {
            let selection = TextSelectionHandle::new("initial", cx);
            let entity_id = selection.entity_id();
            selection.set_fallback_copy_text("updated", cx);
            selection.set_local_selection(true, cx);
            selection
                .subscribe(
                    move |event, _| {
                        if let TextSelectionEvent::SelectionChanged(snapshot) = event {
                            selected_from_callback.set(snapshot.is_some());
                        }
                    },
                    cx,
                )
                .detach();
            selection.focus_with(|_, _| {}, cx);
            selection.copy_with(|_| "copied".to_string(), cx);
            selection.resolve_content_key_with(|_, _| Some(TextSelectionContentKey::new(3)), cx);

            assert_eq!(selection.entity_id(), entity_id);
            assert_eq!(selection.snapshot(cx), None);
            assert_eq!(
                selection.update_runs(&[], cx),
                TextSelectionProjection::default()
            );
        });
        assert!(!selected.get());
    }

    #[gpui::test]
    fn selection_handle_can_subscribe_its_window_to_refresh(cx: &mut TestAppContext) {
        let (_, cx) = cx.add_window_view(|_, cx| WindowSelectionView {
            selection: TextSelectionHandle::new("refresh", cx),
        });
        cx.update(|window, cx| {
            let selection = TextSelectionHandle::new("refresh", cx);
            selection.refresh_window_on_change(window, cx).detach();
        });
    }

    #[gpui::test]
    fn plain_projection_preserves_forward_reversed_and_unicode_ranges(cx: &mut TestAppContext) {
        let (text, layout) = laid_out_runs(&["aé🙂z"], cx).pop().unwrap();
        let run = text_run(0, text, layout.clone());
        let start = layout.position_for_index(1).unwrap();
        let end = layout.position_for_index(7).unwrap();

        let forward = project_ranges(Some(plain_snapshot(start, end)), std::slice::from_ref(&run));
        let reversed = project_ranges(Some(plain_snapshot(end, start)), &[run]);

        assert_eq!(forward.ranges(), &[Some(1..7)]);
        assert_eq!(reversed.ranges(), &[Some(1..7)]);
        assert!(forward.is_active());
        assert!(reversed.is_active());
    }

    #[gpui::test]
    fn double_click_expands_a_plain_run_to_the_input_word_boundary(cx: &mut TestAppContext) {
        let (text, layout) = laid_out_runs(&["one café, three"], cx).pop().unwrap();
        let run = text_run(0, text, layout.clone());
        let click = layout.position_for_index(6).unwrap();

        let (anchor, cursor) =
            carets_for_multi_click(std::slice::from_ref(&run), click, 2).unwrap();
        let states = project_ranges(Some(plain_snapshot(anchor.origin, cursor.origin)), &[run]);

        assert_eq!(states.ranges(), &[Some(4..9)]);
    }

    #[gpui::test]
    fn multi_click_uses_text_layout_window_coordinates_at_a_nonzero_origin(
        cx: &mut TestAppContext,
    ) {
        let mut runs = laid_out_runs(&["above", "alpha beta"], cx);
        let (text, layout) = runs.pop().unwrap();
        assert!(layout.bounds().origin.y > px(0.));
        let run = text_run(0, text, layout.clone());
        let click = layout.position_for_index(7).unwrap();

        let (anchor, cursor) =
            carets_for_multi_click(std::slice::from_ref(&run), click, 2).unwrap();
        let projection = project_ranges(Some(plain_snapshot(anchor.origin, cursor.origin)), &[run]);

        assert_eq!(projection.ranges(), &[Some(6..10)]);
    }

    #[gpui::test]
    fn triple_click_expands_to_the_input_logical_line_not_the_visual_row(cx: &mut TestAppContext) {
        let (text, layout) = laid_out_runs(&["second line"], cx).pop().unwrap();
        let run = text_run(0, text, layout.clone());
        let click = layout.position_for_index(4).unwrap();

        let (anchor, cursor) =
            carets_for_multi_click(std::slice::from_ref(&run), click, 4).unwrap();
        let states = project_ranges(Some(plain_snapshot(anchor.origin, cursor.origin)), &[run]);

        assert_eq!(states.ranges(), &[Some(0..11)]);
        assert_eq!(line_range_at("first line\nsecond line\nthird", 15), 11..22);
    }

    #[gpui::test]
    fn plain_projection_spans_multiple_runs_and_leaves_empty_gutters_unselected(
        cx: &mut TestAppContext,
    ) {
        let mut runs = laid_out_runs(&["first", "", "second"], cx);
        let (first_text, first_layout) = runs.remove(0);
        let (gutter_text, gutter_layout) = runs.remove(0);
        let (second_text, second_layout) = runs.remove(0);
        let start = first_layout.position_for_index(2).unwrap();
        let end = second_layout.position_for_index(3).unwrap();
        let states = project_ranges(
            Some(plain_snapshot(start, end)),
            &[
                text_run(2, second_text, second_layout),
                text_run(1, gutter_text, gutter_layout),
                text_run(0, first_text, first_layout),
            ],
        );

        assert_eq!(states.ranges(), &[Some(0..3), None, Some(2..5)]);
        assert!(states.is_active());
    }

    #[gpui::test]
    fn plain_projection_caches_multiple_participant_copies_in_document_order(
        cx: &mut TestAppContext,
    ) {
        let mut runs = laid_out_runs(&["one", "two"], cx);
        let (first_text, first_layout) = runs.remove(0);
        let (second_text, second_layout) = runs.remove(0);
        let snapshot = plain_snapshot(
            first_layout.position_for_index(1).unwrap(),
            second_layout.position_for_index(2).unwrap(),
        );
        cx.update(|cx| {
            let mut selection_state = WindowSelectionState::default();
            let first = FakeParticipant::new("", cx);
            let second = FakeParticipant::new("", cx);
            first.register(
                &mut selection_state,
                0.,
                TextSelectionScopeId::default(),
                1,
                cx,
            );
            second.register(
                &mut selection_state,
                20.,
                TextSelectionScopeId::default(),
                0,
                cx,
            );

            first
                .selection
                .0
                .update(cx, |state, cx| state.set_snapshot(Some(snapshot), cx));
            let projection = first
                .selection
                .update_runs(&[text_run(0, first_text, first_layout)], cx);
            assert_eq!(projection.ranges(), &[Some(1..3)]);
            assert!(projection.is_active());
            second
                .selection
                .0
                .update(cx, |state, cx| state.set_snapshot(Some(snapshot), cx));
            let projection = second
                .selection
                .update_runs(&[text_run(0, second_text, second_layout)], cx);
            assert_eq!(projection.ranges(), &[Some(0..2)]);
            assert!(projection.is_active());

            assert_eq!(selection_state.selected_text(cx), "tw\nne");
        });
    }

    #[gpui::test]
    fn plain_projection_invalidates_cached_copy_when_the_snapshot_changes(cx: &mut TestAppContext) {
        let (text, layout) = laid_out_runs(&["first"], cx).pop().unwrap();
        let first_snapshot = plain_snapshot(
            layout.position_for_index(1).unwrap(),
            layout.position_for_index(3).unwrap(),
        );
        let changed_snapshot = plain_snapshot(
            layout.position_for_index(3).unwrap(),
            layout.position_for_index(5).unwrap(),
        );
        let run = text_run(0, text, layout);
        cx.update(|cx| {
            let mut selection_state = WindowSelectionState::default();
            let participant = FakeParticipant::new("", cx);
            participant.register(
                &mut selection_state,
                0.,
                TextSelectionScopeId::default(),
                0,
                cx,
            );
            participant.selection.0.update(cx, |state, cx| {
                state.set_snapshot(Some(first_snapshot), cx);
                state.update_runs(std::slice::from_ref(&run));
            });
            assert_eq!(selection_state.selected_text(cx), "ir");

            participant.selection.0.update(cx, |state, cx| {
                state.set_snapshot(Some(changed_snapshot), cx);
            });
            assert_eq!(selection_state.selected_text(cx), "");

            participant.selection.update_runs(&[run], cx);
            assert_eq!(selection_state.selected_text(cx), "st");
            selection_state.clear(cx);
            participant.selection.set_local_selection(true, cx);
            assert_eq!(selection_state.selected_text(cx), "");
        });
    }

    #[gpui::test]
    fn plain_projection_orders_cached_runs_by_frame_order_not_input_order(cx: &mut TestAppContext) {
        let mut runs = laid_out_runs(&["one", "two"], cx);
        let (first_text, first_layout) = runs.remove(0);
        let (second_text, second_layout) = runs.remove(0);
        let snapshot = plain_snapshot(
            first_layout.position_for_index(1).unwrap(),
            second_layout.position_for_index(2).unwrap(),
        );
        cx.update(|cx| {
            let mut selection_state = WindowSelectionState::default();
            let participant = FakeParticipant::new("", cx);
            participant.register(
                &mut selection_state,
                0.,
                TextSelectionScopeId::default(),
                0,
                cx,
            );
            participant.selection.0.update(cx, |state, cx| {
                state.set_snapshot(Some(snapshot), cx);
                state.update_runs(&[
                    text_run(1, first_text, first_layout),
                    text_run(0, second_text, second_layout),
                ]);
            });

            assert_eq!(selection_state.selected_text(cx), "twne");
        });
    }

    #[gpui::test]
    fn plain_projection_safely_rejects_a_text_layout_length_mismatch(cx: &mut TestAppContext) {
        let (_, layout) = laid_out_runs(&["short"], cx).pop().unwrap();
        let start = layout.position_for_index(0).unwrap();
        let end = layout.position_for_index(5).unwrap();
        let states = project_ranges(
            Some(plain_snapshot(start, end)),
            &[text_run(0, SharedString::from("longer"), layout)],
        );

        assert_eq!(states.ranges(), &[None]);
        assert!(states.is_active());
    }

    #[gpui::test]
    fn begin_update_and_end_publish_a_cross_participant_selection(cx: &mut TestAppContext) {
        cx.update(|cx| {
            let mut selection_state = WindowSelectionState::default();
            let first = FakeParticipant::new("first", cx);
            let second = FakeParticipant::new("second", cx);
            first.register(
                &mut selection_state,
                0.,
                TextSelectionScopeId::default(),
                0,
                cx,
            );
            second.register(
                &mut selection_state,
                20.,
                TextSelectionScopeId::default(),
                1,
                cx,
            );

            selection_state.begin(point(px(1.), px(1.)), false, cx);
            selection_state.update(point(px(1.), px(25.)), cx);
            assert!(selection_state.has_selection(cx));
            assert_eq!(selection_state.selected_text(cx), "first\nsecond");

            selection_state.end(cx);
            assert!(!selection_state.is_selecting());
        });
    }

    #[gpui::test]
    fn shift_extension_keeps_its_original_anchor_when_reversed(cx: &mut TestAppContext) {
        cx.update(|cx| {
            let mut selection_state = WindowSelectionState::default();
            let participant = FakeParticipant::new("participant", cx);
            participant.register(
                &mut selection_state,
                0.,
                TextSelectionScopeId::default(),
                0,
                cx,
            );

            selection_state.begin(point(px(2.), px(2.)), false, cx);
            selection_state.end(cx);
            selection_state.begin(point(px(8.), px(2.)), true, cx);
            selection_state.end(cx);
            let first_anchor = selection_state.snapshot().unwrap().anchor();

            selection_state.begin(point(px(0.), px(2.)), true, cx);
            selection_state.end(cx);
            let reversed = selection_state.snapshot().unwrap();
            assert_eq!(reversed.anchor(), first_anchor);
            assert!(reversed.cursor().content_point().x < reversed.anchor().content_point().x);
        });
    }

    #[gpui::test]
    fn content_key_resolver_runs_outside_the_window_state_lease(cx: &mut TestAppContext) {
        cx.update(|cx| {
            let state = cx.new(|_| WindowSelectionState::default());
            let participant = FakeParticipant::new("virtual", cx);
            let state_for_callback = state.clone();
            participant.selection.resolve_content_key_with(
                move |_, cx| {
                    let _ = state_for_callback.read(cx).snapshot();
                    Some(TextSelectionContentKey::new(7))
                },
                cx,
            );
            state.update(cx, |state, cx| {
                participant.register(state, 0., TextSelectionScopeId::default(), 0, cx);
                state.begin(point(px(1.), px(1.)), false, cx);
                state.update(point(px(8.), px(1.)), cx);
            });

            WindowSelectionState::resolve_content_keys(&state, cx);

            assert_eq!(
                state.read(cx).snapshot().unwrap().cursor().content_key(),
                Some(TextSelectionContentKey::new(7))
            );
        });
    }

    #[gpui::test]
    fn active_dnd_does_not_move_a_text_selection_cursor(cx: &mut TestAppContext) {
        let window = cx.add_window(|_, cx| WindowSelectionView {
            selection: TextSelectionHandle::new("unused", cx),
        });
        window
            .update(cx, |_, window, cx| {
                let mut state = WindowSelectionState::default();
                let participant = FakeParticipant::new("participant", cx);
                participant.register(&mut state, 0., TextSelectionScopeId::default(), 0, cx);
                state.begin(point(px(1.), px(1.)), false, cx);
                let before = state.cursor.as_ref().unwrap().point;
                state.update_in_window_with_active_drag(point(px(80.), px(1.)), true, window, cx);
                assert_eq!(state.cursor.as_ref().unwrap().point, before);
            })
            .unwrap();
    }

    #[gpui::test]
    fn shift_extension_falls_back_when_the_anchor_participant_was_swept(cx: &mut TestAppContext) {
        cx.update(|cx| {
            let mut selection_state = WindowSelectionState::default();
            let first = FakeParticipant::new("first", cx);
            let second = FakeParticipant::new("second", cx);
            first.register(
                &mut selection_state,
                0.,
                TextSelectionScopeId::default(),
                0,
                cx,
            );
            selection_state.begin(point(px(1.), px(1.)), false, cx);
            selection_state.update(point(px(8.), px(1.)), cx);
            selection_state.end(cx);

            selection_state.finish_frame(cx);
            selection_state.finish_frame(cx);
            second.register(
                &mut selection_state,
                20.,
                TextSelectionScopeId::default(),
                1,
                cx,
            );
            selection_state.begin(point(px(1.), px(21.)), true, cx);
            selection_state.update(point(px(8.), px(21.)), cx);
            selection_state.end(cx);

            assert_eq!(selection_state.selected_text(cx), "second");
        });
    }

    #[gpui::test]
    fn scope_and_suppression_prevent_unrelated_participants_from_participating(
        cx: &mut TestAppContext,
    ) {
        cx.update(|cx| {
            let mut selection_state = WindowSelectionState::default();
            let base = FakeParticipant::new("base", cx);
            let modal = FakeParticipant::new("modal", cx);
            base.register(
                &mut selection_state,
                0.,
                TextSelectionScopeId::default(),
                0,
                cx,
            );
            modal.register(&mut selection_state, 20., TextSelectionScopeId(1), 1, cx);

            selection_state.set_active_scope(TextSelectionScopeId(1), cx);
            selection_state.begin(point(px(1.), px(21.)), false, cx);
            selection_state.update(point(px(8.), px(21.)), cx);
            selection_state.end(cx);
            assert_eq!(selection_state.selected_text(cx), "modal");

            selection_state.clear(cx);
            GlobalState::init(cx);
            GlobalState::suppress_text_selection(cx);
            selection_state.begin(point(px(1.), px(21.)), false, cx);
            selection_state.update(point(px(8.), px(21.)), cx);
            assert!(!selection_state.has_selection(cx));
        });
    }

    #[gpui::test]
    fn dead_participants_are_pruned_and_empty_selection_falls_back_safely(cx: &mut TestAppContext) {
        let selection_state = cx.update(|cx| {
            let selection_state = cx.new(|_| WindowSelectionState::default());
            let participant = FakeParticipant::new("gone", cx);
            selection_state.update(cx, |selection_state, cx| {
                participant.register(selection_state, 0., TextSelectionScopeId::default(), 0, cx)
            });
            selection_state
        });
        cx.update(|cx| {
            selection_state.update(cx, |selection_state, cx| {
                selection_state.begin(point(px(1.), px(1.)), false, cx);
                selection_state.update(point(px(8.), px(1.)), cx);
                selection_state.end(cx);

                assert_eq!(selection_state.selected_text(cx), "");
                assert!(!selection_state.has_selection(cx));
            });
        });
    }

    #[gpui::test]
    fn text_selection_namespace_reports_copies_ends_and_clears_selection(cx: &mut TestAppContext) {
        let (view, cx) = cx.add_window_view(|_, cx| WindowSelectionView {
            selection: TextSelectionHandle::new("copied", cx),
        });
        cx.update(|window, cx| {
            let selection = view.read(cx).selection.clone();
            let selection_state = WindowSelectionState::ensure(window, cx);
            selection_state.update(cx, |selection_state, cx| {
                FakeParticipant { selection }.register(
                    selection_state,
                    0.,
                    TextSelectionScopeId::default(),
                    0,
                    cx,
                );
                selection_state.begin(point(px(1.), px(1.)), false, cx);
                selection_state.update(point(px(8.), px(1.)), cx);
            });

            assert!(TextSelection::has_selection(window, cx));
            assert_eq!(TextSelection::selected_text(window, cx), "copied");
            TextSelection::end(window, cx);
            assert!(TextSelection::has_selection(window, cx));
            TextSelection::clear(window, cx);
            assert!(!TextSelection::has_selection(window, cx));
            assert_eq!(TextSelection::selected_text(window, cx), "");
        });
    }

    #[gpui::test]
    fn two_windows_isolate_selection_copy_clear_and_release_ownership(cx: &mut TestAppContext) {
        let first = cx.add_window(|_, cx| WindowOwnedSelectionView {
            selection: TextSelectionHandle::new("first", cx),
        });
        let second = cx.add_window(|_, cx| WindowOwnedSelectionView {
            selection: TextSelectionHandle::new("second", cx),
        });
        let first_selection = cx.update(|cx| first.read(cx).unwrap().selection.clone());
        let second_selection = cx.update(|cx| second.read(cx).unwrap().selection.clone());

        let first_state = cx
            .update_window(*first, |_, window, cx| {
                let _ = window.draw(cx);
                first_selection.set_local_selection(true, cx);
                assert_eq!(TextSelection::selected_text(window, cx), "first");
                WindowSelectionState::existing(window, cx)
                    .unwrap()
                    .downgrade()
            })
            .unwrap();
        cx.update_window(*second, |_, window, cx| {
            let _ = window.draw(cx);
            second_selection.set_local_selection(true, cx);
            assert_eq!(TextSelection::selected_text(window, cx), "second");
        })
        .unwrap();

        cx.update_window(*first, |_, window, cx| {
            TextSelection::clear(window, cx);
            assert_eq!(TextSelection::selected_text(window, cx), "");
        })
        .unwrap();
        cx.update_window(*second, |_, window, cx| {
            assert_eq!(TextSelection::selected_text(window, cx), "second");
        })
        .unwrap();

        cx.update_window(*first, |_, window, _| window.remove_window())
            .unwrap();
        cx.run_until_parked();

        assert!(first_state.upgrade().is_none());
        cx.update_window(*second, |_, window, cx| {
            assert_eq!(TextSelection::selected_text(window, cx), "second");
        })
        .unwrap();
        cx.update(|cx| {
            assert_eq!(cx.global::<SelectionStateRegistry>().0.len(), 1);
        });
    }

    #[gpui::test]
    fn copy_callback_can_reenter_window_and_handle_selection(cx: &mut TestAppContext) {
        let (_, cx) = cx.add_window_view(|_, _| SelectionElementOnlyView);
        cx.update(|window, cx| {
            let _ = window.draw(cx);
            let state = WindowSelectionState::existing(window, cx).unwrap();
            let selection = TextSelectionHandle::new("fallback", cx);
            let state_for_copy = state.clone();
            let selection_for_copy = selection.clone();
            selection.copy_with(
                move |cx: &mut App| {
                    state_for_copy.update(cx, |state, _| {
                        assert!(state.snapshot().is_some());
                    });
                    assert!(selection_for_copy.snapshot(cx).is_some());
                    selection_for_copy.set_fallback_copy_text("reentered", cx);
                    "reentrant copy".to_string()
                },
                cx,
            );
            state.update(cx, |state, cx| {
                FakeParticipant {
                    selection: selection.clone(),
                }
                .register(state, 0., TextSelectionScopeId::default(), 0, cx);
                state.begin(point(px(1.), px(1.)), false, cx);
                state.update(point(px(8.), px(1.)), cx);
                state.end(cx);
            });

            assert_eq!(TextSelection::selected_text(window, cx), "reentrant copy");
        });
    }

    #[gpui::test]
    fn cross_participant_selection_excludes_participants_outside_its_document_interval(
        cx: &mut TestAppContext,
    ) {
        cx.update(|cx| {
            let mut selection_state = WindowSelectionState::default();
            let first = FakeParticipant::new("first", cx);
            let second = FakeParticipant::new("second", cx);
            let third = FakeParticipant::new("third", cx);
            first.register(
                &mut selection_state,
                0.,
                TextSelectionScopeId::default(),
                0,
                cx,
            );
            second.register(
                &mut selection_state,
                20.,
                TextSelectionScopeId::default(),
                1,
                cx,
            );
            third.register(
                &mut selection_state,
                40.,
                TextSelectionScopeId::default(),
                2,
                cx,
            );

            selection_state.begin(point(px(1.), px(1.)), false, cx);
            selection_state.update(point(px(1.), px(25.)), cx);
            selection_state.end(cx);

            assert_eq!(selection_state.selected_text(cx), "first\nsecond");
            assert!(third.selection.snapshot(cx).is_none());
        });
    }

    #[gpui::test]
    fn changing_scope_clears_the_previous_scope_selection(cx: &mut TestAppContext) {
        cx.update(|cx| {
            let mut selection_state = WindowSelectionState::default();
            let base = FakeParticipant::new("base", cx);
            let modal = FakeParticipant::new("modal", cx);
            base.register(
                &mut selection_state,
                0.,
                TextSelectionScopeId::default(),
                0,
                cx,
            );
            modal.register(
                &mut selection_state,
                20.,
                TextSelectionScopeId::from_raw(1),
                1,
                cx,
            );

            selection_state.begin(point(px(1.), px(1.)), false, cx);
            selection_state.update(point(px(8.), px(1.)), cx);
            selection_state.end(cx);
            selection_state.set_active_scope(TextSelectionScopeId::from_raw(1), cx);

            assert!(!selection_state.has_selection(cx));
            assert!(base.selection.snapshot(cx).is_none());
        });
    }

    #[gpui::test]
    fn blank_only_drag_never_publishes_or_copies_selection(cx: &mut TestAppContext) {
        cx.update(|cx| {
            let mut selection_state = WindowSelectionState::default();
            let participant = FakeParticipant::new("participant", cx);
            participant.register(
                &mut selection_state,
                0.,
                TextSelectionScopeId::default(),
                0,
                cx,
            );

            selection_state.begin(point(px(200.), px(1.)), false, cx);
            selection_state.update(point(px(200.), px(8.)), cx);
            selection_state.end(cx);

            assert!(!selection_state.has_selection(cx));
            assert_eq!(selection_state.selected_text(cx), "");
            assert!(participant.selection.snapshot(cx).is_none());
        });
    }

    #[gpui::test]
    fn unmounted_selection_does_not_revive_when_the_participant_returns(cx: &mut TestAppContext) {
        cx.update(|cx| {
            let mut selection_state = WindowSelectionState::default();
            let participant = FakeParticipant::new("stale", cx);
            participant.register(
                &mut selection_state,
                0.,
                TextSelectionScopeId::default(),
                0,
                cx,
            );
            selection_state.begin(point(px(1.), px(1.)), false, cx);
            selection_state.update(point(px(8.), px(1.)), cx);
            selection_state.end(cx);
            assert_eq!(selection_state.selected_text(cx), "stale");

            selection_state.finish_frame(cx);
            selection_state.finish_frame(cx);
            assert_eq!(selection_state.selected_text(cx), "");
            assert!(participant.selection.snapshot(cx).is_none());
            participant.register(
                &mut selection_state,
                0.,
                TextSelectionScopeId::default(),
                0,
                cx,
            );
            assert_eq!(selection_state.selected_text(cx), "");
            assert!(participant.selection.snapshot(cx).is_none());

            selection_state.begin(point(px(1.), px(1.)), false, cx);
            selection_state.update(point(px(8.), px(1.)), cx);
            selection_state.end(cx);
            assert_eq!(selection_state.selected_text(cx), "stale");
        });
    }

    #[gpui::test]
    fn removing_an_unselected_participant_preserves_the_current_selection(cx: &mut TestAppContext) {
        cx.update(|cx| {
            let mut selection_state = WindowSelectionState::default();
            let selected = FakeParticipant::new("selected", cx);
            let unrelated = FakeParticipant::new("unrelated", cx);
            let scope = TextSelectionScopeId::default();
            selected.register(&mut selection_state, 0., scope, 0, cx);
            unrelated.register(&mut selection_state, 20., scope, 1, cx);
            selection_state.begin(point(px(1.), px(1.)), false, cx);
            selection_state.update(point(px(8.), px(1.)), cx);
            selection_state.end(cx);
            assert_eq!(selection_state.selected_text(cx), "selected");

            selection_state.finish_frame(cx);
            selected.register(&mut selection_state, 0., scope, 0, cx);
            selection_state.finish_frame(cx);
            assert_eq!(selection_state.selected_text(cx), "selected");
            unrelated.register(&mut selection_state, 20., scope, 1, cx);
            assert_eq!(selection_state.selected_text(cx), "selected");
        });
    }

    #[gpui::test]
    fn removing_either_range_endpoint_discards_the_shared_selection(cx: &mut TestAppContext) {
        for remove_anchor in [true, false] {
            cx.update(|cx| {
                let mut selection_state = WindowSelectionState::default();
                let anchor = FakeParticipant::new("anchor", cx);
                let cursor = FakeParticipant::new("cursor", cx);
                let scope = TextSelectionScopeId::default();
                anchor.register(&mut selection_state, 0., scope, 0, cx);
                cursor.register(&mut selection_state, 20., scope, 1, cx);
                selection_state.begin(point(px(1.), px(1.)), false, cx);
                selection_state.update(point(px(8.), px(21.)), cx);
                selection_state.end(cx);
                assert_eq!(selection_state.selected_text(cx), "anchor\ncursor");
                selection_state.finish_frame(cx);

                if remove_anchor {
                    cursor.register(&mut selection_state, 20., scope, 1, cx);
                } else {
                    anchor.register(&mut selection_state, 0., scope, 0, cx);
                }
                selection_state.finish_frame(cx);
                assert_eq!(selection_state.selected_text(cx), "");
                anchor.register(&mut selection_state, 0., scope, 0, cx);
                cursor.register(&mut selection_state, 20., scope, 1, cx);
                assert_eq!(selection_state.selected_text(cx), "");
            });
        }
    }

    #[gpui::test]
    fn clear_or_unmount_stops_auto_scroll_before_discarding_the_anchor(cx: &mut TestAppContext) {
        for unmount in [false, true] {
            let commands = Rc::new(RefCell::new(Vec::new()));
            let observed = commands.clone();
            let (mut selection_state, participant) = cx.update(|cx| {
                let selection_state = WindowSelectionState::default();
                let participant = FakeParticipant::new("scroll", cx);
                participant
                    .selection
                    .subscribe(
                        move |event, _| {
                            if let TextSelectionEvent::AutoScroll(delta) = event {
                                observed.borrow_mut().push(*delta);
                            }
                        },
                        cx,
                    )
                    .detach();
                (selection_state, participant)
            });
            cx.run_until_parked();
            cx.update(|cx| {
                participant.register(
                    &mut selection_state,
                    0.,
                    TextSelectionScopeId::default(),
                    0,
                    cx,
                );

                selection_state.begin(point(px(1.), px(1.)), false, cx);
                selection_state.update(point(px(1.), px(25.)), cx);
                if unmount {
                    selection_state.finish_frame(cx);
                    selection_state.finish_frame(cx);
                } else {
                    selection_state.clear(cx);
                }
            });
            cx.run_until_parked();
            assert!(commands.borrow().iter().any(Option::is_some));
            assert_eq!(commands.borrow().last(), Some(&None));
        }
    }

    #[gpui::test]
    fn drag_auto_scroll_stops_when_the_content_mask_collapses(cx: &mut TestAppContext) {
        let window = cx.add_window(|_, cx| WindowSelectionView {
            selection: TextSelectionHandle::new("unused", cx),
        });
        window
            .update(cx, |_, window, cx| {
                let state = cx.new(|_| WindowSelectionState::default());
                let participant = FakeParticipant::new("participant", cx);
                state.update(cx, |state, cx| {
                    participant.register(state, 0., TextSelectionScopeId::default(), 0, cx);
                    state.begin(point(px(1.), px(1.)), false, cx);
                });
                // The scrollable ancestor got clipped away mid-drag, so the
                // refreshed registration carries a collapsed content mask.
                let collapsed = Bounds::new(point(px(0.), px(0.)), size(px(100.), px(0.)));
                state.update(cx, |state, cx| {
                    state.register_participant(
                        participant.selection.clone(),
                        TextSelectionRegistration::new(
                            Hitbox {
                                id: HitboxId::placeholder(),
                                bounds: collapsed,
                                content_mask: ContentMask { bounds: collapsed },
                                behavior: HitboxBehavior::Normal,
                            },
                            collapsed,
                        )
                        .with_text_bounds(vec![collapsed]),
                        cx,
                    );
                    state.update_in_window(point(px(1.), px(50.)), window, cx);
                    assert!(!state.auto_scroll.is_active());
                    assert!(state.auto_scroll.last_drag_position.is_none());
                });
            })
            .unwrap();
    }

    #[gpui::test]
    fn pointer_moves_after_a_click_do_not_auto_scroll(cx: &mut TestAppContext) {
        let window = cx.add_window(|_, cx| WindowSelectionView {
            selection: TextSelectionHandle::new("unused", cx),
        });
        window
            .update(cx, |_, window, cx| {
                let state = cx.new(|_| WindowSelectionState::default());
                let participant = FakeParticipant::new("participant", cx);
                state.update(cx, |state, cx| {
                    participant.register(state, 0., TextSelectionScopeId::default(), 0, cx);
                    // A click on text keeps its anchor so shift-click can extend it.
                    state.begin(point(px(1.), px(1.)), false, cx);
                    state.end(cx);
                    assert!(state.anchor.is_some());

                    state.update_in_window(point(px(1.), px(50.)), window, cx);
                    assert!(!state.auto_scroll.is_active());
                });
            })
            .unwrap();
    }

    #[gpui::test]
    fn proxy_endpoints_break_equal_position_ties_by_document_order(cx: &mut TestAppContext) {
        cx.update(|cx| {
            let mut selection_state = WindowSelectionState::default();
            let later = FakeParticipant::new("later", cx);
            let earlier = FakeParticipant::new("earlier", cx);
            later.register(
                &mut selection_state,
                0.,
                TextSelectionScopeId::default(),
                2,
                cx,
            );
            earlier.register(
                &mut selection_state,
                0.,
                TextSelectionScopeId::default(),
                1,
                cx,
            );

            selection_state.begin(point(px(1.), px(1.)), false, cx);
            selection_state.update(point(px(200.), px(25.)), cx);
            let endpoint = selection_state.snapshot().unwrap().cursor();

            assert_eq!(endpoint.entity_id(), Some(earlier.selection.entity_id()));
        });
    }

    #[gpui::test]
    fn equal_area_hovered_participants_break_ties_by_document_order(cx: &mut TestAppContext) {
        cx.update(|cx| {
            for _ in 0..64 {
                let mut selection_state = WindowSelectionState::default();
                let later = FakeParticipant::new("later", cx);
                let earliest = FakeParticipant::new("earliest", cx);
                let middle = FakeParticipant::new("middle", cx);
                later.register(
                    &mut selection_state,
                    0.,
                    TextSelectionScopeId::default(),
                    30,
                    cx,
                );
                earliest.register(
                    &mut selection_state,
                    0.,
                    TextSelectionScopeId::default(),
                    10,
                    cx,
                );
                middle.register(
                    &mut selection_state,
                    0.,
                    TextSelectionScopeId::default(),
                    20,
                    cx,
                );

                selection_state.begin(point(px(1.), px(1.)), false, cx);
                selection_state.update(point(px(8.), px(1.)), cx);

                assert_eq!(
                    selection_state.snapshot().unwrap().anchor().entity_id(),
                    Some(earliest.selection.entity_id())
                );
            }
        });
    }

    #[gpui::test]
    fn text_selection_namespace_is_a_safe_no_op_until_the_element_is_rendered(
        cx: &mut TestAppContext,
    ) {
        let (_, cx) = cx.add_window_view(|_, cx| WindowSelectionView {
            selection: TextSelectionHandle::new("not enabled", cx),
        });
        cx.update(|window, cx| {
            assert!(!TextSelection::has_selection(window, cx));
            assert_eq!(TextSelection::selected_text(window, cx), "");
            TextSelection::clear(window, cx);
            TextSelection::end(window, cx);
            assert!(!TextSelection::has_selection(window, cx));
        });
    }

    #[gpui::test]
    fn unit_selection_element_supports_scope_and_registration_on_the_first_frame(
        cx: &mut TestAppContext,
    ) {
        let (view, cx) = cx.add_window_view(|_, cx| FirstFrameScopedSelectionView {
            selection: TextSelectionHandle::new("first frame", cx),
        });
        let selection = cx.update(|_, cx| view.read(cx).selection.clone());

        cx.update(|window, cx| {
            let _ = window.draw(cx);
            let state = WindowSelectionState::existing(window, cx).unwrap();
            assert_eq!(
                state.read(cx).active_scope,
                TextSelectionScopeId::from_raw(23)
            );
            assert!(
                state
                    .read(cx)
                    .participants
                    .borrow()
                    .contains_key(&selection.entity_id())
            );
        });
    }

    #[gpui::test]
    fn lazy_registration_does_not_enable_queries_without_the_element(cx: &mut TestAppContext) {
        let (_, cx) = cx.add_window_view(|_, cx| WindowSelectionView {
            selection: TextSelectionHandle::new("registered", cx),
        });
        cx.update(|window, cx| {
            let selection = TextSelectionHandle::new("registered", cx);
            selection.set_local_selection(true, cx);
            let bounds = Bounds::new(point(px(0.), px(0.)), size(px(100.), px(20.)));
            let hitbox = Hitbox {
                id: HitboxId::placeholder(),
                bounds,
                content_mask: ContentMask { bounds },
                behavior: HitboxBehavior::Normal,
            };
            selection.register(
                TextSelectionRegistration::new(hitbox, bounds).with_text_bounds(vec![bounds]),
                window,
                cx,
            );
            assert_eq!(TextSelection::selected_text(window, cx), "");
            assert!(!TextSelection::has_selection(window, cx));
            TextSelection::clear(window, cx);
            assert_eq!(TextSelection::selected_text(window, cx), "");
        });
    }

    struct RetainedSelectionText {
        text: Entity<crate::text::TextViewState>,
        renders: Rc<Cell<usize>>,
        scrollable: bool,
    }

    impl RetainedSelectionText {
        fn new(text: &str, cx: &mut App) -> Entity<Self> {
            let text = cx.new(|cx| crate::text::TextViewState::markdown(text, cx));
            cx.new(|_| Self {
                text,
                renders: Rc::new(Cell::new(0)),
                scrollable: false,
            })
        }
    }

    impl Render for RetainedSelectionText {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            self.renders.set(self.renders.get() + 1);
            div()
                .w(px(240.))
                .h(px(32.))
                .child(crate::text::TextView::new(&self.text).scrollable(self.scrollable))
        }
    }

    struct RetainedSelectionRoot {
        texts: Vec<Entity<RetainedSelectionText>>,
    }

    impl Render for RetainedSelectionRoot {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            div()
                .size_full()
                .flex()
                .flex_col()
                .child(TextSelectionLayer)
                .children(self.texts.iter().cloned())
        }
    }

    #[cfg(feature = "gpui-fast")]
    struct RetainedScrollingSelectionRoot {
        text: Entity<RetainedSelectionText>,
        unrelated: Entity<RetainedSelectionText>,
        scroll: gpui::ScrollHandle,
    }

    #[cfg(feature = "gpui-fast")]
    impl Render for RetainedScrollingSelectionRoot {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            div()
                .size_full()
                .flex()
                .flex_col()
                .child(TextSelectionLayer)
                .child(
                    div()
                        .id("scrolling-texts")
                        .w(px(240.))
                        .h(px(64.))
                        .flex_none()
                        .overflow_y_scroll()
                        .track_scroll(&self.scroll)
                        .child(div().h(px(352.)).child(self.text.clone())),
                )
                .child(self.unrelated.clone())
        }
    }

    fn draw_selection_frame(cx: &mut gpui::VisualTestContext) {
        cx.update(|window, cx| window.draw(cx).clear(cx));
        cx.run_until_parked();
    }

    /// Dispatch the gesture and copy in the same update, before either paint
    /// or the TextView's selection subscription can repair its copy cache.
    fn select_retained_texts(
        last: usize,
        release: bool,
        cx: &mut gpui::VisualTestContext,
    ) -> String {
        cx.update(|window, cx| {
            let state = WindowSelectionState::existing(window, cx).unwrap();
            let mut bounds = state
                .read(cx)
                .participants
                .borrow()
                .values()
                .map(|participant| participant.registration.text_bounds[0])
                .collect::<Vec<_>>();
            bounds.sort_by(|a, b| a.top().partial_cmp(&b.top()).unwrap());
            let start = point(bounds[0].left() + px(0.1), bounds[0].center().y);
            let end = point(bounds[last].right() - px(0.1), bounds[last].center().y);
            window.dispatch_event(
                gpui::PlatformInput::MouseDown(MouseDownEvent {
                    position: start,
                    button: MouseButton::Left,
                    click_count: 1,
                    ..Default::default()
                }),
                cx,
            );
            window.dispatch_event(
                gpui::PlatformInput::MouseMove(MouseMoveEvent {
                    position: end,
                    pressed_button: Some(MouseButton::Left),
                    ..Default::default()
                }),
                cx,
            );
            if release {
                window.dispatch_event(
                    gpui::PlatformInput::MouseUp(MouseUpEvent {
                        position: end,
                        button: MouseButton::Left,
                        modifiers: gpui::Modifiers::default(),
                        click_count: 1,
                    }),
                    cx,
                );
            }
            assert!(TextSelection::has_selection(window, cx));
            TextSelection::selected_text(window, cx)
        })
    }

    /// Uses only the original public TextView/selection APIs and real retained
    /// views, so this also runs against the implementation before this fix.
    #[cfg(feature = "gpui-fast")]
    #[gpui::test]
    fn active_selection_keeps_unrelated_text_views_retained(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let (root, cx) = cx.add_window_view(|_, cx| RetainedSelectionRoot {
            texts: ["alpha", "bravo", "charlie"]
                .into_iter()
                .map(|text| RetainedSelectionText::new(text, cx))
                .collect(),
        });
        draw_selection_frame(cx);
        draw_selection_frame(cx);
        assert_eq!(select_retained_texts(0, false, cx).trim(), "alpha");
        draw_selection_frame(cx);
        draw_selection_frame(cx);
        let texts = root.read_with(cx, |root, _| root.texts.clone());
        let unrelated = texts[1].read_with(cx, |text, _| text.renders.clone());
        let before = unrelated.get();
        let first_line = cx.update(|window, cx| {
            let state = WindowSelectionState::existing(window, cx).unwrap();
            state
                .read(cx)
                .participants
                .borrow()
                .values()
                .map(|participant| participant.registration.text_bounds[0])
                .min_by(|a, b| a.top().partial_cmp(&b.top()).unwrap())
                .unwrap()
        });
        for fraction in [0.2, 0.4, 0.6, 0.8] {
            cx.update(|window, cx| {
                window.dispatch_event(
                    gpui::PlatformInput::MouseMove(MouseMoveEvent {
                        position: point(
                            first_line.left() + first_line.size.width * fraction,
                            first_line.center().y,
                        ),
                        pressed_button: Some(MouseButton::Left),
                        ..Default::default()
                    }),
                    cx,
                );
            });
            draw_selection_frame(cx);
        }
        assert_ne!(
            cx.update(|window, cx| TextSelection::selected_text(window, cx))
                .trim(),
            "alpha"
        );
        assert_eq!(
            unrelated.get(),
            before,
            "active registration redrew an unrelated view"
        );
    }

    #[gpui::test]
    fn active_selection_frame_publication_visits_participants_linearly(cx: &mut TestAppContext) {
        for count in [4, 16] {
            cx.update(crate::init);
            let (_, cx) = cx.add_window_view(|_, cx| RetainedSelectionRoot {
                texts: (0..count)
                    .map(|_| RetainedSelectionText::new("text", cx))
                    .collect(),
            });
            draw_selection_frame(cx);
            draw_selection_frame(cx);
            assert_eq!(select_retained_texts(0, false, cx).trim(), "text");
            draw_selection_frame(cx);
            draw_selection_frame(cx);
            cx.update(|window, cx| {
                let state = WindowSelectionState::existing(window, cx).unwrap();
                state.read(cx).snapshot_visits.set(0);
                window.refresh();
                window.draw(cx).clear(cx);
            });
            cx.run_until_parked();
            cx.update(|window, cx| {
                let state = WindowSelectionState::existing(window, cx).unwrap();
                let visits = state.read(cx).snapshot_visits.get();
                assert!(
                    visits >= count,
                    "the frame must actually visit the participants"
                );
                assert!(
                    visits <= 3 * count,
                    "{count} participants required {visits} snapshot visits"
                );
            });
        }
    }

    #[cfg(feature = "gpui-fast")]
    #[gpui::test]
    fn scrolling_selected_text_does_not_rebuild_unrelated_document_order(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let (root, cx) = cx.add_window_view(|_, cx| {
            let scrolling = RetainedSelectionText::new("alpha\n\nbravo\n\ncharlie\n\ndelta", cx);
            scrolling.update(cx, |text, _| text.scrollable = true);
            RetainedSelectionRoot {
                texts: vec![scrolling, RetainedSelectionText::new("unrelated", cx)],
            }
        });
        draw_selection_frame(cx);
        draw_selection_frame(cx);
        assert_eq!(select_retained_texts(0, false, cx).trim(), "alpha");
        draw_selection_frame(cx);
        draw_selection_frame(cx);
        let unrelated = root.read_with(cx, |root, cx| root.texts[1].read(cx).renders.clone());
        let before = unrelated.get();
        let previous_offset = cx.update(|window, cx| {
            let state = WindowSelectionState::existing(window, cx).unwrap();
            let registration = state
                .read(cx)
                .participants
                .borrow()
                .values()
                .find(|participant| participant.registration.self_scroll)
                .unwrap()
                .registration
                .clone();
            let offset = registration.scroll_offset;
            window.dispatch_event(
                gpui::PlatformInput::Scroll(ScrollEvent {
                    position: registration.bounds.center(),
                    delta: ScrollDelta::Pixels(point(px(0.), px(-20.))),
                    touch_phase: TouchPhase::Moved,
                    ..Default::default()
                }),
                cx,
            );
            offset
        });
        for _ in 0..3 {
            draw_selection_frame(cx);
        }
        cx.update(|window, cx| {
            let state = WindowSelectionState::existing(window, cx).unwrap();
            let participants = state.read(cx).participants.borrow();
            let scrolling = participants
                .values()
                .find(|participant| participant.registration.self_scroll)
                .unwrap();
            assert_ne!(
                scrolling.registration.scroll_offset, previous_offset,
                "the content must actually scroll"
            );
            assert!(!state.read(cx).refresh_held_cursor.get());
        });
        assert_eq!(
            unrelated.get(),
            before,
            "a content scroll must not request a full order rebuild"
        );
    }

    #[cfg(feature = "gpui-fast")]
    #[gpui::test]
    fn ancestor_scrolling_keeps_unrelated_text_views_retained(cx: &mut TestAppContext) {
        for selected in [false, true] {
            cx.update(crate::init);
            let (root, cx) = cx.add_window_view(|_, cx| RetainedScrollingSelectionRoot {
                text: RetainedSelectionText::new("alpha", cx),
                unrelated: RetainedSelectionText::new("unrelated", cx),
                scroll: gpui::ScrollHandle::new(),
            });
            draw_selection_frame(cx);
            draw_selection_frame(cx);
            if selected {
                assert_eq!(select_retained_texts(0, true, cx).trim(), "alpha");
                draw_selection_frame(cx);
                draw_selection_frame(cx);
            }
            let (scroll, renders, text) = root.read_with(cx, |root, cx| {
                (
                    root.scroll.clone(),
                    root.unrelated.read(cx).renders.clone(),
                    root.text.read(cx).text.clone(),
                )
            });
            let before = renders.get();
            let bounds_before = text.read_with(cx, |text, _| text.bounds());
            for _ in 0..4 {
                let previous_offset = scroll.offset();
                cx.update(|window, cx| {
                    window.dispatch_event(
                        gpui::PlatformInput::Scroll(ScrollEvent {
                            position: point(px(20.), px(20.)),
                            delta: ScrollDelta::Pixels(point(px(0.), px(-4.))),
                            touch_phase: TouchPhase::Moved,
                            ..Default::default()
                        }),
                        cx,
                    );
                });
                for _ in 0..3 {
                    draw_selection_frame(cx);
                }
                assert_ne!(scroll.offset(), previous_offset, "the ancestor must scroll");
                assert_eq!(
                    renders.get(),
                    before,
                    "ancestor scrolling rebuilt an unrelated text view (selected: {selected})"
                );
                let copied = cx.update(|window, cx| TextSelection::selected_text(window, cx));
                assert_eq!(copied.trim(), if selected { "alpha" } else { "" });
            }
            assert_ne!(text.read_with(cx, |text, _| text.bounds()), bounds_before);
        }
    }

    #[gpui::test]
    fn retained_text_order_survives_partial_frames_insertion_and_reordering(
        cx: &mut TestAppContext,
    ) {
        cx.update(crate::init);
        let (root, cx) = cx.add_window_view(|_, cx| RetainedSelectionRoot {
            texts: ["alpha", "bravo", "charlie"]
                .into_iter()
                .map(|text| RetainedSelectionText::new(text, cx))
                .collect(),
        });
        draw_selection_frame(cx);
        draw_selection_frame(cx);
        let words = |text: String| {
            text.split_whitespace()
                .map(str::to_owned)
                .collect::<Vec<_>>()
        };
        assert_eq!(
            words(select_retained_texts(2, true, cx)),
            ["alpha", "bravo", "charlie"]
        );
        let texts = root.read_with(cx, |root, _| root.texts.clone());
        for _ in 0..3 {
            texts[1].update(cx, |_, cx| cx.notify());
            draw_selection_frame(cx);
            assert_eq!(
                words(cx.update(|window, cx| TextSelection::selected_text(window, cx))),
                ["alpha", "bravo", "charlie"]
            );
        }
        root.update(cx, |root, cx| {
            root.texts
                .insert(1, RetainedSelectionText::new("delta", cx));
            cx.notify();
        });
        for _ in 0..3 {
            draw_selection_frame(cx);
        }
        assert_eq!(
            words(cx.update(|window, cx| TextSelection::selected_text(window, cx))),
            ["alpha", "delta", "bravo", "charlie"]
        );
        root.update(cx, |root, cx| {
            root.texts.swap(1, 2);
            cx.notify();
        });
        for _ in 0..3 {
            draw_selection_frame(cx);
        }
        assert_eq!(
            words(cx.update(|window, cx| TextSelection::selected_text(window, cx))),
            ["alpha", "bravo", "delta", "charlie"]
        );
        #[cfg(feature = "gpui-fast")]
        {
            let renders = texts[0].read_with(cx, |text, _| text.renders.clone());
            let before = renders.get();
            for _ in 0..3 {
                draw_selection_frame(cx);
            }
            assert_eq!(renders.get(), before, "order recovery must settle");
        }
        // Keep the endpoint's entity alive after removing its element. A
        // later remount must not resurrect the retired window gesture.
        root.update(cx, |root, cx| {
            root.texts.pop();
            cx.notify();
        });
        draw_selection_frame(cx);
        draw_selection_frame(cx);
        assert!(
            cx.update(|window, cx| TextSelection::selected_text(window, cx))
                .is_empty()
        );
        root.update(cx, |root, cx| {
            root.texts.push(texts[2].clone());
            cx.notify();
        });
        draw_selection_frame(cx);
        assert!(
            cx.update(|window, cx| TextSelection::selected_text(window, cx))
                .is_empty()
        );
    }

    /// A view reading the window's selection state, beside selectable text,
    /// counting its renders.
    #[cfg(feature = "gpui-fast")]
    struct SelectionStateReader {
        renders: Rc<Cell<usize>>,
    }

    #[cfg(feature = "gpui-fast")]
    impl Render for SelectionStateReader {
        fn render(&mut self, window: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
            self.renders.set(self.renders.get() + 1);
            if let Some(state) = WindowSelectionState::existing(window, cx) {
                let _ = state.read(cx).participants.borrow().len();
            }
            div().size_full()
        }
    }

    /// The selectable text of a [`ToggleSelectionElementView`] beside a
    /// [`SelectionStateReader`].
    #[cfg(feature = "gpui-fast")]
    struct ReaderBesideSelectionView {
        text: gpui::Entity<ToggleSelectionElementView>,
        reader: gpui::Entity<SelectionStateReader>,
    }

    #[cfg(feature = "gpui-fast")]
    impl Render for ReaderBesideSelectionView {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            div()
                .size_full()
                .child(self.reader.clone())
                .child(self.text.clone())
        }
    }

    /// Selectable text drawn again, nothing about its selection changed,
    /// writes neither the window's selection state nor its own: a view
    /// reading them is retained, as it would not be had they changed.
    #[cfg(feature = "gpui-fast")]
    #[gpui::test]
    fn redrawing_selectable_text_leaves_its_readers_retained(cx: &mut TestAppContext) {
        let renders = Rc::new(Cell::new(0));
        let (view, cx) = cx.add_window_view(|_, cx| ReaderBesideSelectionView {
            text: cx.new(|cx| ToggleSelectionElementView {
                enabled: true,
                selection: TextSelectionHandle::new("text", cx),
            }),
            reader: cx.new(|_| SelectionStateReader {
                renders: renders.clone(),
            }),
        });
        let text = cx.update(|_, cx| view.read(cx).text.clone());
        let redraw = |cx: &mut gpui::VisualTestContext| {
            text.update(cx, |_, cx| cx.notify());
            cx.update(|window, cx| {
                let _ = window.draw(cx);
                window.simulate_next_frame(cx);
            });
            cx.run_until_parked();
        };
        redraw(cx);
        redraw(cx);
        let before = renders.get();
        for _ in 0..4 {
            redraw(cx);
        }
        assert_eq!(renders.get(), before, "the reader rendered again");
    }

    #[gpui::test]
    fn retained_selection_state_releases_and_does_not_resurrect_selection(cx: &mut TestAppContext) {
        let (view, cx) = cx.add_window_view(|_, cx| ToggleSelectionElementView {
            enabled: true,
            selection: TextSelectionHandle::new("local", cx),
        });
        let selection = cx.update(|_, cx| view.read(cx).selection.clone());
        cx.update(|window, cx| {
            let _ = window.draw(cx);
            selection.set_local_selection(true, cx);
            assert!(TextSelection::has_selection(window, cx));

            window.simulate_next_frame(cx);
            assert!(TextSelection::has_selection(window, cx));
            let _ = window.draw(cx);
            assert!(TextSelection::has_selection(window, cx));
        });
        view.update(cx, |view, cx| {
            view.enabled = false;
            cx.notify();
        });
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });
        cx.update(|window, cx| {
            window.simulate_next_frame(cx);
        });
        cx.update(|window, cx| {
            window.simulate_next_frame(cx);
        });
        cx.run_until_parked();
        cx.update(|window, cx| {
            assert!(!TextSelection::has_selection(window, cx));
            assert_eq!(TextSelection::selected_text(window, cx), "");
            assert!(!selection.has_local_selection(cx));
        });

        view.update(cx, |view, cx| {
            view.enabled = true;
            cx.notify();
        });
        cx.update(|window, cx| {
            let _ = window.draw(cx);
            assert!(!TextSelection::has_selection(window, cx));
            assert_eq!(TextSelection::selected_text(window, cx), "");
        });
    }

    #[gpui::test]
    fn mounted_selection_element_does_not_keep_an_idle_frame_queue_alive(cx: &mut TestAppContext) {
        let (_, cx) = cx.add_window_view(|_, _| SelectionElementOnlyView);
        cx.update(|window, cx| {
            let _ = window.draw(cx);
            assert_eq!(window.simulate_next_frame(cx), 0);
            assert_eq!(window.simulate_next_frame(cx), 0);
            assert!(live_text_selection_state(window, cx).is_some());
        });
    }

    #[gpui::test]
    fn selection_element_initializes_suppression_and_respects_bubble_suppression(
        cx: &mut TestAppContext,
    ) {
        let (_, cx) = cx.add_window_view(|_, _| SelectionElementOnlyView);
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });
        cx.simulate_mouse_down(
            point(px(1.), px(1.)),
            MouseButton::Left,
            gpui::Modifiers::default(),
        );
        cx.simulate_mouse_up(
            point(px(1.), px(1.)),
            MouseButton::Left,
            gpui::Modifiers::default(),
        );
        cx.update(|window, cx| {
            assert!(GlobalState::is_text_selection_suppressed(cx));
            assert!(!TextSelection::has_selection(window, cx));
        });
    }

    #[gpui::test]
    fn frame_sweep_keeps_a_participant_registered_before_the_selection_element_paints(
        cx: &mut TestAppContext,
    ) {
        cx.update(|cx| {
            let mut selection_state = WindowSelectionState::default();
            let participant = FakeParticipant::new("painted first", cx);
            participant.register(
                &mut selection_state,
                0.,
                TextSelectionScopeId::default(),
                0,
                cx,
            );
            selection_state.begin(point(px(1.), px(1.)), false, cx);
            selection_state.update(point(px(8.), px(1.)), cx);
            selection_state.end(cx);

            selection_state.finish_frame(cx);

            assert_eq!(selection_state.selected_text(cx), "painted first");
            assert!(participant.selection.snapshot(cx).is_some());
        });
    }

    #[gpui::test]
    fn two_selection_elements_schedule_only_one_post_frame_sweep(cx: &mut TestAppContext) {
        let (view, cx) = cx.add_window_view(|_, cx| DoubleSelectionElementView {
            selection: TextSelectionHandle::new("once", cx),
        });
        cx.update(|window, cx| {
            let selection_state = WindowSelectionState::ensure(window, cx);
            let selection = view.read(cx).selection.clone();
            selection_state.update(cx, |selection_state, cx| {
                FakeParticipant { selection }.register(
                    selection_state,
                    0.,
                    TextSelectionScopeId::default(),
                    0,
                    cx,
                );
                selection_state.begin(point(px(1.), px(1.)), false, cx);
                selection_state.update(point(px(8.), px(1.)), cx);
                selection_state.end(cx);
            });

            let _ = window.draw(cx);
            window.simulate_next_frame(cx);

            let items = selection_state.read(cx).copy_items(cx);
            assert_eq!(resolve_copy_items(items, cx), "once");
        });
    }

    #[gpui::test]
    fn duplicate_selection_elements_gate_real_pointer_gestures_and_reentrant_clear(
        cx: &mut TestAppContext,
    ) {
        let (view, cx) = cx.add_window_view(|_, cx| DoubleSelectionElementView {
            selection: TextSelectionHandle::new("once", cx),
        });
        let clear_count = Rc::new(Cell::new(0));
        cx.update(|window, cx| {
            let state = WindowSelectionState::ensure(window, cx);
            let state_for_clear = state.clone();
            let count = clear_count.clone();
            let selection = view.read(cx).selection.clone();
            selection
                .subscribe(
                    move |event, cx| {
                        if matches!(event, TextSelectionEvent::Cleared) {
                            count.set(count.get() + 1);
                            let _ = state_for_clear.read(cx).snapshot();
                        }
                    },
                    cx,
                )
                .detach();
            let _ = window.draw(cx);
        });

        cx.simulate_mouse_down(
            point(px(10.), px(10.)),
            MouseButton::Left,
            gpui::Modifiers::default(),
        );
        cx.simulate_mouse_up(
            point(px(10.), px(10.)),
            MouseButton::Left,
            gpui::Modifiers::default(),
        );
        cx.simulate_mouse_down(
            point(px(70.), px(10.)),
            MouseButton::Left,
            gpui::Modifiers {
                shift: true,
                ..Default::default()
            },
        );
        cx.simulate_mouse_up(
            point(px(70.), px(10.)),
            MouseButton::Left,
            gpui::Modifiers::default(),
        );
        cx.update(|window, cx| assert!(TextSelection::has_selection(window, cx)));

        cx.simulate_mouse_down(
            point(px(15.), px(10.)),
            MouseButton::Left,
            gpui::Modifiers::default(),
        );
        cx.simulate_mouse_move(
            point(px(85.), px(10.)),
            Some(MouseButton::Left),
            gpui::Modifiers::default(),
        );
        cx.simulate_mouse_up(
            point(px(85.), px(10.)),
            MouseButton::Left,
            gpui::Modifiers::default(),
        );
        cx.update(|window, cx| assert!(TextSelection::has_selection(window, cx)));
        assert_eq!(clear_count.get(), 3);
    }

    #[gpui::test]
    fn selection_layer_handles_real_double_and_triple_click_events(cx: &mut TestAppContext) {
        let (text, layout) = laid_out_runs(&["alpha beta"], cx).pop().unwrap();
        let (view, cx) = cx.add_window_view(|_, cx| DoubleSelectionElementView {
            selection: TextSelectionHandle::new("", cx),
        });
        cx.update(|window, cx| {
            let _ = window.draw(cx);
            let selection = view.read(cx).selection.clone();
            selection.resolve_content_key_with(|_, _| Some(TextSelectionContentKey::new(17)), cx);
            selection.update_runs(&[text_run(0, text.clone(), layout.clone())], cx);
        });

        let position = layout.position_for_index(7).unwrap();
        cx.simulate_event(MouseDownEvent {
            position,
            modifiers: gpui::Modifiers::default(),
            button: MouseButton::Left,
            click_count: 2,
            first_mouse: false,
        });
        cx.simulate_event(MouseUpEvent {
            position,
            modifiers: gpui::Modifiers::default(),
            button: MouseButton::Left,
            click_count: 2,
        });
        cx.update(|window, cx| {
            let selection = view.read(cx).selection.clone();
            selection.update_runs(&[text_run(0, text.clone(), layout.clone())], cx);
            assert_eq!(TextSelection::selected_text(window, cx), "beta");
            let snapshot = selection.snapshot(cx).unwrap();
            assert_eq!(
                snapshot.anchor().content_key(),
                Some(TextSelectionContentKey::new(17))
            );
            assert_eq!(
                snapshot.cursor().content_key(),
                Some(TextSelectionContentKey::new(17))
            );
        });

        cx.simulate_event(MouseDownEvent {
            position,
            modifiers: gpui::Modifiers::default(),
            button: MouseButton::Left,
            click_count: 3,
            first_mouse: false,
        });
        cx.simulate_event(MouseUpEvent {
            position,
            modifiers: gpui::Modifiers::default(),
            button: MouseButton::Left,
            click_count: 3,
        });
        cx.update(|window, cx| {
            let selection = view.read(cx).selection.clone();
            selection.update_runs(&[text_run(0, text, layout)], cx);
            assert_eq!(TextSelection::selected_text(window, cx), "alpha beta");
        });
    }

    /// Each text a [`crate::SelectableText`] of its own, one below the other.
    struct SelectableTextsView {
        texts: Vec<&'static str>,
    }

    impl Render for SelectableTextsView {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            div()
                .size_full()
                .child(TextSelectionLayer)
                .child(
                    div()
                        .w(px(400.))
                        .children(self.texts.iter().enumerate().map(|(ix, text)| {
                            crate::SelectableText::new(("text", ix), *text)
                                .document_order(ix as u64)
                        })),
                )
        }
    }

    /// The middle of the character at `index` of `text`, as it was painted.
    fn painted_position(text: &str, index: usize, window: &Window, cx: &App) -> Point<Pixels> {
        let state = WindowSelectionState::existing(window, cx).unwrap();
        let participants = state.read(cx).participants.borrow();
        participants
            .values()
            .filter_map(|registration| registration.participant.upgrade())
            .find_map(|participant| {
                let runs = participant.read(cx).runs.borrow();
                let run = runs.iter().find(|run| run.text.as_ref() == text)?;
                let position = run.layout.position_for_index(index)?;
                Some(point(
                    position.x + px(1.),
                    position.y + run.layout.line_height() / 2.,
                ))
            })
            .unwrap()
    }

    /// Presses the left button `click_count` times at the character `index`
    /// of `text`, and returns where.
    fn press_at(
        text: &str,
        index: usize,
        click_count: usize,
        shift: bool,
        cx: &mut gpui::VisualTestContext,
    ) -> Point<Pixels> {
        let position = cx.update(|window, cx| painted_position(text, index, window, cx));
        cx.simulate_event(MouseDownEvent {
            position,
            modifiers: gpui::Modifiers {
                shift,
                ..Default::default()
            },
            button: MouseButton::Left,
            click_count,
            first_mouse: false,
        });
        position
    }

    /// Drags the pressed button to the character `index` of `text`, and
    /// returns the text selected there.
    fn drag_to(text: &str, index: usize, cx: &mut gpui::VisualTestContext) -> String {
        let position = cx.update(|window, cx| painted_position(text, index, window, cx));
        cx.simulate_event(MouseMoveEvent {
            position,
            pressed_button: Some(MouseButton::Left),
            modifiers: gpui::Modifiers::default(),
        });
        painted_selection(cx)
    }

    fn release(click_count: usize, cx: &mut gpui::VisualTestContext) {
        let position = cx.update(|window, _| window.mouse_position());
        cx.simulate_event(MouseUpEvent {
            position,
            modifiers: gpui::Modifiers::default(),
            button: MouseButton::Left,
            click_count,
        });
    }

    fn painted_selection(cx: &mut gpui::VisualTestContext) -> String {
        cx.update(|window, cx| {
            let _ = window.draw(cx);
            TextSelection::selected_text(window, cx)
        })
    }

    #[gpui::test]
    fn double_click_drag_extends_the_selection_by_words(cx: &mut TestAppContext) {
        let (_, cx) = cx.add_window_view(|_, _| SelectableTextsView {
            texts: vec!["one two three", "four five six"],
        });
        painted_selection(cx);

        press_at("one two three", 5, 2, false, cx);
        assert_eq!(painted_selection(cx), "two");
        assert_eq!(drag_to("one two three", 9, cx), "two three");
        // Backward, the whole of the word the drag started from stays.
        assert_eq!(drag_to("one two three", 1, cx), "one two");
        assert_eq!(drag_to("four five six", 6, cx), "two three\nfour five");
        release(2, cx);
        assert_eq!(painted_selection(cx), "two three\nfour five");
    }

    #[gpui::test]
    fn triple_click_drag_extends_the_selection_by_lines(cx: &mut TestAppContext) {
        let text = "first line\nsecond line\nthird line";
        let (_, cx) = cx.add_window_view(|_, _| SelectableTextsView { texts: vec![text] });
        painted_selection(cx);

        press_at(text, 13, 3, false, cx);
        assert_eq!(painted_selection(cx), "second line");
        assert_eq!(drag_to(text, 25, cx), "second line\nthird line");
        assert_eq!(drag_to(text, 2, cx), "first line\nsecond line");
        release(3, cx);
        assert_eq!(painted_selection(cx), "first line\nsecond line");
    }

    #[gpui::test]
    fn shift_click_after_a_double_click_extends_by_words(cx: &mut TestAppContext) {
        let text = "one two three";
        let (_, cx) = cx.add_window_view(|_, _| SelectableTextsView { texts: vec![text] });
        painted_selection(cx);

        press_at(text, 5, 2, false, cx);
        release(2, cx);
        press_at(text, 9, 1, true, cx);
        release(1, cx);
        assert_eq!(painted_selection(cx), "two three");
        press_at(text, 1, 1, true, cx);
        release(1, cx);
        assert_eq!(painted_selection(cx), "one two");

        // A plain click ends the word selection: a drag from it is by characters.
        press_at(text, 5, 1, false, cx);
        assert_eq!(drag_to(text, 9, cx), "wo t");
        release(1, cx);
    }
}
