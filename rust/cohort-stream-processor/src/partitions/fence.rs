//! The ownership fence: one owner per partition, across pods and restarts. Every commit on the
//! input groups carries its committer's split (see [`super::stamp`]), and the fence reads those
//! stamps three times.
//!
//! 1. **Admission**, before the store opens. A stamp from another split on an owned partition holds
//!    the boot.
//! 2. **The claim**, after the store opens. The pod checks the stamps again, stamps every owned
//!    partition on every group and reads the stamps back, so a broker that drops commit metadata
//!    stops the pod.
//! 3. **The audit**, while the pod runs. Another split's commit on an owned partition revokes this
//!    pod's commits and stops the pod, so the next boot holds in admission.
//!
//! Two processes with one ordinal are not fenced: they carry the same stamp.

use std::collections::{BTreeMap, BTreeSet};
use std::sync::Arc;
use std::time::Duration;

use anyhow::bail;
use async_trait::async_trait;
use lifecycle::Handle;
use metrics::{counter, gauge};
use tracing::{error, info, warn};

use super::positions::{InputGroups, InputTopic, PositionsError, ResumeOffset};
use super::stamp::{CommitStamp, Stamp};
use super::PartitionOwnership;
use crate::observability::metrics::{OWNERSHIP_FENCE_BLOCKED, OWNERSHIP_FENCE_VIOLATIONS_TOTAL};
use crate::sweep::Sweeper;

/// The admission retries as a blocked restore does.
const RETRY_START: Duration = Duration::from_secs(30);
const RETRY_MAX: Duration = Duration::from_secs(300);

/// How often the audit reads the stamps on the owned partitions.
pub const AUDIT_INTERVAL: Duration = Duration::from_secs(30);

/// The last commit of one group on one partition.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Committed {
    Never,
    At { offset: ResumeOffset, stamp: Stamp },
}

impl Committed {
    pub fn stamp(&self) -> Option<&Stamp> {
        match self {
            Self::Never => None,
            Self::At { stamp, .. } => Some(stamp),
        }
    }
}

/// One input group's last commits.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InputCommits {
    topic: InputTopic,
    commits: BTreeMap<u16, Committed>,
}

impl InputCommits {
    pub(super) fn new(topic: InputTopic, commits: BTreeMap<u16, Committed>) -> Self {
        Self { topic, commits }
    }

    pub fn topic(&self) -> &InputTopic {
        &self.topic
    }

    pub fn commits(&self) -> &BTreeMap<u16, Committed> {
        &self.commits
    }
}

/// The last commits on a set of partitions, on every enabled group.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CommitLedger {
    events: InputCommits,
    followers: Vec<InputCommits>,
}

impl CommitLedger {
    pub(super) fn new(events: InputCommits, followers: Vec<InputCommits>) -> Self {
        Self { events, followers }
    }

    /// Every group's commits, the events group first.
    pub fn inputs(&self) -> impl Iterator<Item = &InputCommits> {
        std::iter::once(&self.events).chain(&self.followers)
    }

    fn stamps(&self) -> impl Iterator<Item = (&InputTopic, u16, &Stamp)> {
        self.inputs().flat_map(|input| {
            input
                .commits
                .iter()
                .filter_map(move |(&partition, committed)| {
                    Some((&input.topic, partition, committed.stamp()?))
                })
        })
    }

    /// The fence decision over a ledger that holds `ownership`'s partitions. An owned partition may
    /// carry no stamp, from a build before stamps or a standard Kafka tool, or this pod's split.
    fn admit(&self, ownership: PartitionOwnership) -> Result<(), FenceBlock> {
        for (topic, partition, stamp) in self.stamps() {
            if !ownership.owns(partition) {
                continue;
            }
            match stamp {
                Stamp::Unstamped => {}
                Stamp::Split(found) if *found == ownership => {}
                Stamp::Split(found) => {
                    return Err(FenceBlock::ForeignSplit {
                        topic: topic.clone(),
                        partition,
                        found: *found,
                    })
                }
                Stamp::Unrecognized(metadata) => {
                    return Err(FenceBlock::Unrecognized {
                        topic: topic.clone(),
                        partition,
                        metadata: metadata.clone(),
                    })
                }
            }
        }
        Ok(())
    }
}

/// Why the fence holds the boot.
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum FenceBlock {
    #[error(
        "{found} committed {topic} partition {partition}: its pods may still run, or the pod count \
         changed"
    )]
    ForeignSplit {
        topic: InputTopic,
        partition: u16,
        found: PartitionOwnership,
    },
    #[error("{topic} partition {partition} carries commit metadata this build cannot read: {metadata:?}")]
    Unrecognized {
        topic: InputTopic,
        partition: u16,
        metadata: String,
    },
}

impl FenceBlock {
    const REASONS: [&'static str; 2] = ["foreign_split", "unrecognized"];

    fn reason(&self) -> &'static str {
        match self {
            Self::ForeignSplit { .. } => Self::REASONS[0],
            Self::Unrecognized { .. } => Self::REASONS[1],
        }
    }

    /// Holds `ownership_fence_blocked` at 1 for `blocked`'s reason, and at 0 for the others.
    fn record(blocked: Option<&Self>) {
        let reason = blocked.map(Self::reason);
        for label in Self::REASONS {
            gauge!(OWNERSHIP_FENCE_BLOCKED, "reason" => label).set(if reason == Some(label) {
                1.0
            } else {
                0.0
            });
        }
    }
}

#[derive(Debug, thiserror::Error)]
pub enum FenceError {
    #[error(transparent)]
    Blocked(#[from] FenceBlock),
    #[error("reading the commit ledger failed")]
    Ledger(#[from] PositionsError),
}

/// A split the fence admitted: no other split commits its partitions. Only the admission builds
/// one.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct AdmittedSplit {
    ownership: PartitionOwnership,
}

impl AdmittedSplit {
    /// Retries [`Self::try_admit`] with backoff until the fence admits `ownership`. Each read runs
    /// on a blocking thread, so the health server keeps answering, and the pod reads not ready.
    pub async fn admit(ownership: PartitionOwnership, groups: Arc<InputGroups>) -> Self {
        let mut backoff = RETRY_START;
        loop {
            let reader = groups.clone();
            let attempt = match tokio::task::spawn_blocking(move || {
                Self::try_admit(ownership, &reader)
            })
            .await
            {
                Ok(attempt) => attempt,
                Err(err) => std::panic::resume_unwind(err.into_panic()),
            };
            match attempt {
                Ok(admitted) => {
                    FenceBlock::record(None);
                    info!(%ownership, "the ownership fence admitted this pod");
                    return admitted;
                }
                Err(FenceError::Blocked(block)) => {
                    FenceBlock::record(Some(&block));
                    warn!(
                        %ownership,
                        %block,
                        retry_in_secs = backoff.as_secs(),
                        "the ownership fence holds the boot",
                    );
                }
                Err(FenceError::Ledger(err)) => warn!(
                    %ownership,
                    error = %err,
                    retry_in_secs = backoff.as_secs(),
                    "reading the commit ledger failed; retrying",
                ),
            }
            tokio::time::sleep(backoff).await;
            backoff = (backoff * 2).min(RETRY_MAX);
        }
    }

    /// One fence read. Blocks on Kafka.
    pub fn try_admit(
        ownership: PartitionOwnership,
        groups: &InputGroups,
    ) -> Result<Self, FenceError> {
        let partitions: BTreeSet<u16> = ownership.partitions().collect();
        groups.ledger(&partitions)?.admit(ownership)?;
        Ok(Self { ownership })
    }

    pub fn ownership(&self) -> PartitionOwnership {
        self.ownership
    }

    pub fn stamp(&self) -> CommitStamp {
        CommitStamp::new(self.ownership)
    }

    /// Checks the fence again, then commits every owned partition on every group again with this
    /// pod's stamp, at the group's commit or at the low watermark where the group never committed,
    /// and reads the stamps back. Blocks on Kafka.
    pub fn claim(self, groups: &InputGroups) -> anyhow::Result<ClaimedSplit> {
        let partitions: BTreeSet<u16> = self.ownership.partitions().collect();
        // Another split can claim while this pod opens its store. The restamp would cover that
        // split's stamps, so the claim checks the fence on the same commits that it overwrites.
        let ledger = groups.ledger(&partitions)?;
        ledger.admit(self.ownership)?;
        let stamp = self.stamp();
        groups.restamp(&stamp, &ledger)?;
        let ours = Stamp::Split(self.ownership);
        for input in groups.ledger(&partitions)?.inputs() {
            for (&partition, committed) in input.commits() {
                let topic = input.topic();
                match committed.stamp() {
                    Some(stamp) if *stamp == ours => {}
                    Some(stamp @ (Stamp::Split(_) | Stamp::Unrecognized(_))) => bail!(
                        "{topic} partition {partition} read back {stamp} after this pod stamped \
                         it: another process committed it during the claim"
                    ),
                    Some(Stamp::Unstamped) | None => bail!(
                        "the broker does not keep offset commit metadata, so the ownership fence \
                         cannot work: {topic} partition {partition} read back no stamp after this \
                         pod stamped it"
                    ),
                }
            }
        }
        info!(ownership = %self.ownership, "claimed every owned partition; the stamps read back");
        Ok(ClaimedSplit(stamp))
    }
}

/// A split whose every owned partition carries its stamp on every group. The consumers and the
/// followers take it as proof, and commit with its stamp until the audit revokes it.
#[derive(Debug, Clone)]
pub struct ClaimedSplit(CommitStamp);

impl ClaimedSplit {
    pub fn ownership(&self) -> PartitionOwnership {
        self.0.split()
    }

    pub fn stamp(&self) -> CommitStamp {
        self.0.clone()
    }
}

/// Stops the pod when another split commits one of its partitions. A commit without a stamp passes:
/// an operator's offset reset writes none, and the claim proved that the broker keeps stamps.
pub struct OwnershipAudit {
    groups: Arc<InputGroups>,
    claimed: ClaimedSplit,
    handle: Handle,
}

impl OwnershipAudit {
    pub fn new(groups: Arc<InputGroups>, claimed: ClaimedSplit, handle: Handle) -> Self {
        Self {
            groups,
            claimed,
            handle,
        }
    }
}

#[async_trait]
impl Sweeper for OwnershipAudit {
    async fn run_once(&self) {
        let groups = self.groups.clone();
        let partitions: BTreeSet<u16> = self.claimed.ownership().partitions().collect();
        let ledger = match tokio::task::spawn_blocking(move || groups.ledger(&partitions)).await {
            Ok(Ok(ledger)) => ledger,
            Ok(Err(err)) => {
                warn!(error = %err, "ownership audit: reading the commit ledger failed; skipping");
                return;
            }
            Err(err) => {
                error!(error = %err, "ownership audit: reading the commit ledger panicked; skipping");
                return;
            }
        };
        let ownership = self.claimed.ownership();
        let mut violated = false;
        for (topic, partition, stamp) in ledger.stamps() {
            if stamp.is_foreign_to(&ownership) {
                let label: Arc<str> = Arc::from(topic.as_str());
                counter!(OWNERSHIP_FENCE_VIOLATIONS_TOTAL, "topic" => label).increment(1);
                error!(
                    %topic,
                    partition,
                    %stamp,
                    %ownership,
                    "another split committed a partition this pod owns",
                );
                violated = true;
            }
        }
        if violated {
            // The graceful stop commits this pod's offsets with its stamp over the foreign one, and
            // the next boot would then pass the fence.
            self.claimed.0.revoke();
            self.handle
                .signal_failure("another split committed a partition this pod owns");
        }
    }
}

#[cfg(test)]
mod tests {
    use std::num::NonZeroU16;

    use super::*;
    use crate::store::durability::PodOrdinal;

    const PARTITIONS: u16 = 4;
    const EVENTS: &str = "cohort_stream_events";
    const MERGES: &str = "person_merge_events";

    fn split(pods: u16, ordinal: u16) -> PartitionOwnership {
        PartitionOwnership::new(
            NonZeroU16::new(pods).unwrap(),
            PodOrdinal::from(ordinal),
            PARTITIONS,
        )
        .unwrap()
    }

    /// `None` is a partition its group never committed.
    fn commits(topic: &str, stamps: [Option<Stamp>; PARTITIONS as usize]) -> InputCommits {
        let commits = (0..PARTITIONS)
            .zip(stamps)
            .map(|(partition, stamp)| {
                let committed = match stamp {
                    None => Committed::Never,
                    Some(stamp) => Committed::At {
                        offset: ResumeOffset::try_from(7).unwrap(),
                        stamp,
                    },
                };
                (partition, committed)
            })
            .collect();
        InputCommits::new(InputTopic::new(topic), commits)
    }

    fn by(pods: u16, ordinal: u16) -> Option<Stamp> {
        Some(Stamp::Split(split(pods, ordinal)))
    }

    #[test]
    fn the_fence_admits_a_split_only_over_its_own_or_no_stamps() {
        let unstamped = || Some(Stamp::Unstamped);
        let unreadable = || Some(Stamp::Unrecognized("other-tool".to_owned()));
        type Row = (
            &'static str,
            PartitionOwnership,
            [Option<Stamp>; 4],
            [Option<Stamp>; 4],
            Result<(), FenceBlock>,
        );
        let rows: Vec<Row> = vec![
            (
                "unreadable metadata blocks",
                split(1, 0),
                [by(1, 0), by(1, 0), unreadable(), by(1, 0)],
                [by(1, 0), by(1, 0), by(1, 0), by(1, 0)],
                Err(FenceBlock::Unrecognized {
                    topic: InputTopic::new(EVENTS),
                    partition: 2,
                    metadata: "other-tool".to_owned(),
                }),
            ),
            (
                "its own stamps, none, and partitions never committed",
                split(2, 1),
                [by(2, 0), by(2, 1), by(2, 0), unstamped()],
                [None, by(2, 1), None, None],
                Ok(()),
            ),
            (
                "another split: the pod count changed",
                split(2, 1),
                [by(2, 0), by(1, 0), by(2, 0), by(1, 0)],
                [by(2, 0), by(1, 0), by(2, 0), by(1, 0)],
                Err(FenceBlock::ForeignSplit {
                    topic: InputTopic::new(EVENTS),
                    partition: 1,
                    found: split(1, 0),
                }),
            ),
        ];
        for (name, ownership, events, merges, expected) in rows {
            let ledger = CommitLedger::new(commits(EVENTS, events), vec![commits(MERGES, merges)]);
            assert_eq!(ledger.admit(ownership), expected, "{name}");
        }
    }
}
