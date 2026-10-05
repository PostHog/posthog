//! The packer groups claimed runs into requests near a target size. Sealed
//! requests wait until [`Packer::take_ready`] pulls them, so the caller pulls
//! only as many as it has capacity to send.
//!
//! The packer holds each key at most once, because the key queues claim a
//! key until its run settles.

use std::collections::{HashSet, VecDeque};
use std::time::{Duration, Instant};

use metrics::counter;

use super::key_queues::{payload_bytes, KeyRun, ReadyRun};
use super::request_class::RequestClass;

/// The target request size and the pack latency budget. A zero target
/// disables that dimension. A zero budget seals every open batch at the next
/// pull, so requests carry only what arrived in one action.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct PackTargets {
    pub events: usize,
    pub bytes: usize,
    pub latency_budget: Duration,
}

impl PackTargets {
    fn reached(&self, events: usize, bytes: usize) -> bool {
        (self.events > 0 && events >= self.events) || (self.bytes > 0 && bytes >= self.bytes)
    }
}

#[derive(Debug)]
pub struct PackedRequest {
    pub class: RequestClass,
    pub runs: Vec<KeyRun>,
    pub message_count: usize,
    pub bytes: usize,
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
    request: PackedRequest,
    deadline: Instant,
}

pub struct Packer {
    targets: PackTargets,
    open: Vec<OpenBatch>,
    sealed: VecDeque<PackedRequest>,
}

impl Packer {
    pub fn new(targets: PackTargets) -> Self {
        Self {
            targets,
            open: Vec::new(),
            sealed: VecDeque::new(),
        }
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

    fn requests(&self) -> impl Iterator<Item = &PackedRequest> {
        self.open
            .iter()
            .map(|batch| &batch.request)
            .chain(self.sealed.iter())
    }

    pub fn push(&mut self, ready: ReadyRun, now: Instant) {
        let ReadyRun {
            class, run, bytes, ..
        } = ready;
        let index = match self
            .open
            .iter()
            .position(|batch| batch.request.class == class)
        {
            Some(index) => index,
            None => {
                self.open.push(OpenBatch {
                    request: PackedRequest {
                        class,
                        runs: Vec::new(),
                        message_count: 0,
                        bytes: 0,
                    },
                    deadline: now + self.targets.latency_budget,
                });
                self.open.len() - 1
            }
        };
        let request = &mut self.open[index].request;
        request.message_count += run.messages.len();
        request.bytes += bytes;
        request.runs.push(run);
        if self.targets.reached(request.message_count, request.bytes) {
            self.seal(index, SealReason::Full);
        }
    }

    pub fn take_ready(&mut self, now: Instant, limit: usize) -> Vec<PackedRequest> {
        self.seal_expired(now);
        let count = limit.min(self.sealed.len());
        self.sealed.drain(..count).collect()
    }

    /// Sealing does not wait for send capacity, so an open batch is always
    /// within its latency budget.
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

    /// The caller must release the claims of the returned keys, whose runs
    /// emptied.
    pub fn purge(&mut self, revoked: &[(String, i32)]) -> (usize, Vec<String>) {
        let revoked: HashSet<(&str, i32)> = revoked
            .iter()
            .map(|(topic, partition)| (topic.as_str(), *partition))
            .collect();
        let mut purged = 0usize;
        let mut emptied_keys = Vec::new();
        let requests = self
            .open
            .iter_mut()
            .map(|batch| &mut batch.request)
            .chain(self.sealed.iter_mut());
        for request in requests {
            purged += purge_request(request, &revoked, &mut emptied_keys);
        }
        self.open.retain(|batch| !batch.request.runs.is_empty());
        self.sealed.retain(|request| !request.runs.is_empty());
        (purged, emptied_keys)
    }

    fn seal(&mut self, index: usize, reason: SealReason) {
        let request = self.open.remove(index).request;
        counter!("ingestion_consumer_machine_pack_seals_total", "reason" => reason.as_str())
            .increment(1);
        self.sealed.push_back(request);
    }
}

pub(crate) fn purge_request(
    request: &mut PackedRequest,
    revoked: &HashSet<(&str, i32)>,
    emptied_keys: &mut Vec<String>,
) -> usize {
    let mut purged = 0usize;
    request.runs.retain_mut(|run| {
        let before = run.messages.len();
        run.messages
            .retain(|message| !revoked.contains(&(message.topic.as_str(), message.partition)));
        purged += before - run.messages.len();
        if run.messages.is_empty() {
            emptied_keys.push(run.routing_key.clone());
            false
        } else {
            true
        }
    });
    request.message_count = request.message_count.saturating_sub(purged);
    request.bytes = request
        .runs
        .iter()
        .map(|run| payload_bytes(&run.messages))
        .sum();
    purged
}

#[cfg(test)]
mod tests {
    use super::*;
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
                routing_key: key.to_string(),
                messages,
            },
            first_arrival: Instant::now(),
        }
    }

    fn keys(request: &PackedRequest) -> Vec<&str> {
        request
            .runs
            .iter()
            .map(|run| run.routing_key.as_str())
            .collect()
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

        let (purged, emptied) = packer.purge(&[("events".to_string(), 0)]);
        assert_eq!(purged, 3);
        assert_eq!(emptied, vec!["a".to_string()]);
        packer.flush();
        let sent = packer.take_ready(now, 10);
        assert_eq!(keys(&sent[0]), vec!["b"]);
        assert_eq!(offsets(&sent[0].runs[0].messages), vec![11]);
        assert_eq!(sent[0].message_count, 1);
    }
}
