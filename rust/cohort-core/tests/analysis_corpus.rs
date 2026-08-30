//! Runs the shared HogVM bytecode corpus through the static analysis.
//!
//! The corpus is general Hog, not cohort filters, so almost every program is expected to fall back
//! to full columns. That is the point: this asserts totality and determinism, not coverage. A panic
//! or a hang on real bytecode is what would break the seeder, because the analysis runs on every
//! condition at run-validation time.

use cohort_core::hogvm::analysis::{analyze_condition, ConditionAnalysis, Projection, ReadPath};
use serde_json::Value;

const CORPUS: &str = include_str!("../../common/hogvm/tests/static/bytecode_examples.jsonl");

fn corpus() -> Vec<Vec<Value>> {
    CORPUS
        .lines()
        .filter(|line| !line.trim().is_empty())
        .map(|line| serde_json::from_str(line).expect("the shared corpus is valid JSON"))
        .collect()
}

#[test]
fn the_shared_corpus_analyzes_without_panicking() {
    let programs = corpus();
    assert!(
        programs.len() >= 30,
        "the corpus shrank to {} programs; this test would stop covering anything",
        programs.len()
    );
    for program in &programs {
        analyze_condition(program);
    }
}

#[test]
fn analyzing_the_same_program_twice_gives_the_same_answer() {
    for program in corpus() {
        assert_eq!(
            analyze_condition(&program),
            analyze_condition(&program),
            "analysis of {program:?} is not deterministic"
        );
    }
}

/// No corpus program names a global it reads.
///
/// The corpus is general Hog, so its programs split two ways. Most use locals, closures, or
/// branches, which the linear model refuses, and land on full columns. A few are string-function
/// demonstrations over literals with no `GET_GLOBAL` at all, and those correctly read nothing. What
/// no program in this corpus can legitimately produce is a read of a named global, because none of
/// them touch the globals dict. A change that started reporting one here would be inventing reads.
#[test]
fn no_general_hog_program_claims_to_read_a_named_global() {
    for program in corpus() {
        let ConditionAnalysis {
            projection: Projection::Reads(paths),
            ..
        } = analyze_condition(&program)
        else {
            continue;
        };
        assert!(
            paths.is_empty(),
            "a corpus program that reads no globals claimed {:?}",
            paths.iter().map(ReadPath::render).collect::<Vec<_>>()
        );
    }
}
