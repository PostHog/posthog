//! Runs the shared HogVM bytecode corpus through the static analysis, as a totality check.
//!
//! The corpus is general Hog — closures, locals, exception handling — not cohort filters, and none
//! of its programs touch the globals dict. So this asserts one thing: that the analysis terminates
//! with an answer on arbitrary real bytecode. A panic or a hang is what would break the seeder,
//! because the analysis runs on every condition at run-validation time.
//!
//! It is deliberately not a coverage corpus, and cannot be read as one. Whether the analysis names
//! the right globals for a *cohort* condition is `analysis_parity_corpus.rs`'s question, over
//! compiled cohort bytecode with a recorded oracle verdict.

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
/// The corpus is general Hog, so its programs split two ways. Most use closures or exception
/// handling, which the model refuses, and land on full columns. The rest are string-function
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
