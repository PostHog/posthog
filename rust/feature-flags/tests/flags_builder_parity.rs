//! Rust half of the flags-cache builder parity test.
//!
//! Seeds one team from `fixtures/builder_parity_seed.json`, builds the hypercache payload with
//! `build_flags_cache`, and asserts it against `fixtures/builder_parity_golden.json`. The Python
//! half (`products/feature_flags/backend/test/test_flags_builder_parity.py`) seeds the same rows
//! and asserts the same golden, so the golden is the only place the two builders meet and neither
//! suite has to run the other language.
//!
//! Neither half writes the golden. Regeneration runs from the Python half, on purpose: a builder
//! that both writes the target and asserts against it proves nothing.
//!
//! The comparison is `diff_live_entry`, the same semantic diff the production shadow compare uses,
//! so this test and production agree on what "the same payload" means. Both sides pass through the
//! typed models first, which is what keeps JSON key order, absent-versus-null optional fields, and
//! integer-versus-float number formatting out of the result.

use std::collections::HashMap;

use chrono::{DateTime, Utc};
use serde_json::Value;

use feature_flags::flags::cache_builder::build_flags_cache;
use feature_flags::flags::cache_shadow::{diff_live_entry, summarize_diffs, ShadowLiveEntry};
use feature_flags::flags::flag_models::FeatureFlagRow;
use feature_flags::utils::test_utils::TestContext;

const SEED: &str = include_str!("fixtures/builder_parity_seed.json");
const GOLDEN: &str = include_str!("fixtures/builder_parity_golden.json");

const GOLDEN_PATH: &str = "rust/feature-flags/tests/fixtures/builder_parity_golden.json";
const REGENERATE_COMMAND: &str = "UPDATE_FLAGS_BUILDER_PARITY_GOLDEN=1 hogli test \
                                  products/feature_flags/backend/test/test_flags_builder_parity.py";

const TEAM_TOKEN: &str = "@team";
const COHORT_PREFIX: &str = "@cohort:";
const FLAG_PREFIX: &str = "@flag:";
const FLAG_STR_PREFIX: &str = "@flag_str:";

/// Real ids of the seeded rows, keyed by the `ref` the seed file gives each one.
#[derive(Default)]
struct SeededIds {
    team_id: i32,
    cohorts: HashMap<String, i32>,
    flags: HashMap<String, i32>,
}

impl SeededIds {
    fn id_for(&self, token: &str) -> Option<i32> {
        if token == TEAM_TOKEN {
            return Some(self.team_id);
        }
        for (prefix, table) in [
            (COHORT_PREFIX, &self.cohorts),
            (FLAG_PREFIX, &self.flags),
            (FLAG_STR_PREFIX, &self.flags),
        ] {
            if let Some(reference) = token.strip_prefix(prefix) {
                return Some(*table.get(reference).unwrap_or_else(|| {
                    panic!("{token} names a ref the seed does not define before this point")
                }));
            }
        }
        None
    }

    fn resolve_scalar(&self, value: &str) -> Value {
        match self.id_for(value) {
            None => Value::String(value.to_string()),
            // A flag dependency stores the id it points at as a decimal string.
            Some(id) if value.starts_with(FLAG_STR_PREFIX) => Value::String(id.to_string()),
            Some(id) => Value::from(id),
        }
    }

    fn resolve_key(&self, key: &str) -> String {
        self.id_for(key)
            .map_or_else(|| key.to_string(), |id| id.to_string())
    }
}

/// Replace every seed reference token with the id the row actually got. Mirrors
/// `resolve_tokens` in the Python half; the two must stay in step or the sides read the
/// same files as different data.
fn resolve_tokens(value: &Value, ids: &SeededIds) -> Value {
    match value {
        Value::Object(map) => Value::Object(
            map.iter()
                .map(|(key, nested)| (ids.resolve_key(key), resolve_tokens(nested, ids)))
                .collect(),
        ),
        Value::Array(items) => Value::Array(items.iter().map(|v| resolve_tokens(v, ids)).collect()),
        Value::String(text) => ids.resolve_scalar(text),
        other => other.clone(),
    }
}

/// SQL NULL for a JSON null, so a nullable `jsonb` column does not receive the JSON value
/// `null` instead.
fn optional_json(value: &Value) -> Option<Value> {
    (!value.is_null()).then(|| value.clone())
}

fn optional_i32(value: &Value) -> Option<i32> {
    value.as_i64().map(|number| number as i32)
}

fn optional_timestamp(value: &Value) -> Option<DateTime<Utc>> {
    let text = value.as_str()?;
    Some(
        DateTime::parse_from_rfc3339(text)
            .unwrap_or_else(|e| panic!("{text} is not a timestamp the seed can use: {e}"))
            .with_timezone(&Utc),
    )
}

fn required_str<'a>(spec: &'a Value, field: &str) -> &'a str {
    spec[field]
        .as_str()
        .unwrap_or_else(|| panic!("seed entry is missing the {field} field"))
}

fn required_bool(spec: &Value, field: &str) -> bool {
    spec[field]
        .as_bool()
        .unwrap_or_else(|| panic!("seed entry is missing the {field} field"))
}

/// Insert every seeded row in file order, so ids ascend in file order the way the golden's
/// id-sorted arrays expect. Every column the payload carries is written explicitly: a column
/// left to its database default here would diverge from the Django default the Python half
/// gets, and the two seeds would differ before either builder ran.
async fn seed_team(context: &TestContext, team_id: i32, seed: &Value) -> SeededIds {
    let mut ids = SeededIds {
        team_id,
        ..Default::default()
    };

    for spec in seed["cohorts"]
        .as_array()
        .expect("seed has a cohorts array")
    {
        let mut conn = context
            .get_non_persons_connection()
            .await
            .expect("Failed to get a connection to seed a cohort");
        let row: (i32,) = sqlx::query_as(
            r#"INSERT INTO posthog_cohort
                (team_id, name, description, deleted, filters, query, version, pending_version,
                 count, is_calculating, is_static, errors_calculating, groups, created_by_id,
                 cohort_type, condition_type, last_backfill_person_properties_at,
                 last_backfill_events_at, last_realtime_cohort_calculation_at, created_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, NULL, $14, $15,
                       $16, $17, $18, NOW())
               RETURNING id"#,
        )
        .bind(team_id)
        .bind(required_str(spec, "name"))
        .bind(required_str(spec, "description"))
        .bind(required_bool(spec, "deleted"))
        .bind(resolve_tokens(&spec["filters"], &ids))
        .bind(optional_json(&spec["query"]))
        .bind(optional_i32(&spec["version"]))
        .bind(optional_i32(&spec["pending_version"]))
        .bind(optional_i32(&spec["count"]))
        .bind(required_bool(spec, "is_calculating"))
        .bind(required_bool(spec, "is_static"))
        .bind(optional_i32(&spec["errors_calculating"]).expect("errors_calculating is required"))
        .bind(spec["groups"].clone())
        .bind(spec["cohort_type"].as_str())
        .bind(optional_json(&spec["condition_type"]))
        .bind(optional_timestamp(
            &spec["last_backfill_person_properties_at"],
        ))
        .bind(optional_timestamp(&spec["last_backfill_events_at"]))
        .bind(optional_timestamp(
            &spec["last_realtime_cohort_calculation_at"],
        ))
        .fetch_one(&mut *conn)
        .await
        .expect("Failed to seed a cohort");
        ids.cohorts
            .insert(required_str(spec, "ref").to_string(), row.0);
    }

    for spec in seed["flags"].as_array().expect("seed has a flags array") {
        let mut conn = context
            .get_non_persons_connection()
            .await
            .expect("Failed to get a connection to seed a flag");
        let row: (i32,) = sqlx::query_as(
            r#"INSERT INTO posthog_featureflag
                (team_id, key, name, filters, deleted, active, ensure_experience_continuity,
                 version, evaluation_runtime, bucketing_identifier, created_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, NOW())
               RETURNING id"#,
        )
        .bind(team_id)
        .bind(required_str(spec, "key"))
        .bind(required_str(spec, "name"))
        .bind(resolve_tokens(&spec["filters"], &ids))
        .bind(required_bool(spec, "deleted"))
        .bind(required_bool(spec, "active"))
        .bind(spec["ensure_experience_continuity"].as_bool())
        .bind(optional_i32(&spec["version"]))
        .bind(spec["evaluation_runtime"].as_str())
        .bind(spec["bucketing_identifier"].as_str())
        .fetch_one(&mut *conn)
        .await
        .expect("Failed to seed a flag");
        let flag_id = row.0;
        ids.flags
            .insert(required_str(spec, "ref").to_string(), flag_id);

        let context_names: Vec<&str> = spec["evaluation_contexts"]
            .as_array()
            .expect("seed flag has an evaluation_contexts array")
            .iter()
            .map(|name| {
                name.as_str()
                    .expect("an evaluation context name is a string")
            })
            .collect();
        if !context_names.is_empty() {
            context
                .insert_evaluation_tags_for_flag(flag_id, team_id, context_names)
                .await
                .expect("Failed to seed evaluation contexts");
        }

        if required_bool(spec, "has_experiment") {
            context
                .insert_experiment(flag_id, team_id, false)
                .await
                .expect("Failed to seed an experiment");
        }
    }

    ids
}

#[tokio::test]
async fn built_payload_matches_the_golden_python_also_asserts() {
    let context = TestContext::new(None).await;
    let team = context
        .insert_new_team(None)
        .await
        .expect("Failed to insert team");
    let seed: Value = serde_json::from_str(SEED).expect("the seed must parse");
    let ids = seed_team(&context, team.id, &seed).await;

    let built = build_flags_cache(context.non_persons_reader.clone(), team.id)
        .await
        .expect("Failed to build the flags cache");

    let golden: Value = serde_json::from_str(GOLDEN).expect("the golden must parse");
    let expected: ShadowLiveEntry = serde_json::from_value(resolve_tokens(&golden, &ids)).expect(
        "the golden must deserialize into the models the service reads a cache entry with — \
         a golden this side cannot represent is itself a parity failure",
    );

    let diffs = diff_live_entry(&built, &expected);
    assert!(
        diffs.is_empty(),
        "The Rust flags-cache builder no longer produces the golden payload.\n\n{}\n\n\
         The Python builder asserts against the same file, so a change here that is correct is a \
         change both builders have to make. Confirm the new payload is what you meant to ship, \
         then regenerate {GOLDEN_PATH} from the Python half:\n    {REGENERATE_COMMAND}",
        summarize_diffs(&diffs, 20, 4000),
    );
}

#[tokio::test]
async fn a_flag_whose_stored_filters_do_not_parse_stays_in_the_payload() {
    // Python's builder hands the stored JSONB straight to the payload, so a flag this side
    // cannot deserialize still has to reach the cache entry. Dropping it puts a smaller flag
    // set behind the same team, and every flag it drops evaluates as missing.
    //
    // This case cannot live in the shared golden: a golden holding these filters does not
    // deserialize into the typed models above, so the failure would be a parse error covering
    // every other flag rather than a report about this one.
    let context = TestContext::new(None).await;
    let team = context
        .insert_new_team(None)
        .await
        .expect("Failed to insert team");

    let flag_row = |key: &str, filters: Value| FeatureFlagRow {
        team_id: team.id,
        key: key.to_string(),
        // `posthog_featureflag.name` is NOT NULL.
        name: Some(String::new()),
        active: true,
        evaluation_runtime: Some("all".to_string()),
        filters,
        ..Default::default()
    };
    context
        .insert_flag(
            team.id,
            Some(flag_row(
                "parity-typed-filters",
                serde_json::json!({"groups": [{"properties": [], "rollout_percentage": 100}]}),
            )),
        )
        .await
        .expect("Failed to insert the well-typed flag");
    // A rollout percentage stored as a string. Django's JSONField accepts it and the payload
    // carries it through; this side parses the same key as a number.
    context
        .insert_flag(
            team.id,
            Some(flag_row(
                "parity-wrongly-typed-filters",
                serde_json::json!({"groups": [{"properties": [], "rollout_percentage": "100"}]}),
            )),
        )
        .await
        .expect("Failed to insert the wrongly-typed flag");

    let built = build_flags_cache(context.non_persons_reader.clone(), team.id)
        .await
        .expect("Failed to build the flags cache");

    let keys: Vec<&str> = built.flags.iter().map(|flag| flag.key.as_str()).collect();
    assert!(
        keys.contains(&"parity-wrongly-typed-filters"),
        "A flag whose stored filters do not match the typed model was left out of the payload. \
         The Python builder keeps it, so the two writers put different flag sets in the same \
         cache entry. Payload held: {keys:?}",
    );
}
