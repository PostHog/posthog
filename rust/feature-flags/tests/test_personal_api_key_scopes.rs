mod common;

use feature_flags::config::DEFAULT_TEST_CONFIG;
use feature_flags::utils::test_utils::TestContext;
use uuid::Uuid;

/// Helper: Clean up test data (PAK, organization memberships, and user)
async fn cleanup_test_data(ctx: &TestContext, pak_id: String, user_id: i32) {
    let mut conn = ctx.get_non_persons_connection().await.unwrap();
    sqlx::query("DELETE FROM posthog_personalapikey WHERE id = $1")
        .bind(pak_id)
        .execute(&mut *conn)
        .await
        .unwrap();
    sqlx::query("DELETE FROM posthog_organizationmembership WHERE user_id = $1")
        .bind(user_id)
        .execute(&mut *conn)
        .await
        .unwrap();
    sqlx::query("DELETE FROM posthog_user WHERE id = $1")
        .bind(user_id)
        .execute(&mut *conn)
        .await
        .unwrap();
}

#[tokio::test]
async fn test_personal_api_key_scoped_teams_allowed() {
    let config = DEFAULT_TEST_CONFIG.clone();
    let ctx = TestContext::new(Some(&config)).await;

    // Create two teams
    let team1 = ctx.insert_new_team(None).await.unwrap();
    let _team2 = ctx.insert_new_team(None).await.unwrap();

    let org_id = ctx.get_organization_id_for_team(&team1).await.unwrap();
    let user_email = format!("test_{}@example.com", Uuid::new_v4());
    let user_id = ctx
        .create_user_with_options(&user_email, &org_id, Some(team1.id), true)
        .await
        .unwrap();
    ctx.add_user_to_organization(user_id, &org_id, 15)
        .await
        .unwrap();
    let (pak_id, secure_value) = ctx
        .create_personal_api_key(
            user_id,
            "Test PAK",
            vec!["feature_flag:read"],
            Some(vec![team1.id]),
            None,
        )
        .await
        .unwrap();

    // Start server
    let server = common::ServerHandle::for_config(config.clone()).await;
    tokio::time::sleep(std::time::Duration::from_millis(200)).await;
    let client = reqwest::Client::new();

    // Test accessing team1 (allowed)

    let response = client
        .get(format!(
            "http://{}/flags/definitions?token={}",
            server.addr, team1.api_token
        ))
        .header("Authorization", format!("Bearer {secure_value}"))
        .send()
        .await
        .unwrap();

    assert_ne!(
        response.status(),
        401,
        "Should authenticate when accessing allowed team"
    );

    cleanup_test_data(&ctx, pak_id, user_id).await;
}

#[tokio::test]
async fn test_personal_api_key_scoped_organizations_allowed() {
    let config = DEFAULT_TEST_CONFIG.clone();
    let ctx = TestContext::new(Some(&config)).await;

    // Create a team
    let team = ctx.insert_new_team(None).await.unwrap();

    let org_id = ctx.get_organization_id_for_team(&team).await.unwrap();
    let org_id_str = org_id.to_string();
    let user_email = format!("test_{}@example.com", Uuid::new_v4());
    let user_id = ctx
        .create_user_with_options(&user_email, &org_id, Some(team.id), true)
        .await
        .unwrap();
    let (pak_id, secure_value) = ctx
        .create_personal_api_key(
            user_id,
            "Test PAK",
            vec!["feature_flag:read"],
            None,
            Some(vec![org_id_str]),
        )
        .await
        .unwrap();

    // Start server
    let server = common::ServerHandle::for_config(config.clone()).await;
    tokio::time::sleep(std::time::Duration::from_millis(200)).await;
    let client = reqwest::Client::new();

    // Test accessing team in allowed organization

    let response = client
        .get(format!(
            "http://{}/flags/definitions?token={}",
            server.addr, team.api_token
        ))
        .header("Authorization", format!("Bearer {secure_value}"))
        .send()
        .await
        .unwrap();

    assert_ne!(
        response.status(),
        401,
        "Should authenticate when accessing team in allowed organization"
    );

    cleanup_test_data(&ctx, pak_id, user_id).await;
}

#[tokio::test]
async fn test_personal_api_key_unrestricted_teams_null() {
    let config = DEFAULT_TEST_CONFIG.clone();
    let ctx = TestContext::new(Some(&config)).await;

    // Create two teams
    let team1 = ctx.insert_new_team(None).await.unwrap();
    let team2 = ctx.insert_new_team(None).await.unwrap();

    let org_id = ctx.get_organization_id_for_team(&team1).await.unwrap();
    let user_email = format!("test_{}@example.com", Uuid::new_v4());
    let user_id = ctx
        .create_user_with_options(&user_email, &org_id, Some(team1.id), true)
        .await
        .unwrap();
    ctx.add_user_to_organization(user_id, &org_id, 15)
        .await
        .unwrap();
    let (pak_id, secure_value) = ctx
        .create_personal_api_key(user_id, "Test PAK", vec!["feature_flag:read"], None, None)
        .await
        .unwrap();

    // Start server
    let server = common::ServerHandle::for_config(config.clone()).await;
    tokio::time::sleep(std::time::Duration::from_millis(200)).await;
    let client = reqwest::Client::new();

    // Test accessing team1 (should be allowed - NULL means all teams)

    let response = client
        .get(format!(
            "http://{}/flags/definitions?token={}",
            server.addr, team1.api_token
        ))
        .header("Authorization", format!("Bearer {secure_value}"))
        .send()
        .await
        .unwrap();

    assert_ne!(
        response.status(),
        401,
        "Should authenticate when scoped_teams is NULL (unrestricted)"
    );

    // Test accessing team2 (should also be allowed - NULL means all teams)

    let response = client
        .get(format!(
            "http://{}/flags/definitions?token={}",
            server.addr, team2.api_token
        ))
        .header("Authorization", format!("Bearer {secure_value}"))
        .send()
        .await
        .unwrap();

    assert_ne!(
        response.status(),
        401,
        "Should authenticate for any team when scoped_teams is NULL"
    );

    cleanup_test_data(&ctx, pak_id, user_id).await;
}

#[tokio::test]
async fn test_personal_api_key_unrestricted_teams_empty_array() {
    let config = DEFAULT_TEST_CONFIG.clone();
    let ctx = TestContext::new(Some(&config)).await;

    // Create two teams
    let team1 = ctx.insert_new_team(None).await.unwrap();
    let team2 = ctx.insert_new_team(None).await.unwrap();

    let org_id = ctx.get_organization_id_for_team(&team1).await.unwrap();
    let user_email = format!("test_{}@example.com", Uuid::new_v4());
    let user_id = ctx
        .create_user_with_options(&user_email, &org_id, Some(team1.id), true)
        .await
        .unwrap();
    ctx.add_user_to_organization(user_id, &org_id, 15)
        .await
        .unwrap();
    let (pak_id, secure_value) = ctx
        .create_personal_api_key(
            user_id,
            "Test PAK",
            vec!["feature_flag:read"],
            Some(vec![]),
            None,
        )
        .await
        .unwrap();

    // Start server
    let server = common::ServerHandle::for_config(config.clone()).await;
    tokio::time::sleep(std::time::Duration::from_millis(200)).await;
    let client = reqwest::Client::new();

    // Test accessing team1 (should be allowed - empty array means all teams)

    let response = client
        .get(format!(
            "http://{}/flags/definitions?token={}",
            server.addr, team1.api_token
        ))
        .header("Authorization", format!("Bearer {secure_value}"))
        .send()
        .await
        .unwrap();

    assert_ne!(
        response.status(),
        401,
        "Should authenticate when scoped_teams is empty array (unrestricted)"
    );

    // Test accessing team2 (should also be allowed - empty array means all teams)

    let response = client
        .get(format!(
            "http://{}/flags/definitions?token={}",
            server.addr, team2.api_token
        ))
        .header("Authorization", format!("Bearer {secure_value}"))
        .send()
        .await
        .unwrap();

    assert_ne!(
        response.status(),
        401,
        "Should authenticate for any team when scoped_teams is empty array"
    );

    cleanup_test_data(&ctx, pak_id, user_id).await;
}

#[tokio::test]
async fn test_personal_api_key_unrestricted_organizations_null() {
    let config = DEFAULT_TEST_CONFIG.clone();
    let ctx = TestContext::new(Some(&config)).await;

    // Create teams in two different orgs
    let team1 = ctx.insert_new_team(None).await.unwrap();
    let team2 = ctx.insert_new_team(None).await.unwrap();

    let org_id = ctx.get_organization_id_for_team(&team1).await.unwrap();
    let user_email = format!("test_{}@example.com", Uuid::new_v4());
    let user_id = ctx
        .create_user_with_options(&user_email, &org_id, Some(team1.id), true)
        .await
        .unwrap();
    ctx.add_user_to_organization(user_id, &org_id, 15)
        .await
        .unwrap();
    let (pak_id, secure_value) = ctx
        .create_personal_api_key(
            user_id,
            "Test PAK - Org Unrestricted",
            vec!["feature_flag:read"],
            None,
            None,
        )
        .await
        .unwrap();

    // Start server
    let server = common::ServerHandle::for_config(config.clone()).await;
    tokio::time::sleep(std::time::Duration::from_millis(200)).await;
    let client = reqwest::Client::new();

    // Test accessing team1 (should be allowed - NULL means all orgs)

    let response = client
        .get(format!(
            "http://{}/flags/definitions?token={}",
            server.addr, team1.api_token
        ))
        .header("Authorization", format!("Bearer {secure_value}"))
        .send()
        .await
        .unwrap();

    assert_ne!(
        response.status(),
        401,
        "Should authenticate when scoped_organizations is NULL (unrestricted)"
    );

    // Test accessing team2 in different org (should also be allowed - NULL means all orgs)

    let response = client
        .get(format!(
            "http://{}/flags/definitions?token={}",
            server.addr, team2.api_token
        ))
        .header("Authorization", format!("Bearer {secure_value}"))
        .send()
        .await
        .unwrap();

    assert_ne!(
        response.status(),
        401,
        "Should authenticate for any org when scoped_organizations is NULL"
    );

    cleanup_test_data(&ctx, pak_id, user_id).await;
}

#[tokio::test]
async fn test_personal_api_key_mixed_scopes_both_valid() {
    let config = DEFAULT_TEST_CONFIG.clone();
    let ctx = TestContext::new(Some(&config)).await;

    // Create a team
    let team = ctx.insert_new_team(None).await.unwrap();

    let org_id = ctx.get_organization_id_for_team(&team).await.unwrap();
    let org_id_str = org_id.to_string();
    let user_email = format!("test_{}@example.com", Uuid::new_v4());
    let user_id = ctx
        .create_user_with_options(&user_email, &org_id, Some(team.id), true)
        .await
        .unwrap();
    let (pak_id, secure_value) = ctx
        .create_personal_api_key(
            user_id,
            "Test PAK - Mixed Scopes",
            vec!["feature_flag:read"],
            Some(vec![team.id]),
            Some(vec![org_id_str.clone()]),
        )
        .await
        .unwrap();

    // Start server
    let server = common::ServerHandle::for_config(config.clone()).await;
    tokio::time::sleep(std::time::Duration::from_millis(200)).await;
    let client = reqwest::Client::new();

    // Test accessing team (should be allowed - both scopes match)

    let response = client
        .get(format!(
            "http://{}/flags/definitions?token={}",
            server.addr, team.api_token
        ))
        .header("Authorization", format!("Bearer {secure_value}"))
        .send()
        .await
        .unwrap();

    assert_ne!(
        response.status(),
        401,
        "Should authenticate when both scoped_teams and scoped_organizations match"
    );

    cleanup_test_data(&ctx, pak_id, user_id).await;
}

#[tokio::test]
async fn test_personal_api_key_mixed_scopes_team_valid_org_invalid() {
    let config = DEFAULT_TEST_CONFIG.clone();
    let ctx = TestContext::new(Some(&config)).await;

    // Create two teams in different organizations
    let org1_id = Uuid::new_v4();
    let org2_id = Uuid::new_v4();
    let team1 = ctx
        .insert_new_team_with_org(None, &org1_id.to_string())
        .await
        .unwrap();
    let _team2 = ctx
        .insert_new_team_with_org(None, &org2_id.to_string())
        .await
        .unwrap();

    let org2_id_str = org2_id.to_string();

    let user_email = format!("test_{}@example.com", Uuid::new_v4());
    let user_id = ctx
        .create_user_with_options(&user_email, &org1_id, Some(team1.id), true)
        .await
        .unwrap();
    let (pak_id, secure_value) = ctx
        .create_personal_api_key(
            user_id,
            "Test PAK - Mixed Invalid",
            vec!["feature_flag:read"],
            Some(vec![team1.id]),
            Some(vec![org2_id_str.clone()]),
        )
        .await
        .unwrap();

    // Start server
    let server = common::ServerHandle::for_config(config.clone()).await;
    tokio::time::sleep(std::time::Duration::from_millis(200)).await;
    let client = reqwest::Client::new();

    // Test accessing team1 (should be denied - org doesn't match)

    let response = client
        .get(format!(
            "http://{}/flags/definitions?token={}",
            server.addr, team1.api_token
        ))
        .header("Authorization", format!("Bearer {secure_value}"))
        .send()
        .await
        .unwrap();

    assert_eq!(
        response.status(),
        401,
        "Should return 401 when scoped_organizations doesn't match team's org"
    );

    cleanup_test_data(&ctx, pak_id, user_id).await;
}

#[tokio::test]
async fn test_personal_api_key_user_without_current_team() {
    let config = DEFAULT_TEST_CONFIG.clone();
    let ctx = TestContext::new(Some(&config)).await;

    // Create a team for organization context
    let team = ctx.insert_new_team(None).await.unwrap();

    let org_id = ctx.get_organization_id_for_team(&team).await.unwrap();

    // Create a user WITHOUT current_team_id
    let user_email = format!("test_{}@example.com", Uuid::new_v4());
    let user_id = ctx
        .create_user_with_options(&user_email, &org_id, None, true)
        .await
        .unwrap();
    ctx.add_user_to_organization(user_id, &org_id, 15)
        .await
        .unwrap();
    let (pak_id, secure_value) = ctx
        .create_personal_api_key(
            user_id,
            "Test PAK - No Team",
            vec!["feature_flag:read"],
            None,
            None,
        )
        .await
        .unwrap();

    // Start server
    let server = common::ServerHandle::for_config(config.clone()).await;
    tokio::time::sleep(std::time::Duration::from_millis(200)).await;
    let client = reqwest::Client::new();

    // Test authentication succeeds but cache miss returns 503
    // (Users without current_team_id can still authenticate if they're in the org)

    let response = client
        .get(format!(
            "http://{}/flags/definitions?token={}",
            server.addr, team.api_token
        ))
        .header("Authorization", format!("Bearer {secure_value}"))
        .send()
        .await
        .unwrap();

    assert_eq!(
        response.status(),
        503,
        "Should return 503 on cache miss (auth succeeds for users without current_team_id)"
    );

    cleanup_test_data(&ctx, pak_id, user_id).await;
}

#[tokio::test]
async fn test_personal_api_key_user_member_of_multiple_orgs() {
    let config = DEFAULT_TEST_CONFIG.clone();
    let ctx = TestContext::new(Some(&config)).await;

    // Create two organizations with teams
    let org1_id = Uuid::new_v4();
    let org2_id = Uuid::new_v4();
    let team1 = ctx
        .insert_new_team_with_org(None, &org1_id.to_string())
        .await
        .unwrap();
    let team2 = ctx
        .insert_new_team_with_org(None, &org2_id.to_string())
        .await
        .unwrap();

    // Create a user with current_organization_id set to org1
    let user_email = format!("test_{}@example.com", Uuid::new_v4());
    let user_id = ctx
        .create_user_with_options(&user_email, &org1_id, Some(team1.id), true)
        .await
        .unwrap();

    // Add user as member of BOTH organizations
    ctx.add_user_to_organization(user_id, &org1_id, 15)
        .await
        .unwrap();
    ctx.add_user_to_organization(user_id, &org2_id, 15)
        .await
        .unwrap();

    // Create personal API key with no scopes (unrestricted)
    let (pak_id, secure_value) = ctx
        .create_personal_api_key(user_id, "Test PAK", vec!["feature_flag:read"], None, None)
        .await
        .unwrap();

    // Start server
    let server = common::ServerHandle::for_config(config.clone()).await;
    tokio::time::sleep(std::time::Duration::from_millis(200)).await;
    let client = reqwest::Client::new();

    // Test accessing team2 in org2
    // User is a member of org2, even though current_organization_id is org1
    // This should SUCCEED because the user is a member of org2

    let response = client
        .get(format!(
            "http://{}/flags/definitions?token={}",
            server.addr, team2.api_token
        ))
        .header("Authorization", format!("Bearer {secure_value}"))
        .send()
        .await
        .unwrap();

    assert_ne!(
        response.status(),
        401,
        "Should authenticate when user is a member of the team's org, even if current_organization_id differs"
    );

    cleanup_test_data(&ctx, pak_id, user_id).await;
}
