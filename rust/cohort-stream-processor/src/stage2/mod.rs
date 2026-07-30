//! Stage 2: per-person Boolean composition of a cohort's leaves into membership flips.

pub mod evaluator;
mod register;
pub mod state;

pub use cohort_core::eligibility;
pub use eligibility::{classify, CohortEligibility, CohortParseFlags, ExcludedReason};
pub use evaluator::{evaluate_tree, leaf_membership};
pub(crate) use register::{
    single_leaf_register_writes, single_leaf_transition_register_writes, stage_register_writes,
    MembershipRegisterSource,
};
pub use state::Stage2State;
