//! Integration tests for the internal batch flag evaluation endpoint
//! (`POST /internal/batch_flag_evaluation`), which backs flag-driven static cohort
//! generation.

use anyhow::Result;
use reqwest::StatusCode;
use serde_json::{json, Value};
use uuid::Uuid;

pub mod common;
use crate::common::ServerHandle;
use feature_flags::config::{Config, DEFAULT_TEST_CONFIG};
use feature_flags::flags::flag_matching_utils::calculate_hash;
use feature_flags::flags::flag_models::FeatureFlagRow;
use feature_flags::utils::test_utils::{random_string, TestContext};

const INTERNAL_TOKEN: &str = "test-internal-request-token";
const ENDPOINT: &str = "/internal/batch_flag_evaluation";

fn batch_eval_config() -> Config {
    let mut config = DEFAULT_TEST_CONFIG.clone();
    config.internal_request_token = Some(INTERNAL_TOKEN.to_string());
    config
}

async fn send_batch_request(
    server: &ServerHandle,
    bearer_token: Option<&str>,
    body: &Value,
) -> reqwest::Response {
    let client = reqwest::Client::new();
    let mut request = client
        .post(format!("http://{}{}", server.addr, ENDPOINT))
        .header("content-type", "application/json")
        .body(body.to_string());
    if let Some(token) = bearer_token {
        request = request.header("authorization", format!("Bearer {token}"));
    }
    request.send().await.expect("Failed to send batch request")
}

fn batch_body(team_id: i32, flag_key: &str, expected_version: i32) -> Value {
    json!({
        "team_id": team_id,
        "project_id": team_id,
        "flag_key": flag_key,
        "expected_version": expected_version,
    })
}

fn flag_row(team_id: i32, key: &str, filters: Value) -> FeatureFlagRow {
    FeatureFlagRow {
        id: 0,
        team_id,
        name: Some(format!("{key} description")),
        key: key.to_string(),
        filters,
        deleted: false,
        active: true,
        ensure_experience_continuity: Some(false),
        version: None,
        evaluation_runtime: None,
        evaluation_tags: None,
        bucketing_identifier: None,
        has_experiment: false,
    }
}

/// Matched UUIDs as a sorted Vec for set comparison.
fn matched_uuids(response_json: &Value) -> Vec<Uuid> {
    let mut uuids: Vec<Uuid> = response_json["matched_person_uuids"]
        .as_array()
        .expect("matched_person_uuids should be an array")
        .iter()
        .map(|v| v.as_str().unwrap().parse().unwrap())
        .collect();
    uuids.sort();
    uuids
}

#[tokio::test]
async fn test_rejects_unauthenticated_requests() -> Result<()> {
    let context = TestContext::new(None).await;
    let team = context.insert_new_team(None).await?;
    let server = ServerHandle::for_config(batch_eval_config()).await;

    let body = batch_body(team.id, "any-flag", 0);

    // No Authorization header
    let res = send_batch_request(&server, None, &body).await;
    assert_eq!(res.status(), StatusCode::UNAUTHORIZED);

    // Wrong bearer token
    let res = send_batch_request(&server, Some("wrong-token"), &body).await;
    assert_eq!(res.status(), StatusCode::UNAUTHORIZED);

    Ok(())
}

#[tokio::test]
async fn test_rejects_all_requests_when_no_internal_token_configured() -> Result<()> {
    let context = TestContext::new(None).await;
    let team = context.insert_new_team(None).await?;

    let mut config = DEFAULT_TEST_CONFIG.clone();
    config.internal_request_token = None;
    let server = ServerHandle::for_config(config).await;

    let res = send_batch_request(
        &server,
        Some(INTERNAL_TOKEN),
        &batch_body(team.id, "any-flag", 0),
    )
    .await;
    assert_eq!(res.status(), StatusCode::UNAUTHORIZED);

    Ok(())
}

#[tokio::test]
async fn test_rejects_invalid_limits() -> Result<()> {
    let context = TestContext::new(None).await;
    let team = context.insert_new_team(None).await?;
    let server = ServerHandle::for_config(batch_eval_config()).await;

    for bad_limit in [0, -5, 10_001] {
        let mut body = batch_body(team.id, "any-flag", 0);
        body["limit"] = json!(bad_limit);
        let res = send_batch_request(&server, Some(INTERNAL_TOKEN), &body).await;
        assert_eq!(
            res.status(),
            StatusCode::BAD_REQUEST,
            "limit {bad_limit} should be rejected"
        );
        let json_response = res.json::<Value>().await?;
        assert_eq!(json_response["error"], "invalid_request");
    }

    Ok(())
}

#[tokio::test]
async fn test_missing_and_deleted_flags_return_not_found() -> Result<()> {
    let context = TestContext::new(None).await;
    let team = context.insert_new_team(None).await?;
    let server = ServerHandle::for_config(batch_eval_config()).await;

    // Non-existent flag
    let res = send_batch_request(
        &server,
        Some(INTERNAL_TOKEN),
        &batch_body(team.id, "does-not-exist", 0),
    )
    .await;
    assert_eq!(res.status(), StatusCode::NOT_FOUND);

    // Deleted flag — the flag fetch excludes deleted flags, so this is
    // indistinguishable from a missing flag.
    let mut deleted = flag_row(
        team.id,
        "deleted-flag",
        json!({"groups": [{"properties": [{"key": "key", "value": "value", "type": "person"}]}]}),
    );
    deleted.deleted = true;
    context.insert_flag(team.id, Some(deleted)).await?;

    let res = send_batch_request(
        &server,
        Some(INTERNAL_TOKEN),
        &batch_body(team.id, "deleted-flag", 0),
    )
    .await;
    assert_eq!(res.status(), StatusCode::NOT_FOUND);

    Ok(())
}

#[tokio::test]
async fn test_inactive_flag_rejected() -> Result<()> {
    // The Django caller returns [] for inactive flags without calling us; this guard
    // is defensive.
    let context = TestContext::new(None).await;
    let team = context.insert_new_team(None).await?;
    let server = ServerHandle::for_config(batch_eval_config()).await;

    let mut inactive = flag_row(
        team.id,
        "inactive-flag",
        json!({"groups": [{"rollout_percentage": 100}]}),
    );
    inactive.active = false;
    context.insert_flag(team.id, Some(inactive)).await?;

    let res = send_batch_request(
        &server,
        Some(INTERNAL_TOKEN),
        &batch_body(team.id, "inactive-flag", 0),
    )
    .await;
    assert_eq!(res.status(), StatusCode::BAD_REQUEST);
    let json_response = res.json::<Value>().await?;
    assert_eq!(json_response["error"], "flag_inactive");

    Ok(())
}

#[tokio::test]
async fn test_group_aggregated_flag_rejected() -> Result<()> {
    // The Django caller returns [] for group-aggregated flags without calling us;
    // this guard is defensive.
    let context = TestContext::new(None).await;
    let team = context.insert_new_team(None).await?;
    let server = ServerHandle::for_config(batch_eval_config()).await;

    context
        .insert_flag(
            team.id,
            Some(flag_row(
                team.id,
                "group-flag",
                json!({
                    "groups": [{"properties": [{"key": "key", "value": "value", "type": "group", "group_type_index": 1}]}],
                    "aggregation_group_type_index": 1,
                }),
            )),
        )
        .await?;

    let res = send_batch_request(
        &server,
        Some(INTERNAL_TOKEN),
        &batch_body(team.id, "group-flag", 0),
    )
    .await;
    assert_eq!(res.status(), StatusCode::BAD_REQUEST);
    let json_response = res.json::<Value>().await?;
    assert_eq!(json_response["error"], "group_aggregated_flag");

    Ok(())
}

#[tokio::test]
async fn test_version_mismatch_returns_conflict_with_actual_version() -> Result<()> {
    let context = TestContext::new(None).await;
    let team = context.insert_new_team(None).await?;
    let server = ServerHandle::for_config(batch_eval_config()).await;

    let flag = context
        .insert_flag(
            team.id,
            Some(flag_row(
                team.id,
                "versioned-flag",
                json!({"groups": [{"rollout_percentage": 100}]}),
            )),
        )
        .await?;

    let mut conn = context.get_non_persons_connection().await?;
    sqlx::query("UPDATE posthog_featureflag SET version = 3 WHERE id = $1")
        .bind(flag.id)
        .execute(&mut *conn)
        .await?;

    // Stale expected_version → 409 with the actual version, and no evaluation happened.
    let res = send_batch_request(
        &server,
        Some(INTERNAL_TOKEN),
        &batch_body(team.id, "versioned-flag", 1),
    )
    .await;
    assert_eq!(res.status(), StatusCode::CONFLICT);
    let json_response = res.json::<Value>().await?;
    assert_eq!(json_response["error"], "version_conflict");
    assert_eq!(json_response["actual_version"], json!(3));

    // Matching expected_version → 200.
    let res = send_batch_request(
        &server,
        Some(INTERNAL_TOKEN),
        &batch_body(team.id, "versioned-flag", 3),
    )
    .await;
    assert_eq!(res.status(), StatusCode::OK);

    Ok(())
}

#[tokio::test]
async fn test_null_expected_version_coerces_to_zero() -> Result<()> {
    let context = TestContext::new(None).await;
    let team = context.insert_new_team(None).await?;
    let server = ServerHandle::for_config(batch_eval_config()).await;

    context
        .insert_flag(
            team.id,
            Some(flag_row(
                team.id,
                "null-version-flag",
                json!({"groups": [{"rollout_percentage": 100}]}),
            )),
        )
        .await?;

    // JSON null and an omitted field both mean "expect version 0", matching a flag
    // whose version column is NULL.
    let null_body = json!({
        "team_id": team.id,
        "flag_key": "null-version-flag",
        "expected_version": null,
    });
    let res = send_batch_request(&server, Some(INTERNAL_TOKEN), &null_body).await;
    assert_eq!(res.status(), StatusCode::OK);

    let omitted_body = json!({
        "team_id": team.id,
        "flag_key": "null-version-flag",
    });
    let res = send_batch_request(&server, Some(INTERNAL_TOKEN), &omitted_body).await;
    assert_eq!(res.status(), StatusCode::OK);

    Ok(())
}

#[tokio::test]
async fn test_property_filter_selects_matching_persons() -> Result<()> {
    // Port of the core matching behavior in test_creating_static_cohort_iterator: persons
    // matching the property filter are included, others are not.
    let context = TestContext::new(None).await;
    let team = context.insert_new_team(None).await?;
    let server = ServerHandle::for_config(batch_eval_config()).await;

    context
        .insert_flag(
            team.id,
            Some(flag_row(
                team.id,
                "property-flag",
                json!({
                    "groups": [{
                        "properties": [{"key": "key", "value": "value", "type": "person"}],
                        "rollout_percentage": 100,
                    }],
                }),
            )),
        )
        .await?;

    for (distinct_id, properties) in [
        ("prop_person1", json!({"key": "value"})),
        ("prop_person2", json!({"key": "value"})),
        ("prop_person3", json!({"key": "other"})),
        ("prop_person4", json!({})),
    ] {
        context
            .insert_person(team.id, distinct_id.to_string(), Some(properties))
            .await?;
    }

    let res = send_batch_request(
        &server,
        Some(INTERNAL_TOKEN),
        &batch_body(team.id, "property-flag", 0),
    )
    .await;
    assert_eq!(res.status(), StatusCode::OK);
    let json_response = res.json::<Value>().await?;

    let mut expected = vec![
        context
            .get_person_uuid_by_distinct_id(team.id, "prop_person1")
            .await?,
        context
            .get_person_uuid_by_distinct_id(team.id, "prop_person2")
            .await?,
    ];
    expected.sort();

    assert_eq!(matched_uuids(&json_response), expected);
    assert_eq!(json_response["errors_count"], json!(0));
    assert_eq!(json_response["next_cursor"], Value::Null);

    Ok(())
}

#[tokio::test]
async fn test_datetime_filter_uses_team_timezone_not_utc() -> Result<()> {
    // Batch eval must interpret naive datetime person values in the team's timezone, the
    // same as live `/flags` evaluation and HogQL/ClickHouse cohort membership. The handler
    // reads `team.timezone` from Postgres server-side; the Django caller sends no timezone.
    //
    // Phoenix is UTC-7 year-round (no DST), so the arithmetic is unambiguous. The filter
    // pins an explicit-UTC instant (12:00Z), while the person value is a naive wall-clock
    // time interpreted in the team timezone:
    //   - In America/Phoenix, "2024-06-01 08:00:00" is 2024-06-01 15:00 UTC → after 12:00Z → matches.
    //   - Under a wrong UTC fallback it would be 08:00 UTC → not after 12:00Z → would NOT match.
    // So this person is matched only if the team timezone is applied.
    let context = TestContext::new(None).await;
    let team = context.insert_new_team(None).await?;
    context
        .update_team_timezone(team.id, "America/Phoenix")
        .await?;
    let server = ServerHandle::for_config(batch_eval_config()).await;

    context
        .insert_flag(
            team.id,
            Some(flag_row(
                team.id,
                "date-flag",
                json!({
                    "groups": [{
                        "properties": [{
                            "key": "signup_date",
                            "type": "person",
                            "value": "2024-06-01T12:00:00Z",
                            "operator": "is_date_after",
                        }],
                        "rollout_percentage": 100,
                    }],
                }),
            )),
        )
        .await?;

    for (distinct_id, signup_date) in [
        // 15:00 UTC in Phoenix → after the filter only because the team tz is applied.
        ("tz_dependent_match", "2024-06-01 08:00:00"),
        // Well before the filter under any timezone → never matches (selection control).
        ("clearly_before", "2020-01-01 00:00:00"),
    ] {
        context
            .insert_person(
                team.id,
                distinct_id.to_string(),
                Some(json!({ "signup_date": signup_date })),
            )
            .await?;
    }

    let res = send_batch_request(
        &server,
        Some(INTERNAL_TOKEN),
        &batch_body(team.id, "date-flag", 0),
    )
    .await;
    assert_eq!(res.status(), StatusCode::OK);
    let json_response = res.json::<Value>().await?;

    let matched = context
        .get_person_uuid_by_distinct_id(team.id, "tz_dependent_match")
        .await?;

    assert_eq!(matched_uuids(&json_response), vec![matched]);
    assert_eq!(json_response["errors_count"], json!(0));
    assert_eq!(json_response["next_cursor"], Value::Null);

    Ok(())
}

#[tokio::test]
async fn test_rollout_percentage_bucketing_matches_live_hash() -> Result<()> {
    // Rollout bucketing must use the same `_hash(key, identifier)` as live evaluation.
    let context = TestContext::new(None).await;
    let team = context.insert_new_team(None).await?;
    let server = ServerHandle::for_config(batch_eval_config()).await;

    let flag_key = "rollout-flag";
    context
        .insert_flag(
            team.id,
            Some(flag_row(
                team.id,
                flag_key,
                json!({"groups": [{"rollout_percentage": 50}]}),
            )),
        )
        .await?;

    let mut expected: Vec<Uuid> = Vec::new();
    let mut expected_out = 0;
    for i in 0..20 {
        let distinct_id = format!("rollout_person_{i}");
        context
            .insert_person(team.id, distinct_id.clone(), Some(json!({})))
            .await?;
        let hash = calculate_hash(&format!("{flag_key}."), &distinct_id, "")?;
        if hash <= 0.5 {
            expected.push(
                context
                    .get_person_uuid_by_distinct_id(team.id, &distinct_id)
                    .await?,
            );
        } else {
            expected_out += 1;
        }
    }
    expected.sort();
    assert!(
        !expected.is_empty() && expected_out > 0,
        "test should exercise both sides of the rollout boundary"
    );

    let res = send_batch_request(
        &server,
        Some(INTERNAL_TOKEN),
        &batch_body(team.id, flag_key, 0),
    )
    .await;
    assert_eq!(res.status(), StatusCode::OK);
    let json_response = res.json::<Value>().await?;

    assert_eq!(matched_uuids(&json_response), expected);
    assert_eq!(json_response["errors_count"], json!(0));

    Ok(())
}

#[tokio::test]
async fn test_cursor_pagination_covers_all_persons() -> Result<()> {
    // Port of test_creating_static_cohort_iterator's batching behavior, now cursor-paged.
    let context = TestContext::new(None).await;
    let team = context.insert_new_team(None).await?;
    let server = ServerHandle::for_config(batch_eval_config()).await;

    context
        .insert_flag(
            team.id,
            Some(flag_row(
                team.id,
                "paging-flag",
                json!({"groups": [{"rollout_percentage": 100}]}),
            )),
        )
        .await?;

    let mut expected: Vec<Uuid> = Vec::new();
    for i in 0..5 {
        let distinct_id = format!("paging_person_{i}");
        context
            .insert_person(team.id, distinct_id.clone(), Some(json!({})))
            .await?;
        expected.push(
            context
                .get_person_uuid_by_distinct_id(team.id, &distinct_id)
                .await?,
        );
    }
    expected.sort();

    let mut collected: Vec<Uuid> = Vec::new();
    let mut cursor: i64 = 0;
    let mut pages = 0;
    loop {
        let mut body = batch_body(team.id, "paging-flag", 0);
        body["cursor"] = json!(cursor);
        body["limit"] = json!(2);
        let res = send_batch_request(&server, Some(INTERNAL_TOKEN), &body).await;
        assert_eq!(res.status(), StatusCode::OK);
        let json_response = res.json::<Value>().await?;
        collected.extend(matched_uuids(&json_response));
        pages += 1;
        assert!(pages <= 4, "pagination should terminate");

        match json_response["next_cursor"].as_i64() {
            Some(next) => {
                assert!(next > cursor, "cursor must advance");
                cursor = next;
            }
            None => break,
        }
    }

    // 5 persons with limit 2 → 3 pages (2 + 2 + 1, last page short-circuits next_cursor).
    assert_eq!(pages, 3);
    collected.sort();
    assert_eq!(collected, expected);

    Ok(())
}

#[tokio::test]
async fn test_person_with_no_distinct_ids_is_skipped() -> Result<()> {
    // Almost-deleted persons (no distinct_ids) are skipped without counting as errors.
    let context = TestContext::new(None).await;
    let team = context.insert_new_team(None).await?;
    let server = ServerHandle::for_config(batch_eval_config()).await;

    context
        .insert_flag(
            team.id,
            Some(flag_row(
                team.id,
                "skip-flag",
                json!({"groups": [{"rollout_percentage": 100}]}),
            )),
        )
        .await?;

    // A person with no posthog_persondistinctid rows at all.
    let orphan_uuid = Uuid::now_v7();
    let mut conn = context.get_persons_connection().await?;
    sqlx::query(
        r#"INSERT INTO posthog_person
           (created_at, properties, properties_last_updated_at, properties_last_operation,
            team_id, is_user_id, is_identified, uuid, version)
           VALUES ('2023-04-05', '{}', '{}', '{}', $1, NULL, true, $2, 0)"#,
    )
    .bind(team.id)
    .bind(orphan_uuid)
    .execute(&mut *conn)
    .await?;
    drop(conn);

    context
        .insert_person(team.id, "normal_person".to_string(), Some(json!({})))
        .await?;

    let res = send_batch_request(
        &server,
        Some(INTERNAL_TOKEN),
        &batch_body(team.id, "skip-flag", 0),
    )
    .await;
    assert_eq!(res.status(), StatusCode::OK);
    let json_response = res.json::<Value>().await?;

    let expected = vec![
        context
            .get_person_uuid_by_distinct_id(team.id, "normal_person")
            .await?,
    ];
    assert_eq!(matched_uuids(&json_response), expected);
    assert_eq!(
        json_response["errors_count"],
        json!(0),
        "skipped persons are not errors"
    );

    Ok(())
}

#[tokio::test]
async fn test_distinct_id_choice_is_deterministic_min_id() -> Result<()> {
    // Evaluation uses the distinct_id with the lowest posthog_persondistinctid.id.
    // For a 50% flag, the outcome must follow the FIRST distinct_id's hash, not the
    // second's.
    let context = TestContext::new(None).await;
    let team = context.insert_new_team(None).await?;
    let server = ServerHandle::for_config(batch_eval_config()).await;

    let flag_key = "deterministic-flag";
    context
        .insert_flag(
            team.id,
            Some(flag_row(
                team.id,
                flag_key,
                json!({"groups": [{"rollout_percentage": 50}]}),
            )),
        )
        .await?;

    // Find a (first, second) distinct_id pair whose hashes land on opposite sides of the
    // rollout boundary, so the test can detect which one was used.
    let salt_prefix = format!("{flag_key}.");
    let (first, second) = (0..10_000)
        .find_map(|i| {
            let first = format!("det_first_{i}");
            let second = format!("det_second_{i}");
            let first_in = calculate_hash(&salt_prefix, &first, "").unwrap() <= 0.5;
            let second_in = calculate_hash(&salt_prefix, &second, "").unwrap() <= 0.5;
            (first_in && !second_in).then_some((first, second))
        })
        .expect("should find a hash pair on opposite sides of the boundary");

    let person_id = context
        .insert_person(team.id, first.clone(), Some(json!({})))
        .await?;
    // Second distinct_id gets a strictly higher posthog_persondistinctid.id.
    let mut conn = context.get_persons_connection().await?;
    sqlx::query(
        "INSERT INTO posthog_persondistinctid (distinct_id, person_id, team_id, version)
         VALUES ($1, $2, $3, 0)",
    )
    .bind(&second)
    .bind(person_id)
    .bind(team.id)
    .execute(&mut *conn)
    .await?;
    drop(conn);

    let res = send_batch_request(
        &server,
        Some(INTERNAL_TOKEN),
        &batch_body(team.id, flag_key, 0),
    )
    .await;
    assert_eq!(res.status(), StatusCode::OK);
    let json_response = res.json::<Value>().await?;

    let person_uuid = context
        .get_person_uuid_by_distinct_id(team.id, &first)
        .await?;
    assert_eq!(
        matched_uuids(&json_response),
        vec![person_uuid],
        "the first (min pd.id) distinct_id hashes inside the rollout, so the person must match"
    );

    Ok(())
}

#[tokio::test]
async fn test_experience_continuity_overrides_read_but_never_written() -> Result<()> {
    // An existing hash key override must be honored (read), and the batch endpoint
    // must never write new overrides (the matcher runs with skip_writes).
    let context = TestContext::new(None).await;
    let team = context.insert_new_team(None).await?;
    let server = ServerHandle::for_config(batch_eval_config()).await;

    let flag_key = "continuity-flag";
    let mut flag = flag_row(
        team.id,
        flag_key,
        json!({"groups": [{"rollout_percentage": 50}]}),
    );
    flag.ensure_experience_continuity = Some(true);
    context.insert_flag(team.id, Some(flag)).await?;

    let salt_prefix = format!("{flag_key}.");
    // A person whose own distinct_id hashes OUT of the rollout, with an override hash key
    // that hashes IN — the override must flip them to matched.
    let overridden = (0..10_000)
        .map(|i| format!("continuity_overridden_{i}"))
        .find(|d| calculate_hash(&salt_prefix, d, "").unwrap() > 0.5)
        .unwrap();
    let override_hash_key = (0..10_000)
        .map(|i| format!("override_key_{i}"))
        .find(|d| calculate_hash(&salt_prefix, d, "").unwrap() <= 0.5)
        .unwrap();
    // A person who'd be out of the rollout with no override — must stay out.
    let plain = (0..10_000)
        .map(|i| format!("continuity_plain_{i}"))
        .find(|d| calculate_hash(&salt_prefix, d, "").unwrap() > 0.5)
        .unwrap();

    let overridden_person_id = context
        .insert_person(team.id, overridden.clone(), Some(json!({})))
        .await?;
    context
        .insert_person(team.id, plain.clone(), Some(json!({})))
        .await?;

    let mut conn = context.get_persons_connection().await?;
    sqlx::query(
        "INSERT INTO posthog_featureflaghashkeyoverride (team_id, person_id, feature_flag_key, hash_key)
         VALUES ($1, $2, $3, $4)",
    )
    .bind(team.id)
    .bind(overridden_person_id)
    .bind(flag_key)
    .bind(&override_hash_key)
    .execute(&mut *conn)
    .await?;
    drop(conn);

    let res = send_batch_request(
        &server,
        Some(INTERNAL_TOKEN),
        &batch_body(team.id, flag_key, 0),
    )
    .await;
    assert_eq!(res.status(), StatusCode::OK);
    let json_response = res.json::<Value>().await?;

    let overridden_uuid = context
        .get_person_uuid_by_distinct_id(team.id, &overridden)
        .await?;
    assert_eq!(
        matched_uuids(&json_response),
        vec![overridden_uuid],
        "the override hash key must flip the overridden person into the rollout"
    );

    // skip_writes: the batch call must not have written any new override rows.
    let mut conn = context.get_persons_connection().await?;
    let override_count: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM posthog_featureflaghashkeyoverride WHERE team_id = $1",
    )
    .bind(team.id)
    .fetch_one(&mut *conn)
    .await?;
    assert_eq!(
        override_count, 1,
        "batch evaluation must never write hash key overrides"
    );

    Ok(())
}

#[tokio::test]
async fn test_static_and_dynamic_cohort_conditions() -> Result<()> {
    // Port of test_creating_static_cohort_with_cohort_flag_adds_cohort_props_as_default_too,
    // with live-evaluation semantics: static cohorts resolve via posthog_cohortpeople,
    // dynamic cohorts evaluate in-memory against person properties.
    let context = TestContext::new(None).await;
    let team = context.insert_new_team(None).await?;
    let server = ServerHandle::for_config(batch_eval_config()).await;

    let static_cohort = context
        .insert_cohort(team.id, None, json!({}), true)
        .await?;
    let dynamic_cohort = context
        .insert_cohort(
            team.id,
            None,
            json!({"properties": {"type": "OR", "values": [{
                "type": "OR",
                "values": [{"key": "plan", "value": "premium", "type": "person"}],
            }]}}),
            false,
        )
        .await?;

    context
        .insert_flag(
            team.id,
            Some(flag_row(
                team.id,
                "cohort-flag",
                json!({
                    "groups": [
                        {
                            "properties": [{"key": "id", "value": static_cohort.id, "type": "cohort"}],
                            "rollout_percentage": 100,
                        },
                        {
                            "properties": [{"key": "id", "value": dynamic_cohort.id, "type": "cohort"}],
                            "rollout_percentage": 100,
                        },
                    ],
                }),
            )),
        )
        .await?;

    // in_static: a member of the static cohort.
    let in_static_id = context
        .insert_person(team.id, "cohort_in_static".to_string(), Some(json!({})))
        .await?;
    context
        .add_person_to_cohort(static_cohort.id, in_static_id)
        .await?;
    // in_dynamic: matches the dynamic cohort's property filter.
    context
        .insert_person(
            team.id,
            "cohort_in_dynamic".to_string(),
            Some(json!({"plan": "premium"})),
        )
        .await?;
    // outsider: in neither cohort.
    context
        .insert_person(
            team.id,
            "cohort_outsider".to_string(),
            Some(json!({"plan": "free"})),
        )
        .await?;

    let res = send_batch_request(
        &server,
        Some(INTERNAL_TOKEN),
        &batch_body(team.id, "cohort-flag", 0),
    )
    .await;
    assert_eq!(res.status(), StatusCode::OK);
    let json_response = res.json::<Value>().await?;

    let mut expected = vec![
        context
            .get_person_uuid_by_distinct_id(team.id, "cohort_in_static")
            .await?,
        context
            .get_person_uuid_by_distinct_id(team.id, "cohort_in_dynamic")
            .await?,
    ];
    expected.sort();

    assert_eq!(matched_uuids(&json_response), expected);
    assert_eq!(json_response["errors_count"], json!(0));

    Ok(())
}

#[tokio::test]
async fn test_missing_property_negative_operator_uses_live_semantics() -> Result<()> {
    // Live Rust evaluation explicitly treats a missing property as matching `is_not`
    // (see the IsNot arm of `match_property`). The batch endpoint must follow live:
    // a person missing the property still matches `is_not`.
    let context = TestContext::new(None).await;
    let team = context.insert_new_team(None).await?;
    let server = ServerHandle::for_config(batch_eval_config()).await;

    context
        .insert_flag(
            team.id,
            Some(flag_row(
                team.id,
                "negation-flag",
                json!({
                    "groups": [{
                        "properties": [{"key": "key", "value": "value", "type": "person", "operator": "is_not"}],
                        "rollout_percentage": 100,
                    }],
                }),
            )),
        )
        .await?;

    context
        .insert_person(
            team.id,
            "neg_has_other_value".to_string(),
            Some(json!({"key": "other"})),
        )
        .await?;
    context
        .insert_person(team.id, "neg_missing_property".to_string(), Some(json!({})))
        .await?;

    let res = send_batch_request(
        &server,
        Some(INTERNAL_TOKEN),
        &batch_body(team.id, "negation-flag", 0),
    )
    .await;
    assert_eq!(res.status(), StatusCode::OK);
    let json_response = res.json::<Value>().await?;

    let mut expected = vec![
        context
            .get_person_uuid_by_distinct_id(team.id, "neg_has_other_value")
            .await?,
        context
            .get_person_uuid_by_distinct_id(team.id, "neg_missing_property")
            .await?,
    ];
    expected.sort();
    assert_eq!(
        matched_uuids(&json_response),
        expected,
        "a person missing the property must match is_not, like live evaluation does"
    );

    Ok(())
}

#[tokio::test]
async fn test_multivariate_flag_variants_count_as_matched() -> Result<()> {
    // Cohort membership is "does the live flag match", regardless of which variant.
    let context = TestContext::new(None).await;
    let team = context.insert_new_team(None).await?;
    let server = ServerHandle::for_config(batch_eval_config()).await;

    context
        .insert_flag(
            team.id,
            Some(flag_row(
                team.id,
                "multivariate-flag",
                json!({
                    "groups": [{"rollout_percentage": 100}],
                    "multivariate": {
                        "variants": [
                            {"key": "control", "rollout_percentage": 50},
                            {"key": "test", "rollout_percentage": 50},
                        ],
                    },
                }),
            )),
        )
        .await?;

    let mut expected = Vec::new();
    for i in 0..4 {
        let distinct_id = format!("variant_person_{i}");
        context
            .insert_person(team.id, distinct_id.clone(), Some(json!({})))
            .await?;
        expected.push(
            context
                .get_person_uuid_by_distinct_id(team.id, &distinct_id)
                .await?,
        );
    }
    expected.sort();

    let res = send_batch_request(
        &server,
        Some(INTERNAL_TOKEN),
        &batch_body(team.id, "multivariate-flag", 0),
    )
    .await;
    assert_eq!(res.status(), StatusCode::OK);
    let json_response = res.json::<Value>().await?;

    assert_eq!(matched_uuids(&json_response), expected);

    Ok(())
}

#[tokio::test]
async fn test_no_flag_analytics_emitted_for_batch_requests() -> Result<()> {
    // The batch handler bypasses the /flags pipeline by construction (no billing, no
    // flag analytics); this test pins that so a refactor can't silently reintroduce it.
    use feature_flags::flags::flag_analytics::{current_bucket, get_team_request_key};
    use feature_flags::flags::flag_request::FlagRequestType;
    use feature_flags::utils::test_utils::setup_redis_client;

    let context = TestContext::new(None).await;
    let team = context.insert_new_team(None).await?;
    let server = ServerHandle::for_config(batch_eval_config()).await;

    context
        .insert_flag(
            team.id,
            Some(flag_row(
                team.id,
                "analytics-flag",
                json!({"groups": [{"rollout_percentage": 100}]}),
            )),
        )
        .await?;
    context
        .insert_person(
            team.id,
            random_string("analytics_person", 8),
            Some(json!({})),
        )
        .await?;

    let res = send_batch_request(
        &server,
        Some(INTERNAL_TOKEN),
        &batch_body(team.id, "analytics-flag", 0),
    )
    .await;
    assert_eq!(res.status(), StatusCode::OK);

    let redis_client = setup_redis_client(None).await;
    for request_type in [FlagRequestType::Decide, FlagRequestType::FlagDefinitions] {
        let key = get_team_request_key(team.id, request_type);
        let bucket = current_bucket();
        // Billing aggregator keys are `<team_key>:<bucket>`; analytics counters use the
        // same keyspace. Neither must exist after a batch-only workload.
        for candidate in [key.clone(), format!("{key}:{bucket}")] {
            let value = redis_client.get(candidate.clone()).await;
            assert!(
                value.is_err(),
                "no analytics/billing key should exist for batch requests, found {candidate}"
            );
        }
    }

    Ok(())
}

#[tokio::test]
async fn test_batch_results_match_live_flags_evaluation() -> Result<()> {
    // The contract for static cohort generation is "cohort membership = who the live
    // flag matches". Evaluate the same flag for the same persons via the live /flags
    // endpoint and via the batch endpoint, and require identical outcomes.
    let context = TestContext::new(None).await;
    let team = context.insert_new_team(None).await?;
    // Mock redis validates the team token for the live path; flags are only in PG, so
    // both the live path (PG fallback) and the batch path read the same definitions.
    let server = ServerHandle::for_config_with_mock_redis(
        batch_eval_config(),
        vec![],
        vec![(team.api_token.clone(), team.id)],
    )
    .await;

    let flag_key = "parity-flag";
    context
        .insert_flag(
            team.id,
            Some(flag_row(
                team.id,
                flag_key,
                json!({
                    "groups": [{
                        "properties": [{"key": "plan", "value": "premium", "type": "person"}],
                        "rollout_percentage": 50,
                    }],
                }),
            )),
        )
        .await?;

    // Pick distinct_ids whose rollout hashes are known to land on both sides of the 50%
    // boundary, so the test deterministically exercises matched and unmatched persons.
    let salt_prefix = format!("{flag_key}.");
    let mut in_rollout_ids = (0..10_000)
        .map(|i| format!("parity_in_{i}"))
        .filter(|d| calculate_hash(&salt_prefix, d, "").unwrap() <= 0.5);
    let mut out_of_rollout_ids = (0..10_000)
        .map(|i| format!("parity_out_{i}"))
        .filter(|d| calculate_hash(&salt_prefix, d, "").unwrap() > 0.5);
    let persons = [
        (in_rollout_ids.next().unwrap(), json!({"plan": "premium"})),
        (in_rollout_ids.next().unwrap(), json!({"plan": "premium"})),
        (
            out_of_rollout_ids.next().unwrap(),
            json!({"plan": "premium"}),
        ),
        (in_rollout_ids.next().unwrap(), json!({"plan": "free"})),
        (out_of_rollout_ids.next().unwrap(), json!({"plan": "free"})),
    ];

    let mut live_matched: Vec<Uuid> = Vec::new();
    for (distinct_id, properties) in persons {
        context
            .insert_person(team.id, distinct_id.clone(), Some(properties))
            .await?;

        let live_response = server
            .send_flags_request(
                json!({"token": team.api_token, "distinct_id": distinct_id}).to_string(),
                Some("2"),
                None,
            )
            .await;
        assert_eq!(live_response.status(), StatusCode::OK);
        let live_json = live_response.json::<Value>().await?;
        if live_json["flags"][flag_key]["enabled"] == json!(true) {
            live_matched.push(
                context
                    .get_person_uuid_by_distinct_id(team.id, &distinct_id)
                    .await?,
            );
        }
    }
    live_matched.sort();
    assert_eq!(
        live_matched.len(),
        2,
        "exactly the two premium persons inside the rollout should match live"
    );

    let res = send_batch_request(
        &server,
        Some(INTERNAL_TOKEN),
        &batch_body(team.id, flag_key, 0),
    )
    .await;
    assert_eq!(res.status(), StatusCode::OK);
    let json_response = res.json::<Value>().await?;

    assert_eq!(
        matched_uuids(&json_response),
        live_matched,
        "batch evaluation must match live /flags evaluation exactly"
    );
    assert_eq!(json_response["errors_count"], json!(0));

    Ok(())
}
