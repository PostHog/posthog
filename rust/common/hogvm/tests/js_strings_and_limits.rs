use hogvm::{sync_execute, ExecutionContext, Program, VmError};
use serde_json::{json, Value};

fn context(bytecode: &str, globals: Value) -> ExecutionContext {
    ExecutionContext::with_defaults(Program::new(serde_json::from_str(bytecode).unwrap()).unwrap())
        .with_globals(globals)
        .with_max_heap_size(8 * 1024 * 1024)
}

// return [length('é😀'), substring('é😀x', 2, 2), substring('é😀x', 3), position('é😀x', 'x'), splitByString('', 'ab'), (-4611686018427387904 * 2) % -1]
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

// let a := {'x': 1}; for (let i := 0; i < 22; i := i + 1) { a := {'l': a, 'r': a} }; return length(<call>(a))
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

const CYCLE_THROUGH_NATIVE: &str = r#"["_H", 1, 42, 0, 36, 0, 32, "self", 36, 0, 46, 36, 0, 2, "values", 1, 2, "length", 1, 38, 35]"#;
// `a.self := a` then `values(a)`, and 20,000 nested arrays then `values(a)`.
const DEEP_THROUGH_NATIVE: &str = r#"["_H", 1, 43, 0, 33, 0, 33, 20000, 36, 1, 15, 40, 15, 36, 0, 43, 1, 37, 0, 33, 1, 36, 1, 6, 37, 1, 39, -22, 35, 36, 0, 2, "values", 1, 2, "length", 1, 38, 35]"#;

#[test]
fn a_native_result_that_reaches_a_cycle_or_deep_nesting_does_not_overflow_the_stack() {
    assert_eq!(
        sync_execute(&context(CYCLE_THROUGH_NATIVE, json!({})), false).unwrap(),
        json!(1)
    );
    let failure = sync_execute(&context(DEEP_THROUGH_NATIVE, json!({})), false).unwrap_err();
    assert!(
        matches!(failure.error, VmError::OutOfResource(_)),
        "{:?}",
        failure.error
    );
}

// let n := {'__hx_ast': 'Not', 'expr': null}; n.expr := n; return toString(n)
const CYCLIC_AST: &str = r#"["_H", 1, 32, "__hx_ast", 32, "Not", 32, "expr", 31, 42, 2, 36, 0, 32, "expr", 36, 0, 46, 36, 0, 2, "toString", 1, 38, 35]"#;
const CYCLIC_AST_THROUGH_ARRAY: &str = r#"["_H", 1, 32, "__hx_ast", 32, "Not", 32, "expr", 31, 42, 2, 36, 0, 32, "expr", 36, 0, 43, 1, 46, 36, 0, 2, "toString", 1, 38, 35]"#;

// A `JoinExpr` node with `j.next_join := j`, printed with `toString`.
const CYCLIC_JOIN: &str = r#"["_H", 1, 32, "__hx_ast", 32, "JoinExpr", 32, "table", 32, "__hx_ast", 32, "Field", 32, "chain", 32, "t", 43, 1, 42, 2, 32, "next_join", 31, 42, 3, 36, 0, 32, "next_join", 36, 0, 46, 36, 0, 2, "toString", 1, 38, 35]"#;

// A `Field` node wrapped 24 times as `{'__hx_ast': 'Field', 'chain': [n]}`, printed with `toString`.
const NESTED_FIELD: &str = r#"["_H", 1, 32, "__hx_ast", 32, "Field", 32, "chain", 32, "x", 43, 1, 42, 2, 33, 0, 33, 24, 36, 1, 15, 40, 23, 32, "__hx_ast", 32, "Field", 32, "chain", 36, 0, 43, 1, 42, 2, 37, 0, 33, 1, 36, 1, 6, 37, 1, 39, -30, 35, 36, 0, 2, "toString", 1, 2, "length", 1, 38, 35]"#;

// An array of 16 `Field` nodes, each wrapped 20 times, printed with `toString`.
const WIDE_ARRAY: &str = r#"["_H", 1, 43, 0, 33, 0, 33, 16, 36, 1, 15, 40, 64, 32, "__hx_ast", 32, "Field", 32, "chain", 32, "x", 43, 1, 42, 2, 33, 0, 33, 20, 36, 3, 15, 40, 23, 32, "__hx_ast", 32, "Field", 32, "chain", 36, 2, 43, 1, 42, 2, 37, 2, 33, 1, 36, 3, 6, 37, 3, 39, -30, 35, 36, 0, 36, 2, 2, "arrayPushBack", 2, 37, 0, 35, 33, 1, 36, 1, 6, 37, 1, 39, -71, 35, 36, 0, 2, "toString", 1, 2, "length", 1, 38, 35]"#;

#[test]
fn printing_a_sql_ast_that_holds_itself_or_escapes_itself_again_ends() {
    for bytecode in [
        CYCLIC_AST,
        CYCLIC_AST_THROUGH_ARRAY,
        CYCLIC_JOIN,
        NESTED_FIELD,
        WIDE_ARRAY,
    ] {
        let failure = sync_execute(&context(bytecode, json!({})), false).unwrap_err();
        assert!(
            matches!(failure.error, VmError::OutOfResource(_)),
            "{:?}",
            failure.error
        );
    }
}

// fun make() { let x := null; let f := () -> x; x := () -> x; return f }; let f := make(); return f == f
const CLOSURE_HOLDS_ITSELF: &str = r#"["_H", 1, 52, "make", 0, 0, 32, 31, 52, "lambda", 0, 1, 3, 55, 0, 38, 53, 1, true, 0, 52, "lambda", 0, 1, 3, 55, 0, 38, 53, 1, true, 0, 37, 0, 36, 1, 38, 35, 57, 53, 0, 36, 0, 54, 0, 36, 1, 36, 1, 11, 38, 35, 35]"#;
// fun make(prev) { return (x) -> prev }; fun build(n) { if (n == 0) { return null } return make(build(n - 1)) }; build(inputs.n); return 1
const CLOSURE_CHAIN: &str = r#"["_H", 1, 52, "make", 1, 0, 13, 52, "lambda", 1, 1, 3, 55, 0, 38, 53, 1, true, 0, 38, 53, 0, 52, "build", 1, 2, 23, 33, 0, 36, 0, 11, 40, 2, 31, 38, 33, 1, 36, 0, 7, 55, 0, 54, 1, 55, 1, 54, 1, 38, 53, 2, true, 1, true, 0, 32, "n", 32, "inputs", 1, 2, 36, 1, 54, 1, 35, 33, 1, 38, 57, 57]"#;

#[test]
fn comparing_or_dropping_closures_that_hold_closures_does_not_overflow_the_stack() {
    let itself = sync_execute(&context(CLOSURE_HOLDS_ITSELF, json!({})), false).unwrap();
    assert_eq!(itself, json!(true));

    let chain = context(CLOSURE_CHAIN, json!({"inputs": {"n": 60000}})).with_max_steps(usize::MAX);
    assert_eq!(sync_execute(&chain, false).unwrap(), json!(1));
}
