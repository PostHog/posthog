//! Billing counters for the feature-flags service.
//!
//! - In `AggregatorMode::Shadow`, the authoritative billing write is the
//!   synchronous per-request
//!   [`crate::flags::flag_analytics::increment_request_count`], and
//!   [`aggregator`] tees a parallel write to `…:shadow`-suffixed keys via
//!   [`crate::flags::flag_analytics::get_team_request_shadow_key`] for
//!   offline reconciliation.
//! - In `AggregatorMode::Authoritative`, [`aggregator`] *is* the
//!   authoritative writer — it writes the production billing keys and the
//!   per-request synchronous HINCRBY is skipped.
//! - [`limiters`] reads the production counters to enforce per-tenant
//!   quotas; the same keys are read regardless of mode.

pub mod aggregator;
pub mod limiters;

pub use aggregator::{AggregationKey, AggregatorMode, BillingAggregator, BillingAggregatorConfig};
pub use limiters::{FeatureFlagsLimiter, SessionReplayLimiter};
