//! The gpui-component appearance for the dock area: the outer frame, the
//! split frames, and one dock's chrome.

use std::{rc::Rc, sync::Arc};

use gpui::{
    AnyElement, App, AppContext as _, Axis, Context, Div, Element, Empty, InteractiveElement as _,
    IntoElement, MouseMoveEvent, MouseUpEvent, ParentElement as _, Pixels, Render, Stateful, Style,
    Styled as _, Window, div,
};
use gpui_base::{
    HandleEdge, ResizeHandleContext,
    dock::{
        DockAreaRenderer, DockContext, DockEvent, DockPlacement, NodeId, PanelState, PanelView,
        TabGroupRenderer,
    },
};

use crate::{
    ActiveTheme as _,
    dock::{
        DockSkin, SkinShared, invalid_panel::InvalidPanel, panel_handle, report_user_toggle,
        tab_panel::TabGroupSkin,
    },
    resizable::render_resize_handle,
    resize_handle,
};

/// The payload a dock's resize handle drags. It draws nothing: the handle
/// itself is the affordance.
#[derive(Clone)]
struct ResizePanel;

impl Render for ResizePanel {
    fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
        Empty
    }
}

impl DockAreaRenderer for DockSkin {
    // The row, the fill and the clip are base's now -- applied around whatever
    // these return -- so a skin that has no appearance to add returns a bare
    // frame and still gets a dock area the right shape.
    fn frame(&self, _: &mut Window, _: &mut App) -> Stateful<Div> {
        div().id("dock-area")
    }

    fn center_frame(&self, _: &mut Window, _: &mut App) -> Stateful<Div> {
        div().id("dock-area-center")
    }

    fn render_split_handle(
        &self,
        handle: &ResizeHandleContext,
        window: &mut Window,
        cx: &mut App,
    ) -> Option<AnyElement> {
        Some(render_resize_handle(handle, window, cx))
    }

    fn split_frame(&self, node: NodeId, _: Axis, _: &mut Window, cx: &mut App) -> Stateful<Div> {
        // The size is base's; the background is this skin's, and is the only
        // reason this hook is implemented at all.
        div()
            .id(("dock-split-frame", node.as_u64()))
            .bg(cx.theme().tokens.tab_bar)
    }

    fn render_dock(
        &self,
        dock: &DockContext,
        content: AnyElement,
        window: &mut Window,
        cx: &mut App,
    ) -> AnyElement {
        // No box here any more. A dock's extent is structural, so
        // `DockArea::render_dock` applies it around whatever this returns --
        // which also means a renderer that draws no chrome still gets a dock
        // the right shape. This adds the edge you drag and nothing else.
        div()
            .flex()
            .size_full()
            .relative()
            .child(content)
            .child(self.render_resize_handle(dock, window, cx))
            .child(DockResizeTracker {
                dock: dock.clone(),
                shared: self.shared().clone(),
            })
            .into_any_element()
    }

    /// The "unknown panel" message the old `InvalidPanel` drew.
    ///
    /// It answers `dump` with the state it was handed, so a layout written by
    /// a build that knows the panel survives a load and save here.
    fn build_placeholder(
        &self,
        state: &PanelState,
        _: &mut Window,
        cx: &mut App,
    ) -> Option<Arc<dyn PanelView>> {
        let state = state.clone();
        Some(panel_handle(cx.new(|cx| InvalidPanel::new(state, cx))))
    }

    fn tab_group_renderer(&self) -> Rc<dyn TabGroupRenderer> {
        Rc::new(TabGroupSkin::new(self.shared().clone()))
    }
}

impl DockSkin {
    fn render_resize_handle(
        &self,
        dock: &DockContext,
        _: &mut Window,
        _: &mut App,
    ) -> impl IntoElement {
        let placement = dock.placement();
        let open = dock.is_open();
        let shared = self.shared().clone();

        // One id per placement: the docks all render under the same stateful
        // ancestor, so a shared literal would collapse the handles into one
        // GlobalElementId and GPUI would silently share their element state —
        // a press on the left handle then starts the right handle's drag.
        let id = match placement {
            DockPlacement::Left => "resize-handle-left",
            DockPlacement::Right => "resize-handle-right",
            DockPlacement::Bottom => "resize-handle-bottom",
            DockPlacement::Center => "resize-handle-center",
        };

        // Every dock's handle lives inside the dock, because `dock_frame` clips
        // to the dock's box. The left dock hugs its trailing edge; the right
        // and bottom docks hug their leading one.
        let edge = match placement {
            DockPlacement::Left => HandleEdge::Trailing,
            _ => HandleEdge::Leading,
        };

        resize_handle(id, placement.axis()).inside(edge).on_drag(
            ResizePanel,
            move |info, _, _, cx| {
                cx.stop_propagation();
                shared.resizing_dock().set(Some(placement));
                shared.resize_started_open().set(open);
                cx.new(|_| info.clone())
            },
        )
    }
}

/// Turns the window's mouse stream into dock resizing.
///
/// A resize is driven by pointer moves that land anywhere in the window, not
/// only on the handle, so it cannot be expressed as a listener on the handle
/// itself. This element paints nothing and exists for its `paint` hook, which
/// is the only place a window-level mouse listener can be registered — which
/// is why it stays in the skin rather than moving into base: it is a
/// paint-order concern of this appearance.
struct DockResizeTracker {
    dock: DockContext,
    shared: Rc<SkinShared>,
}

impl IntoElement for DockResizeTracker {
    type Element = Self;

    fn into_element(self) -> Self::Element {
        self
    }
}

impl Element for DockResizeTracker {
    type RequestLayoutState = ();
    type PrepaintState = ();

    fn id(&self) -> Option<gpui::ElementId> {
        None
    }

    fn source_location(&self) -> Option<&'static std::panic::Location<'static>> {
        None
    }

    fn request_layout(
        &mut self,
        _: Option<&gpui::GlobalElementId>,
        _: Option<&gpui::InspectorElementId>,
        window: &mut Window,
        cx: &mut App,
    ) -> (gpui::LayoutId, Self::RequestLayoutState) {
        (window.request_layout(Style::default(), None, cx), ())
    }

    fn prepaint(
        &mut self,
        _: Option<&gpui::GlobalElementId>,
        _: Option<&gpui::InspectorElementId>,
        _: gpui::Bounds<Pixels>,
        _: &mut Self::RequestLayoutState,
        _: &mut Window,
        _: &mut App,
    ) -> Self::PrepaintState {
    }

    fn paint(
        &mut self,
        _: Option<&gpui::GlobalElementId>,
        _: Option<&gpui::InspectorElementId>,
        _: gpui::Bounds<Pixels>,
        _: &mut Self::RequestLayoutState,
        _: &mut Self::PrepaintState,
        window: &mut Window,
        _: &mut App,
    ) {
        let placement = self.dock.placement();

        window.on_mouse_event({
            let dock = self.dock.clone();
            let shared = self.shared.clone();
            move |event: &MouseMoveEvent, phase, window, cx| {
                if !phase.bubble() || shared.resizing_dock().get() != Some(placement) {
                    return;
                }
                // Base opens, closes and sizes the dock from the pointer, so a
                // drag that started on a closed dock reopens it too.
                dock.resize_to(event.position, window, cx);
            }
        });

        window.on_mouse_event({
            let dock = self.dock.clone();
            let shared = self.shared.clone();
            move |_: &MouseUpEvent, phase, window, cx| {
                if !phase.bubble() || shared.resizing_dock().get() != Some(placement) {
                    return;
                }
                shared.resizing_dock().set(None);
                dock.end_resize(window, cx);
                let was_open = shared.resize_started_open().get();
                // The size lives on the dock, not in the layout tree, so
                // nothing else tells a subscriber to persist it.
                _ = shared.area().update(cx, |area, cx| {
                    cx.emit(DockEvent::LayoutChanged);
                    report_user_toggle(area, placement, was_open, cx);
                });
            }
        });
    }
}

#[cfg(test)]
mod tests {
    use std::rc::Rc;

    use gpui::{
        App, Entity, IntoElement as _, Modifiers, MouseButton, TestAppContext, VisualTestContext,
        Window, point, px, size,
    };

    use std::cell::Cell;

    use gpui_base::dock::DockAreaRenderer;

    use gpui_base::PANEL_MIN_SIZE;

    use crate::dock::{
        DockArea, DockLayout, DockPlacement, DockSkin,
        test_support::{MeasuredProbe, SizedProbe},
    };

    /// A renderer that draws no chrome at all: every hook at its trait default.
    ///
    /// This is the position every renderer that is not `DockSkin` starts from,
    /// including the one gpui-shell installs so a script can draw the chrome
    /// itself, and the shape of what it gets is base's promise.
    struct ChromelessDockSkin;

    impl DockAreaRenderer for ChromelessDockSkin {
        fn tab_group_renderer(&self) -> Rc<dyn gpui_base::dock::TabGroupRenderer> {
            Rc::new(ChromelessTabs)
        }
    }

    struct ChromelessTabs;
    impl gpui_base::dock::TabGroupRenderer for ChromelessTabs {
        // The one hook with no default, because a group with no tab bar has no
        // way to choose between its panels. Drawn as nothing, so the height it
        // leaves the content is the whole group.
        fn render_tab_bar(
            &self,
            _: &gpui_base::dock::TabGroupContext,
            _: &mut Window,
            _: &mut App,
        ) -> gpui::AnyElement {
            gpui::Empty.into_any_element()
        }
    }

    /// A dock's box is base's, not its renderer's.
    ///
    /// This is the regression. The extent lived in `DockSkin::render_dock`, so
    /// it was reachable only through that one renderer, and `render_dock`'s
    /// trait default hands the content straight back. A dock that never states
    /// its extent is not a column beside the centre: it takes whatever the row
    /// gives it and the panes inside shrink to their content. Nothing failed,
    /// and nothing said why.
    #[gpui::test]
    fn a_dock_is_its_own_width_under_a_renderer_that_draws_no_chrome(cx: &mut TestAppContext) {
        cx.update(|cx| crate::init(cx));
        let measured = Rc::new(Cell::new(gpui::Size::default()));
        let probe = measured.clone();
        let centre = Rc::new(Cell::new(gpui::Size::default()));
        let centre_probe = centre.clone();
        let (area, cx) = cx.add_window_view(|window, cx| {
            DockArea::new("test", None, window, cx).with_renderer(Rc::new(ChromelessDockSkin))
        });
        cx.simulate_resize(size(px(800.), px(600.)));
        cx.update(|window, cx| {
            area.update(cx, |area, cx| {
                area.set_center(
                    DockLayout::tabs().panel(SizedProbe::new(centre_probe, cx)),
                    window,
                    cx,
                );
                area.set_dock(
                    DockPlacement::Right,
                    DockLayout::tabs().panel(SizedProbe::new(probe, cx)),
                    window,
                    cx,
                );
                area.set_dock_size(DockPlacement::Right, px(200.), window, cx);
            });
        });
        cx.run_until_parked();
        cx.update(|window, cx| {
            area.update(cx, |area, cx| {
                if !area.is_dock_open(DockPlacement::Right) {
                    area.toggle_dock(DockPlacement::Right, window, cx);
                }
            });
        });
        cx.run_until_parked();
        cx.update(|window, cx| window.draw(cx).clear(cx));

        let dock = measured.get().width;
        assert_eq!(
            dock,
            px(200.),
            "the right dock has to be its own width, not the area's: got {dock:?}"
        );
        // The other half of the same fault: a dock area that is not a row puts
        // the centre above the dock at the area's full width instead of beside
        // it at what the dock leaves.
        let middle = centre.get().width;
        assert_eq!(
            middle,
            px(600.),
            "the centre has to be what the docks leave: got {middle:?}"
        );
        // This renderer draws no tab bar, so a group that fills its slot leaves
        // its panel the whole 600. A tab group frame without a column and a
        // fill gives it nothing: the panel is positioned absolutely inside the
        // content region and contributes no height of its own, so the region
        // resolves to zero and the group is a strip of tabs.
        let tall = centre.get().height;
        assert_eq!(
            tall,
            px(600.),
            "a group has to fill its slot, or its panel gets no height: got {tall:?}"
        );
    }

    fn area_with_side_docks(cx: &mut TestAppContext) -> (Entity<DockArea>, &mut VisualTestContext) {
        cx.update(|cx| crate::init(cx));
        let (area, cx) = cx.add_window_view(|window, cx| {
            DockArea::new("test", None, window, cx).with_renderer(DockSkin::new(cx))
        });
        cx.simulate_resize(size(px(800.), px(600.)));
        cx.update(|window, cx| {
            area.update(cx, |area, cx| {
                area.set_center(
                    DockLayout::tabs().panel(MeasuredProbe::new(Rc::default(), cx)),
                    window,
                    cx,
                );
                area.set_dock(
                    DockPlacement::Left,
                    DockLayout::tabs().panel(MeasuredProbe::new(Rc::default(), cx)),
                    window,
                    cx,
                );
                area.set_dock(
                    DockPlacement::Right,
                    DockLayout::tabs().panel(MeasuredProbe::new(Rc::default(), cx)),
                    window,
                    cx,
                );
            });
        });
        cx.run_until_parked();
        (area, cx)
    }

    /// Every dock's handle once shared the literal element id
    /// `"resize-handle"`, so GPUI silently handed them one element state —
    /// including the pending-mouse-down that starts a drag. Pressing the left
    /// handle then let the right dock's drag listener (painted later, so
    /// dispatched first) claim the drag, and one pixel of movement threw the
    /// right dock to nearly the full area width.
    #[gpui::test]
    fn dragging_the_left_handle_resizes_only_the_left_dock(cx: &mut TestAppContext) {
        let (area, cx) = area_with_side_docks(cx);
        cx.update(|window, cx| window.draw(cx).clear(cx));

        // The left dock is 200px wide, so its handle sits at x ∈ [198, 199).
        cx.simulate_mouse_down(
            point(px(198.5), px(300.)),
            MouseButton::Left,
            Modifiers::none(),
        );
        // Past the drag threshold: the drag starts and claims a dock.
        cx.simulate_mouse_move(
            point(px(204.), px(300.)),
            MouseButton::Left,
            Modifiers::none(),
        );
        // The move the claimed dock resizes to.
        cx.simulate_mouse_move(
            point(px(240.), px(300.)),
            MouseButton::Left,
            Modifiers::none(),
        );
        cx.simulate_mouse_up(
            point(px(240.), px(300.)),
            MouseButton::Left,
            Modifiers::none(),
        );
        cx.run_until_parked();

        let (left, right) = cx.update(|_, cx| {
            let area = area.read(cx);
            (
                area.dock_size(DockPlacement::Left),
                area.dock_size(DockPlacement::Right),
            )
        });
        assert_eq!(
            right,
            Some(px(200.)),
            "the right dock must not move when the left handle is dragged"
        );
        assert_eq!(left, Some(px(240.)), "the left dock follows the pointer");
    }
    #[gpui::test]
    fn dragging_the_bottom_dock_closed_and_open_reports_each_toggle(cx: &mut TestAppContext) {
        cx.update(|cx| crate::init(cx));
        let (area, cx) = cx.add_window_view(|window, cx| {
            DockArea::new("test", None, window, cx).with_renderer(DockSkin::new(cx))
        });
        cx.simulate_resize(size(px(800.), px(600.)));
        let events = Rc::new(std::cell::RefCell::new(Vec::new()));
        cx.update(|window, cx| {
            area.update(cx, |area, cx| {
                area.set_center(
                    DockLayout::tabs().panel(MeasuredProbe::new(Rc::default(), cx)),
                    window,
                    cx,
                );
                area.set_dock(
                    DockPlacement::Bottom,
                    DockLayout::tabs().panel(MeasuredProbe::new(Rc::default(), cx)),
                    window,
                    cx,
                );
                area.set_dock_size(DockPlacement::Bottom, px(200.), window, cx);
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

        let drag = |cx: &mut VisualTestContext, ys: &[f32]| {
            cx.update(|window, cx| window.draw(cx).clear(cx));
            let (first, rest) = ys.split_first().unwrap();
            cx.simulate_mouse_down(
                point(px(400.), px(*first)),
                MouseButton::Left,
                Modifiers::none(),
            );
            for y in rest {
                cx.simulate_mouse_move(
                    point(px(400.), px(*y)),
                    MouseButton::Left,
                    Modifiers::none(),
                );
            }
            cx.simulate_mouse_up(
                point(px(400.), px(*ys.last().unwrap())),
                MouseButton::Left,
                Modifiers::none(),
            );
            cx.run_until_parked();
        };

        // A resize that keeps the dock open is not a toggle.
        drag(cx, &[400.5, 380., 350.]);
        assert!(events.borrow().is_empty(), "a plain resize is not reported");

        // Same handle, same strip geometry as the snapping test below.
        drag(cx, &[350.5, 356., 580., 540.]);
        drag(cx, &[571.5, 565., 520.]);
        assert_eq!(
            *events.borrow(),
            vec![
                (DockPlacement::Bottom, false),
                (DockPlacement::Bottom, true)
            ]
        );
    }

    #[gpui::test]
    fn dragging_the_bottom_handle_below_the_minimum_snaps_to_the_nearer_end(
        cx: &mut TestAppContext,
    ) {
        cx.update(|cx| crate::init(cx));
        let (area, cx) = cx.add_window_view(|window, cx| {
            DockArea::new("test", None, window, cx).with_renderer(DockSkin::new(cx))
        });
        cx.simulate_resize(size(px(800.), px(600.)));
        cx.update(|window, cx| {
            area.update(cx, |area, cx| {
                area.set_center(
                    DockLayout::tabs().panel(MeasuredProbe::new(Rc::default(), cx)),
                    window,
                    cx,
                );
                area.set_dock(
                    DockPlacement::Bottom,
                    DockLayout::tabs().panel(MeasuredProbe::new(Rc::default(), cx)),
                    window,
                    cx,
                );
                area.set_dock_size(DockPlacement::Bottom, px(200.), window, cx);
            });
        });
        cx.run_until_parked();

        let drag = |cx: &mut VisualTestContext, ys: &[f32]| {
            cx.update(|window, cx| window.draw(cx).clear(cx));
            let (first, rest) = ys.split_first().unwrap();
            cx.simulate_mouse_down(
                point(px(400.), px(*first)),
                MouseButton::Left,
                Modifiers::none(),
            );
            for y in rest {
                cx.simulate_mouse_move(
                    point(px(400.), px(*y)),
                    MouseButton::Left,
                    Modifiers::none(),
                );
            }
            cx.simulate_mouse_up(
                point(px(400.), px(*ys.last().unwrap())),
                MouseButton::Left,
                Modifiers::none(),
            );
            cx.run_until_parked();
        };
        let bottom = |cx: &mut VisualTestContext| {
            cx.update(|_, cx| {
                let area = area.read(cx);
                (
                    area.is_dock_open(DockPlacement::Bottom),
                    area.dock_size(DockPlacement::Bottom),
                )
            })
        };

        // From the 200px dock's handle at y ∈ [400, 401), through the closed
        // strip and back, released 60px tall: nearer the strip than the
        // minimum, so it closes.
        drag(cx, &[400.5, 406., 580., 540.]);
        assert!(!bottom(cx).0, "released nearer the strip, the dock closes");

        // From the closed strip's handle at y ∈ [571, 572), released 80px
        // tall: nearer the minimum, so it opens at the minimum.
        drag(cx, &[571.5, 565., 520.]);
        assert_eq!(
            bottom(cx),
            (true, Some(PANEL_MIN_SIZE)),
            "released nearer the minimum, the dock opens at the minimum"
        );
    }
}
