//! Shared test utilities for the kafka-deduplicator crate.
//!
//! This module provides common test helpers to avoid duplication across test files.

use std::sync::Arc;

use crate::rebalance_tracker::RebalanceTracker;

/// Creates a test `RebalanceTracker`.
///
/// This is a convenience function that wraps `RebalanceTracker::new()` in an `Arc`.
pub fn create_test_tracker() -> Arc<RebalanceTracker> {
    Arc::new(RebalanceTracker::new())
}

// The store manager creation functions that require tempfile are kept in individual test
// modules since tempfile is a dev-dependency and not available in non-test builds.

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_create_test_tracker() {
        let tracker = create_test_tracker();
        assert!(!tracker.is_rebalancing());
    }
}
