//! HogVM execution wrapper (TDD §5.2, M8.b–c).
//!
//! Runs compiled cohort-filter bytecode through `hogvm::sync_execute` and coerces the result to
//! the boolean Stage 1 needs, matching the Node consumer's `execResult?.result ?? false`
//! (`cdp-precalculated-filters.consumer.ts:129`, TDD §2.4). PR 1.6 wires the catalog
//! (`by_condition_to_bytecode`) + [`crate::hogvm::globals`] into [`evaluate`]; this PR ships the
//! wrapper standalone.

use hogvm::{sync_execute, ExecutionContext, Program, VmError};
use metrics::counter;
use serde_json::Value;

use crate::observability::metrics::{STAGE1_HOGVM_ERROR, STAGE1_HOGVM_UNKNOWN_FUNCTION};

/// HogVM `RETURN` opcode (`common/hogvm/python/operation.py`). See [`evaluate_detailed`] for why
/// it is appended to every program.
const OP_RETURN: i64 = 38;

/// The classified outcome of evaluating one bytecode program — for tests and canonical logging.
/// [`evaluate`] collapses this to a `bool`; this variant set preserves *why* a non-match happened.
#[derive(Debug)]
pub enum EvalOutcome {
    /// The program ran to completion; the boolean is its result coerced via `as_bool`.
    Matched(bool),
    /// The program referenced a `CALL_GLOBAL`/symbol with no registered Rust native — the M0
    /// survey missed it. Carries the function/symbol name for the metric label.
    UnknownFunction(String),
    /// Any other VM or program-construction failure.
    VmError(VmError),
}

/// Evaluate `bytecode` against `globals`, returning the detailed [`EvalOutcome`].
///
/// ## Trailing `RETURN` (cross-runtime parity)
///
/// Compiled cohort bytecode (`create_bytecode`, `posthog/api/cohort.py:174`) ends with its root
/// comparison op and **no** `RETURN`. The Python and Node runtimes return the top-of-stack value
/// when they run off the end of the program (`common/hogvm/python/execute.py:197-204`), but the
/// Rust VM treats that as a fatal `EndOfProgram` error (`rust/common/hogvm/src/context.rs:154`).
/// Left unbridged, *every* real cohort would coerce to `false`. Appending a `RETURN` recovers the
/// shared semantic: hitting it with no call frames makes the VM finish with the top-of-stack value
/// (`rust/common/hogvm/src/vm.rs:329-334`). A program that already ends in `RETURN` finishes before
/// reaching the appended op, so the append is safe for both shapes.
pub fn evaluate_detailed(bytecode: &[Value], globals: Value) -> EvalOutcome {
    let mut with_return = Vec::with_capacity(bytecode.len() + 1);
    with_return.extend_from_slice(bytecode);
    with_return.push(Value::from(OP_RETURN));

    // PERF (M9): `with_defaults` rebuilds stl_map()+hog_stl_map() on every call (context.rs:15 TODO
    // to borrow the native map) and `Program` is not `Clone`, so a per-event `Program::new` +
    // `with_defaults` is the only API path. Correctness-first for parity; flagged as an M9 perf item.
    let program = match Program::new(with_return) {
        Ok(program) => program,
        Err(error) => return classify_failure(error),
    };
    let context = ExecutionContext::with_defaults(program).with_globals(globals);

    match sync_execute(&context, false) {
        // Node coercion: every supported cohort expr has a boolean root, so
        // `as_bool().unwrap_or(false)` agrees with `execResult?.result ?? false` (TDD §2.4).
        Ok(result) => EvalOutcome::Matched(result.as_bool().unwrap_or(false)),
        Err(failure) => classify_failure(failure.error),
    }
}

/// Hot-path wrapper — PR 1.6's entry point. Coerces every failure and non-bool result to `false`
/// (TDD §2.4) and emits the per-failure-class metric so a silently-failing cohort is observable.
pub fn evaluate(bytecode: &[Value], globals: Value) -> bool {
    match evaluate_detailed(bytecode, globals) {
        EvalOutcome::Matched(matched) => matched,
        EvalOutcome::UnknownFunction(name) => {
            counter!(STAGE1_HOGVM_UNKNOWN_FUNCTION, "name" => name).increment(1);
            false
        }
        EvalOutcome::VmError(_) => {
            counter!(STAGE1_HOGVM_ERROR).increment(1);
            false
        }
    }
}

/// A missing native surfaces as either `UnknownFunction` (a bare `CALL_GLOBAL`) or `UnknownSymbol`
/// (an imported module symbol); both mean "the M0 survey missed a native" and share one metric.
/// Everything else is an opaque VM error. `VmError` is `#[non_exhaustive]`, so the catch-all arm
/// is mandatory.
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

    // Opcode numeric values (mirror common/hogvm/python/operation.py).
    const OP_GET_GLOBAL: i64 = 1;
    const OP_CALL_GLOBAL: i64 = 2;
    const OP_EQ: i64 = 11;
    const OP_GT: i64 = 13;
    const OP_LT: i64 = 15;
    const OP_TRUE: i64 = 29;
    const OP_FALSE: i64 = 30;
    const OP_INTEGER: i64 = 33;
    const OP_STRING: i64 = 32;

    fn header() -> Vec<Value> {
        vec![json!("_H"), json!(1)]
    }

    #[test]
    fn true_literal_coerces_to_true() {
        let bc = [header(), vec![json!(OP_TRUE)]].concat();
        assert!(matches!(
            evaluate_detailed(&bc, json!({})),
            EvalOutcome::Matched(true)
        ));
    }

    #[test]
    fn false_literal_coerces_to_false() {
        let bc = [header(), vec![json!(OP_FALSE)]].concat();
        assert!(matches!(
            evaluate_detailed(&bc, json!({})),
            EvalOutcome::Matched(false)
        ));
    }

    #[test]
    fn non_boolean_result_coerces_to_false() {
        // An integer-valued program: `as_bool()` is `None`, so it must coerce to `false`.
        let bc = [header(), vec![json!(OP_INTEGER), json!(42)]].concat();
        assert!(matches!(
            evaluate_detailed(&bc, json!({})),
            EvalOutcome::Matched(false)
        ));
        assert!(!evaluate(&bc, json!({})));
    }

    #[test]
    fn compiled_style_bytecode_without_trailing_return_still_evaluates() {
        // Regression guard for the appended-RETURN bridge: real cohort bytecode ends with its
        // comparison op (here `event == "$pageview"`) and no RETURN, which the bare Rust VM would
        // reject with EndOfProgram.
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
        // And the hot-path wrapper coerces it to `false`.
        assert!(!evaluate(&bc, json!({})));
    }

    #[test]
    fn malformed_program_is_a_vm_error() {
        // Empty bytecode (no `_H` marker) fails `Program::new`.
        assert!(matches!(
            evaluate_detailed(&[], json!({})),
            EvalOutcome::VmError(_)
        ));
        assert!(!evaluate(&[], json!({})));
    }

    /// Push `person.properties.<key>` (GET_GLOBAL reads the path segments in reverse push order).
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
        // The realistic `is_date_before` leaf (F2): `Lt(toDateTime(toString(person.properties.
        // signup_date)), toDateTime("2026-01-01 00:00:00"))`. The compiler emits `right, left, op`.
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

        let globals =
            |signup: Value| json!({ "person": { "properties": { "signup_date": signup } } });
        // Before the threshold → member; after → not; missing → not (the null comparison errors and
        // `evaluate` coerces it to false, matching the leaf's null-safe guard).
        assert!(evaluate(&bc, globals(json!("2024-09-09 08:30:00"))));
        assert!(!evaluate(&bc, globals(json!("2027-09-09 08:30:00"))));
        assert!(!evaluate(&bc, json!({ "person": { "properties": {} } })));
    }

    #[test]
    fn numeric_gt_person_cohort_coerces_the_string_threshold() {
        // The F3 cohort case: the compiler emits the threshold as a *string* constant, so the leaf is
        // `Gt(person.properties.bc_num, "10")`. Pre-fix the VM errored on the string operand and the
        // cohort never entered; now String→Number coercion (because the other side is a Number) makes
        // it correct.
        let mut bc = vec![json!("_H"), json!(1)];
        bc.extend_from_slice(&[json!(OP_STRING), json!("10")]); // right (threshold)
        bc.extend_from_slice(&push_person_property("bc_num")); // left
        bc.push(json!(OP_GT));

        let globals = |num: Value| json!({ "person": { "properties": { "bc_num": num } } });
        // Numeric property: real numeric comparison.
        assert!(evaluate(&bc, globals(json!(20))));
        assert!(!evaluate(&bc, globals(json!(5))));
        // Equal-length numeric *string* property: lexicographic, which agrees with numeric here
        // (the both-strings divergence only bites on unequal lengths — see hogvm numeric_coercion).
        assert!(evaluate(&bc, globals(json!("20"))));
        assert!(!evaluate(&bc, globals(json!("05"))));
    }
}
