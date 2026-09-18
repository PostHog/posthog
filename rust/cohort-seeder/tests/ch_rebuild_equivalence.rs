//! Proves against a real ClickHouse that a key-filtered blob parses to exactly what the whole blob
//! parses to with the unread keys removed.
//!
//! That relation is the one new obligation the column projection takes on. Everything else about a
//! projected row is already the pipeline it was before: the row decoder lifts an empty column to
//! "absent" and the globals builder reads absent as `{}` without parsing, so a scan that selects
//! fewer columns runs the unchanged hot path. Only the rebuilt blob is new text, and only
//! ClickHouse can say what it contains.
//!
//! So there is no Rust mock of the rebuild expression here. A mock would prove the mock.
//!
//! Needs a reachable ClickHouse, which is why it sits behind `ch-test-support`. It reads its
//! endpoint through the seeder's own `Config`/`build_client`, so it also exercises the client-side
//! template parser that turns a bare `?` in a rendered literal into an unbound bind placeholder.

#![cfg(feature = "ch-test-support")]

use std::collections::{BTreeMap, BTreeSet};

use clickhouse::{Client, Row};
use cohort_seeder::clickhouse::client::build_client;
use cohort_seeder::clickhouse::sql::rebuild_expr;
use cohort_seeder::config::Config;
use cohort_seeder::domain::ProjectedKeys;
use envconfig::Envconfig;
use serde::Deserialize;
use serde_json::{Map, Value};

/// One blob as ClickHouse would hold it, and the keys a chunk's conditions read from it.
struct Case {
    blob: &'static str,
    keys: &'static [&'static str],
}

const fn case(blob: &'static str, keys: &'static [&'static str]) -> Case {
    Case { blob, keys }
}

/// Hand-authored rather than sampled from production: every case is here because it names a way the
/// rebuild could differ from a prune, and a sample of real properties would carry customer data
/// while covering none of the hostile shapes.
const CORPUS: &[Case] = &[
    // Ordinary shapes.
    case(r#"{"plan":"paid","utm_source":"ads"}"#, &["plan"]),
    case(
        r#"{"plan":"paid","utm_source":"ads"}"#,
        &["plan", "utm_source"],
    ),
    case(r#"{"plan":"paid"}"#, &["utm_source"]),
    case(r#"{}"#, &["plan"]),
    case(r#"{"plan":"paid"}"#, &["plan", "absent"]),
    // Value kinds, kept raw so nothing is re-encoded on the way through.
    case(r#"{"nested":{"a":[1,2,{"b":null}]},"x":1}"#, &["nested"]),
    case(r#"{"list":[1,"two",false,null],"x":1}"#, &["list"]),
    case(
        r#"{"nul":null,"yes":true,"no":false}"#,
        &["nul", "yes", "no"],
    ),
    case(r#"{"big":123456789012345678901234567890}"#, &["big"]),
    case(
        r#"{"tiny":-1.5e-300,"round":1.0,"zero":-0.0}"#,
        &["tiny", "round", "zero"],
    ),
    // Float re-prints, and the integer tokens that must not follow them. ClickHouse re-serializes
    // recursively, so the floats inside a kept subtree flip too, and `values_equivalent` has to
    // recurse to read that as the same value. 64-bit integers keep their digits instead, which a
    // condition comparing Int to Int can observe, so the oracle holds those exactly.
    case(r#"{"exp":1e3,"caps":1E3,"x":1}"#, &["exp", "caps"]),
    case(
        r#"{"nested":{"round":1.0,"list":[2.0,1e3]},"x":1}"#,
        &["nested"],
    ),
    case(
        r#"{"imax":9223372036854775807,"umax":18446744073709551615}"#,
        &["imax", "umax"],
    ),
    case(
        r#"{"empty_obj":{},"empty_arr":[]}"#,
        &["empty_obj", "empty_arr"],
    ),
    // Duplicate keys. ClickHouse keeps both entries in order and serde_json takes the last, so the
    // rebuilt blob has to keep the order rather than the first match a materialized column would.
    case(r#"{"plan":"free","plan":"paid"}"#, &["plan"]),
    case(r#"{"plan":"free","other":1,"plan":"paid"}"#, &["plan"]),
    case(r#"{"plan":"free","plan":"paid"}"#, &["other"]),
    // Text realism in values.
    case(r#"{"who":"Ana Lópe😀z","x":1}"#, &["who"]),
    case(
        r#"{"esc":"quote \" backslash \\ newline \n tab \t","x":1}"#,
        &["esc"],
    ),
    case(r#"{"uni":"é😀","x":1}"#, &["uni"]),
    case(r#"{"braces":"{\"not\":\"json\"}","x":1}"#, &["braces"]),
    case(r#"{"colon":"a:b,c","x":1}"#, &["colon"]),
    // Keys that have to survive both the SQL literal escaping and the JSON re-quoting.
    case(r#"{"$feature/flag":"variant","x":1}"#, &["$feature/flag"]),
    case(r#"{"has space":1,"x":2}"#, &["has space"]),
    case(r#"{"quote\"key":1,"x":2}"#, &["quote\"key"]),
    // The single quote is the one escape whose failure would be an injection rather than a wrong
    // value, and the renderer's goldens can only pin the text they produce. This runs the same
    // payload the event-name golden uses through a real server, so "the literal stays closed" is
    // measured rather than argued.
    case(r#"{"quote' OR 1 = 1 --":1,"x":2}"#, &["quote' OR 1 = 1 --"]),
    case(r#"{"back\\slash":1,"x":2}"#, &["back\\slash"]),
    case(r#"{"question?":1,"x":2}"#, &["question?"]),
    case(r#"{"why?fields":1,"x":2}"#, &["why?fields"]),
    case(r#"{"new\nline":1,"x":2}"#, &["new\nline"]),
    case(r#"{"tab\tkey":1,"x":2}"#, &["tab\tkey"]),
    case(r#"{"":1,"x":2}"#, &[""]),
    case(r#"{"é😀":1,"x":2}"#, &["é😀"]),
    // A key written as a JSON escape must match the decoded key a condition reads: ClickHouse
    // decodes key escapes before the IN filter and re-encodes on the way out, and the globals a
    // condition indexes into hold the decoded name.
    case(r#"{"\u0070lan":"paid","x":1}"#, &["plan"]),
    case(r#"{"\ud83d\ude00":1,"x":2}"#, &["😀"]),
    // Case and near-miss keys must not match: a prefix match would leak a key no condition reads.
    case(r#"{"Plan":1,"plan":2,"plan2":3}"#, &["plan"]),
    // Roots that are valid JSON but not objects. The globals builder takes them as they are, so the
    // rebuild has to hand them back untouched.
    case(r#"[1,2,3]"#, &["a"]),
    case(r#""a string""#, &["a"]),
    case(r#"123"#, &["a"]),
    case(r#"true"#, &["a"]),
    case(r#"null"#, &["a"]),
    // Malformed roots, which reach the same parse failure and the same skipped-row metric they
    // reach today.
    case(r#""#, &["a"]),
    case(r#"garbage"#, &["a"]),
    case(r#"{"a":1,"#, &["a"]),
    case(r#"{"a":1} trailing"#, &["a"]),
    case(r#"{"a":1}{"b":2}"#, &["a"]),
    case(r#"{'a':1}"#, &["a"]),
    case(r#"{"a":01}"#, &["a"]),
    // Whitespace around a valid object is still an object to both parsers.
    case("  \t{\"plan\":\"paid\"}\n ", &["plan"]),
    // Many keys, few read: the shape the projection exists for.
    case(
        r#"{"k0":0,"k1":1,"k2":2,"k3":3,"k4":4,"k5":5,"k6":6,"k7":7,"k8":8,"k9":9,"plan":"paid"}"#,
        &["plan", "k7"],
    ),
];

/// What a globals build would see for one blob: the parsed value, or nothing when the parse fails
/// and the row is skipped.
type Parsed = Result<Value, ()>;

#[derive(Row, Deserialize)]
struct Rebuilt {
    index: u32,
    rebuilt: String,
}

#[tokio::test]
async fn a_key_filtered_rebuild_parses_to_the_pruned_whole_blob() {
    let client = connect();
    // Grouped by key set because the key set is what the expression is rendered from, so one query
    // per distinct set covers the whole corpus in a handful of round trips.
    let mut by_keys: BTreeMap<&'static [&'static str], Vec<&'static str>> = BTreeMap::new();
    for case in CORPUS {
        by_keys.entry(case.keys).or_default().push(case.blob);
    }

    for (keys, blobs) in by_keys {
        let rebuilt = rebuild_all(&client, keys, &blobs).await;
        for (blob, rebuilt) in blobs.iter().zip(&rebuilt) {
            let (rebuilt_value, pruned) = (parse(rebuilt), prune(parse(blob), keys));
            assert!(
                equivalent(&rebuilt_value, &pruned),
                "blob {blob:?} filtered to {keys:?} rebuilt as {rebuilt:?}\n  parsed: {rebuilt_value:?}\n  wanted: {pruned:?}"
            );
        }
    }
}

/// The one input class where a projected row is not the row today's pipeline produces.
///
/// `serde_json` refuses to parse past 128 levels of nesting while ClickHouse parses much deeper,
/// so a blob whose *unread* part is deeper than that is skipped by the wide scan today and
/// evaluated once projected. The live processor parses the full payload with `serde_json` and
/// skips the same row, so this is a permanent seed-versus-live hole, not a transient seed-only
/// one: the seeded history counts an event live evaluation never will. An over-count rather than
/// a miss, on a shape no property editor produces. Pinned rather than hedged, because a guard
/// would cost every row to buy back a case this names precisely.
#[tokio::test]
async fn a_blob_too_deep_for_serde_but_not_for_clickhouse_diverges() {
    let deep = format!(
        r#"{{"plan":"paid","deep":{}1{}}}"#,
        r#"{"d":"#.repeat(200),
        "}".repeat(200)
    );
    assert!(
        parse(&deep).is_err(),
        "the whole blob is meant to be past serde_json's recursion limit"
    );

    let client = connect();
    let rebuilt = rebuild_all(&client, &["plan"], &[&deep]).await;
    assert_eq!(
        parse(&rebuilt[0]),
        Ok(Value::Object(Map::from_iter([(
            "plan".to_owned(),
            Value::String("paid".to_owned())
        )]))),
        "the shallow key survives the rebuild, so the projected row evaluates where the wide one \
         would have been skipped"
    );
}

/// ClickHouse gives up on the whole document when any number token is outside what it can
/// represent, wherever that token sits: `JSONType` reports `Null`, so the rebuild's guard passes
/// the blob through verbatim. The projected row is then byte-identical to the wide scan's row,
/// which is zero evaluation divergence, just wider than the pruned oracle. That is why this sits
/// beside the depth pin instead of weakening the main assertion.
#[tokio::test]
async fn a_number_clickhouse_cannot_represent_passes_the_whole_blob_through() {
    let client = connect();
    for blob in [
        r#"{"plan":"paid","big":123456789012345678901234567890}"#,
        r#"{"plan":"paid","huge":1e309}"#,
    ] {
        let rebuilt = rebuild_all(&client, &["plan"], &[blob]).await;
        assert_eq!(rebuilt[0], blob, "expected verbatim passthrough");
    }
}

fn connect() -> Client {
    let config = Config::init_from_env().expect("the seeder config falls back to its defaults");
    build_client(&config).expect("the default ClickHouse client builds")
}

/// Run the production rebuild expression over `blobs`, in the blobs' own order.
async fn rebuild_all(client: &Client, keys: &[&str], blobs: &[&str]) -> Vec<String> {
    let keys = ProjectedKeys::new(keys.iter().map(|key| (*key).to_owned()).collect())
        .expect("every corpus case names at least one key");
    let sql = format!(
        "WITH ? AS blobs\nSELECT index, {} AS rebuilt\nFROM (SELECT arrayJoin(arrayEnumerate(blobs)) AS index, blobs[index] AS blob)\nORDER BY index",
        rebuild_expr("blob", &keys)
    );
    let owned = blobs
        .iter()
        .map(|blob| (*blob).to_owned())
        .collect::<Vec<_>>();
    let rows = client
        .query(&sql)
        .bind(owned)
        .fetch_all::<Rebuilt>()
        .await
        .unwrap_or_else(|error| panic!("the rebuild query failed: {error}\n{sql}"));
    assert_eq!(rows.len(), blobs.len(), "a blob went missing: {sql}");
    // `arrayEnumerate` is 1-based, and the caller pairs these rows with its blobs positionally, so
    // the order the query promises has to hold before the results are stripped down to strings.
    for (position, row) in rows.iter().enumerate() {
        assert_eq!(
            row.index as usize,
            position + 1,
            "rows arrived out of order: {sql}"
        );
    }
    rows.into_iter().map(|row| row.rebuilt).collect()
}

/// What the globals builder would get from a raw column value.
fn parse(blob: &str) -> Parsed {
    serde_json::from_str(blob).map_err(|_| ())
}

/// The whole blob's parse with everything the chunk does not read removed — the value a projected
/// row has to reproduce. Non-objects pass through, because a projection cannot narrow what has no
/// keys.
fn prune(parsed: Parsed, keys: &[&str]) -> Parsed {
    let keys = keys.iter().copied().collect::<BTreeSet<_>>();
    parsed.map(|value| match value {
        Value::Object(map) => Value::Object(
            map.into_iter()
                .filter(|(key, _)| keys.contains(key.as_str()))
                .collect(),
        ),
        other => other,
    })
}

fn equivalent(a: &Parsed, b: &Parsed) -> bool {
    match (a, b) {
        (Ok(a), Ok(b)) => values_equivalent(a, b),
        _ => a == b,
    }
}

/// Equal under everything the evaluator can observe once HogVM compares numbers numerically: a
/// float ClickHouse re-prints (`1.0` to `1`, `1e3` to `1000`) is then the same value to every
/// condition. That is a claim about the VM this corpus is written against, not about the VM on
/// this branch, where `Num` equality is still variant-exact and the re-print is observable. Green
/// here therefore means "safe after that change", which is why the change has to land first.
///
/// Integer tokens keep their digits on both sides and a digit change there would be observable
/// either way, so integers still compare exactly. Everything else has to match outright.
fn values_equivalent(a: &Value, b: &Value) -> bool {
    match (a, b) {
        (Value::Number(a), Value::Number(b)) => {
            if a.is_f64() || b.is_f64() {
                a.as_f64() == b.as_f64()
            } else {
                a == b
            }
        }
        (Value::Array(a), Value::Array(b)) => {
            a.len() == b.len() && a.iter().zip(b).all(|(a, b)| values_equivalent(a, b))
        }
        (Value::Object(a), Value::Object(b)) => {
            a.len() == b.len()
                && a.iter()
                    .all(|(key, a)| b.get(key).is_some_and(|b| values_equivalent(a, b)))
        }
        _ => a == b,
    }
}

/// The oracle itself: the numeric blur must stay confined to float representation, or every
/// assertion in this file weakens with it.
#[test]
fn the_equivalence_oracle_blurs_only_float_representation() {
    let value = |text: &str| serde_json::from_str::<Value>(text).expect("oracle cases parse");
    let eq = |a: &str, b: &str| values_equivalent(&value(a), &value(b));
    assert!(eq(r#"{"round":1.0}"#, r#"{"round":1}"#));
    assert!(eq(r#"{"exp":1e3}"#, r#"{"exp":1000}"#));
    assert!(eq(r#"{"deep":[{"x":-0.0}]}"#, r#"{"deep":[{"x":-0}]}"#));
    assert!(
        !eq(r#"{"n":1}"#, r#"{"n":"1"}"#),
        "a string is not its number"
    );
    assert!(!eq(r#"{"n":1}"#, r#"{"n":2}"#));
    assert!(
        !eq(r#"{"a":1}"#, r#"{"a":1,"b":2}"#),
        "a leaked key must fail"
    );
    assert!(
        !eq(r#"{"n":9007199254740993}"#, r#"{"n":9007199254740992}"#),
        "integer digits stay load-bearing past 2^53"
    );
}
