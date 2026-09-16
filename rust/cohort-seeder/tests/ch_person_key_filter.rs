//! Proves against a real ClickHouse that the person scan's key-presence filter drops only rows the
//! seeder's fold would have pruned anyway.
//!
//! The filter is the one place where a server-side function decides whether a person is scanned at
//! all, so a blob ClickHouse reads differently from `serde_json` is a silently dropped member. Only
//! ClickHouse can say how `JSONType` and `JSONExtractKeys` read a hostile blob, so there is no Rust
//! mock of the predicate here — a mock would prove the mock.
//!
//! The oracle is deliberately loose in one direction and exact in the other. A blob ClickHouse
//! reports as a JSON object must be dropped exactly when it carries none of the keys, because that
//! is the whole saving. Every other blob must be admitted, because the seeder decides those: an
//! array errors in the VM, a scalar and a literal `null` read every key as null, an empty blob
//! parses to `{}` and is decided from the cached vacuous verdict, a malformed blob is a skipped
//! row, and a document holding a number ClickHouse cannot represent also reports `Null` while
//! `serde_json` parses it and the VM reads its keys.
//!
//! Needs a reachable ClickHouse, which is why it sits behind `ch-test-support`. It reads its
//! endpoint through the seeder's own `Config`/`build_client`, so it also exercises the client-side
//! template parser that turns a bare `?` in a rendered key literal into an unbound bind placeholder.

#![cfg(feature = "ch-test-support")]

use std::collections::{BTreeMap, BTreeSet};

use clickhouse::{Client, Row};
use cohort_seeder::clickhouse::client::build_client;
use cohort_seeder::clickhouse::person_sql::{person_scan_sql, PersonScanSpec};
use cohort_seeder::config::Config;
use cohort_seeder::domain::{PersonRange, ProjectedKeys, UtcMillis};
use envconfig::Envconfig;
use serde::Deserialize;
use serde_json::Value;
use uuid::Uuid;

/// One blob as ClickHouse would hold the `properties` column, and the keys a run's conditions read.
struct Case {
    blob: &'static str,
    keys: &'static [&'static str],
}

const fn case(blob: &'static str, keys: &'static [&'static str]) -> Case {
    Case { blob, keys }
}

/// Hand-authored rather than sampled from production: every case is here because it names a way the
/// server-side test could disagree with the fold, and a sample of real properties would carry
/// customer data while covering none of the hostile shapes.
const CORPUS: &[Case] = &[
    // The saving: an object carrying none of the keys is dropped.
    case(r#"{}"#, &["email"]),
    case(r#"{"other":1}"#, &["email"]),
    case(r#"{"plan":"paid"}"#, &["email"]),
    // Present in any form, including a null value, keeps the row.
    case(r#"{"email":"a@b.com"}"#, &["email"]),
    case(r#"{"email":null}"#, &["email"]),
    case(r#"{"email":""}"#, &["email"]),
    case(r#"{"plan":"paid","email":"a@b.com"}"#, &["email", "plan"]),
    case(r#"{"plan":"paid"}"#, &["email", "plan"]),
    // Key matching is exact: a case difference, a nested occurrence, or a near-miss must not admit.
    case(r#"{"Email":"a@b.com"}"#, &["email"]),
    case(r#"{"EMAIL":"a@b.com"}"#, &["email"]),
    case(r#"{"a":{"email":1}}"#, &["email"]),
    case(r#"{"emai":1,"emails":2,"email2":3}"#, &["email"]),
    // Duplicate keys, which ClickHouse keeps in order and `serde_json` collapses to the last.
    case(r#"{"email":"a","email":"b"}"#, &["email"]),
    case(r#"{"other":1,"other":2}"#, &["email"]),
    // Whitespace around a valid object is still an object to both parsers.
    case("  \t{\"email\":\"a@b.com\"}\n ", &["email"]),
    case("  \t{\"other\":1}\n ", &["email"]),
    // Keys that have to survive both the SQL literal escaping and JSON key decoding.
    case(r#"{"$feature/flag":"variant"}"#, &["$feature/flag"]),
    case(r#"{"has space":1}"#, &["has space"]),
    case(r#"{"quote\"key":1}"#, &["quote\"key"]),
    case(r#"{"back\\slash":1}"#, &["back\\slash"]),
    case(r#"{"question?":1}"#, &["question?"]),
    case(r#"{"why?fields":1}"#, &["why?fields"]),
    case(r#"{"new\nline":1}"#, &["new\nline"]),
    case(r#"{"tab\tkey":1}"#, &["tab\tkey"]),
    case(r#"{"":1}"#, &[""]),
    case(r#"{"é😀":1}"#, &["é😀"]),
    // A key written as a JSON escape has to match the decoded name a condition reads: ClickHouse
    // and `serde_json` both decode key escapes, and the globals a condition indexes into hold the
    // decoded name.
    case(r#"{"\u0065mail":"a@b.com"}"#, &["email"]),
    case(r#"{"\ud83d\ude00":1}"#, &["😀"]),
    case(r#"{"\u0065mail":1}"#, &["\\u0065mail"]),
    // The single quote is the one escape whose failure would be an injection rather than a wrong
    // answer. A predicate that broke out of its literal would admit or drop everything.
    case(r#"{"quote' OR 1 = 1 --":1}"#, &["quote' OR 1 = 1 --"]),
    case(r#"{"other":1}"#, &["quote' OR 1 = 1 --"]),
    // Non-objects: all admitted, because the seeder's fold is what decides them.
    case(r#"[1]"#, &["email"]),
    case(r#"[{"email":"a@b.com"}]"#, &["email"]),
    case(r#""a string""#, &["email"]),
    case(r#"42"#, &["email"]),
    case(r#"true"#, &["email"]),
    case(r#"null"#, &["email"]),
    case(r#""#, &["email"]),
    case(r#"{not json"#, &["email"]),
    case(r#"{"email":1,"#, &["email"]),
    case(r#"{'email':1}"#, &["email"]),
    // The case the plan's tighter predicate would have dropped: ClickHouse gives up on the whole
    // document over a number it cannot represent and reports `Null`, while `serde_json` parses it
    // and the VM reads `email` — so this person is a member the scan must not drop.
    case(
        r#"{"email":"a@b.com","big":123456789012345678901234567890}"#,
        &["email"],
    ),
    case(r#"{"email":"a@b.com","huge":1e309}"#, &["email"]),
    // Many keys, one read: the shape the filter exists for.
    case(
        r#"{"k0":0,"k1":1,"k2":2,"k3":3,"k4":4,"k5":5,"k6":6,"k7":7,"k8":8,"k9":9}"#,
        &["email"],
    ),
];

#[derive(Row, Deserialize)]
struct Admitted {
    index: u32,
    admitted: bool,
}

#[derive(Row, Deserialize)]
struct ExplainLine {
    explain: String,
}

#[tokio::test]
async fn the_key_filter_drops_exactly_the_key_less_object_blobs() {
    let client = connect();
    // Grouped by key set because that is what the predicate is rendered from, so one query per
    // distinct set covers the corpus in a handful of round trips.
    let mut by_keys: BTreeMap<&'static [&'static str], Vec<&'static str>> = BTreeMap::new();
    for case in CORPUS {
        by_keys.entry(case.keys).or_default().push(case.blob);
    }

    for (keys, blobs) in by_keys {
        let admitted = admit_all(&client, keys, &blobs).await;
        for (blob, admitted) in blobs.iter().zip(&admitted) {
            assert_eq!(
                *admitted,
                oracle(blob, keys),
                "blob {blob:?} against keys {keys:?}"
            );
        }
    }
}

/// A large object must still be read key by key rather than truncated somewhere.
#[tokio::test]
async fn a_large_object_is_still_read_key_by_key() {
    let client = connect();
    let mut wide = String::from("{");
    for index in 0..4_000 {
        if index > 0 {
            wide.push(',');
        }
        wide.push_str(&format!("\"k{index}\":\"{}\"", "v".repeat(20)));
    }
    let without = format!("{wide}}}");
    let with = format!("{wide},\"email\":\"a@b.com\"}}");
    assert!(with.len() > 100_000, "the wide blob is meant to be large");

    let admitted = admit_all(&client, &["email"], &[&without, &with]).await;
    assert_eq!(admitted, vec![false, true]);
}

/// The rendered scan names `argMax(p.properties, p.version)` three times — once in the select list
/// and twice in the filter — because a bare `properties` in `HAVING` would bind to the output alias
/// instead of the column. ClickHouse has to fold those into one aggregate state, or the filter costs
/// every chunk two extra passes over the widest column in the table.
#[tokio::test]
async fn the_repeated_aggregate_is_computed_once() {
    let client = connect();
    let keys = ProjectedKeys::new(BTreeSet::from(["email".to_owned()])).unwrap();
    let spec = PersonScanSpec::new(
        cohort_core::filters::TeamId(2),
        UtcMillis::new(1_780_000_000_000),
        PersonRange::new(Uuid::nil(), None).unwrap(),
        Some(keys),
    );
    let sql = person_scan_sql(&spec);
    assert_eq!(
        sql.matches("argMax(p.properties, p.version)").count(),
        3,
        "the rendered text is meant to name the aggregate three times"
    );

    let plan = client
        .query(&format!("EXPLAIN actions = 1 {sql}"))
        .fetch_all::<ExplainLine>()
        .await
        .unwrap_or_else(|error| panic!("EXPLAIN failed: {error}\n{sql}"))
        .into_iter()
        .map(|line| line.explain)
        .collect::<Vec<_>>();
    assert!(plan.len() > 1, "the plan did not decode: {plan:?}");

    // The `Aggregates:` block lists each distinct aggregate once, as a bare
    // `argMax(<table>.properties, <table>.version)` line with no `Function:`/`Arguments:` prefix.
    let states = plan
        .iter()
        .filter(|line| {
            let line = line.trim();
            line.starts_with("argMax(") && line.contains("properties") && line.ends_with(')')
        })
        .collect::<Vec<_>>();
    assert_eq!(
        states.len(),
        1,
        "the repeated aggregate was not folded into one state: {states:?}\n{}",
        plan.join("\n")
    );
}

fn connect() -> Client {
    let config = Config::init_from_env().expect("the seeder config falls back to its defaults");
    build_client(&config).expect("the default ClickHouse client builds")
}

/// Run the production predicate over `blobs`, in the blobs' own order.
async fn admit_all(client: &Client, keys: &[&str], blobs: &[&str]) -> Vec<bool> {
    let sql = format!(
        "WITH ? AS blobs\nSELECT index, {} AS admitted\nFROM (SELECT arrayJoin(arrayEnumerate(blobs)) AS index, blobs[index] AS blob)\nORDER BY index",
        predicate_over("blob", keys),
    );
    let owned = blobs
        .iter()
        .map(|blob| (*blob).to_owned())
        .collect::<Vec<_>>();
    let rows = client
        .query(&sql)
        .bind(owned)
        .fetch_all::<Admitted>()
        .await
        .unwrap_or_else(|error| panic!("the key-filter query failed: {error}\n{sql}"));
    assert_eq!(rows.len(), blobs.len(), "a blob went missing: {sql}");
    // `arrayEnumerate` is 1-based, and the caller pairs these rows with its blobs positionally, so
    // the promised order has to hold before the results are stripped to booleans.
    for (position, row) in rows.iter().enumerate() {
        assert_eq!(
            row.index as usize,
            position + 1,
            "rows arrived out of order: {sql}"
        );
    }
    rows.into_iter().map(|row| row.admitted).collect()
}

/// The predicate exactly as `person_scan_sql` renders it, lifted out of the surrounding scan and
/// re-pointed at `column`. Extracted from a rendered scan rather than re-assembled, so a change to
/// the production text cannot slip past this file.
fn predicate_over(column: &str, keys: &[&str]) -> String {
    let keys = ProjectedKeys::new(keys.iter().map(|key| (*key).to_owned()).collect())
        .expect("every corpus case names at least one key");
    let spec = PersonScanSpec::new(
        cohort_core::filters::TeamId(2),
        UtcMillis::new(1_780_000_000_000),
        PersonRange::new(Uuid::nil(), None).unwrap(),
        Some(keys),
    );
    let sql = person_scan_sql(&spec);
    let predicate = sql
        .split_once("\n   AND (JSONType")
        .and_then(|(_, rest)| rest.split_once("\nSETTINGS"))
        .map(|(predicate, _)| format!("(JSONType{predicate}"))
        .expect("the rendered scan carries the key filter");
    predicate.replace("argMax(p.properties, p.version)", column)
}

/// What the seeder's own fold does with a blob: an object is worth scanning only when it carries a
/// key, and every other blob is the fold's to decide.
fn oracle(blob: &str, keys: &[&str]) -> bool {
    match serde_json::from_str::<Value>(blob) {
        Ok(Value::Object(map)) => keys.iter().any(|key| map.contains_key(*key)),
        Ok(_) | Err(_) => true,
    }
}

/// The oracle itself, so a mistake in it cannot quietly weaken every assertion above.
#[test]
fn the_oracle_admits_every_non_object_and_reads_object_keys_exactly() {
    assert!(!oracle(r#"{}"#, &["email"]));
    assert!(!oracle(r#"{"Email":1}"#, &["email"]));
    assert!(!oracle(r#"{"a":{"email":1}}"#, &["email"]));
    assert!(oracle(r#"{"email":null}"#, &["email"]));
    assert!(oracle(r#"{"plan":1}"#, &["email", "plan"]));
    for admitted in [r#"[1]"#, r#""s""#, r#"42"#, r#"null"#, r#""#, r#"{bad"#] {
        assert!(oracle(admitted, &["email"]), "{admitted} must be admitted");
    }
}
