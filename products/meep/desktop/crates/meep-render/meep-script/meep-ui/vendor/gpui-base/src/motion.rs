#[cfg(not(target_family = "wasm"))]
use std::time::Instant;
use std::{rc::Rc, time::Duration};
#[cfg(target_family = "wasm")]
use web_time::Instant;

use gpui::{
    App, Bounds, ElementId, Pixels, SharedString, Size, SpringConfig, SpringState, SpringTarget,
    Window,
};

use crate::animation::{Lerp, ease_out_cubic};

mod easing;
mod keyframes;
mod presence;
mod reveal;
mod sequence;
mod stagger;
mod timing;

pub use easing::{Easing, EasingError, LinearStop, StepPosition};
pub use keyframes::{Discrete, DiscreteError, Keyframe, KeyframeError, Keyframes};
pub use presence::{Presence, PresencePhase, PresenceSample};
pub use reveal::MotionReveal;
pub use sequence::{Sequence, SequenceSample, SequenceStep};
pub use stagger::{Stagger, StaggerOrigin};
pub use timing::{
    IterationCount, MotionPhase, PlaybackDirection, SignedDuration, Timing, TimingSample,
};

/// Matches GPUI's own default spring settling tolerance.
const DEFAULT_SPRING_EPSILON: f32 = 0.001;

/// A value that can be interpolated between two application-owned targets.
pub trait Interpolate: Clone {
    fn interpolate(&self, target: &Self, progress: f32) -> Self;
}

impl<T: Lerp> Interpolate for T {
    fn interpolate(&self, target: &Self, progress: f32) -> Self {
        self.lerp(target, progress)
    }
}

impl Interpolate for Size<Pixels> {
    fn interpolate(&self, target: &Self, progress: f32) -> Self {
        Size::new(
            self.width.lerp(&target.width, progress),
            self.height.lerp(&target.height, progress),
        )
    }
}

impl Interpolate for Bounds<Pixels> {
    fn interpolate(&self, target: &Self, progress: f32) -> Self {
        Bounds::new(
            self.origin.lerp(&target.origin, progress),
            self.size.interpolate(&target.size, progress),
        )
    }
}

/// A presentation-neutral bundle for coordinated paint transforms.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct MotionTransform {
    pub translation: gpui::Point<Pixels>,
    pub scale: gpui::Point<f32>,
    pub rotation_radians: f32,
    pub opacity: f32,
}

impl MotionTransform {
    pub fn identity() -> Self {
        Self {
            translation: gpui::point(gpui::px(0.0), gpui::px(0.0)),
            scale: gpui::point(1.0, 1.0),
            rotation_radians: 0.0,
            opacity: 1.0,
        }
    }
}

impl Default for MotionTransform {
    fn default() -> Self {
        Self::identity()
    }
}

impl Interpolate for MotionTransform {
    fn interpolate(&self, target: &Self, progress: f32) -> Self {
        Self {
            translation: self.translation.lerp(&target.translation, progress),
            scale: gpui::point(
                self.scale.x.lerp(&target.scale.x, progress),
                self.scale.y.lerp(&target.scale.y, progress),
            ),
            rotation_radians: self
                .rotation_radians
                .lerp(&target.rotation_radians, progress),
            opacity: self.opacity.lerp(&target.opacity, progress),
        }
    }
}

/// CSS-like timing policy for a target-value transition.
///
/// This type is intentionally separate from [`crate::animation::Transition`],
/// whose legacy interface applies concrete fade, slide, and size effects to an
/// element. A value transition never chooses a visual property for the caller.
#[derive(Clone)]
pub struct Transition {
    duration: Duration,
    delay: SignedDuration,
    easing: Easing,
}

impl Transition {
    pub fn new(duration: Duration) -> Self {
        Self {
            duration,
            delay: SignedDuration::ZERO,
            easing: Easing::Custom(Rc::new(ease_out_cubic)),
        }
    }

    pub fn delay(mut self, delay: impl Into<SignedDuration>) -> Self {
        self.delay = delay.into();
        self
    }

    pub fn ease(mut self, easing: impl Fn(f32) -> f32 + 'static) -> Self {
        self.easing = Easing::Custom(Rc::new(easing));
        self
    }

    pub fn easing(mut self, easing: Easing) -> Self {
        self.easing = easing;
        self
    }

    fn sample(&self, progress: f32) -> f32 {
        self.easing.sample(progress)
    }

    /// The easing curve, for a caller that samples one timeline at several
    /// offsets, such as a staggered plot appear.
    pub(crate) fn curve(&self) -> &Easing {
        &self.easing
    }

    fn progress(&self, elapsed: Duration, duration: Duration) -> (f32, MotionStatus) {
        let Some(active_elapsed) = self.delay.active_elapsed(elapsed) else {
            return (0.0, MotionStatus::Delayed);
        };
        if duration.is_zero() || active_elapsed >= duration {
            return (1.0, MotionStatus::Finished);
        }
        (
            active_elapsed.as_secs_f32() / duration.as_secs_f32(),
            MotionStatus::Running,
        )
    }

    /// The elapsed time at which [`Self::progress`] over the transition's own
    /// duration first reports `Finished`.
    fn finishes_after(&self) -> Duration {
        match self.delay {
            SignedDuration::Positive(delay) => delay.saturating_add(self.duration),
            SignedDuration::Negative(delay) => self.duration.saturating_sub(delay),
        }
    }
}

impl From<Duration> for SignedDuration {
    fn from(duration: Duration) -> Self {
        Self::positive(duration)
    }
}

/// Identifies one independently transitioning value.
#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct TransitionId(ElementId);

impl From<ElementId> for TransitionId {
    fn from(id: ElementId) -> Self {
        Self(id)
    }
}

impl From<&'static str> for TransitionId {
    fn from(id: &'static str) -> Self {
        Self(id.into())
    }
}

impl From<String> for TransitionId {
    fn from(id: String) -> Self {
        Self(id.into())
    }
}

impl From<SharedString> for TransitionId {
    fn from(id: SharedString) -> Self {
        Self(id.into())
    }
}

impl From<usize> for TransitionId {
    fn from(id: usize) -> Self {
        Self(id.into())
    }
}

impl From<i32> for TransitionId {
    fn from(id: i32) -> Self {
        Self(id.into())
    }
}

impl From<TransitionId> for ElementId {
    fn from(id: TransitionId) -> Self {
        ElementId::NamedChild(id.0.into(), "__base-transition-state".into())
    }
}

impl<I, C> From<(I, C)> for TransitionId
where
    I: Into<ElementId>,
    C: Into<SharedString>,
{
    fn from((id, channel): (I, C)) -> Self {
        Self(ElementId::NamedChild(id.into().into(), channel.into()))
    }
}

#[derive(Clone)]
struct ValueTransition<T> {
    from: T,
    target: T,
    started_at: Instant,
    reversing_factor: f32,
    duration: Duration,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum MotionStatus {
    Idle,
    Delayed,
    Running,
    Finished,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct MotionValue<T> {
    pub value: T,
    pub status: MotionStatus,
}

/// Returns the current value for a CSS-like transition toward `target`.
///
/// State is keyed by `id`. The first value is adopted immediately; later target
/// changes transition from the value sampled at that instant. Components opt
/// into this function explicitly—base components do not install default motion.
///
/// Call this while rendering an element, where GPUI keyed element state is
/// available. A channel id must identify one value type within that element.
pub fn transition<T>(
    id: impl Into<TransitionId>,
    target: T,
    policy: Transition,
    window: &mut Window,
    cx: &mut App,
) -> T
where
    T: Interpolate + PartialEq + 'static,
{
    transition_with_status(id, target, policy, window, cx).value
}

pub fn transition_with_status<T>(
    id: impl Into<TransitionId>,
    target: T,
    policy: Transition,
    window: &mut Window,
    cx: &mut App,
) -> MotionValue<T>
where
    T: Interpolate + PartialEq + 'static,
{
    let id: ElementId = id.into().into();
    let now = cx.background_executor().now();
    let state = window.use_keyed_state(id, cx, |_, _| ValueTransition {
        from: target.clone(),
        target: target.clone(),
        started_at: now,
        reversing_factor: 1.0,
        duration: policy.duration,
    });

    let snapshot = state.read(cx).clone();

    if cx.reduce_motion() || policy.duration.is_zero() {
        if snapshot.from != target || snapshot.target != target {
            state.update(cx, |state, _| {
                state.from = target.clone();
                state.target = target.clone();
                state.started_at = now;
                state.reversing_factor = 1.0;
                state.duration = policy.duration;
            });
        }
        return MotionValue {
            value: target,
            status: MotionStatus::Finished,
        };
    }

    let elapsed = now.saturating_duration_since(snapshot.started_at);
    let (progress, status) = policy.progress(elapsed, snapshot.duration);
    let sampled = snapshot
        .from
        .interpolate(&snapshot.target, policy.sample(progress));

    let (value, status) = if snapshot.target != target {
        let reversing = target == snapshot.from;
        let reversing_factor = if reversing {
            (policy.sample(progress) * snapshot.reversing_factor
                + (1.0 - snapshot.reversing_factor))
                .clamp(0.0, 1.0)
        } else {
            1.0
        };
        let duration = policy.duration.mul_f64(f64::from(reversing_factor));
        state.update(cx, |state, _| {
            state.from = sampled.clone();
            state.target = target.clone();
            state.started_at = now;
            state.reversing_factor = reversing_factor;
            state.duration = duration;
        });
        let (initial_progress, initial_status) = policy.progress(Duration::ZERO, duration);
        (
            sampled.interpolate(&target, policy.sample(initial_progress)),
            initial_status,
        )
    } else {
        (
            sampled,
            if snapshot.from == snapshot.target {
                MotionStatus::Idle
            } else {
                status
            },
        )
    };
    if matches!(status, MotionStatus::Delayed | MotionStatus::Running) {
        window.request_animation_frame();
    }
    MotionValue { value, status }
}

#[derive(Clone, Copy)]
struct KeyframePlayback {
    started_at: Instant,
}

/// Samples a keyed keyframe playback and requests frames while it is active.
///
/// The stable `id` owns the playback's start time. Re-rendering with the same
/// ID continues that playback; it does not restart when `keyframes` or `timing`
/// is reconstructed. To replay a sequence, include an application-owned
/// generation in the ID, for example `("notification-enter", generation)`.
pub fn animate_keyframes<T>(
    id: impl Into<TransitionId>,
    keyframes: &Keyframes<T>,
    timing: Timing,
    window: &mut Window,
    cx: &mut App,
) -> MotionValue<T>
where
    T: Interpolate + 'static,
{
    let id: TransitionId = id.into();
    let id = ElementId::NamedChild(ElementId::from(id).into(), "__keyframes".into());
    let now = cx.background_executor().now();
    let state = window.use_keyed_state(id, cx, |_, _| KeyframePlayback { started_at: now });
    let started_at = state.read(cx).started_at;

    if cx.reduce_motion() {
        return MotionValue {
            value: keyframes.sample(1.0),
            status: MotionStatus::Finished,
        };
    }

    let sample = timing.sample(now.saturating_duration_since(started_at));
    let status = match sample.phase {
        MotionPhase::Before => MotionStatus::Delayed,
        MotionPhase::Active => MotionStatus::Running,
        MotionPhase::After => MotionStatus::Finished,
    };
    if matches!(status, MotionStatus::Delayed | MotionStatus::Running) {
        window.request_animation_frame();
    }
    MotionValue {
        value: keyframes.sample(sample.directed_progress),
        status,
    }
}

/// A physical spring policy for [`spring`].
///
/// A spring is the counterpart to [`Transition`] for values that can be
/// retargeted while they are still moving. A duration-based transition restarts
/// its easing from the value sampled at that instant, which is continuous in
/// position but not in velocity. A spring carries velocity across the retarget,
/// so a value reversed mid-flight decelerates and turns around instead of
/// snapping to a new curve's initial speed.
#[derive(Clone, Copy, Debug)]
pub struct Spring {
    response: Duration,
    damping: f32,
    epsilon: f32,
    travel: bool,
}

/// Invalid physical or settling parameters for a [`Spring`].
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SpringError {
    InvalidDamping,
    InvalidEpsilon,
}

impl std::fmt::Display for SpringError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::InvalidDamping => f.write_str("spring damping must be finite and non-negative"),
            Self::InvalidEpsilon => {
                f.write_str("spring epsilon must be finite and greater than zero")
            }
        }
    }
}

impl std::error::Error for SpringError {}

impl Spring {
    /// Builds a spring that reaches its target in about `response` without
    /// overshooting it.
    ///
    /// `response` is not a duration in the sense [`Transition::new`] means one.
    /// A spring has no end to schedule: this is the period one full oscillation
    /// would take without damping, which is the scale the motion is felt at
    /// rather than the moment it stops. The remaining fraction of a percent
    /// keeps settling past it, until it is within the tolerance
    /// [`Self::with_epsilon`] sets.
    ///
    /// A zero response adopts the target on the spot, as a zero duration does
    /// for a transition. Say that with [`Self::with_travel`] where it is what
    /// you mean; a zero here is the degenerate case, defined so an infinitely
    /// stiff spring resolves rather than dividing by its own period.
    pub const fn new(response: Duration) -> Self {
        Self {
            response,
            damping: 1.0,
            epsilon: DEFAULT_SPRING_EPSILON,
            travel: true,
        }
    }

    /// Sets the damping ratio, which is `1.0` — no overshoot — by default.
    ///
    /// Below `1.0` the spring passes its target and comes back; above `1.0` it
    /// approaches slowly. Overshoot suits a value with room to pass its target
    /// and nothing to collide with. A height, an opacity, or anything bounded by
    /// the geometry around it should stay at the default.
    ///
    /// This is $\zeta$, not GPUI's `SpringConfig::damping`, which is the
    /// coefficient $c = 2 \zeta \omega_0$.
    ///
    /// # Panics
    ///
    /// Panics when `ratio` is negative or non-finite. Use
    /// [`Self::try_with_damping`] when the value is not a trusted constant.
    pub const fn with_damping(self, ratio: f32) -> Self {
        match self.try_with_damping(ratio) {
            Ok(spring) => spring,
            Err(_) => panic!("spring damping must be finite and non-negative"),
        }
    }

    /// Checked form of [`Self::with_damping`].
    pub const fn try_with_damping(mut self, ratio: f32) -> Result<Self, SpringError> {
        if !ratio.is_finite() || ratio < 0.0 {
            return Err(SpringError::InvalidDamping);
        }
        self.damping = ratio;
        Ok(self)
    }

    /// Sets whether the spring travels to its target or adopts it on the spot.
    ///
    /// A value the pointer is already moving — a panel being dragged by its
    /// resize handle — must not lag behind the pointer, so the spring stops
    /// travelling for as long as the drag lasts. Retained state stays pinned to
    /// the target meanwhile, so travel resumes from the value the drag released
    /// rather than from wherever the spring was when it began.
    ///
    /// This says at the call that the motion is suspended, and it says it
    /// without disturbing the response, damping or tolerance the spring is
    /// configured with — which a policy swapped out for the length of the drag
    /// would have to restate or discard.
    pub const fn with_travel(mut self, travel: bool) -> Self {
        self.travel = travel;
        self
    }

    /// Sets the settling tolerance, expressed in the target's own units.
    ///
    /// The default suits targets that move within a normalized `0..1` range. A
    /// spring over pixels settles perceptibly sooner with a coarser tolerance,
    /// which also ends the animation frames that the remaining sub-pixel motion
    /// would otherwise request.
    ///
    /// # Panics
    ///
    /// Panics when `epsilon` is zero, negative, or non-finite. Use
    /// [`Self::try_with_epsilon`] when the value is not a trusted constant.
    pub const fn with_epsilon(self, epsilon: f32) -> Self {
        match self.try_with_epsilon(epsilon) {
            Ok(spring) => spring,
            Err(_) => panic!("spring epsilon must be finite and greater than zero"),
        }
    }

    /// Checked form of [`Self::with_epsilon`].
    pub const fn try_with_epsilon(mut self, epsilon: f32) -> Result<Self, SpringError> {
        if !epsilon.is_finite() || epsilon <= 0.0 {
            return Err(SpringError::InvalidEpsilon);
        }
        self.epsilon = epsilon;
        Ok(self)
    }

    /// Returns the settling tolerance in the target's own units.
    pub const fn epsilon(self) -> f32 {
        self.epsilon
    }

    /// The physical parameters GPUI integrates. The response must be non-zero;
    /// [`spring`] adopts the target before reaching here when it is not.
    ///
    /// Derived on use rather than stored, so the builders stay `const`: neither
    /// `Duration::as_secs_f32` nor the square root that recovers a damping ratio
    /// from a built config can be called from a `const fn`.
    fn config(&self) -> SpringConfig {
        let frequency = std::f32::consts::TAU / self.response.as_secs_f32();
        SpringConfig::new(frequency * frequency, 2.0 * self.damping * frequency, 1.0)
    }
}

#[derive(Clone, Copy)]
struct SpringTransition {
    state: SpringState,
    target: f32,
    updated_at: Instant,
}

/// Returns the current value for a spring travelling toward `target`.
///
/// State is keyed by `id` exactly as [`transition`] keys its own. The first
/// value is adopted immediately; later target changes preserve both the current
/// position and the current velocity, so an interrupted spring is redirected
/// rather than restarted.
///
/// Call this while rendering an element, where GPUI keyed element state is
/// available. A channel id must identify one value within that element.
pub fn spring<T>(
    id: impl Into<TransitionId>,
    target: T,
    policy: Spring,
    window: &mut Window,
    cx: &mut App,
) -> T::Output
where
    T: SpringTarget,
{
    let id: ElementId = id.into().into();
    let now = cx.background_executor().now();
    let target_position = target.target();
    let state = window.use_keyed_state(id, cx, |_, _| SpringTransition {
        state: SpringState {
            position: target_position,
            velocity: 0.0,
        },
        target: target_position,
        updated_at: now,
    });

    let snapshot = *state.read(cx);
    let at_rest_on_target =
        snapshot.state.position == target_position && snapshot.state.velocity == 0.0;

    // The overwhelmingly common case: a spring nothing is currently moving. It
    // has no state to advance and no frame to ask for, so it never builds a
    // config or steps one — a settled spring costs a read and two comparisons.
    // Every branch below would return this same value and write nothing.
    //
    // Resting writes nothing, so `updated_at` goes stale for as long as the rest
    // lasts. The next retarget then steps a zero displacement at zero velocity
    // over that whole gap, which any elapsed time leaves where it is, so the
    // stale clock cannot move the value — it only has to not produce a NaN, and
    // every term the propagator scales is finite.
    if at_rest_on_target {
        return target.resolve(target_position);
    }

    let settle = |state: &mut SpringTransition| {
        state.state = SpringState {
            position: target_position,
            velocity: 0.0,
        };
        state.target = target_position;
        state.updated_at = now;
    };

    if cx.reduce_motion() || !policy.travel || policy.response.is_zero() {
        state.update(cx, |state, _| settle(state));
        return target.resolve(target_position);
    }

    // Advance over the frame that just elapsed, which the previous target
    // governed, before adopting the new one for the frame to come.
    let elapsed = now
        .saturating_duration_since(snapshot.updated_at)
        .as_secs_f32();
    let config = policy.config();
    let stepped = config.step(snapshot.state, snapshot.target, elapsed);

    if config.is_settled(stepped, target_position, policy.epsilon) {
        state.update(cx, |state, _| settle(state));
        return target.resolve(target_position);
    }

    state.update(cx, |state, _| {
        state.state = stepped;
        state.target = target_position;
        state.updated_at = now;
    });
    window.request_animation_frame();
    target.resolve(stepped.position)
}

#[cfg(test)]
mod css_timing_tests {
    use super::{
        Easing, IterationCount, LinearStop, MotionPhase, PlaybackDirection, SignedDuration,
        StepPosition, Timing,
    };
    use std::{num::NonZeroU32, sync::Arc, time::Duration};

    #[test]
    fn css_keyword_easing_matches_published_reference_samples() {
        for (easing, samples) in [
            (Easing::Ease, [(0.2, 0.295), (0.5, 0.802), (0.8, 0.976)]),
            (Easing::EaseIn, [(0.2, 0.062), (0.5, 0.315), (0.8, 0.692)]),
            (Easing::EaseOut, [(0.2, 0.308), (0.5, 0.685), (0.8, 0.938)]),
            (Easing::EaseInOut, [(0.2, 0.082), (0.5, 0.5), (0.8, 0.918)]),
        ] {
            for (progress, expected) in samples {
                let actual = easing.sample(progress);
                assert!(
                    (actual - expected).abs() < 0.002,
                    "{easing:?}({progress}) = {actual}, expected {expected}"
                );
            }
        }
    }

    #[test]
    fn cubic_bezier_easing_keeps_anticipation_and_overshoot() {
        let anticipate = Easing::cubic_bezier(1.0, -0.4, 0.35, 0.95).unwrap();
        let overshoot = Easing::cubic_bezier(0.175, 0.885, 0.32, 1.275).unwrap();

        assert!(anticipate.sample(0.2) < 0.0);
        assert!(overshoot.sample(0.8) > 1.0);
        for easing in [anticipate, overshoot] {
            assert_eq!(easing.sample(-1.0), 0.0);
            assert_eq!(easing.sample(2.0), 1.0);
        }
    }

    #[test]
    fn step_easing_observes_css_jump_positions() {
        let start = Easing::steps(4, StepPosition::JumpStart).unwrap();
        let end = Easing::steps(4, StepPosition::JumpEnd).unwrap();

        assert_eq!(start.sample(0.0), 0.25);
        assert_eq!(start.sample(0.24), 0.25);
        assert_eq!(start.sample(0.25), 0.5);
        assert_eq!(end.sample(0.0), 0.0);
        assert_eq!(end.sample(0.24), 0.0);
        assert_eq!(end.sample(0.25), 0.25);
        assert!(Easing::steps(0, StepPosition::JumpEnd).is_err());

        let none = Easing::steps(4, StepPosition::JumpNone).unwrap();
        let both = Easing::steps(4, StepPosition::JumpBoth).unwrap();
        assert_eq!(none.sample(0.0), 0.0);
        assert!((none.sample(0.5) - 2.0 / 3.0).abs() < f32::EPSILON);
        assert_eq!(none.sample(1.0), 1.0);
        assert_eq!(both.sample(0.0), 0.2);
        assert_eq!(both.sample(1.0), 1.0);
        assert!(Easing::steps(1, StepPosition::JumpNone).is_err());
    }

    #[test]
    fn linear_stops_fill_omitted_positions_before_sampling() {
        let easing = Easing::linear_stops([
            LinearStop::at(0.0, 0.0),
            LinearStop::new(0.2),
            LinearStop::new(0.8),
            LinearStop::at(1.0, 1.0),
        ])
        .unwrap();

        assert!((easing.sample(1.0 / 3.0) - 0.2).abs() < 1e-6);
        assert!((easing.sample(0.5) - 0.5).abs() < 1e-6);
        assert!(
            Easing::linear_stops([LinearStop::at(0.0, 0.8), LinearStop::at(1.0, 0.2)]).is_err()
        );
    }

    #[test]
    fn curves_built_without_stops_or_jumps_sample_linearly() {
        // Both are rejected by the constructors, but the variants are public.
        let no_stops = Easing::LinearStops(Arc::from([]));
        let no_jumps = Easing::Steps {
            count: NonZeroU32::MIN,
            position: StepPosition::JumpNone,
        };

        for (progress, expected) in [(-1.0, 0.0), (0.25, 0.25), (2.0, 1.0)] {
            assert_eq!(
                no_stops.sample(progress),
                expected,
                "no stops at {progress}"
            );
            assert_eq!(
                no_jumps.sample(progress),
                expected,
                "no jumps at {progress}"
            );
        }
    }

    #[test]
    fn negative_delay_starts_inside_the_active_interval() {
        let timing = Timing::new(Duration::from_millis(100))
            .delay(SignedDuration::negative(Duration::from_millis(25)));
        let sample = timing.sample(Duration::ZERO);

        assert_eq!(sample.phase, MotionPhase::Active);
        assert!((sample.directed_progress - 0.25).abs() < f32::EPSILON);
        assert!(sample.active);
        assert!(!sample.finished);
    }

    #[test]
    fn alternate_direction_reverses_odd_iterations() {
        let timing = Timing::new(Duration::from_millis(100))
            .iterations(IterationCount::Finite(2))
            .direction(PlaybackDirection::Alternate)
            .ease(Easing::Linear);

        let first = timing.sample(Duration::from_millis(25));
        let second = timing.sample(Duration::from_millis(125));
        let finished = timing.sample(Duration::from_millis(200));

        assert_eq!(first.iteration, 0);
        assert_eq!(first.directed_progress, 0.25);
        assert_eq!(second.iteration, 1);
        assert_eq!(second.directed_progress, 0.75);
        assert_eq!(finished.phase, MotionPhase::After);
        assert_eq!(finished.directed_progress, 0.0);
        assert!(finished.finished);
    }
}

#[cfg(test)]
mod motion_track_tests {
    use super::{
        Discrete, Easing, Interpolate as _, Keyframe, KeyframeError, Keyframes, MotionTransform,
        Stagger, StaggerOrigin,
    };
    use gpui::{Bounds, Point, Size, point, px, size};
    use std::time::Duration;

    #[test]
    fn keyframes_validate_offsets_and_sample_each_segments_easing() {
        assert!(matches!(
            Keyframes::try_new([Keyframe::new(0.2, 0.0_f32), Keyframe::new(1.0, 1.0_f32),]),
            Err(KeyframeError::MissingEndpoint)
        ));
        assert!(matches!(
            Keyframes::try_new([
                Keyframe::new(0.0, 0.0_f32),
                Keyframe::new(0.8, 1.0_f32),
                Keyframe::new(0.7, 2.0_f32),
                Keyframe::new(1.0, 3.0_f32),
            ]),
            Err(KeyframeError::OffsetsNotMonotonic)
        ));

        let track = Keyframes::try_new([
            Keyframe::new(0.0, 0.0_f32)
                .ease(Easing::steps(2, super::StepPosition::JumpEnd).unwrap()),
            Keyframe::new(0.5, 10.0_f32).ease(Easing::Linear),
            Keyframe::new(1.0, 20.0_f32),
        ])
        .unwrap();

        assert_eq!(track.sample(0.2), 0.0);
        assert_eq!(track.sample(0.3), 5.0);
        assert_eq!(track.sample(0.75), 15.0);
        assert_eq!(track.sample(1.0), 20.0);
    }

    #[test]
    fn discrete_values_switch_only_at_the_requested_progress() {
        let value = Discrete::new("old", "new").switch_at(0.75).unwrap();
        assert_eq!(value.sample(0.749), "old");
        assert_eq!(value.sample(0.75), "new");
        assert!(Discrete::new(0, 1).switch_at(f32::NAN).is_err());
    }

    #[test]
    fn stagger_origins_produce_stable_delays_without_allocating_a_schedule() {
        let interval = Duration::from_millis(20);
        let first = Stagger::new(interval, StaggerOrigin::First);
        let last = Stagger::new(interval, StaggerOrigin::Last);
        let center = Stagger::new(interval, StaggerOrigin::Center);

        assert_eq!(first.delay(3, 5), Duration::from_millis(60));
        assert_eq!(last.delay(3, 5), Duration::from_millis(20));
        assert_eq!(center.delay(2, 5), Duration::ZERO);
        assert_eq!(center.delay(0, 5), Duration::from_millis(40));
        assert_eq!(first.delay(7, 0), Duration::ZERO);
    }

    #[test]
    fn common_gpui_geometry_interpolates_channel_by_channel() {
        let from_size = size(px(10.0), px(20.0));
        let to_size = size(px(30.0), px(60.0));
        assert_eq!(
            from_size.interpolate(&to_size, 0.25),
            size(px(15.0), px(30.0))
        );

        let from = Bounds::new(point(px(0.0), px(10.0)), from_size);
        let to = Bounds::new(point(px(40.0), px(50.0)), to_size);
        assert_eq!(
            from.interpolate(&to, 0.5),
            Bounds::new(point(px(20.0), px(30.0)), size(px(20.0), px(40.0)))
        );

        let _: Point<gpui::Pixels> = from.origin;
        let _: Size<gpui::Pixels> = from.size;

        let transform = MotionTransform::identity().interpolate(
            &MotionTransform {
                translation: point(px(20.0), px(40.0)),
                scale: point(2.0, 0.5),
                rotation_radians: std::f32::consts::PI,
                opacity: 0.0,
            },
            0.5,
        );
        assert_eq!(transform.translation, point(px(10.0), px(20.0)));
        assert_eq!(transform.scale, point(1.5, 0.75));
        assert_eq!(transform.rotation_radians, std::f32::consts::FRAC_PI_2);
        assert_eq!(transform.opacity, 0.5);
    }
}

#[cfg(test)]
mod tests {
    use std::{
        cell::{Cell, RefCell},
        rc::Rc,
        time::Duration,
    };

    use gpui::{Empty, IntoElement, Render, TestAppContext, WindowHandle, px, size};

    use super::*;

    struct StatusView {
        target: Rc<Cell<f32>>,
        policy: Transition,
        samples: Rc<RefCell<Vec<MotionValue<f32>>>>,
    }

    impl Render for StatusView {
        fn render(
            &mut self,
            window: &mut Window,
            cx: &mut gpui::Context<Self>,
        ) -> impl IntoElement {
            self.samples.borrow_mut().push(transition_with_status(
                ("status-test", "value"),
                self.target.get(),
                self.policy.clone(),
                window,
                cx,
            ));
            Empty
        }
    }

    struct StatusFixture {
        window: WindowHandle<StatusView>,
        target: Rc<Cell<f32>>,
        samples: Rc<RefCell<Vec<MotionValue<f32>>>>,
    }

    impl StatusFixture {
        fn open(cx: &mut TestAppContext, policy: Transition) -> Self {
            let target = Rc::new(Cell::new(0.0));
            let samples = Rc::new(RefCell::new(Vec::new()));
            let window = cx.open_window(size(px(100.), px(100.)), {
                let target = target.clone();
                let samples = samples.clone();
                move |_, _| StatusView {
                    target,
                    policy,
                    samples,
                }
            });
            cx.run_until_parked();
            Self {
                window,
                target,
                samples,
            }
        }

        fn render(&self, cx: &mut TestAppContext, target: f32) -> MotionValue<f32> {
            self.target.set(target);
            self.window
                .update(cx, |_, window, _| window.refresh())
                .unwrap();
            cx.run_until_parked();
            *self.samples.borrow().last().unwrap()
        }
    }

    #[gpui::test]
    fn status_transition_reports_delay_running_and_finished(cx: &mut TestAppContext) {
        let fixture = StatusFixture::open(
            cx,
            Transition::new(Duration::from_millis(100)).delay(Duration::from_millis(20)),
        );
        assert_eq!(fixture.render(cx, 1.0).status, MotionStatus::Delayed);

        cx.executor().advance_clock(Duration::from_millis(20));
        assert_eq!(fixture.render(cx, 1.0).status, MotionStatus::Running);
        cx.executor().advance_clock(Duration::from_millis(100));
        assert_eq!(fixture.render(cx, 1.0).status, MotionStatus::Finished);
    }

    #[gpui::test]
    fn negative_delay_samples_a_target_change_inside_its_interval(cx: &mut TestAppContext) {
        let fixture = StatusFixture::open(
            cx,
            Transition::new(Duration::from_millis(100))
                .delay(SignedDuration::negative(Duration::from_millis(25)))
                .ease(|t| t),
        );
        let sample = fixture.render(cx, 1.0);
        assert_eq!(sample.status, MotionStatus::Running);
        assert_eq!(sample.value, 0.25);
    }

    #[gpui::test]
    fn a_direct_reversal_shortens_the_return_transition(cx: &mut TestAppContext) {
        let fixture =
            StatusFixture::open(cx, Transition::new(Duration::from_millis(100)).ease(|t| t));
        assert_eq!(fixture.render(cx, 1.0).value, 0.0);
        cx.executor().advance_clock(Duration::from_millis(50));
        assert_eq!(fixture.render(cx, 0.0).value, 0.5);
        cx.executor().advance_clock(Duration::from_millis(25));
        assert_eq!(fixture.render(cx, 0.0).value, 0.25);
    }

    struct KeyframeView {
        track: Keyframes<f32>,
        timing: Timing,
        samples: Rc<RefCell<Vec<MotionValue<f32>>>>,
    }

    impl Render for KeyframeView {
        fn render(
            &mut self,
            window: &mut Window,
            cx: &mut gpui::Context<Self>,
        ) -> impl IntoElement {
            self.samples.borrow_mut().push(animate_keyframes(
                "keyframe-test",
                &self.track,
                self.timing.clone(),
                window,
                cx,
            ));
            Empty
        }
    }

    #[gpui::test]
    fn keyed_keyframes_follow_timing_and_stop_after_completion(cx: &mut TestAppContext) {
        let samples = Rc::new(RefCell::new(Vec::new()));
        let window = cx.open_window(size(px(100.), px(100.)), {
            let samples = samples.clone();
            move |_, _| KeyframeView {
                track: Keyframes::try_new([Keyframe::new(0.0, 0.0), Keyframe::new(1.0, 10.0)])
                    .unwrap(),
                timing: Timing::new(Duration::from_millis(100)),
                samples,
            }
        });
        cx.run_until_parked();
        assert_eq!(samples.borrow().last().unwrap().value, 0.0);
        assert_eq!(
            samples.borrow().last().unwrap().status,
            MotionStatus::Running
        );

        cx.executor().advance_clock(Duration::from_millis(50));
        assert_eq!(
            window
                .update(cx, |_, window, cx| window.simulate_next_frame(cx))
                .unwrap(),
            1
        );
        cx.run_until_parked();
        assert_eq!(samples.borrow().last().unwrap().value, 5.0);

        cx.executor().advance_clock(Duration::from_millis(50));
        window.update(cx, |_, window, _| window.refresh()).unwrap();
        cx.run_until_parked();
        assert_eq!(
            samples.borrow().last().unwrap().status,
            MotionStatus::Finished
        );
        window
            .update(cx, |_, window, cx| window.simulate_next_frame(cx))
            .unwrap();
        cx.run_until_parked();
        assert_eq!(
            window
                .update(cx, |_, window, cx| window.simulate_next_frame(cx))
                .unwrap(),
            0
        );
    }

    struct PresenceView {
        present: Rc<Cell<bool>>,
        samples: Rc<RefCell<Vec<PresenceSample>>>,
    }

    impl Render for PresenceView {
        fn render(
            &mut self,
            window: &mut Window,
            cx: &mut gpui::Context<Self>,
        ) -> impl IntoElement {
            self.samples.borrow_mut().push(
                Presence::new("presence-test", self.present.get())
                    .transition(Transition::new(Duration::from_millis(100)).ease(|t| t))
                    .sample(window, cx),
            );
            Empty
        }
    }

    struct PresenceFixture {
        window: WindowHandle<PresenceView>,
        present: Rc<Cell<bool>>,
        samples: Rc<RefCell<Vec<PresenceSample>>>,
    }

    impl PresenceFixture {
        fn open(cx: &mut TestAppContext, initially_present: bool) -> Self {
            let present = Rc::new(Cell::new(initially_present));
            let samples = Rc::new(RefCell::new(Vec::new()));
            let window = cx.open_window(size(px(100.), px(100.)), {
                let present = present.clone();
                let samples = samples.clone();
                move |_, _| PresenceView { present, samples }
            });
            cx.run_until_parked();
            Self {
                window,
                present,
                samples,
            }
        }

        fn render(&self, cx: &mut TestAppContext, present: bool) -> PresenceSample {
            self.present.set(present);
            self.window
                .update(cx, |_, window, _| window.refresh())
                .unwrap();
            cx.run_until_parked();
            *self.samples.borrow().last().unwrap()
        }
    }

    #[gpui::test]
    fn presence_enters_exits_and_only_unmounts_after_exit(cx: &mut TestAppContext) {
        let fixture = PresenceFixture::open(cx, true);
        let entering = *fixture.samples.borrow().last().unwrap();
        assert_eq!(entering.phase, PresencePhase::Entering);
        assert_eq!(entering.progress, 0.0);
        assert!(entering.should_render());

        cx.executor().advance_clock(Duration::from_millis(100));
        let present = fixture.render(cx, true);
        assert_eq!(present.phase, PresencePhase::Present);
        assert_eq!(present.progress, 1.0);

        let exiting = fixture.render(cx, false);
        assert_eq!(exiting.phase, PresencePhase::Exiting);
        assert_eq!(exiting.progress, 1.0);
        assert!(exiting.should_render());

        cx.executor().advance_clock(Duration::from_millis(100));
        let absent = fixture.render(cx, false);
        assert_eq!(absent.phase, PresencePhase::Absent);
        assert_eq!(absent.progress, 0.0);
        assert!(!absent.should_render());
    }

    #[gpui::test]
    fn presence_reentry_reverses_from_the_exit_sample(cx: &mut TestAppContext) {
        let fixture = PresenceFixture::open(cx, true);
        cx.executor().advance_clock(Duration::from_millis(100));
        fixture.render(cx, true);
        fixture.render(cx, false);
        cx.executor().advance_clock(Duration::from_millis(40));
        let reentering = fixture.render(cx, true);

        assert_eq!(reentering.phase, PresencePhase::Entering);
        assert_eq!(reentering.progress, 0.6);
    }

    #[gpui::test]
    fn reduced_motion_resolves_presence_without_a_pending_frame(cx: &mut TestAppContext) {
        cx.update(|cx| cx.set_reduce_motion(true));
        let fixture = PresenceFixture::open(cx, true);
        assert_eq!(
            fixture.samples.borrow().last().unwrap().phase,
            PresencePhase::Present
        );
        assert_eq!(
            fixture
                .window
                .update(cx, |_, window, cx| window.simulate_next_frame(cx))
                .unwrap(),
            0
        );
        assert_eq!(fixture.render(cx, false).phase, PresencePhase::Absent);
    }

    struct SequenceView {
        steps: Rc<RefCell<Vec<SequenceStep<f32>>>>,
        samples: Rc<RefCell<Vec<SequenceSample<f32>>>>,
    }

    impl Render for SequenceView {
        fn render(
            &mut self,
            window: &mut Window,
            cx: &mut gpui::Context<Self>,
        ) -> impl IntoElement {
            self.samples.borrow_mut().push(
                Sequence::new("sequence-test", 0.0)
                    .with_steps(self.steps.borrow().iter().cloned())
                    .sample(window, cx),
            );
            Empty
        }
    }

    struct SequenceFixture {
        window: WindowHandle<SequenceView>,
        steps: Rc<RefCell<Vec<SequenceStep<f32>>>>,
        samples: Rc<RefCell<Vec<SequenceSample<f32>>>>,
    }

    impl SequenceFixture {
        fn open(cx: &mut TestAppContext, steps: Vec<SequenceStep<f32>>) -> Self {
            let steps = Rc::new(RefCell::new(steps));
            let samples = Rc::new(RefCell::new(Vec::new()));
            let window = cx.open_window(size(px(100.), px(100.)), {
                let steps = steps.clone();
                let samples = samples.clone();
                move |_, _| SequenceView { steps, samples }
            });
            cx.run_until_parked();
            Self {
                window,
                steps,
                samples,
            }
        }

        fn linear(millis: u64) -> Transition {
            Transition::new(Duration::from_millis(millis)).ease(|t| t)
        }

        fn last(&self) -> SequenceSample<f32> {
            *self.samples.borrow().last().unwrap()
        }

        fn render(&self, cx: &mut TestAppContext) -> SequenceSample<f32> {
            self.window
                .update(cx, |_, window, _| window.refresh())
                .unwrap();
            cx.run_until_parked();
            self.last()
        }

        fn advance(&self, cx: &mut TestAppContext, millis: u64) -> SequenceSample<f32> {
            cx.executor().advance_clock(Duration::from_millis(millis));
            self.render(cx)
        }

        fn pending_frame(&self, cx: &mut TestAppContext) -> usize {
            self.window
                .update(cx, |_, window, cx| window.simulate_next_frame(cx))
                .unwrap()
        }
    }

    fn assert_sample(sample: SequenceSample<f32>, value: f32, step: usize, status: MotionStatus) {
        assert_eq!(
            (*sample.value(), sample.step(), sample.status()),
            (value, step, status)
        );
    }

    #[gpui::test]
    fn sequence_steps_advance_in_order_at_their_boundaries(cx: &mut TestAppContext) {
        let fixture = SequenceFixture::open(
            cx,
            vec![
                SequenceStep::new(10.0, SequenceFixture::linear(100)),
                SequenceStep::new(
                    20.0,
                    SequenceFixture::linear(100).delay(Duration::from_millis(50)),
                ),
            ],
        );
        assert_sample(fixture.last(), 0.0, 0, MotionStatus::Running);
        assert_sample(fixture.advance(cx, 50), 5.0, 0, MotionStatus::Running);

        // The first step ends and the second begins within one frame; nothing
        // reports the first step as finished in between.
        assert_sample(fixture.advance(cx, 50), 10.0, 1, MotionStatus::Delayed);
        assert_sample(fixture.advance(cx, 50), 10.0, 1, MotionStatus::Running);
        assert_sample(fixture.advance(cx, 50), 15.0, 1, MotionStatus::Running);
        assert_sample(fixture.advance(cx, 50), 20.0, 1, MotionStatus::Finished);
    }

    #[gpui::test]
    fn a_sequence_starts_its_next_step_where_the_previous_ended_not_at_the_frame(
        cx: &mut TestAppContext,
    ) {
        let fixture = SequenceFixture::open(
            cx,
            vec![
                SequenceStep::new(10.0, SequenceFixture::linear(100)),
                SequenceStep::new(20.0, SequenceFixture::linear(100)),
            ],
        );
        // One frame at 50 ms, the next at 175 ms: the boundary at 100 ms fell
        // between them, and the second step is sampled as if it started there.
        fixture.advance(cx, 50);
        assert_sample(fixture.advance(cx, 125), 17.5, 1, MotionStatus::Running);
    }

    #[gpui::test]
    fn zero_duration_steps_complete_within_the_frame_that_reaches_them(cx: &mut TestAppContext) {
        let fixture = SequenceFixture::open(
            cx,
            vec![
                SequenceStep::new(5.0, SequenceFixture::linear(0)),
                SequenceStep::new(6.0, SequenceFixture::linear(0)),
                SequenceStep::new(10.0, SequenceFixture::linear(100)),
            ],
        );
        assert_sample(fixture.last(), 6.0, 2, MotionStatus::Running);
        assert_sample(fixture.advance(cx, 50), 8.0, 2, MotionStatus::Running);
    }

    #[gpui::test]
    fn a_sequence_reports_finished_once_and_then_stops_requesting_frames(cx: &mut TestAppContext) {
        let fixture = SequenceFixture::open(
            cx,
            vec![
                SequenceStep::new(10.0, SequenceFixture::linear(100)),
                SequenceStep::new(20.0, SequenceFixture::linear(100)),
            ],
        );
        assert_eq!(fixture.pending_frame(cx), 1);
        cx.run_until_parked();

        cx.executor().advance_clock(Duration::from_millis(100));
        assert_eq!(fixture.pending_frame(cx), 1);
        cx.run_until_parked();
        assert_eq!(fixture.last().status(), MotionStatus::Running);
        assert!(
            fixture
                .samples
                .borrow()
                .iter()
                .all(|sample| !sample.is_finished()),
            "the first step's end must not read as the sequence finishing"
        );

        assert_sample(fixture.advance(cx, 100), 20.0, 1, MotionStatus::Finished);
        fixture.pending_frame(cx);
        cx.run_until_parked();
        assert_eq!(fixture.pending_frame(cx), 0);
        assert_sample(fixture.advance(cx, 1_000), 20.0, 1, MotionStatus::Finished);
    }

    #[gpui::test]
    fn reduced_motion_adopts_a_sequences_last_target_without_requesting_a_frame(
        cx: &mut TestAppContext,
    ) {
        cx.update(|cx| cx.set_reduce_motion(true));
        let fixture = SequenceFixture::open(
            cx,
            vec![
                SequenceStep::new(10.0, SequenceFixture::linear(100)),
                SequenceStep::new(20.0, SequenceFixture::linear(100)),
            ],
        );
        assert_sample(fixture.last(), 20.0, 1, MotionStatus::Finished);
        assert_eq!(fixture.pending_frame(cx), 0);
    }

    #[gpui::test]
    fn a_changed_step_target_restarts_the_sequence_from_the_sampled_value(cx: &mut TestAppContext) {
        let fixture = SequenceFixture::open(
            cx,
            vec![
                SequenceStep::new(10.0, SequenceFixture::linear(100)),
                SequenceStep::new(20.0, SequenceFixture::linear(100)),
            ],
        );
        fixture.advance(cx, 150);
        assert_sample(fixture.last(), 15.0, 1, MotionStatus::Running);

        *fixture.steps.borrow_mut() = vec![
            SequenceStep::new(10.0, SequenceFixture::linear(100)),
            SequenceStep::new(35.0, SequenceFixture::linear(100)),
        ];
        assert_sample(fixture.render(cx), 15.0, 0, MotionStatus::Running);
        assert_sample(fixture.advance(cx, 50), 12.5, 0, MotionStatus::Running);
        assert_sample(fixture.advance(cx, 100), 22.5, 1, MotionStatus::Running);

        // Fewer steps than the one being played is a different sequence too.
        *fixture.steps.borrow_mut() = vec![SequenceStep::new(0.0, SequenceFixture::linear(100))];
        assert_sample(fixture.render(cx), 22.5, 0, MotionStatus::Running);
        assert_sample(fixture.advance(cx, 100), 0.0, 0, MotionStatus::Finished);
    }

    #[gpui::test]
    fn a_change_to_a_step_not_being_played_does_not_restart_the_sequence(cx: &mut TestAppContext) {
        let fixture = SequenceFixture::open(
            cx,
            vec![
                SequenceStep::new(10.0, SequenceFixture::linear(100)),
                SequenceStep::new(20.0, SequenceFixture::linear(100)),
            ],
        );
        fixture.advance(cx, 50);
        *fixture.steps.borrow_mut() = vec![
            SequenceStep::new(10.0, SequenceFixture::linear(100)),
            SequenceStep::new(30.0, SequenceFixture::linear(100)),
        ];
        assert_sample(fixture.render(cx), 5.0, 0, MotionStatus::Running);
        assert_sample(fixture.advance(cx, 100), 20.0, 1, MotionStatus::Running);
    }

    struct SingleStepView {
        armed: Rc<Cell<bool>>,
        samples: Rc<RefCell<Vec<(SequenceSample<f32>, MotionValue<f32>)>>>,
    }

    impl Render for SingleStepView {
        fn render(
            &mut self,
            window: &mut Window,
            cx: &mut gpui::Context<Self>,
        ) -> impl IntoElement {
            let policy = Transition::new(Duration::from_millis(100))
                .delay(Duration::from_millis(20))
                .easing(Easing::EaseInOut);
            // A plain transition adopts its first target where a sequence
            // plays from `from` at once, so the transition is primed at 0.0
            // and both leave for 10.0 on the frame that arms the view.
            if !self.armed.get() {
                transition_with_status("plain", 0.0, policy, window, cx);
                return Empty;
            }
            let sequence = Sequence::new("single-step", 0.0)
                .with_step(10.0, policy.clone())
                .sample(window, cx);
            let plain = transition_with_status("plain", 10.0, policy, window, cx);
            self.samples.borrow_mut().push((sequence, plain));
            Empty
        }
    }

    #[gpui::test]
    fn a_single_step_sequence_matches_a_plain_transition(cx: &mut TestAppContext) {
        let armed = Rc::new(Cell::new(false));
        let samples = Rc::new(RefCell::new(Vec::new()));
        let window = cx.open_window(size(px(100.), px(100.)), {
            let armed = armed.clone();
            let samples = samples.clone();
            move |_, _| SingleStepView { armed, samples }
        });
        cx.run_until_parked();
        armed.set(true);
        for millis in [0, 10, 30, 70, 120] {
            cx.executor().advance_clock(Duration::from_millis(millis));
            window.update(cx, |_, window, _| window.refresh()).unwrap();
            cx.run_until_parked();
            let (sequence, plain) = *samples.borrow().last().unwrap();
            assert_eq!(*sequence.value(), plain.value, "value after {millis} ms");
            assert_eq!(sequence.status(), plain.status, "status after {millis} ms");
            assert_eq!(sequence.step(), 0);
        }
    }

    #[gpui::test]
    fn an_empty_sequence_idles_at_its_starting_value(cx: &mut TestAppContext) {
        let fixture = SequenceFixture::open(cx, Vec::new());
        assert_sample(fixture.last(), 0.0, 0, MotionStatus::Idle);
        assert_eq!(fixture.pending_frame(cx), 0);
    }

    #[test]
    fn transition_ids_accept_element_like_scalars_and_named_channels() {
        assert_eq!(
            TransitionId::from("opacity"),
            TransitionId::from(ElementId::from("opacity"))
        );
        assert_ne!(
            TransitionId::from(("terms", "fill")),
            TransitionId::from(("terms", "mark-opacity"))
        );
        let _: TransitionId = 7usize.into();
        let _: TransitionId = 7i32.into();
    }

    struct TestView {
        target: Rc<Cell<f32>>,
        duration: Duration,
        samples: Rc<RefCell<Vec<f32>>>,
    }

    impl Render for TestView {
        fn render(
            &mut self,
            window: &mut Window,
            cx: &mut gpui::Context<Self>,
        ) -> impl IntoElement {
            self.samples.borrow_mut().push(transition(
                ("test", "value"),
                self.target.get(),
                Transition::new(self.duration).ease(|t| t),
                window,
                cx,
            ));
            Empty
        }
    }

    struct DelayedView {
        target: Rc<Cell<f32>>,
        samples: Rc<RefCell<Vec<f32>>>,
    }

    impl Render for DelayedView {
        fn render(
            &mut self,
            window: &mut Window,
            cx: &mut gpui::Context<Self>,
        ) -> impl IntoElement {
            self.samples.borrow_mut().push(transition(
                ("delayed-test", "value"),
                self.target.get(),
                Transition::new(Duration::from_millis(100))
                    .delay(Duration::from_millis(50))
                    .ease(|t| t),
                window,
                cx,
            ));
            Empty
        }
    }

    struct Fixture {
        window: WindowHandle<TestView>,
        target: Rc<Cell<f32>>,
        samples: Rc<RefCell<Vec<f32>>>,
    }

    impl Fixture {
        fn open(cx: &mut TestAppContext, duration: Duration) -> Self {
            let target = Rc::new(Cell::new(0.0));
            let samples = Rc::new(RefCell::new(Vec::new()));
            let window = cx.open_window(size(px(100.), px(100.)), {
                let target = target.clone();
                let samples = samples.clone();
                move |_, _| TestView {
                    target,
                    duration,
                    samples,
                }
            });
            cx.run_until_parked();
            Self {
                window,
                target,
                samples,
            }
        }

        fn render(&self, cx: &mut TestAppContext, target: f32) -> f32 {
            self.target.set(target);
            self.window
                .update(cx, |_, window, _| window.refresh())
                .unwrap();
            cx.run_until_parked();
            *self.samples.borrow().last().unwrap()
        }

        fn pending_frame(&self, cx: &mut TestAppContext) -> usize {
            self.window
                .update(cx, |_, window, cx| window.simulate_next_frame(cx))
                .unwrap()
        }
    }

    #[gpui::test]
    fn a_zero_duration_target_change_is_immediate(cx: &mut TestAppContext) {
        let fixture = Fixture::open(cx, Duration::ZERO);
        assert_eq!(fixture.render(cx, 1.0), 1.0);
    }

    #[gpui::test]
    fn a_changed_target_transitions_over_time(cx: &mut TestAppContext) {
        let duration = Duration::from_millis(100);
        let fixture = Fixture::open(cx, duration);
        assert_eq!(fixture.render(cx, 10.0), 0.0);

        cx.executor().advance_clock(Duration::from_millis(50));
        assert_eq!(fixture.render(cx, 10.0), 5.0);
    }

    #[gpui::test]
    fn requested_animation_frames_resample_without_manual_refresh(cx: &mut TestAppContext) {
        let duration = Duration::from_millis(100);
        let fixture = Fixture::open(cx, duration);
        assert_eq!(fixture.render(cx, 10.0), 0.0);

        cx.executor().advance_clock(Duration::from_millis(50));
        assert_eq!(fixture.pending_frame(cx), 1);
        cx.run_until_parked();

        assert_eq!(*fixture.samples.borrow().last().unwrap(), 5.0);
    }

    #[gpui::test]
    fn reversing_uses_the_current_sample_and_shortens_the_return(cx: &mut TestAppContext) {
        let duration = Duration::from_millis(100);
        let fixture = Fixture::open(cx, duration);
        assert_eq!(fixture.render(cx, 10.0), 0.0);

        cx.executor().advance_clock(Duration::from_millis(50));
        assert_eq!(fixture.render(cx, 0.0), 5.0);
        cx.executor().advance_clock(Duration::from_millis(25));
        assert_eq!(fixture.render(cx, 0.0), 2.5);
    }

    #[gpui::test]
    fn delay_holds_the_previous_value_before_interpolation(cx: &mut TestAppContext) {
        let target = Rc::new(Cell::new(0.0));
        let samples = Rc::new(RefCell::new(Vec::new()));
        let window = cx.open_window(size(px(100.), px(100.)), {
            let target = target.clone();
            let samples = samples.clone();
            move |_, _| DelayedView { target, samples }
        });
        cx.run_until_parked();

        target.set(10.0);
        window.update(cx, |_, window, _| window.refresh()).unwrap();
        cx.run_until_parked();
        assert_eq!(*samples.borrow().last().unwrap(), 0.0);

        cx.executor().advance_clock(Duration::from_millis(50));
        window.update(cx, |_, window, _| window.refresh()).unwrap();
        cx.run_until_parked();
        assert_eq!(*samples.borrow().last().unwrap(), 0.0);

        cx.executor().advance_clock(Duration::from_millis(50));
        window.update(cx, |_, window, _| window.refresh()).unwrap();
        cx.run_until_parked();
        assert_eq!(*samples.borrow().last().unwrap(), 5.0);
    }

    #[gpui::test]
    fn a_completed_transition_stops_requesting_frames(cx: &mut TestAppContext) {
        let duration = Duration::from_millis(100);
        let fixture = Fixture::open(cx, duration);
        fixture.render(cx, 1.0);
        assert_eq!(fixture.pending_frame(cx), 1);

        cx.executor().advance_clock(duration);
        assert_eq!(fixture.render(cx, 1.0), 1.0);
        fixture.pending_frame(cx);
        cx.run_until_parked();
        assert_eq!(fixture.pending_frame(cx), 0);
    }

    #[gpui::test]
    fn reduced_motion_adopts_the_target_without_requesting_a_frame(cx: &mut TestAppContext) {
        cx.update(|cx| cx.set_reduce_motion(true));
        let duration = Duration::from_millis(100);
        let fixture = Fixture::open(cx, duration);
        assert_eq!(fixture.render(cx, 1.0), 1.0);
        assert_eq!(fixture.pending_frame(cx), 0);
    }

    struct SpringView {
        target: Rc<Cell<f32>>,
        policy: Rc<Cell<Spring>>,
        samples: Rc<RefCell<Vec<f32>>>,
    }

    impl Render for SpringView {
        fn render(
            &mut self,
            window: &mut Window,
            cx: &mut gpui::Context<Self>,
        ) -> impl IntoElement {
            self.samples.borrow_mut().push(spring(
                ("spring-test", "value"),
                self.target.get(),
                self.policy.get(),
                window,
                cx,
            ));
            Empty
        }
    }

    struct SpringFixture {
        window: WindowHandle<SpringView>,
        target: Rc<Cell<f32>>,
        policy: Rc<Cell<Spring>>,
        samples: Rc<RefCell<Vec<f32>>>,
    }

    impl SpringFixture {
        fn open(cx: &mut TestAppContext, policy: Spring) -> Self {
            let target = Rc::new(Cell::new(0.0));
            let policy = Rc::new(Cell::new(policy));
            let samples = Rc::new(RefCell::new(Vec::new()));
            let window = cx.open_window(size(px(100.), px(100.)), {
                let target = target.clone();
                let policy = policy.clone();
                let samples = samples.clone();
                move |_, _| SpringView {
                    target,
                    policy,
                    samples,
                }
            });
            cx.run_until_parked();
            Self {
                window,
                target,
                policy,
                samples,
            }
        }

        fn render(&self, cx: &mut TestAppContext, target: f32) -> f32 {
            self.target.set(target);
            self.window
                .update(cx, |_, window, _| window.refresh())
                .unwrap();
            cx.run_until_parked();
            *self.samples.borrow().last().unwrap()
        }

        fn advance(&self, cx: &mut TestAppContext, millis: u64, target: f32) -> f32 {
            cx.executor().advance_clock(Duration::from_millis(millis));
            self.render(cx, target)
        }

        fn pending_frame(&self, cx: &mut TestAppContext) -> usize {
            self.window
                .update(cx, |_, window, cx| window.simulate_next_frame(cx))
                .unwrap()
        }
    }

    #[gpui::test]
    fn a_spring_adopts_its_first_target_immediately(cx: &mut TestAppContext) {
        let fixture = SpringFixture::open(cx, Spring::new(Duration::from_millis(300)));
        assert_eq!(*fixture.samples.borrow().first().unwrap(), 0.0);
    }

    #[gpui::test]
    fn a_spring_travels_toward_its_target_over_time(cx: &mut TestAppContext) {
        let fixture = SpringFixture::open(cx, Spring::new(Duration::from_millis(300)));
        assert_eq!(fixture.render(cx, 1.0), 0.0);

        let early = fixture.advance(cx, 50, 1.0);
        let late = fixture.advance(cx, 50, 1.0);
        assert!(
            0.0 < early && early < late && late < 1.0,
            "expected monotonic approach, got {early} then {late}"
        );
    }

    #[gpui::test]
    fn a_reversed_spring_keeps_its_momentum_before_turning_around(cx: &mut TestAppContext) {
        let fixture = SpringFixture::open(cx, Spring::new(Duration::from_millis(300)));
        fixture.render(cx, 1.0);
        let reversed_at = fixture.advance(cx, 100, 1.0);

        // Retarget mid-flight. A duration-based transition restarts its easing
        // here and moves away from 1.0 on the very next frame.
        assert_eq!(fixture.render(cx, 0.0), reversed_at);

        let next = fixture.advance(cx, 16, 0.0);
        assert!(
            next > reversed_at,
            "expected the spring to carry its velocity past {reversed_at}, got {next}"
        );

        assert_eq!(fixture.advance(cx, 1_000, 0.0), 0.0);
    }

    #[gpui::test]
    fn a_bouncy_spring_overshoots_its_target(cx: &mut TestAppContext) {
        let fixture = SpringFixture::open(
            cx,
            Spring::new(Duration::from_millis(350)).with_damping(0.7),
        );
        fixture.render(cx, 1.0);
        for _ in 0..30 {
            fixture.advance(cx, 16, 1.0);
        }

        let peak = fixture
            .samples
            .borrow()
            .iter()
            .copied()
            .fold(f32::MIN, f32::max);
        assert!(peak > 1.0, "expected an overshoot past 1.0, got {peak}");
    }

    #[gpui::test]
    fn a_settled_spring_stops_requesting_frames(cx: &mut TestAppContext) {
        let fixture = SpringFixture::open(cx, Spring::new(Duration::from_millis(300)));
        fixture.render(cx, 1.0);
        assert_eq!(fixture.pending_frame(cx), 1);

        assert_eq!(fixture.advance(cx, 2_000, 1.0), 1.0);
        fixture.pending_frame(cx);
        cx.run_until_parked();
        assert_eq!(fixture.pending_frame(cx), 0);
    }

    #[gpui::test]
    fn a_spring_that_is_not_travelling_adopts_its_target_on_the_spot(cx: &mut TestAppContext) {
        let travelling = Spring::new(Duration::from_millis(300));
        let fixture = SpringFixture::open(cx, travelling.with_travel(false));

        assert_eq!(fixture.render(cx, 1.0), 1.0);
        assert_eq!(fixture.pending_frame(cx), 0);
        assert_eq!(fixture.advance(cx, 100, 5.0), 5.0);

        // Travel resumes from the value the suspension left behind. A spring
        // that had kept the state it held beforehand would jump back to it here.
        fixture.policy.set(travelling);
        assert_eq!(fixture.render(cx, 6.0), 5.0);
        let next = fixture.advance(cx, 50, 6.0);
        assert!(
            5.0 < next && next < 6.0,
            "expected travel to resume from 5.0, got {next}"
        );
    }

    #[gpui::test]
    fn a_zero_response_spring_resolves_instead_of_dividing_by_its_period(cx: &mut TestAppContext) {
        let fixture = SpringFixture::open(cx, Spring::new(Duration::ZERO));
        assert_eq!(fixture.render(cx, 1.0), 1.0);
        assert_eq!(fixture.pending_frame(cx), 0);
    }

    #[test]
    fn spring_rejects_non_finite_or_negative_physical_parameters() {
        let spring = Spring::new(Duration::from_millis(300));

        assert_eq!(
            spring.try_with_damping(f32::NAN).unwrap_err(),
            SpringError::InvalidDamping
        );
        assert_eq!(
            spring.try_with_damping(-0.1).unwrap_err(),
            SpringError::InvalidDamping
        );
        assert_eq!(
            spring.try_with_epsilon(f32::INFINITY).unwrap_err(),
            SpringError::InvalidEpsilon
        );
        assert_eq!(
            spring.try_with_epsilon(-0.1).unwrap_err(),
            SpringError::InvalidEpsilon
        );
    }

    #[test]
    fn spring_reports_its_unit_specific_settling_tolerance() {
        let normalized = Spring::new(Duration::from_millis(180));
        let pixels = Spring::new(Duration::from_millis(180)).with_epsilon(0.1);

        assert!(normalized.epsilon() < 0.01);
        assert_eq!(pixels.epsilon(), 0.1);
    }

    #[gpui::test]
    fn reduced_motion_adopts_the_spring_target_without_requesting_a_frame(cx: &mut TestAppContext) {
        cx.update(|cx| cx.set_reduce_motion(true));
        let fixture = SpringFixture::open(
            cx,
            Spring::new(Duration::from_millis(350)).with_damping(0.7),
        );
        assert_eq!(fixture.render(cx, 1.0), 1.0);
        assert_eq!(fixture.pending_frame(cx), 0);
    }
}
