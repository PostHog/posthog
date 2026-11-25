use std::time::Duration;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum StaggerOrigin {
    First,
    Last,
    Center,
    Index(usize),
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct Stagger {
    interval: Duration,
    origin: StaggerOrigin,
}

impl Stagger {
    pub const fn new(interval: Duration, origin: StaggerOrigin) -> Self {
        Self { interval, origin }
    }

    #[inline]
    pub fn delay(&self, index: usize, count: usize) -> Duration {
        if count == 0 {
            return Duration::ZERO;
        }
        let index = index.min(count - 1);
        let origin = match self.origin {
            StaggerOrigin::First => 0,
            StaggerOrigin::Last => count - 1,
            StaggerOrigin::Center => (count - 1) / 2,
            StaggerOrigin::Index(origin) => origin.min(count - 1),
        };
        self.interval
            .saturating_mul(index.abs_diff(origin).min(u32::MAX as usize) as u32)
    }
}
