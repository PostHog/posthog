use std::collections::HashMap;

use hogvm::{sync_execute, ExecutionContext, HogLiteral, NativeFunction};
use serde_json::{json, Value};

const fn stl_test_extensions() -> &'static [(&'static str, NativeFunction)] {
    &[
        ("print", |_, args| {
            println!("{:?}", args);
            Ok(HogLiteral::Null.into())
        }),
        ("assert_eq", |vm, args| {
            // Used in test programs
            let lhs = args.first().unwrap();
            let rhs = args.get(1).unwrap();
            if lhs
                .equals(rhs, &vm.heap)
                .expect("Could compare")
                .try_into()
                .expect("Could convert")
            {
                Ok(HogLiteral::Null.into())
            } else {
                panic!("{:?} did not equal {:?}", lhs, rhs)
            }
        }),
        ("assert", |vm, args| {
            // Used in test programs
            let condition = args.first().unwrap().deref(&vm.heap).unwrap();
            if *condition.try_as().expect("Could convert") {
                Ok(HogLiteral::Null.into())
            } else {
                panic!("Assertion failed")
            }
        }),
    ]
}

// This could maybe be moved to the stl module, it seems useful
fn to_extension(ext: &'static [(&'static str, NativeFunction)]) -> HashMap<String, NativeFunction> {
    ext.iter().map(|(a, b)| (a.to_string(), *b)).collect()
}

fn load_test_programs() -> Vec<(String, String)> {
    let test_program_path = std::env::current_dir()
        .unwrap()
        .join("tests/static/test_programs");

    let mut res = Vec::new();
    for file in test_program_path
        .read_dir()
        .expect("Could read test programs")
    {
        let file = file.unwrap();
        if !file.file_name().to_str().unwrap().ends_with(".hoge") {
            continue;
        }
        let name = file.file_name().to_str().unwrap().to_string();
        let code = std::fs::read_to_string(file.path()).unwrap();
        res.push((name, code));
    }
    res
}

pub fn test_globals() -> Value {
    json!({
        "test": "value",
        "an_array": [1, 2, 3],
        "a_string": "Hello, World!",
        "a_number": 42,
        "a_boolean": true,
        "a_null": null,
        "a_nested_object": {
            "nested_key": "nested_value"
        }
    })
}

#[test]
pub fn test_vm() {
    let programs = load_test_programs();
    for program in programs {
        let (name, code) = program;
        println!("Running: {}", name);
        let parsed: Vec<Value> = serde_json::from_str(&code).unwrap();
        let ctx = ExecutionContext::with_defaults(&parsed)
            .with_ext_fns(to_extension(stl_test_extensions()))
            .with_globals(test_globals());
        let res = sync_execute(&ctx, false);
        println!("{:?}", res);
        assert!(res.is_ok());
        assert!(matches!(res, Ok(Value::Bool(true))))
    }
}
