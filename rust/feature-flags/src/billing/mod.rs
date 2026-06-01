//! Billing counters for the feature-flags service.
//!
//! - The authoritative billing write is the synchronous per-request
//!   [`crate::flags::flag_analytics::increment_request_count`].
//! - [`aggregator`] is a *shadow* writer that targets `…:shadow`-suffixed
//!   keys via [`crate::flags::flag_analytics::get_team_request_shadow_key`],
//!   for reconciliation against the authoritative path.
//! - [`limiters`] reads the production counters to enforce per-tenant quotas.

pub mod aggregator;
pub mod limiters;

pub use aggregator::{AggregationKey, BillingAggregator, BillingAggregatorConfig};
pub use limiters::{FeatureFlagsLimiter, SessionReplayLimiter};
