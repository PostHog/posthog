//! Coverage for the pre-decoded token stream on uncommon operand shapes. The parity corpus only
//! exercises the common ones (int under INTEGER, fractional float under FLOAT, strings), so these
//! lock in the decode fallbacks: INTEGER is untyped `pushStack(next())` in the reference VM (the
//! SQL-AST compiler emits it with a boolean operand), FLOAT accepts an integer operand (serde
//! deserialized those transparently), and an integer above `i64::MAX` decodes as a float.

use hogvm::{sync_execute, ExecutionContext, Program};
use serde_json::{json, Value};

// Opcode numeric values (mirror common/hogvm/python/operation.py).
const OP_INTEGER: i64 = 33;
const OP_FLOAT: i64 = 34;
const OP_RETURN: i64 = 38;

fn run(operand: Value, op: i64) -> Value {
    let bytecode = vec![json!("_H"), json!(1), json!(op), operand, json!(OP_RETURN)];
    let program = Program::new(bytecode).expect("valid program");
    let ctx = ExecutionContext::with_defaults(program);
    sync_execute(&ctx, false).expect("execution succeeds")
}

#[test]
fn integer_opcode_with_bool_operand() {
    assert_eq!(run(json!(true), OP_INTEGER), json!(true));
    assert_eq!(run(json!(false), OP_INTEGER), json!(false));
}

#[test]
fn integer_opcode_with_float_operand() {
    assert_eq!(run(json!(2.5), OP_INTEGER), json!(2.5));
}

#[test]
fn integer_opcode_with_operand_above_i64_max() {
    // 2^63 doesn't fit an i64, so the token decodes as a float and pushes a number.
    assert_eq!(
        run(json!(9_223_372_036_854_775_808u64), OP_INTEGER),
        json!(9.223372036854776e18)
    );
}

#[test]
fn float_opcode_with_integer_operand() {
    assert_eq!(run(json!(1), OP_FLOAT), json!(1.0));
}
