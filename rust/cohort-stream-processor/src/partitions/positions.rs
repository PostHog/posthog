//! Where each input topic resumes, read from its consumer group on the broker. A checkpoint records
//! these positions, and a restore commits them back.
//!
//! Every commit the processor makes follows a WAL fsync, so a group's committed offset is at or
//! below the durable state, and a checkpoint taken after reading it contains at least that state.
//! That holds only while this pod is the one committer for the partitions it checkpoints, which a
//! single pod guarantees and static ownership must keep.

use std::collections::{BTreeMap, BTreeSet};
use std::fmt;
use std::time::Duration;

use rdkafka::consumer::{BaseConsumer, CommitMode, Consumer, ConsumerContext};
use rdkafka::error::{KafkaError, KafkaResult};
use rdkafka::types::RDKafkaErrorCode;
use rdkafka::{Offset, TopicPartitionList};
use serde::{Deserialize, Serialize};

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
}

/// Reads one input's consumer-group positions without joining the group. Every method blocks, so
/// async callers go through `spawn_blocking`.
struct GroupReader {
    topic: InputTopic,
    client: BaseConsumer,
}

impl GroupReader {
    /// A client that never subscribes or assigns, so it outlives the group's own consumer at
    /// shutdown and never takes part in a rebalance.
    fn new(config: &Config, topic: &str, group: &str) -> KafkaResult<Self> {
        Ok(Self {
            topic: InputTopic::new(topic),
            client: config.follower_client_config(group).create()?,
        })
    }

    fn topic(&self) -> &InputTopic {
        &self.topic
    }

    /// The group's committed offset per partition, or the low watermark where the group has none.
    /// A consumer without a commit starts at or after the low watermark, so replay from there
    /// misses nothing.
    fn resume_positions(
        &self,
        partitions: &BTreeSet<u16>,
    ) -> Result<InputPositions, PositionsError> {
        let topic = self.topic.as_str();
        let mut request = TopicPartitionList::new();
        for &partition in partitions {
            request.add_partition(topic, i32::from(partition));
        }
        let committed = self.client.committed_offsets(request, FETCH_TIMEOUT)?;

        let mut offsets = BTreeMap::new();
        let mut uncommitted = Vec::new();
        for &partition in partitions {
            let commit = committed.find_partition(topic, i32::from(partition));
            match commit.as_ref().map(|elem| (elem.error(), elem.offset())) {
                Some((Err(err), _)) => return Err(err.into()),
                Some((Ok(()), Offset::Offset(next))) => {
                    offsets.insert(partition, ResumeOffset::try_from(next)?);
                }
                _ => uncommitted.push(partition),
            }
        }
        for (partition, (low, _)) in self.watermarks(uncommitted)? {
            offsets.insert(partition, ResumeOffset::try_from(low)?);
        }
        Ok(InputPositions::new(self.topic.clone(), offsets))
    }

    fn watermarks(
        &self,
        partitions: impl IntoIterator<Item = u16>,
    ) -> KafkaResult<BTreeMap<u16, (i64, i64)>> {
        read_watermarks(&self.client, &self.topic, partitions)
    }
}

/// A follower's group has no members, so a commit from any client needs no generation. Only
/// followers get one: the events group commits through its member consumer.
pub struct FollowerGroup(GroupReader);

impl FollowerGroup {
    pub fn topic(&self) -> &InputTopic {
        self.0.topic()
    }

    pub fn commit(&self, positions: &BTreeMap<u16, ResumeOffset>) -> KafkaResult<()> {
        if positions.is_empty() {
            return Ok(());
        }
        let mut tpl = TopicPartitionList::new();
        for (&partition, &offset) in positions {
            tpl.add_partition_offset(
                self.topic().as_str(),
                i32::from(partition),
                Offset::Offset(offset.get()),
            )?;
        }
        self.0.client.commit(&tpl, CommitMode::Sync)
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
    pub fn new(config: &Config) -> KafkaResult<Self> {
        let events = GroupReader::new(
            config,
            &config.cohort_stream_events_topic,
            &config.kafka_consumer_group,
        )?;
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
            .map(|(topic, group)| GroupReader::new(config, topic, group).map(FollowerGroup))
            .collect::<KafkaResult<Vec<_>>>()?;

        let inputs = std::iter::once(events.topic().clone())
            .chain(followers.iter().map(|follower| follower.topic().clone()))
            .collect();
        Ok(Self {
            events,
            followers,
            inputs,
        })
    }

    pub fn inputs(&self) -> &BTreeSet<InputTopic> {
        &self.inputs
    }

    pub fn followers(&self) -> &[FollowerGroup] {
        &self.followers
    }

    /// Every input's resume positions on `partitions`.
    pub fn resume_positions(
        &self,
        partitions: &BTreeSet<u16>,
    ) -> Result<Vec<InputPositions>, PositionsError> {
        self.readers()
            .map(|reader| reader.resume_positions(partitions))
            .collect()
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
