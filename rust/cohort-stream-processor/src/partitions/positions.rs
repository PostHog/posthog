//! Where each input topic resumes, and who committed it, read from its consumer group on the
//! broker. A checkpoint records these positions, and a restore commits them back.
//!
//! Every commit the processor makes follows a WAL fsync, so a group's committed offset is at or
//! below the durable state, and a checkpoint taken after reading it contains at least that state.
//! That holds only for this pod's own commits, so a checkpoint takes no position another split
//! stamped (see [`super::fence`]).

use std::collections::{BTreeMap, BTreeSet};
use std::fmt;
use std::time::Duration;

use rdkafka::consumer::{BaseConsumer, CommitMode, Consumer, ConsumerContext};
use rdkafka::error::{KafkaError, KafkaResult};
use rdkafka::types::RDKafkaErrorCode;
use rdkafka::{ClientConfig, Offset, TopicPartitionList};
use serde::{Deserialize, Serialize};

use super::fence::{ClaimedSplit, CommitLedger, Committed, InputCommits};
use super::stamp::{CommitStamp, Stamp};
use super::PartitionOwnership;
use crate::config::Config;

const FETCH_TIMEOUT: Duration = Duration::from_secs(10);

/// An input topic's name. A newtype, so a topic and a consumer group name cannot be swapped.
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
#[serde(transparent)]
pub struct InputTopic(String);

impl InputTopic {
    pub fn new(topic: impl Into<String>) -> Self {
        Self(topic.into())
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl fmt::Display for InputTopic {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}

/// The next offset a consumer reads on one input partition. Never negative.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(try_from = "i64", into = "i64")]
pub struct ResumeOffset(i64);

#[derive(Debug, thiserror::Error)]
#[error("offset {0} is negative")]
pub struct NegativeOffset(i64);

impl TryFrom<i64> for ResumeOffset {
    type Error = NegativeOffset;

    fn try_from(offset: i64) -> Result<Self, Self::Error> {
        if offset < 0 {
            return Err(NegativeOffset(offset));
        }
        Ok(Self(offset))
    }
}

impl From<ResumeOffset> for i64 {
    fn from(offset: ResumeOffset) -> Self {
        offset.0
    }
}

impl ResumeOffset {
    pub fn get(self) -> i64 {
        self.0
    }
}

/// The `[low, high]` watermarks of `partitions` on `topic`. Asks each partition leader once per
/// bound, where `Consumer::fetch_watermarks` asks twice per partition: a restore checks every
/// partition of every input, and the boot waits on it.
fn read_watermarks<C, X>(
    client: &C,
    topic: &InputTopic,
    partitions: impl IntoIterator<Item = u16>,
) -> KafkaResult<BTreeMap<u16, (i64, i64)>>
where
    C: Consumer<X>,
    X: ConsumerContext,
{
    let partitions: Vec<(&InputTopic, u16)> = partitions
        .into_iter()
        .map(|partition| (topic, partition))
        .collect();
    let low = list_offsets(client, &partitions, Offset::Beginning)?;
    let high = list_offsets(client, &partitions, Offset::End)?;
    Ok(partitions
        .into_iter()
        .map(|(_, partition)| partition)
        .zip(low.into_iter().zip(high))
        .collect())
}

/// Where `at` falls on each of `partitions`, in their order, from one `ListOffsets` request per
/// partition leader, all within one timeout. `ListOffsets` reads the special timestamps `Beginning`
/// and `End` as the low and high watermarks, exactly as `fetch_watermarks` asks for them.
pub fn list_offsets<C, X>(
    client: &C,
    partitions: &[(&InputTopic, u16)],
    at: Offset,
) -> KafkaResult<Vec<i64>>
where
    C: Consumer<X>,
    X: ConsumerContext,
{
    // librdkafka fails `offsets_for_times` on an empty list with `InvalidArg`.
    if partitions.is_empty() {
        return Ok(Vec::new());
    }
    let mut request = TopicPartitionList::new();
    for &(topic, partition) in partitions {
        request.add_partition_offset(topic.as_str(), i32::from(partition), at)?;
    }
    let answered = client.offsets_for_times(request, FETCH_TIMEOUT)?;
    partitions
        .iter()
        .map(|&(topic, partition)| {
            let elem = answered
                .find_partition(topic.as_str(), i32::from(partition))
                .ok_or(KafkaError::OffsetFetch(RDKafkaErrorCode::UnknownPartition))?;
            elem.error()?;
            match elem.offset() {
                Offset::Offset(offset) => Ok(offset),
                _ => Err(KafkaError::OffsetFetch(RDKafkaErrorCode::InvalidArgument)),
            }
        })
        .collect()
}

/// One input's resume positions, read from its consumer group.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InputPositions {
    topic: InputTopic,
    offsets: BTreeMap<u16, ResumeOffset>,
}

impl InputPositions {
    pub fn new(topic: InputTopic, offsets: BTreeMap<u16, ResumeOffset>) -> Self {
        Self { topic, offsets }
    }

    pub fn topic(&self) -> &InputTopic {
        &self.topic
    }

    pub fn offsets(&self) -> &BTreeMap<u16, ResumeOffset> {
        &self.offsets
    }
}

#[derive(Debug, thiserror::Error)]
pub enum PositionsError {
    #[error(transparent)]
    Kafka(#[from] KafkaError),
    #[error(transparent)]
    Negative(#[from] NegativeOffset),
    #[error("{topic} partition {partition} was last committed by {stamp}, not this pod")]
    Foreign {
        topic: InputTopic,
        partition: u16,
        stamp: Stamp,
    },
}

/// Every input's resume positions on partitions of a claimed split, none of them stamped by
/// another split. Only [`InputGroups::owned_positions`] builds one, so a manifest never records a
/// position another split stamped. An unstamped commit, such as an offset reset, passes.
#[derive(Debug)]
pub struct OwnedPositions {
    split: PartitionOwnership,
    inputs: Vec<InputPositions>,
}

impl OwnedPositions {
    #[cfg(test)]
    pub(crate) fn for_test(split: PartitionOwnership, inputs: Vec<InputPositions>) -> Self {
        Self { split, inputs }
    }

    pub fn split(&self) -> PartitionOwnership {
        self.split
    }

    pub fn inputs(&self) -> &[InputPositions] {
        &self.inputs
    }
}

/// Reads and commits one input's consumer-group positions without joining the group. Every method
/// blocks, so async callers go through `spawn_blocking`.
struct GroupReader {
    topic: InputTopic,
    config: ClientConfig,
}

impl GroupReader {
    fn new(config: &Config, topic: &str, group: &str) -> Self {
        Self {
            topic: InputTopic::new(topic),
            config: config.follower_client_config(group),
        }
    }

    /// A client that never subscribes or assigns, so it outlives the group's own consumer at
    /// shutdown and never takes part in a rebalance. Each call builds its own and drops it: nothing
    /// polls these clients, so one kept between calls would hold every log and error event
    /// librdkafka queues for it.
    fn client(&self) -> KafkaResult<BaseConsumer> {
        self.config.create()
    }

    fn topic(&self) -> &InputTopic {
        &self.topic
    }

    /// The group's last commit on each of `partitions`, from one `OffsetFetch`.
    fn commits(
        &self,
        client: &BaseConsumer,
        partitions: &BTreeSet<u16>,
    ) -> Result<InputCommits, PositionsError> {
        let topic = self.topic.as_str();
        let mut request = TopicPartitionList::new();
        for &partition in partitions {
            request.add_partition(topic, i32::from(partition));
        }
        let answered = client.committed_offsets(request, FETCH_TIMEOUT)?;
        let mut commits = BTreeMap::new();
        for &partition in partitions {
            let committed = match answered.find_partition(topic, i32::from(partition)) {
                Some(elem) => {
                    elem.error()?;
                    match elem.offset() {
                        Offset::Offset(next) => Committed::At {
                            offset: ResumeOffset::try_from(next)?,
                            stamp: Stamp::parse(elem.metadata()),
                        },
                        _ => Committed::Never,
                    }
                }
                None => Committed::Never,
            };
            commits.insert(partition, committed);
        }
        Ok(InputCommits::new(self.topic.clone(), commits))
    }

    /// Where the group resumes on each partition of `commits`: its committed offset, or the low
    /// watermark where it has none. Every consumer here starts at `earliest`, so replay from the low
    /// watermark misses nothing.
    fn resume_positions(
        &self,
        client: &BaseConsumer,
        commits: &InputCommits,
    ) -> Result<BTreeMap<u16, ResumeOffset>, PositionsError> {
        let mut positions = BTreeMap::new();
        let mut uncommitted = Vec::new();
        for (&partition, committed) in commits.commits() {
            match committed {
                Committed::At { offset, .. } => {
                    positions.insert(partition, *offset);
                }
                Committed::Never => uncommitted.push((&self.topic, partition)),
            }
        }
        let lows = list_offsets(client, &uncommitted, Offset::Beginning)?;
        for (&(_, partition), low) in uncommitted.iter().zip(lows) {
            positions.insert(partition, ResumeOffset::try_from(low)?);
        }
        Ok(positions)
    }

    /// Refuses a position another split stamped.
    fn owned_positions(
        &self,
        owner: &PartitionOwnership,
        partitions: &BTreeSet<u16>,
    ) -> Result<InputPositions, PositionsError> {
        let client = self.client()?;
        let commits = self.commits(&client, partitions)?;
        for (&partition, committed) in commits.commits() {
            if let Some(stamp) = committed.stamp().filter(|stamp| stamp.is_foreign_to(owner)) {
                return Err(PositionsError::Foreign {
                    topic: self.topic.clone(),
                    partition,
                    stamp: stamp.clone(),
                });
            }
        }
        let positions = self.resume_positions(&client, &commits)?;
        Ok(InputPositions::new(self.topic.clone(), positions))
    }

    /// Commits each partition of `commits` again at its resume position, with `stamp`.
    fn restamp(&self, stamp: &CommitStamp, commits: &InputCommits) -> Result<(), PositionsError> {
        let positions = self.resume_positions(&self.client()?, commits)?;
        Ok(self.commit(stamp, &positions)?)
    }

    fn commit(
        &self,
        stamp: &CommitStamp,
        positions: &BTreeMap<u16, ResumeOffset>,
    ) -> KafkaResult<()> {
        if positions.is_empty() {
            return Ok(());
        }
        let offsets = positions
            .iter()
            .map(|(&partition, &offset)| (i32::from(partition), offset.get()));
        stamp
            .list(self.topic.as_str(), offsets)?
            .commit(&self.client()?, CommitMode::Sync)
    }

    fn watermarks(
        &self,
        partitions: impl IntoIterator<Item = u16>,
    ) -> KafkaResult<BTreeMap<u16, (i64, i64)>> {
        read_watermarks(&self.client()?, &self.topic, partitions)
    }
}

/// A follower's group has no members, so a commit from any client needs no generation. The
/// restore commits follower positions through it before any consumer runs.
pub struct FollowerGroup(GroupReader);

impl FollowerGroup {
    pub fn topic(&self) -> &InputTopic {
        self.0.topic()
    }

    pub fn commit(
        &self,
        stamp: &CommitStamp,
        positions: &BTreeMap<u16, ResumeOffset>,
    ) -> KafkaResult<()> {
        self.0.commit(stamp, positions)
    }
}

/// Every enabled input, built once at startup and shared by the restore, the checkpoint sweeper and
/// the final checkpoint.
pub struct InputGroups {
    events: GroupReader,
    followers: Vec<FollowerGroup>,
    inputs: BTreeSet<InputTopic>,
}

impl InputGroups {
    pub fn new(config: &Config) -> Self {
        let events = GroupReader::new(
            config,
            &config.cohort_stream_events_topic,
            &config.kafka_consumer_group,
        );
        let mut follower_inputs = vec![
            (
                &config.person_merge_events_topic,
                &config.kafka_merge_consumer_group,
            ),
            (
                &config.cohort_merge_state_transfer_topic,
                &config.kafka_merge_apply_consumer_group,
            ),
        ];
        if config.cohort_cascade_enabled {
            follower_inputs.push((
                &config.cohort_cascade_events_topic,
                &config.kafka_cascade_consumer_group,
            ));
        }
        if config.cohort_seed_consumer_enabled {
            follower_inputs.push((
                &config.cohort_stream_seed_events_topic,
                &config.kafka_seed_consumer_group,
            ));
        }
        let followers = follower_inputs
            .into_iter()
            .map(|(topic, group)| FollowerGroup(GroupReader::new(config, topic, group)))
            .collect::<Vec<_>>();

        let inputs = std::iter::once(events.topic().clone())
            .chain(followers.iter().map(|follower| follower.topic().clone()))
            .collect();
        Self {
            events,
            followers,
            inputs,
        }
    }

    pub fn inputs(&self) -> &BTreeSet<InputTopic> {
        &self.inputs
    }

    pub fn followers(&self) -> &[FollowerGroup] {
        &self.followers
    }

    /// The last commit on `partitions`, on every enabled group.
    pub fn ledger(&self, partitions: &BTreeSet<u16>) -> Result<CommitLedger, PositionsError> {
        let read = |reader: &GroupReader| reader.commits(&reader.client()?, partitions);
        let events = read(&self.events)?;
        let followers = self
            .followers
            .iter()
            .map(|follower| read(&follower.0))
            .collect::<Result<_, _>>()?;
        Ok(CommitLedger::new(events, followers))
    }

    /// Commits the partitions of `ledger`, read by [`Self::ledger`], again with `stamp` on every
    /// enabled group.
    pub(super) fn restamp(
        &self,
        stamp: &CommitStamp,
        ledger: &CommitLedger,
    ) -> Result<(), PositionsError> {
        self.readers()
            .zip(ledger.inputs())
            .try_for_each(|(reader, commits)| {
                debug_assert_eq!(reader.topic(), commits.topic());
                reader.restamp(stamp, commits)
            })
    }

    /// Every input's resume positions on `partitions`, as long as no other split stamped them.
    pub fn owned_positions(
        &self,
        claimed: &ClaimedSplit,
        partitions: &BTreeSet<u16>,
    ) -> Result<OwnedPositions, PositionsError> {
        let split = claimed.ownership();
        let inputs = self
            .readers()
            .map(|reader| reader.owned_positions(&split, partitions))
            .collect::<Result<_, _>>()?;
        Ok(OwnedPositions { split, inputs })
    }

    /// `topic`'s watermarks on partitions `0..partition_count`.
    pub fn watermarks(
        &self,
        topic: &InputTopic,
        partition_count: u16,
    ) -> KafkaResult<BTreeMap<u16, (i64, i64)>> {
        self.readers()
            .find(|reader| reader.topic() == topic)
            .ok_or(KafkaError::MetadataFetch(
                RDKafkaErrorCode::UnknownTopicOrPartition,
            ))?
            .watermarks(0..partition_count)
    }

    fn readers(&self) -> impl Iterator<Item = &GroupReader> {
        std::iter::once(&self.events).chain(self.followers.iter().map(|follower| &follower.0))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use rdkafka::ClientConfig;

    #[test]
    fn an_empty_request_reads_nothing_from_the_broker() {
        let unreachable: BaseConsumer = ClientConfig::new()
            .set("bootstrap.servers", "127.0.0.1:1")
            .create()
            .unwrap();
        assert_eq!(
            list_offsets(&unreachable, &[], Offset::Beginning).unwrap(),
            Vec::<i64>::new()
        );
    }
}
