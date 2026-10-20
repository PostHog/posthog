//! The ownership fence finds a partition that two splits commit, across pods and restarts. Every
//! commit on the input groups carries its committer's split (see [`super::stamp`]), and the fence
//! reads those stamps three times.
//!
//! 1. **Admission**, before the store opens. A stamp from another split on an owned partition holds
//!    the boot, unless a reshard names that split as this pod's parent. A reshard child also waits
//!    until its parent restarts under the new split, then takes its partitions over.
//! 2. **The claim**, after the store opens. The pod checks the stamps again, stamps every owned
//!    partition on every group and reads the stamps back, so a broker that drops commit metadata
//!    stops the pod.
//! 3. **The audit**, while the pod runs. Another split's commit on an owned partition revokes this
//!    pod's commits and stops the pod, so the next boot holds in admission.
//!
//! The fence detects an overlap but cannot prevent one, because Kafka commits are last-writer-wins
//! and have no compare-and-set. So a change of split relies on every pod of the old split stopping
//! first. Two processes with one ordinal are not fenced: they carry the same stamp.

use std::collections::{BTreeMap, BTreeSet};
use std::sync::Arc;
use std::time::Duration;

use anyhow::bail;
use async_trait::async_trait;
use lifecycle::Handle;
use metrics::{counter, gauge};
use tracing::{error, info, warn};

use super::positions::{InputGroups, InputTopic, PositionsError, ResumeOffset};
use super::split::{Role, SplitClaim};
use super::stamp::{CommitStamp, Stamp};
use super::PartitionOwnership;
use crate::observability::metrics::{OWNERSHIP_FENCE_BLOCKED, OWNERSHIP_FENCE_VIOLATIONS_TOTAL};
use crate::store::durability::recovery::{RETRY_MAX, RETRY_START};
use crate::sweep::Sweeper;

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

    fn carries(&self, partition: u16, split: PartitionOwnership) -> bool {
        self.commits.get(&partition).and_then(Committed::stamp) == Some(&Stamp::Split(split))
    }
}

/// The last commits on a set of partitions, on every enabled group.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CommitLedger {
    /// Every pod reads the events group, so it alone says whether another split still runs and
    /// whether a takeover finished. A follower group can be enabled after a reshard, with stamps
    /// that an older split left.
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

    /// The fence decision, over a ledger that holds `claim`'s partitions and, for a child, its
    /// parent's partitions in the new split.
    ///
    /// - Every stamp on an owned partition passes [`Self::check_stamps`].
    /// - A child takes over only once its parent has stamped one of its own partitions under the
    ///   new split. A StatefulSet runs one pod per ordinal, so no process runs the old split at the
    ///   parent's ordinal after that.
    /// - A child with its own split on any events partition finished its takeover before, because
    ///   only its claim and its later commits write that stamp. An offset reset removes the stamp
    ///   from a partition, so the rule cannot require it on every partition.
    fn admit(&self, claim: &SplitClaim) -> Result<StoreSource, FenceBlock> {
        self.check_stamps(claim)?;
        let ownership = claim.ownership();
        let Role::Child { parent, parent_now } = claim.role() else {
            return Ok(StoreSource::Own);
        };
        if ownership
            .partitions()
            .any(|partition| self.events.carries(partition, ownership))
        {
            Ok(StoreSource::Own)
        } else if parent_now
            .partitions()
            .any(|partition| self.events.carries(partition, parent_now))
        {
            Ok(StoreSource::TakeOver { parent })
        } else {
            Err(FenceBlock::ParentRunning { parent })
        }
    }

    /// Refuses a stamp on an owned partition that `claim` does not accept. An owned partition may
    /// carry no stamp, this pod's split, or during a reshard the parent's. An unstamped commit
    /// passes in every role, because older builds and standard Kafka tools write none. A follower
    /// partition may also carry any split that covers this pod, because a pod of that split that
    /// still runs also commits the events group.
    fn check_stamps(&self, claim: &SplitClaim) -> Result<(), FenceBlock> {
        let ownership = claim.ownership();
        let parent = match claim.role() {
            Role::Steady => None,
            Role::Parent { parent } | Role::Child { parent, .. } => Some(parent),
        };
        let events = self.events.topic();
        for (topic, partition, stamp) in self.stamps() {
            if !ownership.owns(partition) {
                continue;
            }
            match stamp {
                Stamp::Unstamped => {}
                Stamp::Split(found) if *found == ownership || Some(*found) == parent => {}
                Stamp::Split(found) if topic != events && found.covers(&ownership) => {}
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

    /// The claim's read-back: every partition of the ledger carries `ownership`'s stamp.
    fn confirm(&self, ownership: PartitionOwnership) -> anyhow::Result<()> {
        let ours = Stamp::Split(ownership);
        for input in self.inputs() {
            let topic = input.topic();
            for (&partition, committed) in input.commits() {
                match committed.stamp() {
                    Some(found) if *found == ours => {}
                    Some(found @ (Stamp::Split(_) | Stamp::Unrecognized(_))) => bail!(
                        "{topic} partition {partition} read back {found} after this pod stamped \
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
        Ok(())
    }
}

/// Where an admitted pod's store comes from.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum StoreSource {
    /// The live store, or this pod's own checkpoint lineage.
    Own,
    /// A reshard child takes its partitions over from `parent`, which advanced them. A live store
    /// without a pending restore is discarded, then `parent`'s checkpoint lineage is restored, or
    /// the store is created.
    TakeOver { parent: PartitionOwnership },
}

/// Why the fence holds the boot.
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum FenceBlock {
    #[error(
        "{found} committed {topic} partition {partition}: its pods may still run, or the pod count \
         changed without COHORT_RESHARD_FROM_POD_COUNT"
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
    #[error("waiting for the pod that ran {parent} to restart under the new split")]
    ParentRunning { parent: PartitionOwnership },
}

impl FenceBlock {
    const REASONS: [&'static str; 3] = ["foreign_split", "unrecognized", "parent_running"];

    fn reason(&self) -> &'static str {
        match self {
            Self::ForeignSplit { .. } => Self::REASONS[0],
            Self::Unrecognized { .. } => Self::REASONS[1],
            Self::ParentRunning { .. } => Self::REASONS[2],
        }
    }

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
/// one. The claim hands its stamp on, so the audit's revoke reaches every stamp the pod uses.
#[derive(Debug, Clone)]
pub struct AdmittedSplit {
    claim: SplitClaim,
    source: StoreSource,
    stamp: CommitStamp,
}

impl AdmittedSplit {
    /// Retries [`Self::try_admit`] with backoff until the fence admits `claim`. Each read runs on a
    /// blocking thread, so the health server keeps answering, and the pod reads not ready.
    pub async fn admit(claim: SplitClaim, groups: Arc<InputGroups>) -> Self {
        let mut backoff = RETRY_START;
        loop {
            let reader = groups.clone();
            let attempt =
                match tokio::task::spawn_blocking(move || Self::try_admit(claim, &reader)).await {
                    Ok(attempt) => attempt,
                    Err(err) => std::panic::resume_unwind(err.into_panic()),
                };
            match attempt {
                Ok(admitted) => {
                    FenceBlock::record(None);
                    info!(%claim, source = ?admitted.source, "the ownership fence admitted this pod");
                    return admitted;
                }
                Err(FenceError::Blocked(block)) => {
                    FenceBlock::record(Some(&block));
                    warn!(
                        %claim,
                        %block,
                        retry_in_secs = backoff.as_secs(),
                        "the ownership fence holds the boot",
                    );
                }
                Err(FenceError::Ledger(err)) => warn!(
                    %claim,
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
    pub fn try_admit(claim: SplitClaim, groups: &InputGroups) -> Result<Self, FenceError> {
        let parent_now = match claim.role() {
            Role::Child { parent_now, .. } => Some(parent_now),
            Role::Steady | Role::Parent { .. } => None,
        };
        let partitions: BTreeSet<u16> = claim
            .ownership()
            .partitions()
            .chain(parent_now.iter().flat_map(PartitionOwnership::partitions))
            .collect();
        let source = groups.ledger(&partitions)?.admit(&claim)?;
        Ok(Self {
            claim,
            source,
            stamp: CommitStamp::new(claim.ownership()),
        })
    }

    pub fn ownership(&self) -> PartitionOwnership {
        self.claim.ownership()
    }

    /// The split the fence admitted, with its place in a reshard.
    pub fn split_claim(&self) -> SplitClaim {
        self.claim
    }

    pub fn source(&self) -> StoreSource {
        self.source
    }

    pub fn stamp(&self) -> CommitStamp {
        self.stamp.clone()
    }

    /// Checks the stamps on the owned partitions again, then commits every owned partition on every
    /// group again with this pod's stamp, at the group's commit or at the low watermark where the
    /// group never committed, and reads the stamps back. Run it after the store opens: a child that
    /// stops before its claim still reads as its parent's, so the next boot takes over again.
    /// Blocks on Kafka.
    pub fn claim(self, groups: &InputGroups) -> anyhow::Result<ClaimedSplit> {
        let ownership = self.ownership();
        let partitions: BTreeSet<u16> = ownership.partitions().collect();
        // Another split can claim while this pod opens its store, so the claim checks the fence
        // again first. Commits have no compare-and-set: a commit between this read and the
        // restamp is overwritten, and only the audit can catch it.
        let ledger = groups.ledger(&partitions)?;
        ledger.check_stamps(&self.claim)?;
        groups.restamp(&self.stamp, &ledger)?;
        groups.ledger(&partitions)?.confirm(ownership)?;
        info!(%ownership, "claimed every owned partition; the stamps read back");
        Ok(ClaimedSplit(self.stamp))
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

    fn claim(pods: u16, ordinal: u16, reshard_from: Option<u16>) -> SplitClaim {
        SplitClaim::new(
            split(pods, ordinal),
            reshard_from.map(|from| NonZeroU16::new(from).unwrap()),
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
    fn the_fence_admits_a_split_only_over_its_own_its_ancestors_or_no_stamps() {
        let unstamped = || Some(Stamp::Unstamped);
        let unreadable = || Some(Stamp::Unrecognized("other-tool".to_owned()));
        type Row = (
            &'static str,
            SplitClaim,
            [Option<Stamp>; 4],
            [Option<Stamp>; 4],
            Result<StoreSource, FenceBlock>,
        );
        let rows: Vec<Row> = vec![
            (
                "unreadable metadata blocks any role",
                claim(1, 0, None),
                [by(1, 0), by(1, 0), unreadable(), by(1, 0)],
                [by(1, 0), by(1, 0), by(1, 0), by(1, 0)],
                Err(FenceBlock::Unrecognized {
                    topic: InputTopic::new(EVENTS),
                    partition: 2,
                    metadata: "other-tool".to_owned(),
                }),
            ),
            (
                "steady over its own stamps, none, and partitions never committed",
                claim(2, 1, None),
                [by(2, 0), by(2, 1), by(2, 0), unstamped()],
                [None, by(2, 1), None, None],
                Ok(StoreSource::Own),
            ),
            (
                "steady over another split: the pod count changed without a reshard",
                claim(2, 1, None),
                [by(2, 0), by(1, 0), by(2, 0), by(1, 0)],
                [by(2, 0), by(1, 0), by(2, 0), by(1, 0)],
                Err(FenceBlock::ForeignSplit {
                    topic: InputTopic::new(EVENTS),
                    partition: 1,
                    found: split(1, 0),
                }),
            ),
            (
                "steady over a follower that was off through a reshard",
                claim(2, 1, None),
                [by(2, 0), by(2, 1), by(2, 0), by(2, 1)],
                [by(1, 0), by(1, 0), by(1, 0), by(1, 0)],
                Ok(StoreSource::Own),
            ),
            (
                "parent over its own, its old split's and no stamps",
                claim(2, 0, Some(1)),
                [by(2, 0), by(1, 0), unstamped(), by(1, 0)],
                [by(1, 0), by(1, 0), by(1, 0), by(1, 0)],
                Ok(StoreSource::Own),
            ),
            (
                "parent over another split",
                claim(2, 0, Some(1)),
                [by(4, 0), by(1, 0), by(2, 0), by(1, 0)],
                [by(1, 0), by(1, 0), by(1, 0), by(1, 0)],
                Err(FenceBlock::ForeignSplit {
                    topic: InputTopic::new(EVENTS),
                    partition: 0,
                    found: split(4, 0),
                }),
            ),
            (
                "child with its split on an events partition finished its takeover, though an \
                 offset reset removed it from another",
                claim(2, 1, Some(1)),
                [by(2, 0), by(2, 1), by(2, 0), unstamped()],
                [by(1, 0), by(1, 0), by(1, 0), unstamped()],
                Ok(StoreSource::Own),
            ),
            (
                "child takes over once its parent stamped under the new split",
                claim(2, 1, Some(1)),
                [by(2, 0), unstamped(), by(1, 0), by(1, 0)],
                [by(2, 0), by(1, 0), by(1, 0), by(1, 0)],
                Ok(StoreSource::TakeOver {
                    parent: split(1, 0),
                }),
            ),
            (
                "child waits while its parent has not restarted",
                claim(2, 1, Some(1)),
                [by(1, 0), unstamped(), by(1, 0), None],
                [by(1, 0), by(1, 0), by(2, 0), by(1, 0)],
                Err(FenceBlock::ParentRunning {
                    parent: split(1, 0),
                }),
            ),
            (
                "child over another split",
                claim(2, 1, Some(1)),
                [by(2, 0), by(1, 0), by(2, 0), by(1, 0)],
                [by(2, 0), by(1, 0), by(2, 0), by(4, 3)],
                Err(FenceBlock::ForeignSplit {
                    topic: InputTopic::new(MERGES),
                    partition: 3,
                    found: split(4, 3),
                }),
            ),
        ];
        for (name, claim, events, merges, expected) in rows {
            let ledger = CommitLedger::new(commits(EVENTS, events), vec![commits(MERGES, merges)]);
            assert_eq!(ledger.admit(&claim), expected, "{name}");
        }
    }

    #[test]
    fn the_claim_confirms_only_its_own_stamp_on_every_partition() {
        let ours = || by(1, 0);
        let rows = [
            ("every partition reads back its stamp", ours(), true),
            (
                "the broker drops commit metadata",
                Some(Stamp::Unstamped),
                false,
            ),
            ("the restamp left a partition uncommitted", None, false),
            ("another split committed during the claim", by(2, 0), false),
        ];
        for (name, read_back, confirmed) in rows {
            let ledger = CommitLedger::new(
                commits(EVENTS, [ours(), ours(), ours(), ours()]),
                vec![commits(MERGES, [ours(), ours(), read_back, ours()])],
            );
            assert_eq!(ledger.confirm(split(1, 0)).is_ok(), confirmed, "{name}");
        }
    }
}
