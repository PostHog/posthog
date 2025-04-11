use hogvm::{stl::NativeFunction, values::HogLiteral, vm::sync_execute};
use serde_json::Value as JsonValue;
use std::{collections::HashMap, io::Read};

const fn stl_test_extensions() -> &'static [(&'static str, NativeFunction)] {
    &[("print", |_, args| {
        println!("{:?}", args);
        Ok(HogLiteral::Null.into())
    })]
}

fn to_extension(ext: &'static [(&'static str, NativeFunction)]) -> HashMap<String, NativeFunction> {
    ext.iter().map(|(a, b)| (a.to_string(), *b)).collect()
}

pub fn main() {
    // Collect stdin to a buffer
    let mut buffer = String::new();
    std::io::stdin().read_to_string(&mut buffer).unwrap();

    // Do something with buffer
    let parsed: Vec<JsonValue> = serde_json::from_str(&buffer).unwrap();
    let extensions = to_extension(stl_test_extensions());
    let res = sync_execute(&parsed, 10000, extensions, true);
    println!("{:?}", res);
    if let Err(res) = res {
        println!("Failed at operation {:?}", parsed.get(res.ip));
    }
}
