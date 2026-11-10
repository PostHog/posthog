use sha2::{Digest, Sha256};
use uuid::Uuid;

use super::ledger::DayCount;

#[derive(Debug, Clone, Copy)]
pub struct ProjectRule {
    pub multiplier: f64,
    pub floor: u64,
    pub keep_percent: u8,
}

impl Default for ProjectRule {
    fn default() -> Self {
        Self {
            multiplier: 3.0,
            floor: 500,
            keep_percent: 10,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct ProjectDecision {
    pub sampled: bool,
    pub baseline: f64,
    pub allowance: u64,
    pub count: u64,
    pub cap_started: bool,
}

impl ProjectRule {
    /// Decide for the events of one batch that the per-issue rules kept.
    /// `kept_before` is today's kept count before the batch.
    pub fn evaluate(
        &self,
        team_id: i32,
        kept_before: u64,
        history: &[DayCount],
        uuids: &[Uuid],
    ) -> Vec<ProjectDecision> {
        let baseline = median_kept(history).max(self.floor as f64);
        let allowance = (self.multiplier * baseline) as u64;
        uuids
            .iter()
            .enumerate()
            .map(|(index, uuid)| {
                let count = kept_before + index as u64 + 1;
                ProjectDecision {
                    sampled: count > allowance && !keep_by_hash(team_id, *uuid, self.keep_percent),
                    baseline,
                    allowance,
                    count,
                    cap_started: allowance.checked_add(1) == Some(count),
                }
            })
            .collect()
    }
}

fn median_kept(history: &[DayCount]) -> f64 {
    if history.is_empty() {
        return 0.0;
    }
    let mut kept: Vec<u64> = history.iter().map(DayCount::kept).collect();
    kept.sort_unstable();
    let middle = kept.len() / 2;
    if kept.len().is_multiple_of(2) {
        (kept[middle - 1] as f64 + kept[middle] as f64) / 2.0
    } else {
        kept[middle] as f64
    }
}

fn keep_by_hash(team_id: i32, uuid: Uuid, percent: u8) -> bool {
    let mut hasher = Sha256::new();
    hasher.update(b"adaptive-ingestion:project:v1");
    hasher.update(team_id.to_be_bytes());
    hasher.update(uuid.as_bytes());
    let hash = hasher.finalize();
    u64::from_be_bytes(hash[0..8].try_into().expect("sha256 has 32 bytes")) % 100 < percent as u64
}

#[cfg(test)]
mod tests {
    use super::*;

    fn days(kept: &[u64]) -> Vec<DayCount> {
        kept.iter()
            .map(|events| DayCount {
                events: *events,
                removed: 0,
            })
            .collect()
    }

    #[test]
    fn daily_cap_uses_median_history_and_stable_sampling() {
        let ids = [Uuid::now_v7(), Uuid::now_v7(), Uuid::now_v7()];
        let mut history = days(&[10, 10, 10, 10, 10, 10, 50, 50, 50, 50, 50, 50, 50]);
        history.push(DayCount {
            events: 80,
            removed: 30,
        });
        let rule = ProjectRule {
            multiplier: 3.0,
            floor: 1,
            keep_percent: 0,
        };
        let first = rule.evaluate(7, 150, &history, &ids);
        assert_eq!(first, rule.evaluate(7, 150, &history, &ids));
        assert_eq!(first[0].baseline, 50.0);
        assert_eq!(first[0].allowance, 150);
        assert_eq!(first[0].count, 151);
        assert!(first[0].cap_started);
        assert!(!first[1].cap_started);
        assert!(first.iter().all(|decision| decision.sampled));

        let cold_start = ProjectRule {
            keep_percent: 0,
            ..ProjectRule::default()
        }
        .evaluate(7, 1498, &days(&[0; 14]), &ids);
        assert_eq!(cold_start[0].baseline, 500.0);
        assert_eq!(cold_start[0].allowance, 1500);
        assert!(!cold_start[1].sampled);
        assert!(cold_start[2].sampled);
    }

    #[test]
    fn sample_hash_is_stable_for_the_same_event() {
        let uuid = Uuid::from_u128(1);
        assert!(!keep_by_hash(7, uuid, 1));
        assert!(keep_by_hash(7, uuid, 10));
    }
}
