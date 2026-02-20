use std::collections::{HashMap, HashSet};

use super::AssignmentStrategy;

/// Assigns partitions while minimizing movement from the current state.
///
/// Keeps all existing assignments where the owning pod is still active,
/// then redistributes orphaned and unassigned partitions to maintain balance
/// (each pod gets within +/-1 of the ideal count). When a new pod joins with
/// zero partitions, steals from the most-loaded pods to rebalance.
pub struct StickyBalancedStrategy;

impl AssignmentStrategy for StickyBalancedStrategy {
    fn compute_assignments(
        &self,
        current: &HashMap<u32, String>,
        active_pods: &[String],
        num_partitions: u32,
    ) -> HashMap<u32, String> {
        if active_pods.is_empty() {
            return HashMap::new();
        }

        let active_set: HashSet<&String> = active_pods.iter().collect();
        let num_pods = active_pods.len();
        let target_min = num_partitions as usize / num_pods;
        let extra = num_partitions as usize % num_pods;
        // `extra` pods get target_min + 1, the rest get target_min

        // Step 1: Keep valid assignments
        let mut assignments: HashMap<u32, String> = current
            .iter()
            .filter(|(p, pod)| **p < num_partitions && active_set.contains(pod))
            .map(|(p, pod)| (*p, pod.clone()))
            .collect();

        // Step 2: Build per-pod partition lists
        let mut pod_partitions: HashMap<&String, Vec<u32>> =
            active_pods.iter().map(|p| (p, Vec::new())).collect();
        for (partition, pod) in &assignments {
            if let Some(parts) = pod_partitions.get_mut(pod) {
                parts.push(*partition);
            }
        }

        // Step 3: Sort pods by current load (descending) and collect excess
        let mut pool: Vec<u32> = Vec::new();

        // Collect unassigned partitions
        for partition in 0..num_partitions {
            if !assignments.contains_key(&partition) {
                pool.push(partition);
            }
        }

        // Determine which pods are allowed target_min + 1 vs target_min.
        // To minimize movement, pods that already have more partitions get
        // priority for the +1 slot.
        let mut pods_sorted: Vec<&String> = active_pods.iter().collect();
        pods_sorted.sort_by(|a, b| {
            let count_a = pod_partitions.get(a).map_or(0, |v| v.len());
            let count_b = pod_partitions.get(b).map_or(0, |v| v.len());
            count_b.cmp(&count_a)
        });

        // First `extra` pods (by current load, descending) get target_min + 1
        let mut pod_targets: HashMap<&String, usize> = HashMap::new();
        for (i, pod) in pods_sorted.iter().enumerate() {
            let target = if i < extra {
                target_min + 1
            } else {
                target_min
            };
            pod_targets.insert(pod, target);
        }

        // Step 4: Strip excess from overloaded pods
        for pod in &pods_sorted {
            let target = pod_targets[pod];
            let parts = pod_partitions.get_mut(pod).unwrap();
            if parts.len() > target {
                // Sort for deterministic eviction (evict highest-numbered partitions)
                parts.sort();
                let excess: Vec<u32> = parts.drain(target..).collect();
                for p in &excess {
                    assignments.remove(p);
                }
                pool.extend(excess);
            }
        }

        // Step 5: Fill underloaded pods from the pool
        pool.sort();
        let mut pool_iter = pool.into_iter();

        // Fill pods sorted by current load ascending (emptiest first)
        pods_sorted.reverse();
        for pod in &pods_sorted {
            let target = pod_targets[pod];
            let parts = pod_partitions.get_mut(pod).unwrap();
            while parts.len() < target {
                if let Some(partition) = pool_iter.next() {
                    parts.push(partition);
                    assignments.insert(partition, (*pod).clone());
                } else {
                    break;
                }
            }
        }

        assignments
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_pods() {
        let strategy = StickyBalancedStrategy;
        let result = strategy.compute_assignments(&HashMap::new(), &[], 16);
        assert!(result.is_empty());
    }

    #[test]
    fn initial_assignment_balanced() {
        let strategy = StickyBalancedStrategy;
        let pods = vec![
            "pod-0".to_string(),
            "pod-1".to_string(),
            "pod-2".to_string(),
        ];
        let result = strategy.compute_assignments(&HashMap::new(), &pods, 12);
        assert_eq!(result.len(), 12);

        for pod in &pods {
            let count = result.values().filter(|v| *v == pod).count();
            assert_eq!(count, 4, "{pod} should own 4 partitions");
        }
    }

    #[test]
    fn initial_assignment_uneven() {
        let strategy = StickyBalancedStrategy;
        let pods = vec![
            "pod-0".to_string(),
            "pod-1".to_string(),
            "pod-2".to_string(),
        ];
        let result = strategy.compute_assignments(&HashMap::new(), &pods, 10);
        assert_eq!(result.len(), 10);

        // 10 / 3 = 3 remainder 1, so one pod gets 4, two get 3
        let mut counts: Vec<usize> = pods
            .iter()
            .map(|pod| result.values().filter(|v| *v == pod).count())
            .collect();
        counts.sort();
        assert_eq!(counts, vec![3, 3, 4]);
    }

    #[test]
    fn keeps_existing_assignments() {
        let strategy = StickyBalancedStrategy;
        let pods = vec!["pod-0".to_string(), "pod-1".to_string()];

        let mut current = HashMap::new();
        for p in 0..8 {
            current.insert(p, "pod-0".to_string());
        }
        for p in 8..16 {
            current.insert(p, "pod-1".to_string());
        }

        let result = strategy.compute_assignments(&current, &pods, 16);
        assert_eq!(result, current);
    }

    #[test]
    fn new_pod_steals_minimum() {
        let strategy = StickyBalancedStrategy;

        let mut current = HashMap::new();
        for p in 0..6 {
            current.insert(p, "pod-0".to_string());
        }
        for p in 6..12 {
            current.insert(p, "pod-1".to_string());
        }

        let pods = vec![
            "pod-0".to_string(),
            "pod-1".to_string(),
            "pod-2".to_string(),
        ];
        let result = strategy.compute_assignments(&current, &pods, 12);
        assert_eq!(result.len(), 12);

        for pod in &pods {
            let count = result.values().filter(|v| *v == pod).count();
            assert_eq!(count, 4, "{pod} should own 4 partitions");
        }

        let moved = (0..12u32)
            .filter(|p| current.get(p) != result.get(p))
            .count();
        assert_eq!(moved, 4, "only 4 partitions should move to the new pod");
    }

    #[test]
    fn pod_dies_redistributes_its_partitions() {
        let strategy = StickyBalancedStrategy;

        let mut current = HashMap::new();
        for p in 0..4 {
            current.insert(p, "pod-0".to_string());
        }
        for p in 4..8 {
            current.insert(p, "pod-1".to_string());
        }
        for p in 8..12 {
            current.insert(p, "pod-2".to_string());
        }

        let pods = vec!["pod-0".to_string(), "pod-2".to_string()];
        let result = strategy.compute_assignments(&current, &pods, 12);
        assert_eq!(result.len(), 12);

        for pod in &pods {
            let count = result.values().filter(|v| *v == pod).count();
            assert_eq!(count, 6, "{pod} should own 6 partitions");
        }

        // Existing assignments are preserved
        for p in 0..4 {
            assert_eq!(result[&p], "pod-0", "partition {p} should stay with pod-0");
        }
        for p in 8..12 {
            assert_eq!(result[&p], "pod-2", "partition {p} should stay with pod-2");
        }
    }

    #[test]
    fn single_pod() {
        let strategy = StickyBalancedStrategy;
        let pods = vec!["pod-0".to_string()];
        let result = strategy.compute_assignments(&HashMap::new(), &pods, 8);
        assert_eq!(result.len(), 8);
        for owner in result.values() {
            assert_eq!(owner, "pod-0");
        }
    }

    #[test]
    fn filters_dead_pod_assignments() {
        let strategy = StickyBalancedStrategy;

        let mut current = HashMap::new();
        current.insert(0, "dead-pod".to_string());
        current.insert(1, "pod-0".to_string());

        let pods = vec!["pod-0".to_string()];
        let result = strategy.compute_assignments(&current, &pods, 2);
        assert_eq!(result.len(), 2);
        assert_eq!(result[&0], "pod-0");
        assert_eq!(result[&1], "pod-0");
    }
}
