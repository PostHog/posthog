//! The json->hog deserialization recursion guard (`MAX_JSON_SERDE_DEPTH`) must clear any realistic
//! event nesting. The reference VMs impose no explicit JSON-nesting limit, so an over-tight cap here
//! surfaces as a shadow `status_mismatch` (Rust errors where Node succeeds) on legitimately deep
//! event properties. Accessing a nested global runs it through `json_to_hog`, so this exercises the
//! guard end to end.

use hogvm::{sync_execute, ExecutionContext, Program};
use serde_json::{json, Value};

const OP_GET_GLOBAL: i64 = 1;
const OP_STRING: i64 = 32;
const OP_RETURN: i64 = 38;

// A value nested `depth` arrays deep: [[[ ... 1 ... ]]].
fn nested_array(depth: usize) -> Value {
    let mut v = json!(1);
    for _ in 0..depth {
        v = json!([v]);
    }
    v
}

// Program: `return globals.deep` — forces json_to_hog over the whole nested subtree on access.
fn return_deep_global(globals: Value) -> Result<Value, hogvm::VmFailure> {
    let bc = vec![
        json!("_H"),
        json!(1),
        json!(OP_STRING),
        json!("deep"),
        json!(OP_GET_GLOBAL),
        json!(1),
        json!(OP_RETURN),
    ];
    let program = Program::new(bc).expect("valid program");
    let ctx = ExecutionContext::with_defaults(program).with_globals(globals);
    sync_execute(&ctx, false)
}

#[test]
fn nesting_past_the_old_64_cap_deserializes() {
    // 100 deep tripped the old cap of 64; it must now round-trip unchanged.
    let value = nested_array(100);
    let result = return_deep_global(json!({ "deep": value.clone() })).expect("execution succeeds");
    assert_eq!(result, value);
}

#[test]
fn nesting_past_the_new_cap_still_errors() {
    // The guard is raised, not removed — pathologically deep input still errors rather than risking
    // native stack exhaustion.
    assert!(
        return_deep_global(json!({ "deep": nested_array(300) })).is_err(),
        "nesting beyond MAX_JSON_SERDE_DEPTH should still error"
    );
}
