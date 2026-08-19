use std::collections::HashMap;

use crate::hash::jump_consistent_hash;

use super::{AssignmentStrategy, Member};

/// Assigns partitions using jump consistent hash.
///
/// Stateless and deterministic: ignores current assignments and recomputes
/// from scratch every time. Good for initial deployment or when you want
/// reproducible, hash-based placement.
///
/// Ignores placement policies — hash placement has no notion of holding or
/// capping a member, so rollout-aware callers should prefer the sticky
/// strategy.
///
/// Minimal disruption property: when going from N to N+1 pods, only ~1/(N+1)
/// of partitions change owners.
pub struct JumpHashStrategy;

impl AssignmentStrategy for JumpHashStrategy {
    fn compute_assignments(
        &self,
        _current: &HashMap<u32, String>,
        members: &[Member],
        num_partitions: u32,
    ) -> HashMap<u32, String> {
        if members.is_empty() {
            return HashMap::new();
        }

        let num_pods = members.len() as i32;
        let mut assignments = HashMap::with_capacity(num_partitions as usize);

        for partition in 0..num_partitions {
            let pod_index = jump_consistent_hash(partition as u64, num_pods);
            assignments.insert(partition, members[pod_index as usize].name.clone());
        }

        assignments
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_pods() {
        let strategy = JumpHashStrategy;
        let result = strategy.compute_assignments(&HashMap::new(), &[], 16);
        assert!(result.is_empty());
    }

    #[test]
    fn single_pod() {
        let strategy = JumpHashStrategy;
        let pods = Member::active_all(&["pod-0"]);
        let result = strategy.compute_assignments(&HashMap::new(), &pods, 16);
        assert_eq!(result.len(), 16);
        for owner in result.values() {
            assert_eq!(owner, "pod-0");
        }
    }

    #[test]
    fn two_pods_balanced() {
        let strategy = JumpHashStrategy;
        let pods = Member::active_all(&["pod-0", "pod-1"]);
        let result = strategy.compute_assignments(&HashMap::new(), &pods, 16);
        assert_eq!(result.len(), 16);
        let pod0 = result.values().filter(|v| v.as_str() == "pod-0").count();
        let pod1 = result.values().filter(|v| v.as_str() == "pod-1").count();
        assert!(pod0 > 0 && pod1 > 0);
        assert_eq!(pod0 + pod1, 16);
    }

    #[test]
    fn ignores_current_assignments() {
        let strategy = JumpHashStrategy;
        let pods = Member::active_all(&["pod-0", "pod-1"]);
        let mut current = HashMap::new();
        for p in 0..16 {
            current.insert(p, "pod-0".to_string());
        }
        let result = strategy.compute_assignments(&current, &pods, 16);
        let pod1 = result.values().filter(|v| v.as_str() == "pod-1").count();
        assert!(pod1 > 0, "jump hash should ignore current and recompute");
    }

    #[test]
    fn deterministic() {
        let strategy = JumpHashStrategy;
        let pods = Member::active_all(&["pod-0", "pod-1", "pod-2"]);
        let a = strategy.compute_assignments(&HashMap::new(), &pods, 16);
        let b = strategy.compute_assignments(&HashMap::new(), &pods, 16);
        assert_eq!(a, b);
    }
}
