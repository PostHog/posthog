//! Rebalance tracking for Kafka consumer group rebalances.
//!
//! This module provides a lightweight tracker for rebalance state across multiple components.
//! It uses a counter (not a boolean) to correctly handle overlapping rebalances - a new
//! rebalance can start before the previous one's async work completes.
//!
//! # Usage
//!
//! The tracker should be created first during service initialization and shared with
//! components that need to check or modify rebalance state:
//!
//! - `ProcessorRebalanceHandler`: Calls `start_rebalancing()` when partitions are assigned
//! - `StoreManager`: Checks `is_rebalancing()` to skip cleanup during rebalance
//! - `OffsetTracker`: Checks `is_rebalancing()` to block offset commits during rebalance
//! - `CheckpointManager`: Uses `get_export_token()` to obtain cancellation tokens for export
//!   workers. These tokens are cancelled when rebalancing starts, freeing S3 bandwidth for
//!   the more critical checkpoint imports.
//!
//! # Counter Semantics
//!
//! - `start_rebalancing()`: Increments the counter. On 0->1 transition, cancels the export
//!   suppression token to immediately stop in-flight checkpoint exports.
//! - `finish_rebalancing()`: Decrements the counter. On 1->0 transition, creates a fresh
//!   export suppression token so checkpoint exports can resume.
//! - `is_rebalancing()`: Returns true if counter > 0.
//! - `get_export_token()`: Returns a child of the export suppression token. Workers use this
//!   to check if they should bail out of S3 uploads.
//!
//! The counter supports overlapping rebalances:
//! - Rebalance A starts: counter = 1, export token cancelled
//! - Rebalance B starts before A finishes: counter = 2 (token already cancelled)
//! - Rebalance A finishes: counter = 1 (still rebalancing, exports still suppressed!)
//! - Rebalance B finishes: counter = 0, fresh export token created (exports can resume)

use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, RwLock};

use dashmap::DashSet;
use tokio_util::sync::CancellationToken;
use tracing::{info, warn};

use crate::kafka::types::Partition;
use crate::metrics_const::{
    OWNED_PARTITIONS_COUNT, PARTITION_OWNERSHIP_ADDED, PARTITION_OWNERSHIP_REMOVED,
    REBALANCING_COUNT,
};

/// Tracks rebalance state across multiple components.
///
/// This is a lightweight struct that can be cheaply cloned via `Arc`.
/// It provides the single source of truth for:
/// - Whether a rebalance is in progress (counter-based for overlapping rebalances)
/// - Which partitions are currently owned by this consumer
/// - Export suppression during rebalancing (to prioritize imports)
///
/// Note: Partition setup task tracking is handled by ProcessorRebalanceHandler
/// (not here) because it needs access to StoreManager to detect stale entries.
pub struct RebalanceTracker {
    /// Counter tracking the number of in-progress rebalances.
    /// Using a counter (not bool) correctly handles overlapping rebalances.
    rebalancing_count: AtomicUsize,

    /// Set of partitions currently owned by this consumer.
    /// Updated synchronously in ASSIGN (add) and REVOKE (remove) callbacks.
    /// Used to determine which partitions to resume and which to cleanup.
    owned_partitions: DashSet<Partition>,

    /// Token for suppressing checkpoint exports during rebalancing.
    /// Cancelled when rebalancing starts (count 0->1), recreated when complete (count 1->0).
    /// CheckpointManager workers use child tokens from this via `get_export_token()`.
    /// This ensures S3 bandwidth is available for checkpoint imports during rebalance.
    export_suppression_token: RwLock<CancellationToken>,
}

impl RebalanceTracker {
    /// Create a new tracker with the counter initialized to 0 and no owned partitions.
    /// Export suppression token starts fresh (uncancelled).
    pub fn new() -> Self {
        Self {
            rebalancing_count: AtomicUsize::new(0),
            owned_partitions: DashSet::new(),
            export_suppression_token: RwLock::new(CancellationToken::new()),
        }
    }

    /// Signal that a rebalance has started. Increments the counter.
    ///
    /// Call this synchronously in the rdkafka callback (before async work is queued)
    /// to ensure no gap where cleanup could run.
    ///
    /// While counter > 0, operations like orphan cleanup and offset commits are blocked.
    ///
    /// On the 0->1 transition (first rebalance starts), cancels the export suppression
    /// token to immediately stop all in-flight checkpoint exports. This frees S3
    /// bandwidth for the more critical checkpoint imports.
    pub fn start_rebalancing(&self) {
        let prev = self.rebalancing_count.fetch_add(1, Ordering::SeqCst);
        let new_count = prev + 1;
        metrics::gauge!(REBALANCING_COUNT).set(new_count as f64);

        // Cancel export token on FIRST rebalance (0 -> 1 transition)
        if prev == 0 {
            // Clone the token and release the lock before calling cancel() to avoid
            // potential deadlock if cancel() triggers callbacks that need this lock
            let token = {
                let guard = self
                    .export_suppression_token
                    .read()
                    .unwrap_or_else(|poison| poison.into_inner());
                guard.clone()
            };
            token.cancel();
            info!("Export suppression: cancelled all in-flight exports (rebalance started)");
        }

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
    ///
    /// On the 1->0 transition (all rebalances complete), creates a fresh export
    /// suppression token so checkpoint exports can resume normally.
    pub fn finish_rebalancing(&self) {
        let prev = self.rebalancing_count.fetch_sub(1, Ordering::SeqCst);
        let new_count = prev.saturating_sub(1);
        metrics::gauge!(REBALANCING_COUNT).set(new_count as f64);

        if prev == 0 {
            warn!("finish_rebalancing called when counter was already 0");
        } else if new_count == 0 {
            // Create fresh token when ALL rebalances complete (1 -> 0 transition)
            let mut token = self
                .export_suppression_token
                .write()
                .unwrap_or_else(|poison| poison.into_inner());
            *token = CancellationToken::new();
            info!("Export suppression: created fresh token (all rebalances complete)");
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

    /// Get a child token for checkpoint export suppression.
    ///
    /// CheckpointManager calls this when spawning export workers. The returned
    /// child token will be cancelled when any rebalance starts, allowing workers
    /// to bail out of S3 uploads early and free bandwidth for imports.
    ///
    /// Returns a child of the current export suppression token. If a rebalance
    /// is in progress, the returned token will already be cancelled.
    pub fn get_export_token(&self) -> CancellationToken {
        self.export_suppression_token
            .read()
            .unwrap_or_else(|poison| poison.into_inner())
            .child_token()
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
    /// tracker.start_rebalancing(); // Called in sync callback
    ///
    /// // In async work:
    /// let _guard = tracker.rebalancing_guard();
    /// // ... do async work ...
    /// // guard drops here, calling finish_rebalancing()
    /// ```
    pub fn rebalancing_guard(self: &Arc<Self>) -> RebalancingGuard {
        RebalancingGuard {
            tracker: Arc::clone(self),
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

    /// Get the current rebalancing count.
    ///
    /// Used by ProcessorRebalanceHandler to decide whether to run finalize before or after
    /// decrementing (so is_rebalancing() stays true during finalize and orphan cleanup skips).
    /// Also useful for observability.
    pub fn rebalancing_count(&self) -> usize {
        self.rebalancing_count.load(Ordering::SeqCst)
    }
}

impl Default for RebalanceTracker {
    fn default() -> Self {
        Self::new()
    }
}

/// RAII guard that decrements the rebalancing counter when dropped.
///
/// This ensures the counter is decremented even if the async work panics or is cancelled.
/// Create via `RebalanceTracker::rebalancing_guard()`.
pub struct RebalancingGuard {
    tracker: Arc<RebalanceTracker>,
}

impl Drop for RebalancingGuard {
    fn drop(&mut self) {
        self.tracker.finish_rebalancing();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::kafka::types::Partition;

    #[test]
    fn test_new_tracker_not_rebalancing() {
        let tracker = RebalanceTracker::new();
        assert!(!tracker.is_rebalancing());
        assert_eq!(tracker.rebalancing_count(), 0);
    }

    #[test]
    fn test_start_and_finish_rebalancing() {
        let tracker = RebalanceTracker::new();

        tracker.start_rebalancing();
        assert!(tracker.is_rebalancing());
        assert_eq!(tracker.rebalancing_count(), 1);

        tracker.finish_rebalancing();
        assert!(!tracker.is_rebalancing());
        assert_eq!(tracker.rebalancing_count(), 0);
    }

    #[test]
    fn test_overlapping_rebalances() {
        let tracker = RebalanceTracker::new();

        // Rebalance A starts
        tracker.start_rebalancing();
        assert_eq!(tracker.rebalancing_count(), 1);

        // Rebalance B starts before A finishes
        tracker.start_rebalancing();
        assert_eq!(tracker.rebalancing_count(), 2);
        assert!(tracker.is_rebalancing());

        // Rebalance A finishes
        tracker.finish_rebalancing();
        assert_eq!(tracker.rebalancing_count(), 1);
        assert!(tracker.is_rebalancing()); // Still rebalancing!

        // Rebalance B finishes
        tracker.finish_rebalancing();
        assert_eq!(tracker.rebalancing_count(), 0);
        assert!(!tracker.is_rebalancing());
    }

    #[test]
    fn test_rebalancing_guard_decrements_on_drop() {
        let tracker = Arc::new(RebalanceTracker::new());

        tracker.start_rebalancing();
        assert_eq!(tracker.rebalancing_count(), 1);

        {
            let _guard = tracker.rebalancing_guard();
            assert_eq!(tracker.rebalancing_count(), 1);
        } // guard drops here

        assert_eq!(tracker.rebalancing_count(), 0);
        assert!(!tracker.is_rebalancing());
    }

    #[test]
    fn test_guard_with_overlapping_rebalances() {
        let tracker = Arc::new(RebalanceTracker::new());

        // Rebalance A
        tracker.start_rebalancing();
        let _guard_a = tracker.rebalancing_guard();

        // Rebalance B
        tracker.start_rebalancing();
        let _guard_b = tracker.rebalancing_guard();

        assert_eq!(tracker.rebalancing_count(), 2);

        drop(_guard_a);
        assert_eq!(tracker.rebalancing_count(), 1);
        assert!(tracker.is_rebalancing());

        drop(_guard_b);
        assert_eq!(tracker.rebalancing_count(), 0);
        assert!(!tracker.is_rebalancing());
    }

    #[test]
    fn test_default_impl() {
        let tracker = RebalanceTracker::default();
        assert!(!tracker.is_rebalancing());
    }

    // ============================================
    // PARTITION OWNERSHIP TESTS
    // ============================================

    #[test]
    fn test_owned_partitions_initially_empty() {
        let tracker = RebalanceTracker::new();
        assert!(tracker.get_owned_partitions().is_empty());
        assert_eq!(tracker.owned_partition_count(), 0);
    }

    #[test]
    fn test_add_and_remove_owned_partitions() {
        let tracker = RebalanceTracker::new();
        let p0 = Partition::new("topic".to_string(), 0);
        let p1 = Partition::new("topic".to_string(), 1);

        // Add partitions
        tracker.add_owned_partitions(&[p0.clone(), p1.clone()]);
        assert_eq!(tracker.owned_partition_count(), 2);
        assert!(tracker.is_partition_owned(&p0));
        assert!(tracker.is_partition_owned(&p1));

        // Remove one partition
        tracker.remove_owned_partitions(std::slice::from_ref(&p1));
        assert_eq!(tracker.owned_partition_count(), 1);
        assert!(tracker.is_partition_owned(&p0));
        assert!(!tracker.is_partition_owned(&p1));

        // Remove the other
        tracker.remove_owned_partitions(std::slice::from_ref(&p0));
        assert_eq!(tracker.owned_partition_count(), 0);
        assert!(!tracker.is_partition_owned(&p0));
    }

    #[test]
    fn test_get_unowned_partitions() {
        let tracker = RebalanceTracker::new();
        let p0 = Partition::new("topic".to_string(), 0);
        let p1 = Partition::new("topic".to_string(), 1);
        let p2 = Partition::new("topic".to_string(), 2);

        // Add p0 only
        tracker.add_owned_partitions(std::slice::from_ref(&p0));

        // Query for unowned among [p0, p1, p2]
        let unowned = tracker.get_unowned_partitions(&[p0.clone(), p1.clone(), p2.clone()]);
        assert_eq!(unowned.len(), 2);
        assert!(!unowned.contains(&p0));
        assert!(unowned.contains(&p1));
        assert!(unowned.contains(&p2));
    }

    #[test]
    fn test_idempotent_add_remove() {
        let tracker = RebalanceTracker::new();
        let p0 = Partition::new("topic".to_string(), 0);

        // Adding twice should be idempotent
        tracker.add_owned_partitions(std::slice::from_ref(&p0));
        tracker.add_owned_partitions(std::slice::from_ref(&p0));
        assert_eq!(tracker.owned_partition_count(), 1);

        // Removing twice should be idempotent
        tracker.remove_owned_partitions(std::slice::from_ref(&p0));
        tracker.remove_owned_partitions(std::slice::from_ref(&p0));
        assert!(tracker.get_owned_partitions().is_empty());
    }

    #[test]
    fn test_rapid_revoke_assign_ownership() {
        // Simulates rapid revoke -> assign scenario
        let tracker = RebalanceTracker::new();
        let p0 = Partition::new("topic".to_string(), 0);

        // Initial assignment
        tracker.add_owned_partitions(std::slice::from_ref(&p0));
        assert!(tracker.is_partition_owned(&p0));

        // Revoke
        tracker.remove_owned_partitions(std::slice::from_ref(&p0));
        assert!(!tracker.is_partition_owned(&p0));

        // Immediate re-assign
        tracker.add_owned_partitions(std::slice::from_ref(&p0));
        assert!(tracker.is_partition_owned(&p0));

        // Partition should be owned and NOT in unowned list
        let unowned = tracker.get_unowned_partitions(std::slice::from_ref(&p0));
        assert!(unowned.is_empty());
    }

    #[test]
    fn test_empty_operations() {
        let tracker = RebalanceTracker::new();

        // Empty add/remove should be no-ops
        tracker.add_owned_partitions(&[]);
        tracker.remove_owned_partitions(&[]);
        assert_eq!(tracker.owned_partition_count(), 0);

        // Empty unowned query
        let unowned = tracker.get_unowned_partitions(&[]);
        assert!(unowned.is_empty());
    }

    // ============================================
    // EXPORT SUPPRESSION TOKEN TESTS
    // ============================================

    #[test]
    fn test_export_token_not_cancelled_on_new_tracker() {
        let tracker = RebalanceTracker::new();
        let token = tracker.get_export_token();
        assert!(
            !token.is_cancelled(),
            "Export token should NOT be cancelled on fresh tracker"
        );
    }

    #[test]
    fn test_export_token_cancelled_on_first_rebalance() {
        let tracker = RebalanceTracker::new();

        // Get child token before rebalance starts
        let token = tracker.get_export_token();
        assert!(!token.is_cancelled(), "Token should not be cancelled yet");

        // Start first rebalance (0 -> 1 transition)
        tracker.start_rebalancing();

        // Token should be cancelled now
        assert!(
            token.is_cancelled(),
            "Export token should be cancelled when first rebalance starts"
        );
    }

    #[test]
    fn test_export_token_stays_cancelled_during_overlapping_rebalances() {
        let tracker = RebalanceTracker::new();

        // Start first rebalance
        tracker.start_rebalancing();
        let token_during_first = tracker.get_export_token();
        assert!(
            token_during_first.is_cancelled(),
            "Token should be cancelled during first rebalance"
        );

        // Start second overlapping rebalance
        tracker.start_rebalancing();
        assert_eq!(tracker.rebalancing_count(), 2);

        // Token should still be cancelled
        let token_during_second = tracker.get_export_token();
        assert!(
            token_during_second.is_cancelled(),
            "Token should stay cancelled during overlapping rebalances"
        );

        // First rebalance finishes
        tracker.finish_rebalancing();
        assert_eq!(tracker.rebalancing_count(), 1);

        // Token should STILL be cancelled (count is still > 0)
        let token_after_first_finish = tracker.get_export_token();
        assert!(
            token_after_first_finish.is_cancelled(),
            "Token should stay cancelled while any rebalance is in progress"
        );
    }

    #[test]
    fn test_export_token_refreshed_when_all_rebalances_complete() {
        let tracker = RebalanceTracker::new();

        // Get initial token
        let initial_token = tracker.get_export_token();
        assert!(!initial_token.is_cancelled());

        // Start and complete a rebalance
        tracker.start_rebalancing();
        assert!(initial_token.is_cancelled(), "Token cancelled on rebalance");

        tracker.finish_rebalancing();

        // Initial token should STILL be cancelled (it's a child of the old cancelled token)
        assert!(
            initial_token.is_cancelled(),
            "Old child tokens stay cancelled after refresh"
        );

        // But NEW tokens should NOT be cancelled
        let new_token = tracker.get_export_token();
        assert!(
            !new_token.is_cancelled(),
            "New tokens should not be cancelled after all rebalances complete"
        );
    }

    #[test]
    fn test_export_token_multiple_rebalance_cycles() {
        let tracker = RebalanceTracker::new();

        // Cycle 1
        let token1 = tracker.get_export_token();
        tracker.start_rebalancing();
        assert!(token1.is_cancelled());
        tracker.finish_rebalancing();

        // After cycle 1, new token should work
        let token2 = tracker.get_export_token();
        assert!(!token2.is_cancelled());

        // Cycle 2
        tracker.start_rebalancing();
        assert!(token2.is_cancelled());
        tracker.finish_rebalancing();

        // After cycle 2, new token should work
        let token3 = tracker.get_export_token();
        assert!(!token3.is_cancelled());
    }

    #[test]
    fn test_export_token_child_inherits_cancelled_state() {
        let tracker = RebalanceTracker::new();

        // Start rebalance to cancel the token
        tracker.start_rebalancing();

        // Child tokens obtained during rebalance should already be cancelled
        let child = tracker.get_export_token();
        assert!(
            child.is_cancelled(),
            "Child tokens obtained during rebalance should be pre-cancelled"
        );
    }

    #[test]
    fn test_export_token_with_guard() {
        let tracker = Arc::new(RebalanceTracker::new());

        let token = tracker.get_export_token();
        assert!(!token.is_cancelled());

        tracker.start_rebalancing();
        {
            let _guard = tracker.rebalancing_guard();
            // Token cancelled during rebalance
            assert!(token.is_cancelled());
        } // guard drops, calls finish_rebalancing

        // Token should STAY cancelled (it was a child of the old parent)
        assert!(token.is_cancelled());

        // New token should NOT be cancelled
        let new_token = tracker.get_export_token();
        assert!(!new_token.is_cancelled());
    }
}
