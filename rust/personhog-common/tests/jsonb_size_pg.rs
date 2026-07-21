//! Welds `jsonb_column_size` to the ground truth: for every fixture, the
//! Rust computation must equal `pg_column_size($1::jsonb)` from a real
//! Postgres. The JSONB binary format is stable across PG versions
//! (pg_upgrade compatibility), so a failure here means our encoder — not
//! PG — changed or was wrong. Fixtures deliberately sweep the encoder's
//! branches: alignment padding at every residue, numeric weight and
//! dscale boundaries, exponent literals, nesting, and near-threshold
//! sizes.

use personhog_common::properties::jsonb_column_size;
use serde_json::{json, Value};
use sqlx::postgres::PgPoolOptions;
use sqlx::Row;

const DB_URL: &str = "postgres://posthog:posthog@localhost:5432/posthog_persons";

fn fixtures() -> Vec<Value> {
    let mut cases = vec![
        // Root scalars (wrapped in a pseudo-array container).
        json!(null),
        json!(true),
        json!(false),
        json!(0),
        json!(1),
        json!(-1),
        json!(9),
        json!(9999),
        json!(10000),
        json!(99999999),
        json!(100000000),
        json!(-10000),
        json!(100),
        json!(1000),
        json!(123.45),
        json!(0.1),
        json!(0.0001),
        json!(0.00001),
        json!(1e-10),
        json!(1.5e10),
        json!(u64::MAX),
        json!(i64::MIN),
        json!(-0.007),
        json!(1.234567890123456),
        json!(""),
        json!("a"),
        json!("hello"),
        json!("héllo wörld ✨"),
        // Containers.
        json!({}),
        json!([]),
        json!([1, 2, 3]),
        json!(["a", "bb", "ccc"]),
        json!([null, true, false]),
        json!({"a": 1}),
        json!({"email": "test@example.com", "name": "Test"}),
        json!({"nested": {"a": [1, 2, {"b": "c"}]}}),
        json!([[], {}, [[]], {"x": {}}]),
        json!({"n": [0.5, -3, 12345.6789, 1e5]}),
    ];

    // Alignment sweep: a string of every length residue before a numeric
    // and before a nested container, at object and array level.
    for pad in 0..8 {
        let s = "x".repeat(pad);
        cases.push(json!({ "k": s, "n": 123.456 }));
        cases.push(json!({ "k": s, "o": {"inner": 1} }));
        cases.push(json!([s, 42, s.clone(), {"a": 7.7}, 0.001]));
    }

    // Many-key objects (sorted-key processing order + JEntry accounting).
    let mut wide = serde_json::Map::new();
    for i in 0..64 {
        wide.insert(format!("key_{i:03}"), json!(i));
    }
    cases.push(Value::Object(wide));

    // Mixed-length keys so PG's (length, bytewise) key order differs from
    // alphabetical — padding depends on processing order.
    cases.push(json!({
        "zz": 1.5, "a": "x", "mmmm": [1.25, "y"], "b": 2, "ccc": {"d": 0.75}
    }));

    // A large, near-threshold person shape.
    let mut big = serde_json::Map::new();
    big.insert("email".to_string(), json!("someone@example.com"));
    for i in 0..500 {
        big.insert(format!("prop_{i}"), json!("v".repeat(1000)));
    }
    big.insert("counter".to_string(), json!(123456.789));
    cases.push(Value::Object(big));

    cases
}

#[tokio::test]
async fn jsonb_column_size_matches_postgres() {
    let pool = PgPoolOptions::new()
        .max_connections(2)
        .connect(DB_URL)
        .await
        .expect("local posthog_persons Postgres must be running (docker compose)");

    for value in fixtures() {
        // Send the exact bytes the leader would produce, so PG parses the
        // same literals our sizer measured.
        let text = serde_json::to_string(&value).unwrap();
        let row = sqlx::query("SELECT pg_column_size($1::jsonb) AS size")
            .bind(&text)
            .fetch_one(&pool)
            .await
            .unwrap();
        let pg_size: i32 = row.get("size");
        let ours = jsonb_column_size(&value);
        assert_eq!(
            ours,
            pg_size as usize,
            "jsonb size mismatch for {}: ours={ours} pg={pg_size}",
            if text.len() > 120 {
                &text[..120]
            } else {
                &text
            }
        );
    }
}
