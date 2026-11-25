use std::time::Duration;

use super::Easing;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SignedDuration {
    Positive(Duration),
    Negative(Duration),
}

impl SignedDuration {
    pub const ZERO: Self = Self::Positive(Duration::ZERO);

    pub const fn positive(duration: Duration) -> Self {
        Self::Positive(duration)
    }

    pub const fn negative(duration: Duration) -> Self {
        Self::Negative(duration)
    }

    pub(crate) fn active_elapsed(self, elapsed: Duration) -> Option<Duration> {
        match self {
            Self::Positive(delay) => elapsed.checked_sub(delay),
            Self::Negative(delay) => Some(elapsed.saturating_add(delay)),
        }
    }
}

impl Default for SignedDuration {
    fn default() -> Self {
        Self::ZERO
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum IterationCount {
    Finite(u64),
    Infinite,
}

impl Default for IterationCount {
    fn default() -> Self {
        Self::Finite(1)
    }
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub enum PlaybackDirection {
    #[default]
    Normal,
    Reverse,
    Alternate,
    AlternateReverse,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum MotionPhase {
    Before,
    Active,
    After,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct TimingSample {
    pub phase: MotionPhase,
    pub directed_progress: f32,
    pub iteration: u64,
    pub active: bool,
    pub finished: bool,
}

#[derive(Clone, Debug)]
pub struct Timing {
    delay: SignedDuration,
    duration: Duration,
    iterations: IterationCount,
    direction: PlaybackDirection,
    easing: Easing,
}

impl Timing {
    pub fn new(duration: Duration) -> Self {
        Self {
            delay: SignedDuration::ZERO,
            duration,
            iterations: IterationCount::Finite(1),
            direction: PlaybackDirection::Normal,
            easing: Easing::Linear,
        }
    }

    pub fn delay(mut self, delay: SignedDuration) -> Self {
        self.delay = delay;
        self
    }

    pub fn iterations(mut self, iterations: IterationCount) -> Self {
        self.iterations = iterations;
        self
    }

    pub fn direction(mut self, direction: PlaybackDirection) -> Self {
        self.direction = direction;
        self
    }

    pub fn ease(mut self, easing: Easing) -> Self {
        self.easing = easing;
        self
    }

    pub fn sample(&self, elapsed: Duration) -> TimingSample {
        let Some(active_elapsed) = self.delay.active_elapsed(elapsed) else {
            return TimingSample {
                phase: MotionPhase::Before,
                directed_progress: self.easing.sample(self.directed(0, 0.0)),
                iteration: 0,
                active: false,
                finished: false,
            };
        };

        let finite_iterations = match self.iterations {
            IterationCount::Finite(count) => Some(count),
            IterationCount::Infinite => None,
        };
        if self.duration.is_zero() || finite_iterations == Some(0) {
            return self.after_sample(finite_iterations.unwrap_or(1));
        }

        let duration_nanos = self.duration.as_nanos();
        let elapsed_nanos = active_elapsed.as_nanos();
        if let Some(count) = finite_iterations
            && elapsed_nanos >= duration_nanos.saturating_mul(count as u128)
        {
            return self.after_sample(count);
        }

        let iteration = (elapsed_nanos / duration_nanos).min(u64::MAX as u128) as u64;
        let iteration_nanos = elapsed_nanos % duration_nanos;
        let progress = iteration_nanos as f64 / duration_nanos as f64;
        TimingSample {
            phase: MotionPhase::Active,
            directed_progress: self
                .easing
                .sample(self.directed(iteration, progress as f32)),
            iteration,
            active: true,
            finished: false,
        }
    }

    fn after_sample(&self, count: u64) -> TimingSample {
        let iteration = count.saturating_sub(1);
        TimingSample {
            phase: MotionPhase::After,
            directed_progress: self.easing.sample(self.directed(iteration, 1.0)),
            iteration,
            active: false,
            finished: true,
        }
    }

    fn directed(&self, iteration: u64, progress: f32) -> f32 {
        let reverse = match self.direction {
            PlaybackDirection::Normal => false,
            PlaybackDirection::Reverse => true,
            PlaybackDirection::Alternate => iteration % 2 == 1,
            PlaybackDirection::AlternateReverse => iteration % 2 == 0,
        };
        if reverse { 1.0 - progress } else { progress }
    }
}
