//! Packs ready key runs into requests near a target size, one request per
//! free worker slot.

use std::num::NonZeroUsize;
use std::time::{Duration, Instant};

use metrics::counter;

use super::key_queues::KeyQueues;
use super::request::{Request, RequestClass};

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct PackTargets {
    pub events: Option<NonZeroUsize>,
    pub bytes: Option<NonZeroUsize>,
    pub latency_budget: Duration,
}

impl PackTargets {
    fn reached(&self, events: usize, bytes: usize) -> bool {
        self.events.is_some_and(|target| events >= target.get())
            || self.bytes.is_some_and(|target| bytes >= target.get())
    }
}

#[derive(Clone, Copy)]
enum SealReason {
    Full,
    Deadline,
    Flush,
}

impl SealReason {
    fn as_str(self) -> &'static str {
        match self {
            SealReason::Full => "full",
            SealReason::Deadline => "deadline",
            SealReason::Flush => "flush",
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
            let (class, reason) = if let Some(class) = self.full_class(keys) {
                (class, SealReason::Full)
            } else if draining || self.reservation.is_some_and(|deadline| deadline <= now) {
                let Some(class) = keys.oldest_ready_class() else {
                    break;
                };
                self.reservation = None;
                let reason = if draining {
                    SealReason::Flush
                } else {
                    SealReason::Deadline
                };
                (class, reason)
            } else {
                if self.reservation.is_none() && keys.has_ready() {
                    self.reservation = Some(now + self.targets.latency_budget);
                    if self.targets.latency_budget.is_zero() {
                        continue;
                    }
                }
                break;
            };
            let runs = keys.take_runs(class, self.targets.events, self.targets.bytes);
            counter!("ingestion_consumer_batcher_pack_seals_total", "reason" => reason.as_str())
                .increment(1);
            requests.push(Request::from_runs(class, runs));
        }
        if !keys.has_ready() {
            self.reservation = None;
        }
        requests
    }

    fn full_class(&self, keys: &KeyQueues) -> Option<RequestClass> {
        keys.ready_sizes()
            .iter()
            .find(|(_, size)| self.targets.reached(size.messages, size.bytes))
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
        let mut keys = KeyQueues::new();
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
        let mut keys = KeyQueues::new();
        push(&mut keys, "a", 0, &[1, 2], now);
        let mut packer = Packer::new(targets(2));

        assert!(packer.pack(&mut keys, now, 0, false).is_empty());
        assert_eq!(keys.claimed_keys(), 0);
        assert_eq!(packer.deadline(), None);
    }

    #[test]
    fn the_byte_target_sends_a_request_with_the_event_target_off() {
        let now = Instant::now();
        let mut keys = KeyQueues::new();
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
        let mut keys = KeyQueues::new();
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
    fn a_reservation_with_nothing_left_to_pack_is_released() {
        let now = Instant::now();
        let mut keys = KeyQueues::new();
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
        let mut keys = KeyQueues::new();
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
