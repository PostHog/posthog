//! Evaluate compiled cohort-filter bytecode against an event, coercing non-bool results to
//! `false` to match the Node consumer.

mod executor;
mod globals;

pub use executor::{evaluate, evaluate_detailed, CohortEvaluator, EvalOutcome};
pub use globals::{build_behavioral_globals, build_person_property_globals, GlobalsError};
