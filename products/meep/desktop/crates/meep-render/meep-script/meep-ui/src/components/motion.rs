//! Native motion policy, shared by the host, GPUI Kit controls and generated views.
//! Input owns intent; keyed Base channels own interpolation and exit lifetime.
use gpui_kit::base::{Easing, Presence, PresenceSample, Spring, Transition};
use gpui_kit::component::{ActiveTheme, Theme, theme::MotionTokens};
use gpui_kit::*;
use std::{cell::Cell, time::Duration};

pub const FAST: Duration = Duration::from_millis(120);
pub const NORMAL: Duration = Duration::from_millis(180);
pub const SLOW: Duration = Duration::from_millis(240);
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum InputOrigin {
    #[default]
    Pointer,
    Keyboard,
}
thread_local! {
    static ORIGIN:Cell<InputOrigin>=const {Cell::new(InputOrigin::Pointer)};
    static SAVED_REDUCTION:Cell<Option<bool>>=const {Cell::new(None)};
}
pub fn origin() -> InputOrigin {
    ORIGIN.with(Cell::get)
}
/// Activity indicators follow the accessibility preference, not the temporary
/// instant-transition policy applied while typing or navigating with keys.
/// The saved preference is authoritative until pointer mode restores it.
pub fn reduced_activity(cx: &App) -> bool {
    SAVED_REDUCTION
        .with(|saved| saved.get())
        .unwrap_or_else(|| cx.reduce_motion())
}
pub fn ease_out() -> Easing {
    Easing::cubic_bezier(0.23, 1., 0.32, 1.).expect("fixed design-system curve")
}
pub fn ease_move() -> Easing {
    Easing::cubic_bezier(0.77, 0., 0.175, 1.).expect("fixed design-system curve")
}
pub fn tokens(input: InputOrigin) -> MotionTokens {
    let instant = input == InputOrigin::Keyboard;
    let mut tokens = MotionTokens::default();
    tokens.duration_fast = if instant { Duration::ZERO } else { FAST };
    tokens.duration_normal = if instant { Duration::ZERO } else { NORMAL };
    tokens.duration_slow = if instant { Duration::ZERO } else { SLOW };
    tokens.easing_enter = ease_out();
    tokens.easing_exit = ease_out();
    tokens.easing_move = ease_move();
    tokens.spring_control = Spring::new(NORMAL).with_damping(1.).with_travel(!instant);
    tokens.spring_move = Spring::new(SLOW)
        .with_damping(1.)
        .with_epsilon(0.1)
        .with_travel(!instant);
    tokens
}
/// Change policy only when input mode changes, never for every keystroke/frame.
/// GPUI's system reduced-motion preference remains independent and authoritative.
pub fn set_input(input: InputOrigin, cx: &mut App) {
    if ORIGIN.with(|current| current.replace(input)) == input {
        return;
    }
    match input {
        InputOrigin::Keyboard => {
            SAVED_REDUCTION.with(|saved| saved.set(Some(cx.reduce_motion())));
            cx.set_reduce_motion(true);
        }
        InputOrigin::Pointer => {
            if let Some(previous) = SAVED_REDUCTION.with(|saved| saved.take()) {
                cx.set_reduce_motion(previous);
            }
            gpui_kit::base::apply_system_reduce_motion(cx);
        }
    }
    Theme::update(cx, |theme| theme.motion = tokens(input));
}
/// Refresh OS preferences without mistaking our temporary keyboard policy for
/// an application override. This never changes the operating-system setting.
pub fn refresh_system(cx: &mut App) {
    if let Some(previous) = SAVED_REDUCTION.with(|saved| saved.take()) {
        cx.set_reduce_motion(previous);
    }
    gpui_kit::base::apply_system_reduce_motion(cx);
    if origin() == InputOrigin::Keyboard {
        SAVED_REDUCTION.with(|saved| saved.set(Some(cx.reduce_motion())));
        cx.set_reduce_motion(true);
    }
}
/// Sample on every owner render, including closed state. Keep the visual mounted
/// until should_render is false; disable hit targets/focus traps as soon as closed.
pub fn presence(
    id: impl Into<ElementId>,
    present: bool,
    window: &mut Window,
    cx: &mut App,
) -> PresenceSample {
    let policy = cx.theme().motion_tokens();
    // Exits are quicker than entries: the user decided, the system responds.
    // The duration is captured when the target changes, so a reversal mid-way
    // takes the timing of the direction it is now heading.
    let transition = if present {
        Transition::new(policy.duration_normal).easing(policy.easing_enter.clone())
    } else {
        Transition::new(policy.duration_fast).easing(policy.easing_exit.clone())
    };
    Presence::new(id.into(), present)
        .transition(transition)
        .sample(window, cx)
}

/// One arrival of new content: progress runs 0 → 1 from the first sample under
/// `id`, so a caller starts another by sampling a fresh id. `slow` is for rare
/// moments that deserve a longer beat; keyboard input and reduced motion
/// settle it at once.
pub fn arrival(
    id: impl Into<ElementId>,
    slow: bool,
    window: &mut Window,
    cx: &mut App,
) -> PresenceSample {
    let policy = cx.theme().motion_tokens();
    let duration = if slow {
        policy.duration_slow
    } else {
        policy.duration_normal
    };
    Presence::new(id.into(), true)
        .transition(Transition::new(duration).easing(policy.easing_enter.clone()))
        .sample(window, cx)
}

/// Remaining travel for an entering surface: `distance` points at progress 0,
/// none when settled. Surfaces arrive from where they live (a panel from its
/// edge, a sheet from slightly below) instead of appearing from nowhere.
pub fn travel(progress: f32, distance: f32) -> f32 {
    (1. - progress.clamp(0., 1.)) * distance
}

/// Measured disclosure progress. A settled closed channel is exactly zero, so
/// callers can skip allocating and shaping hidden tool output entirely.
pub fn reveal(id: impl Into<ElementId>, open: bool, window: &mut Window, cx: &mut App) -> f32 {
    let id: ElementId = id.into();
    gpui_kit::base::spring(
        id,
        if open { 1.0_f32 } else { 0.0_f32 },
        cx.theme().motion_tokens().spring_control,
        window,
        cx,
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    #[::core::prelude::v1::test]
    fn keyboard_policy_is_immediate_and_pointer_policy_is_bounded() {
        let keyboard = tokens(InputOrigin::Keyboard);
        assert_eq!(keyboard.duration_fast, Duration::ZERO);
        assert_eq!(keyboard.duration_normal, Duration::ZERO);
        assert_eq!(keyboard.duration_slow, Duration::ZERO);
        let pointer = tokens(InputOrigin::Pointer);
        assert_eq!(pointer.duration_fast, FAST);
        assert_eq!(pointer.duration_normal, NORMAL);
        assert!(pointer.duration_slow < Duration::from_millis(300));
    }
    #[::core::prelude::v1::test]
    fn curves_are_monotonic() {
        for curve in [ease_out(), ease_move()] {
            assert_eq!(curve.sample(0.), 0.);
            assert_eq!(curve.sample(1.), 1.);
            let mut previous = 0.;
            for i in 1..=100 {
                let sample = curve.sample(i as f32 / 100.);
                assert!(sample >= previous && sample <= 1.);
                previous = sample;
            }
        }
    }
    #[::core::prelude::v1::test]
    fn travel_settles_at_rest_and_starts_at_its_distance() {
        assert_eq!(travel(1., 16.), 0.);
        assert_eq!(travel(0., 16.), 16.);
        assert_eq!(travel(2., 16.), 0.);
        assert!(travel(0.5, 16.) > 0. && travel(0.5, 16.) < 16.);
    }
}
