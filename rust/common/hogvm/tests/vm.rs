use std::collections::HashMap;

use hogvm::{stl::NativeFunction, values::HogLiteral, vm::sync_execute};
use serde_json::Value;

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

#[test]
pub fn test_vm() {
    let programs = load_test_programs();
    for program in programs {
        let (name, code) = program;
        println!("Running: {}", name);
        let parsed: Vec<Value> = serde_json::from_str(&code).unwrap();
        let res = sync_execute(&parsed, 10000, to_extension(stl_test_extensions()), false);
        println!("{:?}", res);
        assert!(res.is_ok());
        assert!(matches!(res, Ok(HogLiteral::Boolean(true))))
    }
}
