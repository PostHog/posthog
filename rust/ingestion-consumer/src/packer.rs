//! The packer: holds the messages of keys with nothing in flight, per key,
//! until a batch near the target size is ready.
//!
//! There is one open batch. A key's messages append to its entry in
//! arrival order; entries are ordered by first arrival. The batch is
//! released when its totals reach the target in events or bytes, when its
//! deadline expires (the first message's arrival plus the latency budget),
//! or when the scheduler flushes it. A zero latency budget releases every
//! entry as its own batch at the end of the seam call that added to it,
//! so requests keep the shape they had before the packer.
//!
//! The packer knows nothing about workers: the scheduler marks the keys of
//! a released batch outstanding and places the batch when it leaves.

use std::collections::HashMap;
use std::time::{Duration, Instant};

use metrics::{counter, histogram};

use crate::scheduler::KeyRun;
use crate::types::SerializedKafkaMessage;

/// Target size T and the pack latency budget. A zero target disables that
/// dimension; a zero budget releases at the end of every seam call.
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

/// The `reason` label on `ingestion_consumer_pack_emits_total`.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ReleaseReason {
    /// The latency budget is zero: the entry left at the end of the seam
    /// call that added to it.
    Arrival,
    Full,
    Deadline,
    Flush,
}

impl ReleaseReason {
    fn as_str(self) -> &'static str {
        match self {
            ReleaseReason::Arrival => "arrival",
            ReleaseReason::Full => "full",
            ReleaseReason::Deadline => "deadline",
            ReleaseReason::Flush => "flush",
        }
    }
}

/// One released batch: one run per key, in first-arrival order, all from
/// one assignment epoch.
pub struct Batch {
    pub epoch: u64,
    pub runs: Vec<KeyRun>,
    pub bytes: usize,
}

impl Batch {
    pub fn message_count(&self) -> usize {
        self.runs.iter().map(|run| run.messages.len()).sum()
    }
}

struct Entry {
    routing_key: String,
    messages: Vec<SerializedKafkaMessage>,
    bytes: usize,
    /// When the entry's oldest message arrived: the start of its wait.
    first_arrival: Instant,
}

impl Entry {
    fn release(self, now: Instant) -> KeyRun {
        histogram!("ingestion_consumer_key_table_queue_wait_seconds", "kind" => "fresh").record(
            now.saturating_duration_since(self.first_arrival)
                .as_secs_f64(),
        );
        KeyRun {
            routing_key: self.routing_key,
            messages: self.messages,
        }
    }
}

struct OpenBatch {
    epoch: u64,
    deadline: Instant,
    entries: Vec<Entry>,
    index: HashMap<String, usize>,
    events: usize,
    bytes: usize,
}

pub struct Packer {
    targets: PackTargets,
    open: Option<OpenBatch>,
}

impl Packer {
    pub fn new(targets: PackTargets) -> Self {
        Self {
            targets,
            open: None,
        }
    }

    pub fn targets(&self) -> PackTargets {
        self.targets
    }

    pub fn set_targets(&mut self, targets: PackTargets) {
        self.targets = targets;
    }

    pub fn is_empty(&self) -> bool {
        self.open.is_none()
    }

    /// The epoch of the open batch's messages.
    pub fn epoch(&self) -> Option<u64> {
        self.open.as_ref().map(|batch| batch.epoch)
    }

    pub fn held_messages(&self) -> usize {
        self.open.as_ref().map_or(0, |batch| batch.events)
    }

    pub fn held_keys(&self) -> usize {
        self.open.as_ref().map_or(0, |batch| batch.entries.len())
    }

    #[cfg(test)]
    pub(crate) fn held_for(&self, key: &str) -> usize {
        self.open
            .as_ref()
            .and_then(|batch| {
                batch
                    .index
                    .get(key)
                    .map(|&i| batch.entries[i].messages.len())
            })
            .unwrap_or(0)
    }

    /// Append messages to the key's entry, opening the batch at `now` when
    /// there is none. `arrived_at` is when the oldest of them arrived, so
    /// a drain from a key's queue keeps its head-of-line wait. Returns the
    /// batch when the messages filled it to the target; a zero budget never
    /// releases here, only at [`Packer::release_entries`].
    pub fn push(
        &mut self,
        key: &str,
        epoch: u64,
        messages: Vec<SerializedKafkaMessage>,
        bytes: usize,
        arrived_at: Instant,
        now: Instant,
    ) -> Option<Batch> {
        let events = messages.len();
        let batch = self.open.get_or_insert_with(|| OpenBatch {
            epoch,
            deadline: now + self.targets.latency_budget,
            entries: Vec::new(),
            index: HashMap::new(),
            events: 0,
            bytes: 0,
        });
        debug_assert_eq!(batch.epoch, epoch, "the open batch spans one epoch");
        match batch.index.get(key) {
            Some(&index) => {
                let entry = &mut batch.entries[index];
                entry.messages.extend(messages);
                entry.bytes += bytes;
                entry.first_arrival = entry.first_arrival.min(arrived_at);
            }
            None => {
                batch.index.insert(key.to_string(), batch.entries.len());
                batch.entries.push(Entry {
                    routing_key: key.to_string(),
                    messages,
                    bytes,
                    first_arrival: arrived_at,
                });
            }
        }
        batch.events += events;
        batch.bytes += bytes;

        if !self.targets.latency_budget.is_zero() && self.targets.reached(batch.events, batch.bytes)
        {
            return self.take(ReleaseReason::Full, now);
        }
        None
    }

    /// At a zero budget, release every entry as its own batch; a nonzero
    /// budget releases nothing here.
    pub fn release_entries(&mut self, now: Instant) -> Vec<Batch> {
        if !self.targets.latency_budget.is_zero() {
            return Vec::new();
        }
        let Some(batch) = self.open.take() else {
            return Vec::new();
        };
        batch
            .entries
            .into_iter()
            .map(|entry| {
                counter!("ingestion_consumer_pack_emits_total", "reason" => ReleaseReason::Arrival.as_str())
                    .increment(1);
                let bytes = entry.bytes;
                Batch {
                    epoch: batch.epoch,
                    runs: vec![entry.release(now)],
                    bytes,
                }
            })
            .collect()
    }

    /// The open batch, when its deadline passed by `now`.
    pub fn take_expired(&mut self, now: Instant) -> Option<Batch> {
        if self
            .open
            .as_ref()
            .is_some_and(|batch| batch.deadline <= now)
        {
            self.take(ReleaseReason::Deadline, now)
        } else {
            None
        }
    }

    pub fn flush(&mut self, now: Instant) -> Option<Batch> {
        self.take(ReleaseReason::Flush, now)
    }

    fn take(&mut self, reason: ReleaseReason, now: Instant) -> Option<Batch> {
        let batch = self.open.take()?;
        counter!("ingestion_consumer_pack_emits_total", "reason" => reason.as_str()).increment(1);
        Some(Batch {
            epoch: batch.epoch,
            runs: batch
                .entries
                .into_iter()
                .map(|entry| entry.release(now))
                .collect(),
            bytes: batch.bytes,
        })
    }
}
