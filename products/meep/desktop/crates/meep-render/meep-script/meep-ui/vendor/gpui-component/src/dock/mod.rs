//! The gpui-component appearance for the dock.
//!
//! The layout tree, the persisted schema, the drag geometry, the active-panel
//! state machine and the container entities all live in
//! [`gpui_base::dock`]. This module is the skin over them: it re-exports the
//! types a consumer needs, adds the presentation half of the panel traits
//! (see [`panel`]), and implements base's two renderer traits.
//!
//! ```ignore
//! let area = cx.new(|cx| {
//!     DockArea::new("main", Some(1), window, cx).with_renderer(DockSkin::new(cx))
//! });
//! ```
//!
//! A [`DockArea`] built without [`DockSkin`] still docks, drags and persists —
//! it simply draws no chrome at all.

mod dock;
mod invalid_panel;
mod panel;
mod tab_panel;
#[cfg(test)]
mod test_support;

use std::{cell::Cell, rc::Rc};

use gpui::{
    App, AppContext as _, Context, Entity, EventEmitter, SharedString, WeakEntity, Window, actions,
};

/// The behavior half of the panel traits, which every panel implements
/// alongside [`Panel`]. Exported under this name because `Panel` in this
/// module is the presentation half that extends it.
pub use gpui_base::dock::Panel as BasePanel;
/// The object-safe counterpart of [`BasePanel`], for the same reason.
pub use gpui_base::dock::PanelView as BasePanelView;
/// Everything [`gpui_base::dock`] exports, so a consumer never has to depend
/// on the foundation crate directly to write a skin or read a container's
/// state. Kept in step with base's own list by
/// `every_base_dock_export_is_reachable_from_here`.
///
/// Two names are handled elsewhere and one is deliberately absent:
/// base's `Panel` and `PanelView` arrive as [`BasePanel`] and [`BasePanelView`]
/// because this module's `Panel`/`PanelView` are the presentation halves that
/// extend them, and base's `Dock` — a plain state struct holding one dock's
/// open, collapsible, size and resizing flags — is not re-exported at all,
/// because the name meant a panel container in every released version of this
/// crate and handing it back with a different meaning is worse than dropping
/// it. A skin reads a dock through [`DockContext`].
pub use gpui_base::dock::{
    AnyDrag, DockArea, DockAreaRenderer, DockAreaState, DockContext, DockEvent, DockLayout,
    DockPlacement, DockSizing, DockState, DragPanel, DropIndicator, DropPlaceholderBounds,
    DropTarget, EditResult, InsertTarget, NodeId, PaneNode, PaneRef, PaneTree, PanelBuildContext,
    PanelBuilder, PanelEvent, PanelId, PanelInfo, PanelRegistry, PanelSource, PanelState, RootKind,
    TabGroup, TabGroupConstraints, TabGroupContext, TabGroupEvent, TabGroupRenderer,
    register_panel,
};
pub use panel::*;
pub use tab_panel::DragPanelPreview;

actions!(dock, [ToggleZoom, ClosePanel]);

/// A dock that the user opened or closed with one of [`DockSkin`]'s controls:
/// the collapse button in a tab bar, the strip of a collapsed bottom dock, or
/// a resize handle dragged past the closed strip and released.
///
/// A [`DockArea`] drawn by [`DockSkin`] emits it after the dock has changed.
/// [`DockArea::toggle_dock`] and the other dock setters do not, so an
/// application can tell a user's toggle from one its own code made.
pub struct DockToggleEvent {
    placement: DockPlacement,
    open: bool,
}

impl DockToggleEvent {
    /// The dock that was toggled.
    pub fn placement(&self) -> DockPlacement {
        self.placement
    }

    /// Whether the dock is open now.
    pub fn is_open(&self) -> bool {
        self.open
    }
}

impl EventEmitter<DockToggleEvent> for DockArea {}

/// Toggle a dock on the user's behalf and report it with [`DockToggleEvent`].
/// A dock that refuses to close emits nothing.
pub(crate) fn toggle_dock_by_user(
    area: &mut DockArea,
    placement: DockPlacement,
    window: &mut Window,
    cx: &mut Context<DockArea>,
) {
    let was_open = area.is_dock_open(placement);
    area.toggle_dock(placement, window, cx);
    report_user_toggle(area, placement, was_open, cx);
}

/// Emit [`DockToggleEvent`] if a user action moved the dock away from
/// `was_open`.
pub(crate) fn report_user_toggle(
    area: &DockArea,
    placement: DockPlacement,
    was_open: bool,
    cx: &mut Context<DockArea>,
) {
    let open = area.is_dock_open(placement);
    if open != was_open {
        cx.emit(DockToggleEvent { placement, open });
    }
}

pub(crate) fn init(cx: &mut App) {
    // `gpui_base::dock::PanelRegistry::init` is crate-private, but the global
    // it installs is not: `DockArea::new` and `register_panel` both create it
    // on demand, and this keeps the old guarantee that it exists as soon as
    // `gpui_component::init` has run.
    if cx.try_global::<PanelRegistry>().is_none() {
        cx.set_global(PanelRegistry::new());
    }
}

/// What every part of the skin reads, and the dock area it belongs to.
///
/// The renderer is the only skin-owned object in the picture, so the settings
/// the old `DockArea` carried — the panel style, whether dock collapse
/// affordances are offered at all — live here. It is shared by reference with
/// the per-container renderers, which are built once each and outlive any one
/// frame.
pub(crate) struct SkinShared {
    area: WeakEntity<DockArea>,
    panel_style: Cell<PanelStyle>,
    toggle_button_visible: Cell<bool>,
    close_button_visible: Cell<bool>,
    /// The dock whose resize handle is being dragged, if any. Only one can be.
    resizing_dock: Cell<Option<DockPlacement>>,
    /// Whether that dock was open when the drag began, so the release can
    /// tell whether the drag opened or closed it.
    resize_started_open: Cell<bool>,
}

impl SkinShared {
    pub(crate) fn area(&self) -> &WeakEntity<DockArea> {
        &self.area
    }

    pub(crate) fn panel_style(&self) -> PanelStyle {
        self.panel_style.get()
    }

    pub(crate) fn is_toggle_button_visible(&self) -> bool {
        self.toggle_button_visible.get()
    }

    pub(crate) fn resizing_dock(&self) -> &Cell<Option<DockPlacement>> {
        &self.resizing_dock
    }

    pub(crate) fn resize_started_open(&self) -> &Cell<bool> {
        &self.resize_started_open
    }

    /// Redraw the area after a setting changed. The skin is not an entity, so
    /// nothing else would notice.
    fn notify(&self, cx: &mut App) {
        _ = self.area.update(cx, |_, cx| cx.notify());
    }
}

/// The gpui-component appearance for a [`DockArea`], and the handle its
/// settings are changed through.
///
/// Install it at construction, where the area's own weak handle is available:
///
/// ```ignore
/// let skin = DockSkin::new(cx);
/// DockArea::new("main", None, window, cx).with_renderer(skin)
/// ```
///
/// Keep the returned handle to change a setting later; it is an `Rc`, so a
/// clone and the installed renderer are the same skin.
pub struct DockSkin {
    shared: Rc<SkinShared>,
}

impl DockSkin {
    /// Build a [`DockArea`] wearing this appearance, together with the handle
    /// its settings are changed through.
    ///
    /// The skin needs the area's own weak handle, so it can only be built
    /// while the area is being constructed; this is that dance done once.
    pub fn dock_area(
        id: impl Into<SharedString>,
        version: Option<usize>,
        window: &mut Window,
        cx: &mut App,
    ) -> (Entity<DockArea>, Rc<Self>) {
        let mut skin = None;
        let area = cx.new(|cx| {
            let this = Self::new(cx);
            skin = Some(this.clone());
            DockArea::new(id, version, window, cx).with_renderer(this)
        });
        // The closure above runs before `cx.new` returns.
        (
            area,
            skin.expect("DockSkin::new ran inside the constructor"),
        )
    }

    pub fn new(cx: &mut Context<DockArea>) -> Rc<Self> {
        Rc::new(Self {
            shared: Rc::new(SkinShared {
                area: cx.weak_entity(),
                panel_style: Cell::new(PanelStyle::default()),
                toggle_button_visible: Cell::new(true),
                close_button_visible: Cell::new(false),
                resizing_dock: Cell::new(None),
                resize_started_open: Cell::new(false),
            }),
        })
    }

    pub(crate) fn shared(&self) -> &Rc<SkinShared> {
        &self.shared
    }

    /// Whether a single-panel tab group draws a plain title or a full tab bar.
    pub fn panel_style(&self) -> PanelStyle {
        self.shared.panel_style()
    }

    pub fn set_panel_style(&self, style: PanelStyle, cx: &mut App) {
        self.shared.panel_style.set(style);
        self.shared.notify(cx);
    }

    /// Whether tab bars offer the affordance that collapses a neighbouring
    /// dock.
    pub fn is_toggle_button_visible(&self) -> bool {
        self.shared.is_toggle_button_visible()
    }

    pub fn set_toggle_button_visible(&self, visible: bool, cx: &mut App) {
        self.shared.toggle_button_visible.set(visible);
        self.shared.notify(cx);
    }

    /// Show close buttons on closable tabs. Hidden by default; a panel's
    /// own close constraints still decide whether its button appears.
    pub fn set_close_button_visible(&self, visible: bool, cx: &mut App) {
        self.shared.close_button_visible.set(visible);
        self.shared.notify(cx);
    }
}

#[cfg(test)]
mod tests {
    /// Every name `gpui_base::dock` exports has to be reachable from
    /// `gpui_component::dock`, or an application cannot write its own skin
    /// without depending on the foundation crate directly.
    ///
    /// This reads both export lists rather than naming them, because the way
    /// this went wrong was checking the list against a description of base
    /// instead of against base itself: a hand-written list cannot notice a
    /// name base gained after it was written; two names were missing when
    /// this was added.
    ///
    /// The parse is deliberately crude — it takes the braces of each
    /// `pub use ...::{..}` and the tail of each single-name `pub use a::b;` —
    /// so a reformat of either file could trip it. That failure says "look at
    /// the two lists", which is the right thing to do anyway.
    fn exported_names(source: &str, prefix: &str) -> Vec<String> {
        let mut names = Vec::new();
        let mut rest = source;
        while let Some(at) = rest.find(prefix) {
            rest = &rest[at + prefix.len()..];
            let Some(end) = rest.find(';') else { break };
            let (item, tail) = rest.split_at(end);
            rest = tail;
            let item = item.trim();
            let list = match (item.find('{'), item.rfind('}')) {
                (Some(open), Some(close)) if open < close => &item[open + 1..close],
                // `pub use a::b;` — the name is the last path segment.
                _ => item.rsplit("::").next().unwrap_or(""),
            };
            names.extend(
                list.split(',')
                    .map(|name| name.split(" as ").next().unwrap_or("").trim().to_string())
                    .filter(|name| !name.is_empty()),
            );
        }
        names.sort();
        names.dedup();
        names
    }

    #[test]
    fn every_base_dock_export_is_reachable_from_here() {
        let base = include_str!("../../../base/src/dock/mod.rs");
        let skin = include_str!("mod.rs");

        let exported = exported_names(base, "pub use ");
        assert!(
            exported.len() > 30,
            "the parse found only {} names in base's dock module, so it is \
             reading the wrong thing rather than reporting the truth",
            exported.len()
        );

        let reachable = exported_names(skin, "pub use gpui_base::dock::");
        // `Panel` and `PanelView` are re-exported under other names because
        // this module's own `Panel`/`PanelView` extend them; `Dock` is a
        // documented omission. See the doc on the re-export block.
        let renamed = ["Panel", "PanelView"];
        let omitted = ["Dock"];

        let missing: Vec<&String> = exported
            .iter()
            .filter(|name| {
                !reachable.contains(name)
                    && !renamed.contains(&name.as_str())
                    && !omitted.contains(&name.as_str())
            })
            .collect();

        assert!(
            missing.is_empty(),
            "gpui_base::dock exports these, and gpui_component::dock does not \
             re-export them: {missing:?}. Add them to the list, or add the \
             name to `omitted` with the reason on the re-export block."
        );
    }
}
