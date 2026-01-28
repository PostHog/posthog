//! Rebalance coordination for Kafka consumer group rebalances.
//!
//! This module provides a lightweight coordinator for tracking rebalance state across
//! multiple components. It uses a counter (not a boolean) to correctly handle overlapping
//! rebalances - a new rebalance can start before the previous one's async work completes.
//!
//! # Usage
//!
//! The coordinator should be created first during service initialization and shared with
//! components that need to check or modify rebalance state:
//!
//! - `ProcessorRebalanceHandler`: Calls `start_rebalancing()` when partitions are assigned
//! - `StoreManager`: Checks `is_rebalancing()` to skip cleanup during rebalance
//! - `OffsetTracker`: Checks `is_rebalancing()` to block offset commits during rebalance
//! - `CheckpointManager`: Checks `is_rebalancing()` to skip checkpoint work during rebalance
//!
//! # Counter Semantics
//!
//! - `start_rebalancing()`: Increments the counter. Called synchronously in the rdkafka
//!   callback before async work is queued.
//! - `finish_rebalancing()`: Decrements the counter. Called when async work completes
//!   (typically via the RAII `RebalancingGuard`).
//! - `is_rebalancing()`: Returns true if counter > 0.
//!
//! The counter supports overlapping rebalances:
//! - Rebalance A starts: counter = 1
//! - Rebalance B starts before A finishes: counter = 2
//! - Rebalance A finishes: counter = 1 (still rebalancing!)
//! - Rebalance B finishes: counter = 0 (safe to proceed)

use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;

use dashmap::DashSet;
use tracing::{info, warn};

use crate::kafka::types::Partition;
use crate::metrics_const::{
    OWNED_PARTITIONS_COUNT, PARTITION_OWNERSHIP_ADDED, PARTITION_OWNERSHIP_REMOVED,
    REBALANCING_COUNT,
};

/// Coordinates rebalance state across multiple components.
///
/// This is a lightweight struct that can be cheaply cloned via `Arc`.
/// It provides the single source of truth for:
/// - Whether a rebalance is in progress (counter-based for overlapping rebalances)
/// - Which partitions are currently owned by this consumer
pub struct RebalanceCoordinator {
    /// Counter tracking the number of in-progress rebalances.
    /// Using a counter (not bool) correctly handles overlapping rebalances.
    rebalancing_count: AtomicUsize,

    /// Set of partitions currently owned by this consumer.
    /// Updated synchronously in ASSIGN (add) and REVOKE (remove) callbacks.
    /// Used to determine which partitions to resume and which to cleanup.
    owned_partitions: DashSet<Partition>,
}

impl RebalanceCoordinator {
    /// Create a new coordinator with the counter initialized to 0 and no owned partitions.
    pub fn new() -> Self {
        Self {
            rebalancing_count: AtomicUsize::new(0),
            owned_partitions: DashSet::new(),
        }
    }

    /// Signal that a rebalance has started. Increments the counter.
    ///
    /// Call this synchronously in the rdkafka callback (before async work is queued)
    /// to ensure no gap where cleanup could run.
    ///
    /// While counter > 0, operations like orphan cleanup and offset commits are blocked.
    pub fn start_rebalancing(&self) {
        let prev = self.rebalancing_count.fetch_add(1, Ordering::SeqCst);
        let new_count = prev + 1;
        metrics::gauge!(REBALANCING_COUNT).set(new_count as f64);
        info!(
            previous_count = prev,
            new_count = new_count,
            "Rebalance started, incremented rebalancing counter"
        );
    }

    /// Signal that a rebalance's async work has completed. Decrements the counter.
    ///
    /// Typically called via the `RebalancingGuard` RAII pattern to ensure cleanup
    /// even on panic or cancellation.
    pub fn finish_rebalancing(&self) {
        let prev = self.rebalancing_count.fetch_sub(1, Ordering::SeqCst);
        let new_count = prev.saturating_sub(1);
        metrics::gauge!(REBALANCING_COUNT).set(new_count as f64);
        if prev == 0 {
            warn!("finish_rebalancing called when counter was already 0");
        } else if new_count == 0 {
            info!("All rebalances completed, counter returned to 0");
        } else {
            info!(
                previous_count = prev,
                new_count = new_count,
                "Rebalance finished, decremented rebalancing counter (other rebalances still in progress)"
            );
        }
    }

    /// Check if any rebalance async work is currently in progress.
    ///
    /// Returns true if the counter is greater than 0.
    pub fn is_rebalancing(&self) -> bool {
        self.rebalancing_count.load(Ordering::SeqCst) > 0
    }

    /// Get a guard that will decrement the counter when dropped.
    ///
    /// Call this AFTER `start_rebalancing()` to ensure cleanup on panic/cancellation.
    /// The guard uses RAII to guarantee the counter is decremented even if the
    /// async work panics or is cancelled.
    ///
    /// # Example
    ///
    /// ```ignore
    /// coordinator.start_rebalancing(); // Called in sync callback
    ///
    /// // In async work:
    /// let _guard = coordinator.rebalancing_guard();
    /// // ... do async work ...
    /// // guard drops here, calling finish_rebalancing()
    /// ```
    pub fn rebalancing_guard(self: &Arc<Self>) -> RebalancingGuard {
        RebalancingGuard {
            coordinator: Arc::clone(self),
        }
    }

    // ============================================
    // PARTITION OWNERSHIP TRACKING
    // ============================================

    /// Add partitions to the owned set. Called from ASSIGN callback.
    ///
    /// This is called synchronously in the rdkafka callback to update ownership
    /// before async work is queued. Idempotent - adding a partition that's already
    /// owned is a no-op.
    pub fn add_owned_partitions(&self, partitions: &[Partition]) {
        if partitions.is_empty() {
            return;
        }

        let mut added_count = 0;
        for partition in partitions {
            if self.owned_partitions.insert(partition.clone()) {
                added_count += 1;
            }
        }

        let total_owned = self.owned_partitions.len();
        metrics::gauge!(OWNED_PARTITIONS_COUNT).set(total_owned as f64);
        metrics::counter!(PARTITION_OWNERSHIP_ADDED).increment(added_count as u64);

        if added_count > 0 {
            info!(
                added_count = added_count,
                total_owned = total_owned,
                "Partitions added to ownership"
            );
        }
    }

    /// Remove partitions from the owned set. Called from REVOKE callback.
    ///
    /// This is called synchronously in the rdkafka callback to update ownership
    /// before async work is queued. Idempotent - removing a partition that's not
    /// owned is a no-op.
    pub fn remove_owned_partitions(&self, partitions: &[Partition]) {
        if partitions.is_empty() {
            return;
        }

        let mut removed_count = 0;
        for partition in partitions {
            if self.owned_partitions.remove(partition).is_some() {
                removed_count += 1;
            }
        }

        let total_owned = self.owned_partitions.len();
        metrics::gauge!(OWNED_PARTITIONS_COUNT).set(total_owned as f64);
        metrics::counter!(PARTITION_OWNERSHIP_REMOVED).increment(removed_count as u64);

        if removed_count > 0 {
            info!(
                removed_count = removed_count,
                total_owned = total_owned,
                "Partitions removed from ownership"
            );
        }
    }

    /// Get a snapshot of all currently owned partitions.
    ///
    /// Returns a Vec copy of all owned partitions. Use this to determine
    /// which partitions to resume after async setup completes.
    pub fn get_owned_partitions(&self) -> Vec<Partition> {
        self.owned_partitions.iter().map(|p| p.clone()).collect()
    }

    /// Check if a specific partition is currently owned.
    ///
    /// Use this to skip work for partitions that were revoked during async setup.
    pub fn is_partition_owned(&self, partition: &Partition) -> bool {
        self.owned_partitions.contains(partition)
    }

    /// Get partitions from the input list that are NOT currently owned.
    ///
    /// Use this in cleanup to determine which partitions should be cleaned up
    /// (those that are still not owned after rapid revoke→assign).
    pub fn get_unowned_partitions(&self, partitions: &[Partition]) -> Vec<Partition> {
        partitions
            .iter()
            .filter(|p| !self.owned_partitions.contains(*p))
            .cloned()
            .collect()
    }

    /// Get the count of owned partitions (for testing/debugging).
    #[cfg(test)]
    pub fn owned_partition_count(&self) -> usize {
        self.owned_partitions.len()
    }

    /// Get the current rebalancing count (for testing/debugging).
    #[cfg(test)]
    pub fn rebalancing_count(&self) -> usize {
        self.rebalancing_count.load(Ordering::SeqCst)
    }
}

impl Default for RebalanceCoordinator {
    fn default() -> Self {
        Self::new()
    }
}

/// RAII guard that decrements the rebalancing counter when dropped.
///
/// This ensures the counter is decremented even if the async work panics or is cancelled.
/// Create via `RebalanceCoordinator::rebalancing_guard()`.
pub struct RebalancingGuard {
    coordinator: Arc<RebalanceCoordinator>,
}

impl Drop for RebalancingGuard {
    fn drop(&mut self) {
        self.coordinator.finish_rebalancing();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::kafka::types::Partition;

    #[test]
    fn test_new_coordinator_not_rebalancing() {
        let coordinator = RebalanceCoordinator::new();
        assert!(!coordinator.is_rebalancing());
        assert_eq!(coordinator.rebalancing_count(), 0);
    }

    #[test]
    fn test_start_and_finish_rebalancing() {
        let coordinator = RebalanceCoordinator::new();

        coordinator.start_rebalancing();
        assert!(coordinator.is_rebalancing());
        assert_eq!(coordinator.rebalancing_count(), 1);

        coordinator.finish_rebalancing();
        assert!(!coordinator.is_rebalancing());
        assert_eq!(coordinator.rebalancing_count(), 0);
    }

    #[test]
    fn test_overlapping_rebalances() {
        let coordinator = RebalanceCoordinator::new();

        // Rebalance A starts
        coordinator.start_rebalancing();
        assert_eq!(coordinator.rebalancing_count(), 1);

        // Rebalance B starts before A finishes
        coordinator.start_rebalancing();
        assert_eq!(coordinator.rebalancing_count(), 2);
        assert!(coordinator.is_rebalancing());

        // Rebalance A finishes
        coordinator.finish_rebalancing();
        assert_eq!(coordinator.rebalancing_count(), 1);
        assert!(coordinator.is_rebalancing()); // Still rebalancing!

        // Rebalance B finishes
        coordinator.finish_rebalancing();
        assert_eq!(coordinator.rebalancing_count(), 0);
        assert!(!coordinator.is_rebalancing());
    }

    #[test]
    fn test_rebalancing_guard_decrements_on_drop() {
        let coordinator = Arc::new(RebalanceCoordinator::new());

        coordinator.start_rebalancing();
        assert_eq!(coordinator.rebalancing_count(), 1);

        {
            let _guard = coordinator.rebalancing_guard();
            assert_eq!(coordinator.rebalancing_count(), 1);
        } // guard drops here

        assert_eq!(coordinator.rebalancing_count(), 0);
        assert!(!coordinator.is_rebalancing());
    }

    #[test]
    fn test_guard_with_overlapping_rebalances() {
        let coordinator = Arc::new(RebalanceCoordinator::new());

        // Rebalance A
        coordinator.start_rebalancing();
        let _guard_a = coordinator.rebalancing_guard();

        // Rebalance B
        coordinator.start_rebalancing();
        let _guard_b = coordinator.rebalancing_guard();

        assert_eq!(coordinator.rebalancing_count(), 2);

        drop(_guard_a);
        assert_eq!(coordinator.rebalancing_count(), 1);
        assert!(coordinator.is_rebalancing());

        drop(_guard_b);
        assert_eq!(coordinator.rebalancing_count(), 0);
        assert!(!coordinator.is_rebalancing());
    }

    #[test]
    fn test_default_impl() {
        let coordinator = RebalanceCoordinator::default();
        assert!(!coordinator.is_rebalancing());
    }

    // ============================================
    // PARTITION OWNERSHIP TESTS
    // ============================================

    #[test]
    fn test_owned_partitions_initially_empty() {
        let coordinator = RebalanceCoordinator::new();
        assert!(coordinator.get_owned_partitions().is_empty());
        assert_eq!(coordinator.owned_partition_count(), 0);
    }

    #[test]
    fn test_add_and_remove_owned_partitions() {
        let coordinator = RebalanceCoordinator::new();
        let p0 = Partition::new("topic".to_string(), 0);
        let p1 = Partition::new("topic".to_string(), 1);

        // Add partitions
        coordinator.add_owned_partitions(&[p0.clone(), p1.clone()]);
        assert_eq!(coordinator.owned_partition_count(), 2);
        assert!(coordinator.is_partition_owned(&p0));
        assert!(coordinator.is_partition_owned(&p1));

        // Remove one partition
        coordinator.remove_owned_partitions(std::slice::from_ref(&p1));
        assert_eq!(coordinator.owned_partition_count(), 1);
        assert!(coordinator.is_partition_owned(&p0));
        assert!(!coordinator.is_partition_owned(&p1));

        // Remove the other
        coordinator.remove_owned_partitions(std::slice::from_ref(&p0));
        assert_eq!(coordinator.owned_partition_count(), 0);
        assert!(!coordinator.is_partition_owned(&p0));
    }

    #[test]
    fn test_get_unowned_partitions() {
        let coordinator = RebalanceCoordinator::new();
        let p0 = Partition::new("topic".to_string(), 0);
        let p1 = Partition::new("topic".to_string(), 1);
        let p2 = Partition::new("topic".to_string(), 2);

        // Add p0 only
        coordinator.add_owned_partitions(std::slice::from_ref(&p0));

        // Query for unowned among [p0, p1, p2]
        let unowned = coordinator.get_unowned_partitions(&[p0.clone(), p1.clone(), p2.clone()]);
        assert_eq!(unowned.len(), 2);
        assert!(!unowned.contains(&p0));
        assert!(unowned.contains(&p1));
        assert!(unowned.contains(&p2));
    }

    #[test]
    fn test_idempotent_add_remove() {
        let coordinator = RebalanceCoordinator::new();
        let p0 = Partition::new("topic".to_string(), 0);

        // Adding twice should be idempotent
        coordinator.add_owned_partitions(std::slice::from_ref(&p0));
        coordinator.add_owned_partitions(std::slice::from_ref(&p0));
        assert_eq!(coordinator.owned_partition_count(), 1);

        // Removing twice should be idempotent
        coordinator.remove_owned_partitions(std::slice::from_ref(&p0));
        coordinator.remove_owned_partitions(std::slice::from_ref(&p0));
        assert!(coordinator.get_owned_partitions().is_empty());
    }

    #[test]
    fn test_rapid_revoke_assign_ownership() {
        // Simulates rapid revoke -> assign scenario
        let coordinator = RebalanceCoordinator::new();
        let p0 = Partition::new("topic".to_string(), 0);

        // Initial assignment
        coordinator.add_owned_partitions(std::slice::from_ref(&p0));
        assert!(coordinator.is_partition_owned(&p0));

        // Revoke
        coordinator.remove_owned_partitions(std::slice::from_ref(&p0));
        assert!(!coordinator.is_partition_owned(&p0));

        // Immediate re-assign
        coordinator.add_owned_partitions(std::slice::from_ref(&p0));
        assert!(coordinator.is_partition_owned(&p0));

        // Partition should be owned and NOT in unowned list
        let unowned = coordinator.get_unowned_partitions(std::slice::from_ref(&p0));
        assert!(unowned.is_empty());
    }

    #[test]
    fn test_empty_operations() {
        let coordinator = RebalanceCoordinator::new();

        // Empty add/remove should be no-ops
        coordinator.add_owned_partitions(&[]);
        coordinator.remove_owned_partitions(&[]);
        assert_eq!(coordinator.owned_partition_count(), 0);

        // Empty unowned query
        let unowned = coordinator.get_unowned_partitions(&[]);
        assert!(unowned.is_empty());
    }
}
