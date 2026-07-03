//! HogVM regression goldens for the supported cohort bytecode surface. Each fixture's
//! `expected_result` is a committed oracle snapshot from the Python
//! `common/hogvm/python/execute.py::execute_bytecode` runtime. The test asserts the Rust executor
//! agrees; it does NOT re-run Python/Node in CI, so a mis-transcribed `expected_result` would
//! enshrine a wrong answer. An optional shared corpus at
//! `../common/hogvm/__tests__/cohort_bytecode` is also loaded when present.
//!
//! Provenance note: the temporal fixtures (`toDateTime`/`toDate` ordering) are a Rust-vs-ClickHouse
//! oracle, not a Python one — the reference Python/TS VMs return `false` for Hog temporal ordering,
//! so `expected_result` reflects the ClickHouse/instant-ordering answer the Rust VM deliberately
//! matches; see `rust/common/hogvm/tests/datetime.rs`.

use std::fs;
use std::path::{Path, PathBuf};

use cohort_stream_processor::hogvm::{evaluate_detailed, EvalOutcome};
use serde_json::Value;

/// HogVM `RETURN`. Fixtures store compiled bytecode without it; append it so the parity oracle runs
/// the same RETURN-terminated shape the hot path does.
const OP_RETURN: i64 = 38;

/// A missing directory yields no fixtures (optional corpus); any other read/parse failure panics.
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
    fixtures.sort_by(|(a, _), (b, _)| a.cmp(b)); // deterministic order for reproducible failures
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
    // Guard against an empty in-crate fixture directory silently passing.
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
        let mut bytecode = bytecode.clone();
        bytecode.push(Value::from(OP_RETURN));
        let globals = fixture["globals"].clone();
        // `unwrap_or(false)` mirrors the Node `?? false` coercion.
        let expected = fixture["expected_result"].as_bool().unwrap_or(false);

        let actual = match evaluate_detailed(&bytecode, globals) {
            EvalOutcome::Matched(matched) => matched,
            other => panic!("fixture `{name}` ({path:?}) did not evaluate cleanly: {other:?}"),
        };

        assert_eq!(
            actual, expected,
            "parity mismatch for fixture `{name}` ({path:?}): rust={actual}, oracle={expected}",
        );
    }
}
