//! Evaluate compiled cohort-filter bytecode against an event, coercing non-bool results to
//! `false` to match the Node consumer.

mod executor;
mod globals;

pub use executor::{
    classify_vm_error, evaluate, evaluate_detailed, CohortEvaluator, EvalOutcome, VmErrorClass,
};
pub use globals::{build_behavioral_globals, build_person_property_globals, GlobalsError};
