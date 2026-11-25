//! The pointer and wheel event surface used by [`super::CarouselContent`].
//!
//! The mask is deliberately a sibling of the scrolled content.  A mask nested
//! inside the content would receive the content's scroll offset and would stop
//! covering the viewport after the first scroll.

use std::cell::RefCell;
use std::panic::Location;
use std::rc::Rc;

use gpui::{
    App, Axis, Bounds, ContentMask, Element, ElementId, GlobalElementId, Hitbox, IntoElement,
    IsZero as _, LayoutId, MouseButton, MouseDownEvent, MouseMoveEvent, MouseUpEvent,
    OngoingScroll, Position, ScrollEvent, Style, TouchPhase, Window, relative,
};

use super::state::CarouselState;
use crate::{AxisExt as _, OngoingScrollExt as _, global_state::GlobalState};

/// A viewport-sized, invisible event surface for a Carousel.
///
/// This surface owns pointer, wheel, and trackpad input so that a Carousel
/// nested in a list can lock its own axis while allowing cross-axis gestures
/// to continue to an ancestor.
pub(super) struct CarouselScrollMask {
    axis: Axis,
    id: ElementId,
    state: gpui::Entity<CarouselState>,
}

impl CarouselScrollMask {
    #[track_caller]
    pub(super) fn new(axis: Axis, state: &gpui::Entity<CarouselState>) -> Self {
        Self {
            axis,
            id: caller_id(),
            state: state.clone(),
        }
    }

    pub(super) fn id(mut self, id: impl Into<ElementId>) -> Self {
        self.id = id.into();
        self
    }
}

impl IntoElement for CarouselScrollMask {
    type Element = Self;

    fn into_element(self) -> Self::Element {
        self
    }
}

impl Element for CarouselScrollMask {
    type RequestLayoutState = ();
    type PrepaintState = Hitbox;

    fn id(&self) -> Option<ElementId> {
        let axis = if self.axis.is_horizontal() {
            "horizontal"
        } else {
            "vertical"
        };
        Some((self.id.clone(), axis).into())
    }

    fn source_location(&self) -> Option<&'static std::panic::Location<'static>> {
        None
    }

    fn request_layout(
        &mut self,
        _: Option<&GlobalElementId>,
        _: Option<&gpui::InspectorElementId>,
        window: &mut Window,
        cx: &mut App,
    ) -> (LayoutId, Self::RequestLayoutState) {
        let mut style = Style::default();
        style.position = Position::Absolute;
        style.inset.top = gpui::px(0.).into();
        style.inset.left = gpui::px(0.).into();
        style.size.width = relative(1.).into();
        style.size.height = relative(1.).into();
        (window.request_layout(style, None, cx), ())
    }

    fn prepaint(
        &mut self,
        _: Option<&GlobalElementId>,
        _: Option<&gpui::InspectorElementId>,
        bounds: Bounds<gpui::Pixels>,
        _: &mut Self::RequestLayoutState,
        window: &mut Window,
        _: &mut App,
    ) -> Self::PrepaintState {
        window.insert_hitbox(bounds, gpui::HitboxBehavior::Normal)
    }

    fn paint(
        &mut self,
        global_id: Option<&GlobalElementId>,
        _: Option<&gpui::InspectorElementId>,
        _: Bounds<gpui::Pixels>,
        _: &mut Self::RequestLayoutState,
        hitbox: &mut Self::PrepaintState,
        window: &mut Window,
        _: &mut App,
    ) {
        let axis = self.axis;
        let hitbox_id = hitbox.id;
        let bounds = hitbox.bounds;
        let state = self.state.clone();
        let ongoing_scroll = global_id
            .map(|global_id| {
                window.with_element_state::<Rc<RefCell<OngoingScroll>>, _>(global_id, |value, _| {
                    let value = value.unwrap_or_default();
                    (value.clone(), value)
                })
            })
            .unwrap_or_default();

        window.with_content_mask(Some(ContentMask { bounds }), |window| {
            let pointer_state = state.clone();
            window.on_mouse_event(move |event: &MouseDownEvent, phase, window, cx| {
                if phase.capture()
                    && event.button == MouseButton::Left
                    && hitbox_id.should_handle_scroll(window)
                {
                    let started =
                        pointer_state.update(cx, |state, cx| state.begin_drag(event.position, cx));
                    if started {
                        GlobalState::suppress_text_selection(cx);
                    }
                }
            });

            let pointer_state = state.clone();
            window.on_mouse_event(move |event: &MouseMoveEvent, phase, _, cx| {
                if !phase.capture() || event.pressed_button != Some(MouseButton::Left) {
                    return;
                }

                let handled =
                    pointer_state.update(cx, |state, cx| state.update_drag(event.position, cx));
                if handled {
                    cx.stop_propagation();
                }
            });

            let pointer_state = state.clone();
            let mut suppress_release = false;
            window.on_mouse_event(move |event: &MouseUpEvent, phase, window, cx| {
                if event.button != MouseButton::Left {
                    return;
                }

                if phase.capture() {
                    let snapshot = pointer_state.read(cx);
                    let handled = snapshot.is_pointer_drag_locked();
                    suppress_release = handled || snapshot.should_suppress_pointer_click();
                    pointer_state.update(cx, |state, cx| {
                        state.finish_drag(cx);
                    });
                    if suppress_release {
                        // The release may be stopped before TextSelectionLayer's
                        // bubble listener. Clear its observable selection state
                        // here so a Carousel drag cannot leave a stale drag or
                        // participant-local selection behind.
                        gpui_base::TextSelection::clear(window, cx);
                    }
                } else if suppress_release {
                    // All capture handlers have now cleared their pressed
                    // state. Stop before descendant click handlers run.
                    suppress_release = false;
                    cx.stop_propagation();
                }
            });

            window.on_mouse_event(move |event: &ScrollEvent, phase, window, cx| {
                if !phase.capture() || !hitbox_id.should_handle_scroll(window) {
                    return;
                }

                let mut delta = event.delta.pixel_delta(window.line_height());
                if event.delta.precise() {
                    ongoing_scroll
                        .borrow_mut()
                        .lock_axis(&mut delta, event.touch_phase);
                }

                if !delta.x.is_zero() && !delta.y.is_zero() {
                    if delta.x.abs() > delta.y.abs() {
                        delta.y = gpui::Pixels::ZERO;
                    } else {
                        delta.x = gpui::Pixels::ZERO;
                    }
                }

                // Ignore the secondary axis. The lock above keeps this stable
                // throughout a precise trackpad gesture.
                if axis.is_horizontal() {
                    delta.y = gpui::Pixels::ZERO;
                } else {
                    delta.x = gpui::Pixels::ZERO;
                }

                let precise = event.delta.precise();
                let primary_delta = if axis.is_horizontal() {
                    delta.x
                } else {
                    delta.y
                };
                let consumed = if primary_delta.is_zero() {
                    false
                } else if !precise {
                    state.update(cx, |state, cx| {
                        state.handle_wheel_step(axis, primary_delta, cx)
                    })
                } else if matches!(event.touch_phase, TouchPhase::Ended | TouchPhase::Cancelled) {
                    false
                } else {
                    // A gesture this carousel already owns stays here even at
                    // an edge, so its leftover never scrolls an ancestor. One
                    // that begins at an edge belongs to the ancestor until it
                    // ends.
                    let owned = state.read(cx).has_scroll_gesture();
                    let moved = state.update(cx, |state, cx| {
                        state.handle_scroll_delta(axis, primary_delta, event.touch_phase, cx)
                    });
                    if !moved && !owned {
                        state.update(cx, |state, cx| state.defer_scroll_to_ancestor(cx));
                    }
                    moved || owned
                };

                if precise {
                    match event.touch_phase {
                        TouchPhase::Ended => {
                            state.update(cx, |state, cx| state.finish_scroll(false, cx));
                        }
                        TouchPhase::Cancelled => {
                            state.update(cx, |state, cx| state.finish_scroll(true, cx));
                        }
                        TouchPhase::Started | TouchPhase::Moved => {}
                    }
                }

                // Horizontal carousels retain every gesture at their edge. A
                // vertical carousel hands a gesture that begins at an edge to
                // an ancestor so the surrounding document keeps scrolling.
                if consumed || (axis.is_horizontal() && !primary_delta.is_zero()) {
                    cx.stop_propagation();
                }
            });
        });
    }
}

#[track_caller]
fn caller_id() -> ElementId {
    ElementId::CodeLocation(*Location::caller())
}

#[cfg(test)]
mod tests {
    use std::{cell::Cell, rc::Rc};

    use gpui::{
        AppContext as _, Axis, Context, Entity, InteractiveElement as _, IntoElement, Modifiers,
        MouseButton, ParentElement as _, Render, ScrollDelta, ScrollEvent, ScrollHandle,
        StatefulInteractiveElement as _, Styled as _, TestAppContext, TouchPhase,
        VisualTestContext, Window, div, point, px,
    };

    use crate::{
        button::Button,
        carousel::{
            Carousel, CarouselContent, CarouselItem, CarouselState, state::SCROLL_EVENT_SEPARATION,
        },
    };

    struct ButtonDragHarness {
        state: Entity<CarouselState>,
        clicks: Rc<Cell<usize>>,
    }

    impl Render for ButtonDragHarness {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            let clicks = self.clicks.clone();
            Carousel::new("button-drag-carousel", &self.state)
                .w(px(100.))
                .h(px(40.))
                .child(
                    CarouselContent::new(&self.state)
                        .h(px(40.))
                        .child(
                            CarouselItem::new("button-slide", 0, &self.state)
                                .h(px(40.))
                                .child(
                                    Button::new("slide-button")
                                        .w_full()
                                        .h(px(40.))
                                        .on_click(move |_, _, _| clicks.set(clicks.get() + 1)),
                                ),
                        )
                        .child(
                            CarouselItem::new("plain-slide", 1, &self.state)
                                .h(px(40.))
                                .child("Second"),
                        ),
                )
        }
    }

    #[gpui::test]
    fn dragging_over_child_button_suppresses_click_without_leaving_it_pending(
        cx: &mut TestAppContext,
    ) {
        cx.update(crate::init);
        let state = cx.update(|cx| cx.new(|_| CarouselState::new(2)));
        let clicks = Rc::new(Cell::new(0));
        let (_, cx) = cx.add_window_view({
            let state = state.clone();
            let clicks = clicks.clone();
            move |_, _| ButtonDragHarness { state, clicks }
        });
        let cx: &mut VisualTestContext = cx;
        cx.update(|window, cx| window.draw(cx).clear(cx));

        cx.simulate_click(point(px(10.), px(10.)), Modifiers::default());
        assert_eq!(clicks.get(), 1);
        clicks.set(0);

        cx.simulate_mouse_down(
            point(px(30.), px(10.)),
            MouseButton::Left,
            Modifiers::default(),
        );
        assert!(state.read_with(cx, |state, _| state.is_interacting()));
        cx.simulate_mouse_move(
            point(px(10.), px(10.)),
            Some(MouseButton::Left),
            Modifiers::default(),
        );
        assert!(state.read_with(cx, |state, _| state.is_pointer_drag_locked()));
        cx.simulate_mouse_up(
            point(px(10.), px(10.)),
            MouseButton::Left,
            Modifiers::default(),
        );
        assert_eq!(clicks.get(), 0);

        cx.update(|window, cx| window.draw(cx).clear(cx));
        cx.simulate_click(point(px(10.), px(10.)), Modifiers::default());
        assert_eq!(clicks.get(), 1);
    }

    struct NestedVerticalCarouselHarness {
        state: Entity<CarouselState>,
        outer_handle: ScrollHandle,
    }

    impl Render for NestedVerticalCarouselHarness {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            div()
                .id("outer-scroll")
                .w(px(100.))
                .h(px(100.))
                .overflow_y_scroll()
                .track_scroll(&self.outer_handle)
                .child(
                    Carousel::new("vertical-carousel", &self.state)
                        .w(px(100.))
                        .h(px(60.))
                        .child(
                            CarouselContent::new(&self.state)
                                .h_full()
                                .children((0..2).map(|index| {
                                    CarouselItem::new(("vertical-slide", index), index, &self.state)
                                        .child(index.to_string())
                                })),
                        ),
                )
                .child(div().w_full().h(px(400.)))
        }
    }

    fn nested_vertical_carousel<'a>(
        cx: &'a mut TestAppContext,
        state: &Entity<CarouselState>,
    ) -> (ScrollHandle, &'a mut VisualTestContext) {
        let outer_handle = ScrollHandle::new();
        let (_, cx) = cx.add_window_view({
            let state = state.clone();
            let outer_handle = outer_handle.clone();
            move |_, _| NestedVerticalCarouselHarness {
                state,
                outer_handle,
            }
        });
        cx.update(|window, cx| window.draw(cx).clear(cx));
        (outer_handle, cx)
    }

    fn wheel_line(cx: &mut VisualTestContext, lines: f32) {
        cx.simulate_event(ScrollEvent {
            position: point(px(20.), px(20.)),
            delta: ScrollDelta::Lines(point(0., lines)),
            ..Default::default()
        });
    }

    fn swipe(cx: &mut VisualTestContext, delta: f32, touch_phase: TouchPhase) {
        cx.simulate_event(ScrollEvent {
            position: point(px(20.), px(20.)),
            delta: ScrollDelta::Pixels(point(px(0.), px(delta))),
            touch_phase,
            ..Default::default()
        });
    }

    #[gpui::test]
    fn vertical_carousel_hands_scroll_to_parent_at_edge(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let state = cx.update(|cx| {
            cx.new(|_| {
                CarouselState::new(2)
                    .with_axis(Axis::Vertical)
                    .with_selected_index(1)
            })
        });
        let (outer_handle, cx) = nested_vertical_carousel(cx, &state);

        wheel_line(cx, -1.);

        assert_eq!(
            state.read_with(cx, |state, _| state.selected_index()),
            Some(1)
        );
        assert!(outer_handle.offset().y < px(0.));
    }

    #[gpui::test]
    fn vertical_carousel_keeps_a_wheel_burst_away_from_the_parent(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let state = cx.update(|cx| cx.new(|_| CarouselState::new(2).with_axis(Axis::Vertical)));
        let (outer_handle, cx) = nested_vertical_carousel(cx, &state);

        // One notch steps once; the rest of its burst stays here.
        wheel_line(cx, -1.);
        wheel_line(cx, -1.);
        assert_eq!(
            state.read_with(cx, |state, _| state.selected_index()),
            Some(1)
        );
        assert_eq!(outer_handle.offset().y, px(0.));

        // A new notch at the edge scrolls the surrounding document instead.
        cx.executor().advance_clock(SCROLL_EVENT_SEPARATION);
        cx.run_until_parked();
        wheel_line(cx, -1.);
        assert_eq!(
            state.read_with(cx, |state, _| state.selected_index()),
            Some(1)
        );
        assert!(outer_handle.offset().y < px(0.));
    }

    #[gpui::test]
    fn vertical_carousel_owns_a_trackpad_gesture_until_it_ends(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let state = cx.update(|cx| cx.new(|_| CarouselState::new(2).with_axis(Axis::Vertical)));
        let (outer_handle, cx) = nested_vertical_carousel(cx, &state);

        // The swipe overshoots the last item; the leftover stays here.
        swipe(cx, -50., TouchPhase::Started);
        swipe(cx, -50., TouchPhase::Moved);
        swipe(cx, -50., TouchPhase::Moved);
        swipe(cx, 0., TouchPhase::Ended);
        assert_eq!(outer_handle.offset().y, px(0.));
        assert_eq!(
            state.read_with(cx, |state, _| state.selected_index()),
            Some(1)
        );

        // A gesture that begins at the edge scrolls the document instead.
        swipe(cx, -50., TouchPhase::Started);
        assert!(outer_handle.offset().y < px(0.));
    }
}
