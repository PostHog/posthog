//! Welds leader admission to the writer's real apply path: any properties
//! value that passes admission (NUL sanitization + the exact jsonb size
//! measure) must land through the writer's actual upsert statement against
//! a live Postgres. This is the executable form of the changelog contract
//! — nothing admission accepts may be unapplyable — and it must break if
//! either side's rejection surface drifts.
//!
//! Requires local PG (posthog_persons) like the other writer integration
//! tests; the target is `personhog_person_tmp`, which carries the size
//! constraint and the uuid unique index.

mod common;

use common::create_test_pool;
use personhog_common::properties::{
    jsonb_column_size, sanitize_for_jsonb, trim_properties_to_fit_size, TrimResult,
};
use personhog_proto::personhog::types::v1::Person;
use personhog_writer::pg::PgStore;
use personhog_writer::store::PersonDb;
use serde_json::{json, Value};
use uuid::Uuid;

const TARGET_TABLE: &str = "personhog_person_tmp";
const SIZE_THRESHOLD: usize = 655_360;
const TRIM_TARGET: usize = 524_288;
const WELD_TEAM_ID: i64 = 99_400;

/// Hostile property maps: every shape we could think of that has ever made
/// a JSON store or a bind path unhappy. Extend freely — every fixture that
/// admission admits must apply.
fn hostile_fixtures() -> Vec<(&'static str, Value)> {
    let deep = {
        // serde_json's default parse recursion limit is 128, which bounds
        // anything the leader can hold; stay just under it.
        let mut v = json!("bottom");
        for _ in 0..120 {
            v = json!({ "d": v });
        }
        v
    };
    let many_nuls: String = "\u{0000}".repeat(500);
    let big_fitting = "x".repeat(400_000);

    vec![
        ("empty_object", json!({})),
        ("empty_key_and_value", json!({"": ""})),
        ("nul_in_value", json!({"k": "a\u{0000}b"})),
        ("nul_in_key", json!({"a\u{0000}b": "v"})),
        ("nul_only_key", json!({"\u{0000}": "\u{0000}"})),
        ("many_nuls", json!({"k": many_nuls})),
        (
            "nul_nested_in_arrays",
            json!({"k": [["\u{0000}"], {"inner\u{0000}": ["x\u{0000}y"]}]}),
        ),
        (
            "control_characters_besides_nul",
            json!({"k": "\u{0001}\u{0008}\u{000b}\u{001f}\u{007f}"}),
        ),
        (
            "numbers_at_the_edges",
            json!({
                "max_u64": u64::MAX,
                "min_i64": i64::MIN,
                // Sanitization clamps this to 1e307: PG's expanded numeric
                // rendering of anything larger cannot be parsed back by
                // serde_json (the leader's own PG fallback would choke).
                "huge_float": 1.7976931348623157e308,
                "boundary_float": 1e307,
                "tiny_float": 5e-324,
                "neg_zero": -0.0,
            }),
        ),
        (
            "unicode_zoo",
            json!({"emoji": "👩‍👩‍👧‍👧🏳️‍⚧️", "rtl": "مرحبا", "cjk": "漢字テスト한글", "fffd": "\u{FFFD}", "zwj": "a\u{200d}b"}),
        ),
        ("deeply_nested", json!({"deep": deep})),
        (
            "big_but_fitting",
            json!({"email": "a@b.c", "blob": big_fitting}),
        ),
        (
            "quotes_and_escapes",
            json!({"k": "\"\\\n\r\t/\u{0008}", "\\\"key\"\\": "v"}),
        ),
        (
            "duplicate_after_sanitize",
            json!({"a\u{0000}": "first", "a\u{FFFD}": "second"}),
        ),
    ]
}

/// The leader's admission pipeline, verbatim: sanitize, measure, trim.
/// Returns the properties as they would be produced, or None if admission
/// rejects (protected properties alone cannot fit).
fn admit(mut properties: Value) -> Option<Value> {
    sanitize_for_jsonb(&mut properties);
    if jsonb_column_size(&properties) > SIZE_THRESHOLD {
        match trim_properties_to_fit_size(&properties, TRIM_TARGET) {
            TrimResult::Trimmed(trimmed) => return Some(trimmed),
            TrimResult::Fits => {}
            TrimResult::CannotFit => return None,
        }
    }
    Some(properties)
}

fn person_for(fixture_index: i64, properties: &Value) -> Person {
    Person {
        id: fixture_index,
        team_id: WELD_TEAM_ID,
        uuid: Uuid::new_v4().to_string(),
        properties: serde_json::to_vec(properties).unwrap(),
        created_at: 1_700_000_000,
        version: 1,
        is_identified: false,
        ..Default::default()
    }
}

async fn cleanup(pool: &sqlx::PgPool) {
    sqlx::query("DELETE FROM personhog_person_tmp WHERE team_id = $1")
        .bind(WELD_TEAM_ID)
        .execute(pool)
        .await
        .unwrap();
}

#[tokio::test]
async fn every_admitted_fixture_lands_through_the_writers_real_upsert() {
    let pool = create_test_pool().await;
    cleanup(&pool).await;
    let store = PgStore::new(pool.clone(), TARGET_TABLE.to_string());

    for (index, (name, fixture)) in hostile_fixtures().into_iter().enumerate() {
        let admitted = admit(fixture)
            .unwrap_or_else(|| panic!("fixture {name} must be admissible — none is oversized"));
        let person = person_for(index as i64 + 1, &admitted);
        store
            .execute_row(&person)
            .await
            .unwrap_or_else(|e| panic!("admitted fixture {name} must apply, got: {e}"));

        // The stored jsonb round-trips to exactly the admitted value.
        let (stored,): (Value,) = sqlx::query_as(
            "SELECT properties FROM personhog_person_tmp WHERE team_id = $1 AND id = $2",
        )
        .bind(WELD_TEAM_ID)
        .bind(index as i64 + 1)
        .fetch_one(&pool)
        .await
        .unwrap();
        assert_eq!(stored, admitted, "fixture {name} must round-trip verbatim");
    }

    cleanup(&pool).await;
}

/// Proves the weld can detect what it guards: the raw (unsanitized) NUL
/// fixture is exactly what PG refuses, so skipping sanitization must fail
/// the same statement the admitted fixtures pass.
#[tokio::test]
async fn unsanitized_nul_is_rejected_by_the_same_statement() {
    let pool = create_test_pool().await;
    let store = PgStore::new(pool.clone(), TARGET_TABLE.to_string());

    let person = person_for(9_999, &json!({"k": "a\u{0000}b"}));
    let err = store
        .execute_row(&person)
        .await
        .expect_err("PG must refuse a NUL that bypassed sanitization");
    assert!(
        err.message.contains("0000") || err.message.to_lowercase().contains("unicode"),
        "rejection should be the jsonb NUL refusal, got: {}",
        err.message
    );
}
