mod sticky_balanced;

pub use sticky_balanced::StickyBalancedStrategy;

use std::collections::HashMap;

/// Trait for partition assignment strategies.
///
/// The coordinator calls `compute_assignments` whenever the set of active
/// members changes. Implementations decide how to map partitions to members.
/// The coordinator then diffs the result against current assignments to
/// determine which partitions need handoffs.
pub trait AssignmentStrategy: Send + Sync {
    /// Compute the desired partition-to-member mapping.
    ///
    /// - `current`: existing partition -> member_name mapping (empty on first run)
    /// - `active_members`: sorted list of member names eligible for assignment
    /// - `num_partitions`: total number of partitions to distribute
    fn compute_assignments(
        &self,
        current: &HashMap<u32, String>,
        active_members: &[String],
        num_partitions: u32,
    ) -> HashMap<u32, String>;
}
