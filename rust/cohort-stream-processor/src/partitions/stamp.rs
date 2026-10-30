//! Commit stamps. Every offset commit on the input groups carries the committer's split as Kafka
//! commit metadata, so a pod can tell who last committed each of its partitions (see
//! [`super::fence`]). [`StampedList::commit`] is the only offset commit in the crate, and only a
//! [`CommitStamp`] builds a [`StampedList`].

use std::fmt;
use std::num::NonZeroU16;

use rdkafka::consumer::{CommitMode, Consumer, ConsumerContext};
use rdkafka::error::{KafkaError, KafkaResult};
use rdkafka::types::RDKafkaErrorCode;
use rdkafka::{Offset, TopicPartitionList};
use tokio_util::sync::CancellationToken;

use super::PartitionOwnership;
use crate::store::durability::PodOrdinal;

/// The format tag. A later format gets a new tag, which this build reads as unrecognized.
const PREFIX: &str = "cohort-split/1:";

/// What a commit's metadata says about who made it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Stamp {
    /// Empty: a build from before stamps, or a standard Kafka tool such as an offset reset.
    Unstamped,
    Split(PartitionOwnership),
    /// Metadata this build cannot read. The fence treats it like another split.
    Unrecognized(String),
}

impl Stamp {
    pub fn parse(metadata: &str) -> Self {
        if metadata.is_empty() {
            return Self::Unstamped;
        }
        Self::decode(metadata).map_or_else(|| Self::Unrecognized(metadata.to_owned()), Self::Split)
    }

    fn decode(metadata: &str) -> Option<PartitionOwnership> {
        let mut fields = metadata.strip_prefix(PREFIX)?.split(':');
        let (Some(pods), Some(ordinal), Some(partitions), None) =
            (fields.next(), fields.next(), fields.next(), fields.next())
        else {
            return None;
        };
        PartitionOwnership::new(
            pods.parse::<NonZeroU16>().ok()?,
            PodOrdinal::from(ordinal.parse::<u16>().ok()?),
            partitions.parse().ok()?,
        )
        .ok()
    }

    /// True when a split other than `split` made the commit, or when the metadata cannot say.
    pub fn is_foreign_to(&self, split: &PartitionOwnership) -> bool {
        match self {
            Self::Unstamped => false,
            Self::Split(found) => found != split,
            Self::Unrecognized(_) => true,
        }
    }
}

impl fmt::Display for Stamp {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Unstamped => f.write_str("no stamp"),
            Self::Split(split) => write!(f, "{split}"),
            Self::Unrecognized(metadata) => write!(f, "unreadable metadata {metadata:?}"),
        }
    }
}

/// This pod's stamp. Only an admitted split builds one. The ownership audit revokes it when another
/// split commits an owned partition, and from then on no list built from it or a clone commits.
#[derive(Debug, Clone)]
pub struct CommitStamp {
    split: PartitionOwnership,
    revoked: CancellationToken,
}

impl CommitStamp {
    pub(super) fn new(split: PartitionOwnership) -> Self {
        Self {
            split,
            revoked: CancellationToken::new(),
        }
    }

    #[cfg(test)]
    pub(crate) fn for_test(split: PartitionOwnership) -> Self {
        Self::new(split)
    }

    pub(super) fn split(&self) -> PartitionOwnership {
        self.split
    }

    pub(super) fn revoke(&self) {
        self.revoked.cancel();
    }

    /// `offsets` on `topic` as a commit list, each element stamped. Fails on a negative offset.
    pub fn list(
        &self,
        topic: &str,
        offsets: impl IntoIterator<Item = (i32, i64)>,
    ) -> KafkaResult<StampedList> {
        let metadata = self.to_string();
        let mut list = TopicPartitionList::new();
        for (partition, offset) in offsets {
            let mut elem = list.add_partition(topic, partition);
            elem.set_offset(Offset::Offset(offset))?;
            elem.set_metadata(&metadata);
        }
        Ok(StampedList {
            list,
            revoked: self.revoked.clone(),
        })
    }
}

impl fmt::Display for CommitStamp {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "{PREFIX}{}:{}:{}",
            self.split.pods(),
            self.split.ordinal(),
            self.split.partition_count()
        )
    }
}

/// A commit list where every element carries this pod's stamp.
#[derive(Debug)]
pub struct StampedList {
    list: TopicPartitionList,
    revoked: CancellationToken,
}

impl StampedList {
    /// The list without its role as a commit, for a seek, which ignores metadata.
    pub fn as_list(&self) -> &TopicPartitionList {
        &self.list
    }

    /// Fails with `Fenced` once the stamp is revoked.
    #[allow(clippy::disallowed_methods)]
    pub fn commit<C, X>(&self, consumer: &C, mode: CommitMode) -> KafkaResult<()>
    where
        C: Consumer<X>,
        X: ConsumerContext,
    {
        if self.revoked.is_cancelled() {
            return Err(KafkaError::ConsumerCommit(RDKafkaErrorCode::Fenced));
        }
        consumer.commit(&self.list, mode)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_split_of_the_partitions_reads_back_from_its_stamp() {
        for pods in [1, 2, 4, 8, 16, 32, 64] {
            let pods = NonZeroU16::new(pods).unwrap();
            for ordinal in 0..pods.get() {
                let split = PartitionOwnership::new(pods, PodOrdinal::from(ordinal), 64).unwrap();
                let stamp = CommitStamp::new(split).to_string();
                assert_eq!(Stamp::parse(&stamp), Stamp::Split(split), "{stamp}");
            }
        }
        assert_eq!(
            CommitStamp::new(PartitionOwnership::single(64)).to_string(),
            "cohort-split/1:1:0:64"
        );
    }

    #[test]
    fn empty_metadata_is_unstamped_and_anything_else_unreadable_is_unrecognized() {
        let own = PartitionOwnership::single(64);
        assert_eq!(Stamp::parse(""), Stamp::Unstamped);
        assert!(!Stamp::Unstamped.is_foreign_to(&own));
        assert!(Stamp::parse("cohort-split/1:1:0:32").is_foreign_to(&own));
        for metadata in [
            "cohort-split/2:2:0:64",
            "other-tool",
            "cohort-split/1:2:0",
            "cohort-split/1:2:0:64:1",
            "cohort-split/1:0:0:64",
            "cohort-split/1:3:0:64",
            "cohort-split/1:2:2:64",
            "cohort-split/1:2:x:64",
        ] {
            let stamp = Stamp::parse(metadata);
            assert_eq!(
                stamp,
                Stamp::Unrecognized(metadata.to_owned()),
                "{metadata}"
            );
            assert!(stamp.is_foreign_to(&own), "the audit stops on {metadata}");
        }
    }

    #[test]
    fn a_stamped_list_carries_the_stamp_on_every_offset() {
        let split =
            PartitionOwnership::new(NonZeroU16::new(2).unwrap(), PodOrdinal::from(1), 4).unwrap();
        let list = CommitStamp::new(split)
            .list("cohort_stream_events", [(1, 10), (3, 0)])
            .unwrap();
        let elements: Vec<(i32, Offset, String)> = list
            .as_list()
            .elements()
            .iter()
            .map(|elem| (elem.partition(), elem.offset(), elem.metadata().to_owned()))
            .collect();
        assert_eq!(
            elements,
            [
                (1, Offset::Offset(10), "cohort-split/1:2:1:4".to_owned()),
                (3, Offset::Offset(0), "cohort-split/1:2:1:4".to_owned()),
            ],
        );
        assert!(CommitStamp::new(split)
            .list("cohort_stream_events", [(1, -1)])
            .is_err());
    }
}
