//! Evaluate compiled cohort-filter bytecode against an event, coercing non-bool results to
//! `false` to match the Node consumer.
//!
//! ## Metric-emission contract
//!
//! The `bool`-collapsing path ([`CohortEvaluator::evaluate`]) is self-counting: a failed result (VM
//! error or unknown function) increments a `STAGE1_HOGVM_*` counter, while a non-bool result is
//! coerced to `false` silently. That is the processor's path. The
//! [`EvalOutcome`]-returning path ([`CohortEvaluator::evaluate_detailed`] and [`evaluate_detailed`])
//! is bring-your-own-metrics: it emits nothing and hands the caller the classified outcome. The
//! seeder uses it so failures land on its own `seeder_hogvm_*` counters, not these.

mod executor;
mod globals;

pub use executor::{
    classify_vm_error, evaluate_detailed, CohortEvaluator, EvalOutcome, VmErrorClass,
};
pub use globals::{build_behavioral_globals, build_person_property_globals, GlobalsError};
