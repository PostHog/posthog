use std::time::Duration;

use gpui::{Rems, rems};
use gpui_base::{Easing, Spring};

/// Semantic motion policy shared by styled components.
#[derive(Clone, Debug)]
#[non_exhaustive]
pub struct MotionTokens {
    pub duration_instant: Duration,
    pub duration_fast: Duration,
    pub duration_normal: Duration,
    pub duration_slow: Duration,
    pub easing_enter: Easing,
    pub easing_exit: Easing,
    pub easing_move: Easing,
    pub spring_control: Spring,
    pub spring_move: Spring,
    pub distance_short: Rems,
    pub distance_medium: Rems,
}

impl Default for MotionTokens {
    fn default() -> Self {
        Self {
            duration_instant: Duration::ZERO,
            duration_fast: Duration::from_millis(120),
            duration_normal: Duration::from_millis(180),
            duration_slow: Duration::from_millis(280),
            easing_enter: Easing::cubic_bezier(0.16, 1.0, 0.3, 1.0)
                .expect("static enter curve is valid"),
            easing_exit: Easing::cubic_bezier(0.4, 0.0, 1.0, 1.0)
                .expect("static exit curve is valid"),
            easing_move: Easing::cubic_bezier(0.2, 0.0, 0.0, 1.0)
                .expect("static move curve is valid"),
            spring_control: Spring::new(Duration::from_millis(180)),
            spring_move: Spring::new(Duration::from_millis(280))
                .with_damping(0.85)
                .with_epsilon(0.1),
            distance_short: rems(0.25),
            distance_medium: rems(0.5),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn normalized_and_pixel_springs_use_unit_appropriate_tolerances() {
        let motion = MotionTokens::default();

        assert!(motion.spring_control.epsilon() < 0.01);
        assert_eq!(motion.spring_move.epsilon(), 0.1);
    }
}
