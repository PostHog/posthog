//! Coverage for the `isNull` native, emitted by the `null_safe_comparisons=True` wrapper that every
//! cohort numeric-comparison leaf compiles through, so it must agree with the Python/TS references.

use hogvm::{sync_execute, ExecutionContext, Program};
use serde_json::{json, Value};

// Opcode numeric values (mirror common/hogvm/python/operation.py).
const OP_GET_GLOBAL: i64 = 1;
const OP_CALL_GLOBAL: i64 = 2;
const OP_NULL: i64 = 31;
const OP_STRING: i64 = 32;
const OP_INTEGER: i64 = 33;
const OP_RETURN: i64 = 38;

fn run(bytecode: Vec<Value>, globals: Value) -> Value {
    let program = Program::new(bytecode).expect("valid program");
    let ctx = ExecutionContext::with_defaults(program).with_globals(globals);
    sync_execute(&ctx, false).expect("execution succeeds")
}

fn is_null_of(push_value: &[Value]) -> Vec<Value> {
    let mut bc = vec![json!("_H"), json!(1)];
    bc.extend_from_slice(push_value);
    bc.extend_from_slice(&[
        json!(OP_CALL_GLOBAL),
        json!("isNull"),
        json!(1),
        json!(OP_RETURN),
    ]);
    bc
}

#[test]
fn is_null_of_null_literal_is_true() {
    assert_eq!(
        run(is_null_of(&[json!(OP_NULL)]), json!({})),
        Value::Bool(true)
    );
}

#[test]
fn is_null_of_integer_literal_is_false() {
    let push_int = [json!(OP_INTEGER), json!(42)];
    assert_eq!(run(is_null_of(&push_int), json!({})), Value::Bool(false));
}

#[test]
fn is_null_of_string_literal_is_false() {
    let push_str = [json!(OP_STRING), json!("hello")];
    assert_eq!(run(is_null_of(&push_str), json!({})), Value::Bool(false));
}

/// A missing person property resolves to null via GET_GLOBAL — the case the null-safe wrapper guards.
/// GET_GLOBAL takes the path segments pushed in reverse, then a count.
fn push_person_property(prop: &str) -> Vec<Value> {
    vec![
        json!(OP_STRING),
        json!(prop),
        json!(OP_STRING),
        json!("properties"),
        json!(OP_STRING),
        json!("person"),
        json!(OP_GET_GLOBAL),
        json!(3),
    ]
}

#[test]
fn is_null_of_missing_person_property_is_true() {
    let globals = json!({ "person": { "properties": {} } });
    assert_eq!(
        run(is_null_of(&push_person_property("email")), globals),
        Value::Bool(true)
    );
}

#[test]
fn is_null_of_present_person_property_is_false() {
    let globals = json!({ "person": { "properties": { "email": "u@p.com" } } });
    assert_eq!(
        run(is_null_of(&push_person_property("email")), globals),
        Value::Bool(false)
    );
}
