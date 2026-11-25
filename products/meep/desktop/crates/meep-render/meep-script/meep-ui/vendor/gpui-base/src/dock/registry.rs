use std::{collections::HashMap, sync::Arc};

use gpui::{App, Global, WeakEntity, Window};

use super::{DockArea, PanelInfo, PanelState, PanelView};

/// Everything a panel builder needs to reconstruct a panel from persisted data.
pub struct PanelBuildContext<'a> {
    dock_area: WeakEntity<DockArea>,
    state: &'a PanelState,
    info: &'a PanelInfo,
}

impl<'a> PanelBuildContext<'a> {
    pub fn new(
        dock_area: WeakEntity<DockArea>,
        state: &'a PanelState,
        info: &'a PanelInfo,
    ) -> Self {
        Self {
            dock_area,
            state,
            info,
        }
    }

    pub fn dock_area(&self) -> WeakEntity<DockArea> {
        self.dock_area.clone()
    }

    pub fn state(&self) -> &PanelState {
        self.state
    }

    pub fn info(&self) -> &PanelInfo {
        self.info
    }
}

/// Global registry of panel builders, keyed by panel name, used to reconstruct
/// a panel view from persisted [`PanelState`]/[`PanelInfo`] data.
///
/// A builder returns an [`Arc<dyn PanelView>`](PanelView), not a bare
/// `AnyView`. An earlier revision of this module returned `AnyView` so that a
/// builder would not have to depend on the panel traits, on the reasoning
/// that "a caller that needs a richer handle downcasts or wraps the
/// `AnyView` itself". [`DockArea::load`](super::DockArea::load) is that
/// caller, and it cannot: downcasting needs the concrete type, which the
/// registry is precisely the mechanism for not knowing. Without a
/// `PanelView` a restored panel could not be asked for its
/// [`dump`](PanelView::dump), so every registered panel's own persisted
/// payload would be dropped on the first save after a load.
///
/// Building a panel that was never registered returns `None` rather than a
/// placeholder view: rendering an "invalid panel" placeholder is presentation
/// behavior that belongs above this seam, not inside `gpui-base`. `DockArea`
/// substitutes a draw-nothing placeholder that carries the original
/// `PanelState` forward, so an unknown panel survives a round trip.
pub struct PanelRegistry {
    items: HashMap<
        String,
        Arc<dyn Fn(PanelBuildContext, &mut Window, &mut App) -> Arc<dyn PanelView>>,
    >,
}

impl PanelRegistry {
    /// Initialize the panel registry.
    pub(crate) fn init(cx: &mut App) {
        if cx.try_global::<PanelRegistry>().is_none() {
            cx.set_global(PanelRegistry::new());
        }
    }

    pub fn new() -> Self {
        Self {
            items: HashMap::new(),
        }
    }

    pub fn global(cx: &App) -> &Self {
        cx.global::<PanelRegistry>()
    }

    pub fn global_mut(cx: &mut App) -> &mut Self {
        cx.global_mut::<PanelRegistry>()
    }

    /// Build a panel by name.
    ///
    /// Returns `None` if no builder is registered for `panel_name`.
    pub fn build_panel(
        panel_name: &str,
        context: PanelBuildContext,
        window: &mut Window,
        cx: &mut App,
    ) -> Option<Arc<dyn PanelView>> {
        let build = Self::global(cx).items.get(panel_name).cloned()?;
        Some(build(context, window, cx))
    }
}

impl Default for PanelRegistry {
    fn default() -> Self {
        Self::new()
    }
}

impl Global for PanelRegistry {}

/// Register the Panel init by panel_name to global registry.
pub fn register_panel<F>(cx: &mut App, panel_name: &str, deserialize: F)
where
    F: Fn(PanelBuildContext, &mut Window, &mut App) -> Arc<dyn PanelView> + 'static,
{
    PanelRegistry::init(cx);
    PanelRegistry::global_mut(cx)
        .items
        .insert(panel_name.to_string(), Arc::new(deserialize));
}
