use std::collections::HashMap;

use hogvm::{ExecutionContext, Program, StepOutcome};
use serde_json::Value;

// Invoked like (when inside the common/hogvm folder): cargo run --bin debug_rule path/to/input.json
pub fn main() {
    // Load the rows - expected to be in the format of a JSON array, the result of
    // `select * from posthog_errortrackingassignmentrules WHERE <blah> LIMIT 1`
    let input_file = std::env::args().nth(1).expect("No input file provided");
    let data = std::fs::read_to_string(input_file).unwrap();
    let mut json: Value = serde_json::from_str(&data).unwrap();

    // Grab the first row
    let json = json[0].take();

    // Grab the bytecode for the rule
    let rule_bytecode = json.get("bytecode").unwrap().as_str().unwrap();
    let rule_bytecode: Vec<Value> =
        serde_json::from_str(rule_bytecode).expect("Failed to convert bytecode to json");
    println!(
        "Bytecode:\n{}",
        rule_bytecode
            .iter()
            .enumerate()
            .fold(String::new(), |acc, (i, value)| format!(
                "{acc}({i}){value:?}\n"
            ))
    );

    // Grab the data we fed in to the invocation that caused the rule to be disabled
    let disabled_data = json.get("disabled_data").unwrap().as_str().unwrap();
    let disabled_data: Value =
        serde_json::from_str(disabled_data).expect("Failed to convert disabled_data to json");

    // Set up our globals
    let mut globals = HashMap::new();
    globals.insert("issue".to_string(), disabled_data.get("issue").unwrap());
    globals.insert(
        "properties".to_string(),
        disabled_data.get("props").unwrap(),
    );
    let globals: Value = serde_json::to_value(globals).unwrap();

    // Construct the rule program
    let program = Program::new(rule_bytecode.clone()).unwrap();
    let context = ExecutionContext::with_defaults(program).with_globals(globals);
    let mut vm = context.to_vm().unwrap();

    // Run the rule program
    let mut i = 0;
    while i < context.max_steps {
        let step_result = vm.step().unwrap();
        match step_result {
            StepOutcome::Finished(Value::Bool(b)) => {
                println!("OK: Rule finished with outcome: {b:?}");
                return;
            }
            StepOutcome::Finished(res) => {
                panic!("ERR: Rule finished with unexpected result: {res:?}");
            }
            StepOutcome::NativeCall(name, args) => context
                .execute_native_function_call(&mut vm, &name, args)
                .unwrap(),
            StepOutcome::Continue => {}
        }
        i += 1;
    }
    panic!("Rule did not finish within the maximum number of steps");
}
