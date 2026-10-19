use std::collections::{HashMap, VecDeque};
use std::sync::Mutex;
use std::time::Instant;

use common_kafka_consumer::{Charge, Held, Offset, Rejection, TopicPartition};

use super::{Accounting, Admission, HandedOut, Pause, Resume};

#[derive(Debug, Clone, PartialEq, Eq)]
pub(super) struct Settled {
    pub(super) topic_partition: TopicPartition,
    pub(super) generation: u64,
    pub(super) offsets: Vec<Offset>,
}

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
    takes: Script<HashMap<TopicPartition, HandedOut>>,
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

    pub(super) fn take_hands_out(&self, handed_out: HashMap<TopicPartition, HandedOut>) {
        self.takes.push(handed_out);
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

    fn take_due(&self, _now: Instant) -> Option<HashMap<TopicPartition, HandedOut>> {
        self.takes.next()
    }

    fn take_all(&self) -> Option<HashMap<TopicPartition, HandedOut>> {
        self.takes.next()
    }

    fn forget_partitions(&self, topic_partitions: &[TopicPartition]) {
        self.forgotten
            .lock()
            .unwrap()
            .extend_from_slice(topic_partitions);
    }
}

#[derive(Default)]
pub(super) struct FakeAdmission {
    pauses: Script<Option<Pause>>,
    resumes: Mutex<HashMap<TopicPartition, Resume>>,
    paused: Mutex<Vec<TopicPartition>>,
    charged: Mutex<Vec<(TopicPartition, Charge)>>,
    handed_out: Mutex<Vec<(TopicPartition, Charge)>>,
    forgotten: Mutex<Vec<TopicPartition>>,
}

impl FakeAdmission {
    pub(super) fn charged_returns(&self, decision: Option<Pause>) {
        self.pauses.push(decision);
    }

    pub(super) fn handed_out_returns(&self, topic_partition: &TopicPartition, decision: Resume) {
        self.resumes
            .lock()
            .unwrap()
            .insert(topic_partition.clone(), decision);
    }

    pub(super) fn pauses(&self, topic_partitions: &[TopicPartition]) {
        *self.paused.lock().unwrap() = topic_partitions.to_vec();
    }

    pub(super) fn charged(&self) -> Vec<(TopicPartition, Charge)> {
        self.charged.lock().unwrap().clone()
    }

    pub(super) fn handed_out(&self) -> Vec<(TopicPartition, Charge)> {
        self.handed_out.lock().unwrap().clone()
    }

    pub(super) fn forgotten(&self) -> Vec<TopicPartition> {
        self.forgotten.lock().unwrap().clone()
    }
}

impl Admission for FakeAdmission {
    fn charged(&self, topic_partition: &TopicPartition, uncommitted: Charge) -> Option<Pause> {
        self.charged
            .lock()
            .unwrap()
            .push((topic_partition.clone(), uncommitted));
        self.pauses.next().flatten()
    }

    fn handed_out(&self, topic_partition: &TopicPartition, uncommitted: Charge) -> Option<Resume> {
        self.handed_out
            .lock()
            .unwrap()
            .push((topic_partition.clone(), uncommitted));
        self.resumes.lock().unwrap().remove(topic_partition)
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
