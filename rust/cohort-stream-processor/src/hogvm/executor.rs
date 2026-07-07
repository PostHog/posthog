//! Run compiled cohort-filter bytecode through `hogvm::sync_execute`, coercing the result to the
//! boolean Stage 1 needs (matching the Node consumer's `execResult?.result ?? false`).
//!
//! The hot path reuses one [`CohortEvaluator`] per event: the STL context and globals are set once
//! and only the program is swapped per condition, amortizing the context build across all conditions.

use std::sync::{Arc, LazyLock};

use dashmap::DashSet;
use hogvm::{sync_execute, ExecutionContext, Program, VmError};
use metrics::counter;
use serde_json::Value;
use tracing::info;

use crate::observability::metrics::{STAGE1_HOGVM_ERROR, STAGE1_HOGVM_UNKNOWN_FUNCTION};

/// Unknown-native function names already logged once. Bounded by the HogQL native surface
/// (~hundreds max), so it never grows without bound; keeps the per-event unknown-function path
/// observable in prod logs without a line per event.
static SEEN_UNKNOWN_FNS: LazyLock<DashSet<String>> = LazyLock::new(DashSet::new);

/// HogVM stack ceiling for cohort evaluation. A `person.properties.X IN (...)` leaf compiles to a
/// tuple build that pushes every list element before `In` pops them, so peak depth ≈ list size.
/// Production catalogs already hold IN-lists of several thousand elements (largest observed ~8.6k).
/// A correctness floor, not a tuning knob — it must exceed real list sizes regardless of environment
/// (and independent of the VM's own default ceiling).
const COHORT_HOGVM_MAX_STACK_DEPTH: usize = 32_768;
/// Step ceiling. Cohort filter bytecode is loop-free, so step count ≈ program length and raising this
/// cannot cause a runaway; kept above the stack ceiling so a max-size tuple build can't trip it.
const COHORT_HOGVM_MAX_STEPS: usize = 131_072;

/// Build the cohort evaluator's [`ExecutionContext`]: coercing comparisons plus the raised
/// stack/step ceilings. Both construction sites route through this so production and the parity path
/// share identical limits — a large `IN`-list must not overflow in one and succeed in the other.
fn cohort_execution_context(program: Program) -> ExecutionContext {
    ExecutionContext::with_defaults(program)
        .with_coercing_comparisons()
        .with_max_stack_depth(COHORT_HOGVM_MAX_STACK_DEPTH)
        .with_max_steps(COHORT_HOGVM_MAX_STEPS)
}

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
        let context = cohort_execution_context(seed);
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
    let context = cohort_execution_context(program).with_globals(globals);
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
            // (bounded counter) and surface the specific function in a log instead. Log each
            // distinct name once at info — the counter already tracks volume, so a per-event line
            // would be spam.
            counter!(STAGE1_HOGVM_UNKNOWN_FUNCTION).increment(1);
            // Steady state is a read-only `contains` (no allocation; the same handful of names recur
            // forever). Only on first sight do we clone-and-insert: `insert` returns `true` for
            // exactly one thread, so the log fires once even when several race past `contains` at once.
            if !SEEN_UNKNOWN_FNS.contains(name.as_str()) && SEEN_UNKNOWN_FNS.insert(name.clone()) {
                info!(function = %name, "cohort bytecode called a function with no registered Rust native");
            }
            false
        }
        EvalOutcome::VmError(error) => {
            counter!(STAGE1_HOGVM_ERROR, "reason" => vm_error_reason(&error)).increment(1);
            false
        }
    }
}

/// Collapse a [`VmError`] into a bounded `reason` label for [`STAGE1_HOGVM_ERROR`]. The bucket set is
/// fixed and small so the Prometheus series count stays constant; the `_` arm keeps the match total
/// over the `#[non_exhaustive]` enum and folds in `VmError::Other`. `UnknownFunction`/`UnknownSymbol`
/// are normally routed to [`EvalOutcome::UnknownFunction`] (separate counter) — mapped here only for
/// totality in case [`classify_failure`] ever changes.
fn vm_error_reason(error: &VmError) -> &'static str {
    match error {
        VmError::InvalidValue(..)
        | VmError::CannotCoerce(..)
        | VmError::InvalidNumber(_)
        | VmError::IntegerOverflow => "type_coercion",

        VmError::StackOverflow | VmError::StackUnderflow | VmError::StackIndexOutOfBounds => {
            "stack"
        }

        VmError::NotImplemented(_) => "not_implemented",

        VmError::UnknownGlobal(_) | VmError::UnknownProperty(_) => "unknown_ref",

        VmError::NotAnOperation(_)
        | VmError::InvalidOperation(_)
        | VmError::EndOfProgram(_)
        | VmError::InvalidBytecode(_)
        | VmError::InvalidCall(_)
        | VmError::NotEnoughArguments(..)
        | VmError::CaptureOutOfBounds(_)
        | VmError::NoFrame => "program",

        VmError::UncaughtException(..) | VmError::InvalidException => "exception",

        VmError::DivisionByZero
        | VmError::HeapIndexOutOfBounds
        | VmError::UseAfterFree
        | VmError::ExpectedObject
        | VmError::UnexpectedPopTry
        | VmError::InvalidIndex
        | VmError::CycleDetected
        | VmError::IndexOutOfBounds(..)
        | VmError::OutOfResource(_)
        | VmError::NativeCallFailed(_)
        | VmError::InvalidRegex(..) => "runtime",

        VmError::UnknownFunction(_) | VmError::UnknownSymbol(_) => "unknown_function",

        _ => "other", // VmError::Other + any future #[non_exhaustive] variant
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
    const OP_IN: i64 = 21;
    const OP_INTEGER: i64 = 33;
    const OP_STRING: i64 = 32;
    // Fixtures terminate explicitly with RETURN, mirroring what the catalog loader stores.
    const OP_RETURN: i64 = 38;
    const OP_TUPLE: i64 = 44;

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

    /// `header + N×(OP_INTEGER, i) + OP_TUPLE N` — the exact shape a `person.properties.X IN (...)`
    /// leaf compiles its list to. Building the tuple pushes all N elements before they are popped, so
    /// peak stack depth ≈ N.
    fn tuple_build_program(n: i64) -> Vec<Value> {
        let mut bc = header();
        for i in 0..n {
            bc.extend_from_slice(&[json!(OP_INTEGER), json!(i)]);
        }
        bc.extend_from_slice(&[json!(OP_TUPLE), json!(n), json!(OP_RETURN)]);
        bc
    }

    #[test]
    fn large_tuple_overflows_at_shallow_depth_but_evaluates_in_cohort_context() {
        // N comfortably above a 128-deep stack, small enough to be instant.
        let prog = tuple_build_program(200);

        // Control: an explicit 128-deep stack (the old `with_defaults` value, before the ceiling was
        // raised) must StackOverflow on the tuple build, pinning the failure the cohort context avoids.
        let program = Program::new(prog.clone()).expect("valid program");
        let control = ExecutionContext::with_defaults(program).with_max_stack_depth(128);
        assert!(
            matches!(sync_execute(&control, false), Err(failure) if matches!(failure.error, VmError::StackOverflow)),
            "expected StackOverflow at a stack depth of 128",
        );

        // Fix, free-function site (parity path): no overflow. A tuple result coerces to false, so we
        // only assert `Matched`, i.e. not a `VmError`.
        assert!(matches!(
            evaluate_detailed(&prog, json!({})),
            EvalOutcome::Matched(_)
        ));

        // Fix, reused-evaluator site (production hot path): likewise no overflow.
        let mut evaluator = CohortEvaluator::new();
        evaluator.set_globals(json!({}));
        assert!(matches!(
            evaluator.evaluate_detailed(Arc::new(prog)),
            EvalOutcome::Matched(_)
        ));
    }

    /// `<needle> IN (0..n)` over integer literals. The compiler emits `right, left, op` and `In` pops
    /// the needle (top) then the haystack, so the n-element tuple is built first, then the needle.
    fn int_in_list_program(n: i64, needle: i64) -> Vec<Value> {
        let mut bc = header();
        for i in 0..n {
            bc.extend_from_slice(&[json!(OP_INTEGER), json!(i)]);
        }
        bc.extend_from_slice(&[json!(OP_TUPLE), json!(n)]);
        bc.extend_from_slice(&[
            json!(OP_INTEGER),
            json!(needle),
            json!(OP_IN),
            json!(OP_RETURN),
        ]);
        bc
    }

    #[test]
    fn vm_error_reason_buckets_one_representative_per_class() {
        // One representative `VmError` per bucket. Catches a forgotten or mis-bucketed variant: a
        // new `#[non_exhaustive]` variant left unhandled silently falls into `other`, and moving an
        // existing variant (e.g. `DivisionByZero` out of `runtime`) breaks the label breakdown.
        let cases: [(VmError, &str); 11] = [
            (
                VmError::InvalidValue("a".into(), "b".into()),
                "type_coercion",
            ),
            (VmError::IntegerOverflow, "type_coercion"),
            (VmError::StackOverflow, "stack"),
            (VmError::NotImplemented("x".into()), "not_implemented"),
            (VmError::UnknownGlobal("g".into()), "unknown_ref"),
            (VmError::InvalidBytecode("b".into()), "program"),
            (
                VmError::UncaughtException("t".into(), "m".into()),
                "exception",
            ),
            (VmError::DivisionByZero, "runtime"),
            // The `max_steps` blowup (`vm.rs` synthesizes `OutOfResource`) must stay visible.
            (VmError::OutOfResource("steps".into()), "runtime"),
            (VmError::UnknownFunction("f".into()), "unknown_function"),
            (VmError::Other("o".into()), "other"),
        ];
        for (error, expected) in &cases {
            assert_eq!(
                vm_error_reason(error),
                *expected,
                "wrong bucket for {error:?}"
            );
        }
    }

    #[test]
    fn large_in_list_membership_is_correct_at_raised_depth() {
        // A 200-element list overflows the default depth; at the cohort ceiling it must yield correct
        // membership both ways — proving the raise restores correctness, not just silences the error.
        assert!(matches!(
            evaluate_detailed(&int_in_list_program(200, 5), json!({})),
            EvalOutcome::Matched(true)
        ));
        assert!(matches!(
            evaluate_detailed(&int_in_list_program(200, 9999), json!({})),
            EvalOutcome::Matched(false)
        ));
    }
}
