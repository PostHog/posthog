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
use tracing::{info, warn};

use crate::metrics_const::REBALANCING_COUNT;

/// Coordinates rebalance state across multiple components.
///
/// This is a lightweight struct (~8 bytes) that can be cheaply cloned via `Arc`.
/// It provides the single source of truth for whether a rebalance is in progress.
pub struct RebalanceCoordinator {
    /// Counter tracking the number of in-progress rebalances.
    /// Using a counter (not bool) correctly handles overlapping rebalances.
    rebalancing_count: AtomicUsize,
}

impl RebalanceCoordinator {
    /// Create a new coordinator with the counter initialized to 0.
    pub fn new() -> Self {
        Self {
            rebalancing_count: AtomicUsize::new(0),
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
}
