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
pub fn ease_layout() -> Easing {
    Easing::cubic_bezier(0.4, 0., 0.2, 1.).expect("fixed design-system curve")
}
/// A clipped vertical reveal. Keep it mounted while open: settled, it lays its
/// content out normally and records the height, so a close starts from the
/// real height instead of an unmeasured first frame. The content fades faster
/// than the clip moves, so the moving edge never cuts through solid text.
pub fn fold(id: impl Into<ElementId>, progress: f32, child: AnyElement) -> AnyElement {
    let progress = progress.clamp(0., 1.);
    let child = if progress >= 1. {
        child
    } else {
        div()
            .w_full()
            .opacity(progress * progress)
            .child(child)
            .into_any_element()
    };
    Fold {
        id: id.into(),
        progress,
        child,
    }
    .into_any_element()
}

struct Fold {
    id: ElementId,
    progress: f32,
    child: AnyElement,
}

#[derive(Clone, Copy, Default)]
struct FoldHeight(Option<Pixels>);

impl IntoElement for Fold {
    type Element = Self;

    fn into_element(self) -> Self::Element {
        self
    }
}

impl Element for Fold {
    type RequestLayoutState = ();
    type PrepaintState = ();

    fn id(&self) -> Option<ElementId> {
        Some(self.id.clone())
    }

    fn source_location(&self) -> Option<&'static std::panic::Location<'static>> {
        None
    }

    fn request_layout(
        &mut self,
        id: Option<&GlobalElementId>,
        _: Option<&InspectorElementId>,
        window: &mut Window,
        cx: &mut App,
    ) -> (LayoutId, Self::RequestLayoutState) {
        let mut style = Style::default();
        style.size.width = relative(1.).into();
        if self.progress >= 1. {
            let child = self.child.request_layout(window, cx);
            return (window.request_layout(style, [child], cx), ());
        }
        let height = window.with_element_state(
            id.expect("a fold has an id"),
            |state: Option<FoldHeight>, _| {
                let state = state.unwrap_or_default();
                (state.0, state)
            },
        );
        style.size.height = (height.unwrap_or_default() * self.progress).into();
        (window.request_layout(style, None, cx), ())
    }

    fn prepaint(
        &mut self,
        id: Option<&GlobalElementId>,
        _: Option<&InspectorElementId>,
        bounds: Bounds<Pixels>,
        _: &mut Self::RequestLayoutState,
        window: &mut Window,
        cx: &mut App,
    ) -> Self::PrepaintState {
        let measured = if self.progress >= 1. {
            bounds.size.height
        } else {
            self.child
                .layout_as_root(
                    size(
                        AvailableSpace::Definite(bounds.size.width),
                        AvailableSpace::MinContent,
                    ),
                    window,
                    cx,
                )
                .height
        };
        let changed = window.with_element_state(
            id.expect("a fold has an id"),
            |state: Option<FoldHeight>, _| {
                (
                    state.and_then(|s| s.0) != Some(measured),
                    FoldHeight(Some(measured)),
                )
            },
        );
        if changed && self.progress < 1. {
            window.request_animation_frame();
        }
        window.with_content_mask(Some(ContentMask { bounds }), |window| {
            if self.progress >= 1. {
                self.child.prepaint(window, cx);
            } else {
                self.child.prepaint_at(bounds.origin, window, cx);
            }
        });
    }

    fn paint(
        &mut self,
        _: Option<&GlobalElementId>,
        _: Option<&InspectorElementId>,
        bounds: Bounds<Pixels>,
        _: &mut Self::RequestLayoutState,
        _: &mut Self::PrepaintState,
        window: &mut Window,
        cx: &mut App,
    ) {
        window.with_content_mask(Some(ContentMask { bounds }), |window| {
            self.child.paint(window, cx);
        });
    }
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

pub fn pane(
    id: impl Into<ElementId>,
    present: bool,
    window: &mut Window,
    cx: &mut App,
) -> PresenceSample {
    let policy = cx.theme().motion_tokens();
    let duration = if present {
        policy.duration_slow
    } else {
        policy.duration_normal
    };
    Presence::new(id.into(), present)
        .transition(Transition::new(duration).easing(ease_layout()))
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
        for curve in [ease_out(), ease_move(), ease_layout()] {
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
