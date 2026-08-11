//! Coverage for the `toDateTime`/`toDate` natives and Hog-temporal comparison. This VM orders
//! temporals by `dt` seconds to match ClickHouse, matching the Python/TS reference VMs; naive
//! strings parse as UTC, not the process-local timezone.

use chrono::{NaiveDate, TimeZone, Utc};
use hogvm::{sync_execute, ExecutionContext, Program};
use serde_json::{json, Value};

// Opcode numeric values (mirror common/hogvm/python/operation.py).
const OP_CALL_GLOBAL: i64 = 2;
const OP_EQ: i64 = 11;
const OP_NOT_EQ: i64 = 12;
const OP_GT: i64 = 13;
const OP_LT: i64 = 15;
const OP_STRING: i64 = 32;
const OP_RETURN: i64 = 38;

fn run(bytecode: Vec<Value>) -> Value {
    let program = Program::new(bytecode).expect("valid program");
    let ctx = ExecutionContext::with_defaults(program)
        .with_globals(json!({}))
        .with_coercing_comparisons();
    sync_execute(&ctx, false).expect("execution succeeds")
}

fn to_datetime(s: &str) -> Vec<Value> {
    vec![
        json!(OP_STRING),
        json!(s),
        json!(OP_CALL_GLOBAL),
        json!("toDateTime"),
        json!(1),
    ]
}

fn to_datetime_zoned(s: &str, zone: &str) -> Vec<Value> {
    vec![
        json!(OP_STRING),
        json!(s),
        json!(OP_STRING),
        json!(zone),
        json!(OP_CALL_GLOBAL),
        json!("toDateTime"),
        json!(2),
    ]
}

/// `left <op> right`. The compiler emits operands as `[right…, left…, op]`.
fn compare(left: &[Value], right: &[Value], op: i64) -> Vec<Value> {
    let mut bc = vec![json!("_H"), json!(1)];
    bc.extend_from_slice(right);
    bc.extend_from_slice(left);
    bc.push(json!(op));
    bc.push(json!(OP_RETURN));
    bc
}

fn returning(fragment: &[Value]) -> Vec<Value> {
    let mut bc = vec![json!("_H"), json!(1)];
    bc.extend_from_slice(fragment);
    bc.push(json!(OP_RETURN));
    bc
}

/// The shared date-like grammar. The canonical spec is above `parse_datetime_to_seconds` in
/// `src/stl.rs`; the same table is driven by `common/hogvm/python/test/test_date.py` and
/// `common/hogvm/typescript/src/__tests__/date.test.ts`. All three must agree — before this was
/// pinned, only 4 of these 22 inputs produced the same answer in all three VMs.
const ACCEPTED: [(&str, f64); 13] = [
    ("2024-01-01", 1704067200.0),
    ("2024-01-01T00:00:00Z", 1704067200.0),
    ("2024-01-01t00:00:00z", 1704067200.0), // RFC3339 says the designators are case-insensitive
    ("2024-01-01T00:00:00.000Z", 1704067200.0),
    ("2024-01-01T00:00:00", 1704067200.0), // naive => UTC, never the host zone
    ("2024-01-01 00:00:00", 1704067200.0), // the ClickHouse form HogQL emits; luxon alone rejected it
    ("2024-01-01T00:00", 1704067200.0),
    ("2024-01-01T00:00:00+05:00", 1704049200.0),
    ("2024-01-01 00:00:00+05:00", 1704049200.0),
    ("2024-01-01T00:00:00-0500", 1704085200.0), // offset without the colon
    ("2024-01-01T00:00:00.123Z", 1704067200.123),
    ("2024-01-01T00:00:00.123456Z", 1704067200.123), // truncated to ms, not rounded
    ("  2024-01-01  ", 1704067200.0),
];

const REJECTED: [&str; 11] = [
    "2024", // luxon accepted these five as instants; a string property could plausibly hold any
    "2024-01",
    "20240101", // Python's `fromisoformat` accepted this and `2024-W05`; the others never did
    "2024-W05",
    "2024-001",
    "12:30",      // luxon resolved this against *today's* date
    "1700000000", // this VM used to accept a bare numeric string as unix seconds; neither other did
    "not-a-date",
    "",
    "2024-13-01",
    "2024-02-30",
];

#[test]
fn date_like_accept_set_matches_the_shared_grammar() {
    for (input, expected) in ACCEPTED {
        let dt = run(returning(&to_datetime(input)));
        assert_eq!(
            dt["dt"].as_f64().expect("parsed to a number"),
            expected,
            "should accept {input:?}"
        );
    }
    for input in REJECTED {
        // `err_to_null` turns the parse failure into Null; see below.
        assert_eq!(
            run(returning(&to_datetime(input))),
            Value::Null,
            "should reject {input:?}"
        );
    }
}

#[test]
fn to_datetime_parses_naive_string_as_utc_not_local() {
    let result = run(returning(&to_datetime("2026-05-13 00:00:00")));
    let expected = NaiveDate::from_ymd_opt(2026, 5, 13)
        .unwrap()
        .and_hms_opt(0, 0, 0)
        .unwrap()
        .and_utc()
        .timestamp() as f64;

    assert_eq!(result["__hogDateTime__"], json!(true));
    assert_eq!(result["zone"], json!("UTC"));
    assert_eq!(result["dt"].as_f64().unwrap(), expected);
}

#[test]
fn to_datetime_honors_an_explicit_iso_offset() {
    let result = run(returning(&to_datetime("2026-03-19T14:00:00Z")));
    let expected = Utc
        .with_ymd_and_hms(2026, 3, 19, 14, 0, 0)
        .unwrap()
        .timestamp() as f64;
    assert_eq!(result["dt"].as_f64().unwrap(), expected);
}

#[test]
fn to_datetime_arity2_interprets_naive_string_in_the_given_zone() {
    let utc = run(returning(&to_datetime("2026-05-13 00:00:00")));
    let ny = run(returning(&to_datetime_zoned(
        "2026-05-13 00:00:00",
        "America/New_York",
    )));
    assert_eq!(ny["zone"], json!("America/New_York"));
    assert_eq!(
        ny["dt"].as_f64().unwrap() - utc["dt"].as_f64().unwrap(),
        4.0 * 3600.0,
    );
}

#[test]
fn to_datetime_passes_through_a_unix_number() {
    let bc = returning(&[
        json!(33), // OP_INTEGER
        json!(1_700_000_000),
        json!(OP_CALL_GLOBAL),
        json!("toDateTime"),
        json!(1),
    ]);
    assert_eq!(run(bc)["dt"].as_f64().unwrap(), 1_700_000_000.0);
}

#[test]
fn unparseable_input_becomes_null_not_an_error() {
    // `err_to_null` turns a parse failure into `Null` so the leaf's `if(isNull(...), false, …)` guard wins.
    assert_eq!(
        run(returning(&to_datetime("definitely not a date"))),
        Value::Null
    );
}

#[test]
fn datetime_less_than_orders_by_instant() {
    let earlier = to_datetime("2020-01-01 00:00:00");
    let later = to_datetime("2030-01-01 00:00:00");
    assert_eq!(run(compare(&earlier, &later, OP_LT)), Value::Bool(true));
    assert_eq!(run(compare(&later, &earlier, OP_LT)), Value::Bool(false));
}

#[test]
fn datetime_greater_than_orders_by_instant() {
    let earlier = to_datetime("2020-06-15 12:00:00");
    let later = to_datetime("2020-06-15 12:00:01");
    assert_eq!(run(compare(&later, &earlier, OP_GT)), Value::Bool(true));
    assert_eq!(run(compare(&earlier, &later, OP_GT)), Value::Bool(false));
}

#[test]
fn datetime_equality_is_by_instant() {
    let naive = to_datetime("2026-03-19 14:00:00");
    let iso_z = to_datetime("2026-03-19T14:00:00Z");
    let other = to_datetime("2026-03-19 14:00:01");
    assert_eq!(run(compare(&naive, &iso_z, OP_EQ)), Value::Bool(true));
    assert_eq!(run(compare(&naive, &other, OP_EQ)), Value::Bool(false));
}

/// Run WITHOUT opting into coercing comparisons — the default every non-cohort consumer gets.
fn run_legacy(bytecode: Vec<Value>) -> Value {
    let program = Program::new(bytecode).expect("valid program");
    let ctx = ExecutionContext::with_defaults(program).with_globals(json!({}));
    sync_execute(&ctx, false).expect("execution succeeds")
}

#[test]
fn legacy_default_compares_temporals_structurally_not_by_epoch() {
    // Same instant (05:30 Kolkata == 00:00 UTC), different zone: epoch-equal but structurally
    // distinct objects. The opt-in coercing path treats them as equal (ClickHouse `is_date_exact`);
    // the default path every other consumer (e.g. cymbal) gets keeps the legacy structural
    // comparison, so they are NOT equal — proving the temporal `Eq` change is gated.
    let kolkata = to_datetime_zoned("2026-01-01 05:30:00", "Asia/Kolkata");
    let utc = to_datetime("2026-01-01 00:00:00");
    assert_eq!(
        run(compare(&kolkata, &utc, OP_EQ)),
        Value::Bool(true),
        "coercing: epoch-equal"
    );
    assert_eq!(
        run_legacy(compare(&kolkata, &utc, OP_EQ)),
        Value::Bool(false),
        "legacy: structurally distinct (zone differs)",
    );
}

#[test]
fn bare_field_string_orders_against_a_datetime_by_parsing_it() {
    // Regression: a hand-written SQL trigger filter like `timestamp > toDateTime('2026-01-01')`
    // only wraps the RHS in toDateTime, so the VM compares a bare String literal (the filter globals'
    // ISO `timestamp`) against a HogDateTime object. Before this fix, exactly one side being temporal
    // fell straight to `CannotCoerce` — the trigger's filter would error, not silently pass, but it
    // never matched by ordering either.
    let bare_timestamp = vec![json!(OP_STRING), json!("2026-06-28T00:00:00.000Z")];
    let threshold = to_datetime("2026-01-01 00:00:00");
    assert_eq!(
        run(compare(&bare_timestamp, &threshold, OP_GT)),
        Value::Bool(true)
    );
    assert_eq!(
        run(compare(&threshold, &bare_timestamp, OP_GT)),
        Value::Bool(false)
    );
}

#[test]
fn bare_field_string_equals_a_datetime_by_parsing_it() {
    // Regression: ordering got the bare-field string treatment but equality did not, so
    // `timestamp == toDateTime('…')` was silently false here while the Python/TS VMs said true —
    // they route all six comparison opcodes through one coercion function. `Eq` and `Gt` must agree
    // on which operands count as dates.
    let bare = |s: &str| vec![json!(OP_STRING), json!(s)];
    let threshold = to_datetime("2026-01-01 00:00:00");

    for (label, string) in [
        ("naive", "2026-01-01 00:00:00"),
        ("iso Z", "2026-01-01T00:00:00.000Z"),
        ("date only", "2026-01-01"),
    ] {
        assert_eq!(
            run(compare(&bare(string), &threshold, OP_EQ)),
            Value::Bool(true),
            "{label}: string on the left"
        );
        assert_eq!(
            run(compare(&threshold, &bare(string), OP_EQ)),
            Value::Bool(true),
            "{label}: string on the right"
        );
        assert_eq!(
            run(compare(&bare(string), &threshold, OP_NOT_EQ)),
            Value::Bool(false),
            "{label}: NotEq is the negation"
        );
    }

    // A different instant, and a string the grammar rejects, both stay unequal rather than erroring.
    assert_eq!(
        run(compare(&bare("2026-01-02"), &threshold, OP_EQ)),
        Value::Bool(false)
    );
    assert_eq!(
        run(compare(&bare("not-a-date"), &threshold, OP_EQ)),
        Value::Bool(false)
    );
}

#[test]
fn legacy_default_does_not_coerce_string_vs_temporal_eq() {
    // The bare-field coercion is gated on `with_coercing_comparisons`, so cymbal's rules engine —
    // which relies on the legacy structural path, and permanently disables a rule on any VmError —
    // is unaffected by the `eq_op` change above.
    let bare = vec![json!(OP_STRING), json!("2026-01-01 00:00:00")];
    let threshold = to_datetime("2026-01-01 00:00:00");
    assert_eq!(run(compare(&bare, &threshold, OP_EQ)), Value::Bool(true));
    assert_eq!(
        run_legacy(compare(&bare, &threshold, OP_EQ)),
        Value::Bool(false),
        "legacy: a String is never structurally equal to a HogDateTime object",
    );
}

#[test]
fn in_does_not_coerce_strings_against_temporals() {
    // Pinning a deliberate gap, not an endorsement: `in` skips the comparison coercion in all three
    // VMs (TS `Array.includes`, Python `in`, Rust `contains` → structural `equals`), so this is
    // consistent today. Rust's `contains` is also NOT gated on `coerce_comparisons` and is shared
    // with `has()` and cymbal, so changing it is a bigger decision than it looks.
    const OP_ARRAY: i64 = 43;
    const OP_IN: i64 = 21;
    let haystack = {
        let mut bc = to_datetime("2026-01-01 00:00:00");
        bc.extend_from_slice(&[json!(OP_ARRAY), json!(1)]);
        bc
    };
    let needle = vec![json!(OP_STRING), json!("2026-01-01 00:00:00")];
    assert_eq!(run(compare(&needle, &haystack, OP_IN)), Value::Bool(false));
}

#[test]
fn date_and_datetime_are_mutually_comparable() {
    let date = vec![
        json!(OP_STRING),
        json!("2026-05-13"),
        json!(OP_CALL_GLOBAL),
        json!("toDate"),
        json!(1),
    ];
    let noon = to_datetime("2026-05-13 12:00:00");
    assert_eq!(run(compare(&date, &noon, OP_LT)), Value::Bool(true));
}

#[test]
fn full_compiled_shape_to_string_to_datetime_lt() {
    // Realistic leaf shape `Lt(toDateTime(toString(person.properties.signup_date)), toDateTime(const))`;
    // the `toString → toDateTime` hop mirrors `_force_datetime`. `Program` is not `Clone`, so rebuild per iteration.
    const OP_GET_GLOBAL: i64 = 1;
    let bytecode = || {
        let lhs = vec![
            json!(OP_STRING),
            json!("signup_date"),
            json!(OP_STRING),
            json!("properties"),
            json!(OP_STRING),
            json!("person"),
            json!(OP_GET_GLOBAL),
            json!(3),
            json!(OP_CALL_GLOBAL),
            json!("toString"),
            json!(1),
            json!(OP_CALL_GLOBAL),
            json!("toDateTime"),
            json!(1),
        ];
        compare(&lhs, &to_datetime("2026-01-01 00:00:00"), OP_LT)
    };

    for (signup, expected) in [
        ("2024-09-09 08:30:00", true),
        ("2027-09-09 08:30:00", false),
    ] {
        let program = Program::new(bytecode()).expect("valid program");
        let ctx = ExecutionContext::with_defaults(program)
            .with_globals(json!({ "person": { "properties": { "signup_date": signup } } }))
            .with_coercing_comparisons();
        assert_eq!(
            sync_execute(&ctx, false).expect("execution succeeds"),
            Value::Bool(expected),
            "signup {signup}",
        );
    }
}
