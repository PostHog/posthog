//! HogVM execution wrapper (TDD §5.2, M8.a–c).
//!
//! Wraps `hogvm::sync_execute` (`rust/common/hogvm/src/vm.rs:903`) to evaluate compiled
//! cohort-filter bytecode against an event, building the globals dict via the Rust port of
//! `convertClickhouseRawEventToFilterGlobals`. Non-bool results coerce to `false`, matching the
//! Node consumer. Submodules:
//! - `executor` — wraps `hogvm::sync_execute`; surfaces unknown CALL_GLOBALs as a metric (PR 1.4)
//! - `globals`  — `CohortStreamEvent` → HogVM globals dict (M8.c port; PR 1.4)

mod executor;
mod globals;

pub use executor::{evaluate, evaluate_detailed, EvalOutcome};
pub use globals::{build_behavioral_globals, build_person_property_globals, GlobalsError};
