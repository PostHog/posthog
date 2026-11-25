use std::{cell::Cell, rc::Rc};

use gpui::{
    Anchor, AnyElement, App, Bounds, Div, ElementId, InteractiveElement, Interactivity,
    IntoElement, ParentElement, Pixels, Point, RenderOnce, StatefulInteractiveElement,
    StyleRefinement, Styled, Window, canvas, deferred, div, point, px,
};

use crate::{Positioner, ResolvedPosition, StyledExt as _};

/// Distance kept between a popup and the window edge.
const WINDOW_MARGIN: Pixels = px(8.);

/// Deferred paint priority for interactive surfaces that must appear above dialogs.
pub const POPUP_PRIORITY: usize = 100;

#[derive(Default)]
struct PopupAnchorState {
    bounds: Bounds<Pixels>,
    captured: bool,
}

/// An unstyled trigger and anchored popup host.
///
/// `Popup` owns trigger measurement, anchor-point calculation, first-frame
/// synchronization, deferred rendering, and window-edge snapping. Callers own
/// open state, interaction, popup content, appearance, and motion.
#[derive(IntoElement)]
pub struct Popup {
    id: ElementId,
    base: gpui::Stateful<Div>,
    style: StyleRefinement,
    anchor: Anchor,
    offset: Pixels,
    on_position: Option<Box<dyn Fn(ResolvedPosition, Bounds<Pixels>)>>,
    trigger: AnyElement,
    content: Option<AnyElement>,
}

impl Popup {
    pub fn new(id: impl Into<ElementId>, trigger: impl IntoElement) -> Self {
        let id = id.into();
        Self {
            base: div().id(id.clone()),
            id,
            style: StyleRefinement::default(),
            anchor: Anchor::TopLeft,
            offset: px(0.),
            on_position: None,
            trigger: trigger.into_any_element(),
            content: None,
        }
    }

    pub fn anchor(mut self, anchor: impl Into<Anchor>) -> Self {
        self.anchor = anchor.into();
        self
    }

    /// Gap from the trigger along the anchor's outward direction, zero by default.
    pub fn offset(mut self, offset: Pixels) -> Self {
        self.offset = offset;
        self
    }

    /// Observe resolved popup and trigger bounds before content prepaint.
    pub fn on_position(
        mut self,
        callback: impl Fn(ResolvedPosition, Bounds<Pixels>) + 'static,
    ) -> Self {
        self.on_position = Some(Box::new(callback));
        self
    }

    pub fn content(mut self, content: impl IntoElement) -> Self {
        self.content = Some(content.into_any_element());
        self
    }

    pub fn resolved_corner(anchor: Anchor, trigger_bounds: Bounds<Pixels>) -> Point<Pixels> {
        match anchor {
            Anchor::TopLeft => trigger_bounds.origin,
            Anchor::TopCenter => trigger_bounds.top_center(),
            Anchor::TopRight => trigger_bounds.top_right(),
            Anchor::BottomLeft => Point {
                x: trigger_bounds.origin.x,
                y: trigger_bounds.origin.y - trigger_bounds.size.height,
            },
            Anchor::BottomCenter => Point {
                x: trigger_bounds.top_center().x,
                y: trigger_bounds.origin.y - trigger_bounds.size.height,
            },
            Anchor::BottomRight => Point {
                x: trigger_bounds.top_right().x,
                y: trigger_bounds.origin.y - trigger_bounds.size.height,
            },
            Anchor::LeftCenter | Anchor::RightCenter => trigger_bounds.origin,
        }
    }
}

/// Match the popup's anchor to the opposite edge of the measured trigger.
fn anchor_position(anchor: Anchor, trigger: Bounds<Pixels>, offset: Pixels) -> Point<Pixels> {
    match anchor {
        Anchor::TopLeft => trigger.bottom_left() + point(px(0.), offset),
        Anchor::TopCenter => trigger.bottom_center() + point(px(0.), offset),
        Anchor::TopRight => trigger.bottom_right() + point(px(0.), offset),
        Anchor::BottomLeft => trigger.origin - point(px(0.), offset),
        Anchor::BottomCenter => trigger.top_center() - point(px(0.), offset),
        Anchor::BottomRight => trigger.top_right() - point(px(0.), offset),
        Anchor::LeftCenter => trigger.right_center() + point(offset, px(0.)),
        Anchor::RightCenter => trigger.left_center() - point(offset, px(0.)),
    }
}

impl Styled for Popup {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl InteractiveElement for Popup {
    fn interactivity(&mut self) -> &mut Interactivity {
        self.base.interactivity()
    }
}

impl StatefulInteractiveElement for Popup {}

impl RenderOnce for Popup {
    fn render(self, window: &mut Window, cx: &mut App) -> impl IntoElement {
        let state =
            window.use_keyed_state((self.id, "anchor"), cx, |_, _| PopupAnchorState::default());
        let anchor = self.anchor;
        let trigger_bounds = Rc::new(Cell::new(state.read(cx).bounds));
        let offset = self.offset;
        let position = Rc::new(Cell::new(anchor_position(
            anchor,
            state.read(cx).bounds,
            offset,
        )));

        // A closed popup places nothing: it notes its trigger's bounds, for when
        // it opens, without asking for another frame.
        let has_content = self.content.is_some();
        let root = self
            .base
            .child(self.trigger)
            .child(
                canvas(
                    {
                        let state = state.clone();
                        let position = position.clone();
                        let trigger_bounds = trigger_bounds.clone();
                        move |bounds, window, cx| {
                            trigger_bounds.set(bounds);
                            position.set(anchor_position(anchor, bounds, offset));
                            let first = state.update(cx, |state, _| {
                                let first = !state.captured;
                                state.bounds = bounds;
                                state.captured = true;
                                first
                            });
                            if first && has_content {
                                window.request_animation_frame();
                            }
                        }
                    },
                    |_, _, _, _| {},
                )
                .absolute()
                .size_full()
                .top_0()
                .left_0(),
            )
            .refine_style(&self.style);

        let Some(content) = self.content else {
            return root;
        };
        if !state.read(cx).captured {
            return root;
        }

        let positioner =
            Positioner::corner(anchor, position.get()).tracked_corner_position(position);
        let positioner = if let Some(callback) = self.on_position {
            positioner.on_position(move |position| callback(position, trigger_bounds.get()))
        } else {
            positioner
        };
        root.child(
            deferred(
                positioner
                    .margin(WINDOW_MARGIN)
                    // The host blocks the mouse, so no caller has to remember:
                    // what a popup covers belongs to the popup.
                    .occlude()
                    .child(content),
            )
            .with_priority(POPUP_PRIORITY),
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use gpui::{Context, Render, px};

    #[test]
    fn resolved_corner_preserves_existing_anchor_math() {
        let bounds = Bounds {
            origin: Point::new(px(100.), px(100.)),
            size: gpui::Size::new(px(200.), px(50.)),
        };
        assert_eq!(
            Popup::resolved_corner(Anchor::TopCenter, bounds),
            Point::new(px(200.), px(100.))
        );
        assert_eq!(
            Popup::resolved_corner(Anchor::BottomRight, bounds),
            Point::new(px(300.), px(50.))
        );
    }

    struct Harness;

    impl Render for Harness {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            Popup::new(
                "popup",
                div()
                    .debug_selector(|| "popup-trigger".into())
                    .size(px(100.)),
            )
            .content(
                div()
                    .debug_selector(|| "popup-content".into())
                    .size(px(20.)),
            )
        }
    }

    /// A caller that styles its own surface — a hover card, a dropdown — does
    /// not have to remember to block the mouse. The host does it, so the panel
    /// a popup covers stops reacting to a pointer that is over the popup.
    struct OcclusionHarness {
        background_hovered: Rc<Cell<bool>>,
        content_hovered: Rc<Cell<bool>>,
    }

    impl Render for OcclusionHarness {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            let background = self.background_hovered.clone();
            let content = self.content_hovered.clone();
            div()
                .relative()
                .size(px(200.))
                .child(
                    div()
                        .id("background")
                        .absolute()
                        .size_full()
                        .on_mouse_move(move |_, _, _| background.set(true)),
                )
                .child(
                    Popup::new("popup", div().size(px(100.))).content(
                        div()
                            .id("content")
                            .size(px(40.))
                            .on_mouse_move(move |_, _, _| content.set(true)),
                    ),
                )
        }
    }

    #[gpui::test]
    fn the_popup_surface_blocks_the_panel_it_covers(cx: &mut gpui::TestAppContext) {
        let background_hovered = Rc::new(Cell::new(false));
        let content_hovered = Rc::new(Cell::new(false));
        let (_, window) = cx.add_window_view({
            let background_hovered = background_hovered.clone();
            let content_hovered = content_hovered.clone();
            move |_, _| OcclusionHarness {
                background_hovered,
                content_hovered,
            }
        });
        window.update(|window, cx| window.draw(cx).clear(cx));
        window.update(|window, cx| window.draw(cx).clear(cx));

        window.simulate_mouse_move(
            gpui::point(px(20.), px(110.)),
            None,
            gpui::Modifiers::default(),
        );
        assert!(!background_hovered.get());
        // The surface blocks what is behind it, not its own content: the
        // hitbox goes in ahead of the children, never over them.
        assert!(content_hovered.get());

        // The same pointer outside the surface still reaches the panel, so the
        // assertion above is about occlusion and not a dead listener.
        window.simulate_mouse_move(
            gpui::point(px(150.), px(180.)),
            None,
            gpui::Modifiers::default(),
        );
        assert!(background_hovered.get());
    }

    /// A popup that may open later.
    struct ClosedHarness {
        open: bool,
    }

    impl Render for ClosedHarness {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            let popup = Popup::new(
                "popup",
                div()
                    .debug_selector(|| "popup-trigger".into())
                    .size(px(100.)),
            );
            if self.open {
                popup.content(
                    div()
                        .debug_selector(|| "popup-content".into())
                        .size(px(20.)),
                )
            } else {
                popup
            }
        }
    }

    /// A closed popup notes its trigger's bounds without asking for another
    /// frame: a list of rows holding closed popups is not drawn again for
    /// each row that shows. Opened, it places its content at once.
    #[gpui::test]
    fn a_closed_popup_asks_for_no_frame_and_opens_at_once(cx: &mut gpui::TestAppContext) {
        let (view, window) = cx.add_window_view(|_, _| ClosedHarness { open: false });
        window.update(|window, cx| {
            window.draw(cx).clear(cx);
            assert_eq!(window.simulate_next_frame(cx), 0, "no frame was asked for");
        });

        view.update(window, |harness, cx| {
            harness.open = true;
            cx.notify();
        });
        window.update(|window, cx| window.draw(cx).clear(cx));
        assert_eq!(
            window.debug_bounds("popup-content").unwrap().size,
            gpui::Size::new(px(20.), px(20.))
        );
    }

    #[gpui::test]
    fn trigger_capture_enables_deferred_content_on_the_next_frame(cx: &mut gpui::TestAppContext) {
        let (_, window) = cx.add_window_view(|_, _| Harness);
        window.update(|window, cx| window.draw(cx).clear(cx));
        window.update(|window, cx| window.draw(cx).clear(cx));

        assert_eq!(
            window.debug_bounds("popup-trigger").unwrap().size,
            gpui::Size::new(px(100.), px(100.))
        );
        assert_eq!(
            window.debug_bounds("popup-content").unwrap().size,
            gpui::Size::new(px(20.), px(20.))
        );
    }
}
