//! Panel doubles shared by the dock's tests.
//!
//! This lives beside the production modules rather than inside one module's
//! `mod tests` so `tab_group`, `dock_area`, and the cutover tests can share a
//! single panel double and a single ordered delivery log. Ported from the
//! `TabPanel` tests in `crates/component/src/dock/tab_panel.rs`.

use std::sync::{Arc, Mutex};

use gpui::{
    App, AppContext as _, Context, Empty, Entity, EventEmitter, FocusHandle, Focusable,
    IntoElement, Render, TestAppContext, VisualTestContext, WeakEntity, Window,
};

use super::layout::{NodeId, PanelId};
use super::panel::{Panel, PanelEvent, PanelView};
use super::tab_group::{TabGroup, TabGroupConstraints};

/// One thing a panel was told, in delivery order.
///
/// `set_active` and the membership callbacks share one log because their
/// relative order is itself part of the contract under test: a panel joining a
/// group must see `Added` before it is told it is active.
///
/// `Removed` is also where a deliberate divergence from `crates/component` shows up.
/// The old `TabPanel::detach_panel` calls `on_removed` on every detach,
/// including the detach half of a drag between groups, so a moved panel is
/// told it was removed and then added again. In the tree world a move never
/// leaves the tree — `PaneTree::move_panel` reports no `removed_panels`, and
/// `EditResult::removed_panels` documents that a moved panel is absent from it
/// precisely so its entity survives. So under the new contract a moved panel
/// must never see `Removed`.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum PanelSignal {
    Active(bool),
    Zoomed(bool),
    Added,
    Removed,
}

/// Shared, cross-panel ordered log of everything the panels were told.
pub(crate) type Log = Arc<Mutex<Vec<(&'static str, PanelSignal)>>>;

pub(crate) fn log_of() -> Log {
    Log::default()
}

/// Take everything logged so far, leaving the log empty.
pub(crate) fn drain(log: &Log) -> Vec<(&'static str, PanelSignal)> {
    std::mem::take(&mut *log.lock().unwrap())
}

/// [`drain`], keeping only the `set_active` edges. Most tests care about the
/// active-state contract and would otherwise have to filter the membership
/// callbacks out by hand at every assertion.
pub(crate) fn drain_active(log: &Log) -> Vec<(&'static str, bool)> {
    drain(log)
        .into_iter()
        .filter_map(|(name, signal)| match signal {
            PanelSignal::Active(active) => Some((name, active)),
            _ => None,
        })
        .collect()
}

pub(crate) struct TestPanel {
    name: &'static str,
    focus_handle: FocusHandle,
    log: Log,
    visible: bool,
    zoomable: bool,
    pub(crate) group: Option<WeakEntity<TabGroup>>,
}

impl TestPanel {
    /// A panel whose deliveries go nowhere. For tests that only need a panel
    /// to exist.
    pub(crate) fn new(name: &'static str, cx: &mut App) -> Entity<Self> {
        Self::logging(name, &log_of(), cx)
    }

    pub(crate) fn logging(name: &'static str, log: &Log, cx: &mut App) -> Entity<Self> {
        let log = log.clone();
        cx.new(|cx| Self {
            name,
            focus_handle: cx.focus_handle(),
            log,
            visible: true,
            zoomable: true,
            group: None,
        })
    }

    pub(crate) fn set_visible(&mut self, visible: bool, cx: &mut Context<Self>) {
        self.visible = visible;
        cx.notify();
    }

    /// A panel that refuses to zoom, which its group must honour.
    pub(crate) fn set_zoomable(&mut self, zoomable: bool, cx: &mut Context<Self>) {
        self.zoomable = zoomable;
        cx.notify();
    }

    fn record(&self, signal: PanelSignal) {
        self.log.lock().unwrap().push((self.name, signal));
    }
}

impl Panel for TestPanel {
    /// The panel's own name, so a dumped layout is legible in assertions.
    fn panel_name(&self) -> &'static str {
        self.name
    }

    fn visible(&self, _: &App) -> bool {
        self.visible
    }

    fn zoomable(&self, _: &App) -> bool {
        self.zoomable
    }

    fn set_active(&mut self, active: bool, _: &mut Window, _: &mut Context<Self>) {
        self.record(PanelSignal::Active(active));
    }

    fn set_zoomed(&mut self, zoomed: bool, _: &mut Window, _: &mut Context<Self>) {
        self.record(PanelSignal::Zoomed(zoomed));
    }

    fn on_added_to(&mut self, group: WeakEntity<TabGroup>, _: &mut Window, _: &mut Context<Self>) {
        self.group = Some(group);
        self.record(PanelSignal::Added);
    }

    fn on_removed(&mut self, _: &mut Window, _: &mut Context<Self>) {
        self.group = None;
        self.record(PanelSignal::Removed);
    }
}

impl EventEmitter<PanelEvent> for TestPanel {}

impl Focusable for TestPanel {
    fn focus_handle(&self, _: &App) -> FocusHandle {
        self.focus_handle.clone()
    }
}

impl Render for TestPanel {
    fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
        Empty
    }
}

pub(crate) fn panel_id(panel: &Entity<TestPanel>, cx: &TestAppContext) -> PanelId {
    cx.read(|cx| Arc::new(panel.clone()).panel_id(cx))
}

/// Open a window holding one tab group over freshly built panels named
/// `names`, with the first tab displayed.
pub(crate) fn build_group<'a>(
    log: &Log,
    names: &[&'static str],
    cx: &'a mut TestAppContext,
) -> (
    Entity<TabGroup>,
    Vec<Entity<TestPanel>>,
    &'a mut VisualTestContext,
) {
    let (group, cx) =
        cx.add_window_view(|window, cx| TabGroup::new(NodeId::from_u64(1), window, cx));

    let names = names.to_vec();
    let log = log.clone();
    let panels = cx.update(|window, cx| {
        let panels: Vec<_> = names
            .iter()
            .map(|name| TestPanel::logging(name, &log, cx))
            .collect();
        let views: Vec<Arc<dyn PanelView>> = panels
            .iter()
            .map(|panel| Arc::new(panel.clone()) as Arc<dyn PanelView>)
            .collect();
        group.update(cx, |group, cx| {
            // A freshly built group is sealed; place it beside siblings so
            // tests that do not care about constraints get a working group.
            group.set_constraints(TabGroupConstraints::in_split(false), window, cx);
            group.sync_from_tree(views, 0, window, cx);
        });
        panels
    });

    (group, panels, cx)
}
