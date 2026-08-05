//! `=~`/`!~` (and the case-insensitive variants) coerce non-string scalar operands like the TS
//! reference's `regexMatch`: `pattern && value ? external.match(pattern, value) : false`, where the
//! external matcher (RE2 `.test`) JS-String-coerces the value. So numbers and booleans stringify
//! and match, a falsy pattern or value (null, `false`, `0`, `""`) never matches, and containers
//! (arrays/objects) still error — the same deliberate deviation `like`/`ilike` make. Contrast
//! `like_null.rs`, where `like` stringifies null to "null" and has no falsy guard. Real hog code
//! hits this because `and` is not short-circuiting: `typeof(x) = 'string' and x =~ '/y'` evaluates
//! the regex even when x is a number or array.

use hogvm::{sync_execute, ExecutionContext, Program, VmFailure};
use serde_json::{json, Value};

const OP_REGEX: i64 = 23;
const OP_NOT_REGEX: i64 = 24;
const OP_IREGEX: i64 = 25;
const OP_TRUE: i64 = 29;
const OP_FALSE: i64 = 30;
const OP_NULL: i64 = 31;
const OP_STRING: i64 = 32;
const OP_INTEGER: i64 = 33;
const OP_RETURN: i64 = 38;
const OP_ARRAY: i64 = 43;

fn run_result(bytecode: Vec<Value>) -> Result<Value, VmFailure> {
    let program = Program::new(bytecode).expect("valid program");
    let ctx = ExecutionContext::with_defaults(program);
    sync_execute(&ctx, false)
}

fn run(bytecode: Vec<Value>) -> Value {
    run_result(bytecode).expect("execution succeeds")
}

// Stack order: the pattern is pushed first, then the value (the VM pops the value first).
fn regex_of(pattern: &str, push_value: &[Value], op: i64) -> Vec<Value> {
    let mut bc = vec![json!("_H"), json!(1), json!(OP_STRING), json!(pattern)];
    bc.extend_from_slice(push_value);
    bc.extend_from_slice(&[json!(op), json!(OP_RETURN)]);
    bc
}

#[test]
fn numbers_and_booleans_coerce_to_their_string_form() {
    // 42 stringifies to "42" and matches, instead of erroring on the non-string operand.
    assert_eq!(
        run(regex_of("4", &[json!(OP_INTEGER), json!(42)], OP_REGEX)),
        Value::Bool(true)
    );
    assert_eq!(
        run(regex_of("^9", &[json!(OP_INTEGER), json!(42)], OP_REGEX)),
        Value::Bool(false)
    );
    // `true` stringifies to "true"; IREGEX matches it case-insensitively.
    assert_eq!(
        run(regex_of("TRUE", &[json!(OP_TRUE)], OP_IREGEX)),
        Value::Bool(true)
    );
}

#[test]
fn falsy_operands_never_match() {
    // Unlike `like` (null -> "null"), the regex family applies the reference's `pattern && value`
    // guard, so any falsy operand short-circuits to no match — regardless of the pattern.
    let falsy_values: &[(&str, &[Value])] = &[
        ("null", &[json!(OP_NULL)]),
        ("zero", &[json!(OP_INTEGER), json!(0)]),
        ("empty string", &[json!(OP_STRING), json!("")]),
        ("false", &[json!(OP_FALSE)]),
    ];
    for (label, push) in falsy_values {
        // `.*` matches any string, so a non-false result would mean the guard failed to fire.
        assert_eq!(
            run(regex_of(".*", push, OP_REGEX)),
            Value::Bool(false),
            "value {label} =~ '.*' should be false"
        );
        // `!~` is the negation: a falsy value never matches, so `!~` is true.
        assert_eq!(
            run(regex_of(".*", push, OP_NOT_REGEX)),
            Value::Bool(true),
            "value {label} !~ '.*' should be true"
        );
    }
    // A falsy pattern (empty string) also short-circuits even against a truthy value.
    assert_eq!(
        run(regex_of("", &[json!(OP_STRING), json!("hello")], OP_REGEX)),
        Value::Bool(false)
    );
}

#[test]
fn container_operands_still_error() {
    // Arrays are truthy, so they reach string coercion — which errors, matching the deliberate
    // `like`/`ilike` container deviation (the reference would stringify to "a,b,c", but no real
    // program relies on regex-matching a stringified container).
    let empty_array = &[json!(OP_ARRAY), json!(0)];
    assert!(
        run_result(regex_of("x", empty_array, OP_REGEX)).is_err(),
        "regex against an array operand should error"
    );
}
