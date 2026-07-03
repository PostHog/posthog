//! Per-STL parity test — every STL function gets a focused case checked against the Node/
//! Python reference VM.
//!
//! The fixture `tests/static/stl_oracle.jsonl` holds one case per line: the `print(fn(args))`
//! bytecode and the output the *reference* VM produced. Here we replay that exact bytecode
//! through the Rust VM and assert it matches. "exact" cases must match byte-for-byte; "smoke"
//! cases (non-deterministic functions like `now()`) only have to run without error.
//!
//! The fixture is committed reference output (generated from the Node/Python VMs), so this runs
//! without a live reference VM.

use std::{
    collections::BTreeSet,
    sync::{Arc, Mutex},
};

use hogvm::{
    native_func, print_hog_string_output, sync_execute, ExecutionContext, HogLiteral, Program,
};
use serde_json::Value;

#[derive(serde::Deserialize)]
struct Entry {
    #[serde(rename = "fn")]
    fn_: String,
    label: String,
    #[serde(rename = "match")]
    match_mode: String,
    bytecode: Vec<Value>,
    expected: String,
}

fn run_bytecode(bytecode: Vec<Value>) -> Result<String, String> {
    let program = Program::new(bytecode).map_err(|e| format!("{e:?}"))?;
    // Arc<Mutex> rather than Rc<RefCell> because NativeFunction requires Send + Sync.
    let captured = Arc::new(Mutex::new(String::new()));
    let sink = captured.clone();
    let print_fn = native_func(move |vm, args| {
        let mut line = String::new();
        for (i, arg) in args.iter().enumerate() {
            if i > 0 {
                line.push(' ');
            }
            line.push_str(&print_hog_string_output(&vm.heap, arg)?);
        }
        line.push('\n');
        sink.lock().unwrap().push_str(&line);
        Ok(HogLiteral::Null.into())
    });
    // Match reference semantics: the reference VMs always coerce comparison operands.
    let ctx = ExecutionContext::with_defaults(program)
        .with_coercing_comparisons()
        .with_ext_fn("print".to_string(), print_fn);
    match sync_execute(&ctx, false) {
        Ok(_) => Ok(captured.lock().unwrap().trim_end_matches('\n').to_string()),
        Err(f) => Err(format!("{}", f.error)),
    }
}

fn load_oracle() -> Vec<Entry> {
    let path = concat!(env!("CARGO_MANIFEST_DIR"), "/tests/static/stl_oracle.jsonl");
    let raw = std::fs::read_to_string(path).unwrap_or_else(|e| panic!("read {path}: {e}"));
    raw.lines()
        .filter(|l| !l.trim().is_empty())
        .map(|l| serde_json::from_str(l).unwrap_or_else(|e| panic!("bad oracle line: {e}\n{l}")))
        .collect()
}

#[test]
fn stl_parity() {
    let entries = load_oracle();

    let mut pass = 0usize;
    let mut failed: Vec<(String, String)> = Vec::new(); // (label, detail)
    let mut failing_fns: BTreeSet<String> = BTreeSet::new();

    for e in &entries {
        let expected = e.expected.trim_end_matches('\n');
        match run_bytecode(e.bytecode.clone()) {
            Ok(_) if e.match_mode == "smoke" => {
                // smoke: ran without error
                pass += 1;
            }
            Ok(actual) if actual == expected => pass += 1,
            Ok(actual) => {
                failed.push((
                    e.label.clone(),
                    format!("node={expected:?} rust={actual:?}"),
                ));
                failing_fns.insert(e.fn_.clone());
            }
            Err(err) => {
                failed.push((e.label.clone(), format!("ERROR {err}")));
                failing_fns.insert(e.fn_.clone());
            }
        }
    }

    let total = entries.len();
    println!("\n============ HogVM per-STL parity ============");
    println!("cases: {total} | PASS {pass} | FAIL {}", failed.len());
    println!("STL functions with a failing case: {}", failing_fns.len());
    if !failed.is_empty() {
        println!("\n-- FAIL --");
        for (label, detail) in &failed {
            println!("  {label}: {detail}");
        }
        println!(
            "\n-- failing functions --\n  {}",
            failing_fns.iter().cloned().collect::<Vec<_>>().join(", ")
        );
    }
    println!("==============================================\n");

    // Regression gate: every failure must be a known, accepted divergence — a new one is a parity
    // regression. `toUnixTimestamp#0` is a reference float-formatting artifact (the oracle prints
    // "1609504496.0"; the Rust VM prints the integer) and is the sole tolerated case.
    const KNOWN_DIVERGENCES: &[&str] = &["toUnixTimestamp#0"];
    let unexpected: Vec<&String> = failed
        .iter()
        .map(|(label, _)| label)
        .filter(|label| !KNOWN_DIVERGENCES.contains(&label.as_str()))
        .collect();

    assert!(total > 0, "no STL cases in fixture");
    assert!(
        unexpected.is_empty(),
        "unexpected STL parity failures (not in the known-divergence allowlist): {unexpected:?}"
    );
}
