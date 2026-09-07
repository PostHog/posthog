//! Runs the cohort parity fixtures through the static analysis.
//!
//! These are real compiled cohort bytecode: each fixture carries the program, the globals it runs
//! against, and the verdict the Python oracle reached. That makes them the only corpus here that
//! can answer the question the analysis exists to answer — whether the read set it claims is enough
//! to decide a condition production actually compiles.
//!
//! The check is the same equivalence the proptest gate asserts, run against compiled rather than
//! synthesized programs: prune the globals down to exactly the claimed paths, evaluate again, and
//! require the same verdict the oracle recorded. A read set that were ever short would decide the
//! wrong way here.

use std::collections::BTreeSet;
use std::fs;
use std::path::{Path, PathBuf};

use cohort_core::hogvm::analysis::{analyze_condition, Projection, ReadPath};
use cohort_core::{
    build_behavioral_globals, classify_vm_error, evaluate_detailed, CohortStreamEvent, EvalOutcome,
    VmErrorClass,
};
use serde_json::{json, Map, Value};

/// The catalog loader appends a `RETURN` to every stored program, and the parity runner does the
/// same, so the analysis has to see the bytecode in that form and not the raw fixture.
const OP_RETURN: i64 = 38;

/// The fixture shapes whose bytecode the compiler lowers through jumps: `null_safe_comparisons`
/// rewrites `>=` into an `if`, and a date comparison goes the same way. They are named here because
/// they are the reason the interpreter follows branches at all — an analysis that refused them
/// would report almost every real date and numeric condition as unreadable, and the census built on
/// it would answer the wrong question.
const BRANCH_LOWERED_FIXTURES: [&str; 5] = [
    "isnull_numeric_gte_below",
    "isnull_numeric_gte_match",
    "isnull_numeric_gte_null",
    "to_datetime_eq_bare_field",
    "to_datetime_ordering_lt",
];

struct Fixture {
    name: String,
    bytecode: Vec<Value>,
    globals: Value,
    expected: bool,
}

fn fixtures() -> Vec<Fixture> {
    let dir = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../cohort-stream-processor/tests/fixtures/hogvm_parity");
    let mut paths = fs::read_dir(&dir)
        .unwrap_or_else(|error| panic!("the parity fixtures are not readable at {dir:?}: {error}"))
        .map(|entry| entry.expect("a directory entry is readable").path())
        .filter(|path| path.extension().is_some_and(|ext| ext == "json"))
        .collect::<Vec<PathBuf>>();
    paths.sort();

    paths
        .iter()
        .map(|path| {
            let text = fs::read_to_string(path).expect("a fixture is readable");
            let fixture: Value = serde_json::from_str(&text)
                .unwrap_or_else(|error| panic!("fixture {path:?} is not JSON: {error}"));
            let mut bytecode = fixture["bytecode"]
                .as_array()
                .unwrap_or_else(|| panic!("fixture {path:?} has no bytecode array"))
                .clone();
            bytecode.push(Value::from(OP_RETURN));
            Fixture {
                name: fixture["name"].as_str().unwrap_or("<unnamed>").to_owned(),
                bytecode,
                globals: fixture["globals"].clone(),
                // `unwrap_or(false)` mirrors the parity runner's coercion.
                expected: fixture["expected_result"].as_bool().unwrap_or(false),
            }
        })
        .collect()
}

/// The globals a scan built from `paths` would produce: every value the analysis did not claim is
/// absent, exactly as a narrower `SELECT` would leave it.
///
/// The objects along a claimed path are created whether or not the leaf is there. That is what a
/// narrower query actually returns — the `properties` column still arrives, holding fewer keys —
/// and the distinction is load-bearing, because the VM reads a missing key inside an object as null
/// but raises on a missing object.
fn project_globals(globals: &Value, paths: &BTreeSet<ReadPath>) -> Value {
    let mut projected = Map::new();
    for path in paths {
        let mut keys = vec![path.root.as_str().to_owned()];
        keys.extend(path.segments.iter().cloned());
        graft(&mut projected, &keys, lookup(globals, &keys));
    }
    Value::Object(projected)
}

fn lookup<'a>(globals: &'a Value, keys: &[String]) -> Option<&'a Value> {
    keys.iter()
        .try_fold(globals, |value, key| value.as_object()?.get(key))
}

fn graft(into: &mut Map<String, Value>, keys: &[String], value: Option<&Value>) {
    let Some((key, rest)) = keys.split_first() else {
        return;
    };
    if rest.is_empty() {
        if let Some(value) = value {
            into.insert(key.clone(), value.clone());
        }
        return;
    }
    let child = into
        .entry(key.clone())
        .or_insert_with(|| Value::Object(Map::new()));
    // A path claimed both bare and nested would collide here. The analysis never emits a bare
    // object root as a read, so the nested form is the only one that reaches this.
    if let Some(object) = child.as_object_mut() {
        graft(object, rest, value);
    }
}

/// Every path the projection kept has to lie on a claimed one: under it, where a claim names a
/// subtree, or on the way to it, for the objects [`graft`] creates along a claimed path.
///
/// Without this the corpus cannot fail on a leak. Each fixture's property bag holds at most the one
/// key its condition reads, so a `project_globals` that returned whole objects instead of the
/// claimed keys would decide every fixture the same way and pass — leaving the test asserting that
/// the full globals decide the condition, which is trivially true. The generated corpus is
/// projected key by key and so cannot leak by construction; this is the same guarantee for the
/// programs that came out of the real compiler.
fn assert_nothing_outside_the_claimed_paths(
    projected: &Value,
    paths: &BTreeSet<ReadPath>,
    name: &str,
) {
    let claimed: Vec<Vec<String>> = paths
        .iter()
        .map(|path| {
            let mut keys = vec![path.root.as_str().to_owned()];
            keys.extend(path.segments.iter().cloned());
            keys
        })
        .collect();
    assert_kept_path_is_claimed(projected, &mut Vec::new(), &claimed, name);
}

fn assert_kept_path_is_claimed(
    value: &Value,
    at: &mut Vec<String>,
    claimed: &[Vec<String>],
    name: &str,
) {
    if let Value::Object(fields) = value {
        if !fields.is_empty() {
            for (key, child) in fields {
                at.push(key.clone());
                assert_kept_path_is_claimed(child, at, claimed, name);
                at.pop();
            }
            return;
        }
    }
    // An empty path is the whole projection being empty, which cannot carry anything unclaimed.
    assert!(
        at.is_empty()
            || claimed
                .iter()
                .any(|path| path.starts_with(at) || at.starts_with(path)),
        "fixture `{name}` kept {at:?}, which no claimed path covers"
    );
}

fn matched(bytecode: &[Value], globals: Value, name: &str) -> bool {
    match evaluate_detailed(bytecode, globals) {
        EvalOutcome::Matched(matched) => matched,
        other => panic!("fixture `{name}` did not evaluate cleanly: {other:?}"),
    }
}

/// Every fixture analyzes, and where the analysis claims a read set, that set alone decides the
/// condition the same way the oracle did — with the projection holding nothing the analysis did not
/// claim, so the equivalence is about the claimed set rather than about the whole event.
#[test]
fn every_parity_fixture_decides_the_same_way_from_its_claimed_reads() {
    let fixtures = fixtures();
    assert!(
        fixtures.len() >= 10,
        "only {} parity fixtures; this test would stop covering the compiled shapes",
        fixtures.len()
    );
    for fixture in &fixtures {
        let full = matched(&fixture.bytecode, fixture.globals.clone(), &fixture.name);
        assert_eq!(
            full, fixture.expected,
            "fixture `{}` disagrees with its own oracle before any projection",
            fixture.name
        );
        let Projection::Reads(paths) = analyze_condition(&fixture.bytecode).projection else {
            continue;
        };
        let projected_globals = project_globals(&fixture.globals, &paths);
        assert_nothing_outside_the_claimed_paths(&projected_globals, &paths, &fixture.name);
        let projected = matched(&fixture.bytecode, projected_globals, &fixture.name);
        assert_eq!(
            projected,
            fixture.expected,
            "fixture `{}` claimed {:?} but decided differently once projected onto it",
            fixture.name,
            paths.iter().map(ReadPath::render).collect::<Vec<_>>()
        );
    }
}

/// The conditions the compiler lowers through jumps must narrow to a read set.
///
/// This is the regression that matters most: while the interpreter refused branches, every one of
/// these reported full columns, so a census over a real catalog would have counted the commonest
/// property-filtered conditions as unreadable and understated what a projection can do.
#[test]
fn the_branch_lowered_fixtures_narrow_to_a_read_set() {
    let fixtures = fixtures();
    for name in BRANCH_LOWERED_FIXTURES {
        let fixture = fixtures
            .iter()
            .find(|fixture| fixture.name == name)
            .unwrap_or_else(|| panic!("the `{name}` parity fixture is gone"));
        let projection = analyze_condition(&fixture.bytecode).projection;
        let Projection::Reads(paths) = projection else {
            panic!("`{name}` compiles through a jump and did not narrow: {projection:?}");
        };
        assert!(
            !paths.is_empty(),
            "`{name}` narrowed to an empty read set, which cannot be right for a property filter"
        );
    }
}

/// A production filter on `organization.properties.name`, where `organization` is a team-defined
/// group type. HogQL aliases such a name onto `group_0` when it prints SQL, but the bytecode
/// compiler emits the written chain, so the root reaches the VM and no globals dict carries it.
///
/// Not a `hogvm_parity` fixture: both runners of that directory panic on a non-`Matched` outcome,
/// and this program raises rather than returning a bool, so adding it there would break the
/// processor's parity suite.
///
/// The two halves together are the equivalence the fixtures assert for ordinary programs. The
/// analysis claims no reads, and the program decides the same way on the full globals as on the
/// empty projection those reads produce, because the absent root raises on both. What the condition
/// does is unchanged — it already collapses to `false` in production and counts an `unknown_ref`.
/// Only its classification moved.
#[test]
fn an_absent_group_type_root_claims_no_reads_and_raises_either_way() {
    // organization.properties.name == 'Example Org'
    let bytecode = vec![
        json!("_H"),
        json!(1),
        json!(32),
        json!("Example Org"),
        json!(32),
        json!("name"),
        json!(32),
        json!("properties"),
        json!(32),
        json!("organization"),
        json!(1),
        json!(3),
        json!(11),
        Value::from(OP_RETURN),
    ];

    let projection = analyze_condition(&bytecode).projection;
    let Projection::Reads(paths) = projection else {
        panic!("a root no globals dict carries should claim a read set: {projection:?}");
    };
    assert!(
        paths.is_empty(),
        "claimed {:?} for a root that reads no event data",
        paths.iter().map(ReadPath::render).collect::<Vec<_>>()
    );

    let full = build_behavioral_globals(&event()).expect("the event's payloads are valid JSON");
    let projected = project_globals(&full, &paths);
    assert_eq!(
        projected,
        Value::Object(Map::new()),
        "an empty read set has to prune the globals to nothing"
    );
    for (shape, globals) in [("full", full), ("projected", projected)] {
        match evaluate_detailed(&bytecode, globals) {
            EvalOutcome::VmError(error) => assert_eq!(
                classify_vm_error(&error),
                VmErrorClass::UnknownReference,
                "the {shape} globals raised something other than an unknown reference: {error:?}"
            ),
            other => panic!("the {shape} globals did not raise: {other:?}"),
        }
    }
}

fn event() -> CohortStreamEvent {
    CohortStreamEvent {
        team_id: 42,
        person_id: "p-123".to_string(),
        distinct_id: "d-1".to_string(),
        uuid: "01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee".to_string(),
        event: "$pageview".to_string(),
        timestamp: "2026-05-26 12:34:56.789000".to_string(),
        properties: Some(r#"{"$browser":"Chrome"}"#.to_string()),
        person_properties: Some(r#"{"email":"u@p.com"}"#.to_string()),
        elements_chain: None,
        source_offset: 0,
        source_partition: 0,
        redirected_from: None,
        redirect_hops: 0,
    }
}
