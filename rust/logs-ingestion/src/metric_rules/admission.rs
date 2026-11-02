//! `MetricSeriesAdmission` from `tally.ts`.

use std::collections::{HashMap, HashSet};

use hmac::{Hmac, Mac};
use rand::RngCore;
use sha2::Sha256;

use super::tally::MAX_LABEL_SETS_PER_RULE;

const SERIES_WINDOW_MS: f64 = 60.0 * 60.0 * 1000.0;

pub const MAX_ADMITTED_LABEL_SETS_PER_TEAM: usize = 5_000;
pub const MAX_ADMITTED_LABEL_SETS: usize = 500_000;

/// Bounds the label sets each rule admits per hour in this process. Batch tallies start empty,
/// so without this bound a rule whose labels change every batch stores new series without limit.
#[derive(Debug, Clone)]
pub struct MetricSeriesAdmission {
    max_per_rule: usize,
    max_per_team: usize,
    max_total: usize,
    /// A random key per process. A team cannot then make colliding labels offline, so a
    /// collision cannot admit label sets past the cap.
    hash_key: [u8; 32],
    window: f64,
    admitted: HashMap<String, HashSet<u64>>,
    // Counts stay after a rule is deleted until the hour changes, so rule churn cannot reset a budget.
    admitted_by_team: HashMap<i64, usize>,
    admitted_total: usize,
}

impl Default for MetricSeriesAdmission {
    fn default() -> Self {
        Self::new(
            MAX_LABEL_SETS_PER_RULE,
            MAX_ADMITTED_LABEL_SETS_PER_TEAM,
            MAX_ADMITTED_LABEL_SETS,
        )
    }
}

impl MetricSeriesAdmission {
    pub fn new(max_per_rule: usize, max_per_team: usize, max_total: usize) -> Self {
        let mut hash_key = [0u8; 32];
        rand::thread_rng().fill_bytes(&mut hash_key);
        Self::with_hash_key(max_per_rule, max_per_team, max_total, hash_key)
    }

    pub fn with_hash_key(
        max_per_rule: usize,
        max_per_team: usize,
        max_total: usize,
        hash_key: [u8; 32],
    ) -> Self {
        Self {
            max_per_rule,
            max_per_team,
            max_total,
            hash_key,
            window: -1.0,
            admitted: HashMap::new(),
            admitted_by_team: HashMap::new(),
            admitted_total: 0,
        }
    }

    pub fn hash_label_key(&self, label_key: &str) -> u64 {
        let mut mac =
            Hmac::<Sha256>::new_from_slice(&self.hash_key).expect("HMAC takes any key length");
        mac.update(label_key.as_bytes());
        let digest = mac.finalize().into_bytes();
        digest[..6]
            .iter()
            .fold(0u64, |acc, b| (acc << 8) | u64::from(*b))
    }

    pub fn admit(&mut self, team_id: i64, rule_id: &str, label_key: &str, now_ms: f64) -> bool {
        let window = (now_ms / SERIES_WINDOW_MS).floor();
        if window != self.window {
            self.admitted.clear();
            self.admitted_by_team.clear();
            self.admitted_total = 0;
            self.window = window;
        }
        let key = format!("{team_id}:{rule_id}");
        let label_hash = self.hash_label_key(label_key);
        let rule_size = match self.admitted.get(&key) {
            Some(hashes) if hashes.contains(&label_hash) => return true,
            Some(hashes) => hashes.len(),
            None => 0,
        };
        let team_admitted = self.admitted_by_team.get(&team_id).copied().unwrap_or(0);
        if rule_size >= self.max_per_rule
            || team_admitted >= self.max_per_team
            || self.admitted_total >= self.max_total
        {
            return false;
        }
        self.admitted.entry(key).or_default().insert(label_hash);
        self.admitted_by_team.insert(team_id, team_admitted + 1);
        self.admitted_total += 1;
        true
    }
}
