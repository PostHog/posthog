//! Partition provenance: whether a partition's local state holds its full history.
//!
//! A partition can lose its history without any error: its volume is lost, its ownership moves to
//! another pod, or a pod reopens state that another pod advanced since. The state then looks valid,
//! and a reconcile on it would certify membership that misses people. The sweeper deletes every row
//! a certified run did not re-assert, so one false certificate deletes true members.
//!
//! Each partition stores its provenance under its own key prefix: a lineage, and the committed
//! offset of each input. [`stage_input_offsets`] writes the offsets before the Kafka commit they
//! describe, so a warm partition is never behind its consumer groups. A partition wipe deletes the
//! provenance together with the state.
//!
//! At the start of each tenure, [`ProvenanceClassifier`] compares the stored provenance with the
//! groups' committed offsets and classifies the partition:
//! - warm: the state holds every committed input;
//! - cold: no lineage while the groups have commits;
//! - stale: a stored offset is behind its group's commit.
//!
//! A cold or stale verdict is persisted in the lineage, so a restart does not forget it. The
//! reconcile drain withholds the completion marker of a fenced partition. Until the first verdict
//! of a tenure, the commit paths commit nothing for the partition: an own commit would move the
//! group past the stored offsets and make a warm partition read stale.

use std::collections::{HashMap, HashSet};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::Duration;

use anyhow::{Context, Result};
use dashmap::DashMap;
use metrics::{counter, gauge};
use rdkafka::consumer::{Consumer, ConsumerContext, StreamConsumer};
use rdkafka::{Offset, TopicPartitionList};
use tokio_util::sync::CancellationToken;
use tracing::{info, warn};
use uuid::Uuid;

use cohort_core::seed::WithheldReason;

use crate::consumers::events::EventDispatcher;
use crate::observability::metrics::{
    PARTITION_PROVENANCE_CLASSIFIED_TOTAL, PARTITION_PROVENANCE_ERRORS_TOTAL,
    PARTITION_PROVENANCE_FENCED, PARTITION_PROVENANCE_PENDING,
};
use crate::store::durability::OffsetManifest;
use crate::store::{PartitionProvenanceKey, StagedBatch, StoreHandle};

const LINEAGE_SLOT: u8 = 0;
const LINEAGE_VERSION: u8 = 1;
const LINEAGE_LEN: usize = 1 + 16 + 1;
const FENCE_NONE: u8 = 0;
const FENCE_COLD: u8 = 1;
const FENCE_STALE: u8 = 2;

/// Timeout of one committed-offset fetch. A timeout fails the tick, and the next tick retries.
const COMMITTED_FETCH_TIMEOUT: Duration = Duration::from_secs(10);

/// One of the five Kafka inputs whose committed offset a partition's provenance records.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum ProvenanceInput {
    Events,
    Merges,
    Transfers,
    Cascades,
    Seeds,
}

impl ProvenanceInput {
    const ALL: [Self; 5] = [
        Self::Events,
        Self::Merges,
        Self::Transfers,
        Self::Cascades,
        Self::Seeds,
    ];

    const fn slot(self) -> u8 {
        match self {
            Self::Events => 1,
            Self::Merges => 2,
            Self::Transfers => 3,
            Self::Cascades => 4,
            Self::Seeds => 5,
        }
    }

    fn from_slot(slot: u8) -> Option<Self> {
        Self::ALL.into_iter().find(|input| input.slot() == slot)
    }
}

/// The identity of one continuous history of a partition's state, and its fence once it is known
/// to miss history.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Lineage {
    pub id: Uuid,
    pub fence: Option<WithheldReason>,
}

impl Lineage {
    fn new(fence: Option<WithheldReason>) -> Self {
        Self {
            id: Uuid::new_v4(),
            fence,
        }
    }

    fn encode(self) -> [u8; LINEAGE_LEN] {
        let mut out = [0u8; LINEAGE_LEN];
        out[0] = LINEAGE_VERSION;
        out[1..17].copy_from_slice(self.id.as_bytes());
        out[17] = match self.fence {
            None => FENCE_NONE,
            Some(WithheldReason::Cold) => FENCE_COLD,
            Some(WithheldReason::Stale) => FENCE_STALE,
        };
        out
    }

    fn decode(bytes: &[u8]) -> Option<Self> {
        if bytes.len() != LINEAGE_LEN || bytes[0] != LINEAGE_VERSION {
            return None;
        }
        let fence = match bytes[17] {
            FENCE_NONE => None,
            FENCE_COLD => Some(WithheldReason::Cold),
            FENCE_STALE => Some(WithheldReason::Stale),
            _ => return None,
        };
        let mut id = [0u8; 16];
        id.copy_from_slice(&bytes[1..17]);
        Some(Self {
            id: Uuid::from_bytes(id),
            fence,
        })
    }
}

/// A partition's provenance as the store holds it. An unreadable lineage reads as absent, so the
/// partition classifies as cold when its groups have commits.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct StoredProvenance {
    pub lineage: Option<Lineage>,
    pub inputs: HashMap<ProvenanceInput, i64>,
}

impl StoredProvenance {
    fn decode(slots: Vec<(u8, Vec<u8>)>) -> Self {
        let mut stored = Self::default();
        for (slot, value) in slots {
            if slot == LINEAGE_SLOT {
                stored.lineage = Lineage::decode(&value);
                continue;
            }
            let (Some(input), Ok(bytes)) = (
                ProvenanceInput::from_slot(slot),
                <[u8; 8]>::try_from(value.as_slice()),
            ) else {
                continue;
            };
            stored.inputs.insert(input, i64::from_be_bytes(bytes));
        }
        stored
    }
}

/// Whether a reconcile on the partition may certify its membership.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PartitionClass {
    Warm,
    Fenced(WithheldReason),
}

/// A verdict and the provenance writes that make it durable.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Classification {
    pub class: PartitionClass,
    /// The metric label: `warm`, `adopted`, `cold` or `stale`.
    pub label: &'static str,
    pub lineage_write: Option<Lineage>,
    pub input_writes: HashMap<ProvenanceInput, i64>,
}

/// Classify one partition at the start of a tenure.
///
/// `expected` holds the committed offset of each input whose group has a commit for the partition.
/// `moved_in` marks a partition that moved to this pod after boot: the worker spawn wipes its slice,
/// so it never holds history. `adopt_legacy` marks a partition of a store that predates provenance;
/// such a partition takes its current commits as its provenance once.
pub fn classify(
    stored: &StoredProvenance,
    expected: &HashMap<ProvenanceInput, i64>,
    moved_in: bool,
    adopt_legacy: bool,
) -> Classification {
    let fence = |reason: WithheldReason| Classification {
        class: PartitionClass::Fenced(reason),
        label: reason.as_str(),
        lineage_write: Some(Lineage {
            id: stored
                .lineage
                .map_or_else(Uuid::new_v4, |lineage| lineage.id),
            fence: Some(reason),
        }),
        input_writes: HashMap::new(),
    };

    if moved_in && !expected.is_empty() {
        return fence(WithheldReason::Cold);
    }
    match stored.lineage {
        Some(Lineage {
            fence: Some(reason),
            ..
        }) => Classification {
            class: PartitionClass::Fenced(reason),
            label: reason.as_str(),
            lineage_write: None,
            input_writes: HashMap::new(),
        },
        Some(_) => {
            let behind = expected.iter().any(|(input, committed)| {
                stored
                    .inputs
                    .get(input)
                    .is_none_or(|recorded| recorded < committed)
            });
            if behind {
                fence(WithheldReason::Stale)
            } else {
                Classification {
                    class: PartitionClass::Warm,
                    label: "warm",
                    lineage_write: None,
                    input_writes: HashMap::new(),
                }
            }
        }
        None if adopt_legacy => Classification {
            class: PartitionClass::Warm,
            label: "adopted",
            lineage_write: Some(Lineage::new(None)),
            input_writes: expected.clone(),
        },
        None if !expected.is_empty() => fence(WithheldReason::Cold),
        None => Classification {
            class: PartitionClass::Warm,
            label: "warm",
            lineage_write: Some(Lineage::new(None)),
            input_writes: HashMap::new(),
        },
    }
}

/// Stage the committed offsets of one input for the partitions in `offsets`. The commit paths stage
/// these and make them durable before the Kafka commit that the offsets describe.
pub fn stage_input_offsets(
    staged: &mut StagedBatch,
    input: ProvenanceInput,
    offsets: &HashMap<i32, i64>,
) {
    for (&partition, &next_offset) in offsets {
        if let Ok(partition_id) = u16::try_from(partition) {
            staged.put_partition_provenance(
                PartitionProvenanceKey::new(partition_id, input.slot()),
                &next_offset.to_be_bytes(),
            );
        }
    }
}

fn stage_classification(staged: &mut StagedBatch, partition_id: u16, verdict: &Classification) {
    if let Some(lineage) = verdict.lineage_write {
        staged.put_partition_provenance(
            PartitionProvenanceKey::new(partition_id, LINEAGE_SLOT),
            &lineage.encode(),
        );
    }
    for (input, next_offset) in &verdict.input_writes {
        staged.put_partition_provenance(
            PartitionProvenanceKey::new(partition_id, input.slot()),
            &next_offset.to_be_bytes(),
        );
    }
}

#[derive(Debug, Clone, Copy)]
struct Tenure {
    generation: u64,
    class: Option<PartitionClass>,
}

/// The in-memory verdict of each owned partition for its current tenure. A disabled registry
/// reads every partition as warm and gates no commit, which keeps the pre-provenance behavior.
#[derive(Debug, Default)]
pub struct ProvenanceRegistry {
    enabled: bool,
    tenures: DashMap<i32, Tenure>,
    next_generation: AtomicU64,
}

impl ProvenanceRegistry {
    pub fn enabled() -> Self {
        Self {
            enabled: true,
            ..Self::default()
        }
    }

    pub fn is_enabled(&self) -> bool {
        self.enabled
    }

    /// Start a tenure that waits for its verdict.
    pub fn begin_tenure(&self, partition: i32) {
        if !self.enabled {
            return;
        }
        let generation = self.next_generation.fetch_add(1, Ordering::Relaxed);
        self.tenures.insert(
            partition,
            Tenure {
                generation,
                class: None,
            },
        );
        self.publish_gauges();
    }

    pub fn end_tenure(&self, partition: i32) {
        if !self.enabled {
            return;
        }
        self.tenures.remove(&partition);
        self.publish_gauges();
    }

    /// The partition's verdict for this tenure. `None` while it waits for one.
    pub fn class(&self, partition: i32) -> Option<PartitionClass> {
        if !self.enabled {
            return Some(PartitionClass::Warm);
        }
        self.tenures.get(&partition).and_then(|tenure| tenure.class)
    }

    /// Keep only the offsets of partitions with a verdict for this tenure.
    pub fn committable(&self, mut offsets: HashMap<i32, i64>) -> HashMap<i32, i64> {
        if self.enabled {
            offsets.retain(|partition, _| self.class(*partition).is_some());
        }
        offsets
    }

    pub(crate) fn pending(&self) -> Vec<(i32, u64)> {
        self.tenures
            .iter()
            .filter(|entry| entry.class.is_none())
            .map(|entry| (*entry.key(), entry.generation))
            .collect()
    }

    /// Record a verdict, unless a newer tenure replaced the one it was computed for.
    pub(crate) fn settle(&self, partition: i32, generation: u64, class: PartitionClass) -> bool {
        let settled = match self.tenures.get_mut(&partition) {
            Some(mut tenure) if tenure.generation == generation => {
                tenure.class = Some(class);
                true
            }
            _ => false,
        };
        self.publish_gauges();
        settled
    }

    fn publish_gauges(&self) {
        let (mut pending, mut cold, mut stale) = (0u64, 0u64, 0u64);
        for tenure in self.tenures.iter() {
            match tenure.class {
                None => pending += 1,
                Some(PartitionClass::Fenced(WithheldReason::Cold)) => cold += 1,
                Some(PartitionClass::Fenced(WithheldReason::Stale)) => stale += 1,
                Some(PartitionClass::Warm) => {}
            }
        }
        gauge!(PARTITION_PROVENANCE_PENDING).set(pending as f64);
        gauge!(PARTITION_PROVENANCE_FENCED, "reason" => WithheldReason::Cold.as_str())
            .set(cold as f64);
        gauge!(PARTITION_PROVENANCE_FENCED, "reason" => WithheldReason::Stale.as_str())
            .set(stale as f64);
    }
}

/// Reads a consumer group's committed offsets for one topic. Blocking.
pub trait CommittedOffsets: Send + Sync {
    fn committed(&self, partitions: &[i32]) -> Result<HashMap<i32, i64>>;
}

/// [`CommittedOffsets`] through the input's own consumer, which carries its group id.
pub struct ConsumerCommits<C: ConsumerContext + 'static> {
    consumer: Arc<StreamConsumer<C>>,
    topic: String,
}

impl<C: ConsumerContext + 'static> ConsumerCommits<C> {
    pub fn new(consumer: Arc<StreamConsumer<C>>, topic: String) -> Self {
        Self { consumer, topic }
    }
}

impl<C: ConsumerContext + 'static> CommittedOffsets for ConsumerCommits<C> {
    fn committed(&self, partitions: &[i32]) -> Result<HashMap<i32, i64>> {
        let mut tpl = TopicPartitionList::new();
        for &partition in partitions {
            tpl.add_partition(&self.topic, partition);
        }
        let committed = self
            .consumer
            .committed_offsets(tpl, COMMITTED_FETCH_TIMEOUT)
            .with_context(|| format!("fetching committed offsets of {}", self.topic))?;
        Ok(committed
            .elements_for_topic(&self.topic)
            .iter()
            .filter_map(|elem| match elem.offset() {
                Offset::Offset(next) => Some((elem.partition(), next)),
                _ => None,
            })
            .collect())
    }
}

/// One input the classifier compares: its topic and where its group's commits come from.
pub struct ClassifierInput {
    pub input: ProvenanceInput,
    pub topic: String,
    pub commits: Arc<dyn CommittedOffsets>,
}

/// Classifies every waiting tenure. Runs only with durable restore, which records the boot
/// assignment that tells a boot partition from a post-boot move-in.
pub struct ProvenanceClassifier {
    registry: Arc<ProvenanceRegistry>,
    dispatcher: Arc<EventDispatcher>,
    inputs: Vec<ClassifierInput>,
    /// The restored checkpoint's offsets. The boot restore rewinds the inputs to them, so they
    /// replace the groups' commits for boot partitions until every boot partition has a verdict.
    restore_manifest: Option<OffsetManifest>,
    boot_remaining: Option<HashSet<i32>>,
    adopt_legacy: Option<bool>,
}

impl ProvenanceClassifier {
    pub fn new(
        registry: Arc<ProvenanceRegistry>,
        dispatcher: Arc<EventDispatcher>,
        inputs: Vec<ClassifierInput>,
        restore_manifest: Option<OffsetManifest>,
    ) -> Self {
        Self {
            registry,
            dispatcher,
            inputs,
            restore_manifest,
            boot_remaining: None,
            adopt_legacy: None,
        }
    }

    pub async fn run(mut self, interval: Duration, shutdown: CancellationToken) {
        let mut ticker = tokio::time::interval(interval);
        ticker.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
        loop {
            tokio::select! {
                biased;
                _ = shutdown.cancelled() => break,
                _ = ticker.tick() => self.tick().await,
            }
        }
    }

    async fn tick(&mut self) {
        let dispatcher = Arc::clone(&self.dispatcher);
        let Some(boot) = dispatcher.boot_assignment() else {
            return;
        };
        let handle = dispatcher.handle().clone();
        let mut boot_remaining = self.boot_remaining.take().unwrap_or_else(|| boot.clone());
        self.classify_pending(&dispatcher, boot, &handle, &mut boot_remaining)
            .await;
        boot_remaining.retain(|partition| dispatcher.owns(*partition));
        let boot_done = boot_remaining.is_empty();
        self.boot_remaining = Some(boot_remaining);
        if !boot_done {
            return;
        }
        self.restore_manifest = None;
        if self.adopt_legacy == Some(true) {
            match handle.mark_provenance_tracked().await {
                Ok(()) => {
                    self.adopt_legacy = Some(false);
                    info!("provenance: every boot partition adopted its commits; the store now tracks provenance");
                }
                Err(error) => {
                    counter!(PARTITION_PROVENANCE_ERRORS_TOTAL, "stage" => "meta").increment(1);
                    warn!(error = %error, "provenance: store meta write failed; retrying next tick");
                }
            }
        }
    }

    async fn classify_pending(
        &mut self,
        dispatcher: &EventDispatcher,
        boot: &HashSet<i32>,
        handle: &StoreHandle,
        boot_remaining: &mut HashSet<i32>,
    ) {
        let adopt_legacy = match self.adopt_legacy {
            Some(adopt) => adopt,
            None => match handle.tracks_provenance().await {
                Ok(tracked) => *self.adopt_legacy.insert(!tracked),
                Err(error) => {
                    counter!(PARTITION_PROVENANCE_ERRORS_TOTAL, "stage" => "meta").increment(1);
                    warn!(error = %error, "provenance: store meta read failed; retrying next tick");
                    return;
                }
            },
        };

        let pending: Vec<(i32, u64)> = self
            .registry
            .pending()
            .into_iter()
            .filter(|(partition, _)| {
                dispatcher.owns(*partition) && !dispatcher.is_draining(*partition)
            })
            .collect();
        if pending.is_empty() {
            return;
        }
        let partitions: Vec<i32> = pending.iter().map(|(partition, _)| *partition).collect();
        let Some(expected) = self.expected_offsets(&partitions, boot).await else {
            return;
        };
        {
            for (partition, generation) in pending {
                let Ok(partition_id) = u16::try_from(partition) else {
                    continue;
                };
                let stored = match handle.read_partition_provenance(partition_id).await {
                    Ok(slots) => StoredProvenance::decode(slots),
                    Err(error) => {
                        counter!(PARTITION_PROVENANCE_ERRORS_TOTAL, "stage" => "read").increment(1);
                        warn!(partition, error = %error, "provenance: read failed; retrying next tick");
                        continue;
                    }
                };
                let empty = HashMap::new();
                let expected = expected.get(&partition).unwrap_or(&empty);
                let is_boot = boot.contains(&partition);
                let verdict = classify(&stored, expected, !is_boot, adopt_legacy && is_boot);
                let mut staged = StagedBatch::default();
                stage_classification(&mut staged, partition_id, &verdict);
                if !staged.is_empty() {
                    if let Err(error) = handle.commit(staged).await {
                        counter!(PARTITION_PROVENANCE_ERRORS_TOTAL, "stage" => "write")
                            .increment(1);
                        warn!(partition, error = %error, "provenance: verdict write failed; retrying next tick");
                        continue;
                    }
                }
                if !self.registry.settle(partition, generation, verdict.class) {
                    continue;
                }
                boot_remaining.remove(&partition);
                counter!(PARTITION_PROVENANCE_CLASSIFIED_TOTAL, "class" => verdict.label)
                    .increment(1);
                let lineage = verdict.lineage_write.or(stored.lineage);
                match verdict.class {
                    PartitionClass::Warm => info!(
                        partition,
                        class = verdict.label,
                        lineage = ?lineage.map(|lineage| lineage.id),
                        "provenance: partition holds its full history",
                    ),
                    PartitionClass::Fenced(reason) => warn!(
                        partition,
                        reason = reason.as_str(),
                        lineage = ?lineage.map(|lineage| lineage.id),
                        stored = ?stored.inputs,
                        committed = ?expected,
                        "provenance: partition is missing history; its reconciles withhold their completion markers",
                    ),
                }
            }
        }
    }

    /// Each partition's committed offset per input, or `None` when a fetch failed. A boot partition
    /// takes the restored checkpoint's offset where the checkpoint has one.
    async fn expected_offsets(
        &self,
        partitions: &[i32],
        boot: &HashSet<i32>,
    ) -> Option<HashMap<i32, HashMap<ProvenanceInput, i64>>> {
        let mut expected: HashMap<i32, HashMap<ProvenanceInput, i64>> = HashMap::new();
        for source in &self.inputs {
            let commits = Arc::clone(&source.commits);
            let requested = partitions.to_vec();
            let fetched = tokio::task::spawn_blocking(move || commits.committed(&requested)).await;
            let committed = match fetched {
                Ok(Ok(committed)) => committed,
                Ok(Err(error)) => {
                    counter!(PARTITION_PROVENANCE_ERRORS_TOTAL, "stage" => "committed")
                        .increment(1);
                    warn!(topic = %source.topic, error = %error, "provenance: committed-offset fetch failed; retrying next tick");
                    return None;
                }
                Err(error) => {
                    counter!(PARTITION_PROVENANCE_ERRORS_TOTAL, "stage" => "committed")
                        .increment(1);
                    warn!(topic = %source.topic, error = %error, "provenance: committed-offset fetch panicked; retrying next tick");
                    return None;
                }
            };
            for &partition in partitions {
                let restored = self
                    .restore_manifest
                    .as_ref()
                    .filter(|_| boot.contains(&partition))
                    .and_then(|manifest| manifest.offset_for(&source.topic, partition));
                if let Some(next) = restored.or_else(|| committed.get(&partition).copied()) {
                    expected
                        .entry(partition)
                        .or_default()
                        .insert(source.input, next);
                }
            }
        }
        Some(expected)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn offsets(pairs: &[(ProvenanceInput, i64)]) -> HashMap<ProvenanceInput, i64> {
        pairs.iter().copied().collect()
    }

    fn stored(
        fence: Option<WithheldReason>,
        inputs: &[(ProvenanceInput, i64)],
    ) -> StoredProvenance {
        StoredProvenance {
            lineage: Some(Lineage {
                id: Uuid::from_u128(7),
                fence,
            }),
            inputs: offsets(inputs),
        }
    }

    #[test]
    fn classify_covers_every_tenure_start() {
        use ProvenanceInput::{Events, Seeds};
        use WithheldReason::{Cold, Stale};
        let committed = offsets(&[(Events, 100), (Seeds, 10)]);
        let none = HashMap::new();
        let cases: Vec<(
            &str,
            StoredProvenance,
            &HashMap<_, _>,
            bool,
            bool,
            PartitionClass,
        )> = vec![
            (
                "caught-up lineage",
                stored(None, &[(Events, 100), (Seeds, 10)]),
                &committed,
                false,
                false,
                PartitionClass::Warm,
            ),
            (
                "provenance written ahead of a failed commit",
                stored(None, &[(Events, 120), (Seeds, 10)]),
                &committed,
                false,
                false,
                PartitionClass::Warm,
            ),
            (
                "another owner advanced one input",
                stored(None, &[(Events, 100), (Seeds, 9)]),
                &committed,
                false,
                false,
                PartitionClass::Fenced(Stale),
            ),
            (
                "an input committed that the state never recorded",
                stored(None, &[(Events, 100)]),
                &committed,
                false,
                false,
                PartitionClass::Fenced(Stale),
            ),
            (
                "lost volume",
                StoredProvenance::default(),
                &committed,
                false,
                false,
                PartitionClass::Fenced(Cold),
            ),
            (
                "first boot of a new deployment",
                StoredProvenance::default(),
                &none,
                false,
                false,
                PartitionClass::Warm,
            ),
            (
                "first deploy over an intact legacy store",
                StoredProvenance::default(),
                &committed,
                false,
                true,
                PartitionClass::Warm,
            ),
            (
                "post-boot move-in",
                stored(None, &[(Events, 100), (Seeds, 10)]),
                &committed,
                true,
                false,
                PartitionClass::Fenced(Cold),
            ),
            (
                "a persisted fence survives a caught-up restart",
                stored(Some(Stale), &[(Events, 100), (Seeds, 10)]),
                &committed,
                false,
                true,
                PartitionClass::Fenced(Stale),
            ),
        ];
        for (name, stored, expected, moved_in, adopt, class) in cases {
            assert_eq!(
                classify(&stored, expected, moved_in, adopt).class,
                class,
                "{name}"
            );
        }
    }

    #[test]
    fn a_new_fence_and_an_adoption_persist_what_the_next_boot_reads() {
        let committed = offsets(&[(ProvenanceInput::Events, 100)]);

        let cold = classify(&StoredProvenance::default(), &committed, false, false);
        let reread = StoredProvenance {
            lineage: cold.lineage_write,
            ..StoredProvenance::default()
        };
        assert_eq!(
            classify(&reread, &committed, false, false).class,
            PartitionClass::Fenced(WithheldReason::Cold),
            "a cold partition stays fenced after its own commits catch up",
        );

        let adopted = classify(&StoredProvenance::default(), &committed, false, true);
        let reread = StoredProvenance {
            lineage: adopted.lineage_write,
            inputs: adopted.input_writes,
        };
        assert_eq!(
            classify(&reread, &committed, false, false).class,
            PartitionClass::Warm,
            "an adopted partition reads warm once the store tracks provenance",
        );
    }

    #[test]
    fn stored_provenance_round_trips_through_its_slots() {
        let lineage = Lineage {
            id: Uuid::from_u128(42),
            fence: Some(WithheldReason::Stale),
        };
        let slots = vec![
            (LINEAGE_SLOT, lineage.encode().to_vec()),
            (ProvenanceInput::Seeds.slot(), 17i64.to_be_bytes().to_vec()),
            (200, 1i64.to_be_bytes().to_vec()),
        ];
        assert_eq!(
            StoredProvenance::decode(slots),
            StoredProvenance {
                lineage: Some(lineage),
                inputs: offsets(&[(ProvenanceInput::Seeds, 17)]),
            },
        );
        assert_eq!(
            StoredProvenance::decode(vec![(LINEAGE_SLOT, vec![9; LINEAGE_LEN])]).lineage,
            None,
            "an unreadable lineage reads as absent, so it cannot certify",
        );
    }

    #[test]
    fn a_waiting_tenure_commits_nothing_and_an_old_tenures_verdict_is_dropped() {
        let registry = ProvenanceRegistry::enabled();
        registry.begin_tenure(3);
        let (_, old_generation) = registry.pending()[0];
        let offsets: HashMap<i32, i64> = [(3, 50), (4, 60)].into_iter().collect();
        assert!(registry.committable(offsets.clone()).is_empty());
        assert_eq!(registry.class(3), None);

        registry.end_tenure(3);
        registry.begin_tenure(3);
        assert!(!registry.settle(3, old_generation, PartitionClass::Warm));
        assert_eq!(registry.class(3), None);

        let (_, generation) = registry.pending()[0];
        assert!(registry.settle(3, generation, PartitionClass::Fenced(WithheldReason::Cold)));
        assert_eq!(
            registry.committable(offsets),
            [(3, 50)].into_iter().collect::<HashMap<_, _>>(),
            "a fenced partition still commits; only an unowned or waiting one does not",
        );

        let disabled = ProvenanceRegistry::default();
        assert_eq!(disabled.class(9), Some(PartitionClass::Warm));
    }
}
