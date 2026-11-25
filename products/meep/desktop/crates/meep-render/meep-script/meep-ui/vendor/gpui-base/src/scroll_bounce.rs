//! Boundary displacement only: the list keeps its clamped logical position.

use crate::overscroll::Overscroll;
use crate::{OngoingScrollExt as _, ScrollbarHandle};
use gpui::{
    AnyElement, App, Bounds, ContentMask, DispatchPhase, Element, ElementId, Global,
    GlobalElementId, Hitbox, HitboxBehavior, HitboxId, InspectorElementId, IntoElement, LayoutId,
    OngoingScroll, Pixels, ScrollDelta, ScrollEvent, TouchPhase, Window, point, px,
};
#[cfg(not(target_family = "wasm"))]
use std::time::Instant;
use std::{cell::RefCell, rc::Rc, time::Duration};
#[cfg(target_family = "wasm")]
use web_time::Instant;

/// Motion tokens for [`ScrollBounce`]: how far a drag stretches the viewport
/// past an edge, and how quickly a released edge returns.
///
/// Base plays the stretch and the return; the feel belongs to the caller.
/// The default is tuned to feel like a `UIScrollView` bounce on iOS and
/// Android, and like an `NSScrollView` bounce elsewhere.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct ScrollBounceMotion {
    tracking: f32,
    response: Duration,
    max_stretch: Option<f32>,
}

impl Default for ScrollBounceMotion {
    /// Tuned to feel like a `UIScrollView` bounce on touch platforms; these
    /// are not UIKit constants. Elsewhere the input is a trackpad, whose
    /// accelerated deltas run far past a finger's travel, so the default is
    /// fitted to an `NSScrollView` measured on macOS: the stretch follows
    /// about 0.075 of the travel, the return decays at 12.5 per second, and
    /// the edge stops 36 px out. AppKit stretches by the unaccelerated
    /// travel, which GPUI does not report; the limit keeps a hard swipe as
    /// short as Finder's.
    fn default() -> Self {
        if cfg!(any(target_os = "ios", target_os = "android")) {
            Self {
                tracking: 0.55,
                response: Duration::from_millis(524),
                max_stretch: None,
            }
        } else {
            Self {
                tracking: 0.075,
                // 2π / 12.5
                response: Duration::from_micros(502_655),
                max_stretch: Some(36.),
            }
        }
    }
}

impl ScrollBounceMotion {
    /// Fraction of finger travel the stretched edge follows at first.
    ///
    /// The edge follows less and less as it approaches the viewport height,
    /// which it never reaches. Tracking is independent of the return, so
    /// slowing the return does not change how the finger feels.
    ///
    /// # Panics
    ///
    /// Panics when `tracking` is not finite or not positive.
    pub fn with_tracking(mut self, tracking: f32) -> Self {
        assert!(
            tracking.is_finite() && tracking > 0.,
            "scroll bounce tracking must be finite and positive"
        );
        self.tracking = tracking;
        self
    }

    /// Time scale of the return once the finger lifts.
    ///
    /// Read the way [`crate::Spring::new`] reads its response: the period one
    /// full oscillation would take without damping, which is the scale the
    /// return is felt at rather than the moment it stops. The return is
    /// critically damped, so it never crosses the edge. A zero response snaps
    /// the edge back on the spot.
    pub fn with_response(mut self, response: Duration) -> Self {
        self.response = response;
        self
    }

    /// The farthest the edge goes past its end, in pixels, whether stretched
    /// or thrown by a fling. The stretch eases into it rather than stopping
    /// at it.
    ///
    /// # Panics
    ///
    /// Panics when `max_stretch` is not finite or not positive.
    pub fn with_max_stretch(mut self, max_stretch: f32) -> Self {
        assert!(
            max_stretch.is_finite() && max_stretch > 0.,
            "scroll bounce max stretch must be finite and positive"
        );
        self.max_stretch = Some(max_stretch);
        self
    }

    /// Fraction of finger travel the stretched edge follows at first.
    pub fn tracking(&self) -> f32 {
        self.tracking
    }

    /// Time scale of the return once the finger lifts.
    pub fn response(&self) -> Duration {
        self.response
    }

    /// The farthest the edge goes past its end, or `None` when only the
    /// viewport height bounds it.
    pub fn max_stretch(&self) -> Option<f32> {
        self.max_stretch
    }

    /// Undamped angular frequency of the return, or `None` when it snaps.
    fn omega(&self) -> Option<f32> {
        let seconds = self.response.as_secs_f32();
        (seconds > 0.).then(|| std::f32::consts::TAU / seconds)
    }
}

/// Adds vertical touch overscroll to an existing scroll viewport.
///
/// The child owns layout, content, and ordinary scrolling; `handle` must be the
/// child's scroll handle. Only unused vertical deltas stretch the viewport.
/// The stable `id` owns gesture and spring state. Change it when replacing the
/// document. Put fixed chrome (scrollbars, toolbars) outside this wrapper.
///
/// Enabled by default where the platform's own scroll views bounce: iOS,
/// Android and macOS. Reduced motion disables displacement. Keyboard and
/// focus remain owned by the child. No colors, padding, or dimensions are
/// imposed.
///
/// Nested scroll areas follow the platform: the innermost one under the
/// pointer takes the whole gesture, at its ends too, and bounces there
/// rather than handing the rest to the area around it. A disabled
/// `ScrollBounce` still scrolls its child and keeps the gesture from the
/// areas around it; it only stops at the ends instead of stretching.
pub struct ScrollBounce {
    id: ElementId,
    handle: Rc<dyn ScrollbarHandle>,
    child: AnyElement,
    enabled: bool,
    scroll_wheel: bool,
    motion: ScrollBounceMotion,
    on_scroll: Option<Rc<dyn Fn(&mut Window, &mut App)>>,
}

impl ScrollBounce {
    pub fn new<H: ScrollbarHandle + Clone>(
        id: impl Into<ElementId>,
        handle: &H,
        child: impl IntoElement,
    ) -> Self {
        Self {
            id: id.into(),
            handle: Rc::new(handle.clone()),
            child: child.into_any_element(),
            enabled: Self::enabled_by_default(),
            scroll_wheel: true,
            motion: ScrollBounceMotion::default(),
            on_scroll: None,
        }
    }

    /// Whether scroll areas bounce on this platform unless told otherwise:
    /// on iOS, Android and macOS, whose own scroll views do.
    pub const fn enabled_by_default() -> bool {
        cfg!(any(
            target_os = "ios",
            target_os = "android",
            target_os = "macos"
        ))
    }

    /// Turn the bounce on or off. Defaults to [`Self::enabled_by_default`].
    pub fn enabled(mut self, enabled: bool) -> Self {
        self.enabled = enabled;
        self
    }

    /// Own vertical scrolling using the shared input overscroll engine.
    /// Precise pixel input can bounce; ordinary line-wheel input only scrolls
    /// and cancels any existing displacement. Keep fixed chrome outside it.
    ///
    /// On by default. Turned off, the child scrolls itself and only its
    /// unused deltas stretch the edge; that needs input that emits `Ended`
    /// at finger release, before momentum, as touch does.
    pub fn scroll_wheel(mut self, enabled: bool) -> Self {
        self.scroll_wheel = enabled;
        self
    }

    /// Set how far a drag stretches past an edge and how the edge returns.
    pub fn motion(mut self, motion: ScrollBounceMotion) -> Self {
        self.motion = motion;
        self
    }

    /// Observe a logical scroll performed when a reverse drag leaves the stretched
    /// region. Runs after the handle update, with no internal state borrowed.
    /// Ordinary child scrolling continues to use the child's own notifications.
    pub fn on_scroll(mut self, handler: impl Fn(&mut Window, &mut App) + 'static) -> Self {
        self.on_scroll = Some(Rc::new(handler));
        self
    }
}

#[derive(Default)]
struct State {
    physics: Physics,
    overscroll: Overscroll,
    sampled_at: Option<Instant>,
    ongoing_scroll: OngoingScroll,
    short_drag_distance: Option<f32>,
    last_wheel_at: Option<Instant>,
    /// Sign of the stream being suppressed, when it is known to be momentum
    /// that cannot reverse. `None` suppresses both directions.
    suppressed_direction: Option<f32>,
}

impl State {
    /// Release the edge. A stretch made outside a gesture is momentum (or a
    /// phaseless wheel) hitting the edge; that stream only pushes outward,
    /// so an inward packet is a new scroll and ends the suppression. After a
    /// gesture's own release the suppressed momentum may point either way.
    fn release(&mut self, from_rest: bool) {
        self.physics.release();
        self.suppressed_direction =
            (from_rest && self.physics.suppress_momentum).then(|| self.physics.offset().signum());
    }
}

// GPUI starts a normal touch pan only after its 8 px touch slop, but a touch
// catching a fling starts at zero displacement. A short catch should stop the
// old fling rather than turn a few fast pixels into a new one.
const CATCH_DRAG_SLOP: f32 = 8.;

// Momentum arrives once per frame until it stops, so a longer silence means
// the suppressed stream has ended. Smooth-scrolling mouse drivers on macOS
// send precise deltas with no phase: they never send the `Started` that
// otherwise ends suppression, and would stay locked after one bounce.
const MOMENTUM_GAP: Duration = Duration::from_millis(250);

/// Which scroll area under the pointer takes the current wheel event.
///
/// Capture runs from the outside in, so every area that could scroll writes
/// itself here before its child paints, and the innermost one is the last
/// to write. Each then acts, from the inside out, only if it is still the
/// one written.
#[derive(Default)]
struct ScrollOwner(Option<HitboxId>);

impl Global for ScrollOwner {}

/// Take the current wheel event from the scroll areas around `hitbox`.
/// Call it in the capture phase, from a listener registered before the
/// children paint, whenever the area would scroll for the event.
pub(crate) fn claim_scroll(hitbox: HitboxId, cx: &mut App) {
    cx.default_global::<ScrollOwner>().0 = Some(hitbox);
}

fn owns_scroll(hitbox: HitboxId, cx: &App) -> bool {
    cx.try_global::<ScrollOwner>()
        .is_some_and(|owner| owner.0 == Some(hitbox))
}

/// `ScrollbarHandle` has no `max_offset`; recover it from the definition
/// `content_size = viewport + max_offset`. Both dispatch phases clamp against
/// this bound and must agree on it.
fn max_scroll_extent(handle: &dyn ScrollbarHandle) -> Pixels {
    (handle.content_size().height - handle.viewport_bounds().size.height).max(px(0.))
}

#[doc(hidden)]
pub struct ScrollBouncePrepaintState {
    state: Rc<RefCell<State>>,
    hitbox: Hitbox,
}

impl IntoElement for ScrollBounce {
    type Element = Self;
    fn into_element(self) -> Self {
        self
    }
}

impl Element for ScrollBounce {
    type RequestLayoutState = ();
    type PrepaintState = ScrollBouncePrepaintState;

    fn id(&self) -> Option<ElementId> {
        Some(self.id.clone())
    }
    fn source_location(&self) -> Option<&'static std::panic::Location<'static>> {
        None
    }

    fn request_layout(
        &mut self,
        _: Option<&GlobalElementId>,
        _: Option<&InspectorElementId>,
        window: &mut Window,
        cx: &mut App,
    ) -> (LayoutId, ()) {
        (self.child.request_layout(window, cx), ())
    }

    fn prepaint(
        &mut self,
        id: Option<&GlobalElementId>,
        _: Option<&InspectorElementId>,
        bounds: Bounds<Pixels>,
        _: &mut (),
        window: &mut Window,
        cx: &mut App,
    ) -> Self::PrepaintState {
        let state = window.with_element_state(
            id.expect("ScrollBounce has an id"),
            |state: Option<Rc<RefCell<State>>>, _| {
                let state = state.unwrap_or_default();
                (state.clone(), state)
            },
        );
        let offset = {
            let mut state = state.borrow_mut();
            if !self.enabled || cx.reduce_motion() {
                *state = State::default();
            }
            if self.scroll_wheel {
                state.overscroll.set_motion(self.motion);
                if max_scroll_extent(self.handle.as_ref()) <= px(0.) {
                    state.overscroll.reset();
                }
                if state.overscroll.step(cx.background_executor().now()) {
                    window.request_animation_frame();
                }
                state.overscroll.offset()
            } else {
                state.physics.motion = self.motion;
                let now = Instant::now();
                let elapsed = state
                    .sampled_at
                    .replace(now)
                    .map_or(0., |at| now.duration_since(at).as_secs_f32());
                if state.physics.step(elapsed) {
                    window.request_animation_frame();
                }
                state.physics.offset()
            }
        };
        let hitbox = window.insert_hitbox(bounds, HitboxBehavior::Normal);
        window.with_content_mask(Some(ContentMask { bounds }), |window| {
            window.with_element_offset(point(px(0.), px(offset)), |window| {
                self.child.prepaint(window, cx);
            });
        });
        // The child's fresh metrics can remove overflow during a drag.
        // Reset against those metrics as well, and repaint any displaced frame.
        if self.scroll_wheel && max_scroll_extent(self.handle.as_ref()) <= px(0.) {
            let mut state = state.borrow_mut();
            let displaced = state.overscroll.offset() != 0.;
            state.overscroll.reset();
            if displaced {
                window.request_animation_frame();
            }
        }
        ScrollBouncePrepaintState { state, hitbox }
    }

    fn paint(
        &mut self,
        _: Option<&GlobalElementId>,
        _: Option<&InspectorElementId>,
        bounds: Bounds<Pixels>,
        _: &mut (),
        prepaint: &mut Self::PrepaintState,
        window: &mut Window,
        cx: &mut App,
    ) {
        if self.scroll_wheel {
            let hitbox = prepaint.hitbox.id;
            let handle = self.handle.clone();
            window.on_mouse_event(move |_: &ScrollEvent, phase, window, cx| {
                if phase == DispatchPhase::Capture
                    && hitbox.should_handle_scroll(window)
                    && max_scroll_extent(handle.as_ref()) > px(0.)
                {
                    claim_scroll(hitbox, cx);
                }
            });
        }
        if self.enabled && !self.scroll_wheel && !cx.reduce_motion() {
            let state = prepaint.state.clone();
            let hitbox = prepaint.hitbox.id;
            let handle = self.handle.clone();
            let view = window.current_view();
            let on_scroll = self.on_scroll.clone();
            let mut before = 0.;
            let mut allow_end_bounce = false;
            window.on_mouse_event(move |event: &ScrollEvent, phase, window, cx| {
                let ScrollDelta::Pixels(mut delta) = event.delta else {
                    if phase == DispatchPhase::Capture && hitbox.should_handle_scroll(window) {
                        let mut state = state.borrow_mut();
                        let displaced = state.physics.offset() != 0.;
                        *state = State::default();
                        drop(state);
                        if displaced {
                            cx.notify(view);
                        }
                    }
                    return;
                };
                if !hitbox.should_handle_scroll(window) {
                    return;
                }
                let mut state = state.borrow_mut();
                // Lock the gesture to the axis it started on, so a diagonal
                // swipe cannot wobble out of the stretch from one packet to
                // the next. Both dispatch phases see the same packet, and the
                // lock gives both the same answer.
                state
                    .ongoing_scroll
                    .lock_axis(&mut delta, event.touch_phase);
                if delta.x.abs() > delta.y.abs() {
                    return;
                }
                let ended = matches!(event.touch_phase, TouchPhase::Ended | TouchPhase::Cancelled);
                let mut scrolled = false;
                let mut changed = false;
                if phase == DispatchPhase::Capture {
                    before = handle.offset().y.as_f32();
                    if event.touch_phase == TouchPhase::Started {
                        state.short_drag_distance = (delta.y == px(0.)).then_some(0.);
                        state.physics.begin(bounds.size.height.as_f32());
                    } else if let Some(distance) = state.short_drag_distance.as_mut() {
                        *distance += delta.y.as_f32().abs();
                        if *distance > CATCH_DRAG_SLOP {
                            state.short_drag_distance = None;
                        }
                    }
                    let suppress_short_drag_momentum = if ended {
                        state.short_drag_distance.take().is_some()
                            && event.touch_phase == TouchPhase::Ended
                    } else {
                        false
                    };
                    // The current Ended packet may still cross an edge; only
                    // momentum packets after it should be suppressed.
                    allow_end_bounce = suppress_short_drag_momentum;
                    let now = cx.background_executor().now();
                    let paused = state
                        .last_wheel_at
                        .replace(now)
                        .is_some_and(|at| now.saturating_duration_since(at) >= MOMENTUM_GAP);
                    let reversed = state.suppressed_direction.is_some_and(|direction| {
                        delta.y != px(0.) && delta.y.as_f32().signum() != direction
                    });
                    if paused || reversed {
                        state.physics.suppress_momentum = false;
                    }
                    if state.physics.suppress_momentum {
                        cx.stop_propagation();
                        return;
                    }
                    if state.physics.offset() != 0. {
                        // Outside a gesture (a phaseless wheel once suppression
                        // lifts) a packet grabs the returning edge and lets it
                        // go again, as it would at rest.
                        let from_rest = !state.physics.dragging;
                        if from_rest {
                            state.physics.begin(bounds.size.height.as_f32());
                        }
                        let remainder = state.physics.pull(delta.y.as_f32());
                        if remainder != 0. {
                            let max = max_scroll_extent(handle.as_ref());
                            let mut offset = handle.offset();
                            offset.y = px(before + remainder).clamp(-max, px(0.));
                            handle.set_offset(offset);
                            scrolled = true;
                        }
                        if ended || from_rest {
                            state.release(from_rest);
                        }
                        changed = true;
                        cx.stop_propagation();
                    } else if ended {
                        state.physics.release();
                    }
                    if suppress_short_drag_momentum {
                        state.physics.suppress_momentum = true;
                        state.suppressed_direction = None;
                    }
                } else {
                    // Div applies deltas immediately but clamps during its next
                    // prepaint. Clamp here so that boundary deltas are not
                    // mistaken for consumed scrolling (ListState clamps eagerly).
                    let mut offset = handle.offset();
                    let max = max_scroll_extent(handle.as_ref());
                    let clamped = offset.y.clamp(-max, px(0.));
                    if clamped != offset.y {
                        offset.y = clamped;
                        handle.set_offset(offset);
                    }
                    let after = offset.y.as_f32();
                    let requested = delta.y.as_f32();
                    // A List can coalesce several packets against one painted
                    // scroll position. Their offset difference alone does not
                    // prove overscroll, especially after direction changes or
                    // a zero-delta Ended packet from a trackpad.
                    let at_outward_edge = (requested > 0. && offset.y == px(0.))
                        || (requested < 0. && offset.y == -max);
                    let residual =
                        (requested - (after - before)).clamp(requested.min(0.), requested.max(0.));
                    if at_outward_edge
                        && residual.abs() > 0.01
                        && (!state.physics.suppress_momentum || allow_end_bounce)
                    {
                        let dragging = state.physics.dragging;
                        if !dragging {
                            state.physics.begin(bounds.size.height.as_f32());
                        }
                        state.physics.pull(residual);
                        if !dragging || ended {
                            state.release(!dragging);
                        }
                        changed = true;
                    }
                }
                if changed {
                    state.sampled_at = Some(Instant::now());
                }
                drop(state);
                if changed {
                    cx.notify(view);
                }
                if scrolled && let Some(handler) = &on_scroll {
                    handler(window, cx);
                }
            });
        }
        window.with_content_mask(Some(ContentMask { bounds }), |window| {
            self.child.paint(window, cx)
        });
        // After the children, so that the areas inside act first.
        if self.scroll_wheel {
            let bounces = self.enabled && !cx.reduce_motion();
            let state = prepaint.state.clone();
            let hitbox = prepaint.hitbox.id;
            let handle = self.handle.clone();
            let view = window.current_view();
            let on_scroll = self.on_scroll.clone();
            window.on_mouse_event(move |event: &ScrollEvent, phase, window, cx| {
                if phase != DispatchPhase::Capture
                    || !hitbox.should_handle_scroll(window)
                    || !owns_scroll(hitbox, cx)
                {
                    return;
                }
                let mut delta = event.delta.pixel_delta(window.line_height());
                let mut state = state.borrow_mut();
                state
                    .ongoing_scroll
                    .lock_axis(&mut delta, event.touch_phase);
                let max = max_scroll_extent(handle.as_ref());
                if max <= px(0.) {
                    state.overscroll.reset();
                    return;
                }
                if delta.x.abs() > delta.y.abs() {
                    return;
                }
                let before = handle.offset();
                let changed = if !bounces || matches!(event.delta, ScrollDelta::Lines(_)) {
                    let displaced = state.overscroll.offset() != 0.;
                    state.overscroll.reset();
                    let mut offset = before;
                    offset.y = (before.y + delta.y).clamp(-max, px(0.));
                    handle.set_offset(offset);
                    displaced
                } else {
                    state.overscroll.packet(
                        delta.y.as_f32(),
                        event.touch_phase,
                        bounds.size.height.as_f32(),
                        cx.background_executor().now(),
                        |dy| {
                            let before = handle.offset();
                            let mut offset = before;
                            let requested = before.y + px(dy);
                            offset.y = requested.clamp(-max, px(0.));
                            handle.set_offset(offset);
                            // Only clamping leaves unused input; subtraction
                            // can leave a rounding residue inside the list.
                            if offset.y == requested {
                                dy
                            } else {
                                (offset.y - before.y).as_f32()
                            }
                        },
                    )
                };
                let scrolled = handle.offset() != before;
                drop(state);
                cx.stop_propagation();
                if changed || scrolled {
                    cx.notify(view);
                }
                if scrolled && let Some(handler) = &on_scroll {
                    handler(window, cx);
                }
            });
        }
    }
}

/// The largest outward speed, at most `speed`, that lets an edge at
/// `position` go no farther out than `max`.
///
/// The edge then follows `(position + speed * t) * e^(-ωt)`, which peaks at
/// `speed / ω * e^(ω * position / speed - 1)` when the speed is enough to
/// carry it outward at all.
fn limit_throw(position: f32, speed: f32, omega: f32, max: f32) -> f32 {
    let peak = |speed: f32| {
        if speed <= omega * position {
            position
        } else {
            speed / omega * (omega * position / speed - 1.).exp()
        }
    };
    if peak(speed) <= max {
        return speed;
    }
    let (mut low, mut high) = (0., speed);
    for _ in 0..24 {
        let mid = (low + high) / 2.;
        if peak(mid) <= max {
            low = mid;
        } else {
            high = mid;
        }
    }
    low
}

/// The stretch past an edge and its return, shared with the input's own
/// scrolling.
#[derive(Default)]
pub(crate) struct Physics {
    position: f32,
    velocity: f32,
    dragging: bool,
    suppress_momentum: bool,
    extent: f32,
    motion: ScrollBounceMotion,
}

impl Physics {
    pub(crate) fn set_motion(&mut self, motion: ScrollBounceMotion) {
        self.motion = motion;
    }

    pub(crate) fn reset(&mut self) {
        *self = Self {
            motion: self.motion,
            ..Self::default()
        };
    }
    pub(crate) fn is_dragging(&self) -> bool {
        self.dragging
    }

    /// Whether a released edge is still on its way.
    pub(crate) fn is_moving(&self) -> bool {
        !self.dragging && (self.position != 0. || self.velocity != 0.)
    }

    pub(crate) fn offset(&self) -> f32 {
        if self.dragging {
            let d = self.extent.max(1.);
            let tracking = self.motion.tracking;
            let stretch = self.position * tracking / (1. + tracking * self.position.abs() / d);
            match self.motion.max_stretch {
                // Follows the stretch closely at first, then eases into the limit.
                Some(max) => max * (stretch / max).tanh(),
                None => stretch,
            }
        } else {
            self.position
        }
    }

    pub(crate) fn begin(&mut self, extent: f32) {
        let offset = self.offset();
        // A displaced edge keeps the extent it was stretched under. The
        // rubber-band curve saturates at the extent, so re-reading a viewport
        // that shrank mid-return (rotation, keyboard) could not place the
        // finger where the edge is: it would snap, then need a long pull back.
        if offset == 0. || self.extent <= 0. {
            self.extent = extent.max(1.);
        }
        // Invert the curves so grabbing a returning edge is continuous.
        let stretch = match self.motion.max_stretch {
            Some(max) => max * (offset / max).clamp(-0.999, 0.999).atanh(),
            None => offset,
        };
        let tracking = self.motion.tracking;
        self.position = stretch / (tracking * (1. - stretch.abs() / self.extent).max(0.01));
        self.velocity = 0.;
        self.dragging = true;
        self.suppress_momentum = false;
    }

    /// Apply finger displacement. Return the part that crosses back into the list.
    pub(crate) fn pull(&mut self, delta: f32) -> f32 {
        let previous = self.position;
        let next = previous + delta;
        if previous != 0. && previous.signum() != next.signum() {
            self.position = 0.;
            next
        } else {
            self.position = next;
            0.
        }
    }

    pub(crate) fn release(&mut self) {
        self.position = self.offset();
        self.dragging = false;
        if self.position != 0. {
            self.suppress_momentum = true;
        }
    }

    /// Let go of the edge the way AppKit does: from wherever it is, it
    /// returns at full speed, and it carries `velocity` outward on the way.
    /// Its path is `(x + velocity * t) * e^(-ωt)`, so an edge at rest is
    /// thrown out and back, and an edge let go while still being pushed
    /// returns a little later. It never crosses the boundary: velocity
    /// pointing back inward is dropped.
    pub(crate) fn let_go(&mut self, velocity: f32) {
        self.position = self.offset();
        self.dragging = false;
        let Some(omega) = self.motion.omega() else {
            self.position = 0.;
            self.velocity = 0.;
            return;
        };
        let mut outward = if self.position * velocity >= 0. {
            velocity
        } else {
            0.
        };
        if let Some(max) = self.motion.max_stretch {
            outward =
                outward.signum() * limit_throw(self.position.abs(), outward.abs(), omega, max);
        }
        self.velocity = outward - omega * self.position;
    }

    /// Exact critically damped spring integration, independent of refresh rate.
    pub(crate) fn step(&mut self, seconds: f32) -> bool {
        if self.dragging || (self.position == 0. && self.velocity == 0.) {
            return false;
        }
        let Some(omega) = self.motion.omega() else {
            self.position = 0.;
            self.velocity = 0.;
            return false;
        };
        let decay = (-omega * seconds).exp();
        let c = self.velocity + omega * self.position;
        self.position = (self.position + c * seconds) * decay;
        self.velocity = (self.velocity - omega * c * seconds) * decay;
        if self.position.abs() < 0.1 && self.velocity.abs() < 1. {
            self.position = 0.;
            self.velocity = 0.;
            false
        } else {
            true
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use gpui::{
        Context, InteractiveElement as _, ParentElement as _, Render, ScrollHandle,
        StatefulInteractiveElement as _, Styled as _, TestAppContext, VisualTestContext, div,
    };

    struct ScrollTest {
        handle: ScrollHandle,
        enabled: bool,
    }

    impl Render for ScrollTest {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            div().p(px(20.)).child(
                ScrollBounce::new(
                    "bounce",
                    &self.handle,
                    div()
                        .id("viewport")
                        .w(px(200.))
                        .h(px(200.))
                        .overflow_y_scroll()
                        .track_scroll(&self.handle)
                        .child(div().h(px(600.)).w_full()),
                )
                .enabled(self.enabled)
                .scroll_wheel(false),
            )
        }
    }

    fn draw(cx: &mut VisualTestContext) {
        cx.update(|window, cx| window.draw(cx).clear(cx));
    }

    fn scroll(cx: &mut VisualTestContext, delta: f32, phase: TouchPhase) {
        cx.simulate_event(ScrollEvent {
            position: point(px(100.), px(100.)),
            delta: ScrollDelta::Pixels(point(px(0.), px(delta))),
            touch_phase: phase,
            ..Default::default()
        });
    }

    struct WheelViewport(ScrollHandle, Pixels);

    impl Render for WheelViewport {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            ScrollBounce::new(
                "wheel-bounce",
                &self.0,
                div()
                    .id("wheel-viewport")
                    .w(px(200.))
                    .h(px(200.))
                    .overflow_y_scroll()
                    .track_scroll(&self.0)
                    .child(div().h(self.1).w_full()),
            )
            .enabled(true)
            .scroll_wheel(true)
        }
    }

    #[gpui::test]
    fn fractional_wheel_input_keeps_scrolling_deep_in_a_long_list(cx: &mut TestAppContext) {
        for delta in [-0.09_f32, 0.09] {
            let mut app = cx.new_app();
            let handle = ScrollHandle::new();
            let (_, cx) = app.add_window_view({
                let handle = handle.clone();
                move |_, _| WheelViewport(handle, px(2_000_000.))
            });
            draw(cx);
            handle.set_offset(point(px(0.), px(-1_000_000.)));
            draw(cx);
            let origin = handle.bounds().origin;
            scroll(cx, delta, TouchPhase::Started);
            scroll(cx, delta.signum() * 20., TouchPhase::Moved);
            scroll(cx, 0., TouchPhase::Ended);
            cx.executor().advance_clock(Duration::from_millis(16));
            draw(cx);
            scroll(cx, delta, TouchPhase::Moved);
            scroll(cx, 0., TouchPhase::Started);
            scroll(cx, delta.signum() * 20., TouchPhase::Moved);
            draw(cx);
            // Here each 0.09px delta rounds to 0.0625px in the stored offset.
            let expected = -1_000_000. + delta.signum() * 40.125;
            assert!((handle.offset().y.as_f32() - expected).abs() < 0.001);
            assert_eq!(handle.bounds().origin, origin);
        }
    }

    #[gpui::test]
    fn ordinary_mouse_wheel_keeps_the_shared_viewport_undisplaced(cx: &mut TestAppContext) {
        let handle = ScrollHandle::new();
        let (_, cx) = cx.add_window_view({
            let handle = handle.clone();
            move |_, _| WheelViewport(handle, px(600.))
        });
        draw(cx);
        let origin = handle.bounds().origin;
        cx.simulate_event(ScrollEvent {
            position: point(px(100.), px(100.)),
            delta: ScrollDelta::Lines(point(0., -100.)),
            ..Default::default()
        });
        draw(cx);
        cx.executor().advance_clock(Duration::from_millis(16));
        draw(cx);
        assert_eq!(handle.offset().y, -handle.max_offset().y);
        assert_eq!(handle.bounds().origin, origin);
    }

    #[gpui::test]
    fn wheel_scrolling_interrupts_the_shared_return(cx: &mut TestAppContext) {
        let handle = ScrollHandle::new();
        let (_, cx) = cx.add_window_view({
            let handle = handle.clone();
            move |_, _| WheelViewport(handle, px(600.))
        });
        draw(cx);
        let wheel = |cx: &mut VisualTestContext, dy| {
            cx.simulate_event(ScrollEvent {
                position: point(px(100.), px(100.)),
                delta: ScrollDelta::Lines(point(0., dy)),
                ..Default::default()
            });
        };
        scroll(cx, -1000., TouchPhase::Started);
        scroll(cx, 0., TouchPhase::Ended);
        draw(cx);
        assert_eq!(handle.offset().y, -handle.max_offset().y);
        cx.executor().advance_clock(Duration::from_millis(200));
        draw(cx);
        let end = handle.offset().y;
        wheel(cx, 2.);
        assert!(
            handle.offset().y > end,
            "the new wheel input scrolls before the next frame"
        );
        draw(cx);
    }

    /// A scroll area with a shorter one inside it, 100 px down.
    struct Nested {
        outer: ScrollHandle,
        inner: ScrollHandle,
        inner_enabled: bool,
    }

    impl Render for Nested {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            ScrollBounce::new(
                "outer",
                &self.outer,
                div()
                    .id("outer-viewport")
                    .w(px(200.))
                    .h(px(300.))
                    .overflow_y_scroll()
                    .track_scroll(&self.outer)
                    .child(div().h(px(100.)).w_full())
                    .child(
                        ScrollBounce::new(
                            "inner",
                            &self.inner,
                            div()
                                .id("inner-viewport")
                                .w(px(200.))
                                .h(px(100.))
                                .overflow_y_scroll()
                                .track_scroll(&self.inner)
                                .child(div().h(px(400.)).w_full()),
                        )
                        .enabled(self.inner_enabled),
                    )
                    .child(div().h(px(600.)).w_full()),
            )
            .enabled(true)
        }
    }

    fn nested(cx: &mut TestAppContext, inner_enabled: bool) -> (Nested, &mut VisualTestContext) {
        let (outer, inner) = (ScrollHandle::new(), ScrollHandle::new());
        let (_, cx) = cx.add_window_view({
            let (outer, inner) = (outer.clone(), inner.clone());
            move |_, _| Nested {
                outer,
                inner,
                inner_enabled,
            }
        });
        draw(cx);
        (
            Nested {
                outer,
                inner,
                inner_enabled,
            },
            cx,
        )
    }

    fn scroll_at(cx: &mut VisualTestContext, y: f32, delta: f32, phase: TouchPhase) {
        cx.simulate_event(ScrollEvent {
            position: point(px(100.), px(y)),
            delta: ScrollDelta::Pixels(point(px(0.), px(delta))),
            touch_phase: phase,
            ..Default::default()
        });
        draw(cx);
    }

    #[gpui::test]
    fn the_innermost_area_takes_the_whole_gesture(cx: &mut TestAppContext) {
        let (areas, cx) = nested(cx, true);
        let inner_origin = areas.inner.bounds().origin.y;
        scroll_at(cx, 150., 0., TouchPhase::Started);
        scroll_at(cx, 150., -200., TouchPhase::Moved);
        assert_eq!(areas.inner.offset().y, px(-200.), "the inner area scrolls");
        assert_eq!(areas.outer.offset().y, px(0.), "the outer one does not");
        // At its end the inner area stretches instead of handing over.
        scroll_at(cx, 150., -200., TouchPhase::Moved);
        assert_eq!(areas.inner.offset().y, px(-300.));
        assert_eq!(areas.outer.offset().y, px(0.));
        assert!(areas.inner.bounds().origin.y < inner_origin);
        // Outside the inner area, the outer one scrolls.
        scroll_at(cx, 150., 0., TouchPhase::Ended);
        scroll_at(cx, 20., -50., TouchPhase::Moved);
        assert_eq!(areas.outer.offset().y, px(-50.));
    }

    #[gpui::test]
    fn a_disabled_inner_area_still_keeps_its_scroll(cx: &mut TestAppContext) {
        let (areas, cx) = nested(cx, false);
        let inner_origin = areas.inner.bounds().origin.y;
        scroll_at(cx, 150., -50., TouchPhase::Moved);
        assert_eq!(areas.inner.offset().y, px(-50.), "the inner area scrolls");
        assert_eq!(areas.outer.offset().y, px(0.), "the outer one does not");
        // At its end it stops without stretching.
        scroll_at(cx, 150., -500., TouchPhase::Moved);
        assert_eq!(areas.inner.offset().y, px(-300.));
        assert_eq!(areas.inner.bounds().origin.y, inner_origin);
        assert_eq!(areas.outer.offset().y, px(0.));
    }

    struct ListTest(gpui::ListState);

    impl Render for ListTest {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            ScrollBounce::new(
                "bounce-list",
                &self.0,
                gpui::list(self.0.clone(), |_, _, _| {
                    div().h(px(40.)).into_any_element()
                })
                .w(px(200.))
                .h(px(200.)),
            )
            .enabled(true)
            .scroll_wheel(false)
        }
    }

    #[gpui::test]
    fn list_reverse_drag_preserves_events_before_the_next_frame(cx: &mut TestAppContext) {
        let handle = gpui::ListState::new(30, gpui::ListAlignment::Top, px(0.)).measure_all();
        let (_, cx) = cx.add_window_view({
            let handle = handle.clone();
            move |_, _| ListTest(handle)
        });
        draw(cx);
        scroll(cx, 100., TouchPhase::Started);
        scroll(cx, -140., TouchPhase::Moved);
        assert_eq!(handle.offset().y, px(-40.));
        scroll(cx, -10., TouchPhase::Moved);
        draw(cx);
        assert_eq!(handle.offset().y, px(-50.));
    }

    #[gpui::test]
    fn trackpad_release_between_frames_does_not_bounce_in_the_middle(cx: &mut TestAppContext) {
        let handle = gpui::ListState::new(30, gpui::ListAlignment::Top, px(0.)).measure_all();
        let (_, cx) = cx.add_window_view({
            let handle = handle.clone();
            move |_, _| ListTest(handle)
        });
        draw(cx);
        handle.set_offset(point(px(0.), px(-400.)));
        draw(cx);
        let origin = handle.viewport_bounds().origin.y;
        // Unlike simulate_event (which may draw after each event), dispatch
        // both packets within one update to exercise native input coalescing.
        cx.update(|window, cx| {
            for (delta, phase) in [(-30., TouchPhase::Started), (0., TouchPhase::Ended)] {
                window.dispatch_event(
                    gpui::PlatformInput::Scroll(ScrollEvent {
                        position: point(px(100.), px(100.)),
                        delta: ScrollDelta::Pixels(point(px(0.), px(delta))),
                        touch_phase: phase,
                        ..Default::default()
                    }),
                    cx,
                );
            }
        });
        draw(cx);
        assert_eq!(handle.viewport_bounds().origin.y, origin);
        assert!(handle.offset().y < px(-300.) && handle.offset().y > px(-500.));
    }

    #[gpui::test]
    fn trackpad_direction_change_between_frames_does_not_bounce_in_the_middle(
        cx: &mut TestAppContext,
    ) {
        let handle = gpui::ListState::new(30, gpui::ListAlignment::Top, px(0.)).measure_all();
        let (_, cx) = cx.add_window_view({
            let handle = handle.clone();
            move |_, _| ListTest(handle)
        });
        draw(cx);
        handle.set_offset(point(px(0.), px(-400.)));
        draw(cx);
        let origin = handle.viewport_bounds().origin.y;
        cx.update(|window, cx| {
            for (delta, phase) in [(-30., TouchPhase::Started), (5., TouchPhase::Moved)] {
                window.dispatch_event(
                    gpui::PlatformInput::Scroll(ScrollEvent {
                        position: point(px(100.), px(100.)),
                        delta: ScrollDelta::Pixels(point(px(0.), px(delta))),
                        touch_phase: phase,
                        ..Default::default()
                    }),
                    cx,
                );
            }
        });
        draw(cx);
        assert!(handle.offset().y < px(-300.) && handle.offset().y > px(-500.));
        assert_eq!(handle.viewport_bounds().origin.y, origin);
    }

    #[gpui::test]
    fn list_stretches_only_the_distance_past_either_edge(cx: &mut TestAppContext) {
        for (start, delta, end) in [(-30., 50., 0.), (-970., -50., -1000.)] {
            let mut app = cx.new_app();
            let handle = gpui::ListState::new(30, gpui::ListAlignment::Top, px(0.)).measure_all();
            let (_, cx) = app.add_window_view({
                let handle = handle.clone();
                move |_, _| ListTest(handle)
            });
            draw(cx);
            handle.set_offset(point(px(0.), px(start)));
            draw(cx);
            let origin = handle.viewport_bounds().origin.y;
            scroll(cx, delta, TouchPhase::Started);
            draw(cx);
            assert_eq!(handle.offset().y, px(end));
            let stretch = (handle.viewport_bounds().origin.y - origin).as_f32();
            assert_eq!(stretch.signum(), delta.signum());
            // Of the 50 px input, 30 px is ordinary scrolling. Only the
            // remaining 20 px may be rubber-banded (resistance reduces it).
            assert!(stretch.abs() > 0. && stretch.abs() < 20.);
        }
    }

    #[gpui::test]
    fn reverse_drag_consumes_stretch_before_scrolling_content(cx: &mut TestAppContext) {
        let handle = ScrollHandle::new();
        let (_, cx) = cx.add_window_view({
            let handle = handle.clone();
            move |_, _| ScrollTest {
                handle,
                enabled: true,
            }
        });
        draw(cx);
        let origin = handle.bounds().origin.y;
        assert_eq!(origin, px(20.));
        scroll(cx, 100., TouchPhase::Started);
        draw(cx);
        assert_eq!(handle.offset().y, px(0.));
        assert!(handle.bounds().origin.y > origin);
        scroll(cx, -140., TouchPhase::Moved);
        draw(cx);
        assert_eq!(handle.offset().y, px(-40.));
        assert_eq!(handle.bounds().origin.y, origin);
    }

    #[gpui::test]
    fn touch_release_ignores_momentum_until_a_new_touch_takes_over(cx: &mut TestAppContext) {
        let handle = ScrollHandle::new();
        let (_, cx) = cx.add_window_view({
            let handle = handle.clone();
            move |_, _| ScrollTest {
                handle,
                enabled: true,
            }
        });
        draw(cx);
        let origin = handle.bounds().origin.y;
        scroll(cx, 100., TouchPhase::Started);
        draw(cx);
        assert!(handle.bounds().origin.y > origin);
        scroll(cx, 0., TouchPhase::Ended);
        draw(cx);
        let released = handle.bounds().origin.y;
        // The iOS backend emits Moved packets for momentum after finger-up.
        // Even a large inward packet must not move the logical list while
        // the returning edge owns this gesture.
        scroll(cx, -400., TouchPhase::Moved);
        draw(cx);
        assert_eq!(handle.offset().y, px(0.));
        assert!(handle.bounds().origin.y <= released);
        // A new finger-down must end suppression and take over immediately.
        scroll(cx, 0., TouchPhase::Started);
        scroll(cx, -250., TouchPhase::Moved);
        draw(cx);
        assert!(handle.offset().y < px(0.));
        assert_eq!(handle.bounds().origin.y, origin);
    }

    #[gpui::test]
    fn phaseless_wheel_scrolls_back_right_after_bouncing(cx: &mut TestAppContext) {
        let handle = gpui::ListState::new(30, gpui::ListAlignment::Top, px(0.)).measure_all();
        let (_, cx) = cx.add_window_view({
            let handle = handle.clone();
            move |_, _| ListTest(handle)
        });
        draw(cx);
        handle.set_offset(point(px(0.), px(-1000.)));
        draw(cx);
        let origin = handle.viewport_bounds().origin.y;
        // Smooth-scrolling mouse drivers on macOS: precise deltas, no phase.
        scroll(cx, -50., TouchPhase::Moved);
        draw(cx);
        assert!(handle.viewport_bounds().origin.y < origin);
        scroll(cx, 200., TouchPhase::Moved);
        draw(cx);
        assert!(handle.offset().y > px(-1000.));
        assert_eq!(handle.viewport_bounds().origin.y, origin);
    }

    #[gpui::test]
    fn phaseless_wheel_bounces_again_only_after_a_pause(cx: &mut TestAppContext) {
        let handle = ScrollHandle::new();
        let (_, cx) = cx.add_window_view({
            let handle = handle.clone();
            move |_, _| ScrollTest {
                handle,
                enabled: true,
            }
        });
        draw(cx);
        scroll(cx, 50., TouchPhase::Moved);
        draw(cx);
        let bounced = handle.bounds().origin.y;
        // Momentum after an edge hit keeps pushing outward; it must not
        // stretch further.
        scroll(cx, 50., TouchPhase::Moved);
        draw(cx);
        assert!(handle.bounds().origin.y <= bounced);
        cx.executor().advance_clock(MOMENTUM_GAP);
        scroll(cx, 50., TouchPhase::Moved);
        draw(cx);
        assert!(handle.bounds().origin.y > bounced);
        assert_eq!(handle.offset().y, px(0.));
    }

    #[gpui::test]
    fn tiny_drag_catching_momentum_does_not_start_a_reverse_fling(cx: &mut TestAppContext) {
        let handle = ScrollHandle::new();
        let (_, cx) = cx.add_window_view({
            let handle = handle.clone();
            move |_, _| ScrollTest {
                handle,
                enabled: true,
            }
        });
        draw(cx);
        handle.set_offset(point(px(0.), px(-200.)));
        draw(cx);

        // GPUI ends the old momentum stream, then starts a drag at zero
        // displacement when a finger catches the moving content.
        scroll(cx, -60., TouchPhase::Started);
        scroll(cx, 0., TouchPhase::Ended);
        draw(cx);
        scroll(cx, -100., TouchPhase::Moved);
        draw(cx);
        scroll(cx, 0., TouchPhase::Ended);
        draw(cx);
        let before_catch = handle.offset().y;
        assert!(before_catch < px(0.));
        scroll(cx, 0., TouchPhase::Started);
        scroll(cx, 8., TouchPhase::Moved);
        scroll(cx, 0., TouchPhase::Ended);
        draw(cx);
        let stopped = handle.offset().y;
        assert_eq!(stopped, before_catch + px(8.));

        // The recognizer can synthesize a large reverse momentum packet from
        // that 8 px movement. It must not move the logical viewport.
        scroll(cx, 100., TouchPhase::Moved);
        draw(cx);
        assert_eq!(handle.offset().y, stopped);

        // A fresh gesture restores ordinary scrolling and momentum.
        scroll(cx, -20., TouchPhase::Started);
        scroll(cx, 0., TouchPhase::Ended);
        scroll(cx, -10., TouchPhase::Moved);
        draw(cx);
        assert_eq!(handle.offset().y, stopped - px(30.));
    }

    #[gpui::test]
    fn deliberate_drag_after_catching_momentum_can_fling(cx: &mut TestAppContext) {
        let handle = ScrollHandle::new();
        let (_, cx) = cx.add_window_view({
            let handle = handle.clone();
            move |_, _| ScrollTest {
                handle,
                enabled: true,
            }
        });
        draw(cx);
        handle.set_offset(point(px(0.), px(-200.)));
        draw(cx);

        scroll(cx, 0., TouchPhase::Started);
        scroll(cx, 24., TouchPhase::Moved);
        scroll(cx, 0., TouchPhase::Ended);
        draw(cx);
        assert_eq!(handle.offset().y, px(-176.));
        scroll(cx, 40., TouchPhase::Moved);
        draw(cx);
        assert_eq!(handle.offset().y, px(-136.));
    }

    #[gpui::test]
    fn short_catch_release_still_stretches_past_the_edge(cx: &mut TestAppContext) {
        let handle = ScrollHandle::new();
        let (_, cx) = cx.add_window_view({
            let handle = handle.clone();
            move |_, _| ScrollTest {
                handle,
                enabled: true,
            }
        });
        draw(cx);
        handle.set_offset(point(px(0.), px(-4.)));
        draw(cx);
        let origin = handle.bounds().origin.y;

        scroll(cx, 0., TouchPhase::Started);
        scroll(cx, 8., TouchPhase::Ended);
        draw(cx);
        assert_eq!(handle.offset().y, px(0.));
        assert!(handle.bounds().origin.y > origin);
    }

    #[gpui::test]
    fn disabled_and_reduced_motion_leave_the_viewport_fixed(cx: &mut TestAppContext) {
        for enabled in [false, true] {
            let mut app = cx.new_app();
            if enabled {
                app.update(|cx| cx.set_reduce_motion(true));
            }
            let handle = ScrollHandle::new();
            let (_, cx) = app.add_window_view({
                let handle = handle.clone();
                move |_, _| ScrollTest { handle, enabled }
            });
            draw(cx);
            let origin = handle.bounds().origin.y;
            scroll(cx, 100., TouchPhase::Started);
            draw(cx);
            assert_eq!(handle.bounds().origin.y, origin);
            scroll(cx, -40., TouchPhase::Moved);
            draw(cx);
            assert_eq!(handle.offset().y, px(-40.));
        }
    }

    #[test]
    fn resistance_and_reverse_preserve_unconsumed_distance() {
        let mut scroll = Physics::default();
        scroll.begin(600.);
        assert_eq!(scroll.pull(100.), 0.);
        assert!(scroll.offset() > 0. && scroll.offset() < 55.);
        assert_eq!(scroll.pull(-130.), -30.);
        assert_eq!(scroll.offset(), 0.);
    }

    #[gpui::test]
    fn diagonal_wobble_stays_with_the_stretch(cx: &mut TestAppContext) {
        let handle = ScrollHandle::new();
        let (_, cx) = cx.add_window_view({
            let handle = handle.clone();
            move |_, _| ScrollTest {
                handle,
                enabled: true,
            }
        });
        draw(cx);
        let origin = handle.bounds().origin.y;
        scroll(cx, 100., TouchPhase::Started);
        draw(cx);
        let stretched = handle.bounds().origin.y;
        assert!(stretched > origin);
        // A trackpad swipe that started vertical wobbles horizontal-dominant
        // for a packet. Dispatch within one update so the packets stay within
        // the axis lock's gesture separation.
        cx.update(|window, cx| {
            for delta in [point(px(30.), px(-20.)), point(px(0.), px(-20.))] {
                window.dispatch_event(
                    gpui::PlatformInput::Scroll(ScrollEvent {
                        position: point(px(100.), px(100.)),
                        delta: ScrollDelta::Pixels(delta),
                        touch_phase: TouchPhase::Moved,
                        ..Default::default()
                    }),
                    cx,
                );
            }
        });
        draw(cx);
        // Both packets shrink the stretch; neither scrolls the list.
        assert!(handle.bounds().origin.y < stretched);
        assert!(handle.bounds().origin.y > origin);
        assert_eq!(handle.offset(), point(px(0.), px(0.)));
    }

    #[test]
    fn motion_builder_configures_tracking_and_response() {
        let motion = ScrollBounceMotion::default()
            .with_tracking(0.4)
            .with_response(Duration::from_millis(300))
            .with_max_stretch(24.);
        assert_eq!(motion.tracking(), 0.4);
        assert_eq!(motion.response(), Duration::from_millis(300));
        assert_eq!(motion.max_stretch(), Some(24.));
    }

    #[test]
    fn tracking_scales_the_first_stretch() {
        let stretch = |tracking: f32| {
            let mut scroll = Physics {
                motion: ScrollBounceMotion::default().with_tracking(tracking),
                ..Physics::default()
            };
            scroll.begin(600.);
            scroll.pull(100.);
            scroll.offset()
        };
        assert!(stretch(0.3) < stretch(0.55));
        assert!(stretch(0.55) < stretch(0.8));
    }

    #[test]
    fn response_scales_the_return_and_zero_snaps() {
        let remaining = |response: Duration| {
            let mut scroll = Physics {
                motion: ScrollBounceMotion::default().with_response(response),
                ..Physics::default()
            };
            scroll.begin(600.);
            scroll.pull(180.);
            scroll.release();
            scroll.step(0.25);
            scroll.offset()
        };
        assert!(remaining(Duration::from_secs(1)) > remaining(Duration::from_millis(524)));
        assert!(remaining(Duration::from_millis(524)) > remaining(Duration::from_millis(200)));
        assert_eq!(remaining(Duration::ZERO), 0.);
    }

    #[test]
    fn regrabbing_a_displaced_edge_keeps_its_extent() {
        let mut scroll = Physics::default();
        scroll.begin(600.);
        scroll.pull(-150.);
        scroll.release();
        scroll.step(0.08);
        let before = scroll.offset();
        // The viewport shrank below the displacement while the edge was
        // returning. The finger still lands on the edge where it is.
        scroll.begin(40.);
        assert!((scroll.offset() - before).abs() < 0.001);
        // And a short pull inward moves the edge right away.
        scroll.pull(10.);
        assert!(scroll.offset() > before);
        assert!(scroll.offset() < before + 10.);
    }

    #[test]
    fn a_gesture_from_rest_adopts_the_current_extent() {
        let mut scroll = Physics::default();
        scroll.begin(600.);
        scroll.begin(40.);
        scroll.pull(-100.);
        // The stretch saturates below the 40 px viewport, not the 600 px one.
        assert!(scroll.offset() > -40.);
    }

    #[test]
    fn grabbing_the_spring_does_not_jump() {
        let mut scroll = Physics::default();
        scroll.begin(600.);
        scroll.pull(-150.);
        scroll.release();
        scroll.step(0.08);
        let before = scroll.offset();
        scroll.begin(600.);
        assert!((scroll.offset() - before).abs() < 0.001);
        let held = scroll.offset();
        assert!(!scroll.step(0.1));
        assert_eq!(scroll.offset(), held);
    }

    #[test]
    fn spring_has_the_same_trajectory_at_60_and_120_hz() {
        let at = |hz: usize| {
            let mut scroll = Physics::default();
            scroll.begin(600.);
            scroll.pull(180.);
            scroll.release();
            for _ in 0..hz / 4 {
                scroll.step(1. / hz as f32);
            }
            scroll.offset()
        };
        assert!((at(60) - at(120)).abs() < 0.001);
    }

    #[test]
    fn return_keeps_a_visible_tail_after_a_quarter_second() {
        let mut scroll = Physics {
            position: 100.,
            ..Physics::default()
        };
        assert!(scroll.step(0.25));
        // A 100 px release should still have a visible, decelerating tail
        // after 250 ms instead of snapping almost completely back by then.
        assert!(scroll.offset() > 10. && scroll.offset() < 30.);
        assert!(scroll.velocity < 0.);
    }

    #[test]
    fn spring_settles_without_crossing_the_boundary() {
        let mut scroll = Physics::default();
        scroll.begin(600.);
        scroll.pull(-200.);
        scroll.release();
        let mut previous = scroll.offset();
        for _ in 0..120 {
            scroll.step(1. / 120.);
            assert!(scroll.offset() >= previous && scroll.offset() <= 0.);
            previous = scroll.offset();
        }
        assert_eq!(scroll.offset(), 0.);
        assert!(scroll.suppress_momentum);
        scroll.begin(600.);
        assert!(!scroll.suppress_momentum);
    }
}
