//! Coverage for the `toDateTime`/`toDate` natives and Hog-temporal comparison (F2).
//!
//! These power `is_date_before`/`is_date_after`/`is_date_exact` cohort leaves, which
//! (`posthog/hogql/property.py` `_force_datetime`) compile to `Lt`/`Gt`/`Eq` of two
//! `toDateTime(...)` objects. The reference Python/TS HogVMs cannot order those objects (Python
//! raises, TS stringifies) — only ClickHouse does — so this VM deliberately orders them by `dt`
//! seconds. Parsing must be UTC-by-default (ClickHouse/TS), **not** Python's local-tz
//! `datetime.fromisoformat(...).timestamp()` bug; the value-pin test below guards that.

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
    let ctx = ExecutionContext::with_defaults(program).with_globals(json!({}));
    sync_execute(&ctx, false).expect("execution succeeds")
}

/// `toDateTime("<s>")` (arity 1).
fn to_datetime(s: &str) -> Vec<Value> {
    vec![
        json!(OP_STRING),
        json!(s),
        json!(OP_CALL_GLOBAL),
        json!("toDateTime"),
        json!(1),
    ]
}

/// `toDateTime("<s>", "<zone>")` (arity 2). Args push left-to-right: input then zone.
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

/// `left <op> right`. The compiler emits `visit(right), visit(left), op`
/// (`bytecode.py:visit_compare_operation`), so the program is `[right…, left…, op]`.
fn compare(left: &[Value], right: &[Value], op: i64) -> Vec<Value> {
    let mut bc = vec![json!("_H"), json!(1)];
    bc.extend_from_slice(right);
    bc.extend_from_slice(left);
    bc.push(json!(op));
    bc.push(json!(OP_RETURN));
    bc
}

/// A program that evaluates one bytecode fragment and returns its value.
fn returning(fragment: &[Value]) -> Vec<Value> {
    let mut bc = vec![json!("_H"), json!(1)];
    bc.extend_from_slice(fragment);
    bc.push(json!(OP_RETURN));
    bc
}

#[test]
fn to_datetime_parses_naive_string_as_utc_not_local() {
    // The decisive anti-Python-local-tz-bug pin: a naive ClickHouse-format string is interpreted in
    // UTC, so `dt` is the UTC epoch regardless of the machine/process timezone.
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
    // `2026-03-19T14:00:00Z` is an absolute instant — the `Z` pins it regardless of any default tz.
    let result = run(returning(&to_datetime("2026-03-19T14:00:00Z")));
    let expected = Utc
        .with_ymd_and_hms(2026, 3, 19, 14, 0, 0)
        .unwrap()
        .timestamp() as f64;
    assert_eq!(result["dt"].as_f64().unwrap(), expected);
}

#[test]
fn to_datetime_arity2_interprets_naive_string_in_the_given_zone() {
    // The 2-arg (team-tz) form: the same naive wall-clock in New York (EDT, UTC-4 on 2026-05-13) is
    // four hours *later* in absolute terms than in UTC.
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
    // A number is already absolute unix seconds.
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
    // `err_to_null` turns a parse failure into `Null` so the leaf's `if(isNull(...), false, …)`
    // guard yields `false` rather than erroring the whole evaluation.
    assert_eq!(
        run(returning(&to_datetime("definitely not a date"))),
        Value::Null
    );
}

#[test]
fn datetime_less_than_orders_by_instant() {
    // `is_date_before`: left(person date) < right(threshold).
    let earlier = to_datetime("2020-01-01 00:00:00");
    let later = to_datetime("2030-01-01 00:00:00");
    assert_eq!(run(compare(&earlier, &later, OP_LT)), Value::Bool(true));
    assert_eq!(run(compare(&later, &earlier, OP_LT)), Value::Bool(false));
}

#[test]
fn datetime_greater_than_orders_by_instant() {
    // `is_date_after`: left(person date) > right(threshold).
    let earlier = to_datetime("2020-06-15 12:00:00");
    let later = to_datetime("2020-06-15 12:00:01"); // one second later
    assert_eq!(run(compare(&later, &earlier, OP_GT)), Value::Bool(true));
    assert_eq!(run(compare(&earlier, &later, OP_GT)), Value::Bool(false));
}

#[test]
fn datetime_equality_is_by_instant() {
    // `is_date_exact`: two equal instants written differently (naive UTC vs explicit `Z`) are equal.
    let naive = to_datetime("2026-03-19 14:00:00");
    let iso_z = to_datetime("2026-03-19T14:00:00Z");
    let other = to_datetime("2026-03-19 14:00:01");
    assert_eq!(run(compare(&naive, &iso_z, OP_EQ)), Value::Bool(true));
    assert_eq!(run(compare(&naive, &other, OP_EQ)), Value::Bool(false));
}

#[test]
fn date_and_datetime_are_mutually_comparable() {
    // `toDate` yields a UTC-midnight date; comparing it against a datetime orders on one axis.
    let date = vec![
        json!(OP_STRING),
        json!("2026-05-13"),
        json!(OP_CALL_GLOBAL),
        json!("toDate"),
        json!(1),
    ];
    let noon = to_datetime("2026-05-13 12:00:00");
    // midnight (date) < noon (datetime) on the same day.
    assert_eq!(run(compare(&date, &noon, OP_LT)), Value::Bool(true));
}

#[test]
fn full_compiled_shape_to_string_to_datetime_lt() {
    // The realistic leaf shape: `Lt(toDateTime(toString(person.properties.signup_date)),
    // toDateTime(const))` — the `toString → toDateTime` hop mirrors `_force_datetime` for the
    // non-constant LHS. `Program` is not `Clone`, so rebuild the bytecode per globals iteration.
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

    // A 2024 signup is before the 2026 threshold → member; a 2027 signup is not.
    for (signup, expected) in [
        ("2024-09-09 08:30:00", true),
        ("2027-09-09 08:30:00", false),
    ] {
        let program = Program::new(bytecode()).expect("valid program");
        let ctx = ExecutionContext::with_defaults(program)
            .with_globals(json!({ "person": { "properties": { "signup_date": signup } } }));
        assert_eq!(
            sync_execute(&ctx, false).expect("execution succeeds"),
            Value::Bool(expected),
            "signup {signup}",
        );
    }
}
