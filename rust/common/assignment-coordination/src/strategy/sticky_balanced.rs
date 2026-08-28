use std::collections::{HashMap, HashSet};

use super::{AssignmentStrategy, Member, PlacementPolicy};

/// Assigns partitions while minimizing movement from the current state.
///
/// With only uncapped active members, keeps all existing assignments where
/// the owning member is still active, then redistributes orphaned and
/// unassigned partitions to maintain balance (each member gets within +/-1
/// of the ideal count). When a new member joins with zero partitions,
/// steals from the most-loaded members to rebalance.
///
/// When any member carries a cap or a Hold policy (a Deployment rollout in
/// progress), placement switches to quota mode: capped members fill to
/// their cap — from orphaned partitions first, then by stealing from Hold
/// members — while Hold members keep whatever they cannot shed and absorb
/// overflow only when no capped member has room.
pub struct StickyBalancedStrategy;

impl AssignmentStrategy for StickyBalancedStrategy {
    fn compute_assignments(
        &self,
        current: &HashMap<u32, String>,
        members: &[Member],
        num_partitions: u32,
    ) -> HashMap<u32, String> {
        if members.is_empty() {
            return HashMap::new();
        }

        let plain = members
            .iter()
            .all(|m| m.policy == PlacementPolicy::Active { cap: None });
        if plain {
            balanced_assignments(current, members, num_partitions)
        } else {
            quota_assignments(current, members, num_partitions)
        }
    }
}

/// The classic sticky-balanced algorithm: every member keeps what it has,
/// then targets are evened out to within +/-1 of the ideal count.
fn balanced_assignments(
    current: &HashMap<u32, String>,
    members: &[Member],
    num_partitions: u32,
) -> HashMap<u32, String> {
    let active_set: HashSet<&str> = members.iter().map(|m| m.name.as_str()).collect();
    let num_members = members.len();
    let target_min = num_partitions as usize / num_members;
    let extra = num_partitions as usize % num_members;

    // Step 1: Keep valid assignments
    let mut assignments: HashMap<u32, String> = current
        .iter()
        .filter(|(p, member)| **p < num_partitions && active_set.contains(member.as_str()))
        .map(|(p, member)| (*p, member.clone()))
        .collect();

    // Step 2: Build per-member partition lists
    let mut member_partitions: HashMap<&str, Vec<u32>> = members
        .iter()
        .map(|m| (m.name.as_str(), Vec::new()))
        .collect();
    for (partition, member) in &assignments {
        if let Some(parts) = member_partitions.get_mut(member.as_str()) {
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
    let mut members_sorted: Vec<&str> = members.iter().map(|m| m.name.as_str()).collect();
    members_sorted.sort_by(|a, b| {
        let count_a = member_partitions.get(a).map_or(0, |v| v.len());
        let count_b = member_partitions.get(b).map_or(0, |v| v.len());
        count_b.cmp(&count_a)
    });

    let mut member_targets: HashMap<&str, usize> = HashMap::new();
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
                assignments.insert(partition, (*member).to_string());
            } else {
                break;
            }
        }
    }

    assignments
}

/// Rollout placement: capped active members fill to their cap, Hold
/// members shed toward them and absorb only what nobody else can take.
///
/// A cap alone never forces shedding — a member above its cap keeps its
/// partitions unless a capped sibling sits below cap, in which case the
/// excess levels toward that sibling. With everyone at or above cap,
/// over-cap members simply receive nothing new.
///
/// Most partitions move once, straight to their final owner, but not
/// all: orphans that overflow onto Hold members (phase 3, when no capped
/// member has room) move again when capacity appears, and ceil-rounded
/// caps can leave the final post-transition balance one leveling move
/// away. Both are the cost of assigning every partition an owner at
/// every step.
fn quota_assignments(
    current: &HashMap<u32, String>,
    members: &[Member],
    num_partitions: u32,
) -> HashMap<u32, String> {
    let member_set: HashSet<&str> = members.iter().map(|m| m.name.as_str()).collect();

    // Keep valid assignments for every listed member, Hold included.
    let mut assignments: HashMap<u32, String> = current
        .iter()
        .filter(|(p, member)| **p < num_partitions && member_set.contains(member.as_str()))
        .map(|(p, member)| (*p, member.clone()))
        .collect();

    let mut owned: HashMap<&str, Vec<u32>> = members
        .iter()
        .map(|m| (m.name.as_str(), Vec::new()))
        .collect();
    for (partition, member) in &assignments {
        if let Some(parts) = owned.get_mut(member.as_str()) {
            parts.push(*partition);
        }
    }
    for parts in owned.values_mut() {
        parts.sort();
    }

    let mut pool: Vec<u32> = (0..num_partitions)
        .filter(|p| !assignments.contains_key(p))
        .collect();
    pool.sort();
    pool.reverse(); // pop() yields the lowest partition first

    // Name-sorted views for deterministic tie-breaking.
    let mut actives: Vec<(&str, Option<u32>)> = members
        .iter()
        .filter_map(|m| match m.policy {
            PlacementPolicy::Active { cap } => Some((m.name.as_str(), cap)),
            PlacementPolicy::Hold => None,
        })
        .collect();
    actives.sort();
    let mut holds: Vec<&str> = members
        .iter()
        .filter(|m| m.policy == PlacementPolicy::Hold)
        .map(|m| m.name.as_str())
        .collect();
    holds.sort();

    let has_room = |name: &str, cap: Option<u32>, owned: &HashMap<&str, Vec<u32>>| -> bool {
        match cap {
            Some(cap) => (owned[name].len() as u32) < cap,
            None => true,
        }
    };

    // Phase 1: fill active members from the pool, emptiest first.
    while !pool.is_empty() {
        let Some(&(name, _)) = actives
            .iter()
            .filter(|&&(n, cap)| has_room(n, cap, &owned))
            .min_by_key(|&&(n, _)| owned[n].len())
        else {
            break;
        };
        let partition = pool.pop().unwrap();
        owned.get_mut(name).unwrap().push(partition);
        assignments.insert(partition, name.to_string());
    }

    // Phase 2: capped active members below cap steal — from Hold members
    // first (the departing generation sheds before anything levels), then
    // from actives above their own cap, which phase 4 forcing and cap
    // shrinks create: without that second donor pool a member rejoining
    // after a crash starves at zero while its siblings sit over cap.
    // Uncapped members never steal — without a cap there is no bound on
    // how much they would strip from holders.
    loop {
        let Some(&(recipient, _)) = actives
            .iter()
            .filter(|&&(n, cap)| cap.is_some() && has_room(n, cap, &owned))
            .min_by_key(|&&(n, _)| owned[n].len())
        else {
            break;
        };
        let donor = holds
            .iter()
            .filter(|n| !owned[*n].is_empty())
            .max_by_key(|n| owned[*n].len())
            .copied()
            .or_else(|| {
                actives
                    .iter()
                    .filter(|&&(n, cap)| matches!(cap, Some(c) if owned[n].len() as u32 > c))
                    .max_by_key(|&&(n, _)| owned[n].len())
                    .map(|&(n, _)| n)
            });
        let Some(donor) = donor else {
            break;
        };
        let partition = owned.get_mut(donor).unwrap().pop().unwrap();
        owned.get_mut(recipient).unwrap().push(partition);
        assignments.insert(partition, recipient.to_string());
    }

    // Phase 3: leftover pool (every capped member full) goes to Hold
    // members, emptiest first — better a doomed owner than no owner.
    while !pool.is_empty() {
        let Some(&name) = holds.iter().min_by_key(|n| owned[*n].len()) else {
            break;
        };
        let partition = pool.pop().unwrap();
        owned.get_mut(name).unwrap().push(partition);
        assignments.insert(partition, name.to_string());
    }

    // Phase 4: still leftover (no holds at all) — force onto active
    // members past their caps; every partition must have an owner.
    while let Some(partition) = pool.pop() {
        let &(name, _) = actives
            .iter()
            .min_by_key(|&&(n, _)| owned[n].len())
            .expect("members is non-empty and holds is empty, so actives is non-empty");
        owned.get_mut(name).unwrap().push(partition);
        assignments.insert(partition, name.to_string());
    }

    assignments
}

#[cfg(test)]
mod tests {
    use super::*;

    fn active_members(names: &[&str]) -> Vec<Member> {
        names.iter().map(|n| Member::active(*n)).collect()
    }

    fn counts(result: &HashMap<u32, String>, member: &str) -> usize {
        result.values().filter(|v| v.as_str() == member).count()
    }

    #[test]
    fn empty_members() {
        let strategy = StickyBalancedStrategy;
        let result = strategy.compute_assignments(&HashMap::new(), &[], 16);
        assert!(result.is_empty());
    }

    #[test]
    fn initial_assignment_balanced() {
        let strategy = StickyBalancedStrategy;
        let members = active_members(&["m-0", "m-1", "m-2"]);
        let result = strategy.compute_assignments(&HashMap::new(), &members, 12);
        assert_eq!(result.len(), 12);
        for m in &members {
            assert_eq!(counts(&result, &m.name), 4, "{} should own 4", m.name);
        }
    }

    #[test]
    fn initial_assignment_uneven() {
        let strategy = StickyBalancedStrategy;
        let members = active_members(&["m-0", "m-1", "m-2"]);
        let result = strategy.compute_assignments(&HashMap::new(), &members, 10);
        assert_eq!(result.len(), 10);
        let mut c: Vec<usize> = members.iter().map(|m| counts(&result, &m.name)).collect();
        c.sort();
        assert_eq!(c, vec![3, 3, 4]);
    }

    #[test]
    fn keeps_existing_assignments() {
        let strategy = StickyBalancedStrategy;
        let members = active_members(&["m-0", "m-1"]);
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
        let members = active_members(&["m-0", "m-1", "m-2"]);
        let result = strategy.compute_assignments(&current, &members, 12);
        assert_eq!(result.len(), 12);
        for m in &members {
            assert_eq!(counts(&result, &m.name), 4, "{} should own 4", m.name);
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
        let members = active_members(&["m-0", "m-2"]);
        let result = strategy.compute_assignments(&current, &members, 12);
        assert_eq!(result.len(), 12);
        for m in &members {
            assert_eq!(counts(&result, &m.name), 6, "{} should own 6", m.name);
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
        let members = active_members(&["m-0"]);
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
        let members = active_members(&["m-0"]);
        let result = strategy.compute_assignments(&current, &members, 2);
        assert_eq!(result.len(), 2);
        assert_eq!(result[&0], "m-0");
        assert_eq!(result[&1], "m-0");
    }

    // ── Quota mode (Deployment rollout) ─────────────────────────────

    /// The whole partition space is on Hold members; the first
    /// new-generation pod pulls exactly its cap, never everything.
    #[test]
    fn first_new_member_capped_at_quota() {
        let strategy = StickyBalancedStrategy;
        let mut current = HashMap::new();
        for p in 0..12 {
            current.insert(p, format!("old-{}", p / 4));
        }
        let members = vec![
            Member::hold("old-0"),
            Member::hold("old-1"),
            Member::hold("old-2"),
            Member::active_capped("new-0", 4),
        ];
        let result = strategy.compute_assignments(&current, &members, 12);
        assert_eq!(result.len(), 12);
        assert_eq!(counts(&result, "new-0"), 4);
        assert_eq!(
            counts(&result, "old-0") + counts(&result, "old-1") + counts(&result, "old-2"),
            8
        );
    }

    /// A drained pod's orphans land on the below-cap new member; Hold
    /// members' assignments are untouched.
    #[test]
    fn orphans_go_to_new_gen_before_holds() {
        let strategy = StickyBalancedStrategy;
        let mut current = HashMap::new();
        // old-drained (not a member anymore) owned 0..4
        for p in 0..4 {
            current.insert(p, "old-drained".to_string());
        }
        for p in 4..8 {
            current.insert(p, "old-0".to_string());
        }
        for p in 8..12 {
            current.insert(p, "old-1".to_string());
        }
        let members = vec![
            Member::hold("old-0"),
            Member::hold("old-1"),
            Member::active_capped("new-0", 4),
        ];
        let result = strategy.compute_assignments(&current, &members, 12);
        for p in 0..4 {
            assert_eq!(result[&p], "new-0");
        }
        for p in 4..8 {
            assert_eq!(result[&p], "old-0");
        }
        for p in 8..12 {
            assert_eq!(result[&p], "old-1");
        }
    }

    /// More orphans than new-generation capacity: overflow spreads over
    /// Hold members instead of blowing past the cap.
    #[test]
    fn overflow_spreads_to_holds_when_new_gen_full() {
        let strategy = StickyBalancedStrategy;
        let mut current = HashMap::new();
        for p in 8..12 {
            current.insert(p, "old-0".to_string());
        }
        let members = vec![
            Member::hold("old-0"),
            Member::hold("old-1"),
            Member::active_capped("new-0", 4),
        ];
        // 0..8 are orphans; new-0 caps at 4, so 4 overflow to holds.
        let result = strategy.compute_assignments(&current, &members, 12);
        assert_eq!(result.len(), 12);
        assert_eq!(counts(&result, "new-0"), 4);
        // old-0 keeps its 4 and the emptier old-1 absorbs the overflow.
        assert_eq!(counts(&result, "old-0"), 4);
        assert_eq!(counts(&result, "old-1"), 4);
    }

    /// With no orphan pool, a capped new member pre-drains the fullest
    /// Hold members up to its cap.
    #[test]
    fn steals_from_fullest_hold_members() {
        let strategy = StickyBalancedStrategy;
        let mut current = HashMap::new();
        for p in 0..6 {
            current.insert(p, "old-0".to_string());
        }
        for p in 6..8 {
            current.insert(p, "old-1".to_string());
        }
        let members = vec![
            Member::hold("old-0"),
            Member::hold("old-1"),
            Member::active_capped("new-0", 4),
        ];
        let result = strategy.compute_assignments(&current, &members, 8);
        assert_eq!(counts(&result, "new-0"), 4);
        // Fullest-first stealing drains old-0 toward old-1's level.
        assert_eq!(counts(&result, "old-0"), 2);
        assert_eq!(counts(&result, "old-1"), 2);
    }

    /// Caps under-provision the space and there are no Hold members:
    /// every partition still gets an owner.
    #[test]
    fn forces_assignment_past_caps_without_holds() {
        let strategy = StickyBalancedStrategy;
        let members = vec![
            Member::active_capped("new-0", 2),
            Member::active_capped("new-1", 2),
        ];
        let result = strategy.compute_assignments(&HashMap::new(), &members, 8);
        assert_eq!(result.len(), 8);
        assert_eq!(counts(&result, "new-0"), 4);
        assert_eq!(counts(&result, "new-1"), 4);
    }

    /// A ten-pod fleet rolls two by two, drain-led: each wave two old
    /// pods drain out and two new pods register at their final cap.
    /// The orphan pool exactly covers the fresh pods' capacity, so
    /// phase 1 absorbs it before any stealing: surviving old pods and
    /// already-placed new pods keep their exact partitions, and every
    /// partition moves exactly once, straight from a dying pod to its
    /// final owner. (Surge ordering — new pods registering before old
    /// ones drain — instead pre-drains surviving holds; still one move
    /// per partition, but not only the dying pods'.)
    #[test]
    fn wave_rollout_moves_only_the_dying_pods_partitions() {
        let strategy = StickyBalancedStrategy;
        let total: u32 = 20;
        let cap = 2u32; // 20 partitions over 10 desired replicas

        let mut assignments: HashMap<u32, String> = (0..total)
            .map(|p| (p, format!("old-{}", p / cap)))
            .collect();
        let mut moves_per_partition: HashMap<u32, u32> = HashMap::new();

        for wave in 0..5u32 {
            let dying: Vec<String> = (2 * wave..2 * wave + 2)
                .map(|i| format!("old-{i}"))
                .collect();
            let dying_partitions: HashSet<u32> = assignments
                .iter()
                .filter(|(_, owner)| dying.contains(owner))
                .map(|(p, _)| *p)
                .collect();

            let mut members: Vec<Member> = (2 * wave + 2..10)
                .map(|i| Member::hold(format!("old-{i}")))
                .collect();
            members
                .extend((0..2 * wave + 2).map(|i| Member::active_capped(format!("new-{i}"), cap)));

            let next = strategy.compute_assignments(&assignments, &members, total);
            assert_eq!(next.len(), total as usize);

            for (partition, owner) in &next {
                let previous = &assignments[partition];
                if owner != previous {
                    assert!(
                        dying_partitions.contains(partition),
                        "wave {wave}: partition {partition} moved {previous} -> {owner} but its owner was not dying"
                    );
                    *moves_per_partition.entry(*partition).or_insert(0) += 1;
                }
            }
            assignments = next;
        }

        for pod in 0..10 {
            assert_eq!(
                assignments
                    .values()
                    .filter(|o| **o == format!("new-{pod}"))
                    .count(),
                cap as usize
            );
        }
        assert_eq!(moves_per_partition.len(), total as usize);
        assert!(moves_per_partition.values().all(|moves| *moves == 1));
    }

    /// A capped member rejoining after a crash is leveled from siblings
    /// sitting above cap: with no Hold donors and no orphan pool,
    /// nothing else can feed it. (Over-cap siblings are what phase 4
    /// forcing leaves behind when the rejoiner was down.)
    #[test]
    fn below_cap_member_steals_from_over_cap_siblings() {
        let strategy = StickyBalancedStrategy;
        let mut current = HashMap::new();
        for p in 0..4 {
            current.insert(p, "new-0".to_string());
        }
        for p in 4..8 {
            current.insert(p, "new-1".to_string());
        }
        let members = vec![
            Member::active_capped("new-0", 3),
            Member::active_capped("new-1", 3),
            Member::active_capped("new-2", 3),
        ];
        let result = strategy.compute_assignments(&current, &members, 8);
        assert_eq!(result.len(), 8);
        assert_eq!(counts(&result, "new-0"), 3);
        assert_eq!(counts(&result, "new-1"), 3);
        assert_eq!(counts(&result, "new-2"), 2);
    }

    /// A member already above a shrunken cap keeps its partitions — the
    /// cap gates new placements, it never forces shedding.
    #[test]
    fn over_cap_member_keeps_assignments() {
        let strategy = StickyBalancedStrategy;
        let mut current = HashMap::new();
        for p in 0..6 {
            current.insert(p, "new-0".to_string());
        }
        let members = vec![Member::active_capped("new-0", 4), Member::hold("old-0")];
        // 6..8 are orphans; new-0 is over cap so they land on the hold.
        let result = strategy.compute_assignments(&current, &members, 8);
        for p in 0..6 {
            assert_eq!(result[&p], "new-0");
        }
        assert_eq!(counts(&result, "old-0"), 2);
    }
}
