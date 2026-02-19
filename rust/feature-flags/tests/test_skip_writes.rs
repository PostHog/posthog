use anyhow::Result;
use reqwest::StatusCode;
use serde_json::{json, Value};

pub mod common;
use crate::common::ServerHandle;
use feature_flags::config::{FlexBool, DEFAULT_TEST_CONFIG};
use feature_flags::flags::flag_models::FeatureFlagRow;
use feature_flags::utils::test_utils::TestContext;

#[tokio::test]
async fn test_skip_writes_prevents_hash_key_override_write() -> Result<()> {
    // With SKIP_WRITES=true, sending $anon_distinct_id should NOT persist a hash key override.
    // A subsequent request without $anon_distinct_id should fall back to the distinct_id,
    // meaning the override was never written.

    let context = TestContext::new(None).await;
    let team = context
        .insert_new_team(None)
        .await
        .expect("Failed to insert team");

    let flag_row = FeatureFlagRow {
        id: 200,
        team_id: team.id,
        name: Some("Skip Writes EEC Flag".to_string()),
        key: "skip-writes-eec-flag".to_string(),
        filters: json!({
            "groups": [{"rollout_percentage": 50}]
        }),
        deleted: false,
        active: true,
        ensure_experience_continuity: Some(true),
        version: Some(1),
        evaluation_runtime: None,
        evaluation_tags: None,
        bucketing_identifier: None,
    };
    context.insert_flag(team.id, Some(flag_row)).await?;

    let user_id = "false_eval_user";
    context
        .insert_person(
            team.id,
            user_id.to_string(),
            Some(json!({"email": "false_eval_user@example.com"})),
        )
        .await?;

    let mut config = DEFAULT_TEST_CONFIG.clone();
    config.skip_writes = FlexBool(true);
    let server = ServerHandle::for_config_with_mock_redis(
        config,
        vec![],
        vec![(team.api_token.clone(), team.id)],
    )
    .await;

    // Step 1: Verify the user evaluates to false without override
    let initial_payload = json!({
        "token": team.api_token,
        "distinct_id": user_id,
    });

    let initial_res = server
        .send_flags_request(initial_payload.to_string(), Some("2"), None)
        .await;
    assert_eq!(initial_res.status(), StatusCode::OK);
    let initial_json = initial_res.json::<Value>().await?;
    let initial_value = initial_json["flags"]["skip-writes-eec-flag"]["enabled"].clone();

    // Step 2: Send a request WITH $anon_distinct_id (would normally write the override)
    let anon_id = "true_eval_user";
    let override_payload = json!({
        "token": team.api_token,
        "distinct_id": user_id,
        "$anon_distinct_id": anon_id,
    });

    let override_res = server
        .send_flags_request(override_payload.to_string(), Some("2"), None)
        .await;
    assert_eq!(override_res.status(), StatusCode::OK);

    // Step 3: Send request WITHOUT $anon_distinct_id again.
    // If the write was skipped, we should get the same result as Step 1
    // (the override should not have been persisted).
    let final_payload = json!({
        "token": team.api_token,
        "distinct_id": user_id,
    });

    let final_res = server
        .send_flags_request(final_payload.to_string(), Some("2"), None)
        .await;
    assert_eq!(final_res.status(), StatusCode::OK);
    let final_json = final_res.json::<Value>().await?;

    assert_eq!(
        final_json["flags"]["skip-writes-eec-flag"]["enabled"], initial_value,
        "With SKIP_WRITES=true, the hash key override should not have been persisted. \
         The final evaluation should match the initial evaluation (no override in DB)."
    );

    // Step 4: Verify the posthog_featureflaghashkeyoverride table has no rows for this team
    let mut conn = context.get_persons_connection().await?;
    let row_count: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM posthog_featureflaghashkeyoverride WHERE team_id = $1")
            .bind(team.id)
            .fetch_one(&mut *conn)
            .await?;

    assert_eq!(
        row_count, 0,
        "No hash key overrides should be written when SKIP_WRITES=true"
    );

    Ok(())
}

#[tokio::test]
async fn test_skip_writes_still_evaluates_flags_correctly() -> Result<()> {
    // SKIP_WRITES should not affect flag evaluation results - only writes.

    let context = TestContext::new(None).await;
    let team = context
        .insert_new_team(None)
        .await
        .expect("Failed to insert team");

    let flag_row = FeatureFlagRow {
        id: 201,
        team_id: team.id,
        name: Some("Simple Flag".to_string()),
        key: "simple-flag".to_string(),
        filters: json!({
            "groups": [{"rollout_percentage": 100}]
        }),
        deleted: false,
        active: true,
        ensure_experience_continuity: Some(false),
        version: Some(1),
        evaluation_runtime: None,
        evaluation_tags: None,
        bucketing_identifier: None,
    };
    context.insert_flag(team.id, Some(flag_row)).await?;

    let mut config = DEFAULT_TEST_CONFIG.clone();
    config.skip_writes = FlexBool(true);
    let server = ServerHandle::for_config_with_mock_redis(
        config,
        vec![],
        vec![(team.api_token.clone(), team.id)],
    )
    .await;

    let payload = json!({
        "token": team.api_token,
        "distinct_id": "test_user",
    });

    let res = server
        .send_flags_request(payload.to_string(), Some("2"), None)
        .await;
    assert_eq!(res.status(), StatusCode::OK);
    let json_response = res.json::<Value>().await?;

    assert_eq!(
        json_response["flags"]["simple-flag"]["enabled"],
        json!(true),
        "A 100% rollout flag should still evaluate to true with SKIP_WRITES enabled"
    );

    Ok(())
}
