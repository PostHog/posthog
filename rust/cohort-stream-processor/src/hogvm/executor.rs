//! Run compiled cohort-filter bytecode through `hogvm::sync_execute`, coercing the result to the
//! boolean Stage 1 needs (matching the Node consumer's `execResult?.result ?? false`).

use hogvm::{sync_execute, ExecutionContext, Program, VmError};
use metrics::counter;
use serde_json::Value;

use crate::observability::metrics::{STAGE1_HOGVM_ERROR, STAGE1_HOGVM_UNKNOWN_FUNCTION};

/// HogVM `RETURN` opcode. See [`evaluate_detailed`] for why it is appended to every program.
const OP_RETURN: i64 = 38;

/// The classified outcome of evaluating one program; [`evaluate`] collapses this to a `bool` but
/// the variants preserve *why* a non-match happened.
#[derive(Debug)]
pub enum EvalOutcome {
    Matched(bool),
    /// A `CALL_GLOBAL`/symbol with no registered Rust native; carries the name for the metric label.
    UnknownFunction(String),
    VmError(VmError),
}

/// Evaluate `bytecode` against `globals`, returning the detailed [`EvalOutcome`].
///
/// Cohort bytecode ends with its root comparison op and no `RETURN`. Python/Node return the
/// top-of-stack value when running off the end, but the Rust VM treats that as a fatal
/// `EndOfProgram`; appending a `RETURN` recovers the shared semantic. A program already ending in
/// `RETURN` finishes first, so the append is safe for both shapes.
pub fn evaluate_detailed(bytecode: &[Value], globals: Value) -> EvalOutcome {
    let mut with_return = Vec::with_capacity(bytecode.len() + 1);
    with_return.extend_from_slice(bytecode);
    with_return.push(Value::from(OP_RETURN));

    // `with_defaults` rebuilds the stl maps and `Program` is not `Clone`, so a per-event
    // `Program::new` + `with_defaults` is the only API path.
    let program = match Program::new(with_return) {
        Ok(program) => program,
        Err(error) => return classify_failure(error),
    };
    let context = ExecutionContext::with_defaults(program).with_globals(globals);

    match sync_execute(&context, false) {
        Ok(result) => EvalOutcome::Matched(result.as_bool().unwrap_or(false)),
        Err(failure) => classify_failure(failure.error),
    }
}

/// Hot-path wrapper: coerces failures and non-bool results to `false`, emitting a per-failure-class
/// metric so a silently-failing cohort stays observable.
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

/// A missing native surfaces as either `UnknownFunction` or `UnknownSymbol`; both collapse to one
/// metric. `VmError` is `#[non_exhaustive]`, so the catch-all arm is mandatory.
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
        let bc = [header(), vec![json!(OP_INTEGER), json!(42)]].concat();
        assert!(matches!(
            evaluate_detailed(&bc, json!({})),
            EvalOutcome::Matched(false)
        ));
        assert!(!evaluate(&bc, json!({})));
    }

    #[test]
    fn compiled_style_bytecode_without_trailing_return_still_evaluates() {
        // Regression guard for the appended-RETURN bridge: cohort bytecode ends with its comparison
        // op and no RETURN, which the bare Rust VM would reject with EndOfProgram.
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
        // `is_date_before` leaf `Lt(toDateTime(toString(person.properties.signup_date)),
        // toDateTime("2026-01-01 00:00:00"))`; the compiler emits `right, left, op`.
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
        // Missing → not: the null comparison errors and `evaluate` coerces it to false, matching
        // the leaf's null-safe guard.
        assert!(evaluate(&bc, globals(json!("2024-09-09 08:30:00"))));
        assert!(!evaluate(&bc, globals(json!("2027-09-09 08:30:00"))));
        assert!(!evaluate(&bc, json!({ "person": { "properties": {} } })));
    }

    #[test]
    fn numeric_gt_person_cohort_coerces_the_string_threshold() {
        // The compiler emits the threshold as a string, so the leaf is
        // `Gt(person.properties.bc_num, "10")`; string→number coercion makes it numeric.
        let mut bc = vec![json!("_H"), json!(1)];
        bc.extend_from_slice(&[json!(OP_STRING), json!("10")]);
        bc.extend_from_slice(&push_person_property("bc_num"));
        bc.push(json!(OP_GT));

        let globals = |num: Value| json!({ "person": { "properties": { "bc_num": num } } });
        assert!(evaluate(&bc, globals(json!(20))));
        assert!(!evaluate(&bc, globals(json!(5))));
        // Equal-length numeric *string* property: lexicographic, which agrees with numeric here
        // (the both-strings divergence only bites on unequal lengths).
        assert!(evaluate(&bc, globals(json!("20"))));
        assert!(!evaluate(&bc, globals(json!("05"))));
    }
}
