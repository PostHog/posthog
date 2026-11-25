//! Dockable layout: splits and tab groups that a host can rearrange,
//! persist, and restore — with no appearance of its own.
//!
//! # The tree is the source of truth
//!
//! Each region — the center, plus an optional left, right, and bottom dock —
//! is one [`PaneTree`]. A tree is pure data. Containers are addressed by
//! [`NodeId`], panels by [`PanelId`], and no GPUI entity handle is stored
//! anywhere in it, which is what lets the layout algebra be exercised without
//! an `App` and lets a whole layout be compared, normalized, and serialized as
//! an ordinary value. A container is a `Split` or a `Tabs`; there is no leaf
//! variant, so a panel can only ever live inside a `Tabs`.
//!
//! Both ids are *stable*, and the rest of the design leans on it:
//!
//! - A [`NodeId`] survives every edit and every normalization rule. A
//!   container still present after a drag carries the same id it had before,
//!   which is what keeps a reconcile from tearing down entities the drag never
//!   touched.
//! - A [`PanelId`] is the panel entity's `EntityId`, so it identifies the
//!   panel for as long as the entity lives, across any number of moves between
//!   groups and regions.
//!
//! Every mutation goes through the tree — [`PaneTree::insert_panel`],
//! [`remove_panel`](PaneTree::remove_panel),
//! [`move_panel`](PaneTree::move_panel), [`split`](PaneTree::split),
//! [`set_active`](PaneTree::set_active), and the rest — and each normalizes
//! before returning, so the tree is self-consistent the instant an edit
//! returns. Every edit reports what it did as an [`EditResult`].
//!
//! # The area reconciles the tree into entities
//!
//! [`DockArea`] owns the trees and a cache of container entities keyed by
//! `NodeId` ([`TabGroup`] for a `Tabs` node), plus the panel handles keyed by
//! `PanelId`. After any edit that
//! reports a change it walks the tree, creates entities for ids the cache does
//! not have, drops entries for ids that are gone — telling those panels
//! [`Panel::on_removed`] — pushes sizes and active indices into the survivors,
//! and emits [`DockEvent::LayoutChanged`]. Nothing else turns a tree edit into
//! live entities.
//!
//! Because node ids are stable, a steady-state pass creates and drops nothing.
//!
//! A layout is described the same entity-free way: [`DockLayout`] builds a
//! tree, and [`DockArea::set_center`] / [`DockArea::set_dock`] install it.
//! [`DockArea::dump`] and [`DockArea::load`] round-trip a whole area through
//! [`DockAreaState`], rebuilding panels through the [`PanelRegistry`].
//!
//! # The renderer seam
//!
//! Base supplies behavior; the host supplies appearance. Nothing in this
//! module paints a color, a border, or a size. Two traits carry the
//! appearance in:
//!
//! - [`DockAreaRenderer`] — the area frame, each split's frame and the divider
//!   between its slots, one dock's chrome, and the stand-in for a panel this
//!   build cannot construct.
//! - [`TabGroupRenderer`] — the tab bar, how the displayed panel is placed,
//!   and the drop indicator.
//!
//! A renderer never sees a drag event or a mouse position. Base attaches the
//! drag sources, drop hit-testing, focus, and keyboard handling to the very
//! elements the renderer returns, and hands it resolved state through
//! [`DockContext`] and [`TabGroupContext`] — each of which
//! also carries the callbacks (`toggle`, `select_tab`, `close`, `resize_to`)
//! that the renderer invokes rather than reimplementing.
//!
//! An area built without a renderer still docks, drags, resizes and persists.
//! It simply draws nothing but the panels themselves.
//!
//! [`Panel`] splits at the same seam: this trait covers behavior, and a
//! presentation layer — `gpui_component::dock::Panel` — extends it with
//! titles, toolbars, and menus. A panel type implements both.
//!
//! Every hook is optional in the same way: a renderer that declines one gets
//! base's own minimum for it. [`DockAreaRenderer::render_split_handle`] is the
//! clearest case — return `None` and the divider falls back to a one-pixel
//! line colored from `Theme::resizable`, so a skin with no opinion about
//! dividers implements nothing, while one that has an opinion replaces the
//! paint without touching the hit area, the cursor, or the drag.
//!
//! # Why the layout is data
//!
//! The usual way to build a dock is to make each container a live view that
//! holds its children, so the widget tree *is* the layout. That is what this
//! module replaced, and the three costs it carries are the reason:
//!
//! - **Emptiness has to propagate.** When the last panel leaves a tab group,
//!   the group must remove itself from its parent, which may empty the parent
//!   in turn. With containers as views this is mutual recursion between two
//!   types, reaching upward through parent handles — and those handles have to
//!   be installed after construction, which in GPUI means a deferred pass.
//!   There is a window in which the tree disagrees with itself.
//! - **Structure and identity are the same thing.** Rearranging the widget
//!   tree means creating and dropping views, so a drag can reset the state of
//!   containers it never touched.
//! - **Nothing is testable without a window.** Asserting that a split collapses
//!   correctly requires an `App`, an entity, and a frame.
//!
//! Here the tree is a value and the entities are its projection. Collapse is
//! [`PaneTree::normalize`]: one post-order pass repeated to a fixpoint, no
//! parent pointers, no deferred work, and idempotent by construction. Identity
//! is a [`NodeId`] that survives every edit and every normalization rule, so
//! reconciliation is a diff rather than a rebuild. And the whole layout algebra
//! runs as plain `#[test]`.
//!
//! What this buys, stated as properties rather than adjectives: a layout can be
//! compared, cloned and serialized as an ordinary value; a steady-state
//! reconcile creates and drops nothing, so a drag leaves untouched panels
//! untouched; and `normalize(normalize(t)) == normalize(t)` holds for every
//! tree, which is what makes the persisted format canonical.
//!
//! # Where this sits among docking libraries
//!
//! Editors tend to build the layout engine into the application — Zed's
//! `PaneGroup` and VS Code's workbench are not reusable outside their hosts.
//! Standalone libraries split the engine from the view to varying degrees:
//! `golden-layout` owns its DOM outright, `FlexLayout` keeps a JSON model
//! beside a React renderer, and `dockview` goes furthest, running a
//! framework-agnostic engine behind thin adapters. All of them still paint
//! their own chrome and expose CSS as the way to change it.
//!
//! This module takes the same separation one step further: the engine paints
//! nothing at all. A renderer returns elements and base attaches the drag
//! sources, drop hit-testing, focus and keyboard handling to the elements it
//! got back, so appearance is not a set of overrides on top of a default look —
//! there is no default look. `crates/component/src/dock` and
//! `crates/base/examples/showcase/components/dock.rs` are two unrelated
//! appearances over one behavior.
//!
//! The naming follows the same neighborhood where it can. A tab group here is
//! what Zed calls a `Pane` and `dockview` calls a group; a [`Dock`] is Zed's
//! dock; a [`Panel`] is the dockable content, as in `dockview` — note that
//! VS Code uses "panel" for the bottom *region* instead, and `rc-dock` uses it
//! for the tab container.
//!
//! # A minimal area
//!
//! ```ignore
//! use std::rc::Rc;
//! use gpui::{px, Context, Window};
//! use gpui_base::dock::{DockArea, DockLayout, DockPlacement};
//!
//! let area = cx.new(|cx| {
//!     DockArea::new("workspace", Some(1), window, cx).with_renderer(Rc::new(MySkin))
//! });
//!
//! area.update(cx, |area, cx| {
//!     area.set_center(
//!         DockLayout::h_split()
//!             .child(DockLayout::tabs().panel(files.clone()), Some(px(240.)))
//!             .child(DockLayout::tabs().panel(editor.clone()), None),
//!         window,
//!         cx,
//!     );
//!     area.set_dock(
//!         DockPlacement::Bottom,
//!         DockLayout::tabs().panel(terminal.clone()),
//!         window,
//!         cx,
//!     );
//! });
//! ```
//!
//! `crates/base/examples/showcase/components/dock.rs` is that program in full,
//! renderers included — run it with `cargo run -p gpui-base dock`.
//! `crates/component/src/dock` is the production skin over the same seam.

mod active;
mod dock_area;
mod dock_placement;
mod drag;
pub mod layout;
mod panel;
mod registry;
mod state;
mod state_convert;
mod tab_group;
#[cfg(test)]
pub(crate) mod test_support;

pub use dock_area::{DockArea, DockAreaRenderer, DockContext, DockEvent};
pub use dock_placement::{Dock, DockSizing};
pub use drag::{AnyDrag, DragPanel, DropIndicator, DropPlaceholderBounds, DropTarget};
// `split_placement_at` stays internal for the same reason: where a drop lands
// is base's decision, and a renderer is told the result through
// `TabGroupContext::drop_indicator`.
pub use layout::{
    DockLayout, EditResult, InsertTarget, NodeId, PaneNode, PaneRef, PaneTree, PanelId, RootKind,
};
pub use panel::{Panel, PanelEvent, PanelView};
pub use registry::{PanelBuildContext, PanelRegistry, register_panel};
pub use state::{DockAreaState, DockPlacement, DockState, PanelInfo, PanelState};
/// Both halves of the persistence seam. `PaneTree::to_state` reads panel
/// properties through `PanelSource`; `PaneTree::from_state` turns persisted
/// leaves back into panels through `PanelBuilder`. Exporting only the first
/// left `from_state` public but uncallable, since no caller outside this crate
/// could name the trait its parameter requires.
pub use state_convert::{PanelBuilder, PanelSource};
pub use tab_group::{
    TabGroup, TabGroupConstraints, TabGroupContext, TabGroupEvent, TabGroupRenderer,
};
