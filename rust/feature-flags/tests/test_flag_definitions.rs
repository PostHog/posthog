mod common;

/// Poll until `last_used_at` is set for the given PAK, or panic after ~4s.
async fn poll_for_pak_last_used_at(
    context: &feature_flags::utils::test_utils::TestContext,
    pak_id: &str,
    message: &str,
) {
    use tokio::time::{sleep, Duration};

    let mut conn = context.get_non_persons_connection().await.unwrap();
    for _ in 0..80 {
        let count: (i64,) = sqlx::query_as(
            "SELECT COUNT(*) FROM posthog_personalapikey WHERE id = $1 AND last_used_at IS NOT NULL",
        )
        .bind(pak_id)
        .fetch_one(&mut *conn)
        .await
        .unwrap();
        if count.0 > 0 {
            return;
        }
        sleep(Duration::from_millis(50)).await;
    }
    panic!("{message}");
}

#[tokio::test]
async fn test_hypercache_config_generation() {
    use common_hypercache::{HyperCacheConfig, KeyType};
    use common_types::TeamIdentifier;

    // Create a test team that implements TeamIdentifier
    #[derive(Debug, Clone)]
    struct TestTeam {
        id: i32,
        token: String,
    }

    impl TeamIdentifier for TestTeam {
        fn team_id(&self) -> i32 {
            self.id
        }

        fn api_token(&self) -> &str {
            &self.token
        }
    }

    let test_team = TestTeam {
        id: 123,
        token: "test_token".to_string(),
    };

    // Test that HyperCache configurations generate correct cache keys matching Django format
    let config_with_cohorts = HyperCacheConfig::new(
        "feature_flags".to_string(),
        "flags_with_cohorts.json".to_string(),
        "us-east-1".to_string(),
        "test-bucket".to_string(),
    );

    let config_without_cohorts = HyperCacheConfig::new(
        "feature_flags".to_string(),
        "flags_without_cohorts.json".to_string(),
        "us-east-1".to_string(),
        "test-bucket".to_string(),
    );

    let team_key = KeyType::team(test_team.clone());

    // Test Redis cache key generation (includes posthog:1: prefix)
    let redis_key_with_cohorts = config_with_cohorts.get_redis_cache_key(&team_key);
    assert_eq!(
        redis_key_with_cohorts,
        "posthog:1:cache/teams/123/feature_flags/flags_with_cohorts.json"
    );

    let redis_key_without_cohorts = config_without_cohorts.get_redis_cache_key(&team_key);
    assert_eq!(
        redis_key_without_cohorts,
        "posthog:1:cache/teams/123/feature_flags/flags_without_cohorts.json"
    );

    // Test S3 cache key generation (no prefix, matches Django object_storage)
    let s3_key_with_cohorts = config_with_cohorts.get_s3_cache_key(&team_key);
    assert_eq!(
        s3_key_with_cohorts,
        "cache/teams/123/feature_flags/flags_with_cohorts.json"
    );

    let s3_key_without_cohorts = config_without_cohorts.get_s3_cache_key(&team_key);
    assert_eq!(
        s3_key_without_cohorts,
        "cache/teams/123/feature_flags/flags_without_cohorts.json"
    );
}

#[tokio::test]
async fn test_flag_definitions_endpoint_exists() {
    use feature_flags::config::Config;
    use reqwest;

    let config = Config::default_test_config();
    let server = common::ServerHandle::for_config(config).await;
    let client = reqwest::Client::new();

    // Test that the endpoint exists and returns some response (even if unauthorized)
    let response = client
        .get(format!(
            "http://{}/flags/definitions?token=any_token",
            server.addr
        ))
        .send()
        .await
        .unwrap();

    // Should return 401 Unauthorized when no authentication is provided
    assert_eq!(response.status(), 401);
}

#[tokio::test]
async fn test_personal_api_key_authentication_no_key() {
    use feature_flags::{config::Config, utils::test_utils::TestContext};
    use reqwest;
    use serde_json::Value;

    let config = Config::default_test_config();
    let context = TestContext::new(Some(&config)).await;

    // Create a real team so we pass the token validation
    let team = context.insert_new_team(None).await.unwrap();

    let server = common::ServerHandle::for_config(config).await;
    let client = reqwest::Client::new();

    // Test that the endpoint returns 401 when no API key is provided
    let response = client
        .get(format!(
            "http://{}/flags/definitions?token={}",
            server.addr, team.api_token
        ))
        .send()
        .await
        .unwrap();

    let status = response.status();
    let body_text = response.text().await.unwrap();

    assert_eq!(status, 401);

    // Verify the response body matches Django's format
    let body: Value = serde_json::from_str(&body_text).unwrap();
    assert_eq!(body["type"], "authentication_error");
    assert_eq!(body["code"], "not_authenticated");
    assert_eq!(
        body["detail"],
        "Authentication credentials were not provided."
    );
    assert_eq!(body["attr"], Value::Null);
}

#[tokio::test]
async fn test_personal_api_key_authentication_invalid_key() {
    use feature_flags::{config::Config, utils::test_utils::TestContext};
    use reqwest;
    use serde_json::Value;

    let config = Config::default_test_config();
    let context = TestContext::new(Some(&config)).await;

    // Create a real team so we pass the token validation
    let team = context.insert_new_team(None).await.unwrap();

    let server = common::ServerHandle::for_config(config).await;
    let client = reqwest::Client::new();

    // Test that the endpoint returns 401 when an invalid API key is provided
    let response = client
        .get(format!(
            "http://{}/flags/definitions?token={}",
            server.addr, team.api_token
        ))
        .header("Authorization", "Bearer phx_invalid_key_12345")
        .send()
        .await
        .unwrap();

    let status = response.status();
    let body_text = response.text().await.unwrap();

    assert_eq!(status, 401);

    // Verify the response body matches Django's format
    let body: Value = serde_json::from_str(&body_text).unwrap();
    assert_eq!(body["type"], "authentication_error");
    assert_eq!(body["code"], "authentication_failed");
    assert_eq!(body["detail"], "Personal API key is invalid.");
    assert_eq!(body["attr"], Value::Null);
}

#[tokio::test]
async fn test_personal_api_key_authentication_valid_key_with_scopes() {
    use feature_flags::{config::Config, utils::test_utils::TestContext};
    use reqwest;

    let config = Config::default_test_config();
    let context = TestContext::new(Some(&config)).await;

    // Create team, user, and personal API key using helpers
    let team = context.insert_new_team(None).await.unwrap();
    let org_id = context.get_organization_id_for_team(&team).await.unwrap();

    let user_email = feature_flags::utils::test_utils::TestContext::generate_test_email("test_pak");
    let user_id = context
        .create_user(&user_email, &org_id, team.id)
        .await
        .unwrap();
    context
        .add_user_to_organization(user_id, &org_id, 15)
        .await
        .unwrap();

    let (_pak_id, api_key_value) = context
        .create_personal_api_key(user_id, "Test PAK", vec!["feature_flag:read"], None, None)
        .await
        .unwrap();

    // Populate cache to avoid 503 errors
    context.populate_cache_for_team(team.id).await.unwrap();

    let server = common::ServerHandle::for_config(config.clone()).await;
    let client = reqwest::Client::new();

    // Test that the endpoint returns 200 when a valid API key with proper scopes is provided
    let response = client
        .get(format!(
            "http://{}/flags/definitions?token={}",
            server.addr, team.api_token
        ))
        .header("Authorization", format!("Bearer {api_key_value}"))
        .send()
        .await
        .unwrap();

    assert_eq!(
        response.status(),
        200,
        "Response body: {}",
        response.text().await.unwrap()
    );
}

#[tokio::test]
async fn test_personal_api_key_authentication_without_feature_flag_scopes() {
    use feature_flags::{config::Config, utils::test_utils::TestContext};
    use reqwest;

    let config = Config::default_test_config();
    let context = TestContext::new(Some(&config)).await;

    // Create team, user, and personal API key with different scope
    let team = context.insert_new_team(None).await.unwrap();
    let org_id = context.get_organization_id_for_team(&team).await.unwrap();

    let user_email =
        feature_flags::utils::test_utils::TestContext::generate_test_email("test_no_scopes");
    let user_id = context
        .create_user(&user_email, &org_id, team.id)
        .await
        .unwrap();

    let (_pak_id, api_key_value) = context
        .create_personal_api_key(
            user_id,
            "Test PAK No Scopes",
            vec!["insight:read"],
            None,
            None,
        )
        .await
        .unwrap();

    let server = common::ServerHandle::for_config(config.clone()).await;
    let client = reqwest::Client::new();

    // Test that the endpoint returns 403 when API key is valid but lacks feature_flag scopes
    let response = client
        .get(format!(
            "http://{}/flags/definitions?token={}",
            server.addr, team.api_token
        ))
        .header("Authorization", format!("Bearer {api_key_value}"))
        .send()
        .await
        .unwrap();

    let status = response.status();
    let body_text = response.text().await.unwrap();
    assert_eq!(status, 403);

    let body: serde_json::Value = serde_json::from_str(&body_text).unwrap();
    assert_eq!(body["type"], "authentication_error");
    assert_eq!(body["code"], "permission_denied");
    assert_eq!(
        body["detail"],
        "Personal API key lacks required scopes (feature_flag:read or feature_flag:write)."
    );
    assert_eq!(body["attr"], serde_json::Value::Null);
}

#[tokio::test]
async fn test_personal_api_key_authentication_inactive_user() {
    use feature_flags::{config::Config, utils::test_utils::TestContext};
    use reqwest;

    let config = Config::default_test_config();
    let context = TestContext::new(Some(&config)).await;

    // Create team
    let team = context.insert_new_team(None).await.unwrap();
    let org_id = context.get_organization_id_for_team(&team).await.unwrap();

    // Create INACTIVE user using helper (is_active = false)
    let test_uuid = uuid::Uuid::new_v4().to_string()[..8].to_string();
    let user_email = format!("test_inactive_{test_uuid}@posthog.com");
    let user_id = context
        .create_user_with_options(&user_email, &org_id, Some(team.id), false)
        .await
        .unwrap();

    let (_pak_id, api_key_value) = context
        .create_personal_api_key(
            user_id,
            "Test PAK Inactive",
            vec!["feature_flag:read"],
            None,
            None,
        )
        .await
        .unwrap();

    let server = common::ServerHandle::for_config(config.clone()).await;
    let client = reqwest::Client::new();

    // Test that the endpoint returns 401 when user is inactive
    let response = client
        .get(format!(
            "http://{}/flags/definitions?token={}",
            server.addr, team.api_token
        ))
        .header("Authorization", format!("Bearer {api_key_value}"))
        .send()
        .await
        .unwrap();

    assert_eq!(response.status(), 401);
}

#[tokio::test]
async fn test_secret_api_token_authentication_valid_token() {
    use feature_flags::{config::Config, utils::test_utils::TestContext};
    use reqwest;

    let config = Config::default_test_config();
    let context = TestContext::new(Some(&config)).await;

    // Create team with secret API token using helper
    let (team, secret_token, _) = context
        .create_team_with_secret_token(None, None, None)
        .await
        .unwrap();

    // Populate cache to avoid 503 errors
    context.populate_cache_for_team(team.id).await.unwrap();

    let server = common::ServerHandle::for_config(config.clone()).await;
    let client = reqwest::Client::new();

    // Test that the endpoint returns 200 when a valid secret API token is provided
    let response = client
        .get(format!(
            "http://{}/flags/definitions?token={}",
            server.addr, team.api_token
        ))
        .header("Authorization", format!("Bearer {secret_token}"))
        .send()
        .await
        .unwrap();

    assert_eq!(
        response.status(),
        200,
        "Response body: {}",
        response.text().await.unwrap()
    );
}

#[tokio::test]
async fn test_secret_api_token_authentication_invalid_token() {
    use feature_flags::{config::Config, utils::test_utils::TestContext};
    use reqwest;
    use serde_json::Value;

    let config = Config::default_test_config();
    let context = TestContext::new(Some(&config)).await;

    // Create a real team so we pass the token validation
    let team = context.insert_new_team(None).await.unwrap();

    let server = common::ServerHandle::for_config(config).await;
    let client = reqwest::Client::new();

    // Test that the endpoint returns 401 when an invalid secret token is provided
    let response = client
        .get(format!(
            "http://{}/flags/definitions?token={}",
            server.addr, team.api_token
        ))
        .header("Authorization", "Bearer phs_invalid_secret_token_xyz")
        .send()
        .await
        .unwrap();

    let status = response.status();
    let body_text = response.text().await.unwrap();

    assert_eq!(status, 401);

    // Verify the response body matches Django's format
    let body: Value = serde_json::from_str(&body_text).unwrap();
    assert_eq!(body["type"], "authentication_error");
    assert_eq!(body["code"], "authentication_failed");
    assert_eq!(body["detail"], "Secret API token is invalid.");
    assert_eq!(body["attr"], Value::Null);
}

/// Token param absent with a valid team-scoped secret — team is derived from the token.
#[rstest::rstest]
#[case::team_secret_token("secret")]
#[case::project_secret_key("project_secret")]
#[tokio::test]
async fn test_missing_token_param_success(#[case] auth_type: &str) {
    use feature_flags::{config::Config, utils::test_utils::TestContext};
    use reqwest;

    let config = Config::default_test_config();
    let context = TestContext::new(Some(&config)).await;

    let (team, bearer_value) = match auth_type {
        "secret" => {
            let (team, secret, _) = context
                .create_team_with_secret_token(None, None, None)
                .await
                .unwrap();
            (team, secret)
        }
        "project_secret" => {
            let team = context.insert_new_team(None).await.unwrap();
            let key = context
                .create_project_secret_api_key(team.id, "Test Key", Some(vec!["feature_flag:read"]))
                .await
                .unwrap();
            (team, key)
        }
        _ => unreachable!(),
    };
    context.populate_cache_for_team(team.id).await.unwrap();

    let server = common::ServerHandle::for_config(config.clone()).await;
    let client = reqwest::Client::new();

    let response = client
        .get(format!("http://{}/flags/definitions", server.addr))
        .header("Authorization", format!("Bearer {bearer_value}"))
        .send()
        .await
        .unwrap();

    assert_eq!(
        response.status(),
        200,
        "Response body: {}",
        response.text().await.unwrap()
    );
}

/// Token param absent — error cases that don't need DB setup.
#[rstest::rstest]
#[case::no_auth(None, 401)]
#[case::invalid_phs_token(Some("Bearer phs_invalid_token_xyz"), 401)]
#[tokio::test]
async fn test_missing_token_param_error(
    #[case] auth_header: Option<&str>,
    #[case] expected_status: u16,
) {
    use feature_flags::config::Config;
    use reqwest;

    let config = Config::default_test_config();
    let server = common::ServerHandle::for_config(config).await;
    let client = reqwest::Client::new();

    let mut req = client.get(format!("http://{}/flags/definitions", server.addr));
    if let Some(header) = auth_header {
        req = req.header("Authorization", header);
    }
    let response = req.send().await.unwrap();

    assert_eq!(response.status(), expected_status);
}

/// When token param is missing, the response should contain flags for the team
/// that owns the phs_ token — not a different team's flags.
#[tokio::test]
async fn test_missing_token_param_returns_correct_team_flags() {
    use feature_flags::{config::Config, utils::test_utils::TestContext};
    use reqwest;
    use serde_json::{json, Value};

    let config = Config::default_test_config();
    let context = TestContext::new(Some(&config)).await;

    // Create two teams with different secret tokens
    let (team1, secret1, _) = context
        .create_team_with_secret_token(None, None, None)
        .await
        .unwrap();
    let (team2, secret2, _) = context
        .create_team_with_secret_token(None, None, None)
        .await
        .unwrap();

    // Seed each team's cache with distinguishable flags so we can verify isolation
    context
        .populate_cache_for_team_with_flags(
            team1.id,
            json!({"flags": [{"key": "team1-flag", "active": true}], "group_type_mapping": {}, "cohorts": {}}),
        )
        .await
        .unwrap();
    context
        .populate_cache_for_team_with_flags(
            team2.id,
            json!({"flags": [{"key": "team2-flag", "active": true}], "group_type_mapping": {}, "cohorts": {}}),
        )
        .await
        .unwrap();

    let server = common::ServerHandle::for_config(config.clone()).await;
    let client = reqwest::Client::new();

    // Request with team1's secret token (no ?token= param)
    let resp1 = client
        .get(format!("http://{}/flags/definitions", server.addr))
        .header("Authorization", format!("Bearer {secret1}"))
        .send()
        .await
        .unwrap();
    assert_eq!(resp1.status(), 200);
    let body1: Value = serde_json::from_str(&resp1.text().await.unwrap()).unwrap();

    // Request with team2's secret token (no ?token= param)
    let resp2 = client
        .get(format!("http://{}/flags/definitions", server.addr))
        .header("Authorization", format!("Bearer {secret2}"))
        .send()
        .await
        .unwrap();
    assert_eq!(resp2.status(), 200);
    let body2: Value = serde_json::from_str(&resp2.text().await.unwrap()).unwrap();

    // Each team should get its own flags, not the other's
    assert_eq!(body1["flags"][0]["key"], "team1-flag");
    assert_eq!(body2["flags"][0]["key"], "team2-flag");
    assert_ne!(
        body1.get("flags"),
        body2.get("flags"),
        "Different teams' phs_ tokens should resolve to different flags"
    );
}

/// When token param is missing and auth is a personal API key (multi-team),
/// should return 400 since we can't derive the team.
#[tokio::test]
async fn test_missing_token_param_with_personal_api_key_returns_400() {
    use feature_flags::{config::Config, utils::test_utils::TestContext};
    use reqwest;

    let config = Config::default_test_config();
    let context = TestContext::new(Some(&config)).await;

    let team = context.insert_new_team(None).await.unwrap();
    let org_id = context.get_organization_id_for_team(&team).await.unwrap();
    let user_email = format!("test-pak-{}@posthog.com", uuid::Uuid::new_v4());
    let user_id = context
        .create_user(&user_email, &org_id, team.id)
        .await
        .unwrap();
    let (_, pak_token) = context
        .create_personal_api_key(user_id, "Test PAK", vec!["feature_flag:read"], None, None)
        .await
        .unwrap();

    let server = common::ServerHandle::for_config(config.clone()).await;
    let client = reqwest::Client::new();

    let response = client
        .get(format!("http://{}/flags/definitions", server.addr))
        .header("Authorization", format!("Bearer {pak_token}"))
        .send()
        .await
        .unwrap();

    assert_eq!(response.status(), 400);
    let body = response.text().await.unwrap();
    assert!(
        body.contains("token"),
        "Error should mention the token parameter: {body}"
    );
}

#[tokio::test]
async fn test_token_mismatch_secret_token_for_different_team() {
    use feature_flags::{config::Config, utils::test_utils::TestContext};
    use reqwest;

    let config = Config::default_test_config();
    let context = TestContext::new(Some(&config)).await;

    // Create two teams with secret tokens
    let (team1, _secret1, _) = context
        .create_team_with_secret_token(None, None, None)
        .await
        .unwrap();

    let (_team2, secret2, _) = context
        .create_team_with_secret_token(None, None, None)
        .await
        .unwrap();

    let server = common::ServerHandle::for_config(config.clone()).await;
    let client = reqwest::Client::new();

    // Test: Use team1's public token but team2's secret token - should fail
    let response = client
        .get(format!(
            "http://{}/flags/definitions?token={}",
            server.addr, team1.api_token
        ))
        .header("Authorization", format!("Bearer {secret2}"))
        .send()
        .await
        .unwrap();

    // Should return 401 because the secret token doesn't match the team
    assert_eq!(response.status(), 401);
}

#[tokio::test]
async fn test_personal_api_key_with_scoped_teams_allowed() {
    use feature_flags::{config::Config, utils::test_utils::TestContext};
    use reqwest;

    let config = Config::default_test_config();
    let context = TestContext::new(Some(&config)).await;

    // Create team using helper (creates org, project, and team)
    let team = context.insert_new_team(None).await.unwrap();
    let org_id = context.get_organization_id_for_team(&team).await.unwrap();

    let test_uuid = uuid::Uuid::new_v4().to_string()[..8].to_string();
    let user_email = format!("test_scoped_teams_{test_uuid}@posthog.com");
    let user_id = context
        .create_user(&user_email, &org_id, team.id)
        .await
        .unwrap();
    context
        .add_user_to_organization(user_id, &org_id, 15)
        .await
        .unwrap();

    // Create personal API key with scoped_teams restriction that includes our team
    let (_pak_id, api_key_value) = context
        .create_personal_api_key(
            user_id,
            "Test PAK Scoped Teams",
            vec!["feature_flag:read"],
            Some(vec![team.id]),
            None,
        )
        .await
        .unwrap();

    // Populate cache to avoid 503 errors
    let redis_client =
        feature_flags::utils::test_utils::setup_redis_client(Some(config.redis_url.clone())).await;
    context
        .populate_flag_definitions_cache(redis_client, team.id)
        .await
        .unwrap();

    let server = common::ServerHandle::for_config(config.clone()).await;
    let client = reqwest::Client::new();

    // Should succeed because the team is in the scoped_teams list
    let response = client
        .get(format!(
            "http://{}/flags/definitions?token={}",
            server.addr, team.api_token
        ))
        .header("Authorization", format!("Bearer {api_key_value}"))
        .send()
        .await
        .unwrap();

    let status = response.status();
    let body = response.text().await.unwrap();
    assert_eq!(
        status, 200,
        "Should authenticate when team is in scoped_teams. Response body: {body}"
    );
}

#[tokio::test]
async fn test_personal_api_key_with_scoped_teams_denied() {
    use feature_flags::{config::Config, utils::test_utils::TestContext};
    use reqwest;

    let config = Config::default_test_config();
    let context = TestContext::new(Some(&config)).await;

    let team = context.insert_new_team(None).await.unwrap();
    let org_id = context.get_organization_id_for_team(&team).await.unwrap();

    let test_uuid = uuid::Uuid::new_v4().to_string()[..8].to_string();
    let user_email = format!("test_denied_{test_uuid}@posthog.com");
    let user_id = context
        .create_user(&user_email, &org_id, team.id)
        .await
        .unwrap();

    // Create personal API key with scoped_teams restriction that excludes our team
    let (_pak_id, api_key_value) = context
        .create_personal_api_key(
            user_id,
            "Test PAK Denied",
            vec!["feature_flag:read"],
            Some(vec![99999]), // Different team ID
            None,
        )
        .await
        .unwrap();

    let server = common::ServerHandle::for_config(config.clone()).await;
    let client = reqwest::Client::new();

    // Should fail because the team is not in the scoped_teams list
    let response = client
        .get(format!(
            "http://{}/flags/definitions?token={}",
            server.addr, team.api_token
        ))
        .header("Authorization", format!("Bearer {api_key_value}"))
        .send()
        .await
        .unwrap();

    assert_eq!(
        response.status(),
        401,
        "Should deny access when team is not in scoped_teams"
    );
}

#[tokio::test]
async fn test_personal_api_key_with_scoped_organizations_allowed() {
    use feature_flags::{config::Config, utils::test_utils::TestContext};
    use reqwest;

    let config = Config::default_test_config();
    let context = TestContext::new(Some(&config)).await;

    let team = context.insert_new_team(None).await.unwrap();
    let org_id = context.get_organization_id_for_team(&team).await.unwrap();

    let test_uuid = uuid::Uuid::new_v4().to_string()[..8].to_string();
    let user_email = format!("test_org_allowed_{test_uuid}@posthog.com");
    let user_id = context
        .create_user(&user_email, &org_id, team.id)
        .await
        .unwrap();
    context
        .add_user_to_organization(user_id, &org_id, 15)
        .await
        .unwrap();

    // Create personal API key with scoped_organizations restriction that includes our org
    let org_id_str = org_id.to_string();
    let (_pak_id, api_key_value) = context
        .create_personal_api_key(
            user_id,
            "Test PAK Org Allowed",
            vec!["feature_flag:read"],
            None,
            Some(vec![org_id_str]),
        )
        .await
        .unwrap();

    // Populate cache to avoid 503 errors
    let redis_client =
        feature_flags::utils::test_utils::setup_redis_client(Some(config.redis_url.clone())).await;
    context
        .populate_flag_definitions_cache(redis_client, team.id)
        .await
        .unwrap();

    let server = common::ServerHandle::for_config(config.clone()).await;
    let client = reqwest::Client::new();

    // Should succeed because the organization is in the scoped_organizations list
    let response = client
        .get(format!(
            "http://{}/flags/definitions?token={}",
            server.addr, team.api_token
        ))
        .header("Authorization", format!("Bearer {api_key_value}"))
        .send()
        .await
        .unwrap();

    let status = response.status();
    let body = response.text().await.unwrap();
    assert_eq!(
        status, 200,
        "Should authenticate when organization is in scoped_organizations. Response body: {body}"
    );
}

#[tokio::test]
async fn test_personal_api_key_with_scoped_organizations_denied() {
    use feature_flags::{config::Config, utils::test_utils::TestContext};
    use reqwest;

    let config = Config::default_test_config();
    let context = TestContext::new(Some(&config)).await;

    // Create team using helper (creates org, project, and team)
    let team = context.insert_new_team(None).await.unwrap();
    let org_id = context.get_organization_id_for_team(&team).await.unwrap();

    let test_uuid = uuid::Uuid::new_v4().to_string()[..8].to_string();
    let user_email = format!("test_org_denied_{test_uuid}@posthog.com");
    let user_id = context
        .create_user(&user_email, &org_id, team.id)
        .await
        .unwrap();

    // Create personal API key with scoped_organizations restriction that excludes our org
    let different_org_id = uuid::Uuid::new_v4().to_string();
    let (_pak_id, api_key_value) = context
        .create_personal_api_key(
            user_id,
            "Test PAK Org Denied",
            vec!["feature_flag:read"],
            None,
            Some(vec![different_org_id]), // Different organization ID
        )
        .await
        .unwrap();

    let server = common::ServerHandle::for_config(config.clone()).await;
    let client = reqwest::Client::new();

    // Should fail because the organization is not in the scoped_organizations list
    let response = client
        .get(format!(
            "http://{}/flags/definitions?token={}",
            server.addr, team.api_token
        ))
        .header("Authorization", format!("Bearer {api_key_value}"))
        .send()
        .await
        .unwrap();

    assert_eq!(
        response.status(),
        401,
        "Should deny access when organization is not in scoped_organizations"
    );
}

#[tokio::test]
async fn test_personal_api_key_with_scoped_organizations_removed_member() {
    use feature_flags::{config::Config, utils::test_utils::TestContext};
    use reqwest;

    let config = Config::default_test_config();
    let context = TestContext::new(Some(&config)).await;

    let team = context.insert_new_team(None).await.unwrap();
    let org_id = context.get_organization_id_for_team(&team).await.unwrap();

    let test_uuid = uuid::Uuid::new_v4().to_string()[..8].to_string();
    let user_email = format!("test_org_removed_{test_uuid}@posthog.com");
    let user_id = context
        .create_user(&user_email, &org_id, team.id)
        .await
        .unwrap();
    context
        .add_user_to_organization(user_id, &org_id, 15)
        .await
        .unwrap();

    let org_id_str = org_id.to_string();
    let (_pak_id, api_key_value) = context
        .create_personal_api_key(
            user_id,
            "Test PAK Org Removed",
            vec!["feature_flag:read"],
            None,
            Some(vec![org_id_str]),
        )
        .await
        .unwrap();

    let redis_client =
        feature_flags::utils::test_utils::setup_redis_client(Some(config.redis_url.clone())).await;
    context
        .populate_flag_definitions_cache(redis_client, team.id)
        .await
        .unwrap();

    let server = common::ServerHandle::for_config(config.clone()).await;
    let client = reqwest::Client::new();

    // Verify access works while user is a member
    let response = client
        .get(format!(
            "http://{}/flags/definitions?token={}",
            server.addr, team.api_token
        ))
        .header("Authorization", format!("Bearer {api_key_value}"))
        .send()
        .await
        .unwrap();
    assert_eq!(
        response.status(),
        200,
        "Should authenticate while user is an org member"
    );

    // Remove user from organization
    context
        .remove_user_from_organization(user_id, &org_id)
        .await
        .unwrap();
    // Simulate Django signal-based cache invalidation (Python handles this in production)
    let redis_client =
        feature_flags::utils::test_utils::setup_redis_client(Some(config.redis_url.clone())).await;
    feature_flags::utils::test_utils::invalidate_personal_api_key_auth_cache(
        redis_client,
        &api_key_value,
    )
    .await
    .unwrap();

    // Should now fail because the user is no longer an org member
    let response = client
        .get(format!(
            "http://{}/flags/definitions?token={}",
            server.addr, team.api_token
        ))
        .header("Authorization", format!("Bearer {api_key_value}"))
        .send()
        .await
        .unwrap();
    assert_eq!(
        response.status(),
        401,
        "Should deny access after user is removed from organization"
    );
}

#[tokio::test]
async fn test_personal_api_key_unscoped_removed_member() {
    use feature_flags::{config::Config, utils::test_utils::TestContext};
    use reqwest;

    let config = Config::default_test_config();
    let context = TestContext::new(Some(&config)).await;

    let team = context.insert_new_team(None).await.unwrap();
    let org_id = context.get_organization_id_for_team(&team).await.unwrap();

    let test_uuid = uuid::Uuid::new_v4().to_string()[..8].to_string();
    let user_email = format!("test_unscoped_removed_{test_uuid}@posthog.com");
    let user_id = context
        .create_user(&user_email, &org_id, team.id)
        .await
        .unwrap();
    context
        .add_user_to_organization(user_id, &org_id, 15)
        .await
        .unwrap();

    // Create PAK without scoped_organizations to confirm the mandatory membership
    // check works for all PAK configurations, not just those with explicit org scoping.
    let (_pak_id, api_key_value) = context
        .create_personal_api_key(
            user_id,
            "Test PAK Unscoped",
            vec!["feature_flag:read"],
            None,
            None,
        )
        .await
        .unwrap();

    let redis_client =
        feature_flags::utils::test_utils::setup_redis_client(Some(config.redis_url.clone())).await;
    context
        .populate_flag_definitions_cache(redis_client, team.id)
        .await
        .unwrap();

    let server = common::ServerHandle::for_config(config.clone()).await;
    let client = reqwest::Client::new();

    // Verify access works while user is a member
    let response = client
        .get(format!(
            "http://{}/flags/definitions?token={}",
            server.addr, team.api_token
        ))
        .header("Authorization", format!("Bearer {api_key_value}"))
        .send()
        .await
        .unwrap();
    assert_eq!(
        response.status(),
        200,
        "Should authenticate while user is an org member"
    );

    // Remove user from organization
    context
        .remove_user_from_organization(user_id, &org_id)
        .await
        .unwrap();
    // Simulate Django signal-based cache invalidation (Python handles this in production)
    let redis_client =
        feature_flags::utils::test_utils::setup_redis_client(Some(config.redis_url.clone())).await;
    feature_flags::utils::test_utils::invalidate_personal_api_key_auth_cache(
        redis_client,
        &api_key_value,
    )
    .await
    .unwrap();

    // Should fail because the user is no longer an org member, even without scoped_organizations
    let response = client
        .get(format!(
            "http://{}/flags/definitions?token={}",
            server.addr, team.api_token
        ))
        .header("Authorization", format!("Bearer {api_key_value}"))
        .send()
        .await
        .unwrap();
    assert_eq!(
        response.status(),
        401,
        "Should deny access after user is removed from organization, even without scoped_organizations"
    );
}

#[tokio::test]
async fn test_cache_miss_returns_503() {
    use feature_flags::{config::Config, utils::test_utils::TestContext};
    use reqwest;
    use serde_json::Value;

    let config = Config::default_test_config();
    let context = TestContext::new(Some(&config)).await;

    // Create team with secret API token
    let (team, secret_token, _) = context
        .create_team_with_secret_token(None, None, None)
        .await
        .unwrap();

    // DO NOT populate cache - we want to test cache miss behavior

    let server = common::ServerHandle::for_config(config.clone()).await;
    let client = reqwest::Client::new();

    // Request should return 503 when cache is empty
    let response = client
        .get(format!(
            "http://{}/flags/definitions?token={}",
            server.addr, team.api_token
        ))
        .header("Authorization", format!("Bearer {secret_token}"))
        .send()
        .await
        .unwrap();

    let status = response.status();
    let body_text = response.text().await.unwrap();

    assert_eq!(
        status, 503,
        "Should return 503 on cache miss. Body: {body_text}"
    );

    // Verify the response body has proper error format (if JSON)
    if let Ok(body) = serde_json::from_str::<Value>(&body_text) {
        assert_eq!(body["type"], "server_error");
        assert_eq!(body["code"], "service_unavailable");
        assert!(
            body["detail"]
                .as_str()
                .unwrap()
                .contains("Required data not found in cache"),
            "Error message should mention cache miss"
        );
    } else {
        // If not JSON, verify the error message mentions cache
        assert!(
            body_text.contains("Required data not found in cache"),
            "Body should mention cache miss. Got: {body_text}"
        );
    }
}

#[tokio::test]
async fn test_personal_api_key_with_all_access_scopes() {
    use feature_flags::{config::Config, utils::test_utils::TestContext};
    use reqwest;

    let config = Config::default_test_config();
    let context = TestContext::new(Some(&config)).await;

    // Create team, user, and personal API key with {*} (all access) scopes
    let team = context.insert_new_team(None).await.unwrap();
    let org_id = context.get_organization_id_for_team(&team).await.unwrap();

    let test_uuid = uuid::Uuid::new_v4().to_string()[..8].to_string();
    let user_email = format!("test_all_access_{test_uuid}@posthog.com");
    let user_id = context
        .create_user(&user_email, &org_id, team.id)
        .await
        .unwrap();
    context
        .add_user_to_organization(user_id, &org_id, 15)
        .await
        .unwrap();

    // Create PAK with {*} scope (all access)
    let (_pak_id, api_key_value) = context
        .create_personal_api_key(user_id, "Test PAK All Access", vec!["*"], None, None)
        .await
        .unwrap();

    // Populate cache to avoid 503 errors
    let redis_client =
        feature_flags::utils::test_utils::setup_redis_client(Some(config.redis_url.clone())).await;
    context
        .populate_flag_definitions_cache(redis_client, team.id)
        .await
        .unwrap();

    let server = common::ServerHandle::for_config(config.clone()).await;
    let client = reqwest::Client::new();

    // Test that the endpoint returns 200 when PAK has all access
    let response = client
        .get(format!(
            "http://{}/flags/definitions?token={}",
            server.addr, team.api_token
        ))
        .header("Authorization", format!("Bearer {api_key_value}"))
        .send()
        .await
        .unwrap();

    assert_eq!(
        response.status(),
        200,
        "Response body: {}",
        response.text().await.unwrap()
    );
}

#[tokio::test]
async fn test_personal_api_key_with_feature_flag_write_scope() {
    use feature_flags::{config::Config, utils::test_utils::TestContext};
    use reqwest;

    let config = Config::default_test_config();
    let context = TestContext::new(Some(&config)).await;

    // Create team, user, and personal API key with feature_flag:write scope
    let team = context.insert_new_team(None).await.unwrap();
    let org_id = context.get_organization_id_for_team(&team).await.unwrap();

    let test_uuid = uuid::Uuid::new_v4().to_string()[..8].to_string();
    let user_email = format!("test_write_scope_{test_uuid}@posthog.com");
    let user_id = context
        .create_user(&user_email, &org_id, team.id)
        .await
        .unwrap();
    context
        .add_user_to_organization(user_id, &org_id, 15)
        .await
        .unwrap();

    // Create PAK with feature_flag:write scope (write includes read access)
    let (_pak_id, api_key_value) = context
        .create_personal_api_key(
            user_id,
            "Test PAK Write Scope",
            vec!["feature_flag:write"],
            None,
            None,
        )
        .await
        .unwrap();

    // Populate cache to avoid 503 errors
    let redis_client =
        feature_flags::utils::test_utils::setup_redis_client(Some(config.redis_url.clone())).await;
    context
        .populate_flag_definitions_cache(redis_client, team.id)
        .await
        .unwrap();

    let server = common::ServerHandle::for_config(config.clone()).await;
    let client = reqwest::Client::new();

    // Test that the endpoint returns 200 with feature_flag:write scope
    let response = client
        .get(format!(
            "http://{}/flags/definitions?token={}",
            server.addr, team.api_token
        ))
        .header("Authorization", format!("Bearer {api_key_value}"))
        .send()
        .await
        .unwrap();

    assert_eq!(
        response.status(),
        200,
        "Should succeed with feature_flag:write scope. Response body: {}",
        response.text().await.unwrap()
    );
}

#[tokio::test]
async fn test_backup_secret_api_token_authentication() {
    use feature_flags::{config::Config, utils::test_utils::TestContext};
    use reqwest;

    let config = Config::default_test_config();
    let context = TestContext::new(Some(&config)).await;

    // Create a team with both secret_api_token and secret_api_token_backup using helper
    let backup_token_value = feature_flags::utils::test_utils::random_string("phs_backup_", 12);
    let (team, _secret_token, backup_secret_token) = context
        .create_team_with_secret_token(None, None, Some(&backup_token_value))
        .await
        .unwrap();

    // Populate cache to avoid 503 errors
    let redis_client =
        feature_flags::utils::test_utils::setup_redis_client(Some(config.redis_url.clone())).await;
    context
        .populate_flag_definitions_cache(redis_client, team.id)
        .await
        .unwrap();

    let server = common::ServerHandle::for_config(config.clone()).await;
    let client = reqwest::Client::new();

    // Test that the backup secret token works
    let response = client
        .get(format!(
            "http://{}/flags/definitions?token={}",
            server.addr, team.api_token
        ))
        .header(
            "Authorization",
            format!("Bearer {}", backup_secret_token.unwrap()),
        )
        .send()
        .await
        .unwrap();

    assert_eq!(
        response.status(),
        200,
        "Should authenticate with backup secret token. Response body: {}",
        response.text().await.unwrap()
    );
}

#[tokio::test]
async fn test_invalid_project_api_key() {
    use feature_flags::config::Config;
    use reqwest;
    use serde_json::Value;

    let config = Config::default_test_config();
    let server = common::ServerHandle::for_config(config).await;
    let client = reqwest::Client::new();

    // Test with an explicitly invalid token (not just missing, but actually wrong)
    let response = client
        .get(format!(
            "http://{}/flags/definitions?token=phc_definitely_invalid_token_12345",
            server.addr
        ))
        .send()
        .await
        .unwrap();

    let status = response.status();
    let body_text = response.text().await.unwrap();

    assert_eq!(
        status, 401,
        "Should return 401 for invalid token. Body: {body_text}"
    );

    // Verify the response body format (if JSON)
    if let Ok(body) = serde_json::from_str::<Value>(&body_text) {
        assert_eq!(body["type"], "authentication_error");
        assert_eq!(body["code"], "not_authenticated");
    } else {
        // If not JSON, verify the error message mentions invalid API key
        assert!(
            body_text.contains("API key is invalid") || body_text.contains("expired"),
            "Body should mention invalid API key. Got: {body_text}"
        );
    }
}

#[tokio::test]
async fn test_secret_token_takes_priority_over_personal_api_key() {
    use feature_flags::{config::Config, utils::test_utils::TestContext};
    use reqwest;

    let config = Config::default_test_config();
    let context = TestContext::new(Some(&config)).await;

    // Create two teams with different data
    let (team1, secret_token1, _) = context
        .create_team_with_secret_token(None, None, None)
        .await
        .unwrap();

    let team2 = context.insert_new_team(None).await.unwrap();
    let org_id2 = context.get_organization_id_for_team(&team2).await.unwrap();

    // Create PAK for team2
    let test_uuid = uuid::Uuid::new_v4().to_string()[..8].to_string();
    let user_email = format!("test_priority_{test_uuid}@posthog.com");
    let user_id = context
        .create_user(&user_email, &org_id2, team2.id)
        .await
        .unwrap();

    let (_pak_id, _personal_key) = context
        .create_personal_api_key(
            user_id,
            "Test PAK Priority",
            vec!["feature_flag:read"],
            None,
            None,
        )
        .await
        .unwrap();

    // Populate cache for team1 only
    let redis_client =
        feature_flags::utils::test_utils::setup_redis_client(Some(config.redis_url.clone())).await;
    context
        .populate_flag_definitions_cache(redis_client, team1.id)
        .await
        .unwrap();

    let server = common::ServerHandle::for_config(config.clone()).await;
    let client = reqwest::Client::new();

    // Provide BOTH authentication methods:
    // - Secret token for team1 (in Authorization header - phs_ prefix)
    // - Personal API key for team2 (phx_ prefix)
    // Expected: Secret token takes priority, so we get team1's data
    let response = client
        .get(format!(
            "http://{}/flags/definitions?token={}",
            server.addr, team1.api_token
        ))
        .header("Authorization", format!("Bearer {secret_token1}"))
        .send()
        .await
        .unwrap();

    // Should succeed with team1's secret token (200 status)
    // If PAK was tried first, it would fail because PAK belongs to team2
    assert_eq!(
        response.status(),
        200,
        "Should authenticate with secret token when both auth methods provided. Response body: {}",
        response.text().await.unwrap()
    );
}

#[tokio::test]
async fn test_flag_definitions_rate_limit_enforced() {
    use feature_flags::{config::Config, utils::test_utils::TestContext};
    use reqwest;

    let context = TestContext::new(None).await;

    // Create team with secret token
    let (team, secret_token, _) = context
        .create_team_with_secret_token(None, None, None)
        .await
        .unwrap();

    // Create config with very low rate limit for this specific team (1 request per second)
    let mut config = Config::default_test_config();
    config.flag_definitions_rate_limits =
        format!(r#"{{"{}": "1/second"}}"#, team.id).parse().unwrap();

    // Populate cache to avoid 503 errors
    let redis_client =
        feature_flags::utils::test_utils::setup_redis_client(Some(config.redis_url.clone())).await;
    context
        .populate_flag_definitions_cache(redis_client, team.id)
        .await
        .unwrap();

    let server = common::ServerHandle::for_config(config.clone()).await;
    let client = reqwest::Client::new();

    // First request should succeed (within rate limit)
    let response = client
        .get(format!(
            "http://{}/flags/definitions?token={}",
            server.addr, team.api_token
        ))
        .header("Authorization", format!("Bearer {secret_token}"))
        .send()
        .await
        .unwrap();

    assert_eq!(
        response.status(),
        200,
        "First request should succeed. Response body: {}",
        response.text().await.unwrap()
    );

    // Second request immediately after should be rate limited (429)
    let response = client
        .get(format!(
            "http://{}/flags/definitions?token={}",
            server.addr, team.api_token
        ))
        .header("Authorization", format!("Bearer {secret_token}"))
        .send()
        .await
        .unwrap();

    let status = response.status();
    let body = response.text().await.unwrap();

    assert_eq!(
        status, 429,
        "Second request should be rate limited. Response body: {body}"
    );
    assert!(
        body.contains("Rate limit exceeded"),
        "Response should mention rate limit. Got: {body}"
    );
}

#[tokio::test]
async fn test_flag_definitions_custom_rate_limit_overrides_default() {
    use feature_flags::{config::Config, utils::test_utils::TestContext};
    use reqwest;
    use tokio::time::{sleep, Duration};

    let context = TestContext::new(None).await;

    // Create teams with secret tokens
    let (custom_team, custom_secret, _) = context
        .create_team_with_secret_token(None, None, None)
        .await
        .unwrap();
    let (default_team, default_secret, _) = context
        .create_team_with_secret_token(None, None, None)
        .await
        .unwrap();

    // Create config with custom rate limit for custom_team (2 requests per second)
    // Default is 600/minute (10/second), so custom should be more restrictive
    let mut config = Config::default_test_config();
    config.flag_definitions_rate_limits = format!(r#"{{"{}": "2/second"}}"#, custom_team.id)
        .parse()
        .unwrap();

    // Populate cache for both teams
    let redis_client =
        feature_flags::utils::test_utils::setup_redis_client(Some(config.redis_url.clone())).await;
    context
        .populate_flag_definitions_cache(redis_client.clone(), custom_team.id)
        .await
        .unwrap();
    context
        .populate_flag_definitions_cache(redis_client, default_team.id)
        .await
        .unwrap();

    let server = common::ServerHandle::for_config(config.clone()).await;
    let client = reqwest::Client::new();

    // Test custom rate limit (2/second)
    // Send all 3 requests concurrently to ensure they hit the rate limiter simultaneously
    let requests = (0..3).map(|_| {
        client
            .get(format!(
                "http://{}/flags/definitions?token={}",
                server.addr, custom_team.api_token
            ))
            .header("Authorization", format!("Bearer {custom_secret}"))
            .send()
    });

    let responses = futures::future::join_all(requests).await;
    let success_count = responses
        .into_iter()
        .filter(|r| r.as_ref().unwrap().status() == 200)
        .count();

    assert_eq!(
        success_count, 2,
        "Should allow exactly 2 requests per second for custom team"
    );

    // Wait for rate limit to reset
    sleep(Duration::from_millis(1100)).await;

    // Test default rate limit (600/minute = 10/second)
    // Should allow more requests than custom limit
    // Send all 5 requests concurrently to ensure they hit the rate limiter simultaneously
    let requests = (0..5).map(|_| {
        client
            .get(format!(
                "http://{}/flags/definitions?token={}",
                server.addr, default_team.api_token
            ))
            .header("Authorization", format!("Bearer {default_secret}"))
            .send()
    });

    let responses = futures::future::join_all(requests).await;
    let default_success_count = responses
        .into_iter()
        .filter(|r| r.as_ref().unwrap().status() == 200)
        .count();

    assert!(
        default_success_count > 2,
        "Default team should allow more than 2 requests per second. Got: {default_success_count}"
    );
}

#[tokio::test]
async fn test_flag_definitions_rate_limit_metrics_incremented() {
    use feature_flags::{config::Config, utils::test_utils::TestContext};
    use reqwest;

    let context = TestContext::new(None).await;

    // Create team with secret token
    let (team, secret_token, _) = context
        .create_team_with_secret_token(None, None, None)
        .await
        .unwrap();

    // Create config with very low rate limit for this specific team
    let mut config = Config::default_test_config();
    config.flag_definitions_rate_limits =
        format!(r#"{{"{}": "1/second"}}"#, team.id).parse().unwrap();
    config.enable_metrics = true; // Enable metrics collection

    // Populate cache
    let redis_client =
        feature_flags::utils::test_utils::setup_redis_client(Some(config.redis_url.clone())).await;
    context
        .populate_flag_definitions_cache(redis_client, team.id)
        .await
        .unwrap();

    let server = common::ServerHandle::for_config(config.clone()).await;
    let client = reqwest::Client::new();

    // Make first request (should succeed)
    let response = client
        .get(format!(
            "http://{}/flags/definitions?token={}",
            server.addr, team.api_token
        ))
        .header("Authorization", format!("Bearer {secret_token}"))
        .send()
        .await
        .unwrap();

    assert_eq!(response.status(), 200);

    // Make second request (should be rate limited)
    let response = client
        .get(format!(
            "http://{}/flags/definitions?token={}",
            server.addr, team.api_token
        ))
        .header("Authorization", format!("Bearer {secret_token}"))
        .send()
        .await
        .unwrap();

    assert_eq!(response.status(), 429);

    // Fetch metrics from /metrics endpoint
    let metrics_response = client
        .get(format!("http://{}/metrics", server.addr))
        .send()
        .await
        .unwrap();

    let metrics_text = metrics_response.text().await.unwrap();

    // Verify that rate limit metrics are present
    assert!(
        metrics_text.contains("flags_flag_definitions_requests_total"),
        "Metrics should include request counter"
    );
    assert!(
        metrics_text.contains("flags_flag_definitions_rate_limited_total"),
        "Metrics should include rate limited counter"
    );

    // Verify key label is present in metrics (key is the generic label for team_id)
    let key_label = format!("key=\"{}\"", team.id);
    assert!(
        metrics_text.contains(&key_label),
        "Metrics should include key label. Metrics: {metrics_text}"
    );
}

#[tokio::test]
async fn test_etag_returns_304_when_matching() {
    use feature_flags::{config::Config, utils::test_utils::TestContext};
    use reqwest;

    let config = Config::default_test_config();
    let context = TestContext::new(Some(&config)).await;

    let (team, secret_token, _) = context
        .create_team_with_secret_token(None, None, None)
        .await
        .unwrap();

    let etag_value = "a1b2c3d4e5f6g7h8";
    context
        .populate_cache_for_team_with_etag(team.id, etag_value)
        .await
        .unwrap();

    let server = common::ServerHandle::for_config(config.clone()).await;
    let client = reqwest::Client::new();

    let response = client
        .get(format!(
            "http://{}/flags/definitions?token={}",
            server.addr, team.api_token
        ))
        .header("Authorization", format!("Bearer {secret_token}"))
        .header("If-None-Match", format!("W/\"{etag_value}\""))
        .send()
        .await
        .unwrap();

    assert_eq!(
        response.status(),
        304,
        "Should return 304 when ETag matches. Body: {}",
        response.text().await.unwrap_or_default()
    );
}

#[tokio::test]
async fn test_etag_304_includes_etag_and_cache_control_headers() {
    use feature_flags::{config::Config, utils::test_utils::TestContext};
    use reqwest;

    let config = Config::default_test_config();
    let context = TestContext::new(Some(&config)).await;

    let (team, secret_token, _) = context
        .create_team_with_secret_token(None, None, None)
        .await
        .unwrap();

    let etag_value = "abcdef1234567890";
    context
        .populate_cache_for_team_with_etag(team.id, etag_value)
        .await
        .unwrap();

    let server = common::ServerHandle::for_config(config.clone()).await;
    let client = reqwest::Client::new();

    let response = client
        .get(format!(
            "http://{}/flags/definitions?token={}",
            server.addr, team.api_token
        ))
        .header("Authorization", format!("Bearer {secret_token}"))
        .header("If-None-Match", format!("W/\"{etag_value}\""))
        .send()
        .await
        .unwrap();

    assert_eq!(response.status(), 304);
    assert_eq!(
        response.headers().get("etag").unwrap().to_str().unwrap(),
        format!("W/\"{etag_value}\"")
    );
    assert_eq!(
        response
            .headers()
            .get("cache-control")
            .unwrap()
            .to_str()
            .unwrap(),
        "private, must-revalidate"
    );
}

#[tokio::test]
async fn test_etag_returns_200_when_not_matching() {
    use feature_flags::{config::Config, utils::test_utils::TestContext};
    use reqwest;

    let config = Config::default_test_config();
    let context = TestContext::new(Some(&config)).await;

    let (team, secret_token, _) = context
        .create_team_with_secret_token(None, None, None)
        .await
        .unwrap();

    context
        .populate_cache_for_team_with_etag(team.id, "current_etag_value")
        .await
        .unwrap();

    let server = common::ServerHandle::for_config(config.clone()).await;
    let client = reqwest::Client::new();

    let response = client
        .get(format!(
            "http://{}/flags/definitions?token={}",
            server.addr, team.api_token
        ))
        .header("Authorization", format!("Bearer {secret_token}"))
        .header("If-None-Match", "W/\"stale_etag_value\"")
        .send()
        .await
        .unwrap();

    assert_eq!(
        response.status(),
        200,
        "Should return 200 when ETag does not match"
    );

    assert_eq!(
        response.headers().get("etag").unwrap().to_str().unwrap(),
        "W/\"current_etag_value\""
    );
    assert_eq!(
        response
            .headers()
            .get("cache-control")
            .unwrap()
            .to_str()
            .unwrap(),
        "private, must-revalidate"
    );
}

#[tokio::test]
async fn test_etag_200_includes_etag_header_without_if_none_match() {
    use feature_flags::{config::Config, utils::test_utils::TestContext};
    use reqwest;

    let config = Config::default_test_config();
    let context = TestContext::new(Some(&config)).await;

    let (team, secret_token, _) = context
        .create_team_with_secret_token(None, None, None)
        .await
        .unwrap();

    let etag_value = "freshdata12345678";
    context
        .populate_cache_for_team_with_etag(team.id, etag_value)
        .await
        .unwrap();

    let server = common::ServerHandle::for_config(config.clone()).await;
    let client = reqwest::Client::new();

    // Request WITHOUT If-None-Match header
    let response = client
        .get(format!(
            "http://{}/flags/definitions?token={}",
            server.addr, team.api_token
        ))
        .header("Authorization", format!("Bearer {secret_token}"))
        .send()
        .await
        .unwrap();

    assert_eq!(response.status(), 200);
    assert_eq!(
        response.headers().get("etag").unwrap().to_str().unwrap(),
        format!("W/\"{etag_value}\""),
        "200 response should include ETag header even without If-None-Match"
    );
}

#[tokio::test]
async fn test_etag_graceful_degradation_without_stored_etag() {
    use feature_flags::{config::Config, utils::test_utils::TestContext};
    use reqwest;

    let config = Config::default_test_config();
    let context = TestContext::new(Some(&config)).await;

    let (team, secret_token, _) = context
        .create_team_with_secret_token(None, None, None)
        .await
        .unwrap();

    // Populate cache WITHOUT an ETag
    context.populate_cache_for_team(team.id).await.unwrap();

    let server = common::ServerHandle::for_config(config.clone()).await;
    let client = reqwest::Client::new();

    // Send If-None-Match even though no ETag is stored — should get 200 (graceful degradation)
    let response = client
        .get(format!(
            "http://{}/flags/definitions?token={}",
            server.addr, team.api_token
        ))
        .header("Authorization", format!("Bearer {secret_token}"))
        .header("If-None-Match", "W/\"some_stale_etag\"")
        .send()
        .await
        .unwrap();

    assert_eq!(
        response.status(),
        200,
        "Should return 200 when no ETag is stored (graceful degradation)"
    );
    assert!(
        response.headers().get("etag").is_none(),
        "Should not include ETag header when no ETag is stored"
    );
}

#[tokio::test]
async fn test_flag_definitions_billing_limited_returns_402() {
    use feature_flags::{config::Config, utils::test_utils::TestContext};
    use reqwest;

    let config = Config::default_test_config();
    let context = TestContext::new(Some(&config)).await;

    // Create team with secret token in real PG (needed for auth)
    let (team, secret_token, _) = context
        .create_team_with_secret_token(None, None, None)
        .await
        .unwrap();

    // Start server with mock Redis where the team's token is billing-limited
    let server = common::ServerHandle::for_config_with_mock_redis(
        config,
        vec![team.api_token.clone()],            // billing-limited
        vec![(team.api_token.clone(), team.id)], // valid for team lookup
    )
    .await;

    let client = reqwest::Client::new();

    let response = client
        .get(format!(
            "http://{}/flags/definitions?token={}",
            server.addr, team.api_token
        ))
        .header("Authorization", format!("Bearer {secret_token}"))
        .send()
        .await
        .unwrap();

    let status = response.status();
    let body_text = response.text().await.unwrap();

    assert_eq!(
        status, 402,
        "Should return 402 when billing quota is exceeded. Body: {body_text}"
    );
    // Response body matches Django's JSON format for SDK compatibility
    let body: serde_json::Value = serde_json::from_str(&body_text).unwrap();
    assert_eq!(body["type"], "quota_limited");
    assert_eq!(body["code"], "payment_required");
}

#[rstest::rstest]
#[case::read_scope(Some(vec!["feature_flag:read"]), true, 200)]
#[case::write_scope(Some(vec!["feature_flag:write"]), true, 200)]
#[case::null_scopes_full_access(None, true, 200)]
#[case::wildcard_scope(Some(vec!["*"]), true, 200)]
#[case::wrong_scope(Some(vec!["insight:read"]), true, 401)]
#[case::wrong_team(Some(vec!["feature_flag:read"]), false, 401)]
#[tokio::test]
async fn test_flag_definitions_project_secret_api_key(
    #[case] scopes: Option<Vec<&str>>,
    #[case] same_team: bool,
    #[case] expected_status: u16,
) {
    use feature_flags::{config::Config, utils::test_utils::TestContext};
    use reqwest;

    let config = Config::default_test_config();
    let context = TestContext::new(Some(&config)).await;

    let team = context.insert_new_team(None).await.unwrap();

    let key_team_id = if same_team {
        team.id
    } else {
        let other_team = context.insert_new_team(None).await.unwrap();
        other_team.id
    };

    let raw_key = context
        .create_project_secret_api_key(key_team_id, "Test Key", scopes)
        .await
        .unwrap();

    if expected_status == 200 {
        context.populate_cache_for_team(team.id).await.unwrap();
    }

    let server = common::ServerHandle::for_config(config.clone()).await;
    let client = reqwest::Client::new();

    let response = client
        .get(format!(
            "http://{}/flags/definitions?token={}",
            server.addr, team.api_token
        ))
        .header("Authorization", format!("Bearer {raw_key}"))
        .send()
        .await
        .unwrap();

    assert_eq!(
        response.status(),
        expected_status,
        "Response body: {}",
        response.text().await.unwrap()
    );
}

#[tokio::test]
async fn test_valid_pak_used_to_authenticate_from_cache_updates_last_used_at() {
    use feature_flags::{
        api::pak_usage::debounce_key, config::Config, utils::test_utils::TestContext,
    };
    use reqwest;

    let config = Config::default_test_config();
    let context = TestContext::new(Some(&config)).await;

    let team = context.insert_new_team(None).await.unwrap();
    let org_id = context.get_organization_id_for_team(&team).await.unwrap();

    let user_email = TestContext::generate_test_email("pak_cache_last_used");
    let user_id = context
        .create_user(&user_email, &org_id, team.id)
        .await
        .unwrap();
    context
        .add_user_to_organization(user_id, &org_id, 15)
        .await
        .unwrap();

    let (pak_id, api_key_value) = context
        .create_personal_api_key(
            user_id,
            "Test PAK Cache",
            vec!["feature_flag:read"],
            None,
            None,
        )
        .await
        .unwrap();

    context.populate_cache_for_team(team.id).await.unwrap();

    let server = common::ServerHandle::for_config(config.clone()).await;
    server.wait_until_ready().await;
    let client = reqwest::Client::new();
    let url = format!(
        "http://{}/flags/definitions?token={}",
        server.addr, team.api_token
    );

    // First request: populates the auth token cache and triggers last_used_at update
    let response = client
        .get(&url)
        .header("Authorization", format!("Bearer {api_key_value}"))
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), 200);

    // Poll for the spawned background task to complete the DB write
    poll_for_pak_last_used_at(
        &context,
        &pak_id,
        "Timed out waiting for background task to set last_used_at for PAK",
    )
    .await;

    // Clear the Redis debounce key so the next request can write to DB again
    let redis_client =
        feature_flags::utils::test_utils::setup_redis_client(Some(config.redis_url.clone())).await;
    redis_client
        .del(debounce_key(&pak_id))
        .await
        .expect("Failed to delete debounce key");

    // Reset last_used_at to NULL so we can verify the second request sets it
    let mut conn = context.get_non_persons_connection().await.unwrap();
    sqlx::query("UPDATE posthog_personalapikey SET last_used_at = NULL WHERE id = $1")
        .bind(&pak_id)
        .execute(&mut *conn)
        .await
        .unwrap();

    // Second request: auth comes from the token cache (no DB query for auth),
    // but should still trigger the last_used_at update via record_pak_last_used
    let response = client
        .get(&url)
        .header("Authorization", format!("Bearer {api_key_value}"))
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), 200);

    // Poll for the spawned background task to complete the DB write
    poll_for_pak_last_used_at(
        &context,
        &pak_id,
        "last_used_at should be set after authenticating from the auth token cache",
    )
    .await;
}

#[tokio::test]
async fn test_flag_definitions_with_legacy_secret_token_fallback() {
    use feature_flags::{config::Config, utils::test_utils::TestContext};
    use reqwest;

    let config = Config::default_test_config();
    let context = TestContext::new(Some(&config)).await;

    // create_team_with_secret_token creates a legacy phs_ token on posthog_team
    let (team, secret_token, _) = context
        .create_team_with_secret_token(None, None, None)
        .await
        .unwrap();

    // Do NOT insert a project secret API key — the phs_ token should fall back to legacy
    context.populate_cache_for_team(team.id).await.unwrap();

    let server = common::ServerHandle::for_config(config.clone()).await;
    let client = reqwest::Client::new();

    let response = client
        .get(format!(
            "http://{}/flags/definitions?token={}",
            server.addr, team.api_token
        ))
        .header("Authorization", format!("Bearer {secret_token}"))
        .send()
        .await
        .unwrap();

    assert_eq!(
        response.status(),
        200,
        "Response body: {}",
        response.text().await.unwrap()
    );
}

/// Tests the DB-backed rate limit allowlist end-to-end.
/// Combined into a single test to avoid DB-level interference — all scenarios
/// share the same `posthog_instancesetting` row.
///
/// Scenarios tested:
/// 1. Allowlisted team bypasses rate limit (200 instead of 429)
/// 2. Non-allowlisted team gets rate limited (429)
/// 3. With two teams, only the listed one bypasses
/// 4. Env var allowlist preserved when DB row is missing
/// 5. null DB value treated as empty allowlist
/// 6. Invalid team IDs skipped, valid ones kept
/// 7. Django-format JSON-encoded string (json.dumps wrapping)
#[tokio::test]
async fn test_db_rate_limit_allowlist() {
    use feature_flags::{config::Config, utils::test_utils::TestContext};

    let context = TestContext::new(None).await;

    // Clean up any leftover rows from a previous failed run
    context
        .delete_instance_setting("RATE_LIMITING_ALLOW_LIST_TEAMS")
        .await
        .unwrap();

    let (team1, secret1, _) = context
        .create_team_with_secret_token(None, None, None)
        .await
        .unwrap();

    let (team2, secret2, _) = context
        .create_team_with_secret_token(None, None, None)
        .await
        .unwrap();

    // --- Scenario 1: allowlisted team bypasses rate limit ---
    {
        let mut config = Config::default_test_config();
        config.flag_definitions_rate_limits = format!(r#"{{"{}": "1/second"}}"#, team1.id)
            .parse()
            .unwrap();

        context
            .set_instance_setting("RATE_LIMITING_ALLOW_LIST_TEAMS", &team1.id.to_string())
            .await
            .unwrap();

        let redis_client =
            feature_flags::utils::test_utils::setup_redis_client(Some(config.redis_url.clone()))
                .await;
        context
            .populate_flag_definitions_cache(redis_client, team1.id)
            .await
            .unwrap();

        let server = common::ServerHandle::for_config(config).await;
        let client = reqwest::Client::new();

        // First request triggers DB refresh
        let resp = client
            .get(format!(
                "http://{}/flags/definitions?token={}",
                server.addr, team1.api_token
            ))
            .header("Authorization", format!("Bearer {secret1}"))
            .send()
            .await
            .unwrap();
        assert_eq!(resp.status(), 200);

        // Second request would be rate limited, but allowlist bypasses it
        let resp = client
            .get(format!(
                "http://{}/flags/definitions?token={}",
                server.addr, team1.api_token
            ))
            .header("Authorization", format!("Bearer {secret1}"))
            .send()
            .await
            .unwrap();
        assert_eq!(
            resp.status(),
            200,
            "Allowlisted team should bypass rate limit"
        );
    }

    // --- Scenario 2: non-allowlisted team gets rate limited ---
    {
        let mut config = Config::default_test_config();
        config.flag_definitions_rate_limits = format!(r#"{{"{}": "1/second"}}"#, team1.id)
            .parse()
            .unwrap();

        context
            .delete_instance_setting("RATE_LIMITING_ALLOW_LIST_TEAMS")
            .await
            .unwrap();

        let redis_client =
            feature_flags::utils::test_utils::setup_redis_client(Some(config.redis_url.clone()))
                .await;
        context
            .populate_flag_definitions_cache(redis_client, team1.id)
            .await
            .unwrap();

        let server = common::ServerHandle::for_config(config).await;
        let client = reqwest::Client::new();

        let resp = client
            .get(format!(
                "http://{}/flags/definitions?token={}",
                server.addr, team1.api_token
            ))
            .header("Authorization", format!("Bearer {secret1}"))
            .send()
            .await
            .unwrap();
        assert_eq!(resp.status(), 200);

        let resp = client
            .get(format!(
                "http://{}/flags/definitions?token={}",
                server.addr, team1.api_token
            ))
            .header("Authorization", format!("Bearer {secret1}"))
            .send()
            .await
            .unwrap();
        assert_eq!(
            resp.status(),
            429,
            "Non-allowlisted team should be rate limited"
        );
    }

    // --- Scenario 3: only listed team bypasses, other team gets limited ---
    {
        let mut config = Config::default_test_config();
        config.flag_definitions_rate_limits = format!(
            r#"{{"{}": "1/second", "{}": "1/second"}}"#,
            team1.id, team2.id
        )
        .parse()
        .unwrap();

        context
            .set_instance_setting("RATE_LIMITING_ALLOW_LIST_TEAMS", &team1.id.to_string())
            .await
            .unwrap();

        let redis_client =
            feature_flags::utils::test_utils::setup_redis_client(Some(config.redis_url.clone()))
                .await;
        context
            .populate_flag_definitions_cache(redis_client.clone(), team1.id)
            .await
            .unwrap();
        context
            .populate_flag_definitions_cache(redis_client, team2.id)
            .await
            .unwrap();

        let server = common::ServerHandle::for_config(config).await;
        let client = reqwest::Client::new();

        // Team1 (allowlisted) can make many requests
        for i in 0..5 {
            let resp = client
                .get(format!(
                    "http://{}/flags/definitions?token={}",
                    server.addr, team1.api_token
                ))
                .header("Authorization", format!("Bearer {secret1}"))
                .send()
                .await
                .unwrap();
            assert_eq!(
                resp.status(),
                200,
                "Allowlisted team1 request {i} should succeed"
            );
        }

        // Team2 (not allowlisted) should eventually be rate limited
        let mut saw_rate_limit = false;
        for _ in 0..10 {
            let resp = client
                .get(format!(
                    "http://{}/flags/definitions?token={}",
                    server.addr, team2.api_token
                ))
                .header("Authorization", format!("Bearer {secret2}"))
                .send()
                .await
                .unwrap();
            if resp.status() == 429 {
                saw_rate_limit = true;
                break;
            }
        }
        assert!(
            saw_rate_limit,
            "Non-allowlisted team2 should eventually be rate limited"
        );
    }

    // --- Scenario 4: env var allowlist preserved when DB row is missing ---
    {
        // Configure team1 as allowlisted via the env var (set at server startup)
        let mut config = Config::default_test_config();
        config.flag_definitions_rate_limits = format!(r#"{{"{}": "1/second"}}"#, team1.id)
            .parse()
            .unwrap();
        config.rate_limiting_allow_list_teams = team1.id.to_string().parse().unwrap();

        // Ensure no DB row exists — env var default should be kept
        context
            .delete_instance_setting("RATE_LIMITING_ALLOW_LIST_TEAMS")
            .await
            .unwrap();

        let redis_client =
            feature_flags::utils::test_utils::setup_redis_client(Some(config.redis_url.clone()))
                .await;
        context
            .populate_flag_definitions_cache(redis_client, team1.id)
            .await
            .unwrap();

        let server = common::ServerHandle::for_config(config).await;
        let client = reqwest::Client::new();

        // First request triggers DB refresh — row missing, so env var default is kept
        let resp = client
            .get(format!(
                "http://{}/flags/definitions?token={}",
                server.addr, team1.api_token
            ))
            .header("Authorization", format!("Bearer {secret1}"))
            .send()
            .await
            .unwrap();
        assert_eq!(resp.status(), 200);

        // Second request: team1 should still bypass via env var allowlist
        let resp = client
            .get(format!(
                "http://{}/flags/definitions?token={}",
                server.addr, team1.api_token
            ))
            .header("Authorization", format!("Bearer {secret1}"))
            .send()
            .await
            .unwrap();
        assert_eq!(
            resp.status(),
            200,
            "Env var allowlist should be preserved when DB row is missing"
        );
    }

    // --- Scenario 5: null DB value treated as empty allowlist ---
    {
        let mut config = Config::default_test_config();
        config.flag_definitions_rate_limits = format!(r#"{{"{}": "1/second"}}"#, team1.id)
            .parse()
            .unwrap();

        context
            .set_instance_setting("RATE_LIMITING_ALLOW_LIST_TEAMS", "null")
            .await
            .unwrap();

        let redis_client =
            feature_flags::utils::test_utils::setup_redis_client(Some(config.redis_url.clone()))
                .await;
        context
            .populate_flag_definitions_cache(redis_client, team1.id)
            .await
            .unwrap();

        let server = common::ServerHandle::for_config(config).await;
        let client = reqwest::Client::new();

        let resp = client
            .get(format!(
                "http://{}/flags/definitions?token={}",
                server.addr, team1.api_token
            ))
            .header("Authorization", format!("Bearer {secret1}"))
            .send()
            .await
            .unwrap();
        assert_eq!(resp.status(), 200);

        // null means empty allowlist — team should be rate limited
        let resp = client
            .get(format!(
                "http://{}/flags/definitions?token={}",
                server.addr, team1.api_token
            ))
            .header("Authorization", format!("Bearer {secret1}"))
            .send()
            .await
            .unwrap();
        assert_eq!(
            resp.status(),
            429,
            "null DB value should be treated as empty allowlist"
        );
    }

    // --- Scenario 6: invalid team IDs skipped, valid ones kept ---
    {
        let mut config = Config::default_test_config();
        config.flag_definitions_rate_limits = format!(r#"{{"{}": "1/second"}}"#, team1.id)
            .parse()
            .unwrap();

        // Mix of valid and invalid IDs — team1 should still be allowlisted
        context
            .set_instance_setting(
                "RATE_LIMITING_ALLOW_LIST_TEAMS",
                &format!("{},abc,xyz", team1.id),
            )
            .await
            .unwrap();

        let redis_client =
            feature_flags::utils::test_utils::setup_redis_client(Some(config.redis_url.clone()))
                .await;
        context
            .populate_flag_definitions_cache(redis_client, team1.id)
            .await
            .unwrap();

        let server = common::ServerHandle::for_config(config).await;
        let client = reqwest::Client::new();

        let resp = client
            .get(format!(
                "http://{}/flags/definitions?token={}",
                server.addr, team1.api_token
            ))
            .header("Authorization", format!("Bearer {secret1}"))
            .send()
            .await
            .unwrap();
        assert_eq!(resp.status(), 200);

        // team1 is in the valid portion of the allowlist — should bypass
        let resp = client
            .get(format!(
                "http://{}/flags/definitions?token={}",
                server.addr, team1.api_token
            ))
            .header("Authorization", format!("Bearer {secret1}"))
            .send()
            .await
            .unwrap();
        assert_eq!(
            resp.status(),
            200,
            "Valid team IDs should be kept even when invalid ones are present"
        );
    }

    // --- Scenario 7: Django-format JSON-encoded string ---
    {
        let mut config = Config::default_test_config();
        config.flag_definitions_rate_limits = format!(r#"{{"{}": "1/second"}}"#, team1.id)
            .parse()
            .unwrap();

        // Django's set_instance_setting calls json.dumps(value), so "23047"
        // is stored as "\"23047\"" in raw_value
        context
            .set_instance_setting(
                "RATE_LIMITING_ALLOW_LIST_TEAMS",
                &format!("\"{}\"", team1.id),
            )
            .await
            .unwrap();

        let redis_client =
            feature_flags::utils::test_utils::setup_redis_client(Some(config.redis_url.clone()))
                .await;
        context
            .populate_flag_definitions_cache(redis_client, team1.id)
            .await
            .unwrap();

        let server = common::ServerHandle::for_config(config).await;
        let client = reqwest::Client::new();

        let resp = client
            .get(format!(
                "http://{}/flags/definitions?token={}",
                server.addr, team1.api_token
            ))
            .header("Authorization", format!("Bearer {secret1}"))
            .send()
            .await
            .unwrap();
        assert_eq!(resp.status(), 200);

        // team1 should bypass via JSON-encoded allowlist
        let resp = client
            .get(format!(
                "http://{}/flags/definitions?token={}",
                server.addr, team1.api_token
            ))
            .header("Authorization", format!("Bearer {secret1}"))
            .send()
            .await
            .unwrap();
        assert_eq!(
            resp.status(),
            200,
            "Django-format JSON-encoded allowlist should work"
        );
    }

    // Clean up
    context
        .delete_instance_setting("RATE_LIMITING_ALLOW_LIST_TEAMS")
        .await
        .unwrap();
}
