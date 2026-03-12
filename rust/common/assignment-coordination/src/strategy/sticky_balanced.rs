use std::collections::{HashMap, HashSet};

use super::AssignmentStrategy;

/// Assigns partitions while minimizing movement from the current state.
///
/// Keeps all existing assignments where the owning member is still active,
/// then redistributes orphaned and unassigned partitions to maintain balance
/// (each member gets within +/-1 of the ideal count). When a new member
/// joins with zero partitions, steals from the most-loaded members to
/// rebalance.
pub struct StickyBalancedStrategy;

impl AssignmentStrategy for StickyBalancedStrategy {
    fn compute_assignments(
        &self,
        current: &HashMap<u32, String>,
        active_members: &[String],
        num_partitions: u32,
    ) -> HashMap<u32, String> {
        if active_members.is_empty() {
            return HashMap::new();
        }

        let active_set: HashSet<&String> = active_members.iter().collect();
        let num_members = active_members.len();
        let target_min = num_partitions as usize / num_members;
        let extra = num_partitions as usize % num_members;

        // Step 1: Keep valid assignments
        let mut assignments: HashMap<u32, String> = current
            .iter()
            .filter(|(p, member)| **p < num_partitions && active_set.contains(member))
            .map(|(p, member)| (*p, member.clone()))
            .collect();

        // Step 2: Build per-member partition lists
        let mut member_partitions: HashMap<&String, Vec<u32>> =
            active_members.iter().map(|m| (m, Vec::new())).collect();
        for (partition, member) in &assignments {
            if let Some(parts) = member_partitions.get_mut(member) {
                parts.push(*partition);
            }
        }

        // Step 3: Collect unassigned partitions
        let mut pool: Vec<u32> = (0..num_partitions)
            .filter(|p| !assignments.contains_key(p))
            .collect();

        // Determine which members get target_min + 1 vs target_min.
        // Members that already have more partitions get priority for the +1
        // slot, to minimize movement.
        let mut members_sorted: Vec<&String> = active_members.iter().collect();
        members_sorted.sort_by(|a, b| {
            let count_a = member_partitions.get(a).map_or(0, |v| v.len());
            let count_b = member_partitions.get(b).map_or(0, |v| v.len());
            count_b.cmp(&count_a)
        });

        let mut member_targets: HashMap<&String, usize> = HashMap::new();
        for (i, member) in members_sorted.iter().enumerate() {
            let target = if i < extra {
                target_min + 1
            } else {
                target_min
            };
            member_targets.insert(member, target);
        }

        // Step 4: Strip excess from overloaded members
        for member in &members_sorted {
            let target = member_targets[member];
            let parts = member_partitions.get_mut(member).unwrap();
            if parts.len() > target {
                parts.sort();
                let excess: Vec<u32> = parts.drain(target..).collect();
                for p in &excess {
                    assignments.remove(p);
                }
                pool.extend(excess);
            }
        }

        // Step 5: Fill underloaded members from the pool (emptiest first)
        pool.sort();
        let mut pool_iter = pool.into_iter();
        members_sorted.reverse();
        for member in &members_sorted {
            let target = member_targets[member];
            let parts = member_partitions.get_mut(member).unwrap();
            while parts.len() < target {
                if let Some(partition) = pool_iter.next() {
                    parts.push(partition);
                    assignments.insert(partition, (*member).clone());
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
    fn empty_members() {
        let strategy = StickyBalancedStrategy;
        let result = strategy.compute_assignments(&HashMap::new(), &[], 16);
        assert!(result.is_empty());
    }

    #[test]
    fn initial_assignment_balanced() {
        let strategy = StickyBalancedStrategy;
        let members = vec!["m-0".to_string(), "m-1".to_string(), "m-2".to_string()];
        let result = strategy.compute_assignments(&HashMap::new(), &members, 12);
        assert_eq!(result.len(), 12);
        for m in &members {
            let count = result.values().filter(|v| *v == m).count();
            assert_eq!(count, 4, "{m} should own 4 partitions");
        }
    }

    #[test]
    fn initial_assignment_uneven() {
        let strategy = StickyBalancedStrategy;
        let members = vec!["m-0".to_string(), "m-1".to_string(), "m-2".to_string()];
        let result = strategy.compute_assignments(&HashMap::new(), &members, 10);
        assert_eq!(result.len(), 10);
        let mut counts: Vec<usize> = members
            .iter()
            .map(|m| result.values().filter(|v| *v == m).count())
            .collect();
        counts.sort();
        assert_eq!(counts, vec![3, 3, 4]);
    }

    #[test]
    fn keeps_existing_assignments() {
        let strategy = StickyBalancedStrategy;
        let members = vec!["m-0".to_string(), "m-1".to_string()];
        let mut current = HashMap::new();
        for p in 0..8 {
            current.insert(p, "m-0".to_string());
        }
        for p in 8..16 {
            current.insert(p, "m-1".to_string());
        }
        let result = strategy.compute_assignments(&current, &members, 16);
        assert_eq!(result, current);
    }

    #[test]
    fn new_member_steals_minimum() {
        let strategy = StickyBalancedStrategy;
        let mut current = HashMap::new();
        for p in 0..6 {
            current.insert(p, "m-0".to_string());
        }
        for p in 6..12 {
            current.insert(p, "m-1".to_string());
        }
        let members = vec!["m-0".to_string(), "m-1".to_string(), "m-2".to_string()];
        let result = strategy.compute_assignments(&current, &members, 12);
        assert_eq!(result.len(), 12);
        for m in &members {
            let count = result.values().filter(|v| *v == m).count();
            assert_eq!(count, 4, "{m} should own 4 partitions");
        }
        let moved = (0..12u32)
            .filter(|p| current.get(p) != result.get(p))
            .count();
        assert_eq!(moved, 4, "only 4 partitions should move to the new member");
    }

    #[test]
    fn member_dies_redistributes() {
        let strategy = StickyBalancedStrategy;
        let mut current = HashMap::new();
        for p in 0..4 {
            current.insert(p, "m-0".to_string());
        }
        for p in 4..8 {
            current.insert(p, "m-1".to_string());
        }
        for p in 8..12 {
            current.insert(p, "m-2".to_string());
        }
        let members = vec!["m-0".to_string(), "m-2".to_string()];
        let result = strategy.compute_assignments(&current, &members, 12);
        assert_eq!(result.len(), 12);
        for m in &members {
            let count = result.values().filter(|v| *v == m).count();
            assert_eq!(count, 6, "{m} should own 6 partitions");
        }
        for p in 0..4 {
            assert_eq!(result[&p], "m-0");
        }
        for p in 8..12 {
            assert_eq!(result[&p], "m-2");
        }
    }

    #[test]
    fn single_member() {
        let strategy = StickyBalancedStrategy;
        let members = vec!["m-0".to_string()];
        let result = strategy.compute_assignments(&HashMap::new(), &members, 8);
        assert_eq!(result.len(), 8);
        for owner in result.values() {
            assert_eq!(owner, "m-0");
        }
    }

    #[test]
    fn filters_dead_member_assignments() {
        let strategy = StickyBalancedStrategy;
        let mut current = HashMap::new();
        current.insert(0, "dead".to_string());
        current.insert(1, "m-0".to_string());
        let members = vec!["m-0".to_string()];
        let result = strategy.compute_assignments(&current, &members, 2);
        assert_eq!(result.len(), 2);
        assert_eq!(result[&0], "m-0");
        assert_eq!(result[&1], "m-0");
    }
}
