//! Pins the reason the analysis refuses a few natives outright: a caller supplying a claimed read
//! path from re-serialized JSON hands the VM a number of the other variant.
//!
//! The seeder's projected scan has ClickHouse rebuild a blob from the keys a chunk reads, and that
//! rebuild re-prints every number it copies, so a `100.0` token arrives as `100`. Most of the VM
//! cannot see the difference. The tests below run both spellings through the real evaluator and
//! sort the natives by whether it can: the ones that answer differently must widen the condition to
//! every column, and the ones that do not must stay narrow, because widening them would give back
//! the projection on ordinary conditions.
//!
//! Written as evaluations rather than as assertions about the STL, so a native that starts or stops
//! reading a number's spelling is caught here rather than in a list nobody re-reads.

use cohort_core::hogvm::analysis::{analyze_condition, FullColumnsReason, Projection};
use cohort_core::{evaluate_detailed, EvalOutcome};
use serde_json::{json, Value};

/// `<native>(properties.n) == <expected>`, in the shape the cohort compiler emits: the operands are
/// pushed before the comparison, and a global chain is pushed leaf first.
fn compare_native_over_property(native: &str, expected: &str) -> Vec<Value> {
    vec![
        json!("_H"),
        json!(1),
        json!(32),
        json!(expected),
        json!(32),
        json!("n"),
        json!(32),
        json!("properties"),
        json!(1),
        json!(2),
        json!(2),
        json!(native),
        json!(1),
        json!(11),
        json!(38),
    ]
}

/// The two spellings of one hundred: what the event carries, and what a rebuilt blob returns.
fn both_spellings() -> [Value; 2] {
    [
        json!({ "properties": { "n": 100.0 } }),
        json!({ "properties": { "n": 100 } }),
    ]
}

fn verdict(bytecode: &[Value], globals: Value) -> bool {
    match evaluate_detailed(bytecode, globals) {
        EvalOutcome::Matched(matched) => matched,
        other => panic!("the probe program did not evaluate: {other:?}"),
    }
}

/// The natives on the refusal list really do read the spelling. Without this, the list reads as
/// caution rather than as a measurement, and the next person to widen it has nothing to check
/// against.
#[test]
fn a_refused_native_answers_differently_for_the_two_spellings() {
    for (native, expected) in [("typeof", "float"), ("jsonStringify", "100.0")] {
        let bytecode = compare_native_over_property(native, expected);
        let [as_written, as_rebuilt] = both_spellings();
        assert!(
            verdict(&bytecode, as_written),
            "{native} did not match the float spelling, so the probe proves nothing"
        );
        assert!(
            !verdict(&bytecode, as_rebuilt),
            "{native} answered the same for both spellings and no longer needs refusing"
        );
    }
}

/// The same probe over the natives and operators the cohort UI actually emits. These stay
/// projectable, and this is what says the refusal above is narrow rather than a blanket ban on
/// calls: `toString` prints both spellings as `100`, and equality unifies the variants.
#[test]
fn an_ordinary_condition_reads_the_two_spellings_the_same_way() {
    let bare_equality = vec![
        json!("_H"),
        json!(1),
        json!(33),
        json!(100),
        json!(32),
        json!("n"),
        json!(32),
        json!("properties"),
        json!(1),
        json!(2),
        json!(11),
        json!(38),
    ];
    for bytecode in [
        compare_native_over_property("toString", "100"),
        bare_equality,
    ] {
        let [as_written, as_rebuilt] = both_spellings();
        assert!(verdict(&bytecode, as_written), "{bytecode:?}");
        assert!(verdict(&bytecode, as_rebuilt), "{bytecode:?}");
    }
}

/// The analysis has to act on the split above: the programs that diverge take every column, and the
/// ones that do not keep their narrow read set.
#[test]
fn the_analysis_widens_exactly_the_conditions_that_diverge() {
    for native in ["typeof", "jsonStringify"] {
        assert_eq!(
            analyze_condition(&compare_native_over_property(native, "x")).projection,
            Projection::FullColumns(FullColumnsReason::RepresentationSensitiveCall),
            "{native} still projects, so a rebuilt blob would reach it"
        );
    }
    let Projection::Reads(paths) =
        analyze_condition(&compare_native_over_property("toString", "100")).projection
    else {
        panic!("an ordinary native call must keep its read set");
    };
    assert_eq!(
        paths.iter().map(|path| path.render()).collect::<Vec<_>>(),
        ["properties.n"]
    );
}
