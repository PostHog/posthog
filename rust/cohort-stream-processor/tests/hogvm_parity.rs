//! Cross-runtime HogVM parity goldens (PR 1.4, TDD M8.b).
//!
//! Each fixture is `{name, bytecode, globals, expected_result}`, where `expected_result` is the
//! value the Python oracle (`common/hogvm/python/execute.py::execute_bytecode`) produced for that
//! `bytecode` + `globals` pair — the same compiler path (`create_bytecode(...,
//! null_safe_comparisons=True)`) the API uses at cohort save time. The test asserts the Rust
//! executor evaluates each one to the same boolean, proving the two runtimes agree on the
//! supported cohort bytecode surface (event/property comparisons + the `isNull` null-safe wrapper).
//!
//! Fixtures are read from this crate's `tests/fixtures/hogvm_parity/` and, when present, the shared
//! M8.b corpus at `common/hogvm/__tests__/cohort_bytecode/` — the latter is auto-included but
//! optional, so this PR's mergeability does not depend on it.

use std::fs;
use std::path::{Path, PathBuf};

use cohort_stream_processor::hogvm::{evaluate_detailed, EvalOutcome};
use serde_json::Value;

/// Read every `*.json` fixture in `dir`. A missing directory yields no fixtures (the optional
/// shared corpus); any other read/parse failure panics with the offending path.
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
    // Deterministic order so a failure always points at the same fixture across runs.
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
    // Guard against an empty run (e.g. fixtures not committed) silently "passing".
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
        // Coerce the expected value exactly as the executor does (`as_bool().unwrap_or(false)`,
        // mirroring Node's `?? false`), so raw-valued corpus fixtures compare apples-to-apples.
        let expected = fixture["expected_result"].as_bool().unwrap_or(false);

        let actual = match evaluate_detailed(bytecode, globals) {
            EvalOutcome::Matched(matched) => matched,
            // A representative fixture should never hit these; surface it loudly if it does
            // (e.g. an unsupported native sneaking into the shared corpus).
            other => panic!("fixture `{name}` ({path:?}) did not evaluate cleanly: {other:?}"),
        };

        assert_eq!(
            actual, expected,
            "parity mismatch for fixture `{name}` ({path:?}): rust={actual}, oracle={expected}",
        );
    }
}
