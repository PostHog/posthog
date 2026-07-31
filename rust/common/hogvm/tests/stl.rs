//! Self-contained STL coverage: builds tiny bytecode programs that call a single native function
//! and asserts the result. These replace the (omitted) Node-oracle parity harness for the STL
//! surface that carries the most regression risk — the crypto/base64 natives backed by new
//! dependencies, JSON round-tripping that must preserve key order, and first-class tuples.

use hogvm::{sync_execute, ExecutionContext, Program};
use serde_json::{json, Value};

// Opcode numeric values (mirror common/hogvm/python/operation.py).
const OP_CALL_GLOBAL: i64 = 2;
const OP_STRING: i64 = 32;
const OP_INTEGER: i64 = 33;
const OP_RETURN: i64 = 38;
const OP_ARRAY: i64 = 43;
const OP_TUPLE: i64 = 44;

/// Wrap a value-producing fragment in a program header + `RETURN` and execute it.
fn run(fragment: Vec<Value>) -> Value {
    let mut bc = vec![json!("_H"), json!(1)];
    bc.extend(fragment);
    bc.push(json!(OP_RETURN));
    let program = Program::new(bc).expect("valid program");
    let ctx = ExecutionContext::with_defaults(program).with_globals(json!({}));
    sync_execute(&ctx, false).expect("execution succeeds")
}

fn str_lit(s: &str) -> Vec<Value> {
    vec![json!(OP_STRING), json!(s)]
}

fn int_lit(n: i64) -> Vec<Value> {
    vec![json!(OP_INTEGER), json!(n)]
}

/// `name(args…)`. The compiler pushes args left-to-right, so `args[0]` is the first listed.
fn call(name: &str, args: &[Vec<Value>]) -> Vec<Value> {
    let mut f = Vec::new();
    for a in args {
        f.extend(a.clone());
    }
    f.extend([json!(OP_CALL_GLOBAL), json!(name), json!(args.len() as i64)]);
    f
}

fn collection(op: i64, elems: &[Vec<Value>]) -> Vec<Value> {
    let mut f = Vec::new();
    for e in elems {
        f.extend(e.clone());
    }
    f.extend([json!(op), json!(elems.len() as i64)]);
    f
}

/// Single-string-arg native returning a string — the shape most STL functions take.
fn call_str(name: &str, arg: &str) -> Value {
    run(call(name, &[str_lit(arg)]))
}

#[test]
fn crypto_and_encoding_known_answers() {
    // Known-answer vectors — these are RFC/spec fixed, so they pin both our wiring and the
    // md-5 / sha2 / base64 dependencies to the correct output.
    let cases: &[(&str, &str, &str)] = &[
        ("md5Hex", "hello", "5d41402abc4b2a76b9719d911017c592"),
        (
            "sha256Hex",
            "hello",
            "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
        ),
        ("base64Encode", "hello", "aGVsbG8="),
        ("base64Decode", "aGVsbG8=", "hello"),
    ];
    for (name, input, expected) in cases {
        assert_eq!(call_str(name, input), json!(expected), "{name}({input:?})");
    }
}

#[test]
fn base64_round_trips() {
    let encoded = run(call("base64Encode", &[str_lit("Hello, World! 🦔")]));
    let decoded = run(call(
        "base64Decode",
        &[call("base64Encode", &[str_lit("Hello, World! 🦔")])],
    ));
    assert!(matches!(encoded, Value::String(_)));
    assert_eq!(decoded, json!("Hello, World! 🦔"));
}

#[test]
fn string_natives() {
    let cases: &[(&str, &[&str], Value)] = &[
        ("upper", &["aBc"], json!("ABC")),
        ("lower", &["aBc"], json!("abc")),
        ("trim", &["  hi  "], json!("hi")),
        ("trimLeft", &["  hi  "], json!("hi  ")),
        ("trimRight", &["  hi  "], json!("  hi")),
        ("concat", &["foo", "bar"], json!("foobar")),
        ("replaceAll", &["aaa", "a", "b"], json!("bbb")),
        ("replaceOne", &["aaa", "a", "b"], json!("baa")),
        ("length", &["hello"], json!(5)),
    ];
    for (name, args, expected) in cases {
        let arg_lits: Vec<Vec<Value>> = args.iter().map(|s| str_lit(s)).collect();
        assert_eq!(run(call(name, &arg_lits)), *expected, "{name}({args:?})");
    }
}

#[test]
fn type_coercion_natives() {
    assert_eq!(run(call("toString", &[int_lit(42)])), json!("42"));
    assert_eq!(run(call("toInt", &[str_lit("42")])), json!(42));
    assert_eq!(run(call("toFloat", &[str_lit("1.5")])), json!(1.5));
}

#[test]
fn array_natives() {
    let arr = || collection(OP_ARRAY, &[int_lit(1), int_lit(2), int_lit(3)]);

    assert_eq!(run(call("length", &[arr()])), json!(3));
    assert_eq!(run(call("has", &[arr(), int_lit(2)])), json!(true));
    assert_eq!(run(call("has", &[arr(), int_lit(9)])), json!(false));
    // arrayPushBack is pure (does not mutate in place) and appends.
    assert_eq!(
        run(call("arrayPushBack", &[arr(), int_lit(4)])),
        json!([1, 2, 3, 4])
    );
    // indexOf is 1-based; 0 means "not found" (Node-aligned, asserted in arrays.hog too).
    assert_eq!(run(call("indexOf", &[arr(), int_lit(3)])), json!(3));
    assert_eq!(run(call("indexOf", &[arr(), int_lit(9)])), json!(0));
}

#[test]
fn json_round_trip_preserves_key_order() {
    // The crux of the order-preserving HogJson deserialization: serde_json::Value would sort keys
    // (BTreeMap); the VM must keep document order so re-stringifying is stable.
    let result = run(call(
        "jsonStringify",
        &[call("jsonParse", &[str_lit(r#"{"b":1,"a":2,"c":3}"#)])],
    ));
    let Value::String(s) = result else {
        panic!("jsonStringify should return a string, got {result:?}");
    };
    let pos = |needle: &str| {
        s.find(needle)
            .unwrap_or_else(|| panic!("{needle} missing from {s}"))
    };
    assert!(
        pos("\"b\"") < pos("\"a\"") && pos("\"a\"") < pos("\"c\""),
        "expected insertion order b, a, c — got {s}"
    );
}

#[test]
fn tuples_are_distinct_from_arrays() {
    // A tuple prints with parens and reports its own type, unlike an array.
    let tup = || collection(OP_TUPLE, &[int_lit(1), int_lit(2), int_lit(3)]);
    assert_eq!(run(call("typeof", &[tup()])), json!("tuple"));
    assert_eq!(
        run(call("typeof", &[collection(OP_ARRAY, &[int_lit(1)])])),
        json!("array")
    );
    // Tuples still index and report length like arrays.
    assert_eq!(run(call("length", &[tup()])), json!(3));
}
