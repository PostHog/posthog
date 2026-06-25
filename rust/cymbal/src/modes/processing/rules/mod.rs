//! Per-team rule kinds the processing pipeline evaluates: assignment,
//! suppression, spike-alerting, and grouping (custom fingerprints). Cached
//! together by `crate::modes::processing::teams::TeamManager`.

pub mod assignment;
pub mod grouping;
pub mod spike;
pub mod suppression;
