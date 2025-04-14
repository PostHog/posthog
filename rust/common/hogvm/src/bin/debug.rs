use hogvm::{stl::NativeFunction, values::HogLiteral, vm::sync_execute};
use serde_json::Value as JsonValue;
use std::{collections::HashMap, io::Read};

const fn stl_test_extensions() -> &'static [(&'static str, NativeFunction)] {
    &[("print", |_, args| {
        println!("--- PRINT: {:?}", args);
        Ok(HogLiteral::Null.into())
    })]
}

fn to_extension(ext: &'static [(&'static str, NativeFunction)]) -> HashMap<String, NativeFunction> {
    ext.iter().map(|(a, b)| (a.to_string(), *b)).collect()
}

const ITERATIONS: usize = 100_000;

pub fn main() {
    // Collect stdin to a buffer
    let mut buffer = String::new();
    std::io::stdin().read_to_string(&mut buffer).unwrap();

    // Do something with buffer
    let parsed: Vec<JsonValue> = serde_json::from_str(&buffer).unwrap();
    let start = std::time::Instant::now();
    let mut res = sync_execute(&parsed, 10000, to_extension(stl_test_extensions()), false);
    let mut i = 1;
    while i < ITERATIONS {
        res = sync_execute(&parsed, 10000, to_extension(stl_test_extensions()), false);
        if let Err(res) = &res {
            println!("Failed: {:?}", res);
            break;
        }
        i += 1;
    }
    let elapsed = start.elapsed();
    println!(
        "Execution time: {:?}, {} iterations, {} microseconds per iteration",
        elapsed,
        i,
        elapsed.as_micros() / i as u128
    );
    println!("Result: {:?}", res);
}
