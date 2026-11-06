//! String indexes count UTF-16 units like the reference VM, integer edge cases do not panic, and
//! string-building calls refuse a result past the heap limit before they build it.

use hogvm::{sync_execute, ExecutionContext, Program, VmError};
use serde_json::{json, Value};

fn context(bytecode: &str, globals: Value) -> ExecutionContext {
    ExecutionContext::with_defaults(Program::new(serde_json::from_str(bytecode).unwrap()).unwrap())
        .with_globals(globals)
        .with_max_heap_size(8 * 1024 * 1024)
}

// return [length('é😀'), substring('é😀x', 2, 2), substring('é😀x', 3), position('é😀x', 'x'),
//         splitByString('', 'ab'), (-4611686018427387904 * 2) % -1]
const STRINGS: &str = r#"["_H", 1, 32, "é😀", 2, "length", 1, 32, "é😀x", 33, 2, 33, 2, 2, "substring", 3, 32, "é😀x", 33, 3, 2, "substring", 2, 32, "é😀x", 32, "x", 2, "position", 2, 32, "", 32, "ab", 2, "splitByString", 2, 33, -1, 33, 2, 33, -4611686018427387904, 8, 10, 43, 6, 38]"#;

#[test]
fn string_indexes_count_utf16_units_and_integer_edges_do_not_panic() {
    let result = sync_execute(&context(STRINGS, json!({})), false).unwrap();
    let items = result.as_array().unwrap();
    assert_eq!(items[0], json!(3));
    assert_eq!(items[1], json!("😀"));
    // Node keeps the lone low surrogate. A Rust string cannot, so it becomes U+FFFD.
    assert_eq!(items[2], json!("\u{fffd}x"));
    assert_eq!(items[3], json!(4));
    assert_eq!(items[4], json!(["a", "b"]));
    // i64::MIN % -1 overflows i64. JavaScript gives -0.
    assert_eq!(items[5].as_f64(), Some(0.0));
}

// return replaceAll(inputs.s, '', inputs.t)
const REPLACE_EMPTY: &str = r#"["_H", 1, 32, "s", 32, "inputs", 1, 2, 32, "", 32, "t", 32, "inputs", 1, 2, 2, "replaceAll", 3, 38]"#;
// return arrayStringConcat(inputs.a, inputs.t)
const JOIN: &str = r#"["_H", 1, 32, "a", 32, "inputs", 1, 2, 32, "t", 32, "inputs", 1, 2, 2, "arrayStringConcat", 2, 38]"#;
// return splitByString('', inputs.t)
const SPLIT_EMPTY: &str =
    r#"["_H", 1, 32, "", 32, "t", 32, "inputs", 1, 2, 2, "splitByString", 2, 38]"#;

// Each of these is one native call whose output grows with the product of its inputs, so a check
// after the call would come after a gigabyte allocation.
#[test]
fn string_building_calls_refuse_results_past_the_heap_limit() {
    let big = "x".repeat(1024 * 1024);
    let cases = [
        (
            REPLACE_EMPTY,
            json!({"inputs": {"s": "y".repeat(1000), "t": big}}),
        ),
        (JOIN, json!({"inputs": {"a": vec![1; 1000], "t": big}})),
        (
            SPLIT_EMPTY,
            json!({"inputs": {"t": "z".repeat(1024 * 1024)}}),
        ),
    ];
    for (bytecode, globals) in cases {
        let failure = sync_execute(&context(bytecode, globals), false).unwrap_err();
        assert!(
            matches!(failure.error, VmError::OutOfResource(_)),
            "{bytecode}: {:?}",
            failure.error
        );
    }
    // Inside the limit the same calls succeed.
    let small = json!({"inputs": {"s": "ab", "t": "-", "a": [1, 2]}});
    assert_eq!(
        sync_execute(&context(REPLACE_EMPTY, small.clone()), false).unwrap(),
        json!("-a-b-")
    );
    assert_eq!(
        sync_execute(&context(JOIN, small), false).unwrap(),
        json!("1-2")
    );
}
