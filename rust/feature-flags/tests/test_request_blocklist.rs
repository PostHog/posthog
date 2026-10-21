use anyhow::Result;
use reqwest::header::CONTENT_TYPE;
use reqwest::StatusCode;
use rstest::rstest;
use serde_json::{json, Value};

use feature_flags::config::DEFAULT_TEST_CONFIG;
use feature_flags::team::request_blocklist::{BlockedHosts, BlockedIps};
use feature_flags::utils::test_utils::{
    insert_flags_for_team_in_redis, insert_new_team_in_redis, setup_redis_client,
    update_team_in_hypercache, TestContext,
};

use crate::common::*;

pub mod common;

/// Server with one flag for a team that blocks `example.com` and a mix of IPv4 and IPv6
/// entries, so a test can tell the blocked response (no flags) from evaluation (the flag).
async fn setup_server_with_blocklist() -> Result<(ServerHandle, String)> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let mut team = insert_new_team_in_redis(client.clone()).await.unwrap();
    team.flags_blocked_hosts = BlockedHosts::from(vec!["example.com".to_string()]);
    team.flags_blocked_ips = BlockedIps::from(vec![
        "203.0.113.7".to_string(),
        "198.51.100.0/24".to_string(),
        "2001:db8:abcd::/48".to_string(),
    ]);
    update_team_in_hypercache(client.clone(), &team).await?;
    let context = TestContext::new(None).await;
    context.insert_new_team(Some(team.id)).await.unwrap();
    insert_flags_for_team_in_redis(client.clone(), team.id, None)
        .await
        .unwrap();
    let server = ServerHandle::for_config(config).await;
    Ok((server, team.api_token))
}

async fn post(
    server: &ServerHandle,
    path: &str,
    token: &str,
    version: &str,
    headers: &[(&str, &str)],
) -> reqwest::Response {
    let mut req = reqwest::Client::new()
        .post(format!("http://{}{}?v={}", server.addr, path, version))
        .header(CONTENT_TYPE, "application/json")
        .body(json!({"token": token, "distinct_id": "any-id"}).to_string());
    for (name, value) in headers {
        req = req.header(*name, *value);
    }
    req.send().await.expect("failed to send request")
}

fn assert_minimal_response(body: &Value, flags_key: &str) {
    assert_eq!(
        body[flags_key],
        json!({}),
        "blocked request evaluated flags"
    );
    // Only the minimal response carries `supportedCompression`, so it tells the
    // blocklist response apart from an empty evaluation.
    assert_eq!(body["supportedCompression"], json!(["gzip", "gzip-js"]));
}

#[rstest]
#[case::origin_host("/flags", &[("Origin", "https://example.com")])]
#[case::origin_subdomain("/flags", &[("Origin", "https://app.example.com:8443")])]
#[case::referer_fallback("/flags", &[("Origin", "null"), ("Referer", "https://www.example.com/page")])]
#[case::ipv4_address("/flags", &[("X-Forwarded-For", "203.0.113.7")])]
#[case::ipv4_cidr("/flags", &[("X-Forwarded-For", "198.51.100.42")])]
#[case::ipv6_cidr("/flags", &[("X-Forwarded-For", "2001:db8:abcd:12::1")])]
#[case::decide_host("/decide", &[("Origin", "https://example.com")])]
#[case::decide_ip("/decide", &[("X-Forwarded-For", "203.0.113.7")])]
#[tokio::test]
async fn blocked_caller_gets_minimal_response(
    #[case] path: &str,
    #[case] headers: &[(&str, &str)],
) -> Result<()> {
    let (server, token) = setup_server_with_blocklist().await?;

    let res = post(&server, path, &token, "2", headers).await;

    assert_eq!(res.status(), StatusCode::OK);
    assert_minimal_response(&res.json().await?, "flags");
    Ok(())
}

#[tokio::test]
async fn blocked_caller_through_legacy_decide_proxy_gets_minimal_response() -> Result<()> {
    let (server, token) = setup_server_with_blocklist().await?;

    let res = post(
        &server,
        "/decide",
        &token,
        "2",
        &[
            ("X-Original-Endpoint", "decide"),
            ("Origin", "https://example.com"),
        ],
    )
    .await;

    assert_eq!(res.status(), StatusCode::OK);
    assert_minimal_response(&res.json().await?, "featureFlags");
    Ok(())
}

#[rstest]
#[case::other_host(&[("Origin", "https://example.org"), ("X-Forwarded-For", "192.0.2.1")])]
#[case::lookalike_host(&[("Origin", "https://notexample.com"), ("X-Forwarded-For", "192.0.2.1")])]
#[case::ipv4_outside_cidr(&[("X-Forwarded-For", "198.51.101.1")])]
#[case::ipv6_outside_cidr(&[("X-Forwarded-For", "2001:db8:abce::1")])]
#[case::no_origin(&[])]
#[tokio::test]
async fn unblocked_caller_reaches_evaluation(#[case] headers: &[(&str, &str)]) -> Result<()> {
    let (server, token) = setup_server_with_blocklist().await?;

    let res = post(&server, "/flags", &token, "1", headers).await;

    assert_eq!(res.status(), StatusCode::OK);
    let body: Value = res.json().await?;
    assert!(
        body["featureFlags"].get("flag1").is_some(),
        "unblocked request should evaluate flags; got {body}"
    );
    Ok(())
}
