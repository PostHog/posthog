//! Regression for the operand-stack ceiling: building a large array literal must not overflow the
//! operand stack. The reference (Node) VM has no operand-stack limit, but the Rust VM's old default
//! of 128 tripped valid programs that push many values at once (surfaced by replaying production hog
//! functions). `with_defaults` now uses a non-binding ceiling.

use hogvm::{sync_execute, ExecutionContext, Program};
use serde_json::json;

// Opcode numeric values (mirror common/hogvm/python/operation.py).
const OP_CALL_GLOBAL: i64 = 2;
const OP_INTEGER: i64 = 33;
const OP_RETURN: i64 = 38;
const OP_ARRAY: i64 = 43;

#[test]
fn large_array_literal_does_not_overflow() {
    // Push N integers (peak operand stack = N, well past the old 128 cap), build an array from them,
    // and return its length.
    const N: i64 = 500;
    let mut bc = vec![json!("_H"), json!(1)];
    for i in 0..N {
        bc.push(json!(OP_INTEGER));
        bc.push(json!(i));
    }
    bc.extend([json!(OP_ARRAY), json!(N)]);
    bc.extend([json!(OP_CALL_GLOBAL), json!("length"), json!(1)]);
    bc.push(json!(OP_RETURN));

    let program = Program::new(bc).expect("valid program");
    let ctx = ExecutionContext::with_defaults(program).with_globals(json!({}));
    let result = sync_execute(&ctx, false).expect("execution succeeds");
    assert_eq!(result, json!(N));
}
