//! Packs claimed key runs into requests near a target size.

use std::collections::{HashSet, VecDeque};
use std::sync::Arc;
use std::time::{Duration, Instant};

use metrics::counter;

use super::key_queues::ReadyRun;
use super::request::{purge_request, Request};

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct PackTargets {
    /// `0` disables the event target.
    pub events: usize,
    /// `0` disables the byte target.
    pub bytes: usize,
    pub latency_budget: Duration,
}

impl PackTargets {
    fn reached(&self, events: usize, bytes: usize) -> bool {
        (self.events > 0 && events >= self.events) || (self.bytes > 0 && bytes >= self.bytes)
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

struct OpenBatch {
    request: Request,
    deadline: Instant,
}

pub struct Packer {
    targets: PackTargets,
    open: Vec<OpenBatch>,
    sealed: VecDeque<Request>,
}

impl Packer {
    pub fn new(targets: PackTargets) -> Self {
        Self {
            targets,
            open: Vec::new(),
            sealed: VecDeque::new(),
        }
    }

    pub fn latency_budget(&self) -> Duration {
        self.targets.latency_budget
    }

    pub fn held_messages(&self) -> usize {
        self.requests().map(|request| request.message_count).sum()
    }

    pub fn open_messages(&self) -> usize {
        self.open
            .iter()
            .map(|batch| batch.request.message_count)
            .sum()
    }

    pub fn held_keys(&self) -> usize {
        self.requests().map(|request| request.runs.len()).sum()
    }

    pub fn sealed_requests(&self) -> usize {
        self.sealed.len()
    }

    pub fn next_deadline(&self) -> Option<Instant> {
        self.open.iter().map(|batch| batch.deadline).min()
    }

    fn requests(&self) -> impl Iterator<Item = &Request> {
        self.open
            .iter()
            .map(|batch| &batch.request)
            .chain(self.sealed.iter())
    }

    /// Takes the run without checking its key: the key queues already allow
    /// one run per key.
    pub fn push(&mut self, ready: ReadyRun, now: Instant) {
        let ReadyRun {
            class,
            run,
            bytes,
            first_arrival,
        } = ready;
        let index = match self
            .open
            .iter()
            .position(|batch| batch.request.class == class)
        {
            Some(index) => index,
            None => {
                self.open.push(OpenBatch {
                    request: Request {
                        class,
                        runs: Vec::new(),
                        message_count: 0,
                        bytes: 0,
                        oldest_arrival: first_arrival,
                    },
                    deadline: now + self.targets.latency_budget,
                });
                self.open.len() - 1
            }
        };
        let request = &mut self.open[index].request;
        request.message_count += run.messages.len();
        request.bytes += bytes;
        request.oldest_arrival = request.oldest_arrival.min(first_arrival);
        request.runs.push(run);
        if self.targets.reached(request.message_count, request.bytes) {
            self.seal(index, SealReason::Full);
        }
    }

    /// Sealed requests wait here, so the caller pulls only as many as it can
    /// send.
    pub fn take_ready(&mut self, now: Instant, limit: usize) -> Vec<Request> {
        self.seal_expired(now);
        let count = limit.min(self.sealed.len());
        self.sealed.drain(..count).collect()
    }

    /// Seals without waiting for a send slot, so an open batch never outlives
    /// its latency budget.
    pub fn seal_expired(&mut self, now: Instant) {
        while let Some(index) = self
            .open
            .iter()
            .enumerate()
            .filter(|(_, batch)| batch.deadline <= now)
            .min_by_key(|(_, batch)| batch.deadline)
            .map(|(index, _)| index)
        {
            self.seal(index, SealReason::Deadline);
        }
    }

    pub fn flush(&mut self) {
        while !self.open.is_empty() {
            self.seal(0, SealReason::Flush);
        }
    }

    /// The caller must release the claim of every returned key.
    pub fn purge(&mut self, revoked: &[(String, i32)]) -> Vec<Arc<str>> {
        let revoked: HashSet<(&str, i32)> = revoked
            .iter()
            .map(|(topic, partition)| (topic.as_str(), *partition))
            .collect();
        let mut emptied_keys = Vec::new();
        let requests = self
            .open
            .iter_mut()
            .map(|batch| &mut batch.request)
            .chain(self.sealed.iter_mut());
        for request in requests {
            purge_request(request, &revoked, &mut emptied_keys);
        }
        self.open.retain(|batch| !batch.request.runs.is_empty());
        self.sealed.retain(|request| !request.runs.is_empty());
        emptied_keys
    }

    fn seal(&mut self, index: usize, reason: SealReason) {
        let request = self.open.remove(index).request;
        counter!("ingestion_consumer_batcher_pack_seals_total", "reason" => reason.as_str())
            .increment(1);
        self.sealed.push_back(request);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::batcher::key_queues::{payload_bytes, KeyRun};
    use crate::batcher::request::RequestClass;
    use crate::batcher::test_support::{message, offsets};

    const FRESH: RequestClass = RequestClass {
        assignment_epoch: 0,
        replay: false,
    };
    const REPLAY: RequestClass = RequestClass {
        assignment_epoch: 0,
        replay: true,
    };

    fn ready(key: &str, class: RequestClass, first_offset: i64, count: i64) -> ReadyRun {
        let messages: Vec<_> = (first_offset..first_offset + count)
            .map(|offset| message(key, 0, offset))
            .collect();
        ReadyRun {
            class,
            bytes: payload_bytes(&messages),
            run: KeyRun {
                routing_key: key.into(),
                messages,
            },
            first_arrival: Instant::now(),
        }
    }

    fn keys(request: &Request) -> Vec<&str> {
        request.runs.iter().map(|run| &*run.routing_key).collect()
    }

    fn targets(events: usize, budget_ms: u64) -> PackTargets {
        PackTargets {
            events,
            bytes: 0,
            latency_budget: Duration::from_millis(budget_ms),
        }
    }

    #[test]
    fn a_batch_seals_at_the_target_and_the_next_one_opens() {
        let now = Instant::now();
        let mut packer = Packer::new(targets(3, 1_000));
        packer.push(ready("a", FRESH, 0, 2), now);
        assert!(packer.take_ready(now, 10).is_empty(), "below target");

        packer.push(ready("b", FRESH, 10, 1), now);
        packer.push(ready("c", FRESH, 20, 1), now);
        let sent = packer.take_ready(now, 10);
        assert_eq!(sent.len(), 1);
        assert_eq!(keys(&sent[0]), vec!["a", "b"]);
        assert_eq!(packer.held_keys(), 1, "c opened the next batch");
    }

    #[test]
    fn a_batch_seals_at_the_byte_target_with_the_event_target_off() {
        let now = Instant::now();
        let first = ready("a", FRESH, 0, 1);
        let mut packer = Packer::new(PackTargets {
            events: 0,
            bytes: first.bytes * 2,
            latency_budget: Duration::from_secs(1),
        });
        packer.push(first, now);
        assert!(
            packer.take_ready(now, 10).is_empty(),
            "below the byte target"
        );

        packer.push(ready("b", FRESH, 10, 1), now);
        assert_eq!(keys(&packer.take_ready(now, 10)[0]), vec!["a", "b"]);
    }

    #[test]
    fn a_batch_below_target_seals_at_its_deadline() {
        let now = Instant::now();
        let budget = Duration::from_millis(50);
        let mut packer = Packer::new(targets(100, 50));
        packer.push(ready("a", FRESH, 0, 1), now);
        assert_eq!(packer.next_deadline(), Some(now + budget));
        assert!(packer.take_ready(now + budget / 2, 10).is_empty());

        let sent = packer.take_ready(now + budget, 10);
        assert_eq!(sent.len(), 1);
        assert_eq!(packer.next_deadline(), None);
    }

    #[test]
    fn classes_pack_into_separate_requests() {
        let now = Instant::now();
        let mut packer = Packer::new(targets(100, 0));
        packer.push(ready("a", FRESH, 0, 1), now);
        packer.push(ready("b", REPLAY, 10, 1), now);
        packer.push(ready("c", FRESH, 20, 1), now);

        let sent = packer.take_ready(now, 10);
        let shapes: Vec<_> = sent
            .iter()
            .map(|request| (request.class.replay, keys(request)))
            .collect();
        assert_eq!(shapes, vec![(false, vec!["a", "c"]), (true, vec!["b"])]);
    }

    #[test]
    fn take_ready_returns_at_most_the_limit_and_keeps_the_rest_in_order() {
        let now = Instant::now();
        let mut packer = Packer::new(targets(1, 1_000));
        for (index, key) in ["a", "b", "c"].into_iter().enumerate() {
            packer.push(ready(key, FRESH, index as i64 * 10, 1), now);
        }
        let first = packer.take_ready(now, 2);
        assert_eq!(
            first.iter().flat_map(keys).collect::<Vec<_>>(),
            vec!["a", "b"]
        );
        let rest = packer.take_ready(now, 2);
        assert_eq!(rest.iter().flat_map(keys).collect::<Vec<_>>(), vec!["c"]);
    }

    #[test]
    fn a_purge_drops_revoked_messages_and_reports_emptied_keys() {
        let now = Instant::now();
        let mut packer = Packer::new(targets(100, 1_000));
        packer.push(ready("a", FRESH, 0, 2), now);
        let mut mixed = ready("b", FRESH, 10, 1);
        mixed.run.messages.push(message("b", 3, 11));
        packer.push(mixed, now);

        let emptied = packer.purge(&[("events".to_string(), 0)]);
        assert_eq!(emptied, vec![Arc::<str>::from("a")]);
        assert_eq!(packer.held_messages(), 1);
        packer.flush();
        let sent = packer.take_ready(now, 10);
        assert_eq!(keys(&sent[0]), vec!["b"]);
        assert_eq!(offsets(&sent[0].runs[0].messages), vec![11]);
        assert_eq!(sent[0].message_count, 1);
    }
}
