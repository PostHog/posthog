//! Suspend/resume (async-coroutine) execution + VMState serialization.
//!
//! These lock in the contract the CDP hog-function path depends on: a program that calls a
//! registered async function suspends with a fully serializable snapshot, and resuming with the
//! async result continues to the correct value — across a real JSON text round-trip of the state,
//! and with a closure whose open upvalue (a live stack reference) must survive serialization.

use std::collections::HashSet;

use hogvm::{execute_resumable, resume, ExecutionContext, Program, Resumable, VmSnapshot};
use serde_json::{json, Value};

// Opcodes used below (see common/hogvm/python/operation.py).
const CALL_GLOBAL: i64 = 2;
const PLUS: i64 = 6;
const INTEGER: i64 = 33;
const GET_LOCAL: i64 = 36;
const RETURN: i64 = 38;
const CALLABLE: i64 = 52;
const CLOSURE: i64 = 53;
const CALL_LOCAL: i64 = 54;
const GET_UPVALUE: i64 = 55;

// Drive a program that calls `asyncFetch`, injecting `inject` as the async result at each
// suspension. Each suspension's snapshot is serialized to JSON text and parsed back before resuming,
// proving the state survives a real serialization boundary (not just an in-memory handoff).
fn run_injecting(tokens: Vec<Value>, inject: Value) -> Value {
    let program = Program::new(tokens).expect("valid program");
    let context = ExecutionContext::with_defaults(program)
        .with_async_functions(HashSet::from(["asyncFetch".to_string()]))
        .with_max_async_steps(4);

    let mut outcome = execute_resumable(&context).expect("initial execution");
    loop {
        match outcome {
            Resumable::Finished(value) => return value,
            Resumable::Suspended { state, .. } => {
                let text = serde_json::to_string(&state).expect("snapshot serializes");
                let restored: VmSnapshot =
                    serde_json::from_str(&text).expect("snapshot parses back");
                outcome = resume(&context, &restored, inject.clone()).expect("resume");
            }
        }
    }
}

#[test]
fn scalar_async_round_trips() {
    // asyncFetch(2) + 40, injecting 2 => 42. Exercises the bare suspend/serialize/resume cycle.
    let result = run_injecting(
        vec![
            json!("_H"),
            json!(1),
            json!(INTEGER),
            json!(2),
            json!(CALL_GLOBAL),
            json!("asyncFetch"),
            json!(1),
            json!(INTEGER),
            json!(40),
            json!(PLUS),
            json!(RETURN),
        ],
        json!(2),
    );
    assert_eq!(result, json!(42));
}

#[test]
fn open_upvalue_survives_suspend() {
    // let x := 5
    // let f := () -> x          // f captures root local 0 (x) as an OPEN upvalue
    // let y := asyncFetch(0)    // suspend while x is in scope => the upvalue is open at snapshot time
    // return f() + y            // after resume, f() must still read x (=5) through that upvalue
    // injecting 37 => 5 + 37 = 42. Regresses the upvalue-graph-by-id flattening + reconnect on resume.
    let result = run_injecting(
        vec![
            json!("_H"),
            json!(1),
            json!(INTEGER),
            json!(5), // x = 5 (local 0)
            json!(CALLABLE),
            json!("lambda"),
            json!(0),
            json!(1),
            json!(3),
            json!(GET_UPVALUE),
            json!(0),
            json!(RETURN), // lambda body: return x (upvalue 0)
            json!(CLOSURE),
            json!(1),
            json!(true),
            json!(0), // capture parent local 0 -> f (local 1)
            json!(INTEGER),
            json!(0), // asyncFetch arg
            json!(CALL_GLOBAL),
            json!("asyncFetch"),
            json!(1), // suspend (x still in scope)
            json!(GET_LOCAL),
            json!(1), // f
            json!(CALL_LOCAL),
            json!(0),    // f()
            json!(PLUS), // f() + y
            json!(RETURN),
        ],
        json!(37),
    );
    assert_eq!(result, json!(42));
}

#[test]
fn sync_execution_rejects_async() {
    // A registered async function under the sync driver can't suspend; with the default budget the
    // resumable driver also refuses. This guards that async never silently no-ops in a sync consumer.
    let program = Program::new(vec![
        json!("_H"),
        json!(1),
        json!(INTEGER),
        json!(0),
        json!(CALL_GLOBAL),
        json!("asyncFetch"),
        json!(1),
        json!(RETURN),
    ])
    .expect("valid program");
    // max_async_steps defaults to 0: the first suspension exceeds the budget and errors.
    let context = ExecutionContext::with_defaults(program)
        .with_async_functions(HashSet::from(["asyncFetch".to_string()]));
    assert!(execute_resumable(&context).is_err());
}
