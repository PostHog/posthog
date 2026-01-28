//! Shared test utilities for the kafka-deduplicator crate.
//!
//! This module provides common test helpers to avoid duplication across test files.

use std::sync::Arc;

use crate::rebalance_coordinator::RebalanceCoordinator;

/// Creates a test `RebalanceCoordinator`.
///
/// This is a convenience function that wraps `RebalanceCoordinator::new()` in an `Arc`.
pub fn create_test_coordinator() -> Arc<RebalanceCoordinator> {
    Arc::new(RebalanceCoordinator::new())
}

// The store manager creation functions that require tempfile are kept in individual test
// modules since tempfile is a dev-dependency and not available in non-test builds.

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_create_test_coordinator() {
        let coordinator = create_test_coordinator();
        assert!(!coordinator.is_rebalancing());
    }
}
