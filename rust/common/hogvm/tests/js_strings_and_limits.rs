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
    assert_eq!(items[5].as_f64(), Some(0.0));
}

// return replaceAll(inputs.s, '', inputs.t)
const REPLACE_EMPTY: &str = r#"["_H", 1, 32, "s", 32, "inputs", 1, 2, 32, "", 32, "t", 32, "inputs", 1, 2, 2, "replaceAll", 3, 38]"#;
// return arrayStringConcat(inputs.a, inputs.t)
const JOIN: &str = r#"["_H", 1, 32, "a", 32, "inputs", 1, 2, 32, "t", 32, "inputs", 1, 2, 2, "arrayStringConcat", 2, 38]"#;
// return splitByString('', inputs.t)
const SPLIT_EMPTY: &str =
    r#"["_H", 1, 32, "", 32, "t", 32, "inputs", 1, 2, 2, "splitByString", 2, 38]"#;

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

// let a := {'x': 1}; for (let i := 0; i < 22; i := i + 1) { a := {'l': a, 'r': a} }
// return length(<call>(a))
fn shared_references(call: &str) -> String {
    format!(
        r#"["_H", 1, 32, "x", 33, 1, 42, 1, 33, 0, 33, 22, 36, 1, 15, 40, 21, 32, "l", 36, 0, 32, "r", 36, 0, 42, 2, 37, 0, 33, 1, 36, 1, 6, 37, 1, 39, -28, 35, 36, 0, 2, "{call}", 1, 2, "length", 1, 38]"#
    )
}
// return length(concat(inputs.t, inputs.t, inputs.t))
const CONCAT_SHARED: &str = r#"["_H", 1, 32, "t", 32, "inputs", 1, 2, 32, "t", 32, "inputs", 1, 2, 32, "t", 32, "inputs", 1, 2, 2, "concat", 3, 2, "length", 1, 38]"#;
// return length(jsonStringify(inputs.tree))
const STRINGIFY_TREE: &str =
    r#"["_H", 1, 32, "tree", 32, "inputs", 1, 2, 2, "jsonStringify", 1, 2, "length", 1, 38]"#;

#[test]
fn printing_shared_references_stops_at_the_heap_limit() {
    for call in ["jsonStringify", "toString", "concat"] {
        let program = Program::new(serde_json::from_str(&shared_references(call)).unwrap());
        let context = ExecutionContext::with_defaults(program.unwrap());
        let failure = sync_execute(&context, false).unwrap_err();
        assert!(
            matches!(failure.error, VmError::OutOfResource(_)),
            "{call}: {:?}",
            failure.error
        );
    }
    let big = json!({"inputs": {"t": "x".repeat(3 * 1024 * 1024)}});
    let failure = sync_execute(&context(CONCAT_SHARED, big), false).unwrap_err();
    assert!(matches!(failure.error, VmError::OutOfResource(_)));

    let rows: Vec<Value> = (0..20_000).map(|i| json!({"k": i, "v": "text"})).collect();
    let tree = json!({"inputs": {"tree": rows}});
    let printed = sync_execute(&context(STRINGIFY_TREE, tree), false).unwrap();
    assert!(printed.as_i64().unwrap() > 400_000, "{printed}");
}
