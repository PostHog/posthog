mod jump_hash;
mod sticky_balanced;

pub use jump_hash::JumpHashStrategy;
pub use sticky_balanced::StickyBalancedStrategy;

use std::collections::HashMap;

/// Trait for partition assignment strategies.
///
/// The coordinator calls `compute_assignments` whenever the set of active pods
/// changes. Implementations decide how to map partitions to pods. The
/// coordinator then diffs the result against current assignments to determine
/// which partitions need handoffs.
pub trait AssignmentStrategy: Send + Sync {
    /// Compute the desired partition-to-pod mapping.
    ///
    /// - `current`: existing partition -> pod_name mapping (empty on first run)
    /// - `active_pods`: sorted list of pod names eligible for assignment
    /// - `num_partitions`: total number of partitions to distribute
    fn compute_assignments(
        &self,
        current: &HashMap<u32, String>,
        active_pods: &[String],
        num_partitions: u32,
    ) -> HashMap<u32, String>;
}
