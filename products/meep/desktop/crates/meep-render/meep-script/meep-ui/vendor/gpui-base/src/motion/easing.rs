use std::{fmt, num::NonZeroU32, rc::Rc, sync::Arc};

use crate::animation::{cubic_bezier, unclamped_cubic_bezier};

/// The point at which a stepped easing jumps.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum StepPosition {
    JumpStart,
    JumpEnd,
    JumpNone,
    JumpBoth,
}

/// One output and its optional input position in a CSS-like `linear()` curve.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct LinearStop {
    pub output: f32,
    pub input: Option<f32>,
}

impl LinearStop {
    pub const fn new(output: f32) -> Self {
        Self {
            output,
            input: None,
        }
    }

    pub const fn at(output: f32, input: f32) -> Self {
        Self {
            output,
            input: Some(input),
        }
    }
}

/// Invalid easing configuration.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum EasingError {
    /// Retained for source compatibility. New validation reports
    /// [`Self::InvalidBezierControlPoint`].
    #[deprecated(note = "use InvalidBezierControlPoint")]
    InvalidBezierX,
    InvalidBezierControlPoint,
    InvalidStepCount,
    InvalidLinearStops,
}

impl fmt::Display for EasingError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        #[allow(deprecated)]
        match self {
            Self::InvalidBezierX | Self::InvalidBezierControlPoint => {
                f.write_str("cubic Bézier control points must be finite and x must be within 0..=1")
            }
            Self::InvalidStepCount => f.write_str("step easing requires a valid step count"),
            Self::InvalidLinearStops => f.write_str("linear easing stops are invalid"),
        }
    }
}

impl std::error::Error for EasingError {}

/// A cheap, cloneable CSS-compatible easing policy.
#[derive(Clone, Default)]
pub enum Easing {
    Linear,
    Ease,
    EaseIn,
    #[default]
    EaseOut,
    EaseInOut,
    CubicBezier {
        x1: f32,
        y1: f32,
        x2: f32,
        y2: f32,
    },
    Steps {
        count: NonZeroU32,
        position: StepPosition,
    },
    LinearStops(Arc<[(f32, f32)]>),
    Custom(Rc<dyn Fn(f32) -> f32>),
}

impl fmt::Debug for Easing {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Linear => f.write_str("Linear"),
            Self::Ease => f.write_str("Ease"),
            Self::EaseIn => f.write_str("EaseIn"),
            Self::EaseOut => f.write_str("EaseOut"),
            Self::EaseInOut => f.write_str("EaseInOut"),
            Self::CubicBezier { x1, y1, x2, y2 } => f
                .debug_struct("CubicBezier")
                .field("x1", x1)
                .field("y1", y1)
                .field("x2", x2)
                .field("y2", y2)
                .finish(),
            Self::Steps { count, position } => f
                .debug_struct("Steps")
                .field("count", count)
                .field("position", position)
                .finish(),
            Self::LinearStops(stops) => f.debug_tuple("LinearStops").field(stops).finish(),
            Self::Custom(_) => f.write_str("Custom(..)"),
        }
    }
}

impl Easing {
    pub fn cubic_bezier(x1: f32, y1: f32, x2: f32, y2: f32) -> Result<Self, EasingError> {
        if !x1.is_finite()
            || !x2.is_finite()
            || !(0.0..=1.0).contains(&x1)
            || !(0.0..=1.0).contains(&x2)
            || !y1.is_finite()
            || !y2.is_finite()
        {
            return Err(EasingError::InvalidBezierControlPoint);
        }
        Ok(Self::CubicBezier { x1, y1, x2, y2 })
    }

    pub fn steps(count: u32, position: StepPosition) -> Result<Self, EasingError> {
        let count = NonZeroU32::new(count).ok_or(EasingError::InvalidStepCount)?;
        if position == StepPosition::JumpNone && count.get() == 1 {
            return Err(EasingError::InvalidStepCount);
        }
        Ok(Self::Steps { count, position })
    }

    pub fn linear_stops(stops: impl IntoIterator<Item = LinearStop>) -> Result<Self, EasingError> {
        let mut stops: Vec<_> = stops.into_iter().collect();
        if stops.len() < 2
            || stops
                .iter()
                .any(|stop| !stop.output.is_finite() || stop.input.is_some_and(|v| !v.is_finite()))
        {
            return Err(EasingError::InvalidLinearStops);
        }

        if stops[0].input.is_none() {
            stops[0].input = Some(0.0);
        }
        let last = stops.len() - 1;
        if stops[last].input.is_none() {
            stops[last].input = Some(1.0);
        }

        let mut anchor = 0;
        while anchor < last {
            let Some(next) = ((anchor + 1)..=last).find(|&ix| stops[ix].input.is_some()) else {
                return Err(EasingError::InvalidLinearStops);
            };
            let from = stops[anchor].input.unwrap();
            let to = stops[next].input.unwrap();
            if !(0.0..=1.0).contains(&from) || !(0.0..=1.0).contains(&to) || to < from {
                return Err(EasingError::InvalidLinearStops);
            }
            let span = (next - anchor) as f32;
            for (offset, stop) in stops[(anchor + 1)..next].iter_mut().enumerate() {
                stop.input = Some(from + (to - from) * (offset + 1) as f32 / span);
            }
            anchor = next;
        }

        Ok(Self::LinearStops(
            stops
                .into_iter()
                .map(|stop| (stop.input.unwrap(), stop.output))
                .collect(),
        ))
    }

    /// Map elapsed `progress`, clamped to `0..=1`, through the curve.
    ///
    /// The output may leave `0..=1`: a cubic Bézier with y control points
    /// outside that range anticipates or overshoots, and linear stops or a
    /// custom curve may do the same. Clamp the result where it drives an
    /// opacity or a color.
    ///
    /// A curve built directly rather than through [`Self::steps`] or
    /// [`Self::linear_stops`] may have nothing to sample: `LinearStops` with
    /// no stops, or one `JumpNone` step, which has no jump. Such a curve
    /// samples as [`Self::Linear`].
    #[inline]
    pub fn sample(&self, progress: f32) -> f32 {
        let progress = progress.clamp(0.0, 1.0);
        match self {
            Self::Linear => progress,
            Self::Ease => cubic_bezier(0.25, 0.1, 0.25, 1.0)(progress),
            Self::EaseIn => cubic_bezier(0.42, 0.0, 1.0, 1.0)(progress),
            Self::EaseOut => cubic_bezier(0.0, 0.0, 0.58, 1.0)(progress),
            Self::EaseInOut => cubic_bezier(0.42, 0.0, 0.58, 1.0)(progress),
            Self::CubicBezier { x1, y1, x2, y2 } => {
                unclamped_cubic_bezier(*x1, *y1, *x2, *y2)(progress)
            }
            Self::Steps { count, position } => {
                let count = count.get() as f32;
                let (jumps, offset) = match position {
                    StepPosition::JumpStart => (count, 1.0),
                    StepPosition::JumpEnd => (count, 0.0),
                    StepPosition::JumpNone => (count - 1.0, 0.0),
                    StepPosition::JumpBoth => (count + 1.0, 1.0),
                };
                if jumps == 0.0 {
                    return progress;
                }
                ((progress * count).floor() + offset).clamp(0.0, jumps) / jumps
            }
            Self::LinearStops(stops) => {
                if stops.is_empty() {
                    return progress;
                }
                let upper = stops.partition_point(|(input, _)| *input <= progress);
                if upper == 0 {
                    return stops[0].1;
                }
                if upper == stops.len() {
                    return stops[stops.len() - 1].1;
                }
                let (x0, y0) = stops[upper - 1];
                let (x1, y1) = stops[upper];
                if x0 == x1 {
                    y1
                } else {
                    y0 + (y1 - y0) * ((progress - x0) / (x1 - x0))
                }
            }
            Self::Custom(easing) => easing(progress),
        }
    }
}

#[cfg(test)]
mod error_tests {
    use super::*;

    #[test]
    fn bezier_errors_name_the_invalid_control_point() {
        let error = Easing::cubic_bezier(0.2, f32::NAN, 0.8, 1.0).unwrap_err();

        assert_eq!(error, EasingError::InvalidBezierControlPoint);
        assert_eq!(
            error.to_string(),
            "cubic Bézier control points must be finite and x must be within 0..=1"
        );
        let _: &dyn std::error::Error = &error;
    }
}
