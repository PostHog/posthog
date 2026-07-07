//! `LIKE`/`ILIKE` `%` must span newlines, matching ClickHouse and the reference VM's unanchored
//! matcher. The pattern compiles to an anchored regex, and the regex crate's `.` excludes `\n`, so
//! mapping `%` to `.*` silently missed matches when the haystack wrapped across lines — e.g.
//! `elements_chain ilike '%onetrust%'`, since element chains carry newlines in their text and
//! attributes. `_` stays `.` (a single non-newline char), matching the reference's `_` -> `.`.

use hogvm::{sync_execute, ExecutionContext, Program};
use serde_json::{json, Value};

const OP_LIKE: i64 = 17;
const OP_ILIKE: i64 = 18;
const OP_STRING: i64 = 32;
const OP_RETURN: i64 = 38;

fn run(bytecode: Vec<Value>) -> Value {
    let program = Program::new(bytecode).expect("valid program");
    let ctx = ExecutionContext::with_defaults(program);
    sync_execute(&ctx, false).expect("execution succeeds")
}

// Stack order: pattern is pushed first, then the value (the VM pops the value first).
fn like_of(pattern: &str, value: &str, op: i64) -> Vec<Value> {
    vec![
        json!("_H"),
        json!(1),
        json!(OP_STRING),
        json!(pattern),
        json!(OP_STRING),
        json!(value),
        json!(op),
        json!(OP_RETURN),
    ]
}

#[test]
fn percent_wildcard_spans_newlines() {
    let chain = "button:attr__class=\"btn\"\nonetrust-accept-btn-handler\nspan";
    assert_eq!(
        run(like_of("%onetrust-accept-btn-handler%", chain, OP_ILIKE)),
        Value::Bool(true),
        "%% wildcard should cross the newline before the token"
    );
    // A token that never appears is still no match.
    assert_eq!(
        run(like_of("%missing-handler%", chain, OP_ILIKE)),
        Value::Bool(false)
    );
}

#[test]
fn underscore_stays_a_single_non_newline_char() {
    // `_` -> `.`, matching the reference; it does not cross a newline.
    assert_eq!(run(like_of("a_b", "aXb", OP_LIKE)), Value::Bool(true));
    assert_eq!(run(like_of("a_b", "a\nb", OP_LIKE)), Value::Bool(false));
}
