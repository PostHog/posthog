//! The commit sentinel: a cheap assert that issued commits only ever move a
//! partition forward, plus out-of-band verification that they land.
//!
//! Contiguity is constructed by the ledger, so the sentinel no longer has to
//! detect gaps; it checks monotonicity per partition and compares what this
//! process attempted with what the broker reports as the group's committed
//! offset. The comparison is out of band because commits use
//! `CommitMode::Async` and librdkafka silently drops the result of manual
//! async commits (no conf-level `offset_commit_cb` is ever registered by
//! rust-rdkafka, so `ConsumerContext::commit_callback` never fires for them).
//! The loop's commit monitor task fetches the broker's committed offsets and
//! feeds them to [`CommitSentinel::observe_broker_committed`].

use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use std::time::{SystemTime, UNIX_EPOCH};

use metrics::{counter, gauge};
use tracing::warn;

use crate::metrics as names;
use crate::types::{Offset, Partition};

/// How an issue violated monotonicity.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum CommitViolationKind {
    /// The issued offset is below the previous issue: the commit moves the
    /// partition backwards.
    Backwards,
    /// The issued offset equals the previous issue: the commit manager
    /// issued without an advance.
    Repeat,
}

impl CommitViolationKind {
    fn as_str(&self) -> &'static str {
        match self {
            CommitViolationKind::Backwards => "backwards",
            CommitViolationKind::Repeat => "repeat",
        }
    }
}

/// One detected violation, returned for tests and logged.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct CommitViolation {
    pub kind: CommitViolationKind,
    pub partition: Partition,
    /// The offset previously issued for the partition.
    pub previous: Offset,
    pub issued: Offset,
}

/// Per-partition commit tracking: what this process asked Kafka to commit
/// (attempted) and what the broker has confirmed as the group's committed
/// offset (observed by the commit monitor via OffsetFetch).
#[derive(Default, Clone, Copy)]
struct PartitionCommits {
    attempted: Option<Offset>,
    confirmed: Option<Offset>,
}

pub struct CommitSentinel {
    partitions: Mutex<HashMap<Partition, PartitionCommits>>,
    /// Kill switch. When off, checks no-op and no state accumulates.
    enabled: AtomicBool,
    group: String,
}

impl CommitSentinel {
    pub fn new(group: impl Into<String>) -> CommitSentinel {
        CommitSentinel {
            partitions: Mutex::new(HashMap::new()),
            enabled: AtomicBool::new(true),
            group: group.into(),
        }
    }

    pub fn set_enabled(&self, enabled: bool) {
        self.enabled.store(enabled, Ordering::Relaxed);
    }

    /// Check one issued batch of `(partition, next offset)` pairs against the
    /// previous issue per partition, then record it as attempted. The first
    /// issue after a partition is (re)assigned baselines and is never a
    /// violation.
    pub fn check_issue(&self, batch: &[(Partition, Offset)]) -> Vec<CommitViolation> {
        if !self.enabled.load(Ordering::Relaxed) {
            return Vec::new();
        }
        let mut partitions = self.partitions.lock().unwrap();
        let mut violations = Vec::new();

        for (partition, issued) in batch {
            counter!(names::COMMITS_CHECKED_TOTAL, names::GROUP_LABEL => self.group.clone())
                .increment(1);
            let state = partitions.entry(*partition).or_default();
            if let Some(previous) = state.attempted {
                let kind = if *issued < previous {
                    Some(CommitViolationKind::Backwards)
                } else if *issued == previous {
                    Some(CommitViolationKind::Repeat)
                } else {
                    None
                };
                if let Some(kind) = kind {
                    counter!(
                        names::COMMIT_VIOLATIONS_TOTAL,
                        names::GROUP_LABEL => self.group.clone(),
                        "kind" => kind.as_str(),
                    )
                    .increment(1);
                    warn!(
                        kind = kind.as_str(),
                        partition = partition.0,
                        previous = previous.0,
                        issued = issued.0,
                        "Commit order violation"
                    );
                    violations.push(CommitViolation {
                        kind,
                        partition: *partition,
                        previous,
                        issued: *issued,
                    });
                }
            }
            state.attempted = Some(*issued);
            gauge!(
                names::COMMITTED_OFFSET,
                names::GROUP_LABEL => self.group.clone(),
                "partition" => partition.to_string(),
            )
            .set(issued.0 as f64);
        }

        violations
    }

    /// Feed broker-confirmed committed offsets (from an OffsetFetch of the
    /// group's assigned partitions) and compare against what this process
    /// attempted. Returns true when commits verifiably progressed since the
    /// last observation — the broker offset advanced, or everything attempted
    /// is confirmed — and stamps the last-successful-commit gauge.
    pub fn observe_broker_committed(
        &self,
        observed: impl IntoIterator<Item = (Partition, Offset)>,
    ) -> bool {
        if !self.enabled.load(Ordering::Relaxed) {
            return false;
        }
        let mut partitions = self.partitions.lock().unwrap();
        let mut advanced = false;

        for (partition, committed) in observed {
            gauge!(
                names::BROKER_COMMITTED_OFFSET,
                names::GROUP_LABEL => self.group.clone(),
                "partition" => partition.to_string(),
            )
            .set(committed.0 as f64);

            let state = partitions.entry(partition).or_default();
            if let Some(attempted) = state.attempted {
                gauge!(
                    names::COMMIT_CONFIRMATION_LAG,
                    names::GROUP_LABEL => self.group.clone(),
                    "partition" => partition.to_string(),
                )
                .set((attempted.0 - committed.0).max(0) as f64);
            }
            // Only an increase over a *previous* observation counts as
            // progress — the first poll baselines (the broker may be reporting
            // a prior incarnation's commits, which say nothing about ours).
            if state.confirmed.is_some_and(|prev| committed > prev) {
                advanced = true;
            }
            state.confirmed = Some(committed);
        }

        let all_confirmed = {
            let attempted_any = partitions.values().any(|s| s.attempted.is_some());
            attempted_any
                && partitions.values().all(|s| match s.attempted {
                    Some(attempted) => s.confirmed.is_some_and(|c| c >= attempted),
                    None => true,
                })
        };

        let progressed = advanced || all_confirmed;
        if progressed {
            gauge!(
                names::LAST_SUCCESSFUL_COMMIT_TIMESTAMP_SECONDS,
                names::GROUP_LABEL => self.group.clone(),
            )
            .set(
                SystemTime::now()
                    .duration_since(UNIX_EPOCH)
                    .unwrap_or_default()
                    .as_secs_f64(),
            );
        }
        progressed
    }

    /// Drop the baselines for revoked partitions so the next issue after a
    /// re-assignment baselines instead of reporting a false violation
    /// (another group member may have committed in between).
    pub fn forget(&self, revoked: impl IntoIterator<Item = Partition>) {
        let mut partitions = self.partitions.lock().unwrap();
        for partition in revoked {
            partitions.remove(&partition);
        }
    }

    /// Every partition's last attempted offset: what a final synchronous
    /// commit at shutdown re-submits.
    pub fn attempted(&self) -> Vec<(Partition, Offset)> {
        let partitions = self.partitions.lock().unwrap();
        let mut attempted: Vec<(Partition, Offset)> = partitions
            .iter()
            .filter_map(|(p, s)| s.attempted.map(|o| (*p, o)))
            .collect();
        attempted.sort();
        attempted
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn issue(p: i32, o: i64) -> (Partition, Offset) {
        (Partition(p), Offset(o))
    }

    #[test]
    fn monotone_issues_pass_and_the_first_issue_baselines() {
        let sentinel = CommitSentinel::new("g");
        assert!(sentinel.check_issue(&[issue(0, 100)]).is_empty());
        assert!(sentinel
            .check_issue(&[issue(0, 150), issue(1, 7)])
            .is_empty());
    }

    #[test]
    fn backwards_and_repeat_issues_are_violations() {
        let sentinel = CommitSentinel::new("g");
        sentinel.check_issue(&[issue(0, 100)]);
        let violations = sentinel.check_issue(&[issue(0, 100)]);
        assert_eq!(violations[0].kind, CommitViolationKind::Repeat);
        let violations = sentinel.check_issue(&[issue(0, 90)]);
        assert_eq!(
            violations,
            vec![CommitViolation {
                kind: CommitViolationKind::Backwards,
                partition: Partition(0),
                previous: Offset(100),
                issued: Offset(90),
            }]
        );
    }

    #[test]
    fn forgetting_a_partition_rebaselines_it() {
        let sentinel = CommitSentinel::new("g");
        sentinel.check_issue(&[issue(0, 100)]);
        sentinel.forget([Partition(0)]);
        assert!(sentinel.check_issue(&[issue(0, 5)]).is_empty());
    }

    #[test]
    fn broker_observation_reports_progress_only_after_a_baseline() {
        let sentinel = CommitSentinel::new("g");
        sentinel.check_issue(&[issue(0, 100)]);
        assert!(
            !sentinel.observe_broker_committed([issue(0, 50)]),
            "first observation baselines"
        );
        assert!(sentinel.observe_broker_committed([issue(0, 80)]));
        assert!(
            sentinel.observe_broker_committed([issue(0, 100)]),
            "everything attempted is confirmed"
        );
    }

    #[test]
    fn attempted_lists_every_partition_for_the_final_commit() {
        let sentinel = CommitSentinel::new("g");
        sentinel.check_issue(&[issue(3, 30), issue(1, 10)]);
        sentinel.check_issue(&[issue(1, 12)]);
        assert_eq!(sentinel.attempted(), vec![issue(1, 12), issue(3, 30)]);
    }

    #[test]
    fn disabled_sentinel_checks_nothing() {
        let sentinel = CommitSentinel::new("g");
        sentinel.set_enabled(false);
        sentinel.check_issue(&[issue(0, 100)]);
        assert!(sentinel.check_issue(&[issue(0, 1)]).is_empty());
        assert!(sentinel.attempted().is_empty());
    }
}
