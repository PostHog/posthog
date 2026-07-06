//! Per-team rule kinds the processing pipeline evaluates: assignment,
//! suppression, spike-alerting, and grouping (custom fingerprints). Cached
//! together by `crate::modes::processing::teams::TeamManager`.

pub mod assignment;
pub mod bypass;
pub mod grouping;
pub mod rate_limit;
pub mod spike;
pub mod suppression;
