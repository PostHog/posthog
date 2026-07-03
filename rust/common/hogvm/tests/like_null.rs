//! The like/ilike operand family must coerce non-string scalars the way the TS reference does
//! (String(...) / RegExp.test(...)): null stringifies to "null" instead of erroring. Real hog code
//! hits this because `and` is not short-circuiting — `x != null and lower(x) like '%y%'` evaluates
//! the like even when x is null.

use hogvm::{sync_execute, ExecutionContext, Program};
use serde_json::{json, Value};

const OP_LIKE: i64 = 17;
const OP_NOT_LIKE: i64 = 19;
const OP_NULL: i64 = 31;
const OP_STRING: i64 = 32;
const OP_INTEGER: i64 = 33;
const OP_RETURN: i64 = 38;

fn run(bytecode: Vec<Value>) -> Value {
    let program = Program::new(bytecode).expect("valid program");
    let ctx = ExecutionContext::with_defaults(program);
    sync_execute(&ctx, false).expect("execution succeeds")
}

// Stack order: pattern is pushed first, then the value (the VM pops value first).
fn like_of(pattern: &str, push_value: &[Value], op: i64) -> Vec<Value> {
    let mut bc = vec![json!("_H"), json!(1), json!(OP_STRING), json!(pattern)];
    bc.extend_from_slice(push_value);
    bc.extend_from_slice(&[json!(op), json!(OP_RETURN)]);
    bc
}

#[test]
fn null_like_pattern_matches_the_string_null() {
    // String(null) is "null" in the reference, so it only matches null-ish patterns.
    assert_eq!(
        run(like_of("%evaluation%", &[json!(OP_NULL)], OP_LIKE)),
        Value::Bool(false)
    );
    assert_eq!(
        run(like_of("%null%", &[json!(OP_NULL)], OP_LIKE)),
        Value::Bool(true)
    );
    assert_eq!(
        run(like_of("%evaluation%", &[json!(OP_NULL)], OP_NOT_LIKE)),
        Value::Bool(true)
    );
}

#[test]
fn numbers_coerce_to_their_string_form() {
    assert_eq!(
        run(like_of("4%", &[json!(OP_INTEGER), json!(42)], OP_LIKE)),
        Value::Bool(true)
    );
}
