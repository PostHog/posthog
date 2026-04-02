use std::collections::BTreeMap;

use crate::types::{Partition, PodId};

/// Jump consistent hash: maps a key to one of `num_buckets` buckets.
///
/// Copied from personhog-coordination. Deterministic, minimal-disruption:
/// when scaling N -> N+1, only ~1/(N+1) of keys move.
///
/// Reference: Lamping & Veach, "A Fast, Minimal Memory, Consistent Hash Algorithm"
fn jump_consistent_hash(key: u64, num_buckets: i32) -> i32 {
    assert!(num_buckets > 0, "num_buckets must be positive");

    let mut k = key;
    let mut b: i64 = -1;
    let mut j: i64 = 0;

    while j < num_buckets as i64 {
        b = j;
        k = k.wrapping_mul(2862933555777941757).wrapping_add(1);
        j = ((b.wrapping_add(1) as f64) * (f64::from(1u32 << 31))
            / (((k >> 33).wrapping_add(1)) as f64)) as i64;
    }

    b as i32
}

/// Compute partition-to-pod assignments using jump consistent hash.
///
/// `active_pods` must be sorted for deterministic results.
pub fn compute_assignments(
    active_pods: &[PodId],
    num_partitions: Partition,
) -> BTreeMap<Partition, PodId> {
    if active_pods.is_empty() {
        return BTreeMap::new();
    }

    let num_pods = active_pods.len() as i32;
    let mut assignments = BTreeMap::new();

    for partition in 0..num_partitions {
        let pod_index = jump_consistent_hash(partition as u64, num_pods);
        assignments.insert(partition, active_pods[pod_index as usize]);
    }

    assignments
}

/// Compute which partitions need to move between old and new assignments.
/// Returns (partition, old_owner, new_owner) triples.
pub fn compute_required_handoffs(
    current: &BTreeMap<Partition, PodId>,
    desired: &BTreeMap<Partition, PodId>,
) -> Vec<(Partition, PodId, PodId)> {
    let mut handoffs = Vec::new();

    for (partition, new_owner) in desired {
        if let Some(old_owner) = current.get(partition) {
            if old_owner != new_owner {
                handoffs.push((*partition, *old_owner, *new_owner));
            }
        }
    }

    handoffs
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn single_pod_gets_all_partitions() {
        let assignments = compute_assignments(&[0], 4);
        assert_eq!(assignments.len(), 4);
        for owner in assignments.values() {
            assert_eq!(*owner, 0);
        }
    }

    #[test]
    fn two_pods_balanced() {
        let assignments = compute_assignments(&[0, 1], 16);
        let pod0 = assignments.values().filter(|&&v| v == 0).count();
        let pod1 = assignments.values().filter(|&&v| v == 1).count();
        assert!(pod0 > 0 && pod1 > 0);
        assert_eq!(pod0 + pod1, 16);
    }

    #[test]
    fn deterministic() {
        let a = compute_assignments(&[0, 1, 2], 8);
        let b = compute_assignments(&[0, 1, 2], 8);
        assert_eq!(a, b);
    }

    #[test]
    fn handoffs_detected() {
        let old = compute_assignments(&[0, 1], 8);
        let new = compute_assignments(&[0, 1, 2], 8);
        let handoffs = compute_required_handoffs(&old, &new);
        assert!(!handoffs.is_empty());
        for (_, old_owner, new_owner) in &handoffs {
            assert_ne!(old_owner, new_owner);
        }
    }
}
