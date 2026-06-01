//! Coverage for ordering-comparison coercion (F3): `Gt`/`GtEq`/`Lt`/`LtEq` over mixed scalar types.
//!
//! Cohort numeric leaves (`bc_num gt 10`) compile the threshold as a **string** constant, so the
//! comparison is `Number <op> String`. The reference Python (`unify_comparison_types`) and TS
//! (`unifyComparisonTypes`) coerce String→Number only when the other side is a number, compare two
//! strings lexicographically, and let an unparseable numeric coercion fall through to a falsy
//! result (Python raises → caught; TS → `NaN`). This VM matches that exactly — the pre-fix code
//! instead errored on *any* non-`Number` operand, so every numeric person cohort silently failed.

use hogvm::{sync_execute, ExecutionContext, Program, VmFailure};
use serde_json::{json, Value};

// Opcode numeric values (mirror common/hogvm/python/operation.py).
const OP_EQ: i64 = 11;
const OP_GT: i64 = 13;
const OP_GT_EQ: i64 = 14;
const OP_LT: i64 = 15;
const OP_LT_EQ: i64 = 16;
const OP_TRUE: i64 = 29;
const OP_FALSE: i64 = 30;
const OP_STRING: i64 = 32;
const OP_INTEGER: i64 = 33;
const OP_FLOAT: i64 = 34;
const OP_RETURN: i64 = 38;

/// `left <op> right`. The compiler emits `visit(right), visit(left), op`, so result = `op(left, right)`.
fn compare(left: &[Value], right: &[Value], op: i64) -> Vec<Value> {
    let mut bc = vec![json!("_H"), json!(1)];
    bc.extend_from_slice(right);
    bc.extend_from_slice(left);
    bc.push(json!(op));
    bc.push(json!(OP_RETURN));
    bc
}

fn run_result(bytecode: Vec<Value>) -> Result<Value, VmFailure> {
    let program = Program::new(bytecode).expect("valid program");
    let ctx = ExecutionContext::with_defaults(program).with_globals(json!({}));
    sync_execute(&ctx, false)
}

fn run(bytecode: Vec<Value>) -> Value {
    run_result(bytecode).expect("execution succeeds")
}

fn int(n: i64) -> Vec<Value> {
    vec![json!(OP_INTEGER), json!(n)]
}

fn float(n: f64) -> Vec<Value> {
    vec![json!(OP_FLOAT), json!(n)]
}

fn string(s: &str) -> Vec<Value> {
    vec![json!(OP_STRING), json!(s)]
}

fn boolean(b: bool) -> Vec<Value> {
    vec![json!(if b { OP_TRUE } else { OP_FALSE })]
}

#[test]
fn number_vs_numeric_string_coerces_the_string() {
    // The exact F3 cohort case: `bc_num gt "10"` (threshold compiled as a string).
    assert_eq!(
        run(compare(&int(20), &string("10"), OP_GT)),
        Value::Bool(true)
    );
    assert_eq!(
        run(compare(&int(5), &string("10"), OP_GT)),
        Value::Bool(false)
    );
    // Symmetric: string on the left coerces too.
    assert_eq!(
        run(compare(&string("20"), &int(10), OP_GT)),
        Value::Bool(true)
    );
    assert_eq!(
        run(compare(&string("5"), &int(10), OP_GT)),
        Value::Bool(false)
    );
}

#[test]
fn every_ordering_op_coerces_numeric_strings() {
    // 20 vs 10 across all four ordering ops, with the threshold as a string.
    for (op, expected) in [
        (OP_GT, true),
        (OP_GT_EQ, true),
        (OP_LT, false),
        (OP_LT_EQ, false),
    ] {
        assert_eq!(
            run(compare(&int(20), &string("10"), op)),
            Value::Bool(expected),
            "op {op}",
        );
    }
    // Equal values: `>=` / `<=` are true, `>` / `<` are false.
    for (op, expected) in [
        (OP_GT, false),
        (OP_GT_EQ, true),
        (OP_LT, false),
        (OP_LT_EQ, true),
    ] {
        assert_eq!(
            run(compare(&int(10), &string("10"), op)),
            Value::Bool(expected),
            "equal, op {op}",
        );
    }
}

#[test]
fn float_string_coercion_works() {
    assert_eq!(
        run(compare(&float(2.5), &string("2.4"), OP_GT)),
        Value::Bool(true)
    );
    assert_eq!(
        run(compare(&string("2.4"), &float(2.5), OP_LT)),
        Value::Bool(true)
    );
}

#[test]
fn both_strings_compare_lexicographically() {
    // Documented residual divergence from ClickHouse: two strings compare lexicographically (matching
    // Python/TS), NOT numerically. "20" > "10" agrees with numeric here…
    assert_eq!(
        run(compare(&string("20"), &string("10"), OP_GT)),
        Value::Bool(true)
    );
    // …but "9" > "100" is true lexicographically ('9' > '1') though 9 < 100 numerically.
    assert_eq!(
        run(compare(&string("9"), &string("100"), OP_GT)),
        Value::Bool(true)
    );
    assert_eq!(
        run(compare(&string("9"), &string("100"), OP_LT)),
        Value::Bool(false)
    );
}

#[test]
fn bool_number_coercion_maps_true_one_false_zero() {
    assert_eq!(
        run(compare(&boolean(true), &int(0), OP_GT)),
        Value::Bool(true)
    );
    assert_eq!(
        run(compare(&boolean(false), &int(1), OP_LT)),
        Value::Bool(true)
    );
    assert_eq!(
        run(compare(&boolean(true), &int(1), OP_GT_EQ)),
        Value::Bool(true)
    );
    assert_eq!(
        run(compare(&int(1), &boolean(false), OP_GT)),
        Value::Bool(true)
    );
}

#[test]
fn number_vs_unparseable_string_errors() {
    // `5 > "abc"`: the string can't coerce to a number. The VM errors (Python raises `TypeError`,
    // TS yields `NaN`); the cohort executor's `evaluate` coerces that error to `false`.
    assert!(run_result(compare(&int(5), &string("abc"), OP_GT)).is_err());
    assert!(run_result(compare(&string("abc"), &int(5), OP_LT)).is_err());
}

#[test]
fn pure_numeric_comparisons_are_unchanged() {
    // Regression guard: the shared `compare_op` must keep number-vs-number byte-identical.
    assert_eq!(run(compare(&int(20), &int(17), OP_GT)), Value::Bool(true));
    assert_eq!(run(compare(&int(17), &int(20), OP_GT)), Value::Bool(false));
    assert_eq!(run(compare(&int(5), &int(10), OP_LT)), Value::Bool(true));
    assert_eq!(
        run(compare(&float(2.5), &float(2.4), OP_GT)),
        Value::Bool(true)
    );
    assert_eq!(
        run(compare(&int(10), &float(10.0), OP_GT_EQ)),
        Value::Bool(true)
    );
    // Equality is untouched by the F3 change.
    assert_eq!(run(compare(&int(10), &int(10), OP_EQ)), Value::Bool(true));
}
