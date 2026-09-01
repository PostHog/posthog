//! Coverage for numeric coercion across the comparison surface: ordering (`Gt`/`GtEq`/`Lt`/`LtEq`)
//! over mixed scalar types, and equality (`Eq`/`NotEq`) plus membership (`in`, `has`, `indexOf`)
//! over mixed int/float operands. Cohort numeric leaves compile the threshold as a string constant,
//! so this must match the Python (`unify_comparison_types`) and TS (`unifyComparisonTypes`)
//! coercion exactly.

use hogvm::{sync_execute, ExecutionContext, Program, VmFailure};
use serde_json::{json, Value};

// Opcode numeric values (mirror common/hogvm/python/operation.py).
const OP_CALL_GLOBAL: i64 = 2;
const OP_EQ: i64 = 11;
const OP_NOT_EQ: i64 = 12;
const OP_GT: i64 = 13;
const OP_GT_EQ: i64 = 14;
const OP_LT: i64 = 15;
const OP_LT_EQ: i64 = 16;
const OP_IN: i64 = 21;
const OP_TRUE: i64 = 29;
const OP_FALSE: i64 = 30;
const OP_STRING: i64 = 32;
const OP_INTEGER: i64 = 33;
const OP_FLOAT: i64 = 34;
const OP_RETURN: i64 = 38;
const OP_ARRAY: i64 = 43;

/// `left <op> right`. The compiler emits operands as `[right…, left…, op]`.
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
    let ctx = ExecutionContext::with_defaults(program)
        .with_globals(json!({}))
        .with_coercing_comparisons();
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

fn array(values: &[Vec<Value>]) -> Vec<Value> {
    let mut bytecode = values.iter().flatten().cloned().collect::<Vec<_>>();
    bytecode.extend([json!(OP_ARRAY), json!(values.len())]);
    bytecode
}

/// `needle in haystack`. The VM pops the needle first, so the haystack is emitted first.
fn in_op(needle: &[Value], haystack: &[Value]) -> Vec<Value> {
    compare(needle, haystack, OP_IN)
}

/// `name(args…)`. The compiler emits the args in order, then the call.
fn call(name: &str, args: &[Vec<Value>]) -> Vec<Value> {
    let mut bc = vec![json!("_H"), json!(1)];
    bc.extend(args.iter().flatten().cloned());
    bc.extend([
        json!(OP_CALL_GLOBAL),
        json!(name),
        json!(args.len()),
        json!(OP_RETURN),
    ]);
    bc
}

/// Numeric equality is unconditional, so it is not gated behind `with_coercing_comparisons`. Every
/// equality expectation must therefore hold on the coercing path and on the default path that
/// cymbal and every other shared-crate consumer runs.
fn assert_both_paths(bytecode: Vec<Value>, expected: Value, label: &str) {
    assert_eq!(run(bytecode.clone()), expected, "coercing path: {label}");
    assert_eq!(
        run_legacy(bytecode).expect("legacy execution succeeds"),
        expected,
        "default path: {label}",
    );
}

#[test]
fn int_float_equality_is_numeric_on_both_paths() {
    // `Integer(1)` and `Float(1.0)` are one value to both reference VMs, and the Rust VM's own
    // ordering ops already widen mixed pairs, so equality has to agree: otherwise `1 == 1.0` is
    // false while `1 >= 1.0` is true.
    assert_both_paths(
        compare(&int(1), &float(1.0), OP_EQ),
        json!(true),
        "1 == 1.0",
    );
    assert_both_paths(
        compare(&int(1), &float(1.0), OP_NOT_EQ),
        json!(false),
        "1 != 1.0",
    );
    assert_both_paths(
        compare(&int(2), &float(1.0), OP_EQ),
        json!(false),
        "2 == 1.0",
    );
    // A `1e3`-style literal compiles to a Float, so it must still equal the integer 1000.
    assert_both_paths(
        compare(&int(1000), &float(1000.0), OP_EQ),
        json!(true),
        "1000 == 1000.0",
    );
}

#[test]
fn string_coercion_equality_unifies_numeric_variants() {
    // The Number/String arm parses "1.0" to a Float, which then has to equal the integer operand.
    assert_both_paths(
        compare(&int(1), &string("1.0"), OP_EQ),
        json!(true),
        "1 == '1.0'",
    );
    assert_both_paths(
        compare(&string("1"), &float(1.0), OP_EQ),
        json!(true),
        "'1' == 1.0",
    );
    // Two strings short-circuit as strings rather than being parsed, matching both references.
    assert_both_paths(
        compare(&string("1"), &string("1.0"), OP_EQ),
        json!(false),
        "'1' == '1.0'",
    );
}

#[test]
fn bool_number_equality_widens() {
    assert_both_paths(
        compare(&boolean(true), &float(1.0), OP_EQ),
        json!(true),
        "true == 1.0",
    );
    assert_both_paths(
        compare(&boolean(false), &float(0.0), OP_EQ),
        json!(true),
        "false == 0.0",
    );
}

#[test]
fn array_equality_is_element_wise_numeric() {
    assert_both_paths(
        compare(
            &array(&[int(1), int(2)]),
            &array(&[float(1.0), float(2.0)]),
            OP_EQ,
        ),
        json!(true),
        "[1, 2] == [1.0, 2.0]",
    );
    assert_both_paths(
        compare(&array(&[int(1)]), &array(&[float(2.0)]), OP_EQ),
        json!(false),
        "[1] == [2.0]",
    );
}

#[test]
fn membership_uses_numeric_equality() {
    let ints = array(&[int(1), int(2)]);
    let floats = array(&[float(1.0), float(2.0)]);

    assert_both_paths(in_op(&float(1.0), &ints), json!(true), "1.0 in [1, 2]");
    assert_both_paths(in_op(&float(3.0), &ints), json!(false), "3.0 in [1, 2]");
    assert_both_paths(
        call("has", &[ints.clone(), float(1.0)]),
        json!(true),
        "has([1, 2], 1.0)",
    );
    assert_both_paths(
        call("indexOf", &[floats, int(2)]),
        json!(2),
        "indexOf([1.0, 2.0], 2)",
    );
    assert_both_paths(
        call("in", &[int(1), array(&[float(1.0)])]),
        json!(true),
        "in(1, [1.0])",
    );
}

#[test]
fn strict_equality_functions_unify_numeric_variants() {
    // `equals`/`notEquals` are the strict function forms. They stay strict across TYPES, but the
    // int/float variants of one number unify, matching the reference `===` where all numbers are f64.
    assert_both_paths(
        call("equals", &[int(1), float(1.0)]),
        json!(true),
        "equals(1, 1.0)",
    );
    assert_both_paths(
        call("notEquals", &[int(1), float(1.0)]),
        json!(false),
        "notEquals(1, 1.0)",
    );
}

#[test]
fn number_vs_numeric_string_coerces_the_string() {
    // The exact cohort case: `bc_num gt "10"` (threshold compiled as a string).
    assert_eq!(
        run(compare(&int(20), &string("10"), OP_GT)),
        Value::Bool(true)
    );
    assert_eq!(
        run(compare(&int(5), &string("10"), OP_GT)),
        Value::Bool(false)
    );
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
    // Residual divergence from ClickHouse: two strings compare lexicographically (matching Python/TS),
    // NOT numerically — so "9" > "100" here though 9 < 100 numerically.
    assert_eq!(
        run(compare(&string("20"), &string("10"), OP_GT)),
        Value::Bool(true)
    );
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
fn bool_vs_non_numeric_string_matches_python() {
    // Python's `unify_comparison_types` coerces a string to bool as `bool(s)`: "true"/"false" map
    // literally, every other non-empty string is truthy, "" is falsy. So `true > "yes"` is 1 > 1.
    assert_eq!(
        run(compare(&boolean(true), &string("yes"), OP_GT)),
        Value::Bool(false),
    );
    assert_eq!(
        run(compare(&boolean(true), &string("yes"), OP_GT_EQ)),
        Value::Bool(true),
    );
    // "false" → 0, so `true > "false"` is 1 > 0.
    assert_eq!(
        run(compare(&boolean(true), &string("false"), OP_GT)),
        Value::Bool(true),
    );
    // "" → 0 (falsy), so `true > ""` is 1 > 0.
    assert_eq!(
        run(compare(&boolean(true), &string(""), OP_GT)),
        Value::Bool(true),
    );
    // `false < "yes"` is 0 < 1.
    assert_eq!(
        run(compare(&boolean(false), &string("yes"), OP_LT)),
        Value::Bool(true),
    );
}

#[test]
fn number_vs_unparseable_string_errors() {
    // An unparseable string errors on this path (Python raises, TS yields NaN).
    assert!(run_result(compare(&int(5), &string("abc"), OP_GT)).is_err());
    assert!(run_result(compare(&string("abc"), &int(5), OP_LT)).is_err());
}

/// Build + run WITHOUT opting into coercing comparisons — the default every non-cohort consumer
/// (e.g. cymbal) gets.
fn run_legacy(bytecode: Vec<Value>) -> Result<Value, VmFailure> {
    let program = Program::new(bytecode).expect("valid program");
    let ctx = ExecutionContext::with_defaults(program).with_globals(json!({}));
    sync_execute(&ctx, false)
}

#[test]
fn legacy_default_keeps_strict_comparisons_for_other_consumers() {
    // The coercion is opt-in: without it a non-number operand ERRORS rather than coercing.
    // This is the contract cymbal relies on to auto-disable a malformed rule.
    assert!(
        run_legacy(compare(&int(5), &string("10"), OP_GT)).is_err(),
        "number vs numeric-string must error on the legacy path, not coerce",
    );
    assert!(
        run_legacy(compare(&boolean(true), &int(0), OP_GT)).is_err(),
        "bool vs number must error on the legacy path, not coerce",
    );
    for (label, left, right) in [
        (
            "shared numeric prefix",
            array(&[int(1), string("invalid")]),
            array(&[int(1)]),
        ),
        (
            "different numeric prefix",
            array(&[int(2), string("invalid")]),
            array(&[int(1)]),
        ),
    ] {
        assert!(
            run_legacy(compare(&left, &right, OP_GT)).is_err(),
            "a nonnumeric array suffix must error after a {label}",
        );
    }
    // Pure numeric comparisons are identical on both paths.
    assert_eq!(
        run_legacy(compare(&int(20), &int(10), OP_GT)).unwrap(),
        Value::Bool(true)
    );
    assert_eq!(
        run_legacy(compare(&int(5), &int(10), OP_GT)).unwrap(),
        Value::Bool(false)
    );
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
    assert_eq!(run(compare(&int(10), &int(10), OP_EQ)), Value::Bool(true));
}
