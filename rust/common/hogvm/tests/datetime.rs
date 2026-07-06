//! Coverage for the `toDateTime`/`toDate` natives and Hog-temporal comparison. This VM orders
//! temporals by `dt` seconds to match ClickHouse (the reference Python/TS HogVMs cannot order them);
//! naive strings parse as UTC, not the process-local timezone.

use chrono::{NaiveDate, TimeZone, Utc};
use hogvm::{sync_execute, ExecutionContext, Program};
use serde_json::{json, Value};

// Opcode numeric values (mirror common/hogvm/python/operation.py).
const OP_CALL_GLOBAL: i64 = 2;
const OP_EQ: i64 = 11;
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
