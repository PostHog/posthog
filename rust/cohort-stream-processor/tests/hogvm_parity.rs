//! HogVM regression goldens for the supported cohort bytecode surface. Each fixture's
//! `expected_result` is a committed oracle snapshot — the value the Python
//! `common/hogvm/python/execute.py::execute_bytecode` runtime produced when the fixture was
//! authored — and the test asserts the Rust executor still agrees with that snapshot. This guards
//! Rust against regression; it does NOT re-run Python/Node in CI, so on its own it is not a live
//! three-way parity proof (a mis-transcribed `expected_result` would enshrine a wrong answer). The
//! optional shared corpus (`../common/hogvm/__tests__/cohort_bytecode`) is not committed yet, so
//! today only the in-crate fixtures run.
//!
//! Provenance caveat: the temporal fixtures (`toDateTime`/`toDate` ordering) are a Rust-vs-ClickHouse
//! oracle, NOT a Python one — the reference Python/TS VMs can't order Hog temporals (they return
//! `false`), so their `expected_result` is the ClickHouse/instant-ordering answer the Rust VM
//! deliberately matches; see `rust/common/hogvm/tests/datetime.rs`.

use std::fs;
use std::path::{Path, PathBuf};

use cohort_stream_processor::hogvm::{evaluate_detailed, EvalOutcome};
use serde_json::Value;

/// A missing directory yields no fixtures (the optional shared corpus); any other read/parse
/// failure panics with the offending path.
fn fixtures_in(dir: &Path) -> Vec<(PathBuf, Value)> {
    let Ok(entries) = fs::read_dir(dir) else {
        return Vec::new();
    };
    let mut fixtures: Vec<(PathBuf, Value)> = entries
        .map(|entry| entry.expect("read dir entry").path())
        .filter(|path| path.extension().and_then(|ext| ext.to_str()) == Some("json"))
        .map(|path| {
            let data = fs::read_to_string(&path).unwrap_or_else(|e| panic!("read {path:?}: {e}"));
            let value =
                serde_json::from_str(&data).unwrap_or_else(|e| panic!("parse {path:?}: {e}"));
            (path, value)
        })
        .collect();
    // Deterministic order so a failure points at the same fixture across runs.
    fixtures.sort_by(|(a, _), (b, _)| a.cmp(b));
    fixtures
}

fn in_crate_dir() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/hogvm_parity")
}

fn all_fixtures() -> Vec<(PathBuf, Value)> {
    let mut fixtures = fixtures_in(&in_crate_dir());
    let corpus =
        Path::new(env!("CARGO_MANIFEST_DIR")).join("../common/hogvm/__tests__/cohort_bytecode");
    fixtures.extend(fixtures_in(&corpus));
    fixtures
}

#[test]
fn in_crate_fixtures_are_present() {
    // Guard against an empty run (fixtures not committed) silently passing.
    assert!(
        !fixtures_in(&in_crate_dir()).is_empty(),
        "no in-crate parity fixtures in {:?}",
        in_crate_dir()
    );
}

#[test]
fn rust_executor_matches_python_oracle() {
    for (path, fixture) in all_fixtures() {
        let name = fixture["name"].as_str().unwrap_or("<unnamed>");
        let bytecode = fixture["bytecode"]
            .as_array()
            .unwrap_or_else(|| panic!("fixture {path:?} `bytecode` must be an array"));
        let globals = fixture["globals"].clone();
        // Coerce expected as the executor does (`unwrap_or(false)`, mirroring Node's `?? false`).
        let expected = fixture["expected_result"].as_bool().unwrap_or(false);

        let actual = match evaluate_detailed(bytecode, globals) {
            EvalOutcome::Matched(matched) => matched,
            // An unsupported native sneaking into the corpus surfaces here rather than silently.
            other => panic!("fixture `{name}` ({path:?}) did not evaluate cleanly: {other:?}"),
        };

        assert_eq!(
            actual, expected,
            "parity mismatch for fixture `{name}` ({path:?}): rust={actual}, oracle={expected}",
        );
    }
}
