use std::collections::HashMap;

use hogvm::{stl::NativeFunction, values::HogLiteral, vm::sync_execute};
use serde_json::Value;

const fn stl_test_extensions() -> &'static [(&'static str, NativeFunction)] {
    &[("print", |_, args| {
        println!("{:?}", args);
        Ok(HogLiteral::Null.into())
    })]
}

fn to_extension(ext: &'static [(&'static str, NativeFunction)]) -> HashMap<String, NativeFunction> {
    ext.iter().map(|(a, b)| (a.to_string(), *b)).collect()
}

#[test]
pub fn test_vm() {
    let examples = include_str!("../tests/static/bytecode_examples.jsonl");
    for (index, example) in examples.lines().enumerate() {
        let extensions = to_extension(stl_test_extensions());
        println!("Executing example {}: {}", index + 1, example);
        let bytecode: Vec<Value> = serde_json::from_str(example).unwrap();
        let res = sync_execute(&bytecode, 10000, extensions, true);
        println!("{:?}", res);
        if let Err(res) = res {
            println!("Failed at operation {:?}", bytecode.get(res.ip));
            panic!("Example {} failed: {:?}", index + 1, res);
        }
    }
}
