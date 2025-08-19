use std::collections::HashMap;

use hogvm::{native_func, sync_execute, ExecutionContext, HogLiteral, NativeFunction, Program};
use serde_json::{json, Value};

fn stl_test_extensions() -> HashMap<String, NativeFunction> {
    [
        (
            "print",
            native_func(|_, args| {
                println!("{args:?}");
                Ok(HogLiteral::Null.into())
            }),
        ),
        (
            "assert_eq",
            native_func(|vm, args| {
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
                    panic!("{lhs:?} did not equal {rhs:?}")
                }
            }),
        ),
        (
            "assert",
            native_func(|vm, args| {
                // Used in test programs
                let condition = args.first().unwrap().deref(&vm.heap).unwrap();
                if *condition.try_as().expect("Could convert") {
                    Ok(HogLiteral::Null.into())
                } else {
                    panic!("Assertion failed")
                }
            }),
        ),
    ]
    .into_iter()
    .map(|(name, func)| (name.to_string(), func))
    .collect()
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
        },
        "inputs": {
            "propertiesToHash": "email,phone,name",
            "hashDistinctId": true,
            "salt": "my-secret-salt",
        }
    })
}

#[test]
pub fn test_vm() {
    let programs = load_test_programs();
    for program in programs {
        let (name, code) = program;
        println!("Running: {name}");
        let parsed: Vec<Value> = serde_json::from_str(&code).unwrap();
        let program = Program::new(parsed).unwrap();
        let ctx = ExecutionContext::with_defaults(program)
            .with_ext_fns(stl_test_extensions())
            .with_globals(test_globals());
        let res = sync_execute(&ctx, false);
        println!("{res:?}");
        assert!(res.is_ok());
        assert!(matches!(res, Ok(Value::Bool(true))))
    }
}
