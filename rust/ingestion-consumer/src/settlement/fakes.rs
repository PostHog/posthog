use std::collections::{HashMap, VecDeque};
use std::sync::Mutex;
use std::time::Instant;

use common_kafka_consumer::{Charge, Held, Offset, Rejection, TopicPartition};

use super::{Accounting, Admission, Commit, Pause};

#[derive(Debug, Clone, PartialEq, Eq)]
pub(super) struct Settled {
    pub(super) topic_partition: TopicPartition,
    pub(super) generation: u64,
    pub(super) offsets: Vec<Offset>,
}

/// Scripted results, returned in order; an empty script returns the default.
struct Script<T>(Mutex<VecDeque<T>>);

impl<T> Default for Script<T> {
    fn default() -> Self {
        Self(Mutex::new(VecDeque::new()))
    }
}

impl<T> Script<T> {
    fn push(&self, result: T) {
        self.0.lock().unwrap().push_back(result);
    }

    fn next(&self) -> Option<T> {
        self.0.lock().unwrap().pop_front()
    }
}

#[derive(Default)]
pub(super) struct FakeAccounting {
    charges: Script<Result<Held, Rejection>>,
    settles: Script<Result<Option<Offset>, Rejection>>,
    takes: Script<HashMap<TopicPartition, Offset>>,
    held: Mutex<HashMap<TopicPartition, Held>>,
    settled: Mutex<Vec<Settled>>,
    forgotten: Mutex<Vec<TopicPartition>>,
}

impl FakeAccounting {
    pub(super) fn charge_returns(&self, result: Result<Held, Rejection>) {
        self.charges.push(result);
    }

    pub(super) fn settle_returns(&self, result: Result<Option<Offset>, Rejection>) {
        self.settles.push(result);
    }

    pub(super) fn take_hands_out(&self, offsets: HashMap<TopicPartition, Offset>) {
        self.takes.push(offsets);
    }

    pub(super) fn holds(&self, topic_partition: &TopicPartition, held: Held) {
        self.held
            .lock()
            .unwrap()
            .insert(topic_partition.clone(), held);
    }

    pub(super) fn settled(&self) -> Vec<Settled> {
        self.settled.lock().unwrap().clone()
    }

    pub(super) fn forgotten(&self) -> Vec<TopicPartition> {
        self.forgotten.lock().unwrap().clone()
    }
}

impl Accounting for FakeAccounting {
    fn charge(
        &self,
        _topic_partition: &TopicPartition,
        _generation: u64,
        _charges: &[(Offset, Charge)],
    ) -> Result<Held, Rejection> {
        self.charges.next().unwrap_or(Ok(Held::default()))
    }

    fn settled(
        &self,
        topic_partition: &TopicPartition,
        generation: u64,
        offsets: impl IntoIterator<Item = Offset>,
    ) -> Result<Option<Offset>, Rejection> {
        self.settled.lock().unwrap().push(Settled {
            topic_partition: topic_partition.clone(),
            generation,
            offsets: offsets.into_iter().collect(),
        });
        self.settles.next().unwrap_or(Ok(None))
    }

    fn take_due(&self, _now: Instant) -> Option<HashMap<TopicPartition, Offset>> {
        self.takes.next()
    }

    fn take_all(&self) -> Option<HashMap<TopicPartition, Offset>> {
        self.takes.next()
    }

    fn forget_partitions(&self, topic_partitions: &[TopicPartition]) {
        self.forgotten
            .lock()
            .unwrap()
            .extend_from_slice(topic_partitions);
    }

    fn held(&self, topic_partition: &TopicPartition) -> Held {
        self.held
            .lock()
            .unwrap()
            .get(topic_partition)
            .copied()
            .unwrap_or_default()
    }
}

#[derive(Default)]
pub(super) struct FakeAdmission {
    charges: Script<Result<Option<Pause>, Rejection>>,
    settles: Script<Result<Option<Offset>, Rejection>>,
    takes: Script<Commit>,
    paused: Mutex<Vec<TopicPartition>>,
    settled: Mutex<Vec<Settled>>,
    forgotten: Mutex<Vec<TopicPartition>>,
}

impl FakeAdmission {
    pub(super) fn charge_returns(&self, result: Result<Option<Pause>, Rejection>) {
        self.charges.push(result);
    }

    pub(super) fn settle_returns(&self, result: Result<Option<Offset>, Rejection>) {
        self.settles.push(result);
    }

    pub(super) fn take_hands_out(&self, commit: Commit) {
        self.takes.push(commit);
    }

    pub(super) fn pauses(&self, topic_partitions: &[TopicPartition]) {
        *self.paused.lock().unwrap() = topic_partitions.to_vec();
    }

    pub(super) fn settled(&self) -> Vec<Settled> {
        self.settled.lock().unwrap().clone()
    }

    pub(super) fn forgotten(&self) -> Vec<TopicPartition> {
        self.forgotten.lock().unwrap().clone()
    }
}

impl Admission for FakeAdmission {
    fn charge(
        &self,
        _topic_partition: &TopicPartition,
        _generation: u64,
        _charges: &[(Offset, Charge)],
    ) -> Result<Option<Pause>, Rejection> {
        self.charges.next().unwrap_or(Ok(None))
    }

    fn settled(
        &self,
        topic_partition: &TopicPartition,
        generation: u64,
        offsets: impl IntoIterator<Item = Offset>,
    ) -> Result<Option<Offset>, Rejection> {
        self.settled.lock().unwrap().push(Settled {
            topic_partition: topic_partition.clone(),
            generation,
            offsets: offsets.into_iter().collect(),
        });
        self.settles.next().unwrap_or(Ok(None))
    }

    fn take_due(&self, _now: Instant) -> Option<Commit> {
        self.takes.next()
    }

    fn take_all(&self) -> Option<Commit> {
        self.takes.next()
    }

    fn forget_partitions(&self, topic_partitions: &[TopicPartition]) {
        self.forgotten
            .lock()
            .unwrap()
            .extend_from_slice(topic_partitions);
    }

    fn paused(&self) -> Vec<TopicPartition> {
        self.paused.lock().unwrap().clone()
    }
}
