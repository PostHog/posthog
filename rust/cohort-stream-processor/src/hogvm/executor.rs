//! Run compiled cohort-filter bytecode through `hogvm::sync_execute`, coercing the result to the
//! boolean Stage 1 needs (matching the Node consumer's `execResult?.result ?? false`).
//!
//! The hot path reuses one [`CohortEvaluator`] per event: the STL context and globals are set once
//! and only the program is swapped per condition, amortizing the context build across all conditions.

use std::sync::Arc;

use hogvm::{sync_execute, ExecutionContext, Program, VmError};
use metrics::counter;
use serde_json::Value;
use tracing::debug;

use crate::observability::metrics::{STAGE1_HOGVM_ERROR, STAGE1_HOGVM_UNKNOWN_FUNCTION};

/// The classified outcome of evaluating one program; [`CohortEvaluator::evaluate`] collapses this to
/// a `bool` but the variants preserve *why* a non-match happened.
#[derive(Debug)]
pub enum EvalOutcome {
    Matched(bool),
    /// A `CALL_GLOBAL`/symbol with no registered Rust native; carries the name for the metric label.
    UnknownFunction(String),
    VmError(VmError),
}

/// A reusable evaluator owning one [`ExecutionContext`]: set globals once per event, swap the program
/// per condition, both in place.
///
/// Comparisons are coercing (cross-type ordering + epoch temporal ordering/equality) to match the
/// Python/TS/ClickHouse reference; opt-in, so other `hogvm` consumers like cymbal keep strict ones.
pub struct CohortEvaluator {
    context: ExecutionContext,
}

impl Default for CohortEvaluator {
    fn default() -> Self {
        Self::new()
    }
}

impl CohortEvaluator {
    pub fn new() -> Self {
        // A bare header is a valid program; `set_program` replaces this seed before the first evaluation.
        let seed = Program::new(vec![Value::from("_H"), Value::from(1)])
            .expect("a bare bytecode header is a valid program");
        let context = ExecutionContext::with_defaults(seed).with_coercing_comparisons();
        Self { context }
    }

    /// Move `globals` into the reused context (no clone); one call serves a whole event's conditions.
    pub fn set_globals(&mut self, globals: Value) {
        self.context.set_globals(globals);
    }

    /// Evaluate one condition's bytecode against the current globals, coercing failures and non-bool
    /// results to `false` and emitting a per-class metric so a silently-failing cohort stays
    /// observable. `bytecode` must be `RETURN`-terminated (the loader appends it).
    pub fn evaluate(&mut self, bytecode: Arc<Vec<Value>>) -> bool {
        outcome_to_bool(self.evaluate_detailed(bytecode))
    }

    /// As [`Self::evaluate`] but returns the detailed [`EvalOutcome`].
    pub fn evaluate_detailed(&mut self, bytecode: Arc<Vec<Value>>) -> EvalOutcome {
        // `from_shared` clones the `Arc`, not the opcode vector, so swapping programs is just a refcount bump.
        let program = match Program::from_shared(bytecode) {
            Ok(program) => program,
            Err(error) => return classify_failure(error),
        };
        self.context.set_program(program);
        run(&self.context)
    }
}

/// Run `context` to completion, collapsing the VM result to an [`EvalOutcome`]. `unwrap_or(false)`
/// mirrors the Node `?? false` coercion of a non-bool result.
fn run(context: &ExecutionContext) -> EvalOutcome {
    match sync_execute(context, false) {
        Ok(result) => EvalOutcome::Matched(result.as_bool().unwrap_or(false)),
        Err(failure) => classify_failure(failure.error),
    }
}

/// One-shot evaluation building a fresh context (used by the parity test). `bytecode` must be
/// `RETURN`-terminated, as the catalog loader leaves it.
pub fn evaluate_detailed(bytecode: &[Value], globals: Value) -> EvalOutcome {
    let program = match Program::new(bytecode.to_vec()) {
        Ok(program) => program,
        Err(error) => return classify_failure(error),
    };
    let context = ExecutionContext::with_defaults(program)
        .with_globals(globals)
        .with_coercing_comparisons();
    run(&context)
}

pub fn evaluate(bytecode: &[Value], globals: Value) -> bool {
    outcome_to_bool(evaluate_detailed(bytecode, globals))
}

/// Collapse an [`EvalOutcome`] to `bool`, emitting a per-class metric on failure.
fn outcome_to_bool(outcome: EvalOutcome) -> bool {
    match outcome {
        EvalOutcome::Matched(matched) => matched,
        EvalOutcome::UnknownFunction(name) => {
            // `name` is bytecode-derived from user cohort filters; keep it out of the metric label
            // (bounded counter) and surface the specific function only in a debug log.
            counter!(STAGE1_HOGVM_UNKNOWN_FUNCTION).increment(1);
            debug!(function = %name, "cohort bytecode called a function with no registered Rust native");
            false
        }
        EvalOutcome::VmError(_) => {
            counter!(STAGE1_HOGVM_ERROR).increment(1);
            false
        }
    }
}

/// `UnknownFunction` and `UnknownSymbol` collapse to the same metric. The catch-all arm is
/// mandatory because `VmError` is `#[non_exhaustive]`.
fn classify_failure(error: VmError) -> EvalOutcome {
    match error {
        VmError::UnknownFunction(name) | VmError::UnknownSymbol(name) => {
            EvalOutcome::UnknownFunction(name)
        }
        other => EvalOutcome::VmError(other),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    const OP_GET_GLOBAL: i64 = 1;
    const OP_CALL_GLOBAL: i64 = 2;
    const OP_EQ: i64 = 11;
    const OP_GT: i64 = 13;
    const OP_LT: i64 = 15;
    const OP_TRUE: i64 = 29;
    const OP_FALSE: i64 = 30;
    const OP_INTEGER: i64 = 33;
    const OP_STRING: i64 = 32;
    // Fixtures terminate explicitly with RETURN, mirroring what the catalog loader stores.
    const OP_RETURN: i64 = 38;

    fn header() -> Vec<Value> {
        vec![json!("_H"), json!(1)]
    }

    #[test]
    fn true_literal_coerces_to_true() {
        let bc = [header(), vec![json!(OP_TRUE), json!(OP_RETURN)]].concat();
        assert!(matches!(
            evaluate_detailed(&bc, json!({})),
            EvalOutcome::Matched(true)
        ));
    }

    #[test]
    fn false_literal_coerces_to_false() {
        let bc = [header(), vec![json!(OP_FALSE), json!(OP_RETURN)]].concat();
        assert!(matches!(
            evaluate_detailed(&bc, json!({})),
            EvalOutcome::Matched(false)
        ));
    }

    #[test]
    fn non_boolean_result_coerces_to_false() {
        let bc = [
            header(),
            vec![json!(OP_INTEGER), json!(42), json!(OP_RETURN)],
        ]
        .concat();
        assert!(matches!(
            evaluate_detailed(&bc, json!({})),
            EvalOutcome::Matched(false)
        ));
        assert!(!evaluate(&bc, json!({})));
    }

    #[test]
    fn compiled_style_bytecode_evaluates() {
        let bc = [
            header(),
            vec![
                json!(OP_STRING),
                json!("$pageview"),
                json!(OP_STRING),
                json!("event"),
                json!(OP_GET_GLOBAL),
                json!(1),
                json!(OP_EQ),
                json!(OP_RETURN),
            ],
        ]
        .concat();
        assert!(evaluate(&bc, json!({ "event": "$pageview" })));
        assert!(!evaluate(&bc, json!({ "event": "$autocapture" })));
    }

    #[test]
    fn unknown_call_global_is_classified_as_unknown_function() {
        let bc = [
            header(),
            vec![
                json!(OP_CALL_GLOBAL),
                json!("definitelyNotANative"),
                json!(0),
            ],
        ]
        .concat();
        match evaluate_detailed(&bc, json!({})) {
            EvalOutcome::UnknownFunction(name) => assert_eq!(name, "definitelyNotANative"),
            other => panic!("expected UnknownFunction, got {other:?}"),
        }
        assert!(!evaluate(&bc, json!({})));
    }

    #[test]
    fn malformed_program_is_a_vm_error() {
        assert!(matches!(
            evaluate_detailed(&[], json!({})),
            EvalOutcome::VmError(_)
        ));
        assert!(!evaluate(&[], json!({})));
    }

    /// Build opcodes to read `person.properties.<key>`. GET_GLOBAL consumes path segments in
    /// reverse push order.
    fn push_person_property(key: &str) -> Vec<Value> {
        vec![
            json!(OP_STRING),
            json!(key),
            json!(OP_STRING),
            json!("properties"),
            json!(OP_STRING),
            json!("person"),
            json!(OP_GET_GLOBAL),
            json!(3),
        ]
    }

    #[test]
    fn is_date_before_person_cohort_enters_and_leaves() {
        // `Lt(toDateTime(toString(person.properties.signup_date)), toDateTime("2026-01-01 00:00:00"))`
        // — compiler emits `right, left, op`.
        let mut left = push_person_property("signup_date");
        left.extend_from_slice(&[
            json!(OP_CALL_GLOBAL),
            json!("toString"),
            json!(1),
            json!(OP_CALL_GLOBAL),
            json!("toDateTime"),
            json!(1),
        ]);
        let right = vec![
            json!(OP_STRING),
            json!("2026-01-01 00:00:00"),
            json!(OP_CALL_GLOBAL),
            json!("toDateTime"),
            json!(1),
        ];
        let mut bc = vec![json!("_H"), json!(1)];
        bc.extend_from_slice(&right);
        bc.extend_from_slice(&left);
        bc.push(json!(OP_LT));
        bc.push(json!(OP_RETURN));

        let globals =
            |signup: Value| json!({ "person": { "properties": { "signup_date": signup } } });
        assert!(evaluate(&bc, globals(json!("2024-09-09 08:30:00"))));
        assert!(!evaluate(&bc, globals(json!("2027-09-09 08:30:00"))));
        assert!(!evaluate(&bc, json!({ "person": { "properties": {} } })));
    }

    #[test]
    fn reused_evaluator_matches_a_fresh_context_per_eval() {
        // Interleave programs and globals so a stale-globals or un-swapped-program leak would diverge
        // from a fresh-context-per-eval baseline.
        let email_eq = {
            let mut bc = header();
            bc.extend_from_slice(&[json!(OP_STRING), json!("a@b.com")]);
            bc.extend_from_slice(&push_person_property("email"));
            bc.extend_from_slice(&[json!(OP_EQ), json!(OP_RETURN)]);
            bc
        };
        let num_gt = {
            let mut bc = header();
            bc.extend_from_slice(&[json!(OP_STRING), json!("10")]);
            bc.extend_from_slice(&push_person_property("bc_num"));
            bc.extend_from_slice(&[json!(OP_GT), json!(OP_RETURN)]);
            bc
        };
        let g_match = json!({ "person": { "properties": { "email": "a@b.com", "bc_num": 20 } } });
        let g_miss = json!({ "person": { "properties": { "email": "x@y.com", "bc_num": 5 } } });

        let cases: [(&Vec<Value>, &Value); 5] = [
            (&email_eq, &g_match),
            (&num_gt, &g_match),
            (&email_eq, &g_miss),
            (&num_gt, &g_miss),
            (&email_eq, &g_match),
        ];

        let mut evaluator = CohortEvaluator::new();
        for (bytecode, globals) in cases {
            evaluator.set_globals(globals.clone());
            let reused = evaluator.evaluate(Arc::new(bytecode.clone()));
            let fresh = evaluate(bytecode, globals.clone());
            assert_eq!(
                reused, fresh,
                "reused evaluator diverged from a fresh per-eval context",
            );
        }
    }

    #[test]
    fn numeric_gt_person_cohort_coerces_the_string_threshold() {
        // Compiler emits the threshold as a string: `Gt(person.properties.bc_num, "10")`.
        // Coercing comparisons promote both sides to numeric, matching ClickHouse/TS behaviour.
        let mut bc = vec![json!("_H"), json!(1)];
        bc.extend_from_slice(&[json!(OP_STRING), json!("10")]);
        bc.extend_from_slice(&push_person_property("bc_num"));
        bc.push(json!(OP_GT));
        bc.push(json!(OP_RETURN));

        let globals = |num: Value| json!({ "person": { "properties": { "bc_num": num } } });
        assert!(evaluate(&bc, globals(json!(20))));
        assert!(!evaluate(&bc, globals(json!(5))));
        assert!(evaluate(&bc, globals(json!("20"))));
        assert!(!evaluate(&bc, globals(json!("05"))));
    }
}
