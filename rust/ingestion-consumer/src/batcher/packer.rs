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
        if let Some(class) = self.class_at_target(keys) {
            return Some((class, PackReason::AtTarget));
        }
        if let Some(class) = keys
            .ready_sizes()
            .iter()
            .map(|(class, _)| *class)
            .find(|class| class.replay)
        {
            return Some((class, PackReason::Replay));
        }
        let class = keys.oldest_ready_class()?;
        if draining {
            self.reservation = None;
            return Some((class, PackReason::Shutdown));
        }
        let deadline = *self
            .reservation
            .get_or_insert(now + self.targets.latency_budget);
        if deadline > now {
            return None;
        }
        self.reservation = None;
        Some((class, PackReason::Deadline))
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

    fn class_at_target(&self, keys: &KeyQueues) -> Option<RequestClass> {
        keys.ready_sizes()
            .iter()
            .find(|(_, size)| self.targets.reached(*size))
            .map(|(class, _)| *class)
    }
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;

    use super::*;
    use crate::batcher::key_queues::payload_bytes;
    use crate::batcher::test_support::message;

    const BUDGET: Duration = Duration::from_millis(50);

    fn targets(events: usize) -> PackTargets {
        PackTargets {
            events: NonZeroUsize::new(events),
            bytes: None,
            latency_budget: BUDGET,
        }
    }

    fn push(keys: &mut KeyQueues, key: &str, epoch: u64, offsets: &[i64], now: Instant) {
        let messages = offsets
            .iter()
            .map(|&offset| message(key, 0, offset))
            .collect();
        keys.push(Arc::from(key), epoch, messages, now);
    }

    fn shapes(requests: &[Request]) -> Vec<Vec<&str>> {
        requests
            .iter()
            .map(|request| request.runs.iter().map(|run| &*run.routing_key).collect())
            .collect()
    }

    #[test]
    fn a_backlog_fills_free_slots_with_full_requests_and_the_rest_waits() {
        let now = Instant::now();
        let mut keys = KeyQueues::default();
        for (index, key) in ["a", "b", "c", "d", "e"].into_iter().enumerate() {
            push(&mut keys, key, 0, &[index as i64], now);
        }
        let mut packer = Packer::new(targets(2));

        let sent = packer.pack(&mut keys, now, 4, false);
        assert_eq!(shapes(&sent), vec![vec!["a", "b"], vec!["c", "d"]]);
        assert_eq!(packer.deadline(), Some(now + BUDGET));

        assert!(packer
            .pack(&mut keys, now + BUDGET / 2, 2, false)
            .is_empty());
        let sent = packer.pack(&mut keys, now + BUDGET, 2, false);
        assert_eq!(shapes(&sent), vec![vec!["e"]]);
        assert_eq!(packer.deadline(), None);
    }

    #[test]
    fn without_a_free_slot_nothing_is_claimed_or_reserved() {
        let now = Instant::now();
        let mut keys = KeyQueues::default();
        push(&mut keys, "a", 0, &[1, 2], now);
        let mut packer = Packer::new(targets(2));

        assert!(packer.pack(&mut keys, now, 0, false).is_empty());
        assert_eq!(keys.claimed_keys(), 0);
        assert_eq!(packer.deadline(), None);
    }

    #[test]
    fn the_byte_target_sends_a_request_with_the_event_target_off() {
        let now = Instant::now();
        let mut keys = KeyQueues::default();
        push(&mut keys, "a", 0, &[1], now);
        let mut packer = Packer::new(PackTargets {
            events: None,
            bytes: NonZeroUsize::new(payload_bytes(&[message("a", 0, 1)]) * 2),
            latency_budget: BUDGET,
        });
        assert!(packer.pack(&mut keys, now, 1, false).is_empty());

        push(&mut keys, "b", 0, &[2], now);
        assert_eq!(
            shapes(&packer.pack(&mut keys, now, 1, false)),
            vec![vec!["a", "b"]]
        );
    }

    #[test]
    fn classes_pack_into_separate_requests() {
        let now = Instant::now();
        let mut keys = KeyQueues::default();
        push(&mut keys, "a", 1, &[1], now);
        push(&mut keys, "b", 2, &[2], now);
        push(&mut keys, "c", 1, &[3], now);
        let mut packer = Packer::new(targets(100));

        let sent = packer.pack(&mut keys, now, 4, true);
        let epochs: Vec<_> = sent
            .iter()
            .map(|request| request.class.assignment_epoch)
            .collect();
        assert_eq!(epochs, vec![1, 2]);
        assert_eq!(shapes(&sent), vec![vec!["a", "c"], vec!["b"]]);
    }

    #[test]
    fn a_replay_below_the_target_goes_out_at_once_and_keeps_the_fresh_deadline() {
        let now = Instant::now();
        let mut keys = KeyQueues::default();
        push(&mut keys, "r", 0, &[1], now);
        let fresh = RequestClass {
            assignment_epoch: 0,
            replay: false,
        };
        let claimed = keys.take_runs(fresh, |taken| taken.messages > 0);
        push(&mut keys, "a", 0, &[2], now);
        let mut packer = Packer::new(targets(100));
        assert!(packer.pack(&mut keys, now, 1, false).is_empty());

        let run = claimed.into_iter().next().expect("a claimed run").run;
        keys.settle(&run.routing_key, run.messages, None, now)
            .expect("a claimed key");
        let sent = packer.pack(&mut keys, now + BUDGET / 2, 1, false);
        assert_eq!(shapes(&sent), vec![vec!["r"]]);
        assert!(sent[0].class.replay);
        assert_eq!(packer.deadline(), Some(now + BUDGET));
    }

    #[test]
    fn a_reservation_with_nothing_left_to_pack_is_released() {
        let now = Instant::now();
        let mut keys = KeyQueues::default();
        push(&mut keys, "a", 0, &[1], now);
        let mut packer = Packer::new(targets(100));
        packer.pack(&mut keys, now, 1, false);
        assert_eq!(packer.deadline(), Some(now + BUDGET));

        keys.purge(&[("events".to_string(), 0)]);
        assert!(packer.pack(&mut keys, now + BUDGET, 1, false).is_empty());
        assert_eq!(packer.deadline(), None);
    }

    #[test]
    fn an_expired_reservation_waits_for_a_slot_and_then_sends_at_once() {
        let now = Instant::now();
        let mut keys = KeyQueues::default();
        push(&mut keys, "a", 0, &[1], now);
        let mut packer = Packer::new(targets(100));
        packer.pack(&mut keys, now, 1, false);

        let late = now + BUDGET * 2;
        assert!(packer.pack(&mut keys, late, 0, false).is_empty());
        assert_eq!(packer.deadline(), Some(now + BUDGET));
        assert_eq!(
            shapes(&packer.pack(&mut keys, late, 1, false)),
            vec![vec!["a"]]
        );
    }
}
