//! The dock area: the trees, the entity cache that mirrors them, and the
//! reconciliation that keeps the two in step.

use crate::TestSupportExt as _;
use std::{
    collections::{HashMap, HashSet},
    rc::Rc,
    sync::Arc,
};

use anyhow::Result;
use gpui::{
    AnyElement, AnyView, App, AppContext as _, Axis, Bounds, Context, Div, Empty, Entity,
    EventEmitter, FocusHandle, Focusable, InteractiveElement as _, IntoElement, ParentElement,
    Pixels, Point, Render, SharedString, Stateful, Styled as _, Subscription, WeakEntity, Window,
    div, prelude::FluentBuilder as _, px,
};

use crate::{
    ElementExt as _, Placement, ResizablePanelEvent, ResizableState, ResizeHandleContext,
    h_resizable, resizable::PANEL_MIN_SIZE, resizable_panel, v_resizable,
};

use super::{
    dock_placement::{Dock, DockSizing},
    drag::{AnyDrag, DropTarget},
    layout::{
        DockLayout, EditResult, InsertTarget, NodeId, NodeKind, PaneNode, PaneRef, PaneTree,
        PanelId, RootKind,
    },
    panel::{LivePanels, Panel, PanelEvent, PanelView},
    registry::{PanelBuildContext, PanelRegistry},
    state::{DockAreaState, DockPlacement, DockState, PanelInfo, PanelState},
    state_convert::{PanelBuilder, PanelSource as _},
    tab_group::{BareTabGroup, TabGroup, TabGroupConstraints, TabGroupEvent, TabGroupRenderer},
};

/// What the dock area reports outward.
pub enum DockEvent {
    /// The layout changed. Subscribe to persist it; this fires on every edit,
    /// so a subscriber that writes to disk should debounce.
    LayoutChanged,
    /// A host-owned drag item was dropped inside the dock.
    DragDrop { item: AnyDrag, target: DropTarget },
}

/// What fills the whole area, when something does.
///
/// A zoom names a *container*, never the panel inside it. The old dock zoomed
/// the `TabPanel`: `TabPanel` is the only thing that ever emitted
/// `PanelEvent::ZoomIn` — `subscribe_panel` was handed `StackPanel`s too, but
/// those never zoom — so `set_zoomed_in` only ever received a whole tab panel,
/// and a zoomed panel kept its tab bar, its toolbar and its menu. That is
/// where the control that zooms back out lives. Naming the panel instead would
/// strip all of it and leave the user with no way back.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
enum Zoomed {
    /// A tab group, rendered whole through its own [`TabGroupRenderer`].
    Group(NodeId),
}

/// One dock: its own layout tree plus the open/size/collapsible state.
struct DockRegion {
    tree: PaneTree,
    dock: Dock,
}

/// A cached container entity together with the subscription that carries its
/// intents back here. Kept as one value so dropping the cache entry drops the
/// subscription with it.
struct Cached<T> {
    entity: Entity<T>,
    _subscription: Subscription,
}

/// A split's cached `ResizableState`, plus the child order that state's panel
/// list currently mirrors.
///
/// The order is what makes a reconcile index-precise. `ResizableState` keeps
/// the authoritative size on `panels[ix]` and only ever consults the tree's
/// size as an initial value, so appending and truncating at the tail —
/// which is all `sync_panels_count` can do — leaves the survivors of a
/// non-tail removal wearing their predecessors' widths.
struct CachedSplit {
    entity: Entity<ResizableState>,
    children: Vec<NodeId>,
    /// The tree sizes the state last adopted. A reconcile that finds them
    /// unchanged leaves the state alone: re-adopting a `None` un-pins the
    /// measurement the layout pass resolved it to, and the split re-flexes
    /// although the edit never touched it.
    sizes: Vec<Option<Pixels>>,
    _subscription: Subscription,
}

/// The main area of the dock.
///
/// It owns one [`PaneTree`] per region and the entity cache that mirrors
/// them. Nothing else turns a tree edit into live entities.
pub struct DockArea {
    id: SharedString,
    version: Option<usize>,
    bounds: Bounds<Pixels>,
    this: WeakEntity<Self>,

    center: PaneTree,
    docks: HashMap<DockPlacement, DockRegion>,

    groups: HashMap<NodeId, Cached<TabGroup>>,
    splits: HashMap<NodeId, CachedSplit>,
    panels: HashMap<PanelId, Arc<dyn PanelView>>,

    locked: bool,
    zoomed: Option<Zoomed>,
    focus_handle: FocusHandle,
    renderer: Rc<dyn DockAreaRenderer>,
}

impl DockArea {
    /// An empty area that draws nothing but its panels.
    ///
    /// `id` names the area for the host's own persistence; `version` is
    /// written into [`Self::dump`] and read back by [`Self::load`], for a host
    /// that wants to reject or migrate a layout an older build wrote.
    ///
    /// Install appearance with [`Self::with_renderer`].
    pub fn new(
        id: impl Into<SharedString>,
        version: Option<usize>,
        _window: &mut Window,
        cx: &mut Context<Self>,
    ) -> Self {
        PanelRegistry::init(cx);

        Self {
            id: id.into(),
            version,
            bounds: Bounds::default(),
            this: cx.weak_entity(),
            center: PaneTree::new(RootKind::Split),
            docks: HashMap::new(),
            groups: HashMap::new(),
            splits: HashMap::new(),
            panels: HashMap::new(),
            locked: false,
            zoomed: None,
            focus_handle: cx.focus_handle(),
            renderer: Rc::new(BareDockArea),
        }
    }

    /// Install the appearance for this area and everything under it: the
    /// renderer also supplies the [`TabGroupRenderer`] every group it builds
    /// will use.
    pub fn with_renderer(mut self, renderer: Rc<dyn DockAreaRenderer>) -> Self {
        self.renderer = renderer;
        self
    }

    pub fn id(&self) -> SharedString {
        self.id.clone()
    }

    pub fn version(&self) -> Option<usize> {
        self.version
    }

    /// Change the schema version a later [`dump`](Self::dump) writes.
    ///
    /// Set at construction for an area whose layout never changes shape. A
    /// host that installs one of several preset layouts into the same area
    /// picks the version with the preset, which is after the area exists.
    pub fn set_version(&mut self, version: Option<usize>, cx: &mut Context<Self>) {
        self.version = version;
        cx.notify();
    }

    /// The area's own bounds, recorded each frame. Dock resizing measures
    /// against it.
    pub fn bounds(&self) -> Bounds<Pixels> {
        self.bounds
    }

    /// The tree for one region, or `None` for a dock that does not exist.
    ///
    /// The `Option` is in the signature rather than hidden behind a panic
    /// because a dock is genuinely optional — it is `Option<DockState>` in the
    /// persisted schema — and there is no borrowable empty tree to hand back
    /// for one that is absent.
    pub fn layout(&self, placement: DockPlacement) -> Option<&PaneTree> {
        match placement {
            DockPlacement::Center => Some(&self.center),
            _ => self.docks.get(&placement).map(|pane| &pane.tree),
        }
    }

    /// The live view for a panel, if the dock still holds it.
    pub fn panel(&self, panel: PanelId) -> Option<&Arc<dyn PanelView>> {
        self.panels.get(&panel)
    }

    pub fn is_locked(&self) -> bool {
        self.locked
    }

    /// Whether a region currently holds no visible panel.
    ///
    /// This is the question the old `DockItem::is_empty` answered, and it is
    /// the same one [`Self::is_node_visible`] answers per container: a region
    /// is empty when nothing in it would be drawn. A region that does not
    /// exist — a dock that was never installed — is empty too.
    pub fn is_empty(&self, placement: DockPlacement, cx: &App) -> bool {
        self.layout(placement)
            .is_none_or(|tree| !self.is_node_visible(tree.root(), cx))
    }

    /// Lock the layout against rearranging. Resizing stays available.
    pub fn set_locked(&mut self, locked: bool, window: &mut Window, cx: &mut Context<Self>) {
        if self.locked == locked {
            return;
        }
        self.locked = locked;
        // The lock is one of the facts every group is told, so it only takes
        // effect once the groups have been re-told.
        self.reconcile(window, cx);
    }
}

/// Installing layouts: the center region and the three docks.
impl DockArea {
    /// Replace the center region with a described layout. Whatever was there
    /// leaves the dock, so its panels are told [`Panel::on_removed`].
    pub fn set_center(&mut self, layout: DockLayout, window: &mut Window, cx: &mut Context<Self>) {
        let (tree, panels) = PaneTree::from_layout(layout, RootKind::Split);
        self.center = tree;
        self.panels.extend(panels);
        self.reconcile(window, cx);
        cx.emit(DockEvent::LayoutChanged);
    }

    /// Replace one dock with a described layout, creating the dock if the area
    /// does not have one there yet. A new dock keeps the size and open state of
    /// the one it replaces, so re-filling a dock does not resize it.
    ///
    /// [`DockPlacement::Center`] defers to [`Self::set_center`]: the center is
    /// not a dock and has no size or open state of its own.
    pub fn set_dock(
        &mut self,
        placement: DockPlacement,
        layout: DockLayout,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        if placement == DockPlacement::Center {
            return self.set_center(layout, window, cx);
        }

        let (tree, panels) = PaneTree::from_layout(layout, RootKind::Any);
        let dock = self
            .docks
            .get(&placement)
            .map(|pane| pane.dock)
            .unwrap_or_else(|| Dock::new(PANEL_MIN_SIZE * 2.));
        self.docks.insert(placement, DockRegion { tree, dock });
        self.panels.extend(panels);
        self.reconcile(window, cx);
        cx.emit(DockEvent::LayoutChanged);
    }

    /// Take a dock away entirely, panels and all. Distinct from
    /// [`Self::toggle_dock`], which only takes it off screen.
    pub fn remove_dock(
        &mut self,
        placement: DockPlacement,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        if self.docks.remove(&placement).is_none() {
            return;
        }
        // The dock's panels leave the dock entirely, so they are told, unlike
        // the panels of a dock that merely closed.
        self.reconcile(window, cx);
        cx.emit(DockEvent::LayoutChanged);
    }

    pub fn has_dock(&self, placement: DockPlacement) -> bool {
        self.docks.contains_key(&placement)
    }

    /// Whether a dock is on screen. A dock the area does not have is never
    /// open, so this answers the question a caller usually means without a
    /// preceding [`Self::has_dock`].
    pub fn is_dock_open(&self, placement: DockPlacement) -> bool {
        self.docks
            .get(&placement)
            .is_some_and(|pane| pane.dock.is_open())
    }

    /// Open a closed dock or close an open one. A dock that is not
    /// collapsible refuses to close; there is nothing to refuse when opening.
    pub fn toggle_dock(
        &mut self,
        placement: DockPlacement,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        let Some(pane) = self.docks.get_mut(&placement) else {
            return;
        };
        if !pane.dock.is_collapsible() && pane.dock.is_open() {
            return;
        }
        let open = pane.dock.is_open();
        pane.dock.set_open(!open);
        // A closed dock takes its displayed panel off screen, which the
        // active-state contract counts as no panel being displayed — that is
        // what `TabGroupConstraints::collapsed` carries.
        self.reconcile(window, cx);
        cx.emit(DockEvent::LayoutChanged);
    }

    /// Whether a dock may be collapsed at all. A skin drawing a collapse
    /// affordance in a tab bar reads this to decide whether to offer one.
    pub fn is_dock_collapsible(&self, placement: DockPlacement) -> bool {
        self.docks
            .get(&placement)
            .is_some_and(|pane| pane.dock.is_collapsible())
    }

    pub fn set_dock_collapsible(
        &mut self,
        placement: DockPlacement,
        collapsible: bool,
        _window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        if let Some(pane) = self.docks.get_mut(&placement) {
            pane.dock.set_collapsible(collapsible);
            cx.notify();
        }
    }

    /// The dock's size along its axis.
    pub fn dock_size(&self, placement: DockPlacement) -> Option<Pixels> {
        self.docks.get(&placement).map(|pane| pane.dock.size())
    }

    pub fn set_dock_size(
        &mut self,
        placement: DockPlacement,
        size: Pixels,
        _window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        if let Some(pane) = self.docks.get_mut(&placement) {
            let previous = pane.dock.size();
            pane.dock.set_size(size);
            if pane.dock.size() == previous {
                return;
            }
            cx.notify();
            cx.emit(DockEvent::LayoutChanged);
        }
    }
}

/// Editing the layout.
impl DockArea {
    /// Add a panel to a region, merging it into the first tab group there,
    /// or starting a group when the region is empty.
    pub fn add_panel<P: Panel>(
        &mut self,
        panel: Entity<P>,
        placement: DockPlacement,
        size: Option<Pixels>,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        let id = PanelId::from(panel.entity_id());
        self.add_panel_inner(id, Arc::new(panel), placement, size, window, cx);
    }

    /// Add an already-wrapped panel handle to a region.
    ///
    /// The companion to [`Self::add_panel`], for a layer that hands base its
    /// own concrete handle — see [`PanelView::as_any`] — rather than a bare
    /// entity. The id comes from [`PanelView::panel_id`], which is the only
    /// place it can come from once the entity is behind the handle.
    pub fn add_panel_view(
        &mut self,
        panel: Arc<dyn PanelView>,
        placement: DockPlacement,
        size: Option<Pixels>,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        let id = panel.panel_id(cx);
        self.add_panel_inner(id, panel, placement, size, window, cx);
    }

    fn add_panel_inner(
        &mut self,
        id: PanelId,
        panel: Arc<dyn PanelView>,
        placement: DockPlacement,
        size: Option<Pixels>,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        // The registration is written before the target is resolved, because
        // both want `&mut self`, so an add that finds nowhere to put the panel
        // has to undo it. *Undo*, not remove: adding a panel the dock already
        // holds is a legitimate call — a host re-placing one it owns — and
        // dropping its view would strand it in a tree with no entity, which is
        // what `reconcile`'s `views_of` asserts against.
        let previous = self.panels.insert(id, panel);

        // A dock is created to hold the panel; `size` seeds it.
        if placement != DockPlacement::Center && !self.docks.contains_key(&placement) {
            self.docks.insert(
                placement,
                DockRegion {
                    tree: PaneTree::new(RootKind::Any),
                    dock: Dock::new(size.unwrap_or(PANEL_MIN_SIZE * 2.)),
                },
            );
        }

        let Some(tree) = self.tree_mut(placement) else {
            self.restore_registration(id, previous);
            return;
        };
        let target = match first_tab_group(tree.root()) {
            Some(node) => InsertTarget::Tabs {
                node,
                ix: None,
                activate: true,
            },
            // An empty region has no container to merge into, so the panel
            // makes one beside the root. `normalize` then removes the emptied
            // root and, for a dock, collapses the wrapper away again.
            None => InsertTarget::Split {
                node: tree.root().id(),
                placement: Placement::Right,
                size,
            },
        };
        let result = tree.insert_panel(id, target);
        if !result.changed() {
            // Nothing took the panel, so a newly registered one must not
            // linger in the view map and be told `on_removed` by the next
            // reconcile.
            self.restore_registration(id, previous);
            return;
        }
        self.commit(result, window, cx);
    }

    /// Put the view map back the way an add found it, for one that placed
    /// nothing. `previous` is what [`HashMap::insert`] handed back.
    fn restore_registration(&mut self, id: PanelId, previous: Option<Arc<dyn PanelView>>) {
        match previous {
            Some(view) => self.panels.insert(id, view),
            None => self.panels.remove(&id),
        };
    }

    /// Remove a panel from wherever it lives, telling it that it was removed.
    pub fn remove_panel<P: Panel>(
        &mut self,
        panel: Entity<P>,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        self.remove_panel_id(PanelId::from(panel.entity_id()), window, cx);
    }

    /// Move a panel to a new home. The panel never leaves the dock, so it is
    /// never told it was removed.
    pub fn move_panel(
        &mut self,
        panel: PanelId,
        target: InsertTarget,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        // A panel this area does not own (e.g. dropped from a nested dock) has
        // no backing entity here; inserting it would strand a ghost tab.
        if self.panel(panel).is_none() {
            return;
        }
        let Some(destination) = self.placement_of_node(target_node(&target)) else {
            return;
        };
        let source = self.placement_of_panel(panel);

        // A split target divides an existing slot, so the tree needs real
        // pixels to divide.
        if matches!(target, InsertTarget::Split { .. }) {
            self.adopt_measured_sizes(destination, cx);
        }

        // Read what the source group last told the panel *before* the edit,
        // so the destination can be seeded with it. Without this a panel
        // dragged between groups while displayed is told `true` twice.
        let was_active = self
            .layout(source.unwrap_or(destination))
            .and_then(|tree| tree.find_panel_node(panel))
            .and_then(|node| self.groups.get(&node))
            .and_then(|cached| cached.entity.read(cx).last_notified_active(panel));

        let changed = match source {
            Some(source) if source == destination => {
                let Some(tree) = self.tree_mut(destination) else {
                    return;
                };
                tree.move_panel(panel, target).changed()
            }
            source => {
                // Across trees a move is a detach plus an insert. The detach's
                // `removed_panels` is deliberately dropped on the floor: the
                // panel is still in the dock, so it must not hear `on_removed`.
                //
                // Both halves are committed on, not just the insert. A target
                // whose node kind does not match the insert is a silent no-op
                // in `apply_insert`, and committing on the insert alone would
                // early-return with the panel already gone from the source —
                // stranded in `self.panels`, belonging to no tree, for the
                // next reconcile to prune and destroy.
                let detached = source
                    .and_then(|source| self.tree_mut(source))
                    .is_some_and(|tree| tree.remove_panel(panel).changed());
                let Some(tree) = self.tree_mut(destination) else {
                    return;
                };
                let inserted = tree.insert_panel(panel, target).changed();
                detached || inserted
            }
        };

        self.commit_changed(changed, window, cx);

        if let Some(active) = was_active {
            if let Some(cached) = self
                .layout(destination)
                .and_then(|tree| tree.find_panel_node(panel))
                .and_then(|node| self.groups.get(&node))
            {
                let group = cached.entity.clone();
                group.update(cx, |group, _| group.seed_active(panel, active));
            }
        }
    }

    /// Display `panel` in the tab group that holds it, wherever that is.
    ///
    /// A host that is handed a file already open, or restores the tab a
    /// layout recorded as active, wants that tab shown where it sits.
    /// [`Self::move_panel`] with `activate` would also move it, and the group
    /// entities are the dock's own, so this is the one way to select a panel
    /// by identity. Nothing happens for a panel the dock does not hold, or
    /// one already displayed.
    pub fn select_panel(&mut self, panel: PanelId, window: &mut Window, cx: &mut Context<Self>) {
        let Some(placement) = self.placement_of_panel(panel) else {
            return;
        };
        let Some(tree) = self.tree_mut(placement) else {
            return;
        };
        let Some(node) = tree.find_panel_node(panel) else {
            return;
        };
        let ix = tree.find_node(node).and_then(|node| match node.kind() {
            PaneRef::Tabs { panels, .. } => panels.iter().position(|held| *held == panel),
            PaneRef::Split { .. } => None,
        });
        let Some(ix) = ix else {
            return;
        };
        let result = tree.set_active(node, ix);
        self.commit(result, window, cx);
    }

    /// Replace the slot sizes of the split at `node` in place.
    pub fn set_split_sizes(
        &mut self,
        node: NodeId,
        sizes: Vec<Pixels>,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        let Some(placement) = self.placement_of_node(node) else {
            return;
        };
        let Some(tree) = self.tree_mut(placement) else {
            return;
        };
        let result = tree.set_sizes(node, sizes.into_iter().map(Some).collect());
        self.commit(result, window, cx);
    }

    /// Put `panel` in a new tab group beside `node`.
    pub fn split_at(
        &mut self,
        node: NodeId,
        panel: PanelId,
        placement: Placement,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        let Some(region) = self.placement_of_node(node) else {
            return;
        };
        self.adopt_measured_sizes(region, cx);
        let Some(tree) = self.tree_mut(region) else {
            return;
        };
        let result = tree.split(node, panel, placement, None);
        self.commit(result, window, cx);
    }

    fn remove_panel_id(&mut self, panel: PanelId, window: &mut Window, cx: &mut Context<Self>) {
        let Some(region) = self.placement_of_panel(panel) else {
            return;
        };
        let focused = window.focused(cx);
        let had_focus = self
            .panel(panel)
            .is_some_and(|view| view.focus_handle(cx).contains_focused(window, cx));
        // Prefer the same group, then the groups following it in layout order,
        // then preceding groups from nearest to farthest. Preserve this order
        // before normalization removes an emptied group or collapses its split.
        let mut candidates = Vec::new();
        if had_focus && let Some(tree) = self.layout(region) {
            tree.root().walk(&mut |node| {
                if matches!(node.kind(), PaneRef::Tabs { .. }) {
                    candidates.push(node.id());
                }
            });
            if let Some(ix) = tree
                .find_panel_node(panel)
                .and_then(|node| candidates.iter().position(|candidate| *candidate == node))
            {
                candidates = candidates[ix..]
                    .iter()
                    .chain(candidates[..ix].iter().rev())
                    .copied()
                    .collect();
            }
        }
        let Some(tree) = self.tree_mut(region) else {
            return;
        };
        let result = tree.remove_panel(panel);
        self.commit(result, window, cx);

        // on_removed may deliberately focus another control (or clear focus).
        // Automatic handoff is only the fallback when the callback left it alone.
        if !had_focus || window.focused(cx) != focused {
            return;
        }
        let next = candidates
            .into_iter()
            .find_map(|node| self.focus_target_in_group(node, cx))
            .or_else(|| {
                [
                    DockPlacement::Center,
                    DockPlacement::Left,
                    DockPlacement::Right,
                    DockPlacement::Bottom,
                ]
                .into_iter()
                .filter(|placement| *placement != region)
                .filter(|placement| {
                    *placement == DockPlacement::Center
                        || self
                            .docks
                            .get(placement)
                            .is_some_and(|pane| pane.dock.is_open())
                })
                .find_map(|placement| {
                    self.layout(placement)
                        .and_then(|tree| self.focus_target_in_node(tree.root(), cx))
                })
            });
        if let Some(next) = next {
            next.focus_handle(cx).focus(window, cx);
        }
    }

    fn focus_target_in_group(&self, node: NodeId, cx: &App) -> Option<Arc<dyn PanelView>> {
        if self.zoomed.is_some_and(|zoom| zoom != Zoomed::Group(node)) {
            return None;
        }
        let group = self.groups.get(&node)?.entity.read(cx);
        if group.is_collapsed() {
            return None;
        }
        group.active_panel(cx)
    }

    fn focus_target_in_node(&self, node: &PaneNode, cx: &App) -> Option<Arc<dyn PanelView>> {
        match node.kind() {
            PaneRef::Tabs { .. } => self.focus_target_in_group(node.id(), cx),
            PaneRef::Split { children, .. } => children
                .iter()
                .find_map(|child| self.focus_target_in_node(child, cx)),
        }
    }
}

/// Zooming.
///
/// There is no `set_zoomed_in(panel)` here. A zoom is a container's own act:
/// only the container knows whether its displayed panel is zoomable, and only
/// the container can tell that panel it was zoomed. So the way in is
/// [`TabGroupContext::toggle_zoom`](super::TabGroupContext::toggle_zoom) — a
/// skin has one wherever it draws a zoom control — or
/// [`Self::set_zoomed_in`] by node, which delegates to the same place. The
/// area then installs the container that reported it.
impl DockArea {
    /// Zoom the tab group at `node` in, as if its own zoom control had been
    /// used.
    ///
    /// Nothing happens for a node that is not a live tab group, or when the
    /// group refuses — the group is the one that knows.
    pub fn set_zoomed_in(&mut self, node: NodeId, window: &mut Window, cx: &mut Context<Self>) {
        self.set_zoom(Some(Zoomed::Group(node)), window, cx);
    }

    /// Clear the zoom, putting the zoomed container's own flag back with it.
    ///
    /// A container toggles its zoom itself and only reports it, so an area
    /// that dropped the view without telling the container would leave it
    /// believing it still fills the dock — and a zoomed group refuses drops.
    pub fn set_zoomed_out(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        self.set_zoom(None, window, cx);
    }

    pub fn is_zoomed(&self) -> bool {
        self.zoomed.is_some()
    }

    /// The tab group filling the area, if a group is what is zoomed.
    pub fn zoomed_group(&self) -> Option<NodeId> {
        match self.zoomed {
            Some(Zoomed::Group(node)) => Some(node),
            _ => None,
        }
    }

    /// The one place `self.zoomed` is written.
    ///
    /// Every write drives the container's own flag through the same call, and
    /// the new target is recorded only if that container accepted it. So the
    /// area cannot show a container the container does not think is zoomed,
    /// and cannot leave a container flagged zoomed while showing something
    /// else — the split state a group would carry as a permanent lock.
    fn set_zoom(&mut self, zoomed: Option<Zoomed>, window: &mut Window, cx: &mut Context<Self>) {
        if self.zoomed == zoomed {
            return;
        }

        if let Some(previous) = self.zoomed {
            self.drive_zoom(previous, false, window, cx);
        }
        let accepted = match zoomed {
            Some(next) => self.drive_zoom(next, true, window, cx).then_some(next),
            None => None,
        };
        self.zoomed = accepted;
        cx.notify();
    }

    /// Ask one container to zoom in or out, and report whether it now agrees.
    ///
    /// A container that has already been left out of the cache — its node is
    /// gone from the tree — has nothing to say and nothing to put back, so it
    /// answers `false` and a zoom naming it is never installed.
    fn drive_zoom(
        &mut self,
        zoomed: Zoomed,
        zoom_in: bool,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) -> bool {
        match zoomed {
            Zoomed::Group(node) => {
                let Some(group) = self.groups.get(&node).map(|cached| cached.entity.clone()) else {
                    return false;
                };
                group.update(cx, |group, cx| {
                    group.set_zoomed(zoom_in, window, cx);
                    group.is_zoomed() == zoom_in
                })
            }
        }
    }

    /// The container that fills the area when something is zoomed.
    ///
    /// The container, not the panel inside it: this is what keeps a zoomed
    /// group's tab bar on screen.
    fn zoomed_view(&self) -> Option<AnyView> {
        match self.zoomed? {
            Zoomed::Group(node) => Some(self.groups.get(&node)?.entity.clone().into()),
        }
    }
}

/// Persistence.
impl DockArea {
    /// Read a persisted layout, rebuilding every panel through
    /// [`PanelRegistry`]. A panel this build does not know about becomes a
    /// placeholder that carries the original [`PanelState`] forward, so the
    /// next save does not erase it.
    pub fn load(
        &mut self,
        state: DockAreaState,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) -> Result<()> {
        self.version = state.version;
        self.zoomed = None;
        // Nothing in the old layout survives a load, so the caches are
        // emptied rather than reconciled: every node id in the new trees is
        // freshly minted and would miss the old cache anyway.
        self.groups.clear();
        self.splits.clear();
        self.docks.clear();
        // `self.panels` is deliberately *not* cleared: leaving the outgoing
        // panels in it lets `reconcile` prune them, which is what tells them
        // they were removed.

        let dock_area = self.this.clone();
        let renderer = self.renderer.clone();
        let mut built = Vec::new();
        self.center = {
            let mut builder = RegistryPanelBuilder {
                dock_area: dock_area.clone(),
                renderer: renderer.clone(),
                built: &mut built,
                window,
                cx,
            };
            PaneTree::from_state(&state.center, RootKind::Split, &mut builder)
        };

        for dock_state in [state.left_dock, state.right_dock, state.bottom_dock]
            .into_iter()
            .flatten()
        {
            let tree = {
                let mut builder = RegistryPanelBuilder {
                    dock_area: dock_area.clone(),
                    renderer: renderer.clone(),
                    built: &mut built,
                    window,
                    cx,
                };
                PaneTree::from_state(dock_state.panel(), RootKind::Any, &mut builder)
            };
            let mut dock = Dock::new(dock_state.size());
            dock.set_open(dock_state.open());
            self.docks
                .insert(dock_state.placement(), DockRegion { tree, dock });
        }

        self.panels.extend(built);
        self.reconcile(window, cx);
        cx.emit(DockEvent::LayoutChanged);
        Ok(())
    }

    /// Write the layout out.
    ///
    /// Slot sizes are resolved to concrete pixels first. The tree represents
    /// an unconstrained slot as `None` and the writer emits `0.0` for it,
    /// which *this* reader maps back to `None` — but an older build has no
    /// notion of the sentinel and would construct a real zero-pixel panel from
    /// it. Preference order is the split's measured size, then the tree's own
    /// size, then [`PANEL_MIN_SIZE`] for a slot nothing has ever measured.
    ///
    /// The measurement wins because the tree does not track every change to
    /// it. `ResizableState` only emits `Resized` from a finished drag, so that
    /// is all the subscription in [`Self::split_entity`] writes back;
    /// `adjust_to_container_size` rescales every slot silently on each window
    /// resize, insert and remove. Preferring the tree would persist load-time
    /// or last-drag pixels after a window resize, and worse, mix them: a slot
    /// left `None` by a later insert would be filled from the current
    /// measurement while its untouched siblings kept file-era numbers, so the
    /// written ratio would match neither the file nor the screen. Reading the
    /// measurement for every slot of a split writes one internally consistent
    /// set, which is what the old `StackPanel::dump` did.
    pub fn dump(&self, cx: &App) -> DockAreaState {
        let source = LivePanels::new(&self.panels, cx);

        DockAreaState {
            version: self.version,
            center: self.resolved_tree(&self.center, cx).to_state(&source),
            left_dock: self.dump_dock(DockPlacement::Left, &source, cx),
            right_dock: self.dump_dock(DockPlacement::Right, &source, cx),
            bottom_dock: self.dump_dock(DockPlacement::Bottom, &source, cx),
        }
    }

    fn dump_dock(
        &self,
        placement: DockPlacement,
        source: &LivePanels<'_>,
        cx: &App,
    ) -> Option<DockState> {
        let pane = self.docks.get(&placement)?;
        Some(DockState::new(
            self.resolved_tree(&pane.tree, cx).to_state(source),
            placement,
            pane.dock.size(),
            pane.dock.is_open(),
        ))
    }

    fn resolved_tree(&self, tree: &PaneTree, cx: &App) -> PaneTree {
        let mut tree = tree.clone();
        self.resolve_sizes(tree.root_mut(), cx);
        tree
    }

    fn resolve_sizes(&self, node: &mut PaneNode, cx: &App) {
        let measured = self
            .splits
            .get(&node.id())
            .map(|cached| cached.entity.read(cx).sizes().clone())
            .unwrap_or_default();

        let NodeKind::Split {
            children, sizes, ..
        } = node.kind_mut()
        else {
            return;
        };

        for (ix, size) in sizes.iter_mut().enumerate() {
            // A slot already holding zero is exactly as unsafe as an absent
            // one: it is the same byte in the file and the same zero-pixel
            // panel in an older build. So both the measurement and the stored
            // value have to clear zero before they can be written.
            let on_screen = measured.get(ix).copied().filter(|size| *size > px(0.));
            let stored = (*size).filter(|size| *size > px(0.));
            *size = Some(on_screen.or(stored).unwrap_or(PANEL_MIN_SIZE));
        }

        for child in children.iter_mut() {
            self.resolve_sizes(child, cx);
        }
    }
}

/// Reconciliation.
impl DockArea {
    /// Apply one edit: bring the entity cache back in line and say so.
    ///
    /// `on_removed` is not fired from `EditResult::removed_panels` here.
    /// [`Self::reconcile`] fires it instead, from the panels it prunes: that
    /// is the same set for a plain removal, and it also covers the panels a
    /// wholesale `set_center`, `set_dock`, `remove_dock` or `load` displaces,
    /// which no `EditResult` describes at all. It is also the safer default —
    /// a caller cannot forget a list it does not pass.
    fn commit(&mut self, result: EditResult, window: &mut Window, cx: &mut Context<Self>) {
        self.commit_changed(result.changed(), window, cx);
    }

    /// [`Self::commit`] for an edit that took more than one `EditResult`.
    fn commit_changed(&mut self, changed: bool, window: &mut Window, cx: &mut Context<Self>) {
        if !changed {
            return;
        }

        self.reconcile(window, cx);
        cx.emit(DockEvent::LayoutChanged);
    }

    /// Bring the entity cache in line with the trees.
    ///
    /// Because `NodeId` survives every edit and every normalization rule, a
    /// steady-state pass creates and drops nothing; only genuinely new or dead
    /// containers churn. That is what keeps a drag from resetting the state of
    /// panels it did not touch.
    fn reconcile(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        // Planned first, applied second: the plan borrows the trees, and
        // applying it needs `&mut self` to fill the caches.
        let mut plans = Vec::new();
        plan_tree(&self.center, false, self.locked, &mut plans);
        for pane in self.docks.values() {
            plan_tree(&pane.tree, !pane.dock.is_open(), self.locked, &mut plans);
        }

        // Sets rather than vectors: these are membership tests, run once per
        // cached entity and once per live panel, and a drag reaches this path
        // on every mouse move.
        let mut live_nodes = HashSet::with_capacity(plans.len());
        let mut live_panels: HashSet<PanelId> = HashSet::new();

        for plan in plans {
            live_nodes.insert(plan.node());
            match plan {
                ContainerPlan::Split {
                    node,
                    axis,
                    children,
                    sizes,
                } => {
                    let state = self.split_entity(node, cx);
                    let (previous, adopted) = self
                        .splits
                        .get(&node)
                        .map(|cached| (cached.children.clone(), cached.sizes.clone()))
                        .unwrap_or_default();
                    // Only a split the edit changed is handed anything. The
                    // state of every other split may legitimately disagree
                    // with its tree — a window resize rescales it silently —
                    // and pushing the tree's sizes back would move slots the
                    // edit never named. For a slot the tree leaves `None`, it
                    // would also un-pin the measurement the first layout pass
                    // resolved it to, and the whole split re-flexes.
                    if previous != children || adopted != sizes {
                        state.update(cx, |state, cx| {
                            sync_split_panels(state, &previous, &children, &sizes, cx);
                            state.sync_panels_count(axis, children.len(), cx);
                            // The tree is authoritative on how space divides,
                            // so its sizes land last — `insert_panel`
                            // renormalizes everything it touches, which would
                            // otherwise undo the share an edit just decided.
                            //
                            // What the tree decides is the *share*, not the
                            // pixel count. The file holds absolute pixels
                            // measured in whatever window last saved it, so
                            // restoring into a different one leaves their
                            // total off the container — and
                            // `adjust_to_container_size` rescales the state to
                            // the container on the very next pass. Adopting
                            // the raw numbers would re-assert the stale total,
                            // so hand over the share instead and both sides
                            // already agree.
                            state.adopt_sizes(&scale_sizes_to(state.container_size(), &sizes), cx);
                        });
                    }
                    if let Some(cached) = self.splits.get_mut(&node) {
                        cached.children = children;
                        cached.sizes = sizes;
                    }
                }
                ContainerPlan::Group {
                    node,
                    panels,
                    active_ix,
                    constraints,
                } => {
                    live_panels.extend(panels.iter().copied());
                    let views = self.views_of(&panels);
                    let group = self.group_entity(node, window, cx);
                    group.update(cx, |group, cx| {
                        // Every group must be told this. A group nobody has
                        // constrained stays `sealed()` and silently declines
                        // drags, drops and closes.
                        group.set_constraints(constraints, window, cx);
                        group.sync_from_tree(views, active_ix, window, cx);
                    });
                }
            }
        }

        self.groups.retain(|node, _| live_nodes.contains(node));
        self.splits.retain(|node, _| live_nodes.contains(node));

        let departed: Vec<Arc<dyn PanelView>> = self
            .panels
            .iter()
            .filter(|(panel, _)| !live_panels.contains(panel))
            .map(|(_, view)| view.clone())
            .collect();
        self.panels.retain(|panel, _| live_panels.contains(panel));

        // A zoomed container fills the whole area, so one that has just left
        // the dock would otherwise keep filling it with nothing behind it.
        //
        // It is the container going away that ends the zoom, not a panel:
        // a group survives its displayed panel closing, and the next tab
        // takes over, still zoomed. The old `TabPanel::remove_panel` instead
        // emitted `ZoomOut` on every removal, which cleared the dock's zoom
        // even for a panel in some other tab panel entirely — and left the
        // zoomed `TabPanel` still flagged zoomed while the dock was not.
        let zoom_survives = match self.zoomed {
            Some(Zoomed::Group(node)) => self.groups.contains_key(&node),
            None => true,
        };
        if !zoom_survives {
            self.set_zoom(None, window, cx);
        }

        cx.notify();
        // Last, so a panel reacting to this sees a dock that already agrees
        // with its trees.
        for view in departed {
            view.on_removed(window, cx);
        }
    }

    /// The views for a group's panel ids, in tab order.
    fn views_of(&self, panels: &[PanelId]) -> Vec<Arc<dyn PanelView>> {
        debug_assert!(
            panels.iter().all(|panel| self.panels.contains_key(panel)),
            "every panel in a tree must have a live view; a missing one would \
             silently shift the group's active index"
        );
        panels
            .iter()
            .filter_map(|panel| self.panels.get(panel).cloned())
            .collect()
    }

    fn group_entity(
        &mut self,
        node: NodeId,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) -> Entity<TabGroup> {
        if let Some(cached) = self.groups.get(&node) {
            return cached.entity.clone();
        }

        let renderer = self.renderer.tab_group_renderer();
        let entity = cx.new(|cx| TabGroup::new(node, window, cx).with_renderer(renderer));
        let subscription = cx.subscribe_in(&entity, window, Self::on_tab_group_event);
        self.groups.insert(
            node,
            Cached {
                entity: entity.clone(),
                _subscription: subscription,
            },
        );
        entity
    }

    fn split_entity(&mut self, node: NodeId, cx: &mut Context<Self>) -> Entity<ResizableState> {
        if let Some(cached) = self.splits.get(&node) {
            return cached.entity.clone();
        }

        let entity = cx.new(|_| ResizableState::default());
        // A drag on a resize handle changes only the measured sizes. Writing
        // them straight back keeps the tree describing the layout the user
        // arranged, which is what a later insert or removal scales from and
        // what a region with no live split entity is dumped from.
        //
        // It does not make the tree authoritative on slot sizes generally, and
        // `dump` does not treat it as such: only a finished drag arrives here,
        // while `adjust_to_container_size` rewrites the measurements silently
        // on every window resize. See [`Self::dump`].
        let subscription =
            cx.subscribe(&entity, move |this, state, _: &ResizablePanelEvent, cx| {
                let sizes: Vec<Option<Pixels>> = state
                    .read(cx)
                    .sizes()
                    .iter()
                    .map(|size| Some(*size))
                    .collect();
                let Some(region) = this.placement_of_node(node) else {
                    return;
                };
                let Some(tree) = this.tree_mut(region) else {
                    return;
                };
                if tree.set_sizes(node, sizes.clone()).changed() {
                    cx.emit(DockEvent::LayoutChanged);
                }
                // The state is where these came from, so the next reconcile
                // has nothing to hand it.
                if let Some(cached) = this.splits.get_mut(&node) {
                    cached.sizes = sizes;
                }
            });
        self.splits.insert(
            node,
            CachedSplit {
                entity: entity.clone(),
                children: Vec::new(),
                sizes: Vec::new(),
                _subscription: subscription,
            },
        );
        entity
    }
}

/// Intents arriving from the containers.
impl DockArea {
    fn on_tab_group_event(
        &mut self,
        group: &Entity<TabGroup>,
        event: &TabGroupEvent,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        match event {
            TabGroupEvent::Drop { panel, target, .. } => {
                self.move_panel(*panel, *target, window, cx)
            }
            TabGroupEvent::DragDrop { item, target } => cx.emit(DockEvent::DragDrop {
                item: item.clone(),
                target: *target,
            }),
            TabGroupEvent::ClosePanel { panel } => self.remove_panel_id(*panel, window, cx),
            TabGroupEvent::ActiveChanged { ix } => {
                let node = group.read(cx).node();
                let Some(region) = self.placement_of_node(node) else {
                    return;
                };
                let Some(tree) = self.tree_mut(region) else {
                    return;
                };
                let result = tree.set_active(node, *ix);
                self.commit(result, window, cx);
            }
            TabGroupEvent::ZoomIn => {
                let node = group.read(cx).node();
                self.set_zoom(Some(Zoomed::Group(node)), window, cx);
            }
            // Only the group that is actually on screen can give the dock
            // back. A group told to zoom out to make room for another one
            // reports it too, and that report must not undo the zoom that
            // replaced it.
            TabGroupEvent::ZoomOut => {
                let node = group.read(cx).node();
                if self.zoomed == Some(Zoomed::Group(node)) {
                    self.set_zoom(None, window, cx);
                }
            }
        }
    }
}

/// Region lookup.
impl DockArea {
    /// Feed every split's measured size back into the tree before an edit
    /// that has to divide space.
    ///
    /// Done here rather than continuously: the tree is the record of what the
    /// user arranged, and rewriting it on every layout pass would let a
    /// transient window size become the stored layout.
    fn adopt_measured_sizes(&mut self, placement: DockPlacement, cx: &App) {
        let measured: HashMap<NodeId, Vec<Pixels>> = self
            .splits
            .iter()
            // Only splits that have actually been laid out. A split created
            // earlier in this same edit has a zero container and its `sizes`
            // are whatever `insert_panel` left behind — adopting those would
            // freeze a placeholder ratio into the tree, and every later edit
            // would divide space according to it.
            .filter(|(_, cached)| cached.entity.read(cx).container_size() > Pixels::ZERO)
            .map(|(node, cached)| (*node, cached.entity.read(cx).sizes().clone()))
            .collect();

        if let Some(tree) = self.tree_mut(placement) {
            tree.adopt_measured_sizes(&measured);
        }
    }

    fn tree_mut(&mut self, placement: DockPlacement) -> Option<&mut PaneTree> {
        match placement {
            DockPlacement::Center => Some(&mut self.center),
            _ => self.docks.get_mut(&placement).map(|pane| &mut pane.tree),
        }
    }

    /// Which region a container belongs to. Unambiguous because `NodeId`s are
    /// allocated globally rather than per tree.
    fn placement_of_node(&self, node: NodeId) -> Option<DockPlacement> {
        if self.center.find_node(node).is_some() {
            return Some(DockPlacement::Center);
        }
        self.docks
            .iter()
            .find(|(_, pane)| pane.tree.find_node(node).is_some())
            .map(|(placement, _)| *placement)
    }

    fn placement_of_panel(&self, panel: PanelId) -> Option<DockPlacement> {
        if self.center.find_panel_node(panel).is_some() {
            return Some(DockPlacement::Center);
        }
        self.docks
            .iter()
            .find(|(_, pane)| pane.tree.find_panel_node(panel).is_some())
            .map(|(placement, _)| *placement)
    }

    /// Resize one dock from a pointer position, clamped so neither this dock
    /// nor the one opposite is squeezed below its minimum.
    ///
    /// A collapsible bottom dock is the exception: it follows the pointer
    /// below the minimum down to its closed strip, so closing it by drag is
    /// one continuous motion. That size is only shown, and
    /// [`Self::end_dock_resize`] settles it on release.
    fn resize_dock(
        &mut self,
        placement: DockPlacement,
        pointer: Point<Pixels>,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        let opposite = match placement {
            DockPlacement::Left => self.dock_size(DockPlacement::Right),
            DockPlacement::Right => self.dock_size(DockPlacement::Left),
            _ => None,
        };
        let sizing = DockSizing::new(placement)
            .with_area_bounds(self.bounds)
            .with_opposite_dock_size(opposite.unwrap_or(px(0.)));
        let size = sizing
            .size_from_pointer(pointer)
            .min(sizing.clamp(Pixels::MAX));

        let Some(pane) = self.docks.get_mut(&placement) else {
            return;
        };
        let was_open = pane.dock.is_open();
        if placement == DockPlacement::Bottom && pane.dock.is_collapsible() && size < PANEL_MIN_SIZE
        {
            pane.dock.set_open(size > CLOSED_BOTTOM_STRIP);
            pane.dock.set_live_size(Some(size.max(CLOSED_BOTTOM_STRIP)));
        } else {
            pane.dock.set_open(true);
            pane.dock.set_live_size(None);
            pane.dock.set_size(size);
        }
        if pane.dock.is_open() != was_open {
            self.reconcile(window, cx);
        }
        cx.notify();
    }

    /// Settle a drag that ended below the minimum: nearer the closed strip it
    /// closes, nearer the minimum it opens at the minimum.
    fn end_dock_resize(
        &mut self,
        placement: DockPlacement,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        let Some(pane) = self.docks.get_mut(&placement) else {
            return;
        };
        let Some(size) = pane.dock.live_size() else {
            return;
        };
        pane.dock.set_live_size(None);

        let open = size >= (CLOSED_BOTTOM_STRIP + PANEL_MIN_SIZE) / 2.;
        if open {
            pane.dock.set_size(PANEL_MIN_SIZE);
        }
        if pane.dock.is_open() != open {
            pane.dock.set_open(open);
            self.reconcile(window, cx);
        }
        cx.notify();
    }
}

/// Rendering.
impl DockArea {
    /// Lower one container to an element.
    fn render_node(&self, node: &PaneNode, window: &mut Window, cx: &mut App) -> AnyElement {
        match node.kind() {
            PaneRef::Split {
                axis,
                children,
                sizes,
            } => {
                let group = match axis {
                    Axis::Horizontal => h_resizable(("dock-split", node.id().as_u64())),
                    Axis::Vertical => v_resizable(("dock-split", node.id().as_u64())),
                };
                // A container whose every panel is hidden must not keep
                // occupying its slot. No renderer hook could supply this:
                // only the area can see the panels behind a node.
                let shown: Vec<bool> = children
                    .iter()
                    .map(|child| self.is_node_visible(child, cx))
                    .collect();
                // The slot that absorbs the leftover has to be one that is
                // actually drawn. A hidden slot renders nothing and grows
                // nothing, so making it the flexible one leaves every drawn
                // slot rigid and the split ends short of its container — the
                // empty strip this picks the *last shown* slot to avoid.
                let grows = shown.iter().rposition(|shown| *shown);
                let panels: Vec<_> = children
                    .iter()
                    .zip(sizes.iter())
                    .enumerate()
                    .map(|(ix, (child, size))| {
                        resizable_panel()
                            .visible(shown[ix])
                            .child(self.render_node(child, window, cx))
                            // `flex_none` is what makes the size stick.
                            // `ResizablePanel` sets `flex_grow: 1` on itself,
                            // so a slot given a size would otherwise treat it
                            // as a flex-basis and still absorb an equal share
                            // of the leftover — a 200px sidebar rendering
                            // 1075px wide in a 1950px split.
                            // The growth slot absorbs container growth. A
                            // drag records every measured size as pixels; if
                            // all of them became `flex_none`, a later viewport
                            // resize would leave an empty strip after the
                            // split instead of keeping the Dock filled.
                            .when_some(*size, |panel, size| {
                                panel
                                    .size(size)
                                    .when(Some(ix) != grows, |panel| panel.flex_none())
                            })
                    })
                    .collect();

                let group = group
                    .when_some(self.splits.get(&node.id()), |group, cached| {
                        group.with_state(&cached.entity)
                    })
                    .with_handle_appearance({
                        let renderer = self.renderer.clone();
                        Rc::new(move |handle, window, cx| {
                            renderer.render_split_handle(handle, window, cx)
                        })
                    })
                    .children(panels);

                self.renderer
                    .split_frame(node.id(), axis, window, cx)
                    // A split frame with no size collapses: base puts it
                    // between a `resizable_panel` and the resizable group, and
                    // between `center_frame` and the centre's root split, and
                    // neither parent sizes it. `size_full` and `flex_1` are
                    // belt and braces -- either alone passes every case I could
                    // construct, so this does not depend on which one wins in a
                    // given parent.
                    .size_full()
                    .flex_1()
                    .min_h(px(0.))
                    .overflow_hidden()
                    .child(group)
                    .into_any_element()
            }
            PaneRef::Tabs { .. } => match self.groups.get(&node.id()) {
                Some(cached) => cached.entity.clone().into_any_element(),
                None => Empty.into_any_element(),
            },
        }
    }

    /// Whether anything in this container is on screen.
    ///
    /// Mirrors the old `StackPanel::render`, which asked each slot's
    /// `TabPanel::visible` — "does this group hold any visible panel?" — and
    /// hid the slot when it did not.
    fn is_node_visible(&self, node: &PaneNode, cx: &App) -> bool {
        let panels = LivePanels::new(&self.panels, cx);
        match node.kind() {
            PaneRef::Split { children, .. } => {
                children.iter().any(|child| self.is_node_visible(child, cx))
            }
            PaneRef::Tabs { panels: ids, .. } => ids.iter().any(|panel| panels.is_visible(*panel)),
        }
    }

    fn render_dock(
        &self,
        placement: DockPlacement,
        window: &mut Window,
        cx: &mut App,
    ) -> Option<AnyElement> {
        let pane = self.docks.get(&placement)?;
        let dock = self.dock_context(placement, &pane.dock);

        // A closed left or right dock takes no space at all; a closed bottom
        // dock keeps a strip so its tab bar stays clickable. Nothing is drawn
        // for a dock with no extent, and the renderer is not asked for chrome
        // nobody can see.
        let size = dock_extent(&dock);
        if size <= px(0.) {
            return Some(div().into_any_element());
        }

        let content = self.render_node(pane.tree.root(), window, cx);
        // The box is applied here rather than left to the renderer, and that is
        // the whole point of it being here. A dock's extent along its own axis
        // is not presentation -- it is what makes the dock a column beside the
        // centre instead of a block in the flow below it -- and a renderer that
        // did not know to state it produced a dock with no width, every pane
        // inside it shrunk to its content. `render_dock` on the renderer is a
        // chrome hook, so a renderer that draws nothing at all still gets a
        // dock that is the right shape.
        let chrome = self.renderer.render_dock(&dock, content, window, cx);
        Some(dock_frame(&dock, size).child(chrome).into_any_element())
    }

    fn dock_context(&self, placement: DockPlacement, dock: &Dock) -> DockContext {
        let area = self.this.clone();

        DockContext {
            placement,
            size: dock.live_size().unwrap_or(dock.size()),
            open: dock.is_open(),
            collapsible: dock.is_collapsible(),
            on_toggle: {
                let area = area.clone();
                Rc::new(move |window, cx| {
                    _ = area.update(cx, |area, cx| area.toggle_dock(placement, window, cx));
                })
            },
            on_resize: {
                let area = area.clone();
                Rc::new(move |pointer, window, cx| {
                    _ = area.update(cx, |area, cx| {
                        area.resize_dock(placement, pointer, window, cx)
                    });
                })
            },
            on_resize_end: Rc::new(move |window, cx| {
                _ = area.update(cx, |area, cx| area.end_dock_resize(placement, window, cx));
            }),
        }
    }
}

impl EventEmitter<DockEvent> for DockArea {}

impl Focusable for DockArea {
    fn focus_handle(&self, _: &App) -> FocusHandle {
        self.focus_handle.clone()
    }
}

impl Render for DockArea {
    fn render(&mut self, window: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        let area = cx.entity();
        let renderer = self.renderer.clone();

        renderer
            .frame(window, cx)
            .test_support()
            // Structure, applied after the hook and not inside it. A dock area
            // lays its left dock, centre and right dock out in a row; a frame
            // that is not one stacks them down the window instead, which is
            // what every renderer that is not `DockSkin` used to get, because
            // the row lived in `DockSkin`'s override of this hook and the trait
            // default is a bare `div`.
            .relative()
            .size_full()
            .overflow_hidden()
            .flex()
            .flex_row()
            .on_prepaint(move |bounds, _, cx| {
                area.update(cx, |area, _| area.bounds = bounds);
            })
            .track_focus(&self.focus_handle)
            .map(|frame| match self.zoomed_view() {
                Some(view) => frame.child(view),
                None => frame
                    .when_some(
                        self.render_dock(DockPlacement::Left, window, cx),
                        ParentElement::child,
                    )
                    .child(
                        renderer
                            .center_frame(window, cx)
                            // Same reason as the frame above: the centre is
                            // whatever the side docks leave, in a column with
                            // the bottom dock. Without this it is neither, and
                            // shrinks to its content.
                            .flex()
                            .flex_1()
                            .flex_col()
                            .overflow_hidden()
                            .child(self.render_node(self.center.root(), window, cx))
                            .when_some(
                                self.render_dock(DockPlacement::Bottom, window, cx),
                                ParentElement::child,
                            ),
                    )
                    .when_some(
                        self.render_dock(DockPlacement::Right, window, cx),
                        ParentElement::child,
                    ),
            })
    }
}

/// One container's worth of reconciliation work, snapshotted out of the tree.
enum ContainerPlan {
    Split {
        node: NodeId,
        axis: Axis,
        children: Vec<NodeId>,
        sizes: Vec<Option<Pixels>>,
    },
    Group {
        node: NodeId,
        panels: Vec<PanelId>,
        active_ix: usize,
        constraints: TabGroupConstraints,
    },
}

impl ContainerPlan {
    fn node(&self) -> NodeId {
        match self {
            Self::Split { node, .. } | Self::Group { node, .. } => *node,
        }
    }
}

/// Re-express slot sizes as shares of `container`, keeping their proportions.
///
/// Returns them unchanged unless every slot is constrained and both the
/// container and the recorded total are usable: an unconstrained slot is laid
/// out by flex and takes the leftover, so scaling only the constrained ones
/// would move a divider nothing asked to move.
fn scale_sizes_to(container: Pixels, sizes: &[Option<Pixels>]) -> Vec<Option<Pixels>> {
    let total: f32 = sizes.iter().flatten().map(|size| size.as_f32()).sum();
    if container <= px(0.) || total <= 0. || sizes.iter().any(Option::is_none) {
        return sizes.to_vec();
    }

    let scale = container.as_f32() / total;
    sizes
        .iter()
        .map(|size| size.map(|size| px(size.as_f32() * scale)))
        .collect()
}

/// Bring one split's `ResizableState` panel list from `previous` to `next`,
/// inserting and removing at the exact index rather than at the tail.
///
/// `ResizableState` treats the size handed to `insert_panel` as an initial
/// value only; from then on `panels[ix].size` is authoritative. So an
/// append-and-truncate sync leaves every survivor of a non-tail removal
/// wearing the width of whoever used to sit at its index — which is the most
/// ordinary edit in the dock, a drag that empties a group, and it is carried
/// into the save file by `resolve_sizes`.
fn sync_split_panels(
    state: &mut ResizableState,
    previous: &[NodeId],
    next: &[NodeId],
    sizes: &[Option<Pixels>],
    cx: &mut Context<ResizableState>,
) {
    let mut current = previous.to_vec();

    // Removals from the tail, so the indices ahead of each removal stay valid.
    for ix in (0..current.len()).rev() {
        if !next.contains(&current[ix]) {
            if ix < state.sizes().len() {
                state.remove_panel(ix, cx);
            }
            current.remove(ix);
        }
    }

    for (ix, node) in next.iter().enumerate() {
        if current.get(ix) == Some(node) {
            continue;
        }
        let at = ix.min(state.sizes().len());
        // Passed through as-is. The tree already decided this slot's share
        // when the panel was inserted — a drop halves the neighbour it landed
        // beside — so there is nothing to compute here, and nothing that
        // depends on a container this state may not have measured yet.
        state.insert_panel(sizes.get(ix).copied().flatten(), Some(at), cx);
        current.insert(at.min(current.len()), *node);
    }

    debug_assert_eq!(
        current, next,
        "the split's panel list must end up mirroring its children exactly; \
         a reordering edit would need its own case here"
    );
}

fn plan_tree(tree: &PaneTree, collapsed: bool, locked: bool, out: &mut Vec<ContainerPlan>) {
    // The root has nothing beside it by definition.
    plan_node(tree.root(), true, collapsed, locked, out);
}

fn plan_node(
    node: &PaneNode,
    alone: bool,
    collapsed: bool,
    locked: bool,
    out: &mut Vec<ContainerPlan>,
) {
    match node.kind() {
        PaneRef::Split {
            axis,
            children,
            sizes,
        } => {
            out.push(ContainerPlan::Split {
                node: node.id(),
                axis,
                children: children.iter().map(PaneNode::id).collect(),
                sizes: sizes.to_vec(),
            });
            let children_alone = children.len() <= 1;
            for child in children {
                plan_node(child, children_alone, collapsed, locked, out);
            }
        }
        PaneRef::Tabs { panels, active_ix } => out.push(ContainerPlan::Group {
            node: node.id(),
            panels: panels.to_vec(),
            active_ix,
            constraints: TabGroupConstraints::in_split(alone)
                .dock_locked(locked)
                .collapsed(collapsed),
        }),
    }
}

fn first_tab_group(node: &PaneNode) -> Option<NodeId> {
    match node.kind() {
        PaneRef::Tabs { .. } => Some(node.id()),
        PaneRef::Split { children, .. } => children.iter().find_map(first_tab_group),
    }
}

fn target_node(target: &InsertTarget) -> NodeId {
    match target {
        InsertTarget::Tabs { node, .. } | InsertTarget::Split { node, .. } => *node,
    }
}

/// Rebuilds panels out of persisted state through [`PanelRegistry`].
struct RegistryPanelBuilder<'a, 'w, 'c> {
    dock_area: WeakEntity<DockArea>,
    renderer: Rc<dyn DockAreaRenderer>,
    built: &'a mut Vec<(PanelId, Arc<dyn PanelView>)>,
    window: &'w mut Window,
    cx: &'c mut App,
}

impl PanelBuilder for RegistryPanelBuilder<'_, '_, '_> {
    fn build(&mut self, state: &PanelState, info: &PanelInfo) -> PanelId {
        let context = PanelBuildContext::new(self.dock_area.clone(), state, info);
        let view =
            match PanelRegistry::build_panel(&state.panel_name, context, self.window, self.cx) {
                Some(view) => view,
                None => self
                    .renderer
                    .build_placeholder(state, self.window, self.cx)
                    .unwrap_or_else(|| {
                        Arc::new(self.cx.new(|cx| PlaceholderPanel::new(state.clone(), cx)))
                            as Arc<dyn PanelView>
                    }),
            };

        let id = view.panel_id(self.cx);
        self.built.push((id, view));
        id
    }
}

/// Stands in for a panel this build cannot construct.
///
/// It draws nothing — an "unknown panel" message is presentation and belongs
/// above this seam — but it keeps the original [`PanelState`] and hands it
/// back from [`Panel::dump`], so a layout written by a newer build survives a
/// load and save here instead of losing the panel.
struct PlaceholderPanel {
    state: PanelState,
    focus_handle: FocusHandle,
}

impl PlaceholderPanel {
    fn new(state: PanelState, cx: &mut Context<Self>) -> Self {
        Self {
            state,
            focus_handle: cx.focus_handle(),
        }
    }
}

impl Panel for PlaceholderPanel {
    fn panel_name(&self) -> &'static str {
        "InvalidPanel"
    }

    fn dump(&self, _: &App) -> PanelState {
        self.state.clone()
    }
}

impl EventEmitter<PanelEvent> for PlaceholderPanel {}

impl Focusable for PlaceholderPanel {
    fn focus_handle(&self, _: &App) -> FocusHandle {
        self.focus_handle.clone()
    }
}

impl Render for PlaceholderPanel {
    fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
        Empty
    }
}

type DockToggleHandler = Rc<dyn Fn(&mut Window, &mut App)>;
type DockResizeHandler = Rc<dyn Fn(Point<Pixels>, &mut Window, &mut App)>;

/// What a skin needs to draw one dock, and the callbacks it invokes rather
/// than reimplementing the open/close and clamping behavior.
#[derive(Clone)]
pub struct DockContext {
    placement: DockPlacement,
    size: Pixels,
    open: bool,
    collapsible: bool,
    on_toggle: DockToggleHandler,
    on_resize: DockResizeHandler,
    on_resize_end: DockToggleHandler,
}

impl DockContext {
    pub fn placement(&self) -> DockPlacement {
        self.placement
    }

    /// The dock's extent along its own axis: width for left/right, height for
    /// bottom.
    pub fn size(&self) -> Pixels {
        self.size
    }

    pub fn is_open(&self) -> bool {
        self.open
    }

    pub fn is_collapsible(&self) -> bool {
        self.collapsible
    }

    pub fn toggle(&self, window: &mut Window, cx: &mut App) {
        (self.on_toggle)(window, cx);
    }

    /// Resize from a pointer position in window coordinates. Base clamps it
    /// against the area bounds and the opposite dock.
    pub fn resize_to(&self, pointer: Point<Pixels>, window: &mut Window, cx: &mut App) {
        (self.on_resize)(pointer, window, cx);
    }

    /// End a resize started with [`Self::resize_to`]. A bottom dock dragged
    /// below its minimum snaps shut or to the minimum, whichever is nearer.
    pub fn end_resize(&self, window: &mut Window, cx: &mut App) {
        (self.on_resize_end)(window, cx);
    }
}

/// A closed bottom dock keeps this much, so its tab bar stays clickable. A
/// closed side dock keeps nothing: there is no tab bar left to click at zero
/// width, and reopening it is the application's to offer.
pub const CLOSED_BOTTOM_STRIP: Pixels = px(29.);

/// How much room a dock asks for along its own axis.
pub fn dock_extent(dock: &DockContext) -> Pixels {
    match (dock.is_open(), dock.placement()) {
        (true, _) => dock.size(),
        (false, DockPlacement::Bottom) => CLOSED_BOTTOM_STRIP,
        (false, _) => px(0.),
    }
}

/// The box a dock occupies: its extent along its own axis, full across, and
/// held at that size rather than stretched by the row it sits in.
///
/// Structural, not decorative, which is why it is built here and not in a
/// renderer. See [`DockArea::render_dock`].
pub fn dock_frame(dock: &DockContext, size: Pixels) -> Div {
    div()
        .flex()
        .flex_none()
        .relative()
        .overflow_hidden()
        .map(|this| match dock.placement() {
            DockPlacement::Left | DockPlacement::Right => this.flex_row().h_full().w(size),
            DockPlacement::Bottom => this.w_full().h(size),
            // Base never builds a dock for the centre.
            DockPlacement::Center => this,
        })
}

/// Appearance for the dock area. Base draws none of it.
///
/// The frame hooks return the element itself rather than wrapping one, for the
/// same reason [`TabGroupRenderer`]'s do: base tracks focus and records the
/// area bounds on the very element the skin styles.
///
/// There is no separate `render_resize_handle` hook. A handle needs to be
/// positioned against the dock it resizes, and positioning is the skin's; the
/// skin draws it inside [`Self::render_dock`] and drives it through
/// [`DockContext::resize_to`].
#[allow(unused_variables)]
pub trait DockAreaRenderer: 'static {
    /// The area's outer frame, which base records its bounds on.
    /// Appearance only. The area is laid out as a row around whatever this
    /// returns, because that is what makes a dock a column beside the centre
    /// rather than a block above it, and a renderer cannot be expected to know
    /// it had a row to declare.
    fn frame(&self, window: &mut Window, cx: &mut App) -> Stateful<Div> {
        div().id("dock-area")
    }

    /// One split container's frame, around base's resizable group.
    ///
    /// This one really is a wrapper, unlike the other frame hooks, and
    /// deliberately: base attaches nothing to it, so there is no hit area to
    /// separate from the painted area. It exists because the old `StackPanel`
    /// carried real appearance here — a background and an overflow clip — and
    /// without it a skin could style a dock and a tab group but nothing in
    /// between. `Stateful<Div>` rather than a plain one so the skin keeps a
    /// role, a tooltip, and scroll tracking.
    fn split_frame(
        &self,
        node: NodeId,
        axis: Axis,
        window: &mut Window,
        cx: &mut App,
    ) -> Stateful<Div> {
        div().id(("dock-split-frame", node.as_u64()))
    }

    /// The column holding the center region and the bottom dock.
    /// Appearance only; see [`DockAreaRenderer::frame`]. The centre fills what
    /// the side docks leave and stacks with the bottom dock either way.
    fn center_frame(&self, window: &mut Window, cx: &mut App) -> Stateful<Div> {
        div().id("dock-area-center")
    }

    /// The painted part of the divider between two slots of a split.
    ///
    /// `None` keeps base's own one-pixel line, so a skin that has no opinion
    /// about dividers implements nothing. The hit area, the cursor and the
    /// drag itself stay with base either way — this hook supplies appearance
    /// only, and is told the axis and whether the divider is being dragged.
    fn render_split_handle(
        &self,
        handle: &ResizeHandleContext,
        window: &mut Window,
        cx: &mut App,
    ) -> Option<AnyElement> {
        None
    }

    /// One dock's chrome around its content: the title strip, the collapse
    /// affordance, and the resize handle.
    ///
    /// Chrome only. The dock's own box -- its extent along its own axis, and
    /// the `flex_none` that holds it there -- is applied by
    /// [`DockArea::render_dock`] around whatever this returns, so a renderer
    /// cannot misplace a dock by not knowing to size it, and the default here
    /// can be what it is: the content, undecorated.
    fn render_dock(
        &self,
        dock: &DockContext,
        content: AnyElement,
        window: &mut Window,
        cx: &mut App,
    ) -> AnyElement {
        content
    }

    /// The stand-in for a panel this build cannot construct — one whose
    /// `panel_name` no [`PanelRegistry`] builder answers to. `None` takes
    /// base's own placeholder, which draws nothing.
    ///
    /// The hook exists because a placeholder cannot be wrapped after the
    /// fact: presentation reaches base only through the handle a panel is
    /// registered behind, so whoever creates the panel decides what it can
    /// draw. An "unknown panel" message is presentation, so the skin creates
    /// that panel or does without one.
    ///
    /// A placeholder is what gets written back out on the next save, so one
    /// supplied here should answer [`Panel::dump`] with `state` unchanged —
    /// otherwise saving after a load erases the panel it stood in for. Base's
    /// own placeholder does; nothing here can enforce it of a skin's.
    fn build_placeholder(
        &self,
        state: &PanelState,
        window: &mut Window,
        cx: &mut App,
    ) -> Option<Arc<dyn PanelView>> {
        None
    }

    fn tab_group_renderer(&self) -> Rc<dyn TabGroupRenderer>;
}

/// The renderer an area starts with: the layout and nothing else.
struct BareDockArea;

impl DockAreaRenderer for BareDockArea {
    fn tab_group_renderer(&self) -> Rc<dyn TabGroupRenderer> {
        Rc::new(BareTabGroup)
    }
}

#[cfg(test)]
impl DockArea {
    /// Every cached container, as `(node, entity)`.
    ///
    /// Entity ids, not just node ids: node ids alone would compare equal even
    /// if every container entity had been torn down and rebuilt under the same
    /// key, which is exactly the failure the reconciliation contract exists to
    /// prevent.
    pub(crate) fn container_entity_ids(&self) -> Vec<(NodeId, gpui::EntityId)> {
        let mut ids: Vec<(NodeId, gpui::EntityId)> = self
            .groups
            .iter()
            .map(|(node, cached)| (*node, cached.entity.entity_id()))
            .chain(
                self.splits
                    .iter()
                    .map(|(node, cached)| (*node, cached.entity.entity_id())),
            )
            .collect();
        ids.sort();
        ids
    }
}

#[cfg(test)]
mod tests {
    use gpui::{TestAppContext, VisualTestContext};

    use std::{
        cell::{Cell, RefCell},
        rc::Rc,
    };

    use super::*;
    use crate::dock::TabGroupContext;
    use crate::dock::test_support::{Log, PanelSignal, TestPanel, drain, drain_active, log_of};

    /// The file holds pixels measured in whatever window last saved it, so its
    /// total is off the container the layout is restored into.
    #[test]
    fn slot_sizes_are_re_expressed_as_shares_of_the_container() {
        let scaled = scale_sizes_to(px(800.), &[Some(px(300.)), Some(px(100.))]);

        assert_eq!(scaled, vec![Some(px(600.)), Some(px(200.))]);
    }

    /// An unconstrained slot is laid out by flex and takes the leftover, so
    /// scaling only its siblings would move a divider nothing asked to move.
    #[test]
    fn an_unconstrained_slot_leaves_every_size_alone() {
        let sizes = [Some(px(300.)), None];

        assert_eq!(scale_sizes_to(px(800.), &sizes), sizes.to_vec());
    }

    /// Nothing to scale against before the first layout pass, or when the
    /// recorded sizes carry no length at all.
    #[test]
    fn an_unusable_container_or_total_leaves_every_size_alone() {
        let sizes = [Some(px(300.)), Some(px(100.))];
        assert_eq!(scale_sizes_to(px(0.), &sizes), sizes.to_vec());

        let zeroed = [Some(px(0.)), Some(px(0.))];
        assert_eq!(scale_sizes_to(px(800.), &zeroed), zeroed.to_vec());
    }

    fn setup(cx: &mut TestAppContext) -> (Entity<DockArea>, &mut VisualTestContext) {
        cx.update(|cx| {
            let _ = crate::Theme::global_mut(cx);
        });
        cx.add_window_view(|window, cx| DockArea::new("test-dock", None, window, cx))
    }

    #[gpui::test]
    fn dock_size_change_emits_one_layout_event(cx: &mut TestAppContext) {
        let (area, cx) = setup(cx);
        cx.update(|window, cx| {
            area.update(cx, |area, cx| {
                area.set_dock(
                    DockPlacement::Left,
                    DockLayout::tabs().panel(TestPanel::new("Left", cx)),
                    window,
                    cx,
                );
            });
        });

        let events = Rc::new(Cell::new(0));
        let observed = events.clone();
        let _subscription = cx.update(|window, cx| {
            window.subscribe(&area, cx, move |_, event: &DockEvent, _, _| {
                if matches!(event, DockEvent::LayoutChanged) {
                    observed.set(observed.get() + 1);
                }
            })
        });

        cx.update(|window, cx| {
            area.update(cx, |area, cx| {
                area.set_dock_size(DockPlacement::Left, px(320.), window, cx);
                area.set_dock_size(DockPlacement::Left, px(320.), window, cx);
            });
        });
        assert_eq!(
            events.get(),
            1,
            "only an effective size change is persisted"
        );
    }

    /// Two tab groups side by side, holding one logging panel each.
    fn two_groups<'a>(
        log: &Log,
        cx: &'a mut TestAppContext,
    ) -> (
        Entity<DockArea>,
        Entity<TestPanel>,
        &'a mut VisualTestContext,
    ) {
        let (area, cx) = setup(cx);
        let log = log.clone();
        let alpha = cx.update(|window, cx| {
            let alpha = TestPanel::logging("Alpha", &log, cx);
            let beta = TestPanel::logging("Beta", &log, cx);
            area.update(cx, |area, cx| {
                area.set_center(
                    DockLayout::h_split()
                        .child(DockLayout::tabs().panel(alpha.clone()), None)
                        .child(DockLayout::tabs().panel(beta), None),
                    window,
                    cx,
                );
            });
            alpha
        });
        (area, alpha, cx)
    }

    /// The id of the center split's `ix`-th child container.
    fn child_node(area: &Entity<DockArea>, ix: usize, cx: &mut VisualTestContext) -> NodeId {
        cx.read(|cx| {
            let PaneRef::Split { children, .. } = area
                .read(cx)
                .layout(DockPlacement::Center)
                .unwrap()
                .root()
                .kind()
            else {
                panic!("the center root is a split");
            };
            children[ix].id()
        })
    }

    fn panel_id_of(panel: &Entity<TestPanel>) -> PanelId {
        PanelId::from(panel.entity_id())
    }

    fn move_alpha_into_the_other_group(
        area: &Entity<DockArea>,
        alpha: &Entity<TestPanel>,
        cx: &mut VisualTestContext,
    ) {
        let target = child_node(area, 1, cx);
        let alpha_id = panel_id_of(alpha);
        cx.update(|window, cx| {
            area.update(cx, |area, cx| {
                area.move_panel(
                    alpha_id,
                    InsertTarget::Tabs {
                        node: target,
                        ix: None,
                        activate: true,
                    },
                    window,
                    cx,
                );
            });
        });
        cx.run_until_parked();
    }

    fn collect_sizes(state: &PanelState, out: &mut Vec<Pixels>) {
        if let PanelInfo::Stack { sizes, .. } = &state.info {
            out.extend(sizes.iter().copied());
        }
        for child in &state.children {
            collect_sizes(child, out);
        }
    }

    fn register_test_panels(cx: &mut App) {
        for name in ["Alpha", "Beta", "Gamma"] {
            crate::dock::registry::register_panel(cx, name, move |_, _, cx| {
                Arc::new(TestPanel::new(name, cx)) as Arc<dyn PanelView>
            });
        }
    }

    /// One tab group holding `names`, installed as the whole center.
    ///
    /// The `DockItem::tabs` the old `TabPanel` tests built is now a described
    /// layout the area reconciles, so the group entity is reached through the
    /// tree rather than handed back by the constructor.
    fn one_group<'a>(
        log: &Log,
        names: &[&'static str],
        active_ix: Option<usize>,
        cx: &'a mut TestAppContext,
    ) -> (
        Entity<DockArea>,
        Vec<Entity<TestPanel>>,
        &'a mut VisualTestContext,
    ) {
        let (area, cx) = setup(cx);
        let log = log.clone();
        let names = names.to_vec();
        let panels = cx.update(|window, cx| {
            let panels: Vec<_> = names
                .iter()
                .map(|name| TestPanel::logging(name, &log, cx))
                .collect();
            let layout = panels
                .iter()
                .fold(DockLayout::tabs(), |layout, panel| {
                    layout.panel(panel.clone())
                })
                .active_index(active_ix.unwrap_or(0));
            area.update(cx, |area, cx| area.set_center(layout, window, cx));
            panels
        });
        (area, panels, cx)
    }

    /// The live group behind the center split's `ix`-th child.
    fn group_of(
        area: &Entity<DockArea>,
        ix: usize,
        cx: &mut VisualTestContext,
    ) -> Entity<TabGroup> {
        let node = child_node(area, ix, cx);
        cx.read(|cx| area.read(cx).groups.get(&node).unwrap().entity.clone())
    }

    fn move_panel_into(
        area: &Entity<DockArea>,
        panel: PanelId,
        node: NodeId,
        ix: Option<usize>,
        activate: bool,
        cx: &mut VisualTestContext,
    ) {
        cx.update(|window, cx| {
            area.update(cx, |area, cx| {
                area.move_panel(panel, InsertTarget::Tabs { node, ix, activate }, window, cx);
            });
        });
        cx.run_until_parked();
    }

    fn is_center_empty(area: &Entity<DockArea>, cx: &mut VisualTestContext) -> bool {
        cx.read(|cx| area.read(cx).is_empty(DockPlacement::Center, cx))
    }

    #[gpui::test]
    fn a_layout_installs_and_dumps_back_to_the_same_state(cx: &mut TestAppContext) {
        let (area, cx) = setup(cx);
        cx.update(|window, cx| {
            let alpha = TestPanel::new("Alpha", cx);
            let beta = TestPanel::new("Beta", cx);
            area.update(cx, |area, cx| {
                area.set_center(
                    DockLayout::h_split()
                        .child(DockLayout::tabs().panel(alpha), Some(px(300.)))
                        .child(DockLayout::tabs().panel(beta), None),
                    window,
                    cx,
                );
            });
        });

        let state = cx.read(|cx| area.read(cx).dump(cx));
        assert_eq!(state.center.panel_name, "StackPanel");
        assert_eq!(state.center.children.len(), 2);
        assert_eq!(state.center.children[0].children[0].panel_name, "Alpha");
        assert_eq!(state.center.children[1].children[0].panel_name, "Beta");
    }

    #[gpui::test]
    fn moving_a_panel_reuses_its_entity(cx: &mut TestAppContext) {
        let log = log_of();
        let (area, alpha, cx) = two_groups(&log, cx);
        cx.run_until_parked();
        drain(&log);

        let destination = child_node(&area, 1, cx);
        let destination_entity = cx.read(|cx| {
            area.read(cx)
                .groups
                .get(&destination)
                .unwrap()
                .entity
                .entity_id()
        });

        move_alpha_into_the_other_group(&area, &alpha, cx);

        assert_eq!(
            cx.read(|cx| area
                .read(cx)
                .groups
                .get(&destination)
                .unwrap()
                .entity
                .entity_id()),
            destination_entity,
            "the group the panel arrived in was reused, not rebuilt"
        );

        // A liveness flag on the panel would not say this. The invariant is
        // that the panel is still in the tree and was never told it was
        // removed — which is exactly what `EditResult::removed_panels` encodes
        // by excluding moves.
        let alpha_id = panel_id_of(&alpha);
        assert!(
            cx.read(|cx| area
                .read(cx)
                .layout(DockPlacement::Center)
                .unwrap()
                .find_panel_node(alpha_id))
                .is_some(),
            "the moved panel is still in the tree"
        );

        let state = cx.read(|cx| area.read(cx).dump(cx));
        // One child, not two: emptying the first group removes it, and a
        // `RootKind::Split` root is never collapsed, so what is left is a
        // one-child split root.
        assert_eq!(
            state.center.children.len(),
            1,
            "the emptied group collapsed out of the split"
        );
        assert_eq!(
            state.center.children[0].children.len(),
            2,
            "both panels now share the surviving group"
        );
    }

    #[gpui::test]
    fn a_moved_panel_is_not_told_it_was_removed(cx: &mut TestAppContext) {
        let log = log_of();
        let (area, alpha, cx) = two_groups(&log, cx);
        cx.run_until_parked();
        drain(&log);

        move_alpha_into_the_other_group(&area, &alpha, cx);

        assert!(
            !drain(&log).contains(&("Alpha", PanelSignal::Removed)),
            "moving a panel between groups must never deliver on_removed"
        );
    }

    #[gpui::test]
    fn removing_a_panel_does_tell_it_it_was_removed(cx: &mut TestAppContext) {
        // Without this, `a_moved_panel_is_not_told_it_was_removed` would pass
        // just as well against a `DockArea` that never calls `on_removed` at
        // all.
        let log = log_of();
        let (area, alpha, cx) = two_groups(&log, cx);
        cx.run_until_parked();
        drain(&log);

        cx.update(|window, cx| {
            area.update(cx, |area, cx| area.remove_panel(alpha.clone(), window, cx));
        });
        cx.run_until_parked();

        assert!(
            drain(&log).contains(&("Alpha", PanelSignal::Removed)),
            "a genuine removal must deliver on_removed"
        );
    }

    #[gpui::test]
    fn reconciling_an_unchanged_tree_creates_no_entities(cx: &mut TestAppContext) {
        let log = log_of();
        let (area, _alpha, cx) = two_groups(&log, cx);
        cx.run_until_parked();
        drain(&log);

        let before = cx.read(|cx| area.read(cx).container_entity_ids());
        cx.update(|window, cx| area.update(cx, |area, cx| area.reconcile(window, cx)));
        let after = cx.read(|cx| area.read(cx).container_entity_ids());

        assert!(!before.is_empty(), "there were containers to preserve");
        assert_eq!(
            before, after,
            "a steady-state pass creates and drops nothing"
        );
        cx.run_until_parked();
        assert_eq!(
            drain(&log),
            vec![],
            "and no panel was re-added or re-activated by it"
        );
    }

    #[gpui::test]
    fn a_loaded_layout_round_trips_through_dump(cx: &mut TestAppContext) {
        let (area, cx) = setup(cx);
        cx.update(|_, cx| register_test_panels(cx));

        let json = include_str!("fixtures/nested_splits.json");
        let state: DockAreaState = serde_json::from_str(json).unwrap();

        cx.update(|window, cx| {
            area.update(cx, |area, cx| area.load(state.clone(), window, cx).unwrap())
        });
        let dumped = cx.read(|cx| area.read(cx).dump(cx));

        cx.update(|window, cx| {
            area.update(cx, |area, cx| {
                area.load(dumped.clone(), window, cx).unwrap()
            })
        });
        let again = cx.read(|cx| area.read(cx).dump(cx));

        assert_eq!(dumped, again, "load/dump must reach a fixpoint");
        assert_eq!(
            dumped.center.children.len(),
            3,
            "the fixture's nesting is flattened, as the state layer already pins"
        );
        assert_eq!(dumped.center.children[0].children[0].panel_name, "Alpha");
    }

    #[gpui::test]
    fn a_dumped_live_layout_has_no_zero_sizes(cx: &mut TestAppContext) {
        let (area, cx) = setup(cx);
        cx.update(|window, cx| {
            let alpha = TestPanel::new("Alpha", cx);
            let beta = TestPanel::new("Beta", cx);
            let gamma = TestPanel::new("Gamma", cx);
            area.update(cx, |area, cx| {
                area.set_center(
                    DockLayout::v_split()
                        // Unconstrained, which the tree stores as `None` and
                        // the writer would otherwise emit as 0.0.
                        .child(DockLayout::tabs().panel(alpha), None)
                        // Already zero. Resolving only the `None` slots would
                        // leave this one writing the same unsafe byte.
                        .child(DockLayout::tabs().panel(beta), Some(px(0.)))
                        .child(DockLayout::tabs().panel(gamma), Some(px(240.))),
                    window,
                    cx,
                );
            });
        });

        let state = cx.read(|cx| area.read(cx).dump(cx));
        let mut sizes = Vec::new();
        collect_sizes(&state.center, &mut sizes);

        assert!(!sizes.is_empty(), "the layout has slots to check");
        assert!(
            sizes.iter().all(|size| *size > px(0.)),
            "an older build reads a persisted 0.0 back as a real zero-pixel panel: {sizes:?}"
        );
    }

    /// The tree only hears about slot sizes a drag finished on: the `Resized`
    /// subscription fires from `done_resizing`, while every window resize
    /// rescales `ResizableState::sizes()` silently. So `dump` reads the
    /// measurement for a split it has on screen, and this pins that it does —
    /// preferring the tree here would persist the described `300.0` after a
    /// layout pass has already rescaled that slot to fit the window.
    #[gpui::test]
    fn a_dumped_split_writes_the_sizes_it_is_actually_drawn_at(cx: &mut TestAppContext) {
        let (area, cx) = setup(cx);
        cx.update(|window, cx| {
            let alpha = TestPanel::new("Alpha", cx);
            let beta = TestPanel::new("Beta", cx);
            area.update(cx, |area, cx| {
                area.set_center(
                    DockLayout::h_split()
                        .child(DockLayout::tabs().panel(alpha), Some(px(300.)))
                        .child(DockLayout::tabs().panel(beta), Some(px(300.))),
                    window,
                    cx,
                );
            });
        });
        cx.run_until_parked();

        let root = cx.read(|cx| {
            area.read(cx)
                .layout(DockPlacement::Center)
                .unwrap()
                .root()
                .id()
        });
        let measured = cx.read(|cx| area.read(cx).splits[&root].entity.read(cx).sizes().clone());
        assert_ne!(
            measured,
            vec![px(300.), px(300.)],
            "the split has to have been rescaled by a layout pass, or this \
             test cannot tell the two preferences apart"
        );

        let state = cx.read(|cx| area.read(cx).dump(cx));
        let PanelInfo::Stack { sizes, .. } = &state.center.info else {
            panic!("the center writes a stack");
        };
        assert_eq!(
            sizes, &measured,
            "the written sizes are the ones on screen, not the ones the tree \
             was built from"
        );
    }

    #[gpui::test]
    fn set_split_sizes_restores_a_share_and_reports_it(cx: &mut TestAppContext) {
        let (area, cx) = setup(cx);
        cx.update(|window, cx| {
            let alpha = TestPanel::new("Alpha", cx);
            let beta = TestPanel::new("Beta", cx);
            area.update(cx, |area, cx| {
                area.set_center(
                    DockLayout::h_split()
                        .child(DockLayout::tabs().panel(alpha), Some(px(300.)))
                        .child(DockLayout::tabs().panel(beta), Some(px(300.))),
                    window,
                    cx,
                );
            });
        });
        cx.run_until_parked();

        let root = cx.read(|cx| {
            area.read(cx)
                .layout(DockPlacement::Center)
                .unwrap()
                .root()
                .id()
        });
        let events = Rc::new(Cell::new(0));
        let observed = events.clone();
        let _subscription = cx.update(|window, cx| {
            window.subscribe(&area, cx, move |_, event: &DockEvent, _, _| {
                if matches!(event, DockEvent::LayoutChanged) {
                    observed.set(observed.get() + 1);
                }
            })
        });

        cx.update(|window, cx| {
            area.update(cx, |area, cx| {
                area.set_split_sizes(root, vec![px(100.), px(300.)], window, cx);
            });
        });
        cx.run_until_parked();
        assert_eq!(events.get(), 1);
        let measured = cx.read(|cx| area.read(cx).splits[&root].entity.read(cx).sizes().clone());
        let share = measured[0].as_f32() / (measured[0].as_f32() + measured[1].as_f32());
        assert!((share - 0.25).abs() < 0.01, "measured {measured:?}");

        cx.update(|window, cx| {
            area.update(cx, |area, cx| {
                area.set_split_sizes(root, vec![px(10.)], window, cx);
            });
        });
        cx.run_until_parked();
        assert_eq!(events.get(), 1);
        let after = cx.read(|cx| area.read(cx).splits[&root].entity.read(cx).sizes().clone());
        assert_eq!(after, measured);
    }

    /// A drop that splits carries no size — `TabGroup` builds
    /// `InsertTarget::Split { size: None }` — so the split has to decide one,
    /// and sharing the container equally is the decision. Passing the `None`
    /// straight to `ResizableState` instead makes the new slot the flexible
    /// one among fixed siblings, and it stops looking like a half.
    #[gpui::test]
    fn a_panel_dropped_beside_another_takes_half_the_split(cx: &mut TestAppContext) {
        let log = Log::default();
        let (area, panels, cx) = one_group(&log, &["Alpha", "Beta"], None, cx);
        let group = child_node(&area, 0, cx);
        let beta = panel_id_of(&panels[1]);

        cx.update(|window, cx| {
            area.update(cx, |area, cx| {
                area.move_panel(
                    beta,
                    InsertTarget::Split {
                        node: group,
                        placement: Placement::Right,
                        size: None,
                    },
                    window,
                    cx,
                );
            });
        });
        cx.run_until_parked();

        let root = cx.read(|cx| {
            area.read(cx)
                .layout(DockPlacement::Center)
                .unwrap()
                .root()
                .id()
        });
        let sizes = cx.read(|cx| area.read(cx).splits[&root].entity.read(cx).sizes().clone());

        assert_eq!(sizes.len(), 2, "the drop splits the center in two");
        let (left, right) = (sizes[0].as_f32(), sizes[1].as_f32());
        assert!(
            (left - right).abs() <= (left + right) * 0.02,
            "the two halves must be within 2% of each other, got {left} and {right}"
        );
    }

    /// Moving a panel this area does not own is a no-op, not a ghost insert.
    #[gpui::test]
    fn a_move_of_an_unowned_panel_is_ignored(cx: &mut TestAppContext) {
        let log = Log::default();
        let (area, _panels, cx) = one_group(&log, &["Alpha", "Beta"], None, cx);
        let group = child_node(&area, 0, cx);
        let before = cx.read(|cx| area.read(cx).dump(cx));

        // A PanelId from nowhere, as if dropped from another DockArea.
        move_panel_into(&area, PanelId::from_u64(9_999_999), group, None, true, cx);

        let after = cx.read(|cx| area.read(cx).dump(cx));
        assert_eq!(
            before, after,
            "an unowned panel move must not touch the tree"
        );
    }

    /// The other drop geometry: a placement whose axis differs from the
    /// parent's wraps the target in a fresh split, so the sizes are decided
    /// by a `ResizableState` that has never been measured.
    #[gpui::test]
    fn a_panel_dropped_across_the_axis_still_takes_half(cx: &mut TestAppContext) {
        let log = Log::default();
        let (area, panels, cx) = one_group(&log, &["Alpha", "Beta"], None, cx);
        let group = child_node(&area, 0, cx);
        let beta = panel_id_of(&panels[1]);

        cx.update(|window, cx| {
            area.update(cx, |area, cx| {
                area.move_panel(
                    beta,
                    InsertTarget::Split {
                        node: group,
                        placement: Placement::Bottom,
                        size: None,
                    },
                    window,
                    cx,
                );
            });
        });
        cx.run_until_parked();

        // Dropping across the axis wraps the target in a new split, which
        // becomes the center root's only child — the root itself still holds
        // one slot.
        let wrapper = child_node(&area, 0, cx);
        let sizes = cx.read(|cx| {
            area.read(cx).splits[&wrapper]
                .entity
                .read(cx)
                .sizes()
                .clone()
        });
        assert_eq!(sizes.len(), 2, "the drop splits the group in two");
        let (top, bottom) = (sizes[0].as_f32(), sizes[1].as_f32());
        assert!(
            (top - bottom).abs() <= (top + bottom) * 0.02,
            "the two halves must be within 2% of each other, got {top} and {bottom}"
        );
    }

    /// A drop into a split that already holds more than one slot, which is the
    /// shape a real workspace is in by the time anyone drags anything.
    #[gpui::test]
    fn a_panel_dropped_into_a_populated_split_takes_an_even_share(cx: &mut TestAppContext) {
        let (area, cx) = setup(cx);
        let panels = cx.update(|window, cx| {
            let alpha = TestPanel::new("Alpha", cx);
            let beta = TestPanel::new("Beta", cx);
            let gamma = TestPanel::new("Gamma", cx);
            area.update(cx, |area, cx| {
                area.set_center(
                    DockLayout::h_split()
                        .child(DockLayout::tabs().panel(alpha.clone()), Some(px(240.)))
                        .child(
                            DockLayout::tabs().panel(beta.clone()).panel(gamma.clone()),
                            None,
                        ),
                    window,
                    cx,
                );
            });
            vec![alpha, beta, gamma]
        });
        cx.run_until_parked();

        let right = child_node(&area, 1, cx);
        let gamma = panel_id_of(&panels[2]);
        cx.update(|window, cx| {
            area.update(cx, |area, cx| {
                area.move_panel(
                    gamma,
                    InsertTarget::Split {
                        node: right,
                        placement: Placement::Right,
                        size: None,
                    },
                    window,
                    cx,
                );
            });
        });
        cx.run_until_parked();

        let root = cx.read(|cx| {
            area.read(cx)
                .layout(DockPlacement::Center)
                .unwrap()
                .root()
                .id()
        });
        let sizes = cx.read(|cx| area.read(cx).splits[&root].entity.read(cx).sizes().clone());
        assert_eq!(sizes.len(), 3, "three slots side by side");
        let dropped = sizes[2].as_f32();
        let neighbour = sizes[1].as_f32();
        assert!(
            (dropped - neighbour).abs() <= (dropped + neighbour) * 0.02,
            "the dropped panel splits its neighbour evenly, got neighbour {neighbour} and dropped {dropped}"
        );
    }

    /// A dock's root is usually a bare tab group, so a drop beside it takes
    /// the "wrap the target in a new split" path rather than the "insert into
    /// the existing split" one — and that split has never been measured.
    #[gpui::test]
    fn a_panel_dropped_beside_a_dock_takes_half(cx: &mut TestAppContext) {
        for placement in [DockPlacement::Bottom, DockPlacement::Left] {
            let (area, cx) = setup(cx);
            let dropped = cx.update(|window, cx| {
                let resident = TestPanel::new("Resident", cx);
                let dropped = TestPanel::new("Dropped", cx);
                area.update(cx, |area, cx| {
                    area.set_center(
                        DockLayout::tabs().panel(TestPanel::new("Center", cx)),
                        window,
                        cx,
                    );
                    area.set_dock(
                        placement,
                        DockLayout::tabs().panel(resident).panel(dropped.clone()),
                        window,
                        cx,
                    );
                    area.set_dock_size(placement, px(400.), window, cx);
                });
                dropped
            });
            cx.run_until_parked();

            let group = cx.read(|cx| {
                area.read(cx)
                    .layout(placement)
                    .unwrap()
                    .find_panel_node(panel_id_of(&dropped))
                    .expect("both panels start in the dock's only group")
            });

            cx.update(|window, cx| {
                area.update(cx, |area, cx| {
                    area.move_panel(
                        panel_id_of(&dropped),
                        InsertTarget::Split {
                            node: group,
                            placement: Placement::Bottom,
                            size: None,
                        },
                        window,
                        cx,
                    );
                });
            });
            cx.run_until_parked();

            let split = cx.read(|cx| {
                let tree = area.read(cx).layout(placement).unwrap();
                let root = tree.root();
                match root.kind() {
                    PaneRef::Split { .. } => root.id(),
                    _ => panic!("the drop must have produced a split"),
                }
            });
            let sizes = cx.read(|cx| area.read(cx).splits[&split].entity.read(cx).sizes().clone());

            assert_eq!(sizes.len(), 2, "{placement:?}: the drop splits in two");
            let (first, second) = (sizes[0].as_f32(), sizes[1].as_f32());
            assert!(
                (first - second).abs() <= (first + second) * 0.02,
                "{placement:?}: expected halves, got {first} and {second}"
            );
        }
    }

    /// A slot given an explicit size keeps it on the frame after the first.
    ///
    /// The layout is laid out once with a flexible sibling, and the flexible
    /// slot's placeholder measurement used to drag the fixed one with it when
    /// the container was first measured — the layout visibly jumped once,
    /// then settled.
    #[gpui::test]
    fn an_explicit_slot_size_survives_the_first_layout_pass(cx: &mut TestAppContext) {
        let (area, cx) = setup(cx);
        cx.update(|window, cx| {
            let sidebar = TestPanel::new("Sidebar", cx);
            let content = TestPanel::new("Content", cx);
            area.update(cx, |area, cx| {
                area.set_center(
                    DockLayout::h_split()
                        .child(DockLayout::tabs().panel(sidebar), Some(px(200.)))
                        .child(DockLayout::tabs().panel(content), None),
                    window,
                    cx,
                );
            });
        });
        cx.run_until_parked();

        let root = cx.read(|cx| {
            area.read(cx)
                .layout(DockPlacement::Center)
                .unwrap()
                .root()
                .id()
        });
        let sizes = cx.read(|cx| area.read(cx).splits[&root].entity.read(cx).sizes().clone());

        // Within a couple of pixels of what was asked for — the measured
        // value carries the frame's own rounding. The bug this pins made it
        // 587px.
        let fixed = sizes
            .first()
            .copied()
            .expect("the split has slots")
            .as_f32();
        assert!(
            (fixed - 200.).abs() <= 4.,
            "the fixed slot keeps its 200px instead of being rescaled by the \
             flexible sibling's placeholder, got {fixed}"
        );
    }

    /// A panel that draws a measurable box, so a test can read where a slot
    /// actually landed rather than what `ResizableState` believes about it.
    struct MeasuredPanel {
        name: &'static str,
        focus_handle: FocusHandle,
    }

    impl MeasuredPanel {
        fn new(name: &'static str, cx: &mut App) -> Entity<Self> {
            cx.new(|cx| Self {
                name,
                focus_handle: cx.focus_handle(),
            })
        }
    }

    impl Panel for MeasuredPanel {
        fn panel_name(&self) -> &'static str {
            self.name
        }
    }

    impl EventEmitter<PanelEvent> for MeasuredPanel {}

    impl Focusable for MeasuredPanel {
        fn focus_handle(&self, _: &App) -> FocusHandle {
            self.focus_handle.clone()
        }
    }

    impl Render for MeasuredPanel {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            let name = self.name;
            div().size_full().debug_selector(move || name.into())
        }
    }

    fn draw_frames(cx: &mut VisualTestContext, frames: usize) {
        for _ in 0..frames {
            cx.update(|window, cx| window.draw(cx).clear(cx));
        }
    }

    /// Switching a tab edits one group, yet `commit` reconciles every
    /// container. Reconciling a split the edit did not touch re-adopted the
    /// tree's `None` for its flexible slot, un-pinning the size the first
    /// layout pass had measured for it, so the split re-flexed from scratch
    /// and its sized neighbour shrank. This is the dock example's left column
    /// getting shorter on every tab click in the bottom dock.
    #[gpui::test]
    fn switching_a_tab_leaves_an_untouched_split_where_it_was_drawn(cx: &mut TestAppContext) {
        let (area, cx) = setup(cx);
        cx.update(|window, cx| {
            area.update(cx, |area, cx| {
                area.set_center(
                    DockLayout::tabs().panel(TestPanel::new("Center", cx)),
                    window,
                    cx,
                );
                area.set_dock(
                    DockPlacement::Left,
                    DockLayout::v_split()
                        .child(
                            DockLayout::tabs().panel(MeasuredPanel::new("upper-left", cx)),
                            None,
                        )
                        .child(
                            DockLayout::tabs().panel(MeasuredPanel::new("lower-left", cx)),
                            Some(px(360.)),
                        ),
                    window,
                    cx,
                );
                area.set_dock_size(DockPlacement::Left, px(350.), window, cx);
                area.set_dock(
                    DockPlacement::Bottom,
                    DockLayout::tabs()
                        .panel(TestPanel::new("Tooltip", cx))
                        .panel(TestPanel::new("Icon", cx)),
                    window,
                    cx,
                );
                area.set_dock_size(DockPlacement::Bottom, px(200.), window, cx);
            });
        });
        cx.run_until_parked();
        draw_frames(cx, 3);
        let before = (
            cx.debug_bounds("upper-left").unwrap(),
            cx.debug_bounds("lower-left").unwrap(),
        );

        let bottom = cx.read(|cx| {
            area.read(cx)
                .layout(DockPlacement::Bottom)
                .unwrap()
                .root()
                .id()
        });
        let group = cx.read(|cx| area.read(cx).groups[&bottom].entity.clone());
        cx.update(|window, cx| {
            group.update(cx, |group, cx| group.select_tab(1, window, cx));
        });
        cx.run_until_parked();
        draw_frames(cx, 3);
        let after = (
            cx.debug_bounds("upper-left").unwrap(),
            cx.debug_bounds("lower-left").unwrap(),
        );

        assert_eq!(
            before, after,
            "a tab change in the bottom dock must not move the left split"
        );
    }

    /// The other way a reconcile could move an untouched split: its file holds
    /// pixels measured in some other window, the first layout pass rescaled
    /// the state to the container it actually has, and handing the file's
    /// pixels back on a tab change slides the divider to a third position.
    #[gpui::test]
    fn switching_a_tab_keeps_a_restored_split_at_its_rescaled_share(cx: &mut TestAppContext) {
        let (area, cx) = setup(cx);
        cx.update(|window, cx| {
            area.update(cx, |area, cx| {
                area.set_center(
                    DockLayout::h_split()
                        .child(
                            DockLayout::tabs()
                                .panel(TestPanel::new("Alpha", cx))
                                .panel(TestPanel::new("Beta", cx)),
                            Some(px(620.)),
                        )
                        .child(
                            DockLayout::tabs().panel(MeasuredPanel::new("second", cx)),
                            Some(px(350.)),
                        ),
                    window,
                    cx,
                );
            });
        });
        cx.run_until_parked();
        draw_frames(cx, 3);
        // The second slot's box tells where the divider is: its left edge is
        // the first slot's width, and the two add up to the container.
        let before = cx.debug_bounds("second").unwrap();
        assert_ne!(
            before.right(),
            px(970.),
            "the window must not match the recorded total, or this test cannot \
             tell a rescaled split from the file's pixels"
        );

        let group = group_of(&area, 0, cx);
        cx.update(|window, cx| {
            group.update(cx, |group, cx| group.select_tab(1, window, cx));
        });
        cx.run_until_parked();
        draw_frames(cx, 3);
        let after = cx.debug_bounds("second").unwrap();

        assert_eq!(
            before, after,
            "a tab change must not hand the file's pixels back to the split"
        );
    }

    /// The headline claim of the whole extraction, in one place: a layout
    /// written by the shipped dock loads into the tree world, draws, and saves
    /// back to a state the next load reproduces exactly.
    ///
    /// The fixture is a real user's file — a two-group center plus all three
    /// docks — and its panels are not registered here, so every leaf takes the
    /// placeholder path that carries the original `PanelState` forward. That
    /// is the load-bearing half: a build that dropped an unknown panel would
    /// still reach a fixpoint, so the region assertions below check the
    /// content is *there* before the fixpoint says it is stable.
    #[gpui::test]
    fn the_shipped_fixture_survives_a_load_dump_load_round_trip(cx: &mut TestAppContext) {
        let (area, cx) = setup(cx);
        let fixture: DockAreaState =
            serde_json::from_str(include_str!("fixtures/layout.json")).unwrap();

        cx.update(|window, cx| area.update(cx, |area, cx| area.load(fixture, window, cx).unwrap()));
        cx.run_until_parked();
        let first = cx.read(|cx| area.read(cx).dump(cx));

        assert_eq!(first.center.children.len(), 2, "the center's two groups");
        assert_eq!(first.center.children[0].children.len(), 15);
        assert_eq!(first.center.children[1].children.len(), 1);
        for dock in [&first.left_dock, &first.bottom_dock, &first.right_dock] {
            let dock = dock.as_ref().expect("all three docks are attached");
            assert!(dock.open());
            assert!(
                !dock.panel().children.is_empty(),
                "a dock that loaded empty would round-trip just as stably"
            );
        }
        assert_eq!(first.left_dock.as_ref().unwrap().size(), px(350.));
        assert_eq!(first.bottom_dock.as_ref().unwrap().size(), px(200.));
        assert_eq!(first.right_dock.as_ref().unwrap().size(), px(320.));

        cx.update(|window, cx| {
            area.update(cx, |area, cx| area.load(first.clone(), window, cx).unwrap())
        });
        cx.run_until_parked();
        let second = cx.read(|cx| area.read(cx).dump(cx));

        assert_eq!(second, first, "dump == dump(load(dump))");
    }

    #[gpui::test]
    fn an_unregistered_panel_survives_a_load_and_save_round_trip(cx: &mut TestAppContext) {
        let (area, cx) = setup(cx);
        cx.update(|_, cx| register_test_panels(cx));

        let json = include_str!("fixtures/unregistered_panel.json");
        let state: DockAreaState = serde_json::from_str(json).unwrap();

        cx.update(|window, cx| area.update(cx, |area, cx| area.load(state, window, cx).unwrap()));
        let dumped = cx.read(|cx| area.read(cx).dump(cx));

        let leaf = &dumped.center.children[0].children[0];
        assert_eq!(leaf.panel_name, "PanelFromTheFuture");
        assert_eq!(
            leaf.info,
            PanelInfo::panel(serde_json::json!({"keep": "me"})),
            "a panel this build cannot construct keeps its payload"
        );
    }

    #[gpui::test]
    fn a_dock_carries_its_own_tree_and_survives_a_round_trip(cx: &mut TestAppContext) {
        let (area, cx) = setup(cx);
        cx.update(|window, cx| {
            let alpha = TestPanel::new("Alpha", cx);
            let beta = TestPanel::new("Beta", cx);
            area.update(cx, |area, cx| {
                area.set_center(DockLayout::tabs().panel(alpha), window, cx);
                area.set_dock(
                    DockPlacement::Left,
                    DockLayout::tabs().panel(beta),
                    window,
                    cx,
                );
            });
        });

        // Node ids are globally allocated, so the center and the dock never
        // claim the same entity-cache slot.
        //
        // Comparing the two *roots* would not pin this: under a per-tree
        // counter the center's root is minted after its tab group and the
        // dock's is not, so the roots differ anyway. The collision is between
        // the two trees' tab-group nodes, and the property the cache actually
        // depends on is that no id is shared at all.
        let center_ids = cx.read(|cx| {
            area.read(cx)
                .layout(DockPlacement::Center)
                .unwrap()
                .node_ids()
        });
        let dock_ids = cx.read(|cx| {
            area.read(cx)
                .layout(DockPlacement::Left)
                .unwrap()
                .node_ids()
        });
        assert!(!center_ids.is_empty() && !dock_ids.is_empty());
        assert!(
            center_ids.iter().all(|id| !dock_ids.contains(id)),
            "every tree in one area must draw from one id space: \
             center {center_ids:?} vs left {dock_ids:?}"
        );

        let state = cx.read(|cx| area.read(cx).dump(cx));
        let left = state.left_dock.clone().expect("the left dock is written");
        assert_eq!(left.placement(), DockPlacement::Left);
        assert!(left.open());
        assert_eq!(left.panel().children[0].panel_name, "Beta");
        assert!(state.right_dock.is_none());
    }

    #[gpui::test]
    fn a_panel_moved_between_regions_keeps_its_active_state(cx: &mut TestAppContext) {
        let log = log_of();
        let (area, alpha, cx) = two_groups(&log, cx);
        cx.run_until_parked();
        // Alpha is the displayed tab of its own group, so it has been told
        // `true` exactly once.
        assert!(drain(&log).contains(&("Alpha", PanelSignal::Active(true))));

        move_alpha_into_the_other_group(&area, &alpha, cx);

        assert!(
            !drain(&log).contains(&("Alpha", PanelSignal::Active(true))),
            "a displayed panel dragged to another group must not be told `true` twice"
        );
    }

    #[gpui::test]
    fn a_groups_close_intent_reaches_the_tree(cx: &mut TestAppContext) {
        // Nothing else here proves `DockArea` subscribes to `TabGroupEvent`
        // at all: a group reports intents and does nothing itself, so an
        // unsubscribed area is a dock region that silently does nothing.
        let log = log_of();
        let (area, alpha, cx) = two_groups(&log, cx);
        cx.run_until_parked();
        drain(&log);

        let node = child_node(&area, 0, cx);
        let alpha_id = panel_id_of(&alpha);
        cx.update(|_, cx| {
            let group = area.read(cx).groups.get(&node).unwrap().entity.clone();
            group.update(cx, |group, cx| group.close_panel(alpha_id, cx));
        });
        cx.run_until_parked();

        assert!(
            cx.read(|cx| area
                .read(cx)
                .layout(DockPlacement::Center)
                .unwrap()
                .find_panel_node(alpha_id))
                .is_none(),
            "the close intent was applied to the tree"
        );
        assert!(drain(&log).contains(&("Alpha", PanelSignal::Removed)));
    }

    #[gpui::test]
    fn replacing_the_center_tells_the_panels_that_left(cx: &mut TestAppContext) {
        let log = log_of();
        let (area, _alpha, cx) = two_groups(&log, cx);
        cx.run_until_parked();
        drain(&log);

        cx.update(|window, cx| {
            let gamma = TestPanel::new("Gamma", cx);
            area.update(cx, |area, cx| {
                area.set_center(DockLayout::tabs().panel(gamma), window, cx)
            });
        });
        cx.run_until_parked();

        let seen = drain(&log);
        assert!(seen.contains(&("Alpha", PanelSignal::Removed)));
        assert!(seen.contains(&("Beta", PanelSignal::Removed)));
    }

    #[gpui::test]
    fn closing_a_zoomed_panel_clears_the_zoom(cx: &mut TestAppContext) {
        let log = log_of();
        let (area, alpha, cx) = two_groups(&log, cx);
        cx.run_until_parked();

        let node = child_node(&area, 0, cx);
        cx.update(|window, cx| area.update(cx, |area, cx| area.set_zoomed_in(node, window, cx)));
        assert!(cx.read(|cx| area.read(cx).is_zoomed()));

        cx.update(|window, cx| {
            area.update(cx, |area, cx| area.remove_panel(alpha.clone(), window, cx))
        });

        assert!(
            !cx.read(|cx| area.read(cx).is_zoomed()),
            "a zoomed panel that left the dock must not keep filling it"
        );
    }

    /// The skin's stand-in for a panel this build cannot construct. It keeps
    /// the original state, which is the obligation
    /// [`DockAreaRenderer::build_placeholder`] documents.
    struct SkinPlaceholder {
        state: PanelState,
        focus_handle: FocusHandle,
    }

    impl Panel for SkinPlaceholder {
        fn panel_name(&self) -> &'static str {
            "SkinPlaceholder"
        }

        fn dump(&self, _: &App) -> PanelState {
            self.state.clone()
        }
    }

    impl EventEmitter<PanelEvent> for SkinPlaceholder {}

    impl Focusable for SkinPlaceholder {
        fn focus_handle(&self, _: &App) -> FocusHandle {
            self.focus_handle.clone()
        }
    }

    impl Render for SkinPlaceholder {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            Empty
        }
    }

    struct PlaceholderSkin {
        asked: Rc<std::cell::RefCell<Vec<String>>>,
    }

    impl DockAreaRenderer for PlaceholderSkin {
        fn build_placeholder(
            &self,
            state: &PanelState,
            _: &mut Window,
            cx: &mut App,
        ) -> Option<Arc<dyn PanelView>> {
            self.asked.borrow_mut().push(state.panel_name.clone());
            let state = state.clone();
            Some(Arc::new(cx.new(|cx| SkinPlaceholder {
                state,
                focus_handle: cx.focus_handle(),
            })))
        }

        fn tab_group_renderer(&self) -> Rc<dyn TabGroupRenderer> {
            Rc::new(BareTabGroup)
        }
    }

    /// A panel no builder answers for becomes the skin's placeholder rather
    /// than base's draw-nothing one, so the "unknown panel" message the old
    /// `InvalidPanel` drew has somewhere to live.
    #[gpui::test]
    fn an_unbuildable_panel_becomes_the_skins_placeholder(cx: &mut TestAppContext) {
        cx.update(|cx| {
            let _ = crate::Theme::global_mut(cx);
        });
        let asked: Rc<std::cell::RefCell<Vec<String>>> = Rc::default();
        let skin = Rc::new(PlaceholderSkin {
            asked: asked.clone(),
        });
        let (area, cx) = cx.add_window_view(|window, cx| {
            DockArea::new("test-dock", None, window, cx).with_renderer(skin)
        });

        // Nothing is registered, so the round trip cannot rebuild this panel.
        cx.update(|window, cx| {
            let ghost = TestPanel::new("Ghost", cx);
            area.update(cx, |area, cx| {
                area.set_center(DockLayout::tabs().panel(ghost), window, cx)
            });
        });
        let state = cx.read(|cx| area.read(cx).dump(cx));
        cx.update(|window, cx| area.update(cx, |area, cx| area.load(state, window, cx).unwrap()));
        cx.run_until_parked();

        assert_eq!(*asked.borrow(), vec!["Ghost".to_string()]);
        assert_eq!(
            cx.read(|cx| area
                .read(cx)
                .panels
                .values()
                .map(|panel| panel.panel_name(cx))
                .collect::<Vec<_>>()),
            vec!["SkinPlaceholder"],
            "base installed the skin's placeholder, not its own"
        );
        assert_eq!(
            cx.read(|cx| area.read(cx).dump(cx)).center.children[0].children[0].panel_name,
            "Ghost",
            "and the unknown panel still survives the next save"
        );
    }

    #[gpui::test]
    fn removing_a_non_tail_child_shifts_the_split_sizes_with_it(cx: &mut TestAppContext) {
        // `ResizableState` keeps the authoritative size on `panels[ix]`, so a
        // tail-truncating sync leaves the survivors of a non-tail removal
        // wearing their predecessors' widths.
        let log = log_of();
        let (area, cx) = setup(cx);
        let alpha = cx.update(|window, cx| {
            let alpha = TestPanel::logging("Alpha", &log, cx);
            let beta = TestPanel::logging("Beta", &log, cx);
            let gamma = TestPanel::logging("Gamma", &log, cx);
            area.update(cx, |area, cx| {
                area.set_center(
                    DockLayout::h_split()
                        .child(DockLayout::tabs().panel(alpha.clone()), Some(px(100.)))
                        .child(DockLayout::tabs().panel(beta), Some(px(200.)))
                        .child(DockLayout::tabs().panel(gamma), Some(px(300.))),
                    window,
                    cx,
                );
            });
            alpha
        });

        let root = cx.read(|cx| {
            area.read(cx)
                .layout(DockPlacement::Center)
                .unwrap()
                .root()
                .id()
        });
        let split = cx.read(|cx| area.read(cx).splits.get(&root).unwrap().entity.clone());
        let sizes = |cx: &mut VisualTestContext| cx.read(|cx| split.read(cx).sizes().clone());

        // Absolute widths are `ResizableState`'s business — it redistributes
        // against the measured container — so what is asserted is which slot
        // disappeared, through the ratio the survivors keep.
        let before = sizes(cx);
        assert_eq!(before.len(), 3);
        let kept_if_correct = before[1] / before[2];
        let kept_if_truncated = before[0] / before[1];
        assert!(
            (kept_if_correct - kept_if_truncated).abs() > 0.1,
            "the fixture must be able to tell the two outcomes apart"
        );

        cx.update(|window, cx| area.update(cx, |area, cx| area.remove_panel(alpha, window, cx)));

        let after = sizes(cx);
        assert_eq!(after.len(), 2);
        assert!(
            (after[0] / after[1] - kept_if_correct).abs() < 0.01,
            "the survivors kept their own proportions: slot 0 was removed, not \
             the tail — got {after:?} from {before:?}"
        );
    }

    #[gpui::test]
    fn a_panel_moves_between_the_center_and_a_dock(cx: &mut TestAppContext) {
        let log = log_of();
        let (area, alpha, cx) = two_groups(&log, cx);
        cx.update(|window, cx| {
            let gamma = TestPanel::logging("Gamma", &log, cx);
            area.update(cx, |area, cx| {
                area.set_dock(
                    DockPlacement::Left,
                    DockLayout::tabs().panel(gamma),
                    window,
                    cx,
                );
            });
        });
        cx.run_until_parked();
        drain(&log);

        let alpha_id = panel_id_of(&alpha);
        let dock_group = cx.read(|cx| {
            area.read(cx)
                .layout(DockPlacement::Left)
                .unwrap()
                .root()
                .id()
        });

        cx.update(|window, cx| {
            area.update(cx, |area, cx| {
                area.move_panel(
                    alpha_id,
                    InsertTarget::Tabs {
                        node: dock_group,
                        ix: None,
                        activate: true,
                    },
                    window,
                    cx,
                );
            });
        });
        cx.run_until_parked();

        assert!(
            cx.read(|cx| area
                .read(cx)
                .layout(DockPlacement::Center)
                .unwrap()
                .find_panel_node(alpha_id))
                .is_none(),
            "the panel left the center"
        );
        assert_eq!(
            cx.read(|cx| area
                .read(cx)
                .layout(DockPlacement::Left)
                .unwrap()
                .find_panel_node(alpha_id)),
            Some(dock_group),
            "and arrived in the dock's group"
        );

        let seen = drain(&log);
        assert!(
            !seen.contains(&("Alpha", PanelSignal::Removed)),
            "crossing regions is still a move, not a removal"
        );
        assert!(
            !seen.contains(&("Alpha", PanelSignal::Active(true))),
            "and it was displayed in both, so it is not told `true` twice"
        );
    }

    #[gpui::test]
    fn a_move_onto_an_unusable_target_leaves_no_stranded_panel(cx: &mut TestAppContext) {
        // `apply_insert` is a silent no-op when the target node's kind does
        // not match. Committing on the insert alone would early-return with
        // the panel already gone from the source tree but still in the view
        // map, for some later unrelated edit to prune and destroy.
        let log = log_of();
        let (area, _alpha, cx) = two_groups(&log, cx);
        let gamma = cx.update(|window, cx| {
            let gamma = TestPanel::logging("Gamma", &log, cx);
            area.update(cx, |area, cx| {
                area.set_dock(
                    DockPlacement::Left,
                    DockLayout::tabs().panel(gamma.clone()),
                    window,
                    cx,
                );
            });
            gamma
        });
        cx.run_until_parked();
        drain(&log);

        let gamma_id = panel_id_of(&gamma);
        // The center root is a split, so a `Tabs` insert naming it does
        // nothing at all.
        let center_root = cx.read(|cx| {
            area.read(cx)
                .layout(DockPlacement::Center)
                .unwrap()
                .root()
                .id()
        });

        cx.update(|window, cx| {
            area.update(cx, |area, cx| {
                area.move_panel(
                    gamma_id,
                    InsertTarget::Tabs {
                        node: center_root,
                        ix: None,
                        activate: true,
                    },
                    window,
                    cx,
                );
            });
        });
        cx.run_until_parked();

        assert!(
            cx.read(|cx| area.read(cx).panel(gamma_id).is_none()),
            "the view map agrees with the trees straight away, rather than \
             carrying a panel that belongs to no tree"
        );
        assert!(
            drain(&log).contains(&("Gamma", PanelSignal::Removed)),
            "and the panel was told so at the point of the call"
        );
    }

    #[gpui::test]
    fn an_all_hidden_container_reports_itself_invisible(cx: &mut TestAppContext) {
        // What the old `StackPanel::render` asked of each slot before hiding
        // it. `render_node` feeds this straight to `resizable_panel().visible`.
        let (area, cx) = setup(cx);
        let beta = cx.update(|window, cx| {
            let alpha = TestPanel::new("Alpha", cx);
            let beta = TestPanel::new("Beta", cx);
            area.update(cx, |area, cx| {
                area.set_center(
                    DockLayout::h_split()
                        .child(DockLayout::tabs().panel(alpha), None)
                        .child(DockLayout::tabs().panel(beta.clone()), None),
                    window,
                    cx,
                );
            });
            beta
        });

        let visible = |ix: usize, cx: &mut VisualTestContext| {
            let node = child_node(&area, ix, cx);
            cx.read(|cx| {
                let area = area.read(cx);
                let tree = area.layout(DockPlacement::Center).unwrap();
                area.is_node_visible(tree.find_node(node).unwrap(), cx)
            })
        };

        assert!(visible(0, cx) && visible(1, cx));

        cx.update(|_, cx| beta.update(cx, |beta, cx| beta.set_visible(false, cx)));

        assert!(visible(0, cx), "the visible group still holds its slot");
        assert!(
            !visible(1, cx),
            "a group whose every panel is hidden must give its slot up"
        );
    }

    #[gpui::test]
    fn a_locked_area_seals_its_groups(cx: &mut TestAppContext) {
        let log = log_of();
        let (area, _alpha, cx) = two_groups(&log, cx);
        cx.run_until_parked();

        let node = child_node(&area, 0, cx);
        let group = cx.read(|cx| area.read(cx).groups.get(&node).unwrap().entity.clone());
        assert!(
            cx.read(|cx| group.read(cx).is_closable(cx)),
            "an unlocked group's panel can be closed"
        );

        cx.update(|window, cx| area.update(cx, |area, cx| area.set_locked(true, window, cx)));

        assert!(
            !cx.read(|cx| group.read(cx).is_closable(cx)),
            "the lock reaches every group through the constraints push"
        );
    }

    // The tests below were ported from `crates/component/src/dock/tab_panel.rs` when
    // the dock skin was rebuilt on this crate. They are the surviving record
    // of the `is_empty` semantics and the documented `set_active` contract.

    /// An empty `StackPanel` used to dump as `PanelInfo::Panel`, the
    /// `PanelState` default, so restoring looked it up in `PanelRegistry` and
    /// failed.
    #[gpui::test]
    fn empty_center_round_trips_as_a_stack(cx: &mut TestAppContext) {
        let (area, cx) = setup(cx);
        let center = cx.read(|cx| area.read(cx).dump(cx).center);

        assert_eq!(center.panel_name, "StackPanel");
        assert!(
            matches!(center.info, PanelInfo::Stack { .. }),
            "got {:?}",
            center.info
        );
    }

    #[gpui::test]
    fn fresh_center_is_empty(cx: &mut TestAppContext) {
        let (area, cx) = setup(cx);

        assert!(
            is_center_empty(&area, cx),
            "DockArea::new starts with an empty split centre"
        );
    }

    #[gpui::test]
    fn center_holding_a_tab_group_is_not_empty(cx: &mut TestAppContext) {
        let log = log_of();
        let (area, _panels, cx) = one_group(&log, &["A", "B"], None, cx);
        cx.run_until_parked();

        assert!(!is_center_empty(&area, cx));
    }

    /// The tree still lists the group's node here until the last panel goes,
    /// so anything reading node counts rather than panels would report
    /// non-empty.
    #[gpui::test]
    fn center_is_empty_again_once_every_panel_is_removed(cx: &mut TestAppContext) {
        let log = log_of();
        let (area, panels, cx) = one_group(&log, &["A", "B"], None, cx);
        cx.run_until_parked();

        for panel in panels {
            cx.update(|window, cx| {
                area.update(cx, |area, cx| area.remove_panel(panel.clone(), window, cx))
            });
        }
        cx.run_until_parked();

        assert!(is_center_empty(&area, cx));
    }

    #[gpui::test]
    fn center_is_not_empty_after_adding_to_a_tab_group(cx: &mut TestAppContext) {
        let (area, cx) = setup(cx);
        assert!(is_center_empty(&area, cx));

        cx.update(|window, cx| {
            let alpha = TestPanel::new("Alpha", cx);
            area.update(cx, |area, cx| {
                area.add_panel(alpha, DockPlacement::Center, None, window, cx)
            });
        });
        cx.run_until_parked();

        assert!(!is_center_empty(&area, cx));
    }

    /// The pre-wrapped companion of `add_panel`, for a layer that hands base
    /// its own handle. The panel it registers is the very handle it was
    /// given, keyed by the id that handle reports.
    #[gpui::test]
    fn add_panel_view_registers_the_handle_it_was_given(cx: &mut TestAppContext) {
        let (area, cx) = setup(cx);

        let view = cx.update(|window, cx| {
            let view: Arc<dyn PanelView> = Arc::new(TestPanel::new("Alpha", cx));
            area.update(cx, |area, cx| {
                area.add_panel_view(view.clone(), DockPlacement::Center, None, window, cx)
            });
            view
        });
        cx.run_until_parked();

        let id = cx.read(|cx| view.panel_id(cx));
        assert!(
            cx.read(|cx| area
                .read(cx)
                .panel(id)
                .is_some_and(|stored| Arc::ptr_eq(stored, &view))),
            "the stored handle is the one that was handed over, under its own id"
        );
        assert!(!is_center_empty(&area, cx));
    }

    /// Rendering skips invisible panels, so a centre holding only hidden ones
    /// draws nothing and counts as empty.
    #[gpui::test]
    fn center_holding_only_hidden_panels_is_empty(cx: &mut TestAppContext) {
        let log = log_of();
        let (area, panels, cx) = one_group(&log, &["A", "B"], None, cx);
        cx.run_until_parked();
        assert!(!is_center_empty(&area, cx));

        cx.update(|_, cx| {
            for panel in &panels {
                panel.update(cx, |panel, cx| panel.set_visible(false, cx));
            }
        });
        cx.run_until_parked();

        assert_eq!(
            cx.read(|cx| area
                .read(cx)
                .layout(DockPlacement::Center)
                .unwrap()
                .panels()
                .count()),
            2,
            "hiding a panel does not remove it from the tab group"
        );
        assert!(is_center_empty(&area, cx));
    }

    #[gpui::test]
    fn single_panel_group_receives_initial_active(cx: &mut TestAppContext) {
        let log = log_of();
        let (_area, _panels, cx) = one_group(&log, &["A"], None, cx);
        cx.run_until_parked();

        assert_eq!(drain_active(&log), [("A", true)]);
    }

    #[gpui::test]
    fn multi_tab_construction_notifies_only_displayed_panel(cx: &mut TestAppContext) {
        let log = log_of();
        let (_area, _panels, cx) = one_group(&log, &["A", "B", "C"], None, cx);
        cx.run_until_parked();

        // No false-then-true flip on A, no duplicate true, B/C silent.
        assert_eq!(drain_active(&log), [("A", true)]);
    }

    #[gpui::test]
    fn active_index_restore_notifies_that_panel_only(cx: &mut TestAppContext) {
        let log = log_of();
        let (_area, _panels, cx) = one_group(&log, &["A", "B", "C"], Some(2), cx);
        cx.run_until_parked();

        assert_eq!(drain_active(&log), [("C", true)]);
    }

    #[gpui::test]
    fn switching_tabs_sends_false_then_true(cx: &mut TestAppContext) {
        let log = log_of();
        let (area, _panels, cx) = one_group(&log, &["A", "B"], None, cx);
        cx.run_until_parked();
        drain(&log);

        let group = group_of(&area, 0, cx);
        cx.update(|window, cx| group.update(cx, |group, cx| group.select_tab(1, window, cx)));
        cx.run_until_parked();

        assert_eq!(drain_active(&log), [("A", false), ("B", true)]);
    }

    #[gpui::test]
    fn select_panel_displays_that_tab_where_it_sits(cx: &mut TestAppContext) {
        let log = log_of();
        let (area, panels, cx) = one_group(&log, &["A", "B", "C"], None, cx);
        cx.run_until_parked();
        drain(&log);

        let b = panel_id_of(&panels[1]);
        cx.update(|window, cx| area.update(cx, |area, cx| area.select_panel(b, window, cx)));
        cx.run_until_parked();

        assert_eq!(drain_active(&log), [("A", false), ("B", true)]);
        let (order, active_ix) = cx.read(|cx| {
            let tree = area.read(cx).layout(DockPlacement::Center).unwrap();
            let node = tree.find_panel_node(b).unwrap();
            match tree.find_node(node).unwrap().kind() {
                PaneRef::Tabs { panels, active_ix } => (panels.to_vec(), active_ix),
                PaneRef::Split { .. } => panic!("a tab group"),
            }
        });
        assert_eq!(active_ix, 1, "the selected tab is displayed");
        assert_eq!(
            order,
            panels.iter().map(panel_id_of).collect::<Vec<_>>(),
            "selecting a tab does not move it"
        );
    }

    #[gpui::test]
    fn select_panel_is_silent_for_the_displayed_or_an_unknown_panel(cx: &mut TestAppContext) {
        let log = log_of();
        let (area, panels, cx) = one_group(&log, &["A", "B"], None, cx);
        cx.run_until_parked();
        drain(&log);

        let a = panel_id_of(&panels[0]);
        let stranger = cx.update(|_, cx| panel_id_of(&TestPanel::logging("Z", &log, cx)));
        cx.update(|window, cx| {
            area.update(cx, |area, cx| {
                area.select_panel(a, window, cx);
                area.select_panel(stranger, window, cx);
            })
        });
        cx.run_until_parked();

        assert_eq!(drain_active(&log), []);
    }

    #[gpui::test]
    fn reselecting_active_tab_stays_silent(cx: &mut TestAppContext) {
        let log = log_of();
        let (area, _panels, cx) = one_group(&log, &["A", "B"], None, cx);
        cx.run_until_parked();
        drain(&log);

        let group = group_of(&area, 0, cx);
        cx.update(|window, cx| group.update(cx, |group, cx| group.select_tab(0, window, cx)));
        cx.run_until_parked();

        assert_eq!(drain_active(&log), []);
    }

    /// The old `TabPanel::insert_panel_at` took a brand-new panel; the tree
    /// API inserts a panel that is already in the dock, so `C` arrives from a
    /// second group. It was a background tab there and so has been told
    /// nothing, which is what makes the arrival a genuine activation rather
    /// than a seeded handoff.
    #[gpui::test]
    fn inserting_at_active_ix_swaps_notifications(cx: &mut TestAppContext) {
        let log = log_of();
        let (area, cx) = setup(cx);
        let c = cx.update(|window, cx| {
            let a = TestPanel::logging("A", &log, cx);
            let b = TestPanel::logging("B", &log, cx);
            let x = TestPanel::logging("X", &log, cx);
            let c = TestPanel::logging("C", &log, cx);
            area.update(cx, |area, cx| {
                area.set_center(
                    DockLayout::h_split()
                        .child(DockLayout::tabs().panel(a).panel(b), None)
                        .child(DockLayout::tabs().panel(x).panel(c.clone()), None),
                    window,
                    cx,
                );
            });
            c
        });
        cx.run_until_parked();
        drain(&log);

        let destination = child_node(&area, 0, cx);
        let c_id = panel_id_of(&c);
        move_panel_into(&area, c_id, destination, Some(0), true, cx);

        assert_eq!(drain_active(&log), [("A", false), ("C", true)]);
        let group = group_of(&area, 0, cx);
        assert_eq!(cx.read(|cx| group.read(cx).active_ix()), 0);
        assert_eq!(
            cx.read(|cx| group.read(cx).panels()[0].panel_id(cx)),
            c_id,
            "the arriving panel took the slot it named"
        );
    }

    #[gpui::test]
    fn removing_before_active_keeps_displayed_panel(cx: &mut TestAppContext) {
        let log = log_of();
        let (area, panels, cx) = one_group(&log, &["A", "B", "C"], None, cx);
        let group = group_of(&area, 0, cx);
        cx.update(|window, cx| group.update(cx, |group, cx| group.select_tab(1, window, cx)));
        cx.run_until_parked();
        drain(&log);

        cx.update(|window, cx| {
            area.update(cx, |area, cx| {
                area.remove_panel(panels[0].clone(), window, cx)
            })
        });
        cx.run_until_parked();

        assert_eq!(drain_active(&log), []);
        assert_eq!(cx.read(|cx| group.read(cx).active_ix()), 0);
        assert_eq!(
            cx.read(|cx| group.read(cx).panels()[0].panel_id(cx)),
            panel_id_of(&panels[1]),
            "the same panel is still displayed, at its new index"
        );
    }

    /// Collapsing is now a dock closing, which is what
    /// `TabGroupConstraints::collapsed` carries.
    #[gpui::test]
    fn collapse_and_expand_notify_active_panel(cx: &mut TestAppContext) {
        let log = log_of();
        let (area, cx) = setup(cx);
        cx.update(|window, cx| {
            let a = TestPanel::logging("A", &log, cx);
            let b = TestPanel::logging("B", &log, cx);
            area.update(cx, |area, cx| {
                area.set_dock(
                    DockPlacement::Left,
                    DockLayout::tabs().panel(a).panel(b),
                    window,
                    cx,
                );
            });
        });
        cx.run_until_parked();
        drain(&log);

        cx.update(|window, cx| {
            area.update(cx, |area, cx| {
                area.toggle_dock(DockPlacement::Left, window, cx)
            })
        });
        cx.run_until_parked();
        assert_eq!(drain_active(&log), [("A", false)]);

        cx.update(|window, cx| {
            area.update(cx, |area, cx| {
                area.toggle_dock(DockPlacement::Left, window, cx)
            })
        });
        cx.run_until_parked();
        assert_eq!(drain_active(&log), [("A", true)]);
    }

    #[gpui::test]
    fn background_add_is_silent_but_first_panel_is_not(cx: &mut TestAppContext) {
        let log = log_of();
        let (area, cx) = setup(cx);
        let d = cx.update(|window, cx| {
            let a = TestPanel::logging("A", &log, cx);
            let b = TestPanel::logging("B", &log, cx);
            let c = TestPanel::logging("C", &log, cx);
            let d = TestPanel::logging("D", &log, cx);
            area.update(cx, |area, cx| {
                area.set_center(
                    DockLayout::h_split()
                        .child(DockLayout::tabs().panel(a).panel(b), None)
                        .child(DockLayout::tabs().panel(c).panel(d.clone()), None),
                    window,
                    cx,
                );
            });
            d
        });
        cx.run_until_parked();
        drain(&log);

        // D is a background tab in its own group and arrives as a background
        // tab in the other one, so nothing changes for anybody.
        let destination = child_node(&area, 0, cx);
        move_panel_into(&area, panel_id_of(&d), destination, None, false, cx);
        assert_eq!(drain_active(&log), []);

        // The first panel of a region that had none is displayed regardless,
        // so it must be told.
        cx.update(|window, cx| {
            let e = TestPanel::logging("E", &log, cx);
            area.update(cx, |area, cx| {
                area.add_panel(e, DockPlacement::Left, None, window, cx)
            });
        });
        cx.run_until_parked();
        assert_eq!(drain_active(&log), [("E", true)]);
    }

    #[gpui::test]
    fn drag_active_panel_to_other_group_stays_silent_for_it(cx: &mut TestAppContext) {
        let log = log_of();
        let (area, cx) = setup(cx);
        let a = cx.update(|window, cx| {
            let a = TestPanel::logging("A", &log, cx);
            let b = TestPanel::logging("B", &log, cx);
            let c = TestPanel::logging("C", &log, cx);
            area.update(cx, |area, cx| {
                area.set_center(
                    DockLayout::h_split()
                        .child(DockLayout::tabs().panel(a.clone()).panel(b), None)
                        .child(DockLayout::tabs().panel(c), None),
                    window,
                    cx,
                );
            });
            a
        });
        cx.run_until_parked();
        drain(&log);

        // A was already told `true`; becoming the target's displayed tab must
        // not repeat it.
        let destination = child_node(&area, 1, cx);
        move_panel_into(&area, panel_id_of(&a), destination, None, true, cx);

        // Two groups reconcile independently, so their deliveries interleave
        // in no guaranteed order; what is pinned is which ones happen.
        let seen = drain_active(&log);
        assert!(seen.contains(&("B", true)), "got {seen:?}");
        assert!(seen.contains(&("C", false)), "got {seen:?}");
        assert!(
            !seen.iter().any(|(name, _)| *name == "A"),
            "the moved panel was displayed before and after: {seen:?}"
        );
    }

    #[gpui::test]
    fn drag_active_panel_to_background_slot_deactivates_it(cx: &mut TestAppContext) {
        let log = log_of();
        let (area, cx) = setup(cx);
        let a = cx.update(|window, cx| {
            let a = TestPanel::logging("A", &log, cx);
            let c = TestPanel::logging("C", &log, cx);
            let d = TestPanel::logging("D", &log, cx);
            area.update(cx, |area, cx| {
                area.set_center(
                    DockLayout::h_split()
                        .child(DockLayout::tabs().panel(a.clone()), None)
                        .child(DockLayout::tabs().panel(c).panel(d), None),
                    window,
                    cx,
                );
            });
            a
        });
        cx.run_until_parked();
        drain(&log);

        // A was told `true` and becomes a background tab, so it gets one
        // `false`.
        let destination = child_node(&area, 1, cx);
        move_panel_into(&area, panel_id_of(&a), destination, None, false, cx);

        assert_eq!(drain_active(&log), [("A", false)]);
    }

    /// A skin that records what it was asked to draw.
    ///
    /// The chrome is the point: a tab bar is drawn by the *group*, and it does
    /// not run if the area renders the bare panel instead, so what lands in
    /// this log says which of the two is on screen — a question no reading of
    /// `is_zoomed()` can answer.
    struct RecordingSkin {
        tab_bars: Rc<RefCell<Vec<NodeId>>>,
    }

    struct RecordingTabGroup {
        drawn: Rc<RefCell<Vec<NodeId>>>,
    }

    impl DockAreaRenderer for RecordingSkin {
        fn tab_group_renderer(&self) -> Rc<dyn TabGroupRenderer> {
            Rc::new(RecordingTabGroup {
                drawn: self.tab_bars.clone(),
            })
        }
    }

    impl TabGroupRenderer for RecordingTabGroup {
        fn render_tab_bar(
            &self,
            group: &TabGroupContext,
            _: &mut Window,
            _: &mut App,
        ) -> AnyElement {
            self.drawn.borrow_mut().push(group.node());
            Empty.into_any_element()
        }
    }

    type DrawLog = Rc<RefCell<Vec<NodeId>>>;

    /// [`setup`], with a skin that records the tab bars drawn.
    fn setup_recording(
        cx: &mut TestAppContext,
    ) -> (Entity<DockArea>, DrawLog, &mut VisualTestContext) {
        cx.update(|cx| {
            let _ = crate::Theme::global_mut(cx);
        });
        let tab_bars: DrawLog = Rc::default();
        let skin = Rc::new(RecordingSkin {
            tab_bars: tab_bars.clone(),
        });
        let (area, cx) = cx.add_window_view(|window, cx| {
            DockArea::new("test-dock", None, window, cx).with_renderer(skin)
        });
        (area, tab_bars, cx)
    }

    fn zoom_signals(log: &Log) -> Vec<(&'static str, PanelSignal)> {
        drain(log)
            .into_iter()
            .filter(|(_, signal)| matches!(signal, PanelSignal::Zoomed(_)))
            .collect()
    }

    /// The regression this exists for: zooming shows the *group*, tab bar and
    /// all, not the panel inside it.
    ///
    /// The old dock zoomed the whole `TabPanel` — every `subscribe_panel` call
    /// site handed it one — so the tab bar, the toolbar and the panel menu
    /// stayed on screen, and that is where the control that zooms back out
    /// lives. A zoom rendering the bare panel would still fill the area and
    /// still answer `is_zoomed()`; only the tab bar tells the two apart.
    #[gpui::test]
    fn a_zoomed_group_is_drawn_whole_rather_than_as_its_bare_panel(cx: &mut TestAppContext) {
        let log = log_of();
        let (area, tab_bars, cx) = setup_recording(cx);
        cx.update(|window, cx| {
            let alpha = TestPanel::logging("Alpha", &log, cx);
            let beta = TestPanel::logging("Beta", &log, cx);
            area.update(cx, |area, cx| {
                area.set_center(
                    DockLayout::h_split()
                        .child(DockLayout::tabs().panel(alpha), None)
                        .child(DockLayout::tabs().panel(beta), None),
                    window,
                    cx,
                );
            });
        });
        cx.run_until_parked();

        let zoomed = child_node(&area, 0, cx);
        let other = child_node(&area, 1, cx);
        assert!(
            tab_bars.borrow().contains(&zoomed) && tab_bars.borrow().contains(&other),
            "both groups draw their own tab bar while nothing is zoomed"
        );

        tab_bars.borrow_mut().clear();
        let group = group_of(&area, 0, cx);
        cx.update(|window, cx| group.update(cx, |group, cx| group.toggle_zoom(window, cx)));
        cx.run_until_parked();

        assert!(
            tab_bars.borrow().contains(&zoomed),
            "a zoomed group is rendered whole: its own tab bar is still drawn, \
             which is exactly what the bare panel does not carry"
        );
        assert!(
            !tab_bars.borrow().contains(&other),
            "and it is the only thing on screen"
        );
    }

    /// The area's zoom and the container's own flag are written together, so
    /// neither can be left believing something the other does not.
    ///
    /// A group left flagged zoomed reports itself locked for good, and a
    /// locked group refuses every drop.
    #[gpui::test]
    fn clearing_the_zoom_from_outside_puts_the_groups_own_flag_back(cx: &mut TestAppContext) {
        let log = log_of();
        let (area, _alpha, cx) = two_groups(&log, cx);
        cx.run_until_parked();
        drain(&log);

        let node = child_node(&area, 0, cx);
        let group = group_of(&area, 0, cx);
        cx.update(|window, cx| group.update(cx, |group, cx| group.toggle_zoom(window, cx)));
        cx.run_until_parked();
        assert_eq!(cx.read(|cx| area.read(cx).zoomed_group()), Some(node));
        assert!(cx.read(|cx| group.read(cx).is_zoomed()));
        assert_eq!(
            zoom_signals(&log),
            vec![("Alpha", PanelSignal::Zoomed(true))]
        );

        cx.update(|window, cx| area.update(cx, |area, cx| area.set_zoomed_out(window, cx)));
        cx.run_until_parked();

        assert!(!cx.read(|cx| area.read(cx).is_zoomed()));
        assert!(
            !cx.read(|cx| group.read(cx).is_zoomed()),
            "a group left flagged zoomed would stay locked and refuse every drop"
        );
        assert!(
            cx.read(|cx| group.read(cx).context(cx).is_droppable()),
            "and the lock the zoom imposed is lifted with it"
        );
        assert_eq!(
            zoom_signals(&log),
            vec![("Alpha", PanelSignal::Zoomed(false))],
            "the panel hears the zoom end too, not just the group"
        );
    }

    /// A group that refuses to zoom must not leave the area showing it as
    /// zoomed: the area records a zoom only once the container agrees.
    #[gpui::test]
    fn a_group_that_refuses_to_zoom_leaves_the_area_unzoomed(cx: &mut TestAppContext) {
        let log = log_of();
        let (area, alpha, cx) = two_groups(&log, cx);
        cx.run_until_parked();
        cx.update(|_, cx| alpha.update(cx, |panel, cx| panel.set_zoomable(false, cx)));

        let node = child_node(&area, 0, cx);
        let group = group_of(&area, 0, cx);
        cx.update(|window, cx| area.update(cx, |area, cx| area.set_zoomed_in(node, window, cx)));
        cx.run_until_parked();

        assert!(!cx.read(|cx| group.read(cx).is_zoomed()));
        assert!(
            !cx.read(|cx| area.read(cx).is_zoomed()),
            "the area must not fill itself with a group that never zoomed"
        );
    }
}
