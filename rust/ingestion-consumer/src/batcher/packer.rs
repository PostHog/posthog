//! Packs ready key runs into requests near a target size, one request per
//! free worker slot.
//!
//! Worst case: 2 × target − 1 events, or 2 × target − 2 bytes plus the largest
//! message. Keys join below the target, and a run is capped at the target.

use std::num::NonZeroUsize;
use std::time::{Duration, Instant};

use metrics::counter;

use super::key_queues::{KeyQueues, ReadySize, RunCap};
use super::request::{Request, RequestClass};

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct PackTargets {
    pub events: Option<NonZeroUsize>,
    pub bytes: Option<NonZeroUsize>,
    pub latency_budget: Duration,
}

impl PackTargets {
    pub fn run_cap(&self) -> RunCap {
        RunCap {
            messages: self.events,
            bytes: self.bytes,
        }
    }

    fn reached(&self, size: ReadySize) -> bool {
        self.run_cap().reached(size)
    }
}

#[derive(Clone, Copy)]
enum PackReason {
    AtTarget,
    Deadline,
    Replay,
    Shutdown,
}

impl PackReason {
    fn as_str(self) -> &'static str {
        match self {
            PackReason::AtTarget => "target",
            PackReason::Deadline => "deadline",
            PackReason::Replay => "replay",
            PackReason::Shutdown => "shutdown",
        }
    }
}

pub struct Packer {
    targets: PackTargets,
    reservation: Option<Instant>,
}

impl Packer {
    pub fn new(targets: PackTargets) -> Self {
        Self {
            targets,
            reservation: None,
        }
    }

    pub fn targets(&self) -> PackTargets {
        self.targets
    }

    pub fn latency_budget(&self) -> Duration {
        self.targets.latency_budget
    }

    pub fn deadline(&self) -> Option<Instant> {
        self.reservation
    }

    /// Builds at most `free_slots` requests and claims only the runs they
    /// hold. A class at the target goes out at once. Ready messages below
    /// the target wait for the latency budget, counted from the first action
    /// that finds a free slot for them, or go out at once when `draining`.
    /// Replays go out at once, because they already waited out a retry delay.
    /// Classes go in `KeyQueues::ready_sizes` order, and a later class goes
    /// ahead only while every earlier one waits below the target.
    pub fn pack(
        &mut self,
        keys: &mut KeyQueues,
        now: Instant,
        free_slots: usize,
        draining: bool,
    ) -> Vec<Request> {
        keys.promote_due(now);
        let mut requests = Vec::new();
        while requests.len() < free_slots {
            let Some((class, reason)) = self.next_request_class(keys, now, draining) else {
                break;
            };
            requests.push(self.build_request(keys, class, reason));
        }
        if !keys.has_ready() {
            self.reservation = None;
        }
        requests
    }

    fn next_request_class(
        &mut self,
        keys: &KeyQueues,
        now: Instant,
        draining: bool,
    ) -> Option<(RequestClass, PackReason)> {
        for &(class, size) in keys.ready_sizes() {
            if self.targets.reached(size) {
                return Some((class, PackReason::AtTarget));
            }
            if class.replay {
                return Some((class, PackReason::Replay));
            }
            if draining {
                self.reservation = None;
                return Some((class, PackReason::Shutdown));
            }
            let deadline = *self
                .reservation
                .get_or_insert(now + self.targets.latency_budget);
            if deadline <= now {
                self.reservation = None;
                return Some((class, PackReason::Deadline));
            }
        }
        None
    }

    fn build_request(
        &self,
        keys: &mut KeyQueues,
        class: RequestClass,
        reason: PackReason,
    ) -> Request {
        let runs = keys.take_runs(class, |taken| self.targets.reached(taken));
        counter!("ingestion_consumer_batcher_packed_requests_total", "reason" => reason.as_str())
            .increment(1);
        Request::from_runs(class, runs)
    }
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;

    use super::*;
    use crate::batcher::key_queues::payload_bytes;
    use crate::batcher::test_support::message;
    use crate::types::SerializedKafkaMessage;

    const BUDGET: Duration = Duration::from_millis(50);
    const NOTHING: [Sent; 0] = [];

    /// A packer and its key queues, driven the way the state machine
    /// drives them: events arrive, slots free up, time passes.
    struct TestPacker {
        packer: Packer,
        keys: KeyQueues,
        now: Instant,
        next_offset: i64,
    }

    impl TestPacker {
        fn with_target(events: usize) -> Self {
            Self::new(PackTargets {
                events: NonZeroUsize::new(events),
                bytes: None,
                latency_budget: BUDGET,
            })
        }

        fn new(targets: PackTargets) -> Self {
            Self {
                packer: Packer::new(targets),
                keys: KeyQueues::new(targets.run_cap()),
                now: Instant::now(),
                next_offset: 0,
            }
        }

        fn arrive(&mut self, key: &str, events: usize) {
            self.arrive_in(0, key, events);
        }

        fn arrive_in(&mut self, epoch: u64, key: &str, events: usize) {
            let messages = self.messages(key, events);
            self.keys.push(Arc::from(key), epoch, messages, self.now);
        }

        fn replay(&mut self, key: &str, events: usize) {
            let messages = self.messages(key, events);
            self.keys.push_replay(Arc::from(key), 0, messages, self.now);
        }

        fn pack(&mut self, free_slots: usize) -> Vec<Sent> {
            self.pack_with(free_slots, false)
        }

        fn pack_for_shutdown(&mut self, free_slots: usize) -> Vec<Sent> {
            self.pack_with(free_slots, true)
        }

        fn advance(&mut self, by: Duration) {
            self.now += by;
        }

        fn deadline_in(&self) -> Option<Duration> {
            self.packer
                .deadline()
                .map(|deadline| deadline.saturating_duration_since(self.now))
        }

        fn revoke_everything(&mut self) {
            self.keys.purge(&[("events".to_string(), 0)]);
        }

        fn pack_with(&mut self, free_slots: usize, draining: bool) -> Vec<Sent> {
            self.packer
                .pack(&mut self.keys, self.now, free_slots, draining)
                .into_iter()
                .map(|request| Sent {
                    epoch: request.class.assignment_epoch,
                    replay: request.class.replay,
                    keys: request
                        .runs
                        .iter()
                        .map(|run| run.routing_key.to_string())
                        .collect(),
                })
                .collect()
        }

        fn messages(&mut self, key: &str, events: usize) -> Vec<SerializedKafkaMessage> {
            (0..events)
                .map(|_| {
                    self.next_offset += 1;
                    message(key, 0, self.next_offset)
                })
                .collect()
        }
    }

    #[derive(Debug, PartialEq)]
    struct Sent {
        epoch: u64,
        replay: bool,
        keys: Vec<String>,
    }

    fn fresh(keys: &[&str]) -> Sent {
        fresh_in(0, keys)
    }

    fn fresh_in(epoch: u64, keys: &[&str]) -> Sent {
        Sent {
            epoch,
            replay: false,
            keys: keys.iter().map(|key| key.to_string()).collect(),
        }
    }

    fn replay(keys: &[&str]) -> Sent {
        Sent {
            replay: true,
            ..fresh(keys)
        }
    }

    fn one_event_bytes() -> usize {
        payload_bytes(&[message("a", 0, 0)])
    }

    #[test]
    fn a_backlog_fills_free_slots_with_full_requests_and_the_rest_waits() {
        let mut packer = TestPacker::with_target(2);
        for key in ["a", "b", "c", "d", "e"] {
            packer.arrive(key, 1);
        }

        assert_eq!(packer.pack(4), [fresh(&["a", "b"]), fresh(&["c", "d"])]);
        assert_eq!(
            packer.deadline_in(),
            Some(BUDGET),
            "e waits below the target"
        );

        packer.advance(BUDGET / 2);
        assert_eq!(packer.pack(2), NOTHING);

        packer.advance(BUDGET / 2);
        assert_eq!(packer.pack(2), [fresh(&["e"])]);
        assert_eq!(packer.deadline_in(), None);
    }

    #[test]
    fn without_a_free_slot_nothing_is_taken_or_reserved() {
        let mut packer = TestPacker::with_target(2);
        packer.arrive("a", 2);

        assert_eq!(packer.pack(0), NOTHING);
        assert_eq!(packer.deadline_in(), None);
        assert_eq!(packer.pack(1), [fresh(&["a"])]);
    }

    #[test]
    fn the_byte_target_sends_a_request_with_the_event_target_off() {
        let mut packer = TestPacker::new(PackTargets {
            events: None,
            bytes: NonZeroUsize::new(2 * one_event_bytes()),
            latency_budget: BUDGET,
        });
        packer.arrive("a", 1);
        assert_eq!(packer.pack(1), NOTHING);

        packer.arrive("b", 1);
        assert_eq!(packer.pack(1), [fresh(&["a", "b"])]);
    }

    #[test]
    fn classes_pack_into_separate_requests() {
        let mut packer = TestPacker::with_target(100);
        packer.arrive_in(1, "a", 1);
        packer.arrive_in(2, "b", 1);
        packer.arrive_in(1, "c", 1);

        assert_eq!(
            packer.pack_for_shutdown(4),
            [fresh_in(1, &["a", "c"]), fresh_in(2, &["b"])]
        );
    }

    #[test]
    fn a_replay_goes_out_at_once_and_keeps_the_fresh_deadline() {
        let mut packer = TestPacker::with_target(100);
        packer.arrive("a", 1);
        assert_eq!(packer.pack(1), NOTHING, "a waits below the target");

        packer.replay("r", 1);
        assert_eq!(packer.pack(1), [replay(&["r"])]);
        assert_eq!(packer.deadline_in(), Some(BUDGET), "a keeps its deadline");
    }

    #[test]
    fn a_replay_goes_before_fresh_work_at_the_target() {
        let mut packer = TestPacker::with_target(2);
        packer.arrive("a", 2);
        packer.replay("r", 1);

        assert_eq!(packer.pack(1), [replay(&["r"])]);
    }

    #[test]
    fn an_older_epoch_goes_first_unless_it_waits_below_the_target() {
        let mut packer = TestPacker::with_target(2);
        packer.arrive_in(2, "new", 2);
        packer.arrive_in(1, "old", 2);
        assert_eq!(packer.pack(1), [fresh_in(1, &["old"])]);

        packer.arrive_in(1, "late", 1);
        assert_eq!(
            packer.pack(1),
            [fresh_in(2, &["new"])],
            "late waits below the target, so new goes ahead"
        );

        packer.advance(BUDGET);
        assert_eq!(packer.pack(1), [fresh_in(1, &["late"])]);
    }

    #[test]
    fn a_deadline_with_nothing_left_to_send_is_released() {
        let mut packer = TestPacker::with_target(100);
        packer.arrive("a", 1);
        assert_eq!(packer.pack(1), NOTHING);
        assert_eq!(packer.deadline_in(), Some(BUDGET));

        packer.revoke_everything();
        packer.advance(BUDGET);
        assert_eq!(packer.pack(1), NOTHING);
        assert_eq!(packer.deadline_in(), None);
    }

    #[test]
    fn a_passed_deadline_waits_for_a_slot_and_then_sends_at_once() {
        let mut packer = TestPacker::with_target(100);
        packer.arrive("a", 1);
        assert_eq!(packer.pack(1), NOTHING);

        packer.advance(BUDGET * 2);
        assert_eq!(packer.pack(0), NOTHING);
        assert_eq!(packer.deadline_in(), Some(Duration::ZERO));
        assert_eq!(packer.pack(1), [fresh(&["a"])]);
    }
}
