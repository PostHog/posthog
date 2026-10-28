//! Governs how many requests the batcher keeps in flight from request
//! round-trip time.
//!
//! The permit bounds follow the routable workers: the ceiling is the
//! per-worker cap times the pool, so at the ceiling the permits are the free
//! worker slots. Permits move by one at most once per step interval, because
//! a step per settlement walks the pool to the floor in one round trip and
//! then sawtooths against the average. With adaptation off the pool is a
//! shadow: it moves by the law and reports what it would have done, while the
//! batcher sizes its passes by free slots as before.

use std::str::FromStr;
use std::time::{Duration, Instant};

const RTT_TIME_CONSTANT: Duration = Duration::from_secs(10);

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum Adaptation {
    #[default]
    Off,
    On,
}

impl Adaptation {
    pub fn as_str(self) -> &'static str {
        match self {
            Adaptation::Off => "off",
            Adaptation::On => "on",
        }
    }
}

impl FromStr for Adaptation {
    type Err = String;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        match value.trim().to_lowercase().as_str() {
            "off" => Ok(Adaptation::Off),
            "on" => Ok(Adaptation::On),
            other => Err(format!(
                "unknown governor adaptation '{other}' (expected 'on' or 'off')"
            )),
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Direction {
    Grow,
    Shrink,
}

impl Direction {
    pub fn as_str(self) -> &'static str {
        match self {
            Direction::Grow => "grow",
            Direction::Shrink => "shrink",
        }
    }
}

/// One step of the law that moved the pool. `applied` is false when
/// adaptation is off, so the step moved only the shadow pool.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Decision {
    pub direction: Direction,
    pub applied: bool,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct GovernorSettings {
    pub adaptation: Adaptation,
    /// An RTT average above it shrinks the pool. `None` never shrinks.
    pub latency_budget: Option<Duration>,
    pub min_permits_per_worker: usize,
    pub step_interval: Duration,
}

impl GovernorSettings {
    /// Measures and reports with no budget, so the pool stays at the ceiling.
    pub fn observing() -> Self {
        Self {
            adaptation: Adaptation::Off,
            latency_budget: None,
            min_permits_per_worker: 1,
            step_interval: Duration::from_secs(1),
        }
    }
}

/// A point-in-time view, for the gauges and the debug API.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct GovernorSnapshot {
    pub adaptation: Adaptation,
    pub permits: usize,
    pub ceiling: usize,
    pub free_permits: usize,
    pub starved_messages: usize,
    pub rtt: Option<Duration>,
}

/// An exponentially weighted moving average whose weight follows the time
/// between samples, so a burst of settlements counts as one stretch of time.
#[derive(Clone, Debug)]
struct Ewma {
    time_constant: Duration,
    state: Option<(f64, Instant)>,
}

impl Ewma {
    fn new(time_constant: Duration) -> Self {
        Self {
            time_constant,
            state: None,
        }
    }

    fn observe(&mut self, sample: Duration, now: Instant) {
        let sample = sample.as_secs_f64();
        self.state = Some(match self.state {
            None => (sample, now),
            Some((average, last)) => {
                let elapsed = now.saturating_duration_since(last).as_secs_f64();
                let alpha = 1.0 - (-elapsed / self.time_constant.as_secs_f64()).exp();
                (average + alpha * (sample - average), last.max(now))
            }
        });
    }

    fn value(&self) -> Option<Duration> {
        self.state
            .map(|(average, _)| Duration::from_secs_f64(average))
    }
}

pub struct Governor {
    settings: GovernorSettings,
    max_permits_per_worker: usize,
    rtt: Ewma,
    ceiling: usize,
    floor: usize,
    /// How far the law has shrunk the pool below the ceiling. Kept as a
    /// distance so a worker that joins adds its permits to the pool at once,
    /// and clamped on read so an empty pool does not erase it.
    deficit: usize,
    in_flight: usize,
    starved_messages: usize,
    last_step: Option<Instant>,
}

impl Governor {
    pub fn new(settings: GovernorSettings, max_permits_per_worker: usize) -> Result<Self, String> {
        if settings.min_permits_per_worker == 0 {
            return Err("the governor's min permits per worker must be > 0".to_string());
        }
        if settings.min_permits_per_worker > max_permits_per_worker {
            return Err(
                "the governor's min permits per worker must be at most its max".to_string(),
            );
        }
        if settings.step_interval.is_zero() {
            return Err("the governor's step interval must be > 0".to_string());
        }
        if settings.adaptation == Adaptation::On && settings.latency_budget.is_none() {
            return Err("governor adaptation needs a latency budget".to_string());
        }
        Ok(Self {
            settings,
            max_permits_per_worker,
            rtt: Ewma::new(RTT_TIME_CONSTANT),
            ceiling: 0,
            floor: 0,
            deficit: 0,
            in_flight: 0,
            starved_messages: 0,
            last_step: None,
        })
    }

    pub fn adaptation(&self) -> Adaptation {
        self.settings.adaptation
    }

    pub fn permits(&self) -> usize {
        self.ceiling - self.deficit()
    }

    pub fn ceiling(&self) -> usize {
        self.ceiling
    }

    pub fn free(&self) -> usize {
        self.permits().saturating_sub(self.in_flight)
    }

    fn deficit(&self) -> usize {
        self.deficit.min(self.ceiling - self.floor)
    }

    pub fn rtt(&self) -> Option<Duration> {
        self.rtt.value()
    }

    pub fn snapshot(&self) -> GovernorSnapshot {
        GovernorSnapshot {
            adaptation: self.settings.adaptation,
            permits: self.permits(),
            ceiling: self.ceiling,
            free_permits: self.free(),
            starved_messages: self.starved_messages,
            rtt: self.rtt(),
        }
    }

    /// `in_flight` counts the requests on those workers only: a request on a
    /// worker that left the pool holds none of the pool's permits.
    pub fn set_pool(&mut self, workers: usize, in_flight: usize) {
        self.ceiling = self.max_permits_per_worker * workers;
        self.floor = self.settings.min_permits_per_worker * workers;
        self.in_flight = in_flight;
    }

    /// The ready messages the last pass had beyond its free permits. The pool
    /// grows only while the last pass left some, so a burst that has cleared
    /// grows nothing.
    pub fn set_starved_messages(&mut self, messages: usize) {
        self.starved_messages = messages;
    }

    pub fn observe(&mut self, sample: Duration, now: Instant) -> Option<Decision> {
        self.rtt.observe(sample, now);
        if self
            .last_step
            .is_some_and(|last| now < last + self.settings.step_interval)
        {
            return None;
        }
        let over_budget = match (self.rtt.value(), self.settings.latency_budget) {
            (Some(rtt), Some(budget)) => rtt > budget,
            _ => false,
        };
        let direction = if over_budget {
            Direction::Shrink
        } else if self.starved_messages > 0 {
            Direction::Grow
        } else {
            return None;
        };
        let deficit = self.deficit();
        self.deficit = match direction {
            Direction::Shrink if deficit < self.ceiling - self.floor => deficit + 1,
            Direction::Grow if deficit > 0 => deficit - 1,
            _ => return None,
        };
        self.last_step = Some(now);
        Some(Decision {
            direction,
            applied: self.settings.adaptation == Adaptation::On,
        })
    }
}

#[cfg(test)]
mod tests {
    use rstest::rstest;

    use super::*;

    const STEP: Duration = Duration::from_secs(1);
    const BUDGET: Duration = Duration::from_secs(1);
    const SLOW: Duration = Duration::from_secs(2);
    const FAST: Duration = Duration::from_millis(100);
    const MAX_PER_WORKER: usize = 4;

    fn settings(adaptation: Adaptation) -> GovernorSettings {
        GovernorSettings {
            adaptation,
            latency_budget: Some(BUDGET),
            min_permits_per_worker: 1,
            step_interval: STEP,
        }
    }

    /// Two workers: a ceiling of 8 and a floor of 2.
    fn governor(adaptation: Adaptation) -> Governor {
        let mut governor = Governor::new(settings(adaptation), MAX_PER_WORKER).expect("valid");
        governor.set_pool(2, 0);
        governor
    }

    fn applied(direction: Direction) -> Option<Decision> {
        Some(Decision {
            direction,
            applied: true,
        })
    }

    fn unapplied(direction: Direction) -> Option<Decision> {
        Some(Decision {
            direction,
            applied: false,
        })
    }

    #[test]
    fn the_pool_shrinks_by_one_per_step_while_the_rtt_is_over_budget() {
        let now = Instant::now();
        let mut governor = governor(Adaptation::On);
        assert_eq!(governor.permits(), 8);

        assert_eq!(governor.observe(SLOW, now), applied(Direction::Shrink));
        assert_eq!(governor.permits(), 7);
        assert_eq!(
            governor.observe(SLOW, now + STEP / 2),
            None,
            "no second step inside the interval"
        );
        assert_eq!(governor.permits(), 7);
        assert_eq!(
            governor.observe(SLOW, now + STEP),
            applied(Direction::Shrink)
        );
        assert_eq!(governor.permits(), 6);
    }

    #[test]
    fn the_pool_grows_by_one_per_step_while_the_last_pass_was_starved_and_the_rtt_is_within_budget()
    {
        let now = Instant::now();
        let mut governor = governor(Adaptation::On);
        assert_eq!(governor.observe(SLOW, now), applied(Direction::Shrink));
        assert_eq!(
            governor.observe(SLOW, now + STEP),
            applied(Direction::Shrink)
        );
        assert_eq!(governor.permits(), 6);

        // Long enough for the average to forget the slow samples.
        let recovered = now + RTT_TIME_CONSTANT * 10;
        governor.set_starved_messages(3);
        governor.set_starved_messages(0);
        assert_eq!(
            governor.observe(FAST, recovered),
            None,
            "a starved pass that a later pass cleared grows nothing"
        );

        governor.set_starved_messages(3);
        assert_eq!(
            governor.observe(FAST, recovered + STEP),
            applied(Direction::Grow)
        );
        assert_eq!(
            governor.observe(FAST, recovered + STEP * 2),
            applied(Direction::Grow)
        );
        assert_eq!(governor.permits(), 8);
    }

    #[test]
    fn the_pool_clamps_at_the_floor_and_at_the_ceiling() {
        let now = Instant::now();
        let mut governor = governor(Adaptation::On);
        for step in 0..6 {
            assert_eq!(
                governor.observe(SLOW, now + STEP * step),
                applied(Direction::Shrink)
            );
        }
        assert_eq!(governor.permits(), 2);
        assert_eq!(
            governor.observe(SLOW, now + STEP * 6),
            None,
            "a step at a bound moves nothing, so it reports nothing"
        );
        assert_eq!(governor.permits(), 2);

        let mut governor = self::governor(Adaptation::On);
        governor.set_starved_messages(1);
        assert_eq!(governor.observe(FAST, now), None);
        assert_eq!(governor.permits(), 8);
    }

    #[test]
    fn the_bounds_follow_the_routable_workers_and_keep_the_shrink() {
        let now = Instant::now();
        let mut governor = governor(Adaptation::On);
        assert_eq!(governor.observe(SLOW, now), applied(Direction::Shrink));
        assert_eq!(governor.permits(), 7);

        governor.set_pool(1, 0);
        assert_eq!(governor.ceiling(), 4);
        assert_eq!(governor.permits(), 3, "the ceiling dropped by one worker");

        governor.set_pool(3, 0);
        assert_eq!(governor.ceiling(), 12);
        assert_eq!(
            governor.permits(),
            11,
            "a joining worker's permits are usable at once"
        );

        for step in 1..=20 {
            governor.observe(SLOW, now + STEP * step);
        }
        assert_eq!(governor.permits(), 3, "at the floor of one per worker");
        governor.set_pool(1, 0);
        assert_eq!(governor.permits(), 1, "the floor dropped with the pool");
    }

    #[test]
    fn an_empty_pool_keeps_the_shrink_until_workers_return() {
        let now = Instant::now();
        let mut governor = governor(Adaptation::On);
        assert_eq!(governor.observe(SLOW, now), applied(Direction::Shrink));
        assert_eq!(
            governor.observe(SLOW, now + STEP),
            applied(Direction::Shrink)
        );
        assert_eq!(governor.permits(), 6);

        governor.set_pool(0, 0);
        assert_eq!((governor.permits(), governor.free()), (0, 0));
        assert_eq!(
            governor.observe(SLOW, now + STEP * 2),
            None,
            "nothing to govern"
        );

        governor.set_pool(2, 0);
        assert_eq!(governor.permits(), 6);
    }

    #[test]
    fn with_adaptation_off_steps_are_unapplied_and_the_shadow_pool_still_moves() {
        let now = Instant::now();
        let mut shadow = governor(Adaptation::Off);
        shadow.set_pool(2, 8);
        assert_eq!(shadow.free(), 0);

        assert_eq!(shadow.observe(SLOW, now), unapplied(Direction::Shrink));
        assert_eq!(shadow.permits(), 7);
        shadow.set_pool(2, 7);
        assert_eq!(
            shadow.free(),
            0,
            "the shadow pool is at the in-flight count"
        );
    }

    #[test]
    fn the_first_sample_seeds_the_average_and_later_samples_weigh_by_their_spacing() {
        let now = Instant::now();
        let mut ewma = Ewma::new(RTT_TIME_CONSTANT);
        assert_eq!(ewma.value(), None);
        ewma.observe(SLOW, now);
        assert_eq!(ewma.value(), Some(SLOW));

        let mut close = ewma.clone();
        close.observe(Duration::ZERO, now + Duration::from_secs(1));
        let mut apart = ewma;
        apart.observe(Duration::ZERO, now + RTT_TIME_CONSTANT);
        let close = close.value().expect("fed").as_secs_f64();
        let apart = apart.value().expect("fed").as_secs_f64();
        assert!((close - 2.0 * (-0.1f64).exp()).abs() < 0.01, "{close}");
        assert!((apart - 2.0 * (-1.0f64).exp()).abs() < 0.01, "{apart}");
    }

    #[rstest]
    #[case::no_min(GovernorSettings { min_permits_per_worker: 0, ..settings(Adaptation::Off) }, 4)]
    #[case::min_above_max(GovernorSettings { min_permits_per_worker: 5, ..settings(Adaptation::Off) }, 4)]
    #[case::no_step_interval(GovernorSettings { step_interval: Duration::ZERO, ..settings(Adaptation::Off) }, 4)]
    #[case::adaptation_without_a_budget(GovernorSettings { latency_budget: None, ..settings(Adaptation::On) }, 4)]
    fn invalid_settings_are_rejected(
        #[case] settings: GovernorSettings,
        #[case] max_permits_per_worker: usize,
    ) {
        assert!(Governor::new(settings, max_permits_per_worker).is_err());
    }
}
