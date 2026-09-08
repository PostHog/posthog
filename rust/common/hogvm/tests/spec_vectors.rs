//! Cross-language spec conformance — every vector in `common/hogvm/spec/vectors/` whose
//! `implementations` include rust must produce the exact expected result or error message this VM
//! shares with the Python and TypeScript reference VMs.
//!
//! The vectors live outside this crate; point the harness at the spec dir with
//! `HOGVM_SPEC_DIR=/abs/path/to/common/hogvm/spec`, or it walks up from the manifest dir.

use std::path::PathBuf;

use hogvm::{sync_execute, ExecutionContext, Program};
use serde_json::Value;

#[derive(serde::Deserialize)]
struct VectorFile {
    cases: Vec<SpecVector>,
}

#[derive(serde::Deserialize)]
struct SpecVector {
    name: String,
    implementations: Vec<String>,
    bytecode: Vec<Value>,
    expect: Expectation,
}

#[derive(serde::Deserialize)]
struct Expectation {
    error: Option<String>,
    result: Option<Value>,
}

fn spec_dir() -> Option<PathBuf> {
    if let Ok(dir) = std::env::var("HOGVM_SPEC_DIR") {
        let p = PathBuf::from(dir);
        return p.is_dir().then_some(p);
    }
    let mut cur = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    loop {
        let candidate = cur.join("common/hogvm/spec");
        if candidate.is_dir() {
            return Some(candidate);
        }
        if !cur.pop() {
            return None;
        }
    }
}

fn run_vector(bytecode: Vec<Value>) -> Result<Value, String> {
    let program = Program::new(bytecode).map_err(|e| e.to_string())?;
    let ctx = ExecutionContext::with_defaults(program).with_coercing_comparisons();
    sync_execute(&ctx, false).map_err(|failure| failure.error.to_string())
}

#[test]
fn spec_vectors() {
    let Some(spec) = spec_dir() else {
        panic!("Could not locate common/hogvm/spec — set HOGVM_SPEC_DIR");
    };
    let vectors_dir = spec.join("vectors");

    let mut files: Vec<PathBuf> = std::fs::read_dir(&vectors_dir)
        .expect("read vectors dir")
        .filter_map(|e| e.ok())
        .map(|e| e.path())
        .filter(|p| p.extension().is_some_and(|ext| ext == "json"))
        .collect();
    files.sort();
    assert!(!files.is_empty(), "no vector files in {vectors_dir:?}");

    let mut failures: Vec<String> = Vec::new();
    let mut total = 0usize;

    for file in files {
        let raw = std::fs::read_to_string(&file).expect("read vector file");
        let parsed: VectorFile = serde_json::from_str(&raw).expect("parse vector file");
        for case in parsed.cases {
            if !case.implementations.iter().any(|i| i == "rust") {
                continue;
            }
            total += 1;
            let outcome = run_vector(case.bytecode);
            match (&case.expect.error, &case.expect.result) {
                (Some(expected_error), _) => match outcome {
                    Ok(value) => failures.push(format!(
                        "{}: expected error {expected_error:?}, got result {value}",
                        case.name
                    )),
                    Err(actual) if &actual != expected_error => failures.push(format!(
                        "{}: expected error {expected_error:?}, got error {actual:?}",
                        case.name
                    )),
                    Err(_) => {}
                },
                (None, Some(expected)) => match outcome {
                    Ok(value) if &value != expected => failures.push(format!(
                        "{}: expected result {expected}, got {value}",
                        case.name
                    )),
                    Err(actual) => failures.push(format!(
                        "{}: expected result {expected}, got error {actual:?}",
                        case.name
                    )),
                    Ok(_) => {}
                },
                (None, None) => failures.push(format!("{}: vector has no expectation", case.name)),
            }
        }
    }

    assert!(total > 0, "no rust-applicable vectors found");
    assert!(
        failures.is_empty(),
        "{} of {} spec vectors diverged:\n  {}",
        failures.len(),
        total,
        failures.join("\n  ")
    );
}
