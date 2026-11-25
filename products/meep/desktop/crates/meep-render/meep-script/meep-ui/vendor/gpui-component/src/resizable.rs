//! What this design system paints inside a resize handle.
//!
//! Base owns the band, the cursor and the drag; everything here is appearance.
//! A divider rests as the same hairline it has always been, and answers the
//! pointer with a pill that grows and solidifies as the pointer engages it:
//! available, held, being dragged.

use std::rc::Rc;

use gpui::{
    AnyElement, App, Axis, ElementId, IntoElement, ParentElement as _, Pixels, Render, Styled as _,
    Window, deferred, div, prelude::FluentBuilder as _, px,
};
use gpui_base::{
    ResizeHandleContext, ResizeHandleRenderer, ResizeHandleState, Transition, transition,
};

pub use gpui_base::{
    HandleEdge, ResizablePanel, ResizablePanelEvent, ResizablePanelGroup, ResizableState,
    ResizeHandle, resizable_panel,
};

use crate::theme::ActiveTheme as _;

/// How thick the indicator is across the divider it sits on.
const INDICATOR_THICKNESS: Pixels = px(3.);

/// Create a [`ResizablePanelGroup`] with horizontal resizing.
pub fn h_resizable(id: impl Into<ElementId>) -> ResizablePanelGroup {
    gpui_base::h_resizable(id).with_handle_appearance(resize_handle_appearance())
}

/// Create a [`ResizablePanelGroup`] with vertical resizing.
pub fn v_resizable(id: impl Into<ElementId>) -> ResizablePanelGroup {
    gpui_base::v_resizable(id).with_handle_appearance(resize_handle_appearance())
}

/// Create a standalone [`ResizeHandle`] wearing this design system's divider,
/// for an edge no [`ResizablePanelGroup`] owns -- an application's sidebar,
/// say. What the drag resizes is the caller's; see
/// [`gpui_base::resize_handle`].
pub fn resize_handle<T: 'static, E: 'static + Render>(
    id: impl Into<ElementId>,
    axis: Axis,
) -> ResizeHandle<T, E> {
    gpui_base::resize_handle(id, axis).with_appearance(resize_handle_appearance())
}

/// This design system's divider appearance, for a handle that base does not
/// already hand it — a dock edge, or a hand-rolled handle in an application.
pub fn resize_handle_appearance() -> ResizeHandleRenderer {
    Rc::new(|handle, window, cx| Some(render_resize_handle(handle, window, cx)))
}

/// How long the indicator is at each level of engagement, and how solid.
///
/// Idle draws nothing. The hairline is the resting appearance of a divider, and
/// a pill on every divider all the time would be noise in a dock that has a
/// dozen of them.
fn indicator(state: ResizeHandleState) -> (Pixels, f32) {
    match state {
        ResizeHandleState::Idle => (px(0.), 0.),
        ResizeHandleState::Hovered => (px(20.), 0.35),
        ResizeHandleState::Pressed => (px(28.), 0.6),
        ResizeHandleState::Dragging => (px(44.), 0.9),
    }
}

/// The hairline, and the indicator riding on it.
pub(crate) fn render_resize_handle(
    handle: &ResizeHandleContext,
    window: &mut Window,
    cx: &mut App,
) -> AnyElement {
    let axis = handle.axis();
    let (target_length, target_opacity) = indicator(handle.state());
    let motion = cx.theme().motion_tokens();
    let policy = Transition::new(motion.duration_fast).easing(motion.easing_move.clone());

    // Both values are sampled on every frame the handle is rendered, whatever
    // it is showing. A transition asks for a frame only while it is moving, so
    // a resting handle costs nothing; sampling it only while the pill is up
    // would instead leave the retained value frozen wherever it was when the
    // pill went away, and the next hover would start from there.
    let length = transition(
        "resizable-handle-indicator-length",
        target_length,
        policy.clone(),
        window,
        cx,
    );
    // An overshooting theme curve may carry the length past its target, but
    // the opacity has to stay a valid alpha.
    let opacity = transition(
        "resizable-handle-indicator-opacity",
        target_opacity,
        policy,
        window,
        cx,
    )
    .clamp(0., 1.);

    div()
        // The hairline fills the handle's content area exactly, so it has
        // nothing to give: shrinking it collapses the divider.
        .flex_none()
        .flex()
        .bg(cx.theme().border)
        // Along the hairline the pill is far shorter than the line, so centring
        // it there is safe. Across the hairline it is thicker than the line and
        // has to overhang, and neither flex alignment can be trusted to centre
        // an item that overflows -- `justify_center` returns it to the start
        // instead -- so that axis is offset by hand, below.
        .map(|line| match axis {
            Axis::Horizontal => line.w(px(1.)).h_full().items_center(),
            _ => line.h(px(1.)).w_full().items_start().justify_center(),
        })
        .when(length > px(0.5), |line| {
            let pill = div()
                // `flex_none` keeps the one-pixel line from squashing it.
                .flex_none()
                .rounded(cx.theme().radius_full())
                .bg(cx.theme().muted_foreground)
                .opacity(opacity)
                // Half the overhang, pulled back so the pill straddles the
                // hairline evenly.
                .map(|pill| match axis {
                    Axis::Horizontal => pill
                        .w(INDICATOR_THICKNESS)
                        .h(length)
                        .ml((INDICATOR_THICKNESS - px(1.)) * -0.5),
                    _ => pill
                        .h(INDICATOR_THICKNESS)
                        .w(length)
                        .mt((INDICATOR_THICKNESS - px(1.)) * -0.5),
                });
            // A hugging handle's hairline is its container's outermost pixel,
            // so the pill's outer pixel lies past the boundary, where a dock's
            // clip would take it off. Deferring the pill -- and only the pill,
            // only while it is up -- paints it after the tree under the
            // window's mask, so it keeps that pixel. The hairline stays in
            // tree order: a deferred element paints over the application's own
            // deferred content, and a divider that cut through a popover
            // opened from the neighbouring panel is what that looked like.
            line.child(match handle.edge() {
                Some(_) => deferred(pill).into_any_element(),
                None => pill.into_any_element(),
            })
        })
        .into_any_element()
}
