use std::{cell::RefCell, ops::RangeInclusive, rc::Rc};

use crate::{
    GlobalState, TextSelectionContentKey, TextSelectionCoverage, TextSelectionEndpoint,
    TextSelectionEvent, TextSelectionHandle, TextSelectionRegistration, TextSelectionRun,
    TextSelectionSnapshot,
};
use gpui::{App, Bounds, EntityId, Hitbox, Pixels, Point, WeakEntity, Window};

use super::{
    TextViewState, inline::InlineSelectionProjection,
    inline_object::InlineObjectSelectionProjection, node::CustomBlockSelectionProjection,
};

#[derive(Clone, Copy, Debug, PartialEq)]
struct CachedBlockEndpoint {
    endpoint: TextSelectionEndpoint,
    block_ix: Option<usize>,
}

#[derive(Default)]
struct VirtualBlockSelection {
    anchor: Option<CachedBlockEndpoint>,
    cursor: Option<CachedBlockEndpoint>,
    coverage: TextSelectionCoverage,
    is_selecting: bool,
}

impl VirtualBlockSelection {
    fn update(&mut self, snapshot: Option<TextSelectionSnapshot>, entity_id: EntityId) -> bool {
        let Some(snapshot) = snapshot else {
            let changed = self.anchor.is_some() || self.cursor.is_some();
            *self = Self::default();
            return changed;
        };

        // Origin and scroll changes only alter the window projection. They must
        // not turn a held logical range back into a hit test in reflowed text.
        let changed = self.anchor.map(|cached| cached.endpoint) != Some(snapshot.anchor())
            || self.cursor.map(|cached| cached.endpoint) != Some(snapshot.cursor())
            || self.coverage != snapshot.coverage()
            || self.is_selecting != snapshot.is_selecting();
        self.coverage = snapshot.coverage();
        self.is_selecting = snapshot.is_selecting();

        Self::update_endpoint(&mut self.anchor, snapshot.anchor(), entity_id);
        Self::update_endpoint(&mut self.cursor, snapshot.cursor(), entity_id);
        changed
    }

    fn update_endpoint(
        cached: &mut Option<CachedBlockEndpoint>,
        endpoint: TextSelectionEndpoint,
        entity_id: EntityId,
    ) {
        if cached.is_some_and(|cached| cached.endpoint == endpoint) {
            return;
        }
        let block_ix = (endpoint.entity_id() == Some(entity_id))
            .then(|| endpoint.content_key().map(|key| key.value() as usize))
            .flatten();
        *cached = Some(CachedBlockEndpoint { endpoint, block_ix });
    }

    fn block_range(&self, entity_id: EntityId, last: usize) -> Option<RangeInclusive<usize>> {
        let anchor = self.anchor?;
        let cursor = self.cursor?;
        match self.coverage {
            TextSelectionCoverage::Full => Some(0..=last),
            TextSelectionCoverage::FromStart => Some(0..=anchor.block_ix.or(cursor.block_ix)?),
            TextSelectionCoverage::ToEnd => Some(anchor.block_ix.or(cursor.block_ix)?..=last),
            TextSelectionCoverage::Bounded => {
                if anchor.endpoint.entity_id() != Some(entity_id)
                    || cursor.endpoint.entity_id() != Some(entity_id)
                {
                    return None;
                }
                let (anchor, cursor) = (anchor.block_ix?, cursor.block_ix?);
                Some(anchor.min(cursor)..=anchor.max(cursor))
            }
        }
    }
}

/// TextView's renderer-specific bridge to base-owned window selection.
#[derive(Clone)]
pub(super) struct TextViewSelectionAdapter {
    selection: TextSelectionHandle,
    /// What the view's text painted this frame, shared by the adapter's
    /// clones. Inlines report it as they paint, through a read of the view's
    /// state: reporting it is not a change of the view.
    frame: Rc<RefCell<PaintedText>>,
    layout_revision: Option<usize>,
}

/// The text a [`TextViewSelectionAdapter`]'s view painted this frame.
#[derive(Default)]
struct PaintedText {
    text_bounds: Vec<Bounds<Pixels>>,
    text_runs: Vec<TextSelectionRun>,
    /// Each with the table cell it painted in, if any.
    copy_projections: Vec<(CopyProjection, Option<Bounds<Pixels>>)>,
    /// The caret boxes at the first and last selected character painted this
    /// frame, where the touch handles go.
    selection_edges: Option<(Bounds<Pixels>, Bounds<Pixels>)>,
}

pub(super) enum CopyProjection {
    Text(InlineSelectionProjection),
    InlineObject(InlineObjectSelectionProjection),
    CustomBlock(CustomBlockSelectionProjection),
}

impl CopyProjection {
    fn reset(&self) {
        if let Self::Text(projection) = self {
            projection.reset();
        }
    }

    fn project(&self, start: Point<Pixels>, end: Point<Pixels>) {
        match self {
            Self::Text(projection) => projection.project(start, end),
            Self::InlineObject(projection) => projection.project(start, end),
            Self::CustomBlock(projection) => projection.project(start, end),
        }
    }

    /// Selects nothing: the selection started in a table cell this is not in.
    fn deselect(&self) {
        match self {
            Self::Text(projection) => projection.reset(),
            Self::InlineObject(projection) => projection.deselect(),
            Self::CustomBlock(projection) => projection.deselect(),
        }
    }
}

impl TextViewSelectionAdapter {
    pub(super) fn new(view: WeakEntity<TextViewState>, cx: &mut App) -> Self {
        let selection = TextSelectionHandle::new("", cx);
        let selection_id = selection.entity_id();
        let virtual_blocks = Rc::new(RefCell::new(VirtualBlockSelection::default()));
        let frame = Rc::new(RefCell::new(PaintedText::default()));

        let view_for_events = view.clone();
        let blocks_for_events = virtual_blocks.clone();
        selection
            .subscribe(
                move |event, cx| match event {
                    TextSelectionEvent::SelectionChanged(snapshot) => {
                        let snapshot = *snapshot;
                        let _ = view_for_events.update(cx, |state, cx| {
                            let changed = blocks_for_events
                                .borrow_mut()
                                .update(snapshot, selection_id);
                            if snapshot.is_none() || changed {
                                state.preserve_inline_selection = false;
                            }
                            state.is_selecting =
                                snapshot.is_some_and(|snapshot| snapshot.is_selecting());
                            if state.is_selecting {
                                state.end_multi_click_selection(cx);
                            }
                            cx.notify();
                        });
                    }
                    TextSelectionEvent::AutoScroll(delta) => {
                        let delta = *delta;
                        let _ = view_for_events.update(cx, |state, cx| {
                            if state.scrollable {
                                state.set_auto_scroll(delta, cx);
                            } else if delta.is_none() {
                                state.stop_auto_scroll();
                            }
                        });
                    }
                    TextSelectionEvent::Cleared => {}
                    TextSelectionEvent::TouchSelectionChanged => {
                        let _ = view_for_events.update(cx, |_, cx| cx.notify());
                    }
                },
                cx,
            )
            .detach();

        let view_for_clear = view.clone();
        let blocks_for_clear = virtual_blocks.clone();
        selection.clear_with(
            move |cx| {
                blocks_for_clear.replace(VirtualBlockSelection::default());
                let _ = view_for_clear.update(cx, |state, cx| {
                    state.reset_selection();
                    cx.notify();
                });
            },
            cx,
        );

        let view_for_copy = view.clone();
        let blocks_for_copy = virtual_blocks.clone();
        let frame_for_copy = frame.clone();
        selection.copy_with(
            move |cx| {
                let Some(view) = view_for_copy.upgrade() else {
                    return String::new();
                };
                let state = view.read(cx);
                if !state.has_current_copy_document() {
                    return String::new();
                }
                // Read the handle itself: event subscribers may not have run
                // yet when input and Copy arrive in the same App update.
                let mut current = VirtualBlockSelection::default();
                current.update(state.selection_adapter.selection.snapshot(cx), selection_id);
                let previous = blocks_for_copy.borrow();
                let range_changed = current.anchor != previous.anchor
                    || current.cursor != previous.cursor
                    || current.coverage != previous.coverage;
                drop(previous);
                let anchor_cell = state.selection_adapter.selection.table_cell_selection(cx);
                // Gesture snapshots are current before paint. Refresh the rich
                // document's byte ranges from its retained native layouts
                // before its existing Plain/Source serializer reads them.
                if !state.has_view_selection()
                    && (!state.preserve_inline_selection || range_changed)
                {
                    if let Some((start, end)) = state.selection_points(cx) {
                        // Only represented source states are refreshed.
                        // Offscreen AST selections retain their logical ends.
                        let frame = frame_for_copy.borrow();
                        for (projection, _) in &frame.copy_projections {
                            projection.reset();
                        }
                        for (projection, cell) in &frame.copy_projections {
                            match crate::global_state::confine_to_cell(
                                anchor_cell.map(|bounds| (start, bounds)),
                                *cell,
                                start,
                                end,
                            ) {
                                Some((start, end)) => projection.project(start, end),
                                None => projection.deselect(),
                            }
                        }
                    }
                }
                let last = state.parsed_content.document.blocks.len().saturating_sub(1);
                let blocks = if anchor_cell.is_some() {
                    let Some(anchor) = current
                        .anchor
                        .filter(|anchor| anchor.endpoint.entity_id() == Some(selection_id))
                    else {
                        return String::new();
                    };
                    anchor.block_ix.map(|ix| ix..=ix)
                } else {
                    current.block_range(selection_id, last)
                };
                state.selected_text_in(blocks)
            },
            cx,
        );

        let view_for_content_key = view.clone();
        selection.resolve_content_key_with(
            move |point, cx| {
                let view = view_for_content_key.upgrade()?;
                view.read(cx)
                    .block_ix_at(point.y)
                    .map(|block| TextSelectionContentKey::new(block as u64))
            },
            cx,
        );

        selection.focus_with(
            move |window, cx| {
                let Some(view) = view.upgrade() else {
                    return;
                };
                let focus_handle = view.read(cx).focus_handle.clone();
                view.update(cx, |state, _| state.is_selecting = true);
                focus_handle.focus(window, cx);
            },
            cx,
        );

        Self {
            selection,
            frame,
            layout_revision: None,
        }
    }

    pub(super) fn update_layout_revision(&mut self, revision: usize, is_selecting: bool) -> bool {
        let changed = self
            .layout_revision
            .is_some_and(|previous| previous != revision);
        if !changed || !is_selecting {
            self.layout_revision = Some(revision);
        }
        changed && !is_selecting
    }

    pub(super) fn clear_copy_projections(&self, cx: &App) {
        self.selection.clear_table_cell_selection(cx);
        self.frame.borrow_mut().copy_projections.clear();
    }

    /// Registers `projection` as it paints, with the table cell it is in.
    pub(super) fn register_copy_projection(&self, projection: CopyProjection, cx: &App) {
        let cell = GlobalState::global(cx).table_cell();
        self.frame
            .borrow_mut()
            .copy_projections
            .push((projection, cell));
    }

    pub(super) fn begin_frame(&self) {
        let mut frame = self.frame.borrow_mut();
        frame.text_bounds.clear();
        frame.text_runs.clear();
        frame.copy_projections.clear();
        frame.selection_edges = None;
    }

    /// Records one inline's painted selection ends. Inlines paint in document
    /// order, so the first start and the last end are the view's.
    pub(super) fn register_selection_edges(&self, start: Bounds<Pixels>, end: Bounds<Pixels>) {
        let mut frame = self.frame.borrow_mut();
        let first = frame.selection_edges.map_or(start, |(first, _)| first);
        frame.selection_edges = Some((first, end));
    }

    pub(super) fn register_text_run(&self, run: TextSelectionRun) {
        self.frame.borrow_mut().text_runs.push(run);
    }

    pub(super) fn register_inline(&self, bounds: Vec<Bounds<Pixels>>) {
        self.frame.borrow_mut().text_bounds.extend(bounds);
    }

    #[allow(clippy::too_many_arguments)]
    pub(super) fn register(
        &self,
        hitbox: Hitbox,
        bounds: Bounds<Pixels>,
        scroll_offset: Point<Pixels>,
        self_scroll: bool,
        window: &mut Window,
        cx: &mut App,
    ) {
        let frame = self.frame.borrow();
        self.selection.set_hit_test_runs(&frame.text_runs, cx);
        let registration = TextSelectionRegistration::new(hitbox, bounds)
            .with_scroll_offset(scroll_offset)
            .in_paint_order()
            .with_text_bounds(frame.text_bounds.clone())
            .with_self_scroll(self_scroll)
            .with_rendered_element(&self.selection, window, cx);
        let registration = match frame.selection_edges {
            Some((start, end)) => registration.with_selection_edges(start, end),
            None => registration,
        };
        drop(frame);
        self.selection.register(registration, window, cx);
    }

    /// Lays out the touch handles this view owns; see
    /// [`TextSelectionHandle::prepaint_touch_handles`].
    pub(super) fn prepaint_touch_handles(
        &self,
        window: &mut Window,
        cx: &App,
    ) -> crate::TouchHandleLayout {
        self.selection.prepaint_touch_handles(window, cx)
    }

    /// Paints the touch handles this view owns, after its content for the
    /// frame; see [`TextSelectionHandle::paint_touch_handles`].
    pub(super) fn paint_touch_handles(
        &self,
        layout: &crate::TouchHandleLayout,
        color: gpui::Hsla,
        window: &mut Window,
        cx: &mut App,
    ) {
        self.selection
            .paint_touch_handles(layout, color, window, cx);
    }

    pub(super) fn record_table_cell(&self, bounds: Bounds<Pixels>, cx: &App) {
        self.selection.record_table_cell(bounds, cx);
    }

    pub(super) fn painted_selection_points(
        &self,
        cx: &App,
    ) -> Option<(Point<Pixels>, Point<Pixels>)> {
        let (anchor, cursor) = self.selection_points(cx)?;
        crate::global_state::confine_to_cell(
            self.selection
                .table_cell_selection(cx)
                .map(|bounds| (anchor, bounds)),
            GlobalState::global(cx).table_cell(),
            anchor,
            cursor,
        )
    }

    pub(super) fn selection_points(&self, cx: &App) -> Option<(Point<Pixels>, Point<Pixels>)> {
        let points = self.selection.snapshot(cx)?.window_points()?;
        Some((points.anchor(), points.cursor()))
    }

    pub(super) fn set_local_selection(&self, active: bool, cx: &mut App) {
        self.selection.set_local_selection(active, cx);
    }

    /// See [`TextSelectionHandle::hold_multi_click`].
    pub(super) fn hold_multi_click(
        &self,
        start: Bounds<Pixels>,
        end: Bounds<Pixels>,
        click_count: usize,
        cx: &mut App,
    ) {
        self.selection.hold_multi_click(start, end, click_count, cx);
    }

    pub(super) fn is_part_of_window_selection(&self, cx: &App) -> bool {
        let id = self.selection.entity_id();
        self.selection.snapshot(cx).is_some_and(|snapshot| {
            snapshot.anchor().entity_id() == Some(id) || snapshot.cursor().entity_id() == Some(id)
        })
    }

    pub(super) fn has_selection_snapshot(&self, cx: &App) -> bool {
        self.selection.snapshot(cx).is_some()
    }

    #[cfg(test)]
    pub(super) fn text_bounds(&self) -> Vec<Bounds<Pixels>> {
        self.frame.borrow().text_bounds.clone()
    }

    /// Just inside the character at `index` of the text run painted this
    /// frame with `text`, in the middle of its row.
    #[cfg(test)]
    pub(super) fn text_position(&self, text: &str, index: usize) -> Point<Pixels> {
        let frame = self.frame.borrow();
        let layout = frame
            .text_runs
            .iter()
            .find(|run| run.text().as_ref() == text)
            .unwrap()
            .layout();
        layout.position_for_index(index).unwrap()
            + gpui::point(gpui::px(1.), layout.line_height() / 2.)
    }

    #[cfg(test)]
    pub(super) fn first_text_position(&self, index: usize) -> Point<Pixels> {
        let frame = self.frame.borrow();
        let layout = frame.text_runs.first().unwrap().layout();
        layout.position_for_index(index).unwrap()
            + gpui::point(Pixels::ZERO, layout.line_height() / 2.)
    }
}
