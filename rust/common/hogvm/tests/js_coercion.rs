//! Reference-VM (JS) coercion semantics observed diverging on production transformations:
//! integer dict keys ({96: 'x'} — a JS Map keyed by the raw scalar), null behaving as 0 in
//! arithmetic, and toUnixTimestamp parsing ISO strings.

use hogvm::{sync_execute, ExecutionContext, Program};
use serde_json::{json, Value};

const OP_CALL_GLOBAL: i64 = 2;
const OP_MINUS: i64 = 7;
const OP_NULL: i64 = 31;
const OP_STRING: i64 = 32;
const OP_INTEGER: i64 = 33;
const OP_RETURN: i64 = 38;
const OP_DICT: i64 = 42;
const OP_GET_PROPERTY: i64 = 45;

fn run(bytecode: Vec<Value>) -> Value {
    let program = Program::new(bytecode).expect("valid program");
    let ctx = ExecutionContext::with_defaults(program);
    sync_execute(&ctx, false).expect("execution succeeds")
}

#[test]
fn integer_dict_keys_construct_and_look_up() {
    // {96: 'x'}[96] — both the construction and the lookup coerce the numeric key.
    let bc = vec![
        json!("_H"),
        json!(1),
        json!(OP_INTEGER),
        json!(96),
        json!(OP_STRING),
        json!("x"),
        json!(OP_DICT),
        json!(1),
        json!(OP_INTEGER),
        json!(96),
        json!(OP_GET_PROPERTY),
        json!(OP_RETURN),
    ];
    assert_eq!(run(bc), json!("x"));
}

#[test]
fn null_behaves_as_zero_in_arithmetic() {
    // 5 - null = 5 (operands push null first, then 5; MINUS pops top-first).
    let bc = vec![
        json!("_H"),
        json!(1),
        json!(OP_NULL),
        json!(OP_INTEGER),
        json!(5),
        json!(OP_MINUS),
        json!(OP_RETURN),
    ];
    assert_eq!(run(bc), json!(5));

    // null - null = 0
    let bc = vec![
        json!("_H"),
        json!(1),
        json!(OP_NULL),
        json!(OP_NULL),
        json!(OP_MINUS),
        json!(OP_RETURN),
    ];
    assert_eq!(run(bc), json!(0));
}

fn to_unix_timestamp_of(value: Value) -> Vec<Value> {
    vec![
        json!("_H"),
        json!(1),
        json!(OP_STRING),
        value,
        json!(OP_CALL_GLOBAL),
        json!("toUnixTimestamp"),
        json!(1),
        json!(OP_RETURN),
    ]
}

#[test]
fn to_unix_timestamp_parses_iso_strings() {
    assert_eq!(
        run(to_unix_timestamp_of(json!("2026-07-03T12:00:00.000Z"))),
        json!(1783080000.0)
    );
}

#[test]
fn to_unix_timestamp_of_unparseable_string_is_null() {
    // The reference yields NaN, which serializes to null.
    assert_eq!(run(to_unix_timestamp_of(json!("not a date"))), Value::Null);
}
