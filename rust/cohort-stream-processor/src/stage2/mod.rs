//! Stage 2: per-person Boolean composition of a cohort's leaves into membership flips.
//!
//! Provides the parse-time [`eligibility`] classification: which cohorts compose, and which must
//! not emit.

pub mod eligibility;

pub use eligibility::{classify, CohortEligibility, CohortParseFlags, ExcludedReason};
