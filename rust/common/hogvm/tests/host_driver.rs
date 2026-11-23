use std::sync::Arc;

use hogvm::{
    ExecutionContext, HogLiteral, HogVM, HogValue, Num, OrderedJson, Program, RegexCache,
    StepOutcome,
};
use serde_json::{json, Value};

fn program(bytecode: &str) -> Program {
    Program::new(serde_json::from_str(bytecode).unwrap()).unwrap()
}

fn ordered_record() -> OrderedJson {
    let attributes = OrderedJson::Object(vec![
        ("b".into(), OrderedJson::String(Arc::from("1"))),
        ("a".into(), OrderedJson::Number(Num::Integer(2))),
    ]);
    OrderedJson::Object(vec![(
        "record".into(),
        OrderedJson::Object(vec![("attributes".into(), attributes)]),
    )])
}

fn object_keys(vm: &HogVM, value: &HogValue) -> Vec<String> {
    match value.deref(&vm.heap).unwrap() {
        HogLiteral::Object(map) => map.keys().cloned().collect(),
        other => panic!("expected an object, got {other:?}"),
    }
}

// `serde_json` sorts keys, so without ordered globals `keys()` and the result read `a, b`.
#[test]
fn ordered_globals_keep_key_order_through_keys_and_a_raw_result() {
    // let m := record.attributes; m.c := keys(m); return m
    let context = ExecutionContext::with_defaults(program(r#"["_H", 1, 32, "attributes", 32, "record", 1, 2, 36, 0, 32, "c", 36, 0, 2, "keys", 1, 46, 36, 0, 38, 35]"#))
    .with_ordered_globals(ordered_record())
    .with_raw_result();
    let mut vm = context.to_vm().unwrap();
    loop {
        match vm.step().unwrap() {
            StepOutcome::Continue => {}
            StepOutcome::NativeCall(name, args) => {
                context
                    .execute_native_function_call(&mut vm, &name, args)
                    .unwrap();
            }
            StepOutcome::Finished(json) => {
                assert_eq!(json, Value::Null);
                break;
            }
        }
    }
    let result = vm.take_result().unwrap();
    assert_eq!(object_keys(&vm, &result), vec!["b", "a", "c"]);
    let HogLiteral::Object(map) = result.deref(&vm.heap).unwrap() else {
        unreachable!()
    };
    let keys: Vec<String> = match map["c"].deref(&vm.heap).unwrap() {
        HogLiteral::Array(items) => items
            .iter()
            .map(|k| {
                k.deref(&vm.heap)
                    .unwrap()
                    .try_as::<str>()
                    .unwrap()
                    .to_string()
            })
            .collect(),
        other => panic!("expected an array, got {other:?}"),
    };
    assert_eq!(keys, vec!["b", "a"]);
}

#[test]
fn a_missing_key_under_an_ordered_global_reads_null() {
    let context = ExecutionContext::with_defaults(program(
        r#"["_H", 1, 32, "missing", 32, "inputs", 1, 2, 38]"#,
    ))
    .with_ordered_globals(OrderedJson::Object(vec![(
        "inputs".into(),
        OrderedJson::Object(vec![]),
    )]));
    assert_eq!(hogvm::sync_execute(&context, false).unwrap(), Value::Null);
}

// return [inputs.list.1, inputs.list.-1, inputs.list.3, inputs.list.<i64::MIN>]
#[test]
fn a_global_array_reads_by_index_from_either_end() {
    let read = program(
        r#"["_H", 1, 33, 1, 32, "list", 32, "inputs", 1, 3, 33, -1, 32, "list", 32, "inputs", 1, 3, 33, 3, 32, "list", 32, "inputs", 1, 3, 33, -9223372036854775808, 32, "list", 32, "inputs", 1, 3, 43, 4, 38]"#,
    );
    let ordered = OrderedJson::Object(vec![(
        "inputs".into(),
        OrderedJson::Object(vec![(
            "list".into(),
            OrderedJson::Array(vec![
                OrderedJson::String(Arc::from("first")),
                OrderedJson::String(Arc::from("last")),
            ]),
        )]),
    )]);
    for context in [
        ExecutionContext::with_defaults(read.clone()).with_ordered_globals(ordered),
        ExecutionContext::with_defaults(read)
            .with_globals(json!({"inputs": {"list": ["first", "last"]}})),
    ] {
        assert_eq!(
            hogvm::sync_execute(&context, false).unwrap(),
            json!(["first", "last", null, null])
        );
    }
}

#[test]
fn memory_bytes_counts_stack_strings_and_push_stack_answers_a_call() {
    // let s := concat('ab', 'cd'); return s
    let context = ExecutionContext::with_defaults(program(
        r#"["_H", 1, 32, "ab", 32, "cd", 2, "concat", 2, 36, 0, 38, 35]"#,
    ));
    let mut vm = context.to_vm().unwrap();
    let finished = loop {
        match vm.step().unwrap() {
            StepOutcome::Continue => {}
            StepOutcome::NativeCall(name, _args) => {
                assert_eq!(name, "concat");
                vm.push_stack(HogLiteral::from("answered by the host".to_string()))
                    .unwrap();
                assert!(vm.memory_bytes() >= "answered by the host".len());
            }
            StepOutcome::Finished(json) => break json,
        }
    };
    assert_eq!(finished, json!("answered by the host"));
}

#[test]
fn printing_many_references_to_one_global_string_stops_at_the_heap_limit() {
    let context = ExecutionContext::with_defaults(program(
        r#"["_H", 1, 32, "t", 32, "inputs", 1, 2, 32, "t", 32, "inputs", 1, 2, 32, "t", 32, "inputs", 1, 2, 32, "t", 32, "inputs", 1, 2, 32, "t", 32, "inputs", 1, 2, 32, "t", 32, "inputs", 1, 2, 32, "t", 32, "inputs", 1, 2, 32, "t", 32, "inputs", 1, 2, 32, "t", 32, "inputs", 1, 2, 32, "t", 32, "inputs", 1, 2, 43, 10, 2, "jsonStringify", 1, 2, "length", 1, 38]"#,
    ))
    .with_ordered_globals(OrderedJson::Object(vec![(
        "inputs".into(),
        OrderedJson::Object(vec![(
            "t".into(),
            OrderedJson::String(Arc::from("x".repeat(300 * 1024))),
        )]),
    )]));
    let failure = hogvm::sync_execute(&context, false).unwrap_err();
    assert!(
        matches!(failure.error, hogvm::VmError::OutOfResource(_)),
        "{:?}",
        failure.error
    );
}

#[test]
fn the_sql_printer_ends_on_a_join_that_joins_itself() {
    let context = ExecutionContext::with_defaults(program(
        r#"["_H", 1, 32, "__hx_ast", 32, "JoinExpr", 32, "table", 32, "t", 32, "next_join", 31, 42, 3, 36, 0, 32, "next_join", 36, 0, 46, 36, 0, 38, 35]"#,
    ))
    .with_raw_result();
    let mut vm = context.to_vm().unwrap();
    while !matches!(vm.step().unwrap(), StepOutcome::Finished(_)) {}
    let join = vm.take_result().unwrap();
    let printed = hogvm::print_hog_value(&vm.heap, &join, &mut Vec::new(), 0);
    assert!(
        matches!(printed, Err(hogvm::VmError::OutOfResource(_))),
        "{printed:?}"
    );
}

#[test]
fn a_run_frees_a_closure_that_captures_itself() {
    // fun make(big) { let x := null; x := () -> [x, big]; return 1 }; make(inputs.t); return 1
    let text: Arc<str> = Arc::from("held by the closure");
    let context = ExecutionContext::with_defaults(program(
        r#"["_H", 1, 52, "make", 1, 0, 25, 31, 52, "lambda", 0, 2, 7, 55, 0, 55, 1, 43, 2, 38, 53, 2, true, 1, true, 0, 37, 1, 33, 1, 38, 57, 53, 0, 32, "t", 32, "inputs", 1, 2, 36, 0, 54, 1, 35, 33, 1, 38, 35]"#,
    ))
    .with_ordered_globals(OrderedJson::Object(vec![(
        "inputs".into(),
        OrderedJson::Object(vec![("t".into(), OrderedJson::String(text.clone()))]),
    )]));
    let held_before = Arc::strong_count(&text);
    hogvm::sync_execute(&context, false).unwrap();
    assert_eq!(Arc::strong_count(&text), held_before);
}

#[test]
fn a_bounded_regex_cache_keeps_small_patterns_and_compiles_large_ones_per_call() {
    // return [match('aaa', inputs.small), match('aaa', inputs.large)]
    let cache = Arc::new(RegexCache::bounded(8, 4 * 1024));
    let context = ExecutionContext::with_defaults(program(
        r#"["_H", 1, 32, "aaa", 32, "small", 32, "inputs", 1, 2, 2, "match", 2, 32, "aaa", 32, "large", 32, "inputs", 1, 2, 2, "match", 2, 43, 2, 38]"#,
    ))
    .with_globals(json!({"inputs": {"small": "a+", "large": "\\w{200}"}}))
    .with_regex_cache(cache.clone());
    assert_eq!(
        hogvm::sync_execute(&context, false).unwrap(),
        json!([true, false])
    );
    assert!(cache.contains("a+", false));
    assert!(!cache.contains("\\w{200}", false));
}

#[test]
fn the_public_printer_refuses_a_value_that_repeats_past_the_heap_limit() {
    // let a := [1]; 21 times: a := [a, a]; return a
    let context = ExecutionContext::with_defaults(program(
        r#"["_H", 1, 33, 1, 43, 1, 33, 0, 33, 21, 36, 1, 15, 40, 17, 36, 0, 36, 0, 43, 2, 37, 0, 33, 1, 36, 1, 6, 37, 1, 39, -24, 35, 36, 0, 38, 35]"#,
    ))
    .with_raw_result();
    let mut vm = context.to_vm().unwrap();
    while !matches!(vm.step().unwrap(), StepOutcome::Finished(_)) {}
    let result = vm.take_result().unwrap();
    let printed = hogvm::print_hog_value(&vm.heap, &result, &mut Vec::new(), 0);
    assert!(
        matches!(printed, Err(hogvm::VmError::OutOfResource(_))),
        "{:?}",
        printed.map(|text| text.len())
    );
}

// fun make(big) { let f := () -> big; return f }; let f := make(concat(inputs.t, 'x')); asyncFetch(1); return 1
const STRING_HELD_ONLY_BY_A_CLOSURE: &str = r#"["_H", 1, 52, "make", 1, 0, 16, 52, "lambda", 0, 1, 3, 55, 0, 38, 53, 1, true, 0, 36, 1, 38, 35, 53, 0, 32, "t", 32, "inputs", 1, 2, 32, "x", 2, "concat", 2, 36, 0, 54, 1, 33, 1, 2, "asyncFetch", 1, 35, 33, 1, 38, 35, 35]"#;

#[test]
fn memory_bytes_counts_a_string_that_only_a_closure_holds() {
    let context = ExecutionContext::with_defaults(program(STRING_HELD_ONLY_BY_A_CLOSURE))
        .with_ordered_globals(OrderedJson::Object(vec![(
            "inputs".into(),
            OrderedJson::Object(vec![(
                "t".into(),
                OrderedJson::String(Arc::from("t".repeat(1024 * 1024))),
            )]),
        )]))
        .with_max_heap_size(8 * 1024 * 1024);
    let mut vm = context.to_vm().unwrap();
    loop {
        match vm.step().unwrap() {
            StepOutcome::NativeCall(name, args) if name == "concat" => {
                context
                    .execute_native_function_call(&mut vm, &name, args)
                    .unwrap();
            }
            StepOutcome::NativeCall(name, _) => {
                assert_eq!(name, "asyncFetch");
                break;
            }
            StepOutcome::Continue => {}
            StepOutcome::Finished(_) => panic!("the program ended before its last call"),
        }
    }
    assert!(vm.memory_bytes() >= 1024 * 1024, "{}", vm.memory_bytes());
}

#[test]
fn a_host_checks_native_arguments_before_it_answers_a_call() {
    // return length(inputs.list)
    let call = program(r#"["_H", 1, 32, "list", 32, "inputs", 1, 2, 2, "length", 1, 38]"#);
    let arguments_fit = |copies: usize| {
        let text: Arc<str> = Arc::from("t".repeat(64 * 1024));
        let list = OrderedJson::Array(vec![OrderedJson::String(text); copies]);
        let context = ExecutionContext::with_defaults(call.clone()).with_ordered_globals(
            OrderedJson::Object(vec![(
                "inputs".into(),
                OrderedJson::Object(vec![("list".into(), list)]),
            )]),
        );
        let mut vm = context.to_vm().unwrap();
        loop {
            match vm.step().unwrap() {
                StepOutcome::NativeCall(_, args) => {
                    return hogvm::assert_native_arguments_fit(&vm.heap, &args);
                }
                StepOutcome::Continue => {}
                StepOutcome::Finished(_) => panic!("the program made no native call"),
            }
        }
    };
    assert!(arguments_fit(4).is_ok());
    assert!(matches!(
        arguments_fit(64),
        Err(hogvm::VmError::OutOfResource(_))
    ));
}
