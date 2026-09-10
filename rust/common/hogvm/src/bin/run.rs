//! Minimal HogVM bytecode runner. Emits the `{"result", "error"}` JSON shape that the Python
//! (`common/hogvm/python/execute.py`) and Node runners also emit, so output can be diffed across runtimes.

use hogvm::{sync_execute, ExecutionContext, Program};
use serde_json::{json, Value};

pub fn main() {
    // nosemgrep: rust.lang.security.args.args
    let mut args = std::env::args().skip(1);
    let bytecode_path = args
        .next()
        .expect("Usage: run <bytecode.hoge> [globals.json]");
    let globals_path = args.next();

    let bytecode = read_json_array(&bytecode_path);
    let globals = globals_path
        .map(|path| read_json(&path))
        .unwrap_or_else(|| json!({}));

    let output = match execute(bytecode, globals) {
        Ok(result) => json!({ "result": result, "error": Value::Null }),
        Err(message) => json!({ "result": Value::Null, "error": message }),
    };
    println!("{output}");
}

/// Surface construction and execution failures as the `error` string — a malformed program is a
/// divergence to observe, not a crash.
fn execute(bytecode: Vec<Value>, globals: Value) -> Result<Value, String> {
    let program = Program::new(bytecode).map_err(|e| e.to_string())?;
    let context = ExecutionContext::with_defaults(program).with_globals(globals);
    sync_execute(&context, false).map_err(|failure| failure.error.to_string())
}

fn read_json_array(path: &str) -> Vec<Value> {
    let data = std::fs::read_to_string(path)
        .unwrap_or_else(|e| panic!("Failed to read bytecode file {path}: {e}"));
    serde_json::from_str(&data)
        .unwrap_or_else(|e| panic!("Failed to parse {path} as a JSON bytecode array: {e}"))
}

fn read_json(path: &str) -> Value {
    let data = std::fs::read_to_string(path)
        .unwrap_or_else(|e| panic!("Failed to read globals file {path}: {e}"));
    serde_json::from_str(&data).unwrap_or_else(|e| panic!("Failed to parse {path} as JSON: {e}"))
}
