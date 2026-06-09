//! Stage 2: per-person Boolean composition of a cohort's leaves into membership flips.
//!
//! - [`eligibility`] — the parse-time classification: which cohorts compose, and which must not emit.
//! - [`evaluator`] — the pure AND/OR composition over leaf membership ([`leaf_membership`],
//!   [`evaluate_tree`]); the store-driving orchestration lives in
//!   [`workers::stage2_path`](crate::workers::stage2_path).
//! - [`state`] — the persisted [`Stage2State`] `cf_stage2` value.

pub mod eligibility;
pub mod evaluator;
pub mod state;

pub use eligibility::{classify, CohortEligibility, CohortParseFlags, ExcludedReason};
pub use evaluator::{evaluate_tree, leaf_membership};
pub use state::Stage2State;
