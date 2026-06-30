//! Stage 2: per-person Boolean composition of a cohort's leaves into membership flips.

pub mod eligibility;
pub mod evaluator;
pub mod state;

pub use eligibility::{classify, CohortEligibility, CohortParseFlags, ExcludedReason};
pub use evaluator::{evaluate_tree, leaf_membership};
pub use state::Stage2State;
