//! Billing counters for the feature-flags service.
//!
//! - [`aggregator`] is the authoritative writer for the production billing
//!   keyspace. Each pod aggregates billable requests in memory and flushes
//!   them to Redis on a periodic tick (and on graceful shutdown).
//! - [`limiters`] reads the same counters to enforce per-tenant quotas.

pub mod aggregator;
pub mod limiters;
pub mod usage_reporter;
#[cfg(test)]
pub mod usage_test_support;

pub use aggregator::{AggregationKey, BillingAggregator, BillingAggregatorConfig};
pub use limiters::{FeatureFlagsLimiter, SessionReplayLimiter};
pub use usage_reporter::UsageReporter;
