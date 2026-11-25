//! A tab group's behavior, with no appearance of its own.

use crate::TestSupportExt as _;
use std::{rc::Rc, sync::Arc};

use gpui::{
    AnyElement, AnyView, App, Bounds, Context, Div, DragMoveEvent, Empty, EventEmitter,
    FocusHandle, Focusable, InteractiveElement as _, IntoElement, ParentElement as _, Pixels,
    Render, Stateful, Styled as _, WeakEntity, Window, div, prelude::FluentBuilder as _, px,
};

use crate::Placement;

use super::{
    active::ActiveTracker,
    drag::{
        AnyDrag, DragPanel, DropIndicator, DropPlaceholderBounds, DropTarget, ITEM_DRAG_SESSION_ID,
        split_placement_at,
    },
    layout::{InsertTarget, NodeId, PanelId},
    panel::PanelView,
};

/// Behavior a tab group cannot carry out on its own.
///
/// Every variant here ends in an edit to the layout tree, and the tree belongs
/// to the container that owns this group. Reporting the intent instead of
/// reaching for the container keeps the whole detach-then-reinsert dance —
/// and the reentrancy it used to provoke — out of the group entirely.
#[non_exhaustive]
pub enum TabGroupEvent {
    /// A panel was dropped on this group. `target` says where in the tree it
    /// lands; the container applies it as a single `PaneTree::move_panel`.
    Drop {
        panel: PanelId,
        source: NodeId,
        target: InsertTarget,
    },
    /// A host-owned drag landed on this group.
    DragDrop { item: AnyDrag, target: DropTarget },
    /// The user asked to close `panel`.
    ClosePanel { panel: PanelId },
    /// The displayed tab changed, so the tree's stored `active_ix` is stale.
    ActiveChanged { ix: usize },
    /// This group asked to fill the whole dock. The container installs the
    /// *group* as its zoomed view, chrome and all — the tab bar is where the
    /// control that zooms back out lives.
    ZoomIn,
    /// This group gave the dock back.
    ZoomOut,
}

/// Everything the container knows about a group's place in the dock.
///
/// Pushed as one value rather than one setter per fact. These are read
/// together, and a container that updates one while leaving another stale
/// describes a dock that cannot exist — a group beside siblings that still
/// reports itself alone. Choosing a constructor forces the container kind to be
/// stated; anything a constructor does not grant stays off, so a container
/// that forgets something gets a group that does less rather than more.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct TabGroupConstraints {
    alone: bool,
    dock_locked: bool,
    collapsed: bool,
    closable: bool,
}

impl TabGroupConstraints {
    /// A group with nowhere to go: locked, alone, unclosable. What a group
    /// starts as, before any container has placed it.
    pub fn sealed() -> Self {
        Self {
            alone: true,
            dock_locked: true,
            collapsed: false,
            closable: false,
        }
    }

    /// A group in a split layout. `alone` when nothing sits beside it, which
    /// is what stops its last visible panel being dragged out and leaving the
    /// dock empty.
    pub fn in_split(alone: bool) -> Self {
        Self {
            alone,
            dock_locked: false,
            collapsed: false,
            closable: true,
        }
    }

    /// Whether the dock as a whole forbids rearranging.
    pub fn dock_locked(mut self, dock_locked: bool) -> Self {
        self.dock_locked = dock_locked;
        self
    }

    /// Whether the group is folded away to a strip of tabs with no content.
    pub fn collapsed(mut self, collapsed: bool) -> Self {
        self.collapsed = collapsed;
        self
    }

    /// Whether the container allows this group's panels to be closed at all.
    /// A dock's last group sets this `false` so the dock cannot be emptied.
    pub fn closable(mut self, closable: bool) -> Self {
        self.closable = closable;
        self
    }

    /// Whether nothing sits beside this group in its tree.
    pub fn is_alone(&self) -> bool {
        self.alone
    }

    /// Whether the group's place in the dock is fixed.
    ///
    /// The dock-wide lock is the whole of it. A tab group only ever sits
    /// inside a split, so there is no second way for a container to pin one
    /// down, and no separate `is_dock_locked` reader that would answer
    /// identically.
    pub fn is_locked(&self) -> bool {
        self.dock_locked
    }

    pub fn is_collapsed(&self) -> bool {
        self.collapsed
    }

    pub fn is_closable(&self) -> bool {
        self.closable
    }
}

/// A tab group's behavior, with no appearance of its own.
///
/// It owns the panel list mirrored from the layout tree, the displayed index,
/// the focus handle, drag and drop hit state, and the zoom flag. Everything
/// visible is produced by the [`TabGroupRenderer`] the host installs.
///
/// The group holds no handle on its container. What the container knows — the
/// facts in [`TabGroupConstraints`] — is pushed in, and what the group needs
/// done is emitted as a [`TabGroupEvent`]. That keeps a group constructible,
/// and testable, on its own.
pub struct TabGroup {
    node: NodeId,
    /// Handed to the callbacks in [`TabGroupContext`], which are built from a
    /// plain `&App` and so cannot ask for it.
    this: WeakEntity<Self>,
    panels: Vec<Arc<dyn PanelView>>,
    active_ix: usize,
    zoomed: bool,
    constraints: TabGroupConstraints,
    focus_handle: FocusHandle,
    active: ActiveTracker,
    drop_indicator: Option<DropIndicator>,
    renderer: Rc<dyn TabGroupRenderer>,
}

impl TabGroup {
    /// Only a container builds groups: a group is the entity mirror of one
    /// `Tabs` node, and it is created when that node first appears in the
    /// tree. `DockArea` is the only caller outside tests.
    pub(crate) fn new(node: NodeId, _window: &mut Window, cx: &mut Context<Self>) -> Self {
        Self {
            node,
            this: cx.weak_entity(),
            panels: Vec::new(),
            active_ix: 0,
            zoomed: false,
            // A group that no container has placed yet can do nothing.
            constraints: TabGroupConstraints::sealed(),
            focus_handle: cx.focus_handle(),
            active: ActiveTracker::default(),
            drop_indicator: None,
            renderer: Rc::new(BareTabGroup),
        }
    }

    pub fn with_renderer(mut self, renderer: Rc<dyn TabGroupRenderer>) -> Self {
        self.renderer = renderer;
        self
    }

    /// The `Tabs` node this group mirrors.
    pub fn node(&self) -> NodeId {
        self.node
    }

    pub fn panels(&self) -> &[Arc<dyn PanelView>] {
        &self.panels
    }

    pub fn active_ix(&self) -> usize {
        self.active_ix
    }

    /// The panel currently on screen, which is the displayed tab unless it has
    /// gone invisible, in which case rendering falls back to the first visible
    /// panel.
    pub fn active_panel(&self, cx: &App) -> Option<Arc<dyn PanelView>> {
        match self.panels.get(self.active_ix) {
            Some(panel) if panel.visible(cx) => Some(panel.clone()),
            Some(_) => self.visible_panels(cx).next(),
            None => None,
        }
    }

    pub fn is_zoomed(&self) -> bool {
        self.zoomed
    }

    pub fn is_collapsed(&self) -> bool {
        self.constraints.is_collapsed()
    }

    /// Whether closing this group's displayed panel is allowed at all.
    ///
    /// Mirrors the old `TabPanel::closable`: the container must permit it, the
    /// group must have somewhere to go, and the displayed panel must itself be
    /// closable.
    pub fn is_closable(&self, cx: &App) -> bool {
        self.constraints.is_closable()
            && self.draggable(cx)
            && self
                .active_panel(cx)
                .is_some_and(|panel| panel.closable(cx))
    }

    /// Display `ix`, if it names a tab that is not already displayed.
    pub fn select_tab(&mut self, ix: usize, window: &mut Window, cx: &mut Context<Self>) {
        if ix >= self.panels.len() || ix == self.active_ix {
            return;
        }

        self.active_ix = ix;
        self.focus_active_panel(window, cx);
        self.schedule_active_sync(window, cx);
        cx.emit(TabGroupEvent::ActiveChanged { ix });
        cx.notify();
    }

    /// Ask the container to close `panel`. Nothing happens for a panel that is
    /// not in this group, or when either the group or the panel refuses.
    pub fn close_panel(&mut self, panel: PanelId, cx: &mut Context<Self>) {
        if !self.constraints.is_closable() {
            return;
        }
        // A dock's last group has nowhere to go and must stay.
        if !self.draggable(cx) {
            return;
        }

        let closable = self
            .panels
            .iter()
            .any(|candidate| candidate.panel_id(cx) == panel && candidate.closable(cx));
        if !closable {
            return;
        }

        cx.emit(TabGroupEvent::ClosePanel { panel });
        cx.notify();
    }

    pub fn toggle_zoom(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        self.set_zoomed(!self.zoomed, window, cx);
    }

    /// A snapshot of everything a skin needs to draw this group.
    pub fn context(&self, cx: &App) -> TabGroupContext {
        let group = self.this.clone();

        TabGroupContext {
            node: self.node,
            panels: self.panels.clone(),
            active_panel: self.active_panel(cx),
            active_ix: self.active_ix,
            zoomed: self.zoomed,
            constraints: self.constraints,
            active_panel_closable: self.is_closable(cx),
            draggable: self.draggable(cx),
            droppable: self.droppable(),
            // A stale indicator would otherwise outlive a drag that was
            // cancelled while hovering this group.
            drop_indicator: cx
                .has_active_drag()
                .then_some(self.drop_indicator)
                .flatten(),
            on_select_tab: {
                let group = group.clone();
                Rc::new(move |ix, window, cx| {
                    _ = group.update(cx, |group, cx| group.select_tab(ix, window, cx));
                })
            },
            on_close: {
                let group = group.clone();
                Rc::new(move |panel, _, cx| {
                    _ = group.update(cx, |group, cx| group.close_panel(panel, cx));
                })
            },
            on_toggle_zoom: {
                let group = group.clone();
                Rc::new(move |window, cx| {
                    _ = group.update(cx, |group, cx| group.toggle_zoom(window, cx));
                })
            },
            on_drop_panel: {
                let group = group.clone();
                Rc::new(move |drag, ix, activate, _, cx| {
                    _ = group.update(cx, |group, cx| group.on_drop(&drag, ix, activate, cx));
                })
            },
            on_drop_item: Rc::new(move |item, placement, _, cx| {
                _ = group.update(cx, |group, cx| group.emit_drag_drop(&item, placement, cx));
            }),
        }
    }
}

/// What the container pushes into a group, and reads back out of it.
///
/// `DockArea` is the only caller outside tests.
impl TabGroup {
    /// Mirror one `Tabs` node's membership and displayed index into this
    /// group. `on_added_to` fires for arrivals; departures are silent here
    /// because only the container can tell a move from a removal.
    pub(crate) fn sync_from_tree(
        &mut self,
        panels: Vec<Arc<dyn PanelView>>,
        active_ix: usize,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        let group = cx.weak_entity();
        let existing: Vec<PanelId> = self.panels.iter().map(|panel| panel.panel_id(cx)).collect();
        for panel in panels.iter() {
            if !existing.contains(&panel.panel_id(cx)) {
                panel.on_added_to(group.clone(), window, cx);
            }
        }

        self.panels = panels;
        self.active_ix = active_ix.min(self.panels.len().saturating_sub(1));
        self.schedule_active_sync(window, cx);
        cx.notify();
    }

    /// Replace everything the container knows about this group's place in the
    /// dock, in one call.
    ///
    /// One value rather than a setter per fact, because these are read
    /// together and a container that updates one while leaving another stale
    /// describes a dock that cannot exist — a group beside siblings that still
    /// reports itself alone.
    pub(crate) fn set_constraints(
        &mut self,
        constraints: TabGroupConstraints,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        if self.constraints == constraints {
            return;
        }

        // Collapsing takes the displayed panel off screen, which the
        // active-state contract counts as no panel being displayed.
        let collapse_changed = self.constraints.is_collapsed() != constraints.is_collapsed();
        self.constraints = constraints;
        if collapse_changed {
            self.schedule_active_sync(window, cx);
        }
        cx.notify();
    }

    /// Zoom this group in or out, in full: the flag flips, the displayed
    /// panel is told, and the container is asked to install or clear the
    /// zoomed view.
    ///
    /// Zoom is the group's own state rather than the container's, but the
    /// container drives it too when it installs or clears a zoomed view — and
    /// it goes through this same method, so a group cannot end up flagged
    /// zoomed while the container shows something else.
    ///
    /// Zooming *in* is refused, leaving the flag alone, when there is no
    /// displayed panel or that panel is not zoomable — the early return the
    /// old `TabPanel::on_action_toggle_zoom` made on `zoomable(cx).is_none()`.
    /// Zooming *out* is never refused: a group that became unzoomable while
    /// zoomed still has to be able to give the dock back.
    pub(crate) fn set_zoomed(&mut self, zoomed: bool, window: &mut Window, cx: &mut Context<Self>) {
        if self.zoomed == zoomed {
            return;
        }
        let panel = self.active_panel(cx);
        if zoomed && !panel.as_ref().is_some_and(|panel| panel.zoomable(cx)) {
            return;
        }

        self.zoomed = zoomed;
        cx.emit(if zoomed {
            TabGroupEvent::ZoomIn
        } else {
            TabGroupEvent::ZoomOut
        });

        // Delivered outside this update so a `set_zoomed` handler may call
        // back into the group. The old `TabPanel` sent this to itself, where
        // `Panel::set_zoomed` defaulted to a no-op, so no panel ever heard it.
        if let Some(panel) = panel {
            cx.spawn_in(window, async move |_, cx| {
                _ = cx.update(|window, cx| panel.set_zoomed(zoomed, window, cx));
            })
            .detach();
        }
        cx.notify();
    }

    /// What this group last told `panel` about being active, for handing to
    /// [`Self::seed_active`] on the group it is moving to.
    pub(crate) fn last_notified_active(&self, panel: PanelId) -> Option<bool> {
        self.active.last_notified(panel)
    }

    /// Record what an arriving panel already believes, so a move between
    /// groups does not read as a fresh activation.
    pub(crate) fn seed_active(&mut self, panel: PanelId, active: bool) {
        self.active.seed(panel, active);
    }
}

impl TabGroup {
    /// Every visible panel, in tab order.
    fn visible_panels<'a>(&'a self, cx: &'a App) -> impl Iterator<Item = Arc<dyn PanelView>> + 'a {
        self.panels
            .iter()
            .filter(|panel| panel.visible(cx))
            .cloned()
    }

    /// A locked group cannot be rearranged. Zooming locks it too: a zoomed
    /// group is the only thing on screen, so there is nowhere to drop.
    fn is_locked(&self) -> bool {
        self.constraints.is_locked() || self.zoomed
    }

    /// True when this group holds the last visible panel that anything could
    /// be rearranged around. Only visible panels count, so a hidden panel does
    /// not keep the last visible one draggable and leave the dock empty.
    fn is_last_panel(&self, cx: &App) -> bool {
        self.constraints.is_alone() && self.visible_panels(cx).count() <= 1
    }

    fn draggable(&self, cx: &App) -> bool {
        !self.is_locked() && !self.is_last_panel(cx)
    }

    fn droppable(&self) -> bool {
        !self.is_locked()
    }

    fn focus_active_panel(&self, window: &mut Window, cx: &mut Context<Self>) {
        if let Some(panel) = self.active_panel(cx) {
            panel.focus_handle(cx).focus(window, cx);
        }
    }

    /// Queue one reconcile per frame that notifies panels of their frame-end
    /// net active state. A spawned task, not `defer`, so it runs after every
    /// same-frame mutation including a deferred collapse.
    fn schedule_active_sync(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        if !self.active.schedule_sync() {
            return;
        }

        cx.spawn_in(window, async move |group, cx| {
            _ = cx.update(|window, cx| {
                let Ok(changes) = group.update(cx, |group, cx| group.reconcile_active(cx)) else {
                    return;
                };
                // Dispatched outside the group's update so a `set_active`
                // handler may call back into it without panicking.
                for (panel, active) in changes {
                    panel.set_active(active, window, cx);
                }
            });
        })
        .detach();
    }

    /// The deliveries this frame owes, deactivations first. The displayed slot
    /// is `active_ix` even when the panel there is invisible: rendering falls
    /// back to another panel, but the active-state contract does not.
    fn reconcile_active(&mut self, cx: &App) -> Vec<(Arc<dyn PanelView>, bool)> {
        self.active.sync_finished();

        let ids: Vec<PanelId> = self.panels.iter().map(|panel| panel.panel_id(cx)).collect();
        let displayed = match self.constraints.is_collapsed() {
            true => None,
            false => ids.get(self.active_ix).copied(),
        };

        self.active
            .reconcile(&ids, displayed)
            .into_iter()
            .filter_map(|(id, active)| {
                ids.iter()
                    .position(|candidate| *candidate == id)
                    .map(|ix| (self.panels[ix].clone(), active))
            })
            .collect()
    }

    /// Where a dragged panel would land, tracked while it moves over the
    /// group's content.
    fn on_panel_drag_move(
        &mut self,
        drag: &DragMoveEvent<DragPanel>,
        _: &mut Window,
        cx: &mut Context<Self>,
    ) {
        let bounds = drag.bounds;
        if !bounds.contains(&drag.event.position) {
            self.clear_drop_indicator(cx);
            return;
        }

        let placement = split_placement_at(bounds, drag.event.position);
        let dragged = drag.drag(cx);
        // The placeholder flies in from wherever the preview currently is.
        let source = DropPlaceholderBounds::new(
            drag.event.position - dragged.drag_offset() - bounds.origin,
            dragged.preview_size(),
        );

        self.sync_drop_placeholder(bounds, placement, dragged.drag_session_id(), source, cx);
    }

    /// Same as [`Self::on_panel_drag_move`], for a host-owned drag item.
    ///
    /// A drag item has no dragged tab to fly the placeholder in from, so it
    /// starts at its resting position and only animates between placements.
    fn on_item_drag_move(
        &mut self,
        drag: &DragMoveEvent<AnyDrag>,
        _: &mut Window,
        cx: &mut Context<Self>,
    ) {
        let bounds = drag.bounds;
        if !bounds.contains(&drag.event.position) {
            self.clear_drop_indicator(cx);
            return;
        }

        let placement = split_placement_at(bounds, drag.event.position);
        let source = DropPlaceholderBounds::for_placement(bounds, placement);

        self.sync_drop_placeholder(bounds, placement, ITEM_DRAG_SESSION_ID, source, cx);
    }

    fn sync_drop_placeholder(
        &mut self,
        bounds: Bounds<Pixels>,
        placement: Option<Placement>,
        drag_session_id: u64,
        source: DropPlaceholderBounds,
        cx: &mut Context<Self>,
    ) {
        let to = DropPlaceholderBounds::for_placement(bounds, placement);

        let restart = self.drop_indicator.is_none_or(|indicator| {
            indicator.drag_session_id() != drag_session_id || indicator.placement() != placement
        });

        let (from, epoch) = match (restart, self.drop_indicator) {
            (false, Some(indicator)) => (indicator.from(), indicator.epoch()),
            (_, Some(indicator)) => {
                let from = match indicator.drag_session_id() == drag_session_id {
                    true => indicator.to(),
                    false => source,
                };
                (from, indicator.epoch().wrapping_add(1))
            }
            (_, None) => (source, 0),
        };

        self.drop_indicator = Some(DropIndicator::new(
            bounds,
            placement,
            from,
            to,
            drag_session_id,
            epoch,
        ));
        cx.notify();
    }

    fn clear_drop_indicator(&mut self, cx: &mut Context<Self>) {
        if self.drop_indicator.take().is_some() {
            cx.notify();
        }
    }

    /// Report a host-owned drag landing on this group. `placement` is `None`
    /// to merge into the tab group instead of splitting.
    fn emit_drag_drop(
        &mut self,
        item: &AnyDrag,
        placement: Option<Placement>,
        cx: &mut Context<Self>,
    ) {
        self.drop_indicator = None;
        cx.emit(TabGroupEvent::DragDrop {
            item: item.clone(),
            target: DropTarget::new(self.node, placement),
        });
        cx.notify();
    }

    /// Resolve where a dropped panel lands and report it as one move.
    ///
    /// `ix` names a tab slot, which the tab bar supplies and the content area
    /// does not; a slot always merges, so it overrides any split the hovering
    /// drag had resolved. `activate` decides whether the arriving panel
    /// becomes the displayed tab.
    fn on_drop(
        &mut self,
        drag: &DragPanel,
        ix: Option<usize>,
        activate: bool,
        cx: &mut Context<Self>,
    ) {
        let indicator = self.drop_indicator.take();
        let placement = match ix {
            Some(_) => None,
            None => indicator.and_then(|indicator| indicator.placement()),
        };

        // Dropping a panel back onto its own group is a move only when it
        // splits out of a group holding more than itself, or when it lands on
        // a specific tab slot.
        if drag.source() == self.node
            && ix.is_none()
            && (placement.is_none() || self.panels.len() == 1)
        {
            cx.notify();
            return;
        }

        let target = match placement {
            Some(placement) => InsertTarget::Split {
                node: self.node,
                placement,
                size: None,
            },
            None => InsertTarget::Tabs {
                node: self.node,
                ix,
                activate,
            },
        };

        cx.emit(TabGroupEvent::Drop {
            panel: drag.panel(),
            source: drag.source(),
            target,
        });
        cx.notify();
    }
}

impl EventEmitter<TabGroupEvent> for TabGroup {}

impl Focusable for TabGroup {
    fn focus_handle(&self, cx: &App) -> FocusHandle {
        match self.active_panel(cx) {
            Some(panel) => panel.focus_handle(cx),
            None => self.focus_handle.clone(),
        }
    }
}

impl Render for TabGroup {
    fn render(&mut self, window: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        let context = self.context(cx);
        let renderer = self.renderer.clone();
        let focus_handle = self.focus_handle(cx);
        let droppable = context.droppable;
        let indicator = context.drop_indicator;

        renderer
            .frame(&context, window, cx)
            .test_support()
            // Structure, applied around whatever the renderer returns.
            //
            // A column, and not a `div`: gpui's default display is Block, and
            // in block layout a child's `flex_grow` is ignored -- the content
            // region below the tab bar resolves to zero height, because its
            // only descendant is the panel view, positioned absolutely and
            // contributing no content height. So a renderer that returned a
            // plain frame got a group that drew its tabs and nothing else, at
            // whatever width its tabs happened to be.
            .flex()
            .flex_col()
            .size_full()
            .overflow_hidden()
            .track_focus(&focus_handle)
            .tab_group()
            .child(renderer.render_tab_bar(&context, window, cx))
            .child(
                renderer
                    .content_frame(&context, window, cx)
                    .test_support()
                    // The region below the tab bar takes the rest of the
                    // group -- except in a collapsed one, which is a strip of
                    // tabs with no content and must claim no space at all.
                    .flex()
                    .flex_col()
                    .when(!context.is_collapsed(), |this| this.flex_1())
                    // A flex item's `min-height` is `auto`, so a column that
                    // grows to fill the group is still floored by the height
                    // its content wants. A panel holding a virtualized list
                    // measured itself against every row rather than the region
                    // it was given: the clip was right, so it looked correct,
                    // and the list built rows nobody could see. Flooring it at
                    // zero lets the region win.
                    .min_h(px(0.))
                    .overflow_hidden()
                    // Both drag kinds hang off `droppable` alone.
                    .when(droppable, |this| {
                        this.on_drag_move(cx.listener(Self::on_panel_drag_move))
                            .on_drop(cx.listener(|this, drag: &DragPanel, _, cx| {
                                this.on_drop(drag, None, true, cx)
                            }))
                            .on_drag_move(cx.listener(Self::on_item_drag_move))
                            .on_drop(cx.listener(|this, item: &AnyDrag, _, cx| {
                                let placement = this
                                    .drop_indicator
                                    .and_then(|indicator| indicator.placement());
                                this.emit_drag_drop(item, placement, cx);
                            }))
                    })
                    .map(|this| match context.active_panel.as_ref() {
                        Some(panel) => this.child(renderer.render_active_panel(
                            panel.view(),
                            &context,
                            window,
                            cx,
                        )),
                        None => this.children(renderer.render_empty(&context, window, cx)),
                    })
                    .when_some(indicator, |this, indicator| {
                        this.children(renderer.render_drop_indicator(indicator, window, cx))
                    }),
            )
    }
}

type SelectTabHandler = Rc<dyn Fn(usize, &mut Window, &mut App)>;
type ClosePanelHandler = Rc<dyn Fn(PanelId, &mut Window, &mut App)>;
type ToggleZoomHandler = Rc<dyn Fn(&mut Window, &mut App)>;
type DropPanelHandler = Rc<dyn Fn(DragPanel, Option<usize>, bool, &mut Window, &mut App)>;
type DropItemHandler = Rc<dyn Fn(AnyDrag, Option<Placement>, &mut Window, &mut App)>;

/// What a skin needs to draw a tab group, and the callbacks it invokes rather
/// than reimplementing behavior.
#[derive(Clone)]
pub struct TabGroupContext {
    node: NodeId,
    panels: Vec<Arc<dyn PanelView>>,
    active_panel: Option<Arc<dyn PanelView>>,
    active_ix: usize,
    zoomed: bool,
    constraints: TabGroupConstraints,
    draggable: bool,
    droppable: bool,
    active_panel_closable: bool,
    drop_indicator: Option<DropIndicator>,
    on_select_tab: SelectTabHandler,
    on_close: ClosePanelHandler,
    on_toggle_zoom: ToggleZoomHandler,
    on_drop_panel: DropPanelHandler,
    on_drop_item: DropItemHandler,
}

impl TabGroupContext {
    /// The `Tabs` node this group mirrors, for a skin that needs to name the
    /// group in a drag payload or a drop target.
    pub fn node(&self) -> NodeId {
        self.node
    }

    /// Every panel in the group, in tab order — visible or not. A skin filters
    /// with [`PanelView::visible`] when it draws.
    pub fn panels(&self) -> &[Arc<dyn PanelView>] {
        &self.panels
    }

    pub fn active_ix(&self) -> usize {
        self.active_ix
    }

    /// The panel on screen, which is the displayed tab unless that panel has
    /// gone invisible.
    pub fn active_panel(&self) -> Option<&Arc<dyn PanelView>> {
        self.active_panel.as_ref()
    }

    pub fn drop_indicator(&self) -> Option<DropIndicator> {
        self.drop_indicator
    }

    pub fn is_zoomed(&self) -> bool {
        self.zoomed
    }

    pub fn is_collapsed(&self) -> bool {
        self.constraints.is_collapsed()
    }

    /// Whether the active panel can be closed.
    pub fn is_closable(&self) -> bool {
        self.active_panel_closable
    }

    /// Whether `panel` can be closed from this group. Uses the same constraints
    /// as [`TabGroup::close_panel`], including the panel's own `closable` flag.
    pub fn is_panel_closable(&self, panel: PanelId, cx: &App) -> bool {
        self.constraints.is_closable()
            && self.draggable
            && self
                .panels
                .iter()
                .any(|candidate| candidate.panel_id(cx) == panel && candidate.closable(cx))
    }

    pub fn is_locked(&self) -> bool {
        self.constraints.is_locked() || self.zoomed
    }

    pub fn is_draggable(&self) -> bool {
        self.draggable
    }

    pub fn is_droppable(&self) -> bool {
        self.droppable
    }

    pub fn select_tab(&self, ix: usize, window: &mut Window, cx: &mut App) {
        (self.on_select_tab)(ix, window, cx);
    }

    pub fn close(&self, panel: PanelId, window: &mut Window, cx: &mut App) {
        (self.on_close)(panel, window, cx);
    }

    pub fn toggle_zoom(&self, window: &mut Window, cx: &mut App) {
        (self.on_toggle_zoom)(window, cx);
    }

    /// The drag payload for the tab at `ix`, for a skin wiring `on_drag` onto
    /// its tabs. `None` when `ix` names no panel.
    pub fn drag_panel(&self, ix: usize, cx: &App) -> Option<DragPanel> {
        self.panels
            .get(ix)
            .map(|panel| DragPanel::new(panel.panel_id(cx), self.node))
    }

    /// A panel dropped on the tab bar. `ix` names the slot it lands in, or
    /// `None` to append; `activate` decides whether it becomes displayed.
    pub fn drop_panel(
        &self,
        drag: DragPanel,
        ix: Option<usize>,
        activate: bool,
        window: &mut Window,
        cx: &mut App,
    ) {
        (self.on_drop_panel)(drag, ix, activate, window, cx);
    }

    /// A host-owned drag dropped on the tab bar. `placement` is `None` to
    /// merge into this group rather than split beside it.
    pub fn drop_item(
        &self,
        item: AnyDrag,
        placement: Option<Placement>,
        window: &mut Window,
        cx: &mut App,
    ) {
        (self.on_drop_item)(item, placement, window, cx);
    }
}

/// Appearance for a tab group. Base draws none of it.
///
/// The two frame hooks return the element itself rather than wrapping one,
/// because base attaches focus, keyboard grouping, and drop handling to the
/// very elements the skin styles: a wrapper would put the hit area and the
/// painted area on different elements.
#[allow(unused_variables)]
pub trait TabGroupRenderer: 'static {
    /// The group's outer frame, which base tracks focus on.
    ///
    /// Identified rather than plain, so a skin can add a role, a tooltip, or
    /// scroll tracking; `Stateful<Div>` does everything base needs from it.
    /// Appearance only. The group is laid out as a column that fills its slot
    /// around whatever this returns, because a group that does not is a strip
    /// of tabs with no content under it.
    /// A renderer that needs the painted group bounds can attach `on_prepaint`
    /// here and identify the group with [`TabGroupContext::node`].
    fn frame(&self, group: &TabGroupContext, window: &mut Window, cx: &mut App) -> Stateful<Div> {
        div().id("tab-group")
    }

    /// The region below the tab bar, which base installs drop handling on.
    fn content_frame(
        &self,
        group: &TabGroupContext,
        window: &mut Window,
        cx: &mut App,
    ) -> Stateful<Div> {
        div().id("tab-group-content")
    }

    fn render_tab_bar(
        &self,
        group: &TabGroupContext,
        window: &mut Window,
        cx: &mut App,
    ) -> AnyElement;

    /// How the displayed panel's view is placed in the content region. The
    /// skin receives the view rather than an element so it can decide how the
    /// view is cached and stretched.
    fn render_active_panel(
        &self,
        panel: AnyView,
        group: &TabGroupContext,
        window: &mut Window,
        cx: &mut App,
    ) -> AnyElement {
        panel.into_any_element()
    }

    fn render_drop_indicator(
        &self,
        indicator: DropIndicator,
        window: &mut Window,
        cx: &mut App,
    ) -> Option<AnyElement> {
        None
    }

    fn render_empty(
        &self,
        group: &TabGroupContext,
        window: &mut Window,
        cx: &mut App,
    ) -> Option<AnyElement> {
        None
    }
}

/// The renderer a group starts with: the displayed panel and nothing else.
pub(crate) struct BareTabGroup;

impl TabGroupRenderer for BareTabGroup {
    fn render_tab_bar(&self, _: &TabGroupContext, _: &mut Window, _: &mut App) -> AnyElement {
        Empty.into_any_element()
    }
}

#[cfg(test)]
mod tests {
    use std::cell::RefCell;

    use gpui::{
        AppContext as _, Entity, Modifiers, MouseButton, StatefulInteractiveElement as _,
        TestAppContext, VisualTestContext, point, px, size,
    };

    use super::*;
    use crate::dock::test_support::{
        PanelSignal, build_group, drain, drain_active, log_of, panel_id,
    };

    /// The node `build_group` gives its group.
    fn group_node() -> NodeId {
        NodeId::from_u64(1)
    }

    fn elsewhere() -> NodeId {
        NodeId::from_u64(7)
    }

    fn content_bounds() -> Bounds<Pixels> {
        Bounds {
            origin: point(px(0.), px(0.)),
            size: size(px(400.), px(300.)),
        }
    }

    /// Collect the group's outgoing intents as readable strings, so an
    /// assertion reads as the sentence the event means.
    fn record_events(
        group: &Entity<TabGroup>,
        cx: &mut VisualTestContext,
    ) -> Rc<RefCell<Vec<String>>> {
        let events: Rc<RefCell<Vec<String>>> = Rc::default();
        let sink = events.clone();
        cx.update(|_, cx| {
            cx.subscribe(group, move |_, event: &TabGroupEvent, _| {
                sink.borrow_mut().push(describe(event));
            })
            .detach();
        });
        events
    }

    fn describe(event: &TabGroupEvent) -> String {
        match event {
            TabGroupEvent::Drop {
                panel,
                source,
                target,
            } => match target {
                InsertTarget::Tabs { node, ix, activate } => format!(
                    "drop panel {} from {} into tabs {} at {:?} activate={}",
                    panel.as_u64(),
                    source.as_u64(),
                    node.as_u64(),
                    ix,
                    activate
                ),
                InsertTarget::Split {
                    node, placement, ..
                } => format!(
                    "drop panel {} from {} split {} {}",
                    panel.as_u64(),
                    source.as_u64(),
                    node.as_u64(),
                    placement
                ),
            },
            TabGroupEvent::DragDrop { target, .. } => format!(
                "item onto {} at {:?}",
                target.node().as_u64(),
                target.placement()
            ),
            TabGroupEvent::ClosePanel { panel } => format!("close {}", panel.as_u64()),
            TabGroupEvent::ActiveChanged { ix } => format!("active {ix}"),
            TabGroupEvent::ZoomIn => "zoom in".into(),
            TabGroupEvent::ZoomOut => "zoom out".into(),
        }
    }

    #[gpui::test]
    fn a_group_announces_its_first_panel_active(cx: &mut TestAppContext) {
        let log = log_of();
        let (group, panels, cx) = build_group(&log, &["a"], cx);
        cx.run_until_parked();

        assert_eq!(drain_active(&log), vec![("a", true)]);
        let _ = (group, panels);
    }

    #[gpui::test]
    fn selecting_another_tab_deactivates_then_activates(cx: &mut TestAppContext) {
        let log = log_of();
        let (group, _panels, cx) = build_group(&log, &["a", "b"], cx);
        cx.run_until_parked();
        drain_active(&log);

        cx.update(|window, cx| {
            group.update(cx, |group, cx| group.select_tab(1, window, cx));
        });
        cx.run_until_parked();

        assert_eq!(drain_active(&log), vec![("a", false), ("b", true)]);
    }

    #[gpui::test]
    fn the_context_snapshots_the_group_state(cx: &mut TestAppContext) {
        let log = log_of();
        let (group, _panels, cx) = build_group(&log, &["a", "b"], cx);

        let seen = cx.update(|_, cx| {
            group.update(cx, |group, cx| {
                let context = group.context(cx);
                (
                    context.panels().len(),
                    context.active_ix(),
                    context.is_zoomed(),
                )
            })
        });

        assert_eq!(seen, (2, 0, false));
    }

    /// A panel hidden while it holds the displayed slot is still the panel
    /// told it is active; only what gets drawn falls back to a visible one.
    #[gpui::test]
    fn a_hidden_displayed_panel_is_still_the_active_one(cx: &mut TestAppContext) {
        let log = log_of();
        let (group, panels, cx) = build_group(&log, &["a", "b"], cx);
        cx.update(|_, cx| {
            panels[0].update(cx, |panel, cx| panel.set_visible(false, cx));
        });
        cx.run_until_parked();

        assert_eq!(drain_active(&log), vec![("a", true)]);
        assert_eq!(
            cx.update(|_, cx| group.read(cx).active_panel(cx).unwrap().panel_name(cx)),
            "b",
            "rendering falls back to the first visible panel"
        );
    }

    /// `on_removed` is a departing panel's deactivation signal, so the group
    /// must not also announce `false` to it.
    #[gpui::test]
    fn a_panel_dropped_from_the_group_is_never_told_it_went_inactive(cx: &mut TestAppContext) {
        let log = log_of();
        let (group, panels, cx) = build_group(&log, &["a", "b"], cx);
        cx.run_until_parked();
        drain(&log);

        cx.update(|window, cx| {
            let remaining: Vec<Arc<dyn PanelView>> = vec![Arc::new(panels[1].clone())];
            group.update(cx, |group, cx| {
                group.sync_from_tree(remaining, 0, window, cx)
            });
        });
        cx.run_until_parked();

        assert_eq!(drain_active(&log), vec![("b", true)]);
    }

    #[gpui::test]
    fn selecting_a_tab_that_is_not_there_changes_nothing(cx: &mut TestAppContext) {
        let log = log_of();
        let (group, _panels, cx) = build_group(&log, &["a", "b"], cx);
        cx.run_until_parked();
        drain_active(&log);
        let events = record_events(&group, cx);

        cx.update(|window, cx| {
            group.update(cx, |group, cx| group.select_tab(5, window, cx));
        });
        cx.run_until_parked();

        assert_eq!(cx.update(|_, cx| group.read(cx).active_ix()), 0);
        assert!(events.borrow().is_empty());
        assert!(drain_active(&log).is_empty());
    }

    #[gpui::test]
    fn a_locked_group_can_be_neither_dragged_nor_dropped_into(cx: &mut TestAppContext) {
        let log = log_of();
        let (group, _panels, cx) = build_group(&log, &["a", "b"], cx);

        cx.update(|window, cx| {
            group.update(cx, |group, cx| {
                group.set_constraints(TabGroupConstraints::in_split(false), window, cx)
            })
        });
        let unlocked = cx.update(|_, cx| {
            let context = group.read(cx).context(cx);
            (context.is_draggable(), context.is_droppable())
        });
        cx.update(|window, cx| {
            group.update(cx, |group, cx| {
                group.set_constraints(
                    TabGroupConstraints::in_split(false).dock_locked(true),
                    window,
                    cx,
                )
            })
        });
        let locked = cx.update(|_, cx| {
            let context = group.read(cx).context(cx);
            (context.is_draggable(), context.is_droppable())
        });

        assert_eq!(unlocked, (true, true));
        assert_eq!(locked, (false, false));
    }

    /// Zooming is a lock of its own: a zoomed group fills the dock, so there
    /// is nothing beside it to drop against.
    #[gpui::test]
    fn a_zoomed_group_takes_no_drops(cx: &mut TestAppContext) {
        let log = log_of();
        let (group, _panels, cx) = build_group(&log, &["a", "b"], cx);

        cx.update(|window, cx| {
            group.update(cx, |group, cx| {
                group.set_constraints(TabGroupConstraints::in_split(false), window, cx);
                group.set_zoomed(true, window, cx);
            })
        });

        assert!(!cx.update(|_, cx| group.read(cx).context(cx).is_droppable()));
    }

    /// Dragging the last visible panel out of the only group would leave the
    /// dock empty and undroppable, so it is refused.
    #[gpui::test]
    fn the_only_groups_last_visible_panel_cannot_be_dragged_out(cx: &mut TestAppContext) {
        let log = log_of();
        let (group, _panels, cx) = build_group(&log, &["a"], cx);

        cx.update(|window, cx| {
            group.update(cx, |group, cx| {
                group.set_constraints(TabGroupConstraints::in_split(true), window, cx)
            })
        });
        let alone = cx.update(|_, cx| group.read(cx).context(cx).is_draggable());
        cx.update(|window, cx| {
            group.update(cx, |group, cx| {
                group.set_constraints(TabGroupConstraints::in_split(false), window, cx)
            })
        });
        let beside_others = cx.update(|_, cx| group.read(cx).context(cx).is_draggable());

        assert!(!alone);
        assert!(beside_others);
    }

    #[gpui::test]
    fn a_panel_from_another_group_lands_as_one_move(cx: &mut TestAppContext) {
        let log = log_of();
        let (group, _panels, cx) = build_group(&log, &["a"], cx);
        let events = record_events(&group, cx);

        let drag = DragPanel::new(PanelId::from_u64(99), elsewhere());
        cx.update(|_, cx| {
            group.update(cx, |group, cx| group.on_drop(&drag, None, true, cx));
        });
        cx.run_until_parked();

        assert_eq!(
            *events.borrow(),
            vec!["drop panel 99 from 7 into tabs 1 at None activate=true"]
        );
    }

    #[gpui::test]
    fn dropping_a_panel_back_onto_its_own_group_is_ignored(cx: &mut TestAppContext) {
        let log = log_of();
        let (group, panels, cx) = build_group(&log, &["a", "b"], cx);
        let events = record_events(&group, cx);

        let panel = panel_id(&panels[0], cx);
        let drag = DragPanel::new(panel, group_node());
        cx.update(|_, cx| {
            group.update(cx, |group, cx| group.on_drop(&drag, None, true, cx));
        });
        cx.run_until_parked();

        assert!(events.borrow().is_empty());
    }

    #[gpui::test]
    fn a_hovering_split_turns_a_drop_into_a_split(cx: &mut TestAppContext) {
        let log = log_of();
        let (group, _panels, cx) = build_group(&log, &["a"], cx);
        let events = record_events(&group, cx);

        let drag = DragPanel::new(PanelId::from_u64(99), elsewhere());
        cx.update(|_, cx| {
            group.update(cx, |group, cx| {
                group.sync_drop_placeholder(
                    content_bounds(),
                    Some(Placement::Right),
                    drag.drag_session_id(),
                    DropPlaceholderBounds::for_placement(content_bounds(), None),
                    cx,
                );
                group.on_drop(&drag, None, true, cx);
            });
        });
        cx.run_until_parked();

        assert_eq!(*events.borrow(), vec!["drop panel 99 from 7 split 1 Right"]);
    }

    /// The tab bar reports the slot a drop landed on, and a slot always means
    /// "into these tabs" however the content area had resolved the cursor.
    #[gpui::test]
    fn a_tab_slot_overrides_the_hovering_split(cx: &mut TestAppContext) {
        let log = log_of();
        let (group, _panels, cx) = build_group(&log, &["a"], cx);
        let events = record_events(&group, cx);

        let drag = DragPanel::new(PanelId::from_u64(99), elsewhere());
        cx.update(|_, cx| {
            group.update(cx, |group, cx| {
                group.sync_drop_placeholder(
                    content_bounds(),
                    Some(Placement::Right),
                    drag.drag_session_id(),
                    DropPlaceholderBounds::for_placement(content_bounds(), None),
                    cx,
                );
                group.on_drop(&drag, Some(0), true, cx);
            });
        });
        cx.run_until_parked();

        assert_eq!(
            *events.borrow(),
            vec!["drop panel 99 from 7 into tabs 1 at Some(0) activate=true"]
        );
    }

    /// A lone panel splitting out of its own group would empty that group and
    /// refill it, which is no move at all.
    #[gpui::test]
    fn a_lone_panel_cannot_split_out_of_its_own_group(cx: &mut TestAppContext) {
        let log = log_of();
        let (group, panels, cx) = build_group(&log, &["a"], cx);
        let events = record_events(&group, cx);

        let drag = DragPanel::new(panel_id(&panels[0], cx), group_node());
        cx.update(|_, cx| {
            group.update(cx, |group, cx| {
                group.sync_drop_placeholder(
                    content_bounds(),
                    Some(Placement::Right),
                    drag.drag_session_id(),
                    DropPlaceholderBounds::for_placement(content_bounds(), None),
                    cx,
                );
                group.on_drop(&drag, None, true, cx);
            });
        });
        cx.run_until_parked();

        assert!(events.borrow().is_empty());
    }

    #[gpui::test]
    fn the_placeholder_replays_only_when_the_target_moves(cx: &mut TestAppContext) {
        let log = log_of();
        let (group, _panels, cx) = build_group(&log, &["a"], cx);
        let bounds = content_bounds();
        let source = DropPlaceholderBounds::new(point(px(10.), px(10.)), size(px(96.), px(30.)));

        let sync = |placement: Option<Placement>, cx: &mut VisualTestContext| {
            cx.update(|_, cx| {
                group.update(cx, |group, cx| {
                    group.sync_drop_placeholder(bounds, placement, 42, source, cx);
                    group.drop_indicator.unwrap()
                })
            })
        };

        let first = sync(Some(Placement::Left), cx);
        let again = sync(Some(Placement::Left), cx);
        let moved = sync(Some(Placement::Right), cx);

        assert_eq!(first.epoch(), 0);
        assert_eq!(first.from(), source, "the first run flies in from the drag");
        assert_eq!(again.epoch(), 0, "an unchanged target keeps animating");
        assert_eq!(again.from(), source);
        assert_eq!(moved.epoch(), 1, "a moved target replays from where it was");
        assert_eq!(moved.from(), first.to());
        assert_eq!(
            moved.to(),
            DropPlaceholderBounds::for_placement(bounds, Some(Placement::Right))
        );
    }

    /// The indicator is hit state, not a latch: a drag cancelled while
    /// hovering must not leave the placeholder painted.
    #[gpui::test]
    fn the_indicator_is_withheld_when_no_drag_is_in_flight(cx: &mut TestAppContext) {
        let log = log_of();
        let (group, _panels, cx) = build_group(&log, &["a"], cx);

        let (stored, published) = cx.update(|_, cx| {
            group.update(cx, |group, cx| {
                group.sync_drop_placeholder(
                    content_bounds(),
                    Some(Placement::Top),
                    42,
                    DropPlaceholderBounds::for_placement(content_bounds(), None),
                    cx,
                );
                (
                    group.drop_indicator.is_some(),
                    group.context(cx).drop_indicator().is_some(),
                )
            })
        });

        assert!(stored);
        assert!(!published);
    }

    #[gpui::test]
    fn a_host_drag_reports_the_group_and_the_edge_it_resolved(cx: &mut TestAppContext) {
        let log = log_of();
        let (group, _panels, cx) = build_group(&log, &["a"], cx);
        let events = record_events(&group, cx);

        cx.update(|_, cx| {
            group.update(cx, |group, cx| {
                group.emit_drag_drop(&AnyDrag::new(7u32), Some(Placement::Bottom), cx)
            });
        });
        cx.run_until_parked();

        assert_eq!(*events.borrow(), vec!["item onto 1 at Some(Bottom)"]);
    }

    #[gpui::test]
    fn closing_asks_the_container_rather_than_editing_the_group(cx: &mut TestAppContext) {
        let log = log_of();
        let (group, panels, cx) = build_group(&log, &["a", "b"], cx);
        let events = record_events(&group, cx);
        let panel = panel_id(&panels[1], cx);

        cx.update(|_, cx| {
            group.update(cx, |group, cx| {
                group.close_panel(panel, cx);
                // A panel that is not a member is not this group's to close.
                group.close_panel(PanelId::from_u64(4242), cx);
            });
        });
        cx.run_until_parked();

        assert_eq!(*events.borrow(), vec![format!("close {}", panel.as_u64())]);
        assert_eq!(
            cx.update(|_, cx| group.read(cx).panels().len()),
            2,
            "the group still holds both panels until the container edits the tree"
        );
    }

    #[gpui::test]
    fn zooming_toggles_and_tells_the_displayed_panel(cx: &mut TestAppContext) {
        let log = log_of();
        let (group, _panels, cx) = build_group(&log, &["a"], cx);
        let events = record_events(&group, cx);

        cx.update(|window, cx| group.update(cx, |group, cx| group.toggle_zoom(window, cx)));
        cx.run_until_parked();
        cx.update(|window, cx| group.update(cx, |group, cx| group.toggle_zoom(window, cx)));
        cx.run_until_parked();

        assert_eq!(*events.borrow(), vec!["zoom in", "zoom out"]);
        assert!(!cx.update(|_, cx| group.read(cx).is_zoomed()));
        assert_eq!(
            drain(&log)
                .into_iter()
                .filter(|(_, signal)| matches!(signal, PanelSignal::Zoomed(_)))
                .collect::<Vec<_>>(),
            vec![
                ("a", PanelSignal::Zoomed(true)),
                ("a", PanelSignal::Zoomed(false))
            ],
            "the old TabPanel sent this to itself, where the default no-op swallowed it"
        );
    }

    /// A real drag over a locked group must resolve nothing: base installs no
    /// drop handling on one, so the placement is never computed and the layout
    /// tree is never asked to move anything.
    #[gpui::test]
    fn a_drag_over_a_locked_group_resolves_nothing(cx: &mut TestAppContext) {
        let (group, _calls, cx) = build_skinned_group(&["a", "b"], cx);
        cx.update(|window, cx| {
            group.update(cx, |group, cx| {
                group.set_constraints(
                    TabGroupConstraints::in_split(false).dock_locked(true),
                    window,
                    cx,
                )
            })
        });
        cx.update(|window, cx| window.draw(cx).clear(cx));

        drag_from_the_tab_into_the_content(cx);

        assert!(
            cx.update(|_, cx| group.read(cx).drop_indicator.is_none()),
            "a locked group installs no drag-move listener, so nothing resolved"
        );
    }

    /// `Dock::new` marks a dock's last group unclosable so the dock cannot be
    /// emptied out from under itself.
    #[gpui::test]
    fn a_group_the_container_sealed_shut_refuses_to_close(cx: &mut TestAppContext) {
        let log = log_of();
        let (group, panels, cx) = build_group(&log, &["a", "b"], cx);
        let events = record_events(&group, cx);
        let panel = panel_id(&panels[0], cx);

        cx.update(|window, cx| {
            group.update(cx, |group, cx| {
                group.set_constraints(
                    TabGroupConstraints::in_split(false).closable(false),
                    window,
                    cx,
                );
                group.close_panel(panel, cx);
            })
        });
        cx.run_until_parked();

        assert!(!cx.update(|_, cx| group.read(cx).context(cx).is_closable()));
        assert!(events.borrow().is_empty());
    }

    /// The last visible panel of the only group has nowhere to go, so it is
    /// not closable either — closing it would empty the region out from under
    /// itself. Placing a sibling beside the group makes the same panel
    /// closable again, which is what pins the reason to `alone` rather than to
    /// something else the sealed default also forbids.
    #[gpui::test]
    fn the_only_groups_last_panel_is_not_closable(cx: &mut TestAppContext) {
        let log = log_of();
        let (group, _panels, cx) = build_group(&log, &["a"], cx);

        cx.update(|window, cx| {
            group.update(cx, |group, cx| {
                group.set_constraints(TabGroupConstraints::in_split(true), window, cx)
            })
        });
        let alone = cx.update(|_, cx| group.read(cx).context(cx).is_closable());

        cx.update(|window, cx| {
            group.update(cx, |group, cx| {
                group.set_constraints(TabGroupConstraints::in_split(false), window, cx)
            })
        });
        let beside_a_sibling = cx.update(|_, cx| group.read(cx).context(cx).is_closable());

        assert!(!alone);
        assert!(beside_a_sibling);
    }

    /// Collapsing takes the displayed panel off screen, and the active-state
    /// contract counts that as no panel being displayed.
    #[gpui::test]
    fn collapsing_deactivates_the_displayed_panel_and_expanding_restores_it(
        cx: &mut TestAppContext,
    ) {
        let log = log_of();
        let (group, _panels, cx) = build_group(&log, &["a", "b"], cx);
        cx.run_until_parked();
        assert_eq!(drain_active(&log), vec![("a", true)]);

        cx.update(|window, cx| {
            group.update(cx, |group, cx| {
                group.set_constraints(
                    TabGroupConstraints::in_split(false).collapsed(true),
                    window,
                    cx,
                )
            })
        });
        cx.run_until_parked();
        assert_eq!(drain_active(&log), vec![("a", false)]);

        cx.update(|window, cx| {
            group.update(cx, |group, cx| {
                group.set_constraints(TabGroupConstraints::in_split(false), window, cx)
            })
        });
        cx.run_until_parked();
        assert_eq!(drain_active(&log), vec![("a", true)]);
    }

    // ---- the renderer seam ----

    /// Where `RecordingRenderer` puts its content frame. Deliberately not the
    /// window's own origin or size, so a listener on the outer frame would
    /// report different bounds.
    fn skin_content() -> Bounds<Pixels> {
        Bounds {
            origin: point(px(100.), px(50.)),
            size: size(px(400.), px(300.)),
        }
    }

    /// A skin that records which hooks base calls, and lays its two frames out
    /// at known coordinates so a test can tell them apart by hit geometry.
    struct RecordingRenderer {
        calls: Rc<RefCell<Vec<&'static str>>>,
    }

    impl RecordingRenderer {
        fn saw(&self, call: &'static str) {
            self.calls.borrow_mut().push(call);
        }
    }

    impl TabGroupRenderer for RecordingRenderer {
        fn frame(&self, _: &TabGroupContext, _: &mut Window, _: &mut App) -> Stateful<Div> {
            self.saw("frame");
            div().id("skin-frame").relative().size_full()
        }

        fn content_frame(&self, _: &TabGroupContext, _: &mut Window, _: &mut App) -> Stateful<Div> {
            self.saw("content_frame");
            div()
                .id("skin-content")
                .absolute()
                .left(skin_content().origin.x)
                .top(skin_content().origin.y)
                .w(skin_content().size.width)
                .h(skin_content().size.height)
        }

        fn render_tab_bar(
            &self,
            group: &TabGroupContext,
            _: &mut Window,
            cx: &mut App,
        ) -> AnyElement {
            self.saw("tab_bar");
            div()
                .id("skin-tab")
                .absolute()
                .left(px(0.))
                .top(px(0.))
                .w(px(80.))
                .h(px(24.))
                .when_some(group.drag_panel(0, cx), |this, drag| {
                    this.on_drag(drag, |drag, offset, _, cx| {
                        drag.set_drag_offset(offset);
                        cx.new(|_| drag.clone())
                    })
                })
                .into_any_element()
        }

        fn render_active_panel(
            &self,
            panel: AnyView,
            _: &TabGroupContext,
            _: &mut Window,
            _: &mut App,
        ) -> AnyElement {
            self.saw("active_panel");
            panel.into_any_element()
        }

        fn render_empty(
            &self,
            _: &TabGroupContext,
            _: &mut Window,
            _: &mut App,
        ) -> Option<AnyElement> {
            self.saw("empty");
            None
        }

        fn render_drop_indicator(
            &self,
            _: DropIndicator,
            _: &mut Window,
            _: &mut App,
        ) -> Option<AnyElement> {
            self.saw("drop_indicator");
            None
        }
    }

    fn build_skinned_group<'a>(
        names: &[&'static str],
        cx: &'a mut TestAppContext,
    ) -> (
        Entity<TabGroup>,
        Rc<RefCell<Vec<&'static str>>>,
        &'a mut VisualTestContext,
    ) {
        let calls: Rc<RefCell<Vec<&'static str>>> = Rc::default();
        let renderer = Rc::new(RecordingRenderer {
            calls: calls.clone(),
        });
        let (group, cx) = cx.add_window_view(|window, cx| {
            TabGroup::new(NodeId::from_u64(1), window, cx).with_renderer(renderer)
        });

        let names = names.to_vec();
        let log = log_of();
        cx.update(|window, cx| {
            let views: Vec<Arc<dyn PanelView>> = names
                .iter()
                .map(|name| {
                    Arc::new(crate::dock::test_support::TestPanel::logging(
                        name, &log, cx,
                    )) as _
                })
                .collect();
            group.update(cx, |group, cx| {
                group.set_constraints(TabGroupConstraints::in_split(false), window, cx);
                group.sync_from_tree(views, 0, window, cx);
            });
        });
        cx.run_until_parked();
        calls.borrow_mut().clear();

        (group, calls, cx)
    }

    /// Press on the skin's tab, start the drag, and move into the right-hand
    /// third of `skin_content()`.
    fn drag_from_the_tab_into_the_content(cx: &mut VisualTestContext) {
        cx.simulate_mouse_down(
            point(px(20.), px(10.)),
            MouseButton::Left,
            Modifiers::none(),
        );
        cx.simulate_mouse_move(
            point(px(30.), px(14.)),
            MouseButton::Left,
            Modifiers::none(),
        );
        cx.simulate_mouse_move(
            point(px(450.), px(200.)),
            MouseButton::Left,
            Modifiers::none(),
        );
    }

    /// The composition contract every later renderer copies: which hooks base
    /// calls, and in what order.
    #[gpui::test]
    fn the_renderer_composes_frame_then_tab_bar_then_content(cx: &mut TestAppContext) {
        let (_group, calls, cx) = build_skinned_group(&["a"], cx);

        cx.update(|window, cx| window.draw(cx).clear(cx));

        assert_eq!(
            *calls.borrow(),
            vec!["frame", "tab_bar", "content_frame", "active_panel"],
            "the tab bar is a sibling of the content, not a child of it"
        );
    }

    /// With nothing to display base asks for the empty element instead of the
    /// active panel, and never for both.
    #[gpui::test]
    fn an_empty_group_asks_the_renderer_for_its_empty_state(cx: &mut TestAppContext) {
        let (_group, calls, cx) = build_skinned_group(&[], cx);

        cx.update(|window, cx| window.draw(cx).clear(cx));

        assert_eq!(
            *calls.borrow(),
            vec!["frame", "tab_bar", "content_frame", "empty"]
        );
    }

    /// The drop listeners must sit on the content frame, not the outer frame:
    /// a drag over the group resolves against the content frame's own bounds,
    /// which the skin — not base — decides.
    #[gpui::test]
    fn the_content_frame_is_what_a_drag_is_measured_against(cx: &mut TestAppContext) {
        let (group, calls, cx) = build_skinned_group(&["a", "b"], cx);
        cx.update(|window, cx| window.draw(cx).clear(cx));

        drag_from_the_tab_into_the_content(cx);

        let indicator = cx
            .update(|_, cx| group.read(cx).drop_indicator)
            .expect("the content frame's drag-move listener ran");

        assert_eq!(
            indicator.bounds(),
            skin_content(),
            "measured against the content frame, not the full-size outer frame"
        );
        assert_eq!(indicator.placement(), Some(Placement::Right));

        cx.update(|window, cx| window.draw(cx).clear(cx));
        assert!(
            calls.borrow().contains(&"drop_indicator"),
            "a published indicator is handed to the renderer to draw"
        );
    }

    /// A drop landing on the content frame reports a move the container can
    /// apply, and clears the hover state behind it.
    #[gpui::test]
    fn dropping_on_the_content_frame_reports_the_move(cx: &mut TestAppContext) {
        let (group, _calls, cx) = build_skinned_group(&["a", "b"], cx);
        let events = record_events(&group, cx);
        cx.update(|window, cx| window.draw(cx).clear(cx));

        drag_from_the_tab_into_the_content(cx);
        cx.simulate_mouse_up(
            point(px(450.), px(200.)),
            MouseButton::Left,
            Modifiers::none(),
        );
        cx.run_until_parked();

        assert_eq!(events.borrow().len(), 1, "got {:?}", events.borrow());
        assert!(
            events.borrow()[0].ends_with("split 1 Right"),
            "got {:?}",
            events.borrow()
        );
        assert!(cx.update(|_, cx| group.read(cx).drop_indicator.is_none()));
    }
}
