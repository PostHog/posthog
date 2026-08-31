use std::collections::HashMap;
use std::time::{Duration, Instant};

use crate::charge::Charge;
use crate::types::{Advance, DrainHarvest, Offset, Partition};

/// The injected commit issue: the caller commits `(partition, next offset)`
/// pairs, async and fire-and-forget, and never blocks the loop.
pub type IssueCommit<'a> = dyn FnMut(&[(Partition, Offset)]) + 'a;

/// The whole commit policy behind three calls: `progress` on every frontier
/// advance, `tick` from the loop's housekeeping tick, and `finish_revoke` for
/// a drain's end. When and how to issue — delay, batching — is this
/// component's algorithm and appears nowhere else. Budget refunds return from
/// whichever call issues, keeping `B` = polled minus committed exact.
#[derive(Debug)]
pub struct CommitManager {
    /// Latest unissued frontier plus the charge tally behind it.
    pending: HashMap<Partition, PendingAdvance>,
    last_issue: Option<Instant>,
    interval: Duration,
}

#[derive(Debug)]
struct PendingAdvance {
    frontier: Offset,
    charge: Charge,
}

impl CommitManager {
    pub fn new(interval: Duration) -> CommitManager {
        CommitManager {
            pending: HashMap::new(),
            last_issue: None,
            interval,
        }
    }

    /// Called on every completion that moved a frontier; whether to issue now
    /// is this component's decision, nobody else's.
    pub fn progress(
        &mut self,
        advances: Vec<Advance>,
        now: Instant,
        issue: &mut IssueCommit<'_>,
    ) -> Charge {
        for a in advances {
            let entry = self.pending.entry(a.partition).or_insert(PendingAdvance {
                frontier: a.frontier,
                charge: Charge::ZERO,
            });
            entry.frontier = entry.frontier.max(a.frontier);
            entry.charge += a.charge;
        }
        self.maybe_issue(now, issue)
    }

    /// The clock: issue if the delay is up.
    pub fn tick(&mut self, now: Instant, issue: &mut IssueCommit<'_>) -> Charge {
        self.maybe_issue(now, issue)
    }

    /// The drain's end: issue the partition's final frontier NOW — the
    /// rebalance is waiting. Every completed span was already reported via
    /// `progress`, so the refund is the held tally plus the never-completed
    /// charge — nothing counts twice.
    pub fn finish_revoke(
        &mut self,
        harvest: DrainHarvest,
        now: Instant,
        issue: &mut IssueCommit<'_>,
    ) -> Charge {
        let held = self.pending.remove(&harvest.partition);
        if let Some(frontier) = harvest.frontier {
            self.issue(&[(harvest.partition, frontier.next())], now, issue);
        }
        held.map_or(Charge::ZERO, |h| h.charge) + harvest.dropped
    }

    /// The algorithm — today: at most one batched issue per interval.
    fn maybe_issue(&mut self, now: Instant, issue: &mut IssueCommit<'_>) -> Charge {
        if self
            .last_issue
            .is_some_and(|last| now.duration_since(last) < self.interval)
        {
            return Charge::ZERO;
        }
        if self.pending.is_empty() {
            return Charge::ZERO;
        }
        let batch: Vec<(Partition, Offset)> = self
            .pending
            .iter()
            .map(|(p, a)| (*p, a.frontier.next()))
            .collect();
        let refund = self.pending.drain().map(|(_, a)| a.charge).sum();
        self.issue(&batch, now, issue);
        refund
    }

    fn issue(&mut self, batch: &[(Partition, Offset)], now: Instant, issue: &mut IssueCommit<'_>) {
        issue(batch);
        self.last_issue = Some(now);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const INTERVAL: Duration = Duration::from_secs(5);

    fn advance(p: i32, frontier: i64, events: u64) -> Advance {
        Advance {
            partition: Partition(p),
            frontier: Offset(frontier),
            charge: Charge { events, bytes: 0 },
        }
    }

    #[test]
    fn at_most_one_batched_issue_per_interval() {
        let now = Instant::now();
        let mut commits = CommitManager::new(INTERVAL);
        let mut issued: Vec<Vec<(Partition, Offset)>> = vec![];

        // The first advance issues immediately (nothing issued yet).
        let refund = commits.progress(vec![advance(0, 3, 4)], now, &mut |b| {
            issued.push(b.to_vec())
        });
        assert_eq!(issued, vec![vec![(Partition(0), Offset(4))]]);
        assert_eq!(
            refund,
            Charge {
                events: 4,
                bytes: 0
            }
        );

        // More advances inside the interval accumulate instead of issuing.
        let refund = commits.progress(
            vec![advance(0, 7, 4), advance(1, 1, 2)],
            now + Duration::from_secs(1),
            &mut |b| issued.push(b.to_vec()),
        );
        assert_eq!(issued.len(), 1);
        assert_eq!(refund, Charge::ZERO);

        // The tick past the interval issues both frontiers, one batch.
        let refund = commits.tick(now + INTERVAL, &mut |b| issued.push(b.to_vec()));
        assert_eq!(
            refund,
            Charge {
                events: 6,
                bytes: 0
            }
        );
        let mut batch = issued[1].clone();
        batch.sort();
        assert_eq!(
            batch,
            vec![(Partition(0), Offset(8)), (Partition(1), Offset(2))]
        );

        // Nothing pending: the next tick stays quiet.
        assert_eq!(
            commits.tick(now + INTERVAL * 2, &mut |b| issued.push(b.to_vec())),
            Charge::ZERO
        );
        assert_eq!(issued.len(), 2);
    }

    #[test]
    fn finish_revoke_issues_immediately_and_refunds_exactly_once() {
        let now = Instant::now();
        let mut commits = CommitManager::new(INTERVAL);
        let mut issued: Vec<Vec<(Partition, Offset)>> = vec![];

        commits.progress(vec![advance(0, 2, 3)], now, &mut |b| {
            issued.push(b.to_vec())
        });
        // A second advance is still held when the drain ends.
        commits.progress(
            vec![advance(0, 5, 3)],
            now + Duration::from_secs(1),
            &mut |b| issued.push(b.to_vec()),
        );

        let refund = commits.finish_revoke(
            DrainHarvest {
                partition: Partition(0),
                frontier: Some(Offset(5)),
                dropped: Charge {
                    events: 2,
                    bytes: 0,
                },
            },
            now + Duration::from_secs(2),
            &mut |b| issued.push(b.to_vec()),
        );
        // Held tally (3) plus never-completed charge (2); the first issue's 3
        // was already refunded, so nothing counts twice.
        assert_eq!(
            refund,
            Charge {
                events: 5,
                bytes: 0
            }
        );
        assert_eq!(issued.last().unwrap(), &vec![(Partition(0), Offset(6))]);
    }

    #[test]
    fn finish_revoke_with_no_frontier_commits_nothing() {
        let now = Instant::now();
        let mut commits = CommitManager::new(INTERVAL);
        let mut issued = 0usize;

        let refund = commits.finish_revoke(
            DrainHarvest {
                partition: Partition(0),
                frontier: None,
                dropped: Charge {
                    events: 7,
                    bytes: 0,
                },
            },
            now,
            &mut |_| issued += 1,
        );
        assert_eq!(issued, 0, "nothing ever completed, nothing to commit");
        assert_eq!(
            refund,
            Charge {
                events: 7,
                bytes: 0
            }
        );
    }
}
