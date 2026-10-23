use std::collections::{HashMap, VecDeque};
use std::sync::{Arc, Mutex};
use std::time::Instant;

use common_kafka_consumer::{Charge, Held, Offset, Rejection, TopicPartition};

use super::{Accounting, Admission, HandedOut, Pause};

#[derive(Debug, Clone, PartialEq, Eq)]
pub(super) struct Settled {
    pub(super) topic_partition: TopicPartition,
    pub(super) generation: u64,
    pub(super) offsets: Vec<Offset>,
}

struct Script<T>(Arc<Mutex<VecDeque<T>>>);

impl<T> Default for Script<T> {
    fn default() -> Self {
        Self(Arc::new(Mutex::new(VecDeque::new())))
    }
}

impl<T> Clone for Script<T> {
    fn clone(&self) -> Self {
        Self(Arc::clone(&self.0))
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

#[derive(Default, Clone)]
pub(super) struct FakeAccounting {
    charges: Script<Result<Held, Rejection>>,
    settles: Script<Result<Option<Offset>, Rejection>>,
    takes: Script<HashMap<TopicPartition, HandedOut>>,
    settled: Arc<Mutex<Vec<Settled>>>,
    forgotten: Arc<Mutex<Vec<TopicPartition>>>,
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

    pub(super) fn settles_seen(&self) -> Vec<Settled> {
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

#[derive(Default, Clone)]
pub(super) struct FakeAdmission {
    pauses: Script<Option<Pause>>,
    resumes: Script<Vec<TopicPartition>>,
    charged: Arc<Mutex<Vec<(TopicPartition, Charge)>>>,
    handed_out: Arc<Mutex<Vec<HashMap<TopicPartition, HandedOut>>>>,
    forgotten: Arc<Mutex<Vec<TopicPartition>>>,
}

impl FakeAdmission {
    pub(super) fn charged_returns(&self, decision: Option<Pause>) {
        self.pauses.push(decision);
    }

    pub(super) fn handed_out_returns(&self, resume: Vec<TopicPartition>) {
        self.resumes.push(resume);
    }

    pub(super) fn charges_seen(&self) -> Vec<(TopicPartition, Charge)> {
        self.charged.lock().unwrap().clone()
    }

    pub(super) fn hand_outs_seen(&self) -> Vec<HashMap<TopicPartition, HandedOut>> {
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

    fn handed_out(&self, handed_out: &HashMap<TopicPartition, HandedOut>) -> Vec<TopicPartition> {
        self.handed_out.lock().unwrap().push(handed_out.clone());
        self.resumes.next().unwrap_or_default()
    }

    fn forget_partitions(&self, topic_partitions: &[TopicPartition]) {
        self.forgotten
            .lock()
            .unwrap()
            .extend_from_slice(topic_partitions);
    }
}
