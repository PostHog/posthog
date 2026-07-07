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
fn nested_call_suspend_round_trips() {
    // fun helper() { return asyncFetch(0) }   // suspend one frame deep (callStack = [root, helper])
    // return helper() + 40
    // injecting 2 => 42. Exercises the N>=1 call-stack mapping: the snapshot must reconstruct the
    // helper frame's return point + stack window so it returns into root correctly.
    let result = run_injecting(
        vec![
            json!("_H"),
            json!(1),
            json!(CALLABLE),
            json!("helper"),
            json!(0),
            json!(0),
            json!(6),
            json!(INTEGER),
            json!(0),
            json!(CALL_GLOBAL),
            json!("asyncFetch"),
            json!(1),
            json!(RETURN),
            json!(CLOSURE),
            json!(0), // helper -> local 0
            json!(GET_LOCAL),
            json!(0),
            json!(CALL_LOCAL),
            json!(0), // helper()
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
fn sleep_is_builtin_async() {
    // sleep(1) suspends as async even with no host-registered async functions, mirroring the
    // reference's ASYNC_STL (which sleep is the sole member of).
    let program = Program::new(vec![
        json!("_H"),
        json!(1),
        json!(INTEGER),
        json!(1),
        json!(CALL_GLOBAL),
        json!("sleep"),
        json!(1),
        json!(RETURN),
    ])
    .expect("valid program");
    let context = ExecutionContext::with_defaults(program).with_max_async_steps(1);
    match execute_resumable(&context).expect("exec") {
        Resumable::Suspended { function, .. } => assert_eq!(function, "sleep"),
        Resumable::Finished(_) => panic!("expected suspension on sleep"),
    }
}

#[test]
fn telemetry_traces_opcodes() {
    // With telemetry on, the suspend snapshot carries the reference's [time, chunk, ip, "op/NAME",
    // debug] trace. The first opcode is INTEGER at header-inclusive ip 2, and a CALL_GLOBAL follows.
    let program = Program::new(vec![
        json!("_H"),
        json!(1),
        json!(INTEGER),
        json!(2),
        json!(CALL_GLOBAL),
        json!("asyncFetch"),
        json!(1),
        json!(RETURN),
    ])
    .expect("valid program");
    let context = ExecutionContext::with_defaults(program)
        .with_async_functions(HashSet::from(["asyncFetch".to_string()]))
        .with_max_async_steps(1)
        .with_telemetry();
    let Resumable::Suspended { state, .. } = execute_resumable(&context).expect("exec") else {
        panic!("expected suspension");
    };
    let telemetry = state.telemetry.expect("telemetry collected");
    assert_eq!(telemetry[0][3], json!("33/INTEGER"));
    assert_eq!(telemetry[0][2], json!(2));
    assert!(telemetry.iter().any(|e| e[3] == json!("2/CALL_GLOBAL")));
}

#[test]
fn resumes_a_node_produced_state() {
    // A real VMState captured from the Node reference VM (@posthog/hogvm) for the open-upvalue
    // program (let x := 5; let f := () -> x; let y := asyncFetch(0); return f() + y), suspended on
    // asyncFetch. Rust must resume it from Node's exact wire format — reconstructing the program from
    // the state's own `bytecodes` — and reach f() + y = 5 + 37 = 42. Frozen oracle (no Node at test
    // time): guards the callable-ip header offset, 1-based upvalue ids, and the frame mapping so a
    // serialize/deserialize drift can't silently break cross-VM resume.
    let node_state = r#"{"bytecodes":{"root":{"bytecode":["_H",1,33,5,52,"lambda",0,1,3,55,0,38,53,1,true,0,33,0,2,"asyncFetch",1,36,1,54,0,6,38]}},"stack":[5,{"__hogClosure__":true,"callable":{"__hogCallable__":"local","name":"lambda","chunk":"root","argCount":0,"upvalueCount":1,"ip":9},"upvalues":[1]}],"upvalues":[{"__hogUpValue__":true,"id":1,"location":0,"closed":false,"value":null}],"callStack":[{"ip":21,"chunk":"root","stackStart":0,"argCount":0,"closure":{"__hogClosure__":true,"callable":{"__hogCallable__":"local","name":"","chunk":"root","argCount":0,"upvalueCount":0,"ip":1},"upvalues":[]}}],"throwStack":[],"declaredFunctions":{},"ops":5,"asyncSteps":1,"syncDuration":0,"maxMemUsed":267}"#;
    let snapshot: VmSnapshot = serde_json::from_str(node_state).expect("parse node state");
    let tokens: Vec<Value> = snapshot.bytecodes["root"]["bytecode"]
        .as_array()
        .expect("bytecode array")
        .clone();
    let program = Program::new(tokens).expect("valid program");
    let context = ExecutionContext::with_defaults(program)
        .with_async_functions(HashSet::from(["asyncFetch".to_string()]))
        .with_max_async_steps(4);
    match resume(&context, &snapshot, json!(37)).expect("resume") {
        Resumable::Finished(v) => assert_eq!(v, json!(42)),
        Resumable::Suspended { .. } => panic!("unexpected re-suspension"),
    }
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
