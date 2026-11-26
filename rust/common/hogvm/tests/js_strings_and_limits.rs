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
// return replaceAll(inputs.s, 'a', inputs.t)
const REPLACE_EACH_A: &str = r#"["_H", 1, 32, "s", 32, "inputs", 1, 2, 32, "a", 32, "t", 32, "inputs", 1, 2, 2, "replaceAll", 3, 38]"#;
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
        (
            REPLACE_EACH_A,
            json!({"inputs": {"s": "a".repeat(1000), "t": big}}),
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
// fun make() { let x := 1; let f := () -> x; return f }; return make() == make()
const CLOSURES_OF_TWO_CALLS: &str = r#"["_H", 1, 52, "make", 0, 0, 19, 33, 1, 52, "lambda", 0, 1, 3, 55, 0, 38, 53, 1, true, 0, 36, 1, 38, 35, 57, 53, 0, 36, 0, 54, 0, 36, 0, 54, 0, 11, 38, 35]"#;
// fun make(prev) { return (x) -> prev }; fun build(n) { if (n == 0) { return null } return make(build(n - 1)) }; build(inputs.n); return 1
const CLOSURE_CHAIN: &str = r#"["_H", 1, 52, "make", 1, 0, 13, 52, "lambda", 1, 1, 3, 55, 0, 38, 53, 1, true, 0, 38, 53, 0, 52, "build", 1, 2, 23, 33, 0, 36, 0, 11, 40, 2, 31, 38, 33, 1, 36, 0, 7, 55, 0, 54, 1, 55, 1, 54, 1, 38, 53, 2, true, 1, true, 0, 32, "n", 32, "inputs", 1, 2, 36, 1, 54, 1, 35, 33, 1, 38, 57, 57]"#;

// The same `make`, then `return ed25519Verify('', '', '', make())`, whose error message prints the fourth argument.
const CLOSURE_IN_AN_ERROR: &str = r#"["_H", 1, 52, "make", 0, 0, 32, 31, 52, "lambda", 0, 1, 3, 55, 0, 38, 53, 1, true, 0, 52, "lambda", 0, 1, 3, 55, 0, 38, 53, 1, true, 0, 37, 0, 36, 1, 38, 35, 57, 53, 0, 32, "", 32, "", 32, "", 36, 0, 54, 0, 2, "ed25519Verify", 4, 38, 35]"#;

#[test]
fn comparing_printing_or_dropping_closures_that_hold_closures_does_not_overflow_the_stack() {
    let itself = sync_execute(&context(CLOSURE_HOLDS_ITSELF, json!({})), false).unwrap();
    assert_eq!(itself, json!(true));
    let two_calls = sync_execute(&context(CLOSURES_OF_TWO_CALLS, json!({})), false).unwrap();
    assert_eq!(two_calls, json!(false));

    let failure = sync_execute(&context(CLOSURE_IN_AN_ERROR, json!({})), false).unwrap_err();
    assert!(
        matches!(failure.error, VmError::NativeCallFailed(_)),
        "{:?}",
        failure.error
    );

    let chain = context(CLOSURE_CHAIN, json!({"inputs": {"n": 60000}})).with_max_steps(usize::MAX);
    assert_eq!(sync_execute(&chain, false).unwrap(), json!(1));
}

// let n := {'__hx_ast': 'Not', 'expr': null}; n.expr := n; return jsonStringify(n)
const CYCLIC_AST_AS_JSON: &str = r#"["_H", 1, 32, "__hx_ast", 32, "Not", 32, "expr", 31, 42, 2, 36, 0, 32, "expr", 36, 0, 46, 36, 0, 2, "jsonStringify", 1, 38, 35]"#;
// let s := inputs.s; return replaceOne(s, s, '')
const REPLACE_ALL_OF_IT: &str =
    r#"["_H", 1, 32, "s", 32, "inputs", 1, 2, 36, 0, 36, 0, 32, "", 2, "replaceOne", 3, 38, 35]"#;

#[test]
fn limits_do_not_refuse_what_fits() {
    let json = sync_execute(&context(CYCLIC_AST_AS_JSON, json!({})), false).unwrap();
    assert!(json.as_str().unwrap().contains("__hx_ast"), "{json}");

    let large = "x".repeat(5 * 1024 * 1024);
    let replaced = sync_execute(
        &context(REPLACE_ALL_OF_IT, json!({"inputs": {"s": large}})),
        false,
    );
    assert_eq!(replaced.unwrap(), json!(""));
}

// let a := range(2000); let h := range(2000); for i in 1..=2000: h[i] := a; let b := range(2000); b[2000] := -1; return <test of b in h>
const ONE_ARRAY_MANY_TIMES: &str = r#"["_H", 1, 33, 2000, 2, "range", 1, 33, 2000, 2, "range", 1, 33, 1, 33, 2000, 36, 2, 16, 40, 16, 36, 1, 36, 2, 36, 0, 46, 33, 1, 36, 2, 6, 37, 2, 39, -23, 35, 33, 2000, 2, "range", 1, 36, 2, 33, 2000, 33, -1, 46, "#;

#[test]
fn membership_stops_on_a_list_that_holds_one_array_many_times() {
    // b in h, has(h, b), indexOf(h, b), in(b, h)
    for test in [
        r#"36, 1, 36, 2, 21"#,
        r#"36, 1, 36, 2, 2, "has", 2"#,
        r#"36, 1, 36, 2, 2, "indexOf", 2"#,
        r#"36, 2, 36, 1, 2, "in", 2"#,
    ] {
        let bytecode = format!("{ONE_ARRAY_MANY_TIMES}{test}, 38, 35, 35, 35]");
        let context = context(&bytecode, json!({})).with_max_steps(1_000_000);
        let error = sync_execute(&context, false).unwrap_err().error;
        assert!(
            matches!(error, hogvm::VmError::OutOfResource(_)),
            "{test}: {error:?}"
        );
    }
}

// let a := []; let b := []; 100 times: a := arrayPushBack(a, '<A>'); b := arrayPushBack(b, '<B>'); then by inputs.mode:
// 'eq': return a == b; 'equals': return equals(a, b); 'empty': return [] == a; 'bool': return true in a; else: return '<C>' in a
const ONE_LITERAL_MANY_TIMES: &str = r#"["_H", 1, 43, 0, 43, 0, 33, 0, 33, 100, 36, 2, 15, 40, 27, 36, 0, 32, "ZZA", 2, "arrayPushBack", 2, 37, 0, 36, 1, 32, "ZZB", 2, "arrayPushBack", 2, 37, 1, 33, 1, 36, 2, 6, 37, 2, 39, -34, 35, 32, "eq", 32, "mode", 32, "inputs", 1, 2, 11, 40, 6, 36, 1, 36, 0, 11, 38, 32, "equals", 32, "mode", 32, "inputs", 1, 2, 11, 40, 8, 36, 0, 36, 1, 2, "equals", 2, 38, 32, "empty", 32, "mode", 32, "inputs", 1, 2, 11, 40, 6, 36, 0, 43, 0, 11, 38, 32, "bool", 32, "mode", 32, "inputs", 1, 2, 11, 40, 5, 36, 0, 29, 21, 38, 36, 0, 32, "ZZC", 21, 38, 35, 35]"#;

#[test]
fn a_test_against_one_long_literal_many_times_stops() {
    let text = "z".repeat(1024 * 1024);
    let bytecode = ONE_LITERAL_MANY_TIMES
        .replace("ZZA", &text)
        .replace("ZZB", &text)
        .replace("ZZC", &format!("{}y", &text[1..]));
    let run = |mode: &str| {
        let context =
            context(&bytecode, json!({"inputs": {"mode": mode}})).with_max_steps(1_000_000);
        sync_execute(&context, false).map_err(|failure| failure.error)
    };
    for mode in ["in", "eq", "equals", "bool"] {
        let error = run(mode).unwrap_err();
        assert!(
            matches!(error, hogvm::VmError::OutOfResource(_)),
            "{mode}: {error:?}"
        );
    }
    assert_eq!(run("empty").unwrap(), json!(false));
}

// let s := 'x'; 20 times: s := concat(s, s); let a := []; 64 times: a := arrayPushBack(a, s); return length(jsonStringify(a))
const ONE_BUILT_STRING_MANY_TIMES: &str = r#"["_H", 1, 32, "x", 33, 0, 33, 20, 36, 1, 15, 40, 18, 36, 0, 36, 0, 2, "concat", 2, 37, 0, 33, 1, 36, 1, 6, 37, 1, 39, -25, 35, 43, 0, 33, 0, 33, 64, 36, 2, 15, 40, 18, 36, 1, 36, 0, 2, "arrayPushBack", 2, 37, 1, 33, 1, 36, 2, 6, 37, 2, 39, -25, 35, 36, 1, 2, "jsonStringify", 1, 2, "length", 1, 38, 35, 35]"#;

#[test]
fn many_references_to_one_built_string_print_inside_the_heap_limit() {
    let context = context(ONE_BUILT_STRING_MANY_TIMES, json!({})).with_max_steps(1_000_000);
    let error = sync_execute(&context, false).unwrap_err().error;
    assert!(
        matches!(error, hogvm::VmError::OutOfResource(_)),
        "{error:?}"
    );
}

// let a := [null]; let t := (a, a); a[1] := t; return [jsonStringify(t), toString(t)]
const TUPLE_THAT_HOLDS_ITSELF: &str = r#"["_H", 1, 31, 43, 1, 36, 0, 36, 0, 44, 2, 36, 0, 33, 1, 36, 1, 46, 36, 1, 2, "jsonStringify", 1, 36, 1, 2, "toString", 1, 43, 2, 38, 35, 35]"#;

#[test]
fn a_tuple_that_holds_itself_prints_null_where_it_repeats() {
    let printed = sync_execute(&context(TUPLE_THAT_HOLDS_ITSELF, json!({})), false).unwrap();
    assert_eq!(printed, json!(["[[null], [null]]", "([null], [null])"]));
}

// let a := []; 3000 times: a := arrayPushBack(a, null); return length(a)
const KEEP_EVERY_COPY_OF_A_NULL_ARRAY: &str = r#"["_H", 1, 43, 0, 33, 0, 33, 3000, 36, 1, 15, 40, 17, 36, 0, 31, 2, "arrayPushBack", 2, 37, 0, 33, 1, 36, 1, 6, 37, 1, 39, -24, 35, 36, 0, 2, "length", 1, 38, 35]"#;

#[test]
fn nulls_in_an_array_count_toward_the_heap_limit() {
    let context = context(KEEP_EVERY_COPY_OF_A_NULL_ARRAY, json!({})).with_max_steps(1_000_000);
    let error = sync_execute(&context, false).unwrap_err().error;
    assert!(
        matches!(error, hogvm::VmError::OutOfResource(_)),
        "{error:?}"
    );
}

// return [inputs.s =~ inputs.p]
const MATCH_INPUT_PATTERN: &str =
    r#"["_H", 1, 32, "p", 32, "inputs", 1, 2, 32, "s", 32, "inputs", 1, 2, 23, 43, 1, 38]"#;

#[test]
fn a_bounded_regex_cache_refuses_the_repetitions_that_re2_refuses() {
    let run = |pattern: &str, bounded: bool| {
        let mut context = context(
            MATCH_INPUT_PATTERN,
            json!({"inputs": {"s": "aaa", "p": pattern}}),
        );
        if bounded {
            context = context.with_regex_cache(std::sync::Arc::new(hogvm::RegexCache::bounded(
                8,
                128 * 1024,
            )));
        }
        sync_execute(&context, false).map_err(|failure| failure.error)
    };
    let long = format!("a{{1001}}{}", "(?:)".repeat(260));
    for pattern in ["a{1001}", "a{2,1001}", "(a{40}){40}", long.as_str()] {
        assert!(
            matches!(run(pattern, true), Err(hogvm::VmError::InvalidRegex(..))),
            "{pattern}"
        );
        assert!(run(pattern, false).is_ok(), "{pattern}");
    }
    for pattern in ["a{3}", "a{1000}|a+", "(a{25}){40}|a"] {
        assert_eq!(run(pattern, true).unwrap(), json!([true]), "{pattern}");
    }
}

// 400 times: let o := {}; o['<1 MiB>'] := 1
const ONE_LONG_KEY_IN_MANY_OBJECTS: &str = r#"["_H", 1, 33, 0, 33, 400, 36, 0, 15, 40, 19, 42, 0, 36, 1, 32, "ZZK", 33, 1, 46, 35, 33, 1, 36, 0, 6, 37, 0, 39, -26, 35, 33, 1, 38]"#;

#[test]
fn a_long_key_counts_toward_the_heap_limit_in_each_object_that_copies_it() {
    let bytecode = ONE_LONG_KEY_IN_MANY_OBJECTS.replace("ZZK", &"k".repeat(1024 * 1024));
    let error = sync_execute(&context(&bytecode, json!({})), false)
        .unwrap_err()
        .error;
    assert!(
        matches!(error, hogvm::VmError::OutOfResource(_)),
        "{error:?}"
    );
}

// let o := {}; o['<K>'] := 'v'; let n := {}; n['<K>'] := 'w'; let h := range(1000); for i in 1..=1000: h[i] := o; return n in h
const ONE_LONG_KEYED_OBJECT_MANY_TIMES: &str = r#"["_H", 1, 42, 0, 36, 0, 32, "ZZK", 32, "v", 46, 42, 0, 36, 1, 32, "ZZK", 32, "w", 46, 33, 1000, 2, "range", 1, 33, 1, 33, 1000, 36, 3, 16, 40, 16, 36, 2, 36, 3, 36, 0, 46, 33, 1, 36, 3, 6, 37, 3, 39, -23, 35, 36, 2, 36, 1, 21, 38, 35, 35, 35]"#;

#[test]
fn membership_counts_the_keys_that_an_object_compare_reads() {
    let bytecode = ONE_LONG_KEYED_OBJECT_MANY_TIMES.replace("ZZK", &"k".repeat(128 * 1024));
    let context = context(&bytecode, json!({})).with_max_steps(1_000_000);
    let error = sync_execute(&context, false).unwrap_err().error;
    assert!(
        matches!(error, hogvm::VmError::OutOfResource(_)),
        "{error:?}"
    );
}
