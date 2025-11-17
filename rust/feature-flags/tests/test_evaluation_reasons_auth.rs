use anyhow::Result;
use reqwest::StatusCode;
use serde_json::json;

use crate::common::*;
use feature_flags::config::DEFAULT_TEST_CONFIG;
use feature_flags::utils::test_utils::{
    insert_flags_for_team_in_redis, insert_new_team_in_redis, setup_redis_client, TestContext,
};

pub mod common;

/// Tests that a personal API key from User A cannot access Team B if User A is not a member of Team B's organization
#[tokio::test]
async fn test_personal_api_key_cannot_access_other_org_team() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let distinct_id = "test_user".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let context = TestContext::new(None).await;

    // Create two separate organizations
    let org_a_id = uuid::Uuid::new_v4();
    let org_b_id = uuid::Uuid::new_v4();

    // Create team in org A
    let team_a = context
        .insert_new_team_with_org(None, &org_a_id.to_string())
        .await?;

    // Create team in org B
    let team_b = context
        .insert_new_team_with_org(None, &org_b_id.to_string())
        .await?;

    // Insert team B into Redis so it can be looked up by token
    let redis_team_b = insert_new_team_in_redis(client.clone()).await?;

    // Create user in org A only
    let user_a = context
        .create_user("user_a@test.com", &org_a_id, team_a.id)
        .await?;

    // Add user A to organization A
    context
        .add_user_to_organization(user_a, &org_a_id, 15)
        .await?;

    // Create personal API key for user A
    let (_pak_id, api_key_value) = context
        .create_personal_api_key(user_a, "test-key", vec!["feature_flag:read"], None, None)
        .await?;

    // Insert a flag for team B
    let flag_json = json!([{
        "id": 1,
        "key": "test-flag-org-b",
        "name": "Test Flag Org B",
        "active": true,
        "deleted": false,
        "team_id": team_b.id,
        "filters": {
            "groups": [{
                "properties": [],
                "rollout_percentage": 100
            }]
        },
    }]);

    insert_flags_for_team_in_redis(
        client,
        team_b.id,
        team_b.project_id(),
        Some(flag_json.to_string()),
    )
    .await?;

    let server = ServerHandle::for_config(config).await;

    // Attempt to access team B's flags with user A's API key (should fail)
    let response = reqwest::Client::new()
        .get(format!(
            "http://{}/evaluation_reasons?token={}&distinct_id={distinct_id}",
            server.addr, redis_team_b.api_token
        ))
        .header("Authorization", format!("Bearer {api_key_value}"))
        .send()
        .await?;

    // Should be forbidden because user A is not a member of org B
    assert_eq!(response.status(), StatusCode::UNAUTHORIZED);

    Ok(())
}

/// Tests that scoped_organizations on personal API keys is properly enforced
#[tokio::test]
async fn test_scoped_organizations_restriction() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let distinct_id = "test_user".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let context = TestContext::new(None).await;

    // Create two organizations
    let org_a_id = uuid::Uuid::new_v4();
    let org_b_id = uuid::Uuid::new_v4();

    // Create teams in both orgs
    let team_a = context
        .insert_new_team_with_org(None, &org_a_id.to_string())
        .await?;
    let team_b = context
        .insert_new_team_with_org(None, &org_b_id.to_string())
        .await?;

    // Insert team B into Redis
    let redis_team_b = insert_new_team_in_redis(client.clone()).await?;

    // Create user who is member of BOTH organizations
    let user = context
        .create_user("user@test.com", &org_a_id, team_a.id)
        .await?;
    context
        .add_user_to_organization(user, &org_a_id, 15)
        .await?;
    context
        .add_user_to_organization(user, &org_b_id, 15)
        .await?;

    // Create API key scoped to only org A
    let (_pak_id, api_key_value) = context
        .create_personal_api_key(
            user,
            "scoped-key",
            vec!["feature_flag:read"],
            None,
            Some(vec![org_a_id.to_string()]),
        )
        .await?;

    // Insert a flag for team B
    let flag_json = json!([{
        "id": 1,
        "key": "test-flag-org-b",
        "name": "Test Flag Org B",
        "active": true,
        "deleted": false,
        "team_id": team_b.id,
        "filters": {
            "groups": [{
                "properties": [],
                "rollout_percentage": 100
            }]
        },
    }]);

    insert_flags_for_team_in_redis(
        client,
        team_b.id,
        team_b.project_id(),
        Some(flag_json.to_string()),
    )
    .await?;

    let server = ServerHandle::for_config(config).await;

    // Should fail even though user is member of org_b, because API key is scoped to org_a
    let response = reqwest::Client::new()
        .get(format!(
            "http://{}/evaluation_reasons?token={}&distinct_id={distinct_id}",
            server.addr, redis_team_b.api_token
        ))
        .header("Authorization", format!("Bearer {api_key_value}"))
        .send()
        .await?;

    assert_eq!(response.status(), StatusCode::UNAUTHORIZED);

    Ok(())
}

/// Tests that scoped_teams combined with organization membership works correctly
#[tokio::test]
async fn test_scoped_teams_requires_org_membership() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let distinct_id = "test_user".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let context = TestContext::new(None).await;

    // Create one organization
    let org_id = uuid::Uuid::new_v4();

    // Create two teams in the same org
    let team_a = context
        .insert_new_team_with_org(None, &org_id.to_string())
        .await?;
    let team_b = context
        .insert_new_team_with_org(None, &org_id.to_string())
        .await?;

    // Insert teams into Redis
    let redis_team_a = insert_new_team_in_redis(client.clone()).await?;
    let redis_team_b = insert_new_team_in_redis(client.clone()).await?;

    // Create user who is member of the organization
    let user = context
        .create_user("user@test.com", &org_id, team_a.id)
        .await?;
    context.add_user_to_organization(user, &org_id, 15).await?;

    // Create API key scoped to only team_a
    let (_pak_id, api_key_value) = context
        .create_personal_api_key(
            user,
            "team-scoped-key",
            vec!["feature_flag:read"],
            Some(vec![team_a.id]),
            None,
        )
        .await?;

    // Insert flags for both teams
    let flag_json_a = json!([{
        "id": 1,
        "key": "test-flag-team-a",
        "name": "Test Flag Team A",
        "active": true,
        "deleted": false,
        "team_id": team_a.id,
        "filters": {
            "groups": [{
                "properties": [],
                "rollout_percentage": 100
            }]
        },
    }]);

    let flag_json_b = json!([{
        "id": 2,
        "key": "test-flag-team-b",
        "name": "Test Flag Team B",
        "active": true,
        "deleted": false,
        "team_id": team_b.id,
        "filters": {
            "groups": [{
                "properties": [],
                "rollout_percentage": 100
            }]
        },
    }]);

    insert_flags_for_team_in_redis(
        client.clone(),
        team_a.id,
        team_a.project_id(),
        Some(flag_json_a.to_string()),
    )
    .await?;

    insert_flags_for_team_in_redis(
        client,
        team_b.id,
        team_b.project_id(),
        Some(flag_json_b.to_string()),
    )
    .await?;

    let server = ServerHandle::for_config(config).await;

    // Should succeed for team A (in scoped_teams)
    let response_a = reqwest::Client::new()
        .get(format!(
            "http://{}/evaluation_reasons?token={}&distinct_id={distinct_id}",
            server.addr, redis_team_a.api_token
        ))
        .header("Authorization", format!("Bearer {api_key_value}"))
        .send()
        .await?;

    assert_eq!(response_a.status(), StatusCode::OK);

    // Should fail for team B (not in scoped_teams)
    let response_b = reqwest::Client::new()
        .get(format!(
            "http://{}/evaluation_reasons?token={}&distinct_id={distinct_id}",
            server.addr, redis_team_b.api_token
        ))
        .header("Authorization", format!("Bearer {api_key_value}"))
        .send()
        .await?;

    assert_eq!(response_b.status(), StatusCode::UNAUTHORIZED);

    Ok(())
}

/// Tests that organization membership is checked even when scoped_organizations is set
/// This is the critical security fix - scoped_organizations is an ADDITIONAL restriction,
/// not a replacement for organization membership
#[tokio::test]
async fn test_scoped_organizations_does_not_bypass_membership() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let distinct_id = "test_user".to_string();

    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let context = TestContext::new(None).await;

    // Create two organizations
    let org_a_id = uuid::Uuid::new_v4();
    let org_b_id = uuid::Uuid::new_v4();

    // Create team in org B
    let team_b = context
        .insert_new_team_with_org(None, &org_b_id.to_string())
        .await?;

    // Insert team B into Redis
    let redis_team_b = insert_new_team_in_redis(client.clone()).await?;

    // Create user in org A only (NOT a member of org B)
    let user_a = context
        .create_user_with_options("attacker@test.com", &org_a_id, None, true)
        .await?;
    context
        .add_user_to_organization(user_a, &org_a_id, 15)
        .await?;

    // Attacker creates API key with scoped_organizations including org_b
    // This should NOT grant access since user is not a member of org_b
    let (_pak_id, api_key_value) = context
        .create_personal_api_key(
            user_a,
            "malicious-key",
            vec!["feature_flag:read"],
            None,
            Some(vec![org_b_id.to_string()]), // Scoped to victim org!
        )
        .await?;

    // Insert a flag for team B
    let flag_json = json!([{
        "id": 1,
        "key": "victim-flag",
        "name": "Victim Flag",
        "active": true,
        "deleted": false,
        "team_id": team_b.id,
        "filters": {
            "groups": [{
                "properties": [],
                "rollout_percentage": 100
            }]
        },
    }]);

    insert_flags_for_team_in_redis(
        client,
        team_b.id,
        team_b.project_id(),
        Some(flag_json.to_string()),
    )
    .await?;

    let server = ServerHandle::for_config(config).await;

    // CRITICAL: This should FAIL because user is not a member of org_b
    // Even though scoped_organizations includes org_b, membership is checked first
    let response = reqwest::Client::new()
        .get(format!(
            "http://{}/evaluation_reasons?token={}&distinct_id={distinct_id}",
            server.addr, redis_team_b.api_token
        ))
        .header("Authorization", format!("Bearer {api_key_value}"))
        .send()
        .await?;

    // This is the critical security check - the attack should be blocked
    assert_eq!(
        response.status(),
        StatusCode::UNAUTHORIZED,
        "SECURITY VULNERABILITY: scoped_organizations bypassed organization membership check!"
    );

    Ok(())
}
