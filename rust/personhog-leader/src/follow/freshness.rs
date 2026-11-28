use std::time::{Duration, Instant};

/// How recently a followed partition was known to hold every committed changelog record.
///
/// A confirmation is an end offset together with the time it was asked for. The partition
/// is current as of that time once it has applied everything below that offset, so an idle
/// partition and a stalled consumer are told apart.
#[derive(Debug, Default)]
pub struct Freshness {
    /// The next offset to apply.
    position: i64,
    /// The oldest end offset not yet reached, and when it was asked for.
    waiting: Option<(Instant, i64)>,
    confirmed_at: Option<Instant>,
    /// When `position` last moved.
    progressed_at: Option<Instant>,
}

impl Freshness {
    /// The changelog ended at `end` when asked at `asked_at`.
    ///
    /// While an earlier end is still unreached this one is dropped. Keeping the newest
    /// instead would never confirm a follower that runs steadily behind.
    pub fn observe_end(&mut self, asked_at: Instant, end: i64) {
        if self.waiting.is_none() {
            self.waiting = Some((asked_at, end));
            self.settle();
        }
    }

    /// Everything below `position` has been applied.
    pub fn advance(&mut self, position: i64) {
        if position > self.position {
            self.position = position;
            self.progressed_at = Some(Instant::now());
        }
        self.settle();
    }

    /// Whether the reader has stalled: an end it was told of is still unreached, and it
    /// has made no progress toward it for `timeout`. A reader that is behind but moving
    /// has not stalled, and neither has one whose end checks cannot be answered.
    pub fn stalled(&self, now: Instant, timeout: Duration) -> bool {
        self.waiting.is_some_and(|(asked_at, _)| {
            let since = self.progressed_at.map_or(asked_at, |at| at.max(asked_at));
            now.saturating_duration_since(since) >= timeout
        })
    }

    pub fn is_current(&self, now: Instant, threshold: Duration) -> bool {
        self.confirmed_at
            .is_some_and(|at| now.saturating_duration_since(at) <= threshold)
    }

    /// How many offsets short of `end` the reader is.
    pub fn behind(&self, end: i64) -> i64 {
        (end - self.position).max(0)
    }

    /// How long ago the partition last held every committed record, once it has.
    pub fn confirmed_age(&self, now: Instant) -> Option<Duration> {
        self.confirmed_at
            .map(|at| now.saturating_duration_since(at))
    }

    fn settle(&mut self) {
        if let Some((asked_at, end)) = self.waiting {
            if self.position >= end {
                self.confirmed_at = Some(asked_at);
                self.waiting = None;
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const THRESHOLD: Duration = Duration::from_millis(500);

    #[test]
    fn a_partition_is_not_current_before_its_first_confirmation() {
        let mut freshness = Freshness::default();
        freshness.advance(100);
        assert!(!freshness.is_current(Instant::now(), THRESHOLD));
    }

    #[test]
    fn an_idle_partition_stays_current_only_while_confirmations_keep_arriving() {
        let asked = Instant::now();
        let mut freshness = Freshness::default();
        freshness.advance(10);
        freshness.observe_end(asked, 10);

        assert!(freshness.is_current(asked + THRESHOLD, THRESHOLD));
        assert!(!freshness.is_current(asked + THRESHOLD + Duration::from_millis(1), THRESHOLD));
    }

    #[test]
    fn a_partition_behind_the_end_is_current_as_of_when_the_end_was_asked_for() {
        let asked = Instant::now();
        let mut freshness = Freshness::default();
        freshness.observe_end(asked, 10);
        freshness.advance(9);
        assert!(!freshness.is_current(asked, THRESHOLD));

        // Reached 400 ms later: the confirmation is 400 ms old, not new.
        freshness.advance(10);
        let reached = asked + Duration::from_millis(400);
        assert!(freshness.is_current(reached, THRESHOLD));
        assert!(!freshness.is_current(reached + Duration::from_millis(101), THRESHOLD));
    }

    #[test]
    fn a_reader_stalls_only_when_it_stops_moving_toward_a_known_end() {
        const TIMEOUT: Duration = Duration::from_secs(10);
        let now = Instant::now();
        let asked = now
            .checked_sub(TIMEOUT)
            .expect("a clock older than the timeout");
        let mut freshness = Freshness::default();
        // With no end to reach, however long it has been.
        assert!(!freshness.stalled(now, TIMEOUT));

        freshness.observe_end(asked, 10);
        assert!(!freshness.stalled(now - Duration::from_millis(1), TIMEOUT));
        assert!(freshness.stalled(now, TIMEOUT));

        // Behind but moving: the wait restarts from the progress.
        freshness.advance(5);
        assert!(!freshness.stalled(now, TIMEOUT));
        assert!(freshness.stalled(Instant::now() + TIMEOUT, TIMEOUT));

        freshness.advance(10);
        assert!(!freshness.stalled(Instant::now() + TIMEOUT, TIMEOUT));
    }

    #[test]
    fn a_later_end_does_not_replace_one_still_unreached() {
        let first = Instant::now();
        let second = first + Duration::from_millis(100);
        let mut freshness = Freshness::default();
        freshness.observe_end(first, 10);
        freshness.observe_end(second, 20);

        freshness.advance(10);

        assert!(freshness.is_current(first + THRESHOLD, THRESHOLD));
        assert!(!freshness.is_current(second + THRESHOLD, THRESHOLD));
    }
}
