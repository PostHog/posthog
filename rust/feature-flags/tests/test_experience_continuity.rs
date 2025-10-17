use anyhow::Result;
use reqwest::StatusCode;
use serde_json::{json, Value};

pub mod common;
use crate::common::ServerHandle;
use feature_flags::config::DEFAULT_TEST_CONFIG;
use feature_flags::flags::flag_models::FeatureFlagRow;
use feature_flags::utils::test_utils::TestContext;

#[tokio::test]
async fn test_experience_continuity_matches_python() -> Result<()> {
    // 1. Create a user that evaluates to false
    // 2. Find an ID that evaluates to true
    // 3. Set hash key override via $anon_distinct_id
    // 4. Call WITHOUT $anon_distinct_id - should maintain the override

    // Insert a new team
    let context = TestContext::new(None).await;
    let team = context
        .insert_new_team(None)
        .await
        .expect("Failed to insert team");

    // Create a flag with experience continuity (50% rollout like the real experience-flag)
    let flag_row = FeatureFlagRow {
        id: 100,
        team_id: team.id,
        name: Some("Experience Flag".to_string()),
        key: "experience-flag-test".to_string(),
        filters: json!({
            "groups": [{"rollout_percentage": 50}]
        }),
        deleted: false,
        active: true,
        ensure_experience_continuity: Some(true),
        version: Some(1),
        evaluation_runtime: None,
        evaluation_tags: None,
    };
    context.insert_flag(team.id, Some(flag_row)).await?;

    // Create a person with false_eval_user (this ID evaluates to false for 50% rollout)
    let user_id = "false_eval_user";
    context
        .insert_person(
            team.id,
            user_id.to_string(),
            Some(json!({"email": "false_eval_user@example.com", "name": "Test User"})),
        )
        .await?;

    // Start test server
    let config = DEFAULT_TEST_CONFIG.clone();
    let server = ServerHandle::for_config_with_mock_redis(
        config,
        vec![],
        vec![(team.api_token.clone(), team.id)],
    )
    .await;

    // Step 1: Check initial evaluation (should be false)
    let payload = json!({
        "token": team.api_token,
        "distinct_id": user_id,
    });

    let res = server
        .send_flags_request(payload.to_string(), Some("2"), None)
        .await;
    assert_eq!(res.status(), StatusCode::OK);
    let json = res.json::<Value>().await?;

    assert_eq!(
        json["flags"]["experience-flag-test"]["enabled"],
        json!(false),
        "false_eval_user should initially evaluate to false"
    );

    // Step 2: Use an ID that evaluates to true
    let anon_id = "true_eval_user";
    let anon_payload = json!({
        "token": team.api_token,
        "distinct_id": anon_id,
    });

    let anon_res = server
        .send_flags_request(anon_payload.to_string(), Some("2"), None)
        .await;
    assert_eq!(anon_res.status(), StatusCode::OK);
    let anon_json = anon_res.json::<Value>().await?;

    assert_eq!(
        anon_json["flags"]["experience-flag-test"]["enabled"],
        json!(true),
        "true_eval_user should evaluate to true"
    );

    // Step 3: Set the hash key override by calling with $anon_distinct_id
    let override_payload = json!({
        "token": team.api_token,
        "distinct_id": user_id,
        "$anon_distinct_id": anon_id,
    });

    let override_res = server
        .send_flags_request(override_payload.to_string(), Some("2"), None)
        .await;
    assert_eq!(override_res.status(), StatusCode::OK);
    let override_json = override_res.json::<Value>().await?;

    assert_eq!(
        override_json["flags"]["experience-flag-test"]["enabled"],
        json!(true),
        "With $anon_distinct_id, should now evaluate to true"
    );

    // Step 4: Call WITHOUT $anon_distinct_id
    let final_payload = json!({
        "token": team.api_token,
        "distinct_id": user_id,
        // NO $anon_distinct_id
    });

    let final_res = server
        .send_flags_request(final_payload.to_string(), Some("2"), None)
        .await;
    assert_eq!(final_res.status(), StatusCode::OK);
    let final_json = final_res.json::<Value>().await?;

    assert_eq!(
        final_json["flags"]["experience-flag-test"]["enabled"],
        json!(true),
        "WITHOUT $anon_distinct_id, should STILL return true due to existing override (matching Python)"
    );

    Ok(())
}

#[tokio::test]
async fn test_experience_continuity_with_merge() -> Result<()> {
    // Test that merged persons also maintain overrides without $anon_distinct_id

    let context = TestContext::new(None).await;
    let team = context
        .insert_new_team(None)
        .await
        .expect("Failed to insert team");

    // Create flag
    let flag_row = FeatureFlagRow {
        id: 101,
        team_id: team.id,
        name: Some("Merge Test Flag".to_string()),
        key: "merge-test-flag".to_string(),
        filters: json!({
            "groups": [{"rollout_percentage": 50}]
        }),
        deleted: false,
        active: true,
        ensure_experience_continuity: Some(true),
        version: Some(1),
        evaluation_runtime: None,
        evaluation_tags: None,
    };
    context.insert_flag(team.id, Some(flag_row)).await?;

    // Create initial person with an ID that evaluates to false
    let initial_id = "false_eval_initial";
    let person_id = context
        .insert_person(
            team.id,
            initial_id.to_string(),
            Some(json!({"email": "initial@example.com"})),
        )
        .await?;

    // Start server
    let config = DEFAULT_TEST_CONFIG.clone();
    let server = ServerHandle::for_config_with_mock_redis(
        config,
        vec![],
        vec![(team.api_token.clone(), team.id)],
    )
    .await;

    // Step 1: Verify initial_id evaluates to false
    let initial_check = json!({
        "token": team.api_token,
        "distinct_id": initial_id,
    });

    let initial_res = server
        .send_flags_request(initial_check.to_string(), Some("2"), None)
        .await;
    assert_eq!(initial_res.status(), StatusCode::OK);
    let initial_json = initial_res.json::<Value>().await?;

    assert_eq!(
        initial_json["flags"]["merge-test-flag"]["enabled"],
        json!(false),
        "Initial user should evaluate to false"
    );

    // Step 2: Use an anonymous ID that evaluates to true
    let anon_id = "true_eval_anon";
    let anon_check = json!({
        "token": team.api_token,
        "distinct_id": anon_id,
    });

    let anon_res = server
        .send_flags_request(anon_check.to_string(), Some("2"), None)
        .await;
    assert_eq!(anon_res.status(), StatusCode::OK);
    let anon_json = anon_res.json::<Value>().await?;

    assert_eq!(
        anon_json["flags"]["merge-test-flag"]["enabled"],
        json!(true),
        "Anonymous ID should evaluate to true"
    );

    // Step 3: Set override via $anon_distinct_id
    let override_payload = json!({
        "token": team.api_token,
        "distinct_id": initial_id,
        "$anon_distinct_id": anon_id,
    });

    let override_res = server
        .send_flags_request(override_payload.to_string(), Some("2"), None)
        .await;
    assert_eq!(override_res.status(), StatusCode::OK);
    let override_json = override_res.json::<Value>().await?;

    assert_eq!(
        override_json["flags"]["merge-test-flag"]["enabled"],
        json!(true),
        "After setting override, should evaluate to true"
    );

    // Step 4: First verify that the merged_id would naturally evaluate to false
    let merged_id = "false_eval_merged_user";

    // Test that this ID naturally evaluates to false (before any association)
    let natural_check = json!({
        "token": team.api_token,
        "distinct_id": merged_id,
    });

    let natural_res = server
        .send_flags_request(natural_check.to_string(), Some("2"), None)
        .await;
    assert_eq!(natural_res.status(), StatusCode::OK);
    let natural_json = natural_res.json::<Value>().await?;

    assert_eq!(
        natural_json["flags"]["merge-test-flag"]["enabled"],
        json!(false),
        "merged_id should naturally evaluate to false before association"
    );

    // Step 5: Simulate a person merge (this would normally happen via $identify event)
    // Use an ID that would naturally evaluate to false to prove the override is working
    let mut conn = context.get_persons_connection().await?;
    sqlx::query(
        "INSERT INTO posthog_persondistinctid (team_id, person_id, distinct_id, version)
         VALUES ($1, $2, $3, 0)",
    )
    .bind(team.id)
    .bind(person_id)
    .bind(merged_id)
    .execute(&mut *conn)
    .await?;

    // Step 6: Call with merged ID without $anon_distinct_id
    // This is the key test - the merged ID should inherit the override
    let merged_payload = json!({
        "token": team.api_token,
        "distinct_id": merged_id,
        // NO $anon_distinct_id
    });

    let res = server
        .send_flags_request(merged_payload.to_string(), Some("2"), None)
        .await;

    assert_eq!(res.status(), StatusCode::OK);
    let json = res.json::<Value>().await?;

    assert_eq!(
        json["flags"]["merge-test-flag"]["enabled"],
        json!(true),
        "Merged distinct_id should use existing override without $anon_distinct_id (inherits from the person's existing override)"
    );

    Ok(())
}

#[tokio::test]
async fn test_anon_distinct_id_from_person_properties() -> Result<()> {
    let context = TestContext::new(None).await;
    let team = context
        .insert_new_team(None)
        .await
        .expect("Failed to insert team");

    // Create flag with experience continuity
    let flag_row = FeatureFlagRow {
        id: 102,
        team_id: team.id,
        name: Some("Experience Flag".to_string()),
        key: "experience-flag-test".to_string(),
        filters: json!({
            "groups": [{"rollout_percentage": 50}]
        }),
        deleted: false,
        active: true,
        ensure_experience_continuity: Some(true),
        version: Some(1),
        evaluation_runtime: None,
        evaluation_tags: None,
    };
    context.insert_flag(team.id, Some(flag_row)).await?;

    // Create person with an ID that evaluates to false
    let user_id = "false_eval_user";
    context
        .insert_person(
            team.id,
            user_id.to_string(),
            Some(json!({"email": "false_eval_user@example.com"})),
        )
        .await?;

    let config = DEFAULT_TEST_CONFIG.clone();
    let server = ServerHandle::for_config_with_mock_redis(
        config,
        vec![],
        vec![(team.api_token.clone(), team.id)],
    )
    .await;

    // Step 1: Verify user evaluates to false
    let initial_payload = json!({
        "token": team.api_token,
        "distinct_id": user_id,
    });

    let res = server
        .send_flags_request(initial_payload.to_string(), Some("2"), None)
        .await;
    assert_eq!(res.status(), StatusCode::OK);
    let json_response = res.json::<Value>().await?;

    assert_eq!(
        json_response["flags"]["experience-flag-test"]["enabled"],
        json!(false),
        "User should initially evaluate to false"
    );

    // Step 2: Verify the anon ID evaluates to true
    let anon_id = "true_eval_user";
    let anon_payload = json!({
        "token": team.api_token,
        "distinct_id": anon_id,
    });

    let anon_res = server
        .send_flags_request(anon_payload.to_string(), Some("2"), None)
        .await;
    assert_eq!(anon_res.status(), StatusCode::OK);
    let anon_json = anon_res.json::<Value>().await?;

    assert_eq!(
        anon_json["flags"]["experience-flag-test"]["enabled"],
        json!(true),
        "true_eval_user should evaluate to true"
    );

    // Step 3: Set override using $anon_distinct_id in person_properties
    let override_payload = json!({
        "token": team.api_token,
        "distinct_id": user_id,
        "person_properties": {
            "$anon_distinct_id": anon_id,
            "other_prop": "some_value"
        }
    });

    let override_res = server
        .send_flags_request(override_payload.to_string(), Some("2"), None)
        .await;
    assert_eq!(override_res.status(), StatusCode::OK);
    let override_json = override_res.json::<Value>().await?;

    assert_eq!(
        override_json["flags"]["experience-flag-test"]["enabled"],
        json!(true),
        "With $anon_distinct_id in person_properties, should evaluate to true"
    );

    // Step 4: Verify override persists without $anon_distinct_id
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
        final_json["flags"]["experience-flag-test"]["enabled"],
        json!(true),
        "Override should persist even without $anon_distinct_id"
    );

    Ok(())
}

#[tokio::test]
async fn test_top_level_anon_distinct_id_takes_precedence() -> Result<()> {
    let context = TestContext::new(None).await;
    let team = context
        .insert_new_team(None)
        .await
        .expect("Failed to insert team");

    // Create flag
    let flag_row = FeatureFlagRow {
        id: 103,
        team_id: team.id,
        name: Some("Experience Flag".to_string()),
        key: "experience-flag-test".to_string(),
        filters: json!({
            "groups": [{"rollout_percentage": 50}]
        }),
        deleted: false,
        active: true,
        ensure_experience_continuity: Some(true),
        version: Some(1),
        evaluation_runtime: None,
        evaluation_tags: None,
    };
    context.insert_flag(team.id, Some(flag_row)).await?;

    // Create person
    let user_id = "precedence_test_user";
    context
        .insert_person(
            team.id,
            user_id.to_string(),
            Some(json!({"email": "precedence@example.com"})),
        )
        .await?;

    let config = DEFAULT_TEST_CONFIG.clone();
    let server = ServerHandle::for_config_with_mock_redis(
        config,
        vec![],
        vec![(team.api_token.clone(), team.id)],
    )
    .await;

    // Use two different IDs that evaluate differently
    let true_eval_id = "true_eval_user";
    let false_eval_id = "false_eval_user";

    // Verify the true_eval_id evaluates to true
    let true_check = json!({
        "token": team.api_token,
        "distinct_id": true_eval_id,
    });

    let true_res = server
        .send_flags_request(true_check.to_string(), Some("2"), None)
        .await;
    assert_eq!(true_res.status(), StatusCode::OK);
    let true_json = true_res.json::<Value>().await?;

    assert_eq!(
        true_json["flags"]["experience-flag-test"]["enabled"],
        json!(true),
        "true_eval_id should evaluate to true"
    );

    // Verify the false_eval_id evaluates to false
    let false_check = json!({
        "token": team.api_token,
        "distinct_id": false_eval_id,
    });

    let false_res = server
        .send_flags_request(false_check.to_string(), Some("2"), None)
        .await;
    assert_eq!(false_res.status(), StatusCode::OK);
    let false_json = false_res.json::<Value>().await?;

    assert_eq!(
        false_json["flags"]["experience-flag-test"]["enabled"],
        json!(false),
        "false_eval_id should evaluate to false"
    );

    // Test with BOTH top-level and person_properties $anon_distinct_id
    // Top-level should win
    let payload_with_both = json!({
        "token": team.api_token,
        "distinct_id": user_id,
        "$anon_distinct_id": true_eval_id,  // Top level - evaluates to TRUE
        "person_properties": {
            "$anon_distinct_id": false_eval_id,  // In person_properties - evaluates to FALSE
        }
    });

    let res = server
        .send_flags_request(payload_with_both.to_string(), Some("2"), None)
        .await;
    assert_eq!(res.status(), StatusCode::OK);
    let json_response = res.json::<Value>().await?;

    assert_eq!(
        json_response["flags"]["experience-flag-test"]["enabled"],
        json!(true),
        "Top-level $anon_distinct_id should take precedence (evaluates to true)"
    );

    Ok(())
}
