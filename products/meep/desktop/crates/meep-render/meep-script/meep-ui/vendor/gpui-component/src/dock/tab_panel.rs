//! The gpui-component appearance for a tab group.
//!
//! `gpui_base::dock::TabGroup` owns the behavior — membership, the displayed
//! tab, drag hit-testing, the zoom flag — and draws none of it. Everything
//! visible is here: the tab bar, the toolbar, the ellipsis menu, the dock
//! collapse affordances, the drop placeholder, and the styled drag preview.

use std::{
    cell::{Cell, RefCell},
    collections::HashSet,
    rc::Rc,
    sync::Arc,
};

use gpui::{
    Anchor, AnyElement, AnyView, App, AppContext as _, Context, Div, Empty,
    InteractiveElement as _, IntoElement, ParentElement as _, Render, ScrollHandle, SharedString,
    Stateful, StatefulInteractiveElement as _, StyleRefinement, Styled as _, Window, div,
    prelude::FluentBuilder as _, px,
};
use gpui_base::{
    dock::{
        AnyDrag, DockPlacement, DragPanel, DropIndicator, NodeId, PaneNode, PaneRef, PanelId,
        TabGroupContext, TabGroupRenderer,
    },
    spring,
};
use rust_i18n::t;

use crate::{
    ActiveTheme as _, IconName, Selectable as _, Sizable as _,
    button::{Button, ButtonCustomVariant, ButtonVariants as _},
    dock::{
        ClosePanel, PanelControl, PanelHandle, PanelStyle, SkinShared, ToggleZoom,
        toggle_dock_by_user,
    },
    h_flex,
    menu::DropdownMenu as _,
    tab::{Tab, TabBar},
};

/// Names the tab bar's zoom button in the debug-bounds map, so a test can ask
/// a really-drawn frame whether the control was offered.
const ZOOM_CONTROL_SELECTOR: &str = "dock-tab-bar-zoom-control";

/// Debug-bounds selector for a tab's close (X) button, for tests.
const CLOSE_BUTTON_SELECTOR: &str = "dock-tab-close-button";

/// Debug-bounds selector prefix for a tab, suffixed with its panel index.
const TAB_SELECTOR: &str = "dock-tab";

/// Debug-bounds selector prefix for a dock's collapse button, suffixed with
/// its placement.
const DOCK_TOGGLE_SELECTOR: &str = "dock-toggle";

/// The size the styled drag preview occupies, reported to base so a drop
/// placeholder knows where to fly in from.
const DRAG_PREVIEW_SIZE: gpui::Size<gpui::Pixels> = gpui::size(px(96.), px(30.));

/// The preview that follows the cursor while a panel is dragged.
///
/// `gpui_base::dock::DragPanel` is the payload and draws nothing; this is the
/// appearance half, reintroduced here.
pub struct DragPanelPreview {
    panel: Arc<dyn gpui_base::dock::PanelView>,
}

impl Render for DragPanelPreview {
    fn render(&mut self, window: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        div()
            .id("drag-panel")
            .cursor_grab()
            .py_1()
            .px_3()
            .w_24()
            .overflow_hidden()
            .whitespace_nowrap()
            .border_1()
            .border_color(cx.theme().border)
            .rounded(cx.theme().radius)
            .text_color(cx.theme().tab_foreground)
            .bg(cx.theme().tokens.tab_active)
            .opacity(0.75)
            .child(panel_title(&self.panel, window, cx))
    }
}

/// A panel's title, or its registered name when it reached base without this
/// crate's handle and so carries no presentation. See [`PanelHandle::of`].
pub(crate) fn panel_title(
    panel: &Arc<dyn gpui_base::dock::PanelView>,
    window: &mut Window,
    cx: &mut App,
) -> AnyElement {
    let Some(handle) = PanelHandle::of(panel) else {
        let name = panel.panel_name(cx);
        warn_unwrapped_once(panel.panel_id(cx), name);
        return SharedString::from(name).into_any_element();
    };
    handle.title(window, cx)
}

thread_local! {
    /// Panels already warned about. `panel_title` sits on the render path, so
    /// an unguarded warning would repeat at frame rate and bury the very
    /// signal it exists to give.
    ///
    /// Keyed by panel rather than a bare `Once` so a second wrongly installed
    /// panel is still named, and a runtime set rather than a `debug_assert!`
    /// so a release build says it too — the consequence is a shipped app whose
    /// tabs are titleless, which is exactly when someone needs to be told.
    /// Thread-local because rendering happens on one thread, so no lock is
    /// needed.
    static WARNED_UNWRAPPED: RefCell<HashSet<PanelId>> = RefCell::new(HashSet::new());
}

/// Say once, per panel, that a panel reached the skin without its
/// presentation handle. Silent otherwise, and visual-only: the panel docks,
/// drags and persists, it just has no title. The shorter method is the wrong
/// one — `DockLayout::panel` and `DockArea::add_panel` accept a
/// `gpui_component::dock::Panel` and store the bare entity — so this says
/// which panel and what to call instead.
fn warn_unwrapped_once(panel: PanelId, name: &'static str) {
    if !WARNED_UNWRAPPED.with(|warned| warned.borrow_mut().insert(panel)) {
        return;
    }
    tracing::warn!(
        panel = name,
        "dock panel reached the skin without its presentation handle, so it \
         draws its panel name instead of its title; install it with \
         `gpui_component::dock::panel_handle(..)` and `DockLayout::panel_view` \
         / `DockArea::add_panel_view` rather than `DockLayout::panel` / \
         `DockArea::add_panel`"
    );
}

/// Where the zoom affordance goes for the group's displayed panel, or `None`
/// when there is none to offer.
///
/// Two questions, and both have to be asked. [`Panel::zoom_control`] says
/// *where* the control appears; [`gpui_base::dock::Panel::zoomable`] says
/// whether zooming happens at all, and base refuses a zoom that fails it. The
/// old dock had a single `zoomable() -> Option<PanelControl>` that could not
/// disagree with itself; split across the seam it can, and a panel answering
/// `zoomable() == false` with `zoom_control() == Some(Toolbar)` would
/// otherwise draw a button that does nothing.
fn zoom_control(group: &TabGroupContext, cx: &App) -> Option<PanelControl> {
    let panel = group.active_panel()?;
    panel
        .zoomable(cx)
        .then(|| PanelHandle::of(panel).and_then(|handle| handle.zoom_control(cx)))
        .flatten()
}

/// The payload for dragging the tab at `ix` out of its group, or `None` when
/// this group must not be rearranged.
///
/// The guard is the skin's. [`TabGroupContext::drag_panel`] answers for any
/// tab in range whether or not the group may be rearranged, so a tab bar that
/// forgets to ask [`TabGroupContext::is_draggable`] makes a group that has
/// nowhere to go — a dock's last group, a locked dock — draggable anyway. The
/// old dock asked the same question, spelled `state.draggable`.
fn tab_drag(group: &TabGroupContext, ix: usize, cx: &App) -> Option<DragPanel> {
    group
        .is_draggable()
        .then(|| group.drag_panel(ix, cx))
        .flatten()
}

/// The left-most, top-most tab group in a container — where a left dock's
/// collapse affordance goes. Mirrors the old `StackPanel::left_top_tab_panel`.
fn left_top_group(node: &PaneNode) -> Option<NodeId> {
    match node.kind() {
        PaneRef::Tabs { .. } => Some(node.id()),
        PaneRef::Split { children, .. } => children.first().and_then(left_top_group),
    }
}

/// The right-most, top-most tab group. A vertical split stacks its children,
/// so its *first* child is the top one; a horizontal split's last child is the
/// right-most. Mirrors the old `StackPanel::right_top_tab_panel`.
fn right_top_group(node: &PaneNode) -> Option<NodeId> {
    match node.kind() {
        PaneRef::Tabs { .. } => Some(node.id()),
        PaneRef::Split { axis, children, .. } => match axis {
            gpui::Axis::Vertical => children.first(),
            gpui::Axis::Horizontal => children.last(),
        }
        .and_then(right_top_group),
    }
}

/// One tab group's appearance.
///
/// Built per group — `DockAreaRenderer::tab_group_renderer` is called once per
/// container — so the tab bar's scroll position belongs to the group whose
/// tabs it scrolls.
pub(crate) struct TabGroupSkin {
    shared: Rc<SkinShared>,
    scroll_handle: ScrollHandle,
    /// The displayed tab the last frame drew, so a change scrolls the new tab
    /// into view. The old dock recorded this at the moment of selection; the
    /// group now owns selection, so the skin notices instead of being told.
    last_active_ix: Rc<Cell<Option<usize>>>,
}

impl TabGroupSkin {
    pub(crate) fn new(shared: Rc<SkinShared>) -> Self {
        Self {
            shared,
            scroll_handle: ScrollHandle::default(),
            last_active_ix: Rc::new(Cell::new(None)),
        }
    }

    /// Whether a dock's collapse affordance belongs in *this* group's tab bar,
    /// and which way it points. `None` means this group draws none.
    fn dock_toggle_button(
        &self,
        placement: DockPlacement,
        group: &TabGroupContext,
        cx: &mut App,
    ) -> Option<Button> {
        if group.is_zoomed() || !self.shared.is_toggle_button_visible() {
            return None;
        }

        let area = self.shared.area().upgrade()?;
        let area = area.read(cx);
        // A dock that does not exist is not collapsible, so this covers the
        // old `left_dock.is_some()` test too.
        if !area.is_dock_collapsible(placement) {
            return None;
        }

        let designated = match placement {
            DockPlacement::Left => area
                .layout(DockPlacement::Center)
                .and_then(|tree| left_top_group(tree.root())),
            DockPlacement::Right => area
                .layout(DockPlacement::Center)
                .and_then(|tree| right_top_group(tree.root())),
            DockPlacement::Bottom => area
                .layout(DockPlacement::Bottom)
                .and_then(|tree| left_top_group(tree.root())),
            DockPlacement::Center => None,
        };
        if designated != Some(group.node()) {
            return None;
        }

        let is_open = area.is_dock_open(placement);
        let icon = match (placement, is_open) {
            (DockPlacement::Left, true) => IconName::PanelLeft,
            (DockPlacement::Left, false) => IconName::PanelLeftOpen,
            (DockPlacement::Right, true) => IconName::PanelRight,
            (DockPlacement::Right, false) => IconName::PanelRightOpen,
            (DockPlacement::Bottom, true) => IconName::PanelBottom,
            (DockPlacement::Bottom, false) => IconName::PanelBottomOpen,
            (DockPlacement::Center, _) => return None,
        };

        let area = self.shared.area().clone();
        Some(
            Button::new(SharedString::from(format!("toggle-dock:{:?}", placement)))
                .icon(icon)
                .xsmall()
                .ghost()
                .tab_stop(false)
                .tooltip(match is_open {
                    true => t!("Dock.Collapse"),
                    false => t!("Dock.Expand"),
                })
                .debug_selector(move || format!("{DOCK_TOGGLE_SELECTOR}-{placement:?}"))
                .on_click(move |_, window, cx| {
                    _ = area.update(cx, |area, cx| {
                        toggle_dock_by_user(area, placement, window, cx)
                    });
                }),
        )
    }

    /// The trailing controls: the panel's own buttons, the zoom affordance,
    /// and the ellipsis menu.
    fn render_toolbar(
        &self,
        group: &TabGroupContext,
        window: &mut Window,
        cx: &mut App,
    ) -> impl IntoElement {
        if group.is_collapsed() {
            return div();
        }

        let zoomed = group.is_zoomed();
        let handle = group.active_panel().and_then(PanelHandle::of);
        let control = zoom_control(group, cx);
        let toolbar_zoom = control.is_some_and(|control| control.toolbar_visible());
        let menu_zoom = control.is_some_and(|control| control.menu_visible());
        let closable = group.is_closable();
        let buttons = handle.and_then(|handle| handle.toolbar_buttons(window, cx));
        let panel = handle.map(|handle| handle.panel());

        h_flex()
            .gap_1()
            .occlude()
            .when_some(buttons, |this, buttons| {
                this.children(
                    buttons
                        .into_iter()
                        .map(|button| button.xsmall().ghost().tab_stop(false)),
                )
            })
            .when_some(
                match (zoomed, toolbar_zoom) {
                    (true, _) => Some(("zoom-out", IconName::Minimize, t!("Dock.Zoom Out"))),
                    (false, true) => Some(("zoom-in", IconName::Maximize, t!("Dock.Zoom In"))),
                    (false, false) => None,
                },
                |this, (id, icon, tooltip)| {
                    this.child(
                        Button::new(id)
                            .icon(icon)
                            .xsmall()
                            .ghost()
                            .tab_stop(false)
                            .tooltip_with_action(tooltip, &ToggleZoom, None)
                            .selected(zoomed)
                            // Whether this button was drawn is the whole of
                            // the `zoom_control` decision, and there is no
                            // other way to ask a drawn tree about it. A no-op
                            // outside test builds; see `debug_selector`.
                            .debug_selector(|| ZOOM_CONTROL_SELECTOR.to_string())
                            .on_click({
                                let group = group.clone();
                                move |_, window, cx| group.toggle_zoom(window, cx)
                            }),
                    )
                },
            )
            .child(
                Button::new("menu")
                    .icon(IconName::Ellipsis)
                    .xsmall()
                    .ghost()
                    .tab_stop(false)
                    .dropdown_menu(move |menu, window, cx| {
                        menu.when_some(panel.clone(), |menu, panel| {
                            panel.dropdown_menu(menu, window, cx)
                        })
                        .separator()
                        .menu_with_disabled(
                            match zoomed {
                                true => t!("Dock.Zoom Out"),
                                false => t!("Dock.Zoom In"),
                            },
                            Box::new(ToggleZoom),
                            !menu_zoom,
                        )
                        .when(closable, |menu| {
                            menu.separator()
                                .menu(t!("Dock.Close"), Box::new(ClosePanel))
                        })
                    })
                    .anchor(Anchor::TopRight),
            )
    }

    /// The one-panel title bar: no tabs, just the title and the controls.
    fn render_title(
        &self,
        group: &TabGroupContext,
        ix: usize,
        window: &mut Window,
        cx: &mut App,
    ) -> AnyElement {
        let panel = &group.panels()[ix];
        let left_button = self.dock_toggle_button(DockPlacement::Left, group, cx);
        let bottom_button = self.dock_toggle_button(DockPlacement::Bottom, group, cx);
        let right_button = self.dock_toggle_button(DockPlacement::Right, group, cx);
        let has_leading = left_button.is_some() || bottom_button.is_some();
        let handle = PanelHandle::of(panel);
        let title_style = handle.and_then(|handle| handle.title_style(cx));
        let drag = tab_drag(group, ix, cx);

        h_flex()
            .justify_between()
            .h(px(30.))
            .py_2()
            .pl_3()
            .pr_2()
            .when(left_button.is_some(), |this| this.pl_2())
            .when(right_button.is_some(), |this| this.pr_2())
            .when_some(title_style, |this, style| {
                this.bg(style.background).text_color(style.foreground)
            })
            .when(has_leading, |this| {
                this.child(
                    h_flex()
                        .flex_shrink_0()
                        .mr_1()
                        .gap_1()
                        .children(left_button)
                        .children(bottom_button),
                )
            })
            .child(
                div()
                    .id("tab")
                    .flex_1()
                    .min_w_16()
                    .overflow_hidden()
                    .text_ellipsis()
                    .whitespace_nowrap()
                    .child(panel_title(panel, window, cx))
                    .when_some(drag, |this, drag| {
                        this.on_drag(drag, {
                            let panel = panel.clone();
                            move |drag, offset, _, cx| {
                                cx.stop_propagation();
                                drag.set_drag_offset(offset);
                                drag.set_preview_size(DRAG_PREVIEW_SIZE);
                                cx.new(|_| DragPanelPreview {
                                    panel: panel.clone(),
                                })
                            }
                        })
                    }),
            )
            .children(handle.and_then(|handle| handle.title_suffix(window, cx)))
            .child(
                h_flex()
                    .flex_shrink_0()
                    .ml_1()
                    .gap_1()
                    .child(self.render_toolbar(group, window, cx))
                    .children(right_button),
            )
            .into_any_element()
    }

    /// The full tab bar.
    fn render_tabs(
        &self,
        group: &TabGroupContext,
        window: &mut Window,
        cx: &mut App,
    ) -> AnyElement {
        let left_button = self.dock_toggle_button(DockPlacement::Left, group, cx);
        let bottom_button = self.dock_toggle_button(DockPlacement::Bottom, group, cx);
        let right_button = self.dock_toggle_button(DockPlacement::Right, group, cx);
        let has_leading = left_button.is_some() || bottom_button.is_some();
        let is_bottom_dock = bottom_button.is_some();
        let collapsed = group.is_collapsed();

        let droppable = group.is_droppable();
        let tabs_count = group.panels().len();
        let active_ix = group.active_ix();
        let displayed = group.active_panel().map(|panel| panel.panel_id(cx));
        let visible: Vec<usize> = group
            .panels()
            .iter()
            .enumerate()
            .filter(|(_, panel)| panel.visible(cx))
            .map(|(ix, _)| ix)
            .collect();
        let displayed_ix = displayed.and_then(|displayed| {
            group
                .panels()
                .iter()
                .position(|panel| panel.panel_id(cx) == displayed)
        });

        // Bring a newly displayed tab into view. The group owns selection now,
        // so the skin notices the change rather than being told about it.
        if self.last_active_ix.replace(Some(active_ix)) != Some(active_ix) {
            if let Some(visible_ix) = visible.iter().position(|ix| *ix == active_ix) {
                self.scroll_handle.scroll_to_item(visible_ix);
            }
        }

        TabBar::new("tab-bar")
            .track_scroll(&self.scroll_handle)
            .when(has_leading, |this| {
                this.prefix(
                    h_flex()
                        .items_center()
                        .top_0()
                        // Right -1 for avoid border overlap with the first tab
                        .right(-px(1.))
                        .border_r_1()
                        .border_b_1()
                        .h_full()
                        .border_color(cx.theme().border)
                        .bg(cx.theme().tokens.tab_bar)
                        .px_2()
                        .children(left_button)
                        .children(bottom_button),
                )
            })
            .children(
                visible
                    .into_iter()
                    .map(|ix| {
                        let panel = &group.panels()[ix];
                        let handle = PanelHandle::of(panel);
                        let drag = tab_drag(group, ix, cx);

                        Tab::new()
                            .ix(ix)
                            .debug_selector(move || format!("{TAB_SELECTOR}-{ix}"))
                            .tab_bar_prefix(has_leading)
                            .map(|this| match handle.and_then(|handle| handle.tab_name(cx)) {
                                Some(tab_name) => this.child(tab_name),
                                None => this.child(panel_title(panel, window, cx)),
                            })
                            // Per-tab close (X) button. The gate mirrors
                            // `TabGroup::close_panel`, plus `!collapsed`, since a
                            // collapsed strip is a way back in, not a place to
                            // close. Stops propagation so the click closes by id
                            // without also selecting the tab.
                            .when(
                                !collapsed
                                    && self.shared.close_button_visible.get()
                                    && group.is_panel_closable(panel.panel_id(cx), cx),
                                |this| {
                                    this.suffix(
                                        Button::new(("close-tab", ix))
                                            .icon(IconName::Close)
                                            .xsmall()
                                            // The regular ghost hover matches the
                                            // inactive tab bar background in the
                                            // default theme. Use a stronger theme
                                            // surface while keeping a transparent
                                            // idle background and no border.
                                            .custom(
                                                ButtonCustomVariant::new(cx)
                                                    .foreground(cx.theme().secondary_foreground)
                                                    .hover(*cx.theme().tokens.secondary_hover)
                                                    .active(*cx.theme().tokens.secondary_active),
                                            )
                                            // The 20px XS button has a 12px icon:
                                            // 4px inside plus 8px outside matches
                                            // the label's 12px leading padding.
                                            // Offset the label's own 12px right
                                            // padding and the tab's 4px gap so the
                                            // text-to-icon distance is also 12px.
                                            .ml(-px(8.))
                                            .mr_2()
                                            .tab_stop(false)
                                            .debug_selector(|| CLOSE_BUTTON_SELECTOR.to_string())
                                            .on_click({
                                                let group = group.clone();
                                                let panel_id = panel.panel_id(cx);
                                                move |_, window, cx| {
                                                    cx.stop_propagation();
                                                    group.close(panel_id, window, cx);
                                                }
                                            }),
                                    )
                                },
                            )
                            // A collapsed group shows no tab as active: the
                            // strip is a way back in, not a selection. The
                            // comparison is against the panel on screen, not
                            // the stored index: a hidden displayed tab falls
                            // back to the first visible one.
                            .selected(!collapsed && Some(ix) == displayed_ix)
                            .on_click({
                                let group = group.clone();
                                let area = self.shared.area().clone();
                                let last_active_ix = self.last_active_ix.clone();
                                move |_, window, cx| {
                                    // The tab bar reveals a clicked tab itself,
                                    // so the change must not snap it into view.
                                    last_active_ix.set(Some(ix));
                                    group.select_tab(ix, window, cx);

                                    // Clicking the strip of a collapsed bottom
                                    // dock is how it is opened again.
                                    if is_bottom_dock && collapsed {
                                        _ = area.update(cx, |area, cx| {
                                            toggle_dock_by_user(
                                                area,
                                                DockPlacement::Bottom,
                                                window,
                                                cx,
                                            )
                                        });
                                    }
                                }
                            })
                            // A collapsed group is a strip of tabs with no
                            // content, so there is nothing to rearrange in it.
                            .when(!collapsed, |this| {
                                this.when_some(drag, |this, drag| {
                                    this.on_drag(drag, {
                                        let panel = panel.clone();
                                        move |drag, offset, _, cx| {
                                            cx.stop_propagation();
                                            drag.set_drag_offset(offset);
                                            drag.set_preview_size(DRAG_PREVIEW_SIZE);
                                            cx.new(|_| DragPanelPreview {
                                                panel: panel.clone(),
                                            })
                                        }
                                    })
                                })
                                .when(droppable, |this| {
                                    this.drag_over::<DragPanel>(|this, _, _, cx| {
                                        this.rounded_l_none()
                                            .border_l_2()
                                            .border_r_0()
                                            .border_color(cx.theme().drag_border)
                                    })
                                    .on_drop({
                                        let group = group.clone();
                                        move |drag: &DragPanel, window, cx| {
                                            group.drop_panel(
                                                drag.clone(),
                                                Some(ix),
                                                true,
                                                window,
                                                cx,
                                            );
                                        }
                                    })
                                    .drag_over::<AnyDrag>(|this, _, _, cx| {
                                        this.rounded_l_none()
                                            .border_l_2()
                                            .border_r_0()
                                            .border_color(cx.theme().drag_border)
                                    })
                                    .on_drop({
                                        let group = group.clone();
                                        move |item: &AnyDrag, window, cx| {
                                            group.drop_item(item.clone(), None, window, cx);
                                        }
                                    })
                                })
                            })
                    })
                    .collect::<Vec<_>>(),
            )
            .last_empty_space(
                // Empty space so a panel can be moved past the last tab.
                div()
                    .id("tab-bar-empty-space")
                    .h_full()
                    .flex_grow_1()
                    .min_w_16()
                    .when(droppable, |this| {
                        this.drag_over::<DragPanel>(|this, _, _, cx| {
                            this.bg(cx.theme().tokens.drop_target)
                        })
                        .on_drop({
                            let group = group.clone();
                            let node = group.node();
                            move |drag: &DragPanel, window, cx| {
                                // A panel dropped past its own last tab lands
                                // in the final slot; one from elsewhere is
                                // appended in the background.
                                let ix = (drag.source() == node).then(|| tabs_count - 1);
                                group.drop_panel(drag.clone(), ix, false, window, cx);
                            }
                        })
                        .drag_over::<AnyDrag>(|this, _, _, cx| {
                            this.bg(cx.theme().tokens.drop_target)
                        })
                        .on_drop({
                            let group = group.clone();
                            move |item: &AnyDrag, window, cx| {
                                group.drop_item(item.clone(), None, window, cx);
                            }
                        })
                    }),
            )
            .when(!collapsed, |this| {
                this.suffix(
                    h_flex()
                        .items_center()
                        .top_0()
                        .right_0()
                        .border_l_1()
                        .border_b_1()
                        .h_full()
                        .border_color(cx.theme().border)
                        .bg(cx.theme().tokens.tab_bar)
                        .px_2()
                        .gap_1()
                        .children(
                            group
                                .active_panel()
                                .and_then(PanelHandle::of)
                                .and_then(|handle| handle.title_suffix(window, cx)),
                        )
                        .child(self.render_toolbar(group, window, cx))
                        .children(right_button),
                )
            })
            .into_any_element()
    }
}

impl TabGroupRenderer for TabGroupSkin {
    fn frame(&self, group: &TabGroupContext, _: &mut Window, cx: &mut App) -> Stateful<Div> {
        let control = zoom_control(group, cx);

        // The column, the fill and the clip are base's now, applied around
        // this. What is left is the background and the two actions.
        div()
            .id("tab-panel")
            .bg(cx.theme().tokens.background)
            // A collapsed group is a strip of tabs with no content, and the
            // actions act on content. The old dock gated them the same way.
            .when(!group.is_collapsed(), |this| {
                this.on_action({
                    let group = group.clone();
                    move |_: &ToggleZoom, window, cx| {
                        // The affordance decides the control, so a panel that
                        // offers none is not zoomed *in* by the keybinding
                        // either. Zooming out is never refused: a panel that
                        // stopped offering the control while zoomed would
                        // otherwise strand the user with no way back.
                        if !group.is_zoomed() && control.is_none() {
                            return;
                        }
                        group.toggle_zoom(window, cx);
                    }
                })
                .on_action({
                    let group = group.clone();
                    move |_: &ClosePanel, window, cx| {
                        let Some(panel) = group.active_panel() else {
                            return;
                        };
                        let panel = panel.panel_id(cx);
                        group.close(panel, window, cx);
                    }
                })
            })
    }

    fn content_frame(
        &self,
        group: &TabGroupContext,
        _: &mut Window,
        cx: &mut App,
    ) -> Stateful<Div> {
        let padded = group.panels().len() > 1
            && group
                .active_panel()
                .and_then(PanelHandle::of)
                .is_none_or(|handle| handle.inner_padding(cx));

        // The fill and the collapsed-group exception are base's; the padding
        // is this skin's, and is the only reason this hook is implemented.
        div().id("active-panel").when(padded, |this| this.pt_2())
    }

    fn render_tab_bar(
        &self,
        group: &TabGroupContext,
        window: &mut Window,
        cx: &mut App,
    ) -> AnyElement {
        let visible: Vec<usize> = group
            .panels()
            .iter()
            .enumerate()
            .filter(|(_, panel)| panel.visible(cx))
            .map(|(ix, _)| ix)
            .collect();

        match visible.as_slice() {
            [] => Empty.into_any_element(),
            [ix] if self.shared.panel_style() == PanelStyle::Auto => {
                // A panel that draws its own chrome declines the title bar.
                let panel = &group.panels()[*ix];
                if PanelHandle::of(panel).is_some_and(|handle| !handle.title_bar(cx)) {
                    return Empty.into_any_element();
                }
                self.render_title(group, *ix, window, cx)
            }
            _ => self.render_tabs(group, window, cx),
        }
    }

    fn render_active_panel(
        &self,
        panel: AnyView,
        group: &TabGroupContext,
        _: &mut Window,
        _: &mut App,
    ) -> AnyElement {
        if group.is_collapsed() {
            return Empty.into_any_element();
        }

        div()
            .id("tab-content")
            .overflow_y_scroll()
            .overflow_x_hidden()
            .flex_1()
            .child(panel.cached(StyleRefinement::default().absolute().size_full()))
            .into_any_element()
    }

    fn render_drop_indicator(
        &self,
        indicator: DropIndicator,
        window: &mut Window,
        cx: &mut App,
    ) -> Option<AnyElement> {
        let to = indicator.to();
        // The placeholder chases the drop it would land in. Its rect was
        // previously replayed from the drag source on every epoch, so crossing
        // several drop zones in one drag restarted the walk at each one; the
        // springs carry it through instead, and the element no longer needs an
        // outer frame to hold the destination while an inner one walks to it.
        let id = "drop-placeholder";
        let placeholder_spring = cx.theme().motion_tokens().spring_move.with_epsilon(0.5);
        let left = spring((id, "left"), to.origin().x, placeholder_spring, window, cx);
        let top = spring((id, "top"), to.origin().y, placeholder_spring, window, cx);
        let width = spring(
            (id, "width"),
            to.size().width,
            placeholder_spring,
            window,
            cx,
        );
        let height = spring(
            (id, "height"),
            to.size().height,
            placeholder_spring,
            window,
            cx,
        );

        Some(
            div()
                .absolute()
                .bg(cx.theme().tokens.drop_target)
                .left(left)
                .top(top)
                .w(width)
                .h(height)
                .into_any_element(),
        )
    }
}

#[cfg(test)]
mod tests {
    use std::{
        cell::{Cell, RefCell},
        sync::Arc,
    };

    use gpui::{
        Entity, EventEmitter, FocusHandle, Focusable, Modifiers, MouseButton, Pixels,
        TestAppContext, VisualTestContext,
    };
    use gpui_base::dock::{DockArea, DockAreaRenderer, DockLayout, DockPlacement, PanelEvent};

    use super::*;
    use crate::{
        ElementExt as _,
        dock::{
            DockSkin, Panel, panel_handle,
            test_support::{HideableProbe, MeasuredProbe},
        },
    };

    struct Probe {
        focus_handle: FocusHandle,
    }

    impl Probe {
        fn new(cx: &mut App) -> Entity<Self> {
            cx.new(|cx| Self {
                focus_handle: cx.focus_handle(),
            })
        }
    }

    impl gpui_base::dock::Panel for Probe {
        fn panel_name(&self) -> &'static str {
            "Probe"
        }
    }

    impl Panel for Probe {}
    impl EventEmitter<PanelEvent> for Probe {}

    impl Focusable for Probe {
        fn focus_handle(&self, _: &App) -> FocusHandle {
            self.focus_handle.clone()
        }
    }

    impl Render for Probe {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            Empty
        }
    }

    /// Draws nothing, but runs the real gates the skin's tab bar runs and
    /// records what they decided for every group it was asked to draw.
    #[derive(Default)]
    struct Recorded {
        /// One entry per tab: whether its tab would start a drag.
        draggable: Vec<bool>,
    }

    struct Recorder {
        log: Rc<RefCell<Recorded>>,
    }

    impl TabGroupRenderer for Recorder {
        fn render_tab_bar(
            &self,
            group: &TabGroupContext,
            _: &mut Window,
            cx: &mut App,
        ) -> AnyElement {
            let mut log = self.log.borrow_mut();
            for ix in 0..group.panels().len() {
                log.draggable.push(tab_drag(group, ix, cx).is_some());
            }
            Empty.into_any_element()
        }
    }

    impl DockAreaRenderer for Recorder {
        fn frame(&self, _: &mut Window, _: &mut App) -> Stateful<Div> {
            div().id("recorder").size_full()
        }

        fn tab_group_renderer(&self) -> Rc<dyn TabGroupRenderer> {
            Rc::new(Recorder {
                log: self.log.clone(),
            })
        }
    }

    fn recording_area(
        cx: &mut TestAppContext,
    ) -> (
        Entity<DockArea>,
        Rc<RefCell<Recorded>>,
        &mut VisualTestContext,
    ) {
        cx.update(|cx| {
            crate::init(cx);
        });
        let log = Rc::new(RefCell::new(Recorded::default()));
        let renderer = Rc::new(Recorder { log: log.clone() });
        let (area, cx) = cx.add_window_view(|window, cx| {
            DockArea::new("skin", None, window, cx).with_renderer(renderer)
        });
        (area, log, cx)
    }

    /// The gate carried forward from the old `TabPanel::render`, which wrapped
    /// `on_drag` in `.when(state.draggable, ..)`. Base does not enforce it:
    /// `TabGroupContext::drag_panel` answers for any tab in range.
    #[gpui::test]
    fn the_last_group_in_a_dock_offers_no_drag(cx: &mut TestAppContext) {
        let (area, log, cx) = recording_area(cx);

        cx.update(|window, cx| {
            let layout = DockLayout::tabs().panel_view(panel_handle(Probe::new(cx)), cx);
            area.update(cx, |area, cx| area.set_center(layout, window, cx));
        });
        cx.run_until_parked();
        log.borrow_mut().draggable.clear();
        cx.update(|window, cx| window.draw(cx).clear(cx));

        assert_eq!(
            log.borrow().draggable,
            vec![false],
            "the only visible panel in the dock has nowhere to go, so its tab \
             must not start a drag"
        );
    }

    #[gpui::test]
    fn a_group_beside_another_offers_a_drag(cx: &mut TestAppContext) {
        let (area, log, cx) = recording_area(cx);

        cx.update(|window, cx| {
            let layout = DockLayout::h_split()
                .child(
                    DockLayout::tabs().panel_view(panel_handle(Probe::new(cx)), cx),
                    None,
                )
                .child(
                    DockLayout::tabs().panel_view(panel_handle(Probe::new(cx)), cx),
                    None,
                );
            area.update(cx, |area, cx| area.set_center(layout, window, cx));
        });
        cx.run_until_parked();
        log.borrow_mut().draggable.clear();
        cx.update(|window, cx| window.draw(cx).clear(cx));

        assert_eq!(
            log.borrow().draggable,
            vec![true, true],
            "each group has somewhere to go, so both tabs start a drag"
        );
    }

    /// A panel that allows zooming and asks for the control in the toolbar.
    /// `Probe`'s default is `PanelControl::Menu`, which draws no button.
    struct ToolbarZoomProbe {
        focus_handle: FocusHandle,
    }

    impl ToolbarZoomProbe {
        fn new(cx: &mut App) -> Entity<Self> {
            cx.new(|cx| Self {
                focus_handle: cx.focus_handle(),
            })
        }
    }

    impl gpui_base::dock::Panel for ToolbarZoomProbe {
        fn panel_name(&self) -> &'static str {
            "ToolbarZoomProbe"
        }
    }

    impl Panel for ToolbarZoomProbe {
        fn zoom_control(&self, _: &App) -> Option<PanelControl> {
            Some(PanelControl::Toolbar)
        }
    }

    impl EventEmitter<PanelEvent> for ToolbarZoomProbe {}

    impl Focusable for ToolbarZoomProbe {
        fn focus_handle(&self, _: &App) -> FocusHandle {
            self.focus_handle.clone()
        }
    }

    impl Render for ToolbarZoomProbe {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            Empty
        }
    }

    /// A panel that offers no zoom control but leaves base's `zoomable`
    /// default alone. Withholding the control is meant to be enough.
    struct NoControlProbe {
        focus_handle: FocusHandle,
    }

    impl NoControlProbe {
        fn new(cx: &mut App) -> Entity<Self> {
            cx.new(|cx| Self {
                focus_handle: cx.focus_handle(),
            })
        }
    }

    impl gpui_base::dock::Panel for NoControlProbe {
        fn panel_name(&self) -> &'static str {
            "NoControlProbe"
        }
    }

    impl Panel for NoControlProbe {
        fn zoom_control(&self, _: &App) -> Option<PanelControl> {
            None
        }
    }

    impl EventEmitter<PanelEvent> for NoControlProbe {}

    impl Focusable for NoControlProbe {
        fn focus_handle(&self, _: &App) -> FocusHandle {
            self.focus_handle.clone()
        }
    }

    impl Render for NoControlProbe {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            Empty
        }
    }

    /// A panel that says "never zoom" in base's half but still names a place
    /// for the control in this crate's half.
    struct UnzoomableProbe {
        focus_handle: FocusHandle,
    }

    impl gpui_base::dock::Panel for UnzoomableProbe {
        fn panel_name(&self) -> &'static str {
            "UnzoomableProbe"
        }

        fn zoomable(&self, _: &App) -> bool {
            false
        }
    }

    impl Panel for UnzoomableProbe {
        fn zoom_control(&self, _: &App) -> Option<PanelControl> {
            Some(PanelControl::Toolbar)
        }
    }

    impl EventEmitter<PanelEvent> for UnzoomableProbe {}

    impl Focusable for UnzoomableProbe {
        fn focus_handle(&self, _: &App) -> FocusHandle {
            self.focus_handle.clone()
        }
    }

    impl Render for UnzoomableProbe {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            Empty
        }
    }

    /// Draw one panel through the real [`DockSkin`] and report whether its tab
    /// bar offered a zoom control.
    ///
    /// The real skin, not a recorder: the bug this guards is `render_toolbar`
    /// asking only half the question, so a test that calls `zoom_control`
    /// itself would pass with the bug in place.
    fn drew_zoom_control(
        cx: &mut TestAppContext,
        panel: impl FnOnce(&mut App) -> Arc<dyn gpui_base::dock::PanelView>,
    ) -> bool {
        cx.update(|cx| {
            crate::init(cx);
        });
        let (area, cx) = cx.add_window_view(|window, cx| {
            let skin = DockSkin::new(cx);
            DockArea::new("skin", None, window, cx).with_renderer(skin)
        });

        cx.update(|window, cx| {
            let layout = DockLayout::tabs().panel_view(panel(cx), cx);
            area.update(cx, |area, cx| area.set_center(layout, window, cx));
        });
        cx.run_until_parked();
        cx.update(|window, cx| window.draw(cx).clear(cx));
        cx.debug_bounds(ZOOM_CONTROL_SELECTOR).is_some()
    }

    /// The two halves of the old `zoomable()` can now disagree, and base is
    /// the one that decides. A control drawn against base's refusal is dead:
    /// pressing it does nothing.
    #[gpui::test]
    fn a_panel_base_will_not_zoom_gets_no_zoom_control(cx: &mut TestAppContext) {
        let drew = drew_zoom_control(cx, |cx| {
            panel_handle(cx.new(|cx| UnzoomableProbe {
                focus_handle: cx.focus_handle(),
            }))
        });

        assert!(
            !drew,
            "the panel names a place for the control, but base refuses the zoom"
        );
    }

    /// The other half: a panel that allows zoom and asks for a toolbar control
    /// gets one drawn. Without this the test above would also pass a skin that
    /// never draws a zoom control at all.
    #[gpui::test]
    fn a_zoomable_panel_gets_its_zoom_control(cx: &mut TestAppContext) {
        let drew = drew_zoom_control(cx, |cx| panel_handle(ToolbarZoomProbe::new(cx)));

        assert!(
            drew,
            "a zoomable panel asking for a toolbar control gets one"
        );
    }

    /// The centre and the bottom dock share the centre column, and both get
    /// height.
    ///
    /// `DockSkin::center_frame` is a flex column holding the centre's root
    /// split and the bottom dock, and the centre's split frame sits between
    /// them. This pins that the frame carries a size at all: strip
    /// `split_frame` of both `size_full` and `flex_1` and every panel here
    /// measures zero. It does not pin *which* of the two does the work —
    /// either alone passes.
    #[gpui::test]
    fn the_centre_and_the_bottom_dock_share_the_column(cx: &mut TestAppContext) {
        cx.update(|cx| {
            crate::init(cx);
        });
        let centre = Rc::new(Cell::new(px(0.)));
        let bottom = Rc::new(Cell::new(px(0.)));
        let (area, cx) = cx.add_window_view(|window, cx| {
            let skin = DockSkin::new(cx);
            DockArea::new("skin", None, window, cx).with_renderer(skin)
        });

        let (centre_probe, bottom_probe) = (centre.clone(), bottom.clone());
        cx.update(|window, cx| {
            let centre_panel = MeasuredProbe::new(centre_probe, cx);
            let bottom_panel = MeasuredProbe::new(bottom_probe, cx);
            area.update(cx, |area, cx| {
                // A split inside a split, so the *nested* `split_frame` — the
                // one that sits inside a `resizable_panel` — is exercised too,
                // not only the centre's root.
                area.set_center(
                    DockLayout::v_split().child(
                        DockLayout::h_split().child(
                            DockLayout::tabs().panel_view(panel_handle(centre_panel), cx),
                            None,
                        ),
                        None,
                    ),
                    window,
                    cx,
                );
                area.set_dock(
                    DockPlacement::Bottom,
                    DockLayout::tabs().panel_view(panel_handle(bottom_panel), cx),
                    window,
                    cx,
                );
                area.set_dock_size(DockPlacement::Bottom, px(200.), window, cx);
            });
        });
        cx.run_until_parked();
        cx.update(|window, cx| window.draw(cx).clear(cx));

        let window_height = cx.update(|window, _| window.viewport_size().height);
        assert!(
            centre.get() > px(0.),
            "the centre panel must receive height; it got {:?}",
            centre.get()
        );
        assert!(
            bottom.get() > px(0.),
            "the bottom dock's panel must receive height; it got {:?}",
            bottom.get()
        );
        assert!(
            centre.get() < window_height - px(150.),
            "the centre must give the 200px bottom dock its share; the centre \
             got {:?} of {window_height:?}",
            centre.get()
        );
    }

    /// Whichever slots of a split are hidden, the drawn ones fill it.
    ///
    /// `render_node` pins every slot but one to a fixed size and lets the
    /// remaining one absorb whatever the container has spare. Picking that
    /// slot by tree position alone picks a hidden one whenever the trailing
    /// container's panels are all hidden — nothing draws there, nothing
    /// grows, and the split stops short of its frame, showing a band of the
    /// frame's own background under the last visible panel. Hiding a slot is
    /// an everyday event: a panel that is only meaningful for some symbols
    /// answers `visible` with `false` for the rest.
    ///
    /// Every subset is covered because the defect is positional: only the
    /// cases that hide the trailing slot fail, and a test that hid one fixed
    /// slot would pass against a fix that only special-cased that slot.
    #[gpui::test]
    fn a_split_fills_its_container_whichever_slots_are_hidden(cx: &mut TestAppContext) {
        cx.update(|cx| {
            crate::init(cx);
        });
        let heights: Vec<Rc<Cell<Pixels>>> = (0..3).map(|_| Rc::new(Cell::new(px(0.)))).collect();
        let (area, cx) = cx.add_window_view(|window, cx| {
            let skin = DockSkin::new(cx);
            DockArea::new("skin", None, window, cx).with_renderer(skin)
        });

        let slots = heights.clone();
        let probes = cx.update(|window, cx| {
            let probes: Vec<_> = slots
                .iter()
                .map(|height| HideableProbe::new(height.clone(), cx))
                .collect();
            area.update(cx, |area, cx| {
                area.set_dock(
                    DockPlacement::Right,
                    probes.iter().zip([260., 320., 200.]).fold(
                        DockLayout::v_split(),
                        |split, (probe, size)| {
                            split.child(
                                DockLayout::tabs().panel_view(panel_handle(probe.clone()), cx),
                                Some(px(size)),
                            )
                        },
                    ),
                    window,
                    cx,
                );
                area.set_dock_size(DockPlacement::Right, px(380.), window, cx);
            });
            probes
        });
        cx.run_until_parked();
        let draw = |cx: &mut VisualTestContext| {
            cx.update(|window, _| window.refresh());
            cx.update(|window, cx| window.draw(cx).clear(cx));
            cx.update(|window, cx| window.draw(cx).clear(cx));
        };
        draw(cx);

        let dock_height = cx.update(|window, _| window.viewport_size().height);
        // Each slot spends a tab bar out of its height and the probe under it
        // measures the rest, so the drawn slots account for the whole dock
        // once one tab bar per drawn slot is added back.
        let drawn: Pixels = heights.iter().map(|height| height.get()).sum();
        let bar = (dock_height - drawn) / 3.;
        assert!(
            bar > px(0.) && bar < px(60.),
            "the three slots fill the dock to begin with, one tab bar each; \
             that leaves {bar:?} per slot of {dock_height:?}"
        );

        // Every subset except "all three hidden", which gives the whole node
        // up to *its* parent and so has no container of its own to fill.
        for hidden in 1..0b111u8 {
            let shown = (0..3).filter(|slot| hidden & (1 << slot) == 0);
            cx.update(|_, cx| {
                for (slot, probe) in probes.iter().enumerate() {
                    // A sentinel, so a slot that stopped drawing is not read
                    // as one that kept the height it had.
                    heights[slot].set(px(-1.));
                    probe.update(cx, |probe, cx| {
                        probe.set_visible(hidden & (1 << slot) == 0, cx)
                    });
                }
            });
            cx.run_until_parked();
            draw(cx);

            let mut count = 0;
            let mut total = px(0.);
            for slot in shown {
                assert_ne!(
                    heights[slot].get(),
                    px(-1.),
                    "hiding {hidden:03b}: slot {slot} is shown and must draw"
                );
                count += 1;
                total += heights[slot].get();
            }
            let empty = dock_height - total - bar * count as f32;
            assert!(
                empty.abs() < px(1.),
                "hiding {hidden:03b}: the drawn slots must take the hidden \
                 ones' space between them; they left {empty:?} of \
                 {dock_height:?} empty"
            );
        }
    }

    /// The old dock installed `ToggleZoom` and `ClosePanel` on the tab panel
    /// itself; base installs neither, so the skin's `frame` is the only place
    /// the keybindings reach.
    #[gpui::test]
    fn the_zoom_action_reaches_the_group_through_the_skin(cx: &mut TestAppContext) {
        cx.update(|cx| {
            crate::init(cx);
        });
        let (area, cx) = cx.add_window_view(|window, cx| {
            let skin = DockSkin::new(cx);
            DockArea::new("skin", None, window, cx).with_renderer(skin)
        });

        let panel = cx.update(|window, cx| {
            let panel = Probe::new(cx);
            let layout = DockLayout::tabs().panel_view(panel_handle(panel.clone()), cx);
            area.update(cx, |area, cx| area.set_center(layout, window, cx));
            panel
        });
        cx.run_until_parked();
        cx.update(|window, cx| {
            panel.read(cx).focus_handle(cx).focus(window, cx);
        });
        cx.run_until_parked();

        assert_eq!(cx.read(|cx| area.read(cx).is_zoomed()), false);
        cx.dispatch_action(ToggleZoom);
        cx.run_until_parked();
        assert_eq!(
            cx.read(|cx| area.read(cx).is_zoomed()),
            true,
            "the skin's frame is what carries the ToggleZoom handler"
        );

        cx.dispatch_action(ToggleZoom);
        cx.run_until_parked();
        assert_eq!(cx.read(|cx| area.read(cx).is_zoomed()), false);
    }

    /// Withholding the control withholds the whole affordance, keybinding
    /// included. The two halves of the zoom question are asked in one place —
    /// the skin's `frame` — so a doc claiming the action gets through anyway
    /// would send a panel author looking for a second switch that does not
    /// exist.
    #[gpui::test]
    fn the_zoom_action_refuses_a_panel_that_offers_no_control(cx: &mut TestAppContext) {
        cx.update(|cx| {
            crate::init(cx);
        });
        let (area, cx) = cx.add_window_view(|window, cx| {
            let skin = DockSkin::new(cx);
            DockArea::new("skin", None, window, cx).with_renderer(skin)
        });

        let panel = cx.update(|window, cx| {
            let panel = NoControlProbe::new(cx);
            let layout = DockLayout::tabs().panel_view(panel_handle(panel.clone()), cx);
            area.update(cx, |area, cx| area.set_center(layout, window, cx));
            panel
        });
        cx.run_until_parked();
        cx.update(|window, cx| {
            panel.read(cx).focus_handle(cx).focus(window, cx);
        });
        cx.run_until_parked();

        cx.dispatch_action(ToggleZoom);
        cx.run_until_parked();
        assert_eq!(
            cx.read(|cx| area.read(cx).is_zoomed()),
            false,
            "no control means no zoom, however the zoom was asked for"
        );
    }

    /// The tab group's own frame has to be a flex column.
    ///
    /// gpui's default display is Block, and block layout ignores a child's
    /// `flex_grow`. With a plain `div()` frame the content region's `flex_1`
    /// does nothing, `#tab-content` sizes to its content, and its only child
    /// is the panel view positioned absolutely by `cached` — which
    /// contributes no content height. The whole chain resolves to zero and
    /// the dock draws a tab bar with nothing under it.
    ///
    /// This asserts a dimension, which the project's testing guidance
    /// discourages, because a zero-height content region is not a cosmetic
    /// difference: it is the panel not rendering at all, and no behavioral
    /// test in this crate can see it. `set_active` still fires, the layout
    /// still round-trips, and the window still opens.
    #[gpui::test]
    fn the_panel_content_region_gets_the_height_below_the_tab_bar(cx: &mut TestAppContext) {
        cx.update(|cx| {
            crate::init(cx);
        });
        let height = Rc::new(Cell::new(px(0.)));
        let (area, cx) = cx.add_window_view(|window, cx| {
            let skin = DockSkin::new(cx);
            DockArea::new("skin", None, window, cx).with_renderer(skin)
        });

        let measured = height.clone();
        cx.update(|window, cx| {
            let panel = MeasuredProbe::new(measured, cx);
            let layout = DockLayout::tabs().panel_view(panel_handle(panel), cx);
            area.update(cx, |area, cx| area.set_center(layout, window, cx));
        });
        cx.run_until_parked();
        cx.update(|window, cx| window.draw(cx).clear(cx));

        let window_height = cx.update(|window, _| window.viewport_size().height);
        let content = height.get();
        assert!(
            content > px(0.),
            "the panel must receive height; it got {content:?} in a {window_height:?} window"
        );
        // The tab bar is 30px and the padded content region adds none for a
        // single tab, so the panel should get nearly the whole window.
        assert!(
            content > window_height - px(60.),
            "the panel should fill what the tab bar leaves; it got {content:?} \
             of {window_height:?}"
        );
    }

    /// A collapsed group is a strip of tabs with no content, and the actions
    /// act on content. The old `TabPanel::bind_actions` gated them the same
    /// way.
    ///
    /// The bottom dock, not a side one: a closed left or right dock draws
    /// nothing at all, so it would pass this whether or not the gate exists.
    #[gpui::test]
    fn a_collapsed_dock_ignores_the_zoom_action(cx: &mut TestAppContext) {
        cx.update(|cx| {
            crate::init(cx);
        });
        let (area, cx) = cx.add_window_view(|window, cx| {
            let skin = DockSkin::new(cx);
            DockArea::new("skin", None, window, cx).with_renderer(skin)
        });

        let panel = cx.update(|window, cx| {
            let panel = Probe::new(cx);
            let layout = DockLayout::tabs().panel_view(panel_handle(panel.clone()), cx);
            area.update(cx, |area, cx| {
                area.set_dock(DockPlacement::Bottom, layout, window, cx);
                area.toggle_dock(DockPlacement::Bottom, window, cx);
            });
            panel
        });
        cx.run_until_parked();
        cx.update(|window, cx| {
            panel.read(cx).focus_handle(cx).focus(window, cx);
        });
        cx.run_until_parked();

        cx.dispatch_action(ToggleZoom);
        cx.run_until_parked();
        assert_eq!(
            cx.read(|cx| area.read(cx).is_zoomed()),
            false,
            "a collapsed group installs no action handler"
        );
    }

    /// A panel that carries its own chrome declines the one-panel title bar
    /// and gets the whole group.
    #[gpui::test]
    fn a_panel_without_a_title_bar_gets_the_whole_group(cx: &mut TestAppContext) {
        struct Chromeless {
            focus_handle: FocusHandle,
            height: Rc<Cell<Pixels>>,
        }

        impl gpui_base::dock::Panel for Chromeless {
            fn panel_name(&self) -> &'static str {
                "Chromeless"
            }
        }

        impl Panel for Chromeless {
            fn title_bar(&self, _: &App) -> bool {
                false
            }
        }

        impl EventEmitter<PanelEvent> for Chromeless {}

        impl Focusable for Chromeless {
            fn focus_handle(&self, _: &App) -> FocusHandle {
                self.focus_handle.clone()
            }
        }

        impl Render for Chromeless {
            fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
                let height = self.height.clone();
                div()
                    .size_full()
                    .on_prepaint(move |bounds, _, _| height.set(bounds.size.height))
            }
        }

        cx.update(|cx| crate::init(cx));

        let measure = |cx: &mut TestAppContext, chromeless: bool| -> Pixels {
            let height = Rc::new(Cell::new(px(0.)));
            let (area, cx) = cx.add_window_view(|window, cx| {
                let skin = DockSkin::new(cx);
                DockArea::new("skin", None, window, cx).with_renderer(skin)
            });
            let measured = height.clone();
            cx.update(|window, cx| {
                let panel: Arc<dyn gpui_base::dock::PanelView> = if chromeless {
                    panel_handle(cx.new(|cx| Chromeless {
                        focus_handle: cx.focus_handle(),
                        height: measured,
                    }))
                } else {
                    panel_handle(MeasuredProbe::new(measured, cx))
                };
                let layout = DockLayout::tabs().panel_view(panel, cx);
                area.update(cx, |area, cx| area.set_center(layout, window, cx));
            });
            cx.run_until_parked();
            cx.update(|window, cx| window.draw(cx).clear(cx));
            height.get()
        };

        let with_title = measure(cx, false);
        let without = measure(cx, true);
        assert!(with_title > px(0.), "the probe must have been drawn");
        assert_eq!(
            without,
            with_title + px(30.),
            "the 30px the title bar took go to the panel instead"
        );
    }

    /// Panel with a chosen `closable` that records whether it was made active.
    struct TabProbe {
        focus_handle: FocusHandle,
        closable: bool,
        activated: Rc<Cell<bool>>,
    }

    impl TabProbe {
        fn new(closable: bool, cx: &mut App) -> Entity<Self> {
            cx.new(|cx| Self {
                focus_handle: cx.focus_handle(),
                closable,
                activated: Rc::new(Cell::new(false)),
            })
        }
    }

    impl gpui_base::dock::Panel for TabProbe {
        fn panel_name(&self) -> &'static str {
            "TabProbe"
        }

        fn closable(&self, _: &App) -> bool {
            self.closable
        }

        fn set_active(&mut self, active: bool, _: &mut Window, _: &mut Context<Self>) {
            if active {
                self.activated.set(true);
            }
        }
    }

    impl Panel for TabProbe {}

    impl EventEmitter<PanelEvent> for TabProbe {}

    impl Focusable for TabProbe {
        fn focus_handle(&self, _: &App) -> FocusHandle {
            self.focus_handle.clone()
        }
    }

    impl Render for TabProbe {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            Empty
        }
    }

    /// Render a two-tab group through the real [`DockSkin`] and report whether
    /// the first tab drew a close button. The second tab is a non-closable
    /// filler (a lone panel draws no tab bar) that never draws one, so the
    /// probe is unambiguous.
    fn drew_close_button(cx: &mut TestAppContext, closable: bool, enabled: bool) -> bool {
        cx.update(|cx| crate::init(cx));
        let mut skin = None;
        let (area, cx) = cx.add_window_view(|window, cx| {
            let renderer = DockSkin::new(cx);
            skin = Some(renderer.clone());
            DockArea::new("skin", None, window, cx).with_renderer(renderer)
        });
        let skin = skin.expect("skin constructed with the area");
        if enabled {
            cx.update(|_, cx| skin.set_close_button_visible(true, cx));
        }
        cx.update(|window, cx| {
            let under_test = TabProbe::new(closable, cx);
            let filler = TabProbe::new(false, cx);
            let layout = DockLayout::tabs()
                .panel_view(panel_handle(under_test), cx)
                .panel_view(panel_handle(filler), cx);
            area.update(cx, |area, cx| area.set_center(layout, window, cx));
        });
        cx.run_until_parked();
        cx.update(|window, cx| window.draw(cx).clear(cx));
        let button = cx.debug_bounds(CLOSE_BUTTON_SELECTOR);
        if enabled && closable {
            assert_eq!(
                button.as_ref().map(|bounds| bounds.size.width),
                Some(px(20.)),
                "the close button keeps the standard XS hover target"
            );
        }
        button.is_some()
    }

    /// A closable panel's tab carries a close (X) button.
    #[gpui::test]
    fn a_closable_panel_gets_a_close_button(cx: &mut TestAppContext) {
        assert!(
            drew_close_button(cx, true, true),
            "a closable panel's tab must draw a close button"
        );
    }

    /// A non-closable panel draws no close button (the gate is real).
    #[gpui::test]
    fn a_non_closable_panel_gets_no_close_button(cx: &mut TestAppContext) {
        assert!(
            !drew_close_button(cx, false, true),
            "a panel that reports itself non-closable must draw no close button"
        );
    }

    #[gpui::test]
    fn close_buttons_are_off_by_default(cx: &mut TestAppContext) {
        assert!(!drew_close_button(cx, true, false));
    }

    #[gpui::test]
    fn close_button_visibility_updates_after_the_skin_setting_changes(cx: &mut TestAppContext) {
        cx.update(|cx| crate::init(cx));
        let mut skin = None;
        let (area, cx) = cx.add_window_view(|window, cx| {
            let renderer = DockSkin::new(cx);
            skin = Some(renderer.clone());
            DockArea::new("skin", None, window, cx).with_renderer(renderer)
        });
        let skin = skin.expect("skin constructed with the area");
        cx.update(|window, cx| {
            let panel = TabProbe::new(true, cx);
            let filler = TabProbe::new(false, cx);
            area.update(cx, |area, cx| {
                area.set_center(
                    DockLayout::tabs()
                        .panel_view(panel_handle(panel), cx)
                        .panel_view(panel_handle(filler), cx),
                    window,
                    cx,
                )
            });
        });

        for (visible, expected) in [(false, false), (true, true), (false, false)] {
            cx.update(|_, cx| skin.set_close_button_visible(visible, cx));
            cx.run_until_parked();
            cx.update(|window, cx| window.draw(cx).clear(cx));
            assert_eq!(cx.debug_bounds(CLOSE_BUTTON_SELECTOR).is_some(), expected);
        }
    }

    /// Clicking a non-active tab's close button removes that panel by id and
    /// does not select it (`stop_propagation`). The displayed tab is a
    /// non-closable filler, so the only close button is the one under test.
    #[gpui::test]
    fn clicking_a_close_button_removes_only_that_tab(cx: &mut TestAppContext) {
        cx.update(|cx| crate::init(cx));
        let mut skin = None;
        let (area, cx) = cx.add_window_view(|window, cx| {
            let renderer = DockSkin::new(cx);
            skin = Some(renderer.clone());
            DockArea::new("skin", None, window, cx).with_renderer(renderer)
        });
        cx.update(|_, cx| skin.unwrap().set_close_button_visible(true, cx));

        let (closable_id, filler_id, activated) = cx.update(|window, cx| {
            let filler = TabProbe::new(false, cx);
            let closable = TabProbe::new(true, cx);
            let activated = closable.read(cx).activated.clone();
            let filler_handle = panel_handle(filler);
            let closable_handle = panel_handle(closable);
            let ids = (closable_handle.panel_id(cx), filler_handle.panel_id(cx));
            // Filler at ix 0 is the displayed tab; the closable tab at ix 1 is
            // never active, so its close button is the only one drawn.
            let layout = DockLayout::tabs()
                .panel_view(filler_handle, cx)
                .panel_view(closable_handle, cx);
            area.update(cx, |area, cx| area.set_center(layout, window, cx));
            (ids.0, ids.1, activated)
        });
        cx.run_until_parked();
        cx.update(|window, cx| window.draw(cx).clear(cx));

        assert!(
            cx.update(|_, cx| area.read(cx).panel(closable_id).is_some()),
            "the closable tab starts owned by the area"
        );

        let button = cx
            .debug_bounds(CLOSE_BUTTON_SELECTOR)
            .expect("the non-active closable tab draws a close button");
        cx.simulate_mouse_down(button.center(), MouseButton::Left, Modifiers::none());
        cx.simulate_mouse_up(button.center(), MouseButton::Left, Modifiers::none());
        cx.run_until_parked();

        assert!(
            cx.update(|_, cx| area.read(cx).panel(closable_id).is_none()),
            "the close click removes exactly the tab it belongs to"
        );
        assert!(
            cx.update(|_, cx| area.read(cx).panel(filler_id).is_some()),
            "the displayed filler tab is untouched"
        );
        assert!(
            !activated.get(),
            "stop_propagation keeps the close click from also selecting the tab"
        );
    }

    /// A click is left to the tab bar's animated reveal: the skin's own snap
    /// for a changed tab would land the strip on the first frame and cut the
    /// animation short.
    #[gpui::test]
    fn a_clicked_tab_is_revealed_by_the_tab_bar_not_snapped(cx: &mut TestAppContext) {
        cx.update(|cx| {
            crate::init(cx);
            cx.set_reduce_motion(false);
        });
        let (area, cx) = cx.add_window_view(|window, cx| {
            DockArea::new("skin", None, window, cx).with_renderer(DockSkin::new(cx))
        });
        cx.simulate_resize(gpui::size(px(300.), px(300.)));
        cx.update(|window, cx| {
            let layout = (0..8).fold(DockLayout::tabs(), |layout, _| {
                layout.panel_view(panel_handle(Probe::new(cx)), cx)
            });
            area.update(cx, |area, cx| area.set_center(layout, window, cx));
        });
        cx.run_until_parked();
        cx.update(|window, cx| window.draw(cx).clear(cx));

        // `debug_bounds` takes a `'static` selector.
        let tab = |cx: &mut VisualTestContext, ix: usize| {
            cx.debug_bounds(format!("{TAB_SELECTOR}-{ix}").leak())
                .unwrap()
        };
        let first_left = |cx: &mut VisualTestContext| tab(cx, 0).left();
        let start = first_left(cx);
        // The tab that runs off the 300px window: only its first few pixels
        // show before the bar's toolbar.
        let clipped = (0..8)
            .map(|ix| tab(cx, ix))
            .find(|tab| tab.right() > px(300.))
            .unwrap();

        cx.simulate_click(
            clipped.origin + gpui::point(px(4.), px(16.)),
            Modifiers::none(),
        );
        cx.update(|window, cx| window.draw(cx).clear(cx));
        assert_eq!(first_left(cx), start, "the first frame has not snapped");

        let mut lefts = Vec::new();
        for _ in 0..60 {
            cx.executor()
                .advance_clock(std::time::Duration::from_millis(16));
            cx.update(|window, cx| {
                window.simulate_next_frame(cx);
                window.draw(cx).clear(cx);
            });
            lefts.push(first_left(cx));
        }
        let end = *lefts.last().unwrap();
        assert!(end < start, "the strip scrolled");
        assert!(
            lefts.iter().any(|left| *left < start && *left > end),
            "the strip slid rather than jumped: {lefts:?}"
        );
    }

    /// The collapse button reports the user's toggle; a toggle made by code
    /// does not.
    #[gpui::test]
    fn the_collapse_button_reports_the_toggle(cx: &mut TestAppContext) {
        cx.update(|cx| crate::init(cx));
        let (area, cx) = cx.add_window_view(|window, cx| {
            DockArea::new("toggle", None, window, cx).with_renderer(DockSkin::new(cx))
        });
        cx.simulate_resize(gpui::size(px(800.), px(600.)));
        let events = Rc::new(RefCell::new(Vec::new()));
        cx.update(|window, cx| {
            let center = DockLayout::tabs().panel_view(panel_handle(Probe::new(cx)), cx);
            let left = DockLayout::tabs().panel_view(panel_handle(Probe::new(cx)), cx);
            area.update(cx, |area, cx| {
                area.set_center(center, window, cx);
                area.set_dock(DockPlacement::Left, left, window, cx);
            });
            let events = events.clone();
            cx.subscribe(&area, move |_, event: &crate::dock::DockToggleEvent, _| {
                events
                    .borrow_mut()
                    .push((event.placement(), event.is_open()));
            })
            .detach();
        });
        cx.run_until_parked();
        cx.update(|window, cx| window.draw(cx).clear(cx));

        let selector = format!("{DOCK_TOGGLE_SELECTOR}-{:?}", DockPlacement::Left).leak();
        let button = cx
            .debug_bounds(selector)
            .expect("the left dock offers a toggle");
        cx.simulate_click(button.center(), Modifiers::none());
        cx.run_until_parked();
        assert!(!cx.read(|cx| area.read(cx).is_dock_open(DockPlacement::Left)));
        assert_eq!(*events.borrow(), vec![(DockPlacement::Left, false)]);

        cx.update(|window, cx| {
            area.update(cx, |area, cx| {
                area.toggle_dock(DockPlacement::Left, window, cx)
            });
        });
        cx.run_until_parked();
        assert_eq!(
            events.borrow().len(),
            1,
            "a toggle made by code is not reported"
        );
    }

    /// Clicking a tab on a collapsed bottom dock's strip opens the dock and
    /// reports it.
    #[gpui::test]
    fn opening_the_bottom_strip_reports_the_toggle(cx: &mut TestAppContext) {
        cx.update(|cx| crate::init(cx));
        let (area, cx) = cx.add_window_view(|window, cx| {
            DockArea::new("strip", None, window, cx).with_renderer(DockSkin::new(cx))
        });
        cx.simulate_resize(gpui::size(px(800.), px(600.)));
        let events = Rc::new(RefCell::new(Vec::new()));
        cx.update(|window, cx| {
            // Two panels: a group with one panel draws its title, not a tab bar.
            let layout = DockLayout::tabs()
                .panel_view(panel_handle(Probe::new(cx)), cx)
                .panel_view(panel_handle(Probe::new(cx)), cx);
            area.update(cx, |area, cx| {
                area.set_dock(DockPlacement::Bottom, layout, window, cx);
                area.toggle_dock(DockPlacement::Bottom, window, cx);
            });
            let events = events.clone();
            cx.subscribe(&area, move |_, event: &crate::dock::DockToggleEvent, _| {
                events
                    .borrow_mut()
                    .push((event.placement(), event.is_open()));
            })
            .detach();
        });
        cx.run_until_parked();
        cx.update(|window, cx| window.draw(cx).clear(cx));
        assert!(!cx.read(|cx| area.read(cx).is_dock_open(DockPlacement::Bottom)));

        let tab = cx
            .debug_bounds(format!("{TAB_SELECTOR}-0").leak())
            .expect("the collapsed strip still draws its tab");
        cx.simulate_click(tab.center(), Modifiers::none());
        cx.run_until_parked();
        assert_eq!(*events.borrow(), vec![(DockPlacement::Bottom, true)]);
    }

    /// A dock that refuses to close is not reported as toggled.
    #[gpui::test]
    fn a_refused_toggle_is_not_reported(cx: &mut TestAppContext) {
        cx.update(|cx| crate::init(cx));
        let (area, cx) = cx.add_window_view(|window, cx| {
            DockArea::new("refuse", None, window, cx).with_renderer(DockSkin::new(cx))
        });
        let events = Rc::new(RefCell::new(Vec::new()));
        cx.update(|window, cx| {
            let layout = DockLayout::tabs().panel_view(panel_handle(Probe::new(cx)), cx);
            area.update(cx, |area, cx| {
                area.set_dock(DockPlacement::Left, layout, window, cx);
                area.set_dock_collapsible(DockPlacement::Left, false, window, cx);
            });
            let events = events.clone();
            cx.subscribe(&area, move |_, event: &crate::dock::DockToggleEvent, _| {
                events
                    .borrow_mut()
                    .push((event.placement(), event.is_open()));
            })
            .detach();
        });
        cx.update(|window, cx| {
            area.update(cx, |area, cx| {
                toggle_dock_by_user(area, DockPlacement::Left, window, cx)
            });
        });
        cx.run_until_parked();
        assert!(cx.read(|cx| area.read(cx).is_dock_open(DockPlacement::Left)));
        assert!(events.borrow().is_empty());
    }

    /// A collapsed group offers no close button, though the same group does
    /// while open. Before/after collapse isolates `!collapsed`; nothing else
    /// changes.
    #[gpui::test]
    fn a_collapsed_group_draws_no_close_button(cx: &mut TestAppContext) {
        cx.update(|cx| crate::init(cx));
        let mut skin = None;
        let (area, cx) = cx.add_window_view(|window, cx| {
            let renderer = DockSkin::new(cx);
            skin = Some(renderer.clone());
            DockArea::new("skin", None, window, cx).with_renderer(renderer)
        });
        cx.update(|_, cx| skin.unwrap().set_close_button_visible(true, cx));
        // Two closable panels so the group is draggable (not on its last
        // visible panel) and offers close buttons while open.
        cx.update(|window, cx| {
            let a = TabProbe::new(true, cx);
            let b = TabProbe::new(true, cx);
            let layout = DockLayout::tabs()
                .panel_view(panel_handle(a), cx)
                .panel_view(panel_handle(b), cx);
            area.update(cx, |area, cx| {
                area.set_dock(DockPlacement::Bottom, layout, window, cx);
                if !area.is_dock_open(DockPlacement::Bottom) {
                    area.toggle_dock(DockPlacement::Bottom, window, cx);
                }
            });
        });
        cx.run_until_parked();
        cx.update(|window, cx| window.draw(cx).clear(cx));
        assert!(
            cx.debug_bounds(CLOSE_BUTTON_SELECTOR).is_some(),
            "an open group with two closable panels offers a close button"
        );

        // Collapse the bottom dock: its strip stays clickable, but the close
        // buttons on it must not.
        cx.update(|window, cx| {
            area.update(cx, |area, cx| {
                area.toggle_dock(DockPlacement::Bottom, window, cx)
            });
        });
        cx.run_until_parked();
        cx.update(|window, cx| window.draw(cx).clear(cx));
        assert!(
            cx.debug_bounds(CLOSE_BUTTON_SELECTOR).is_none(),
            "a collapsed group must not offer a close button"
        );
    }
}
