//! Correctness parity harness — the engine of the "HogVM in Rust" loop.
//!
//! For every program in the shared reference corpus (`common/hogvm/__tests__/*.hog`) it:
//!   1. loads the committed `.hoge` bytecode snapshot,
//!   2. runs it through this Rust VM with a `print` that formats values canonically,
//!   3. diffs the captured output against the committed Node oracle
//!      (`__snapshots__/<name>.stdout.nodejs`, falling back to `<name>.stdout`).
//!
//! Each program lands in one of three buckets: PASS (output matches Node), MISMATCH
//! (ran but diverged — a real parity bug), or ERROR (the VM bailed — usually an
//! unimplemented opcode or STL function). The aggregated ERROR/MISMATCH reasons ARE the
//! loop backlog: every distinct "Unknown function X" / "Not implemented: Y" is the next
//! thing to build.
//!
//! The corpus lives outside this crate, so point the harness at it with
//! `HOGVM_CORPUS_DIR=/abs/path/to/common/hogvm/__tests__`; otherwise it walks up from the
//! manifest dir looking for `common/hogvm/__tests__`.

use std::{
    collections::BTreeMap,
    path::PathBuf,
    sync::{Arc, Mutex},
};

use hogvm::{
    native_func, print_hog_string_output, sync_execute, ExecutionContext, HogLiteral, Program,
    VmError,
};
use serde_json::Value;

#[derive(Debug)]
enum Outcome {
    Pass,
    Mismatch {
        expected: String,
        actual: String,
    },
    Error {
        reason: String,
        capability: Option<String>,
    },
    Skipped(String),
}

fn corpus_dir() -> Option<PathBuf> {
    if let Ok(dir) = std::env::var("HOGVM_CORPUS_DIR") {
        let p = PathBuf::from(dir);
        return p.is_dir().then_some(p);
    }
    // Walk up from the crate manifest dir looking for common/hogvm/__tests__
    let mut cur = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    loop {
        let candidate = cur.join("common/hogvm/__tests__");
        if candidate.is_dir() {
            return Some(candidate);
        }
        if !cur.pop() {
            return None;
        }
    }
}

// Pull the missing-capability name out of the errors the loop cares about, so distinct
// gaps can be tallied across the whole corpus.
fn capability_of(err: &VmError) -> Option<String> {
    match err {
        VmError::UnknownFunction(name) => Some(format!("stl:{name}")),
        VmError::NotImplemented(what) => Some(format!("op/feature:{what}")),
        VmError::UnknownGlobal(_) => Some("global (test setup)".to_string()),
        _ => None,
    }
}

fn run_one(hoge_path: &PathBuf, oracle: &str) -> Outcome {
    let code = match std::fs::read_to_string(hoge_path) {
        Ok(c) => c,
        Err(e) => return Outcome::Skipped(format!("unreadable .hoge: {e}")),
    };
    let parsed: Vec<Value> = match serde_json::from_str(&code) {
        Ok(p) => p,
        Err(e) => return Outcome::Skipped(format!("bad .hoge json: {e}")),
    };
    let program = match Program::new(parsed) {
        Ok(p) => p,
        Err(e) => {
            return Outcome::Error {
                reason: format!("{e:?}"),
                capability: capability_of(&e),
            }
        }
    };

    // Capture print output the way `console.log(...args.map(printHogStringOutput))` does:
    // args space-separated, one newline per call.
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

    // The reference VM bounds execution by a 5s timeout, not a step count; use a generous step cap
    // so compute-heavy corpus programs (e.g. mandelbrot) can finish rather than tripping the default.
    // The reference VMs always coerce comparison operands (unifyComparisonTypes), so enable the
    // coercing path here to replicate reference semantics — this is the behavior we diff against.
    let ctx = ExecutionContext::with_defaults(program)
        .with_max_steps(50_000_000)
        .with_coercing_comparisons()
        .with_ext_fn("print".to_string(), print_fn);

    match sync_execute(&ctx, false) {
        Ok(_) => {
            let actual = captured.lock().unwrap().trim_end_matches('\n').to_string();
            let expected = oracle.trim_end_matches('\n').to_string();
            if actual == expected {
                Outcome::Pass
            } else {
                Outcome::Mismatch { expected, actual }
            }
        }
        Err(failure) => Outcome::Error {
            reason: format!("{}", failure.error),
            capability: capability_of(&failure.error),
        },
    }
}

#[test]
fn parity_report() {
    let Some(corpus) = corpus_dir() else {
        panic!("Could not locate common/hogvm/__tests__ — set HOGVM_CORPUS_DIR");
    };
    let snapshots = corpus.join("__snapshots__");

    let mut programs: Vec<String> = std::fs::read_dir(&corpus)
        .expect("read corpus dir")
        .filter_map(|e| e.ok())
        .filter_map(|e| e.file_name().to_str().map(str::to_string))
        .filter(|n| n.ends_with(".hog"))
        .map(|n| n.trim_end_matches(".hog").to_string())
        .collect();
    programs.sort();

    let mut pass = Vec::new();
    let mut mismatch = Vec::new();
    let mut errored = Vec::new();
    let mut skipped = Vec::new();
    // capability -> programs that need it
    let mut backlog: BTreeMap<String, Vec<String>> = BTreeMap::new();

    for name in &programs {
        let hoge = snapshots.join(format!("{name}.hoge"));
        if !hoge.is_file() {
            skipped.push((name.clone(), "no .hoge snapshot".to_string()));
            continue;
        }
        // Node is the oracle; prefer the node-specific snapshot when Node/Python diverge.
        let oracle_path = {
            let nodejs = snapshots.join(format!("{name}.stdout.nodejs"));
            if nodejs.is_file() {
                nodejs
            } else {
                snapshots.join(format!("{name}.stdout"))
            }
        };
        let Ok(oracle) = std::fs::read_to_string(&oracle_path) else {
            skipped.push((name.clone(), "no oracle stdout".to_string()));
            continue;
        };

        match run_one(&hoge, &oracle) {
            Outcome::Pass => pass.push(name.clone()),
            Outcome::Mismatch { expected, actual } => {
                mismatch.push((name.clone(), expected, actual))
            }
            Outcome::Error { reason, capability } => {
                if let Some(cap) = capability {
                    backlog.entry(cap).or_default().push(name.clone());
                }
                errored.push((name.clone(), reason));
            }
            Outcome::Skipped(why) => skipped.push((name.clone(), why)),
        }
    }

    let total = programs.len();
    println!("\n================ HogVM Rust↔Node parity report ================");
    println!(
        "corpus: {}\nprograms: {total} | PASS {} | MISMATCH {} | ERROR {} | SKIP {}",
        corpus.display(),
        pass.len(),
        mismatch.len(),
        errored.len(),
        skipped.len()
    );

    println!("\n-- PASS ({}) --", pass.len());
    println!("  {}", pass.join(", "));

    println!(
        "\n-- MISMATCH ({}) — ran but diverged from Node (parity bugs) --",
        mismatch.len()
    );
    for (name, expected, actual) in &mismatch {
        let (line_no, exp, act) = first_diff(expected, actual);
        println!("  {name} (first diff at line {line_no})\n      node: {exp}\n      rust: {act}");
    }

    println!(
        "\n-- ERROR ({}) — VM bailed (usually unimplemented) --",
        errored.len()
    );
    for (name, reason) in &errored {
        println!("  {name}: {reason}");
    }

    println!("\n-- BACKLOG (missing capabilities, by program count) --");
    let mut ranked: Vec<(&String, &Vec<String>)> = backlog.iter().collect();
    ranked.sort_by(|a, b| b.1.len().cmp(&a.1.len()).then(a.0.cmp(b.0)));
    for (cap, progs) in ranked {
        println!("  [{}] {}  ({})", progs.len(), cap, progs.join(", "));
    }

    if !skipped.is_empty() {
        println!("\n-- SKIPPED ({}) --", skipped.len());
        for (name, why) in &skipped {
            println!("  {name}: {why}");
        }
    }
    println!("===============================================================\n");

    // Regression gate: the Rust VM must match Node on every committed corpus program. The whole
    // corpus passes today (36/36), so any mismatch (ran but diverged) or error (VM bailed) is a
    // real parity regression and fails the test.
    assert!(total > 0, "no corpus programs found");
    assert!(
        mismatch.is_empty() && errored.is_empty(),
        "corpus parity regressed: {} mismatch(es), {} error(s) vs Node — see report above",
        mismatch.len(),
        errored.len()
    );
}

// Find the first line where expected and actual diverge, returning (1-based line, exp, act).
fn first_diff(expected: &str, actual: &str) -> (usize, String, String) {
    let mut exp_lines = expected.lines();
    let mut act_lines = actual.lines();
    let mut n = 0;
    loop {
        n += 1;
        match (exp_lines.next(), act_lines.next()) {
            (None, None) => return (n, "<eof>".to_string(), "<eof>".to_string()),
            (e, a) => {
                let e = e.unwrap_or("<eof>");
                let a = a.unwrap_or("<eof>");
                if e != a {
                    return (n, clip(e), clip(a));
                }
            }
        }
    }
}

fn clip(line: &str) -> String {
    let limit = 200;
    if line.chars().count() > limit {
        let truncated: String = line.chars().take(limit).collect();
        format!("{truncated}…")
    } else {
        line.to_string()
    }
}
