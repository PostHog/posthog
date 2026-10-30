use anyhow::Result;
use reqwest::header::CONTENT_TYPE;
use reqwest::StatusCode;
use rstest::rstest;
use serde_json::{json, Value};

use feature_flags::config::DEFAULT_TEST_CONFIG;
use feature_flags::flags::flag_analytics::{current_bucket, get_team_request_key};
use feature_flags::flags::flag_request::FlagRequestType;
use feature_flags::team::request_blocklist::{BlockedHosts, BlockedIps};
use feature_flags::team::team_models::Team;
use feature_flags::utils::test_utils::{
    insert_config_in_hypercache, insert_flags_for_team_in_redis, insert_new_team_in_redis,
    setup_redis_client, update_team_in_hypercache, TestContext,
};

use crate::common::*;

pub mod common;

const INTERNAL_TOKEN: &str = "internal-test-token";

/// Server with one flag for a team that blocks `example.com` and a mix of IPv4 and IPv6
/// entries, so a test can tell the blocked response (no flags) from evaluation (the flag).
/// The cached remote config enables session recording, so a `config=true` response built
/// from it differs from the minimal response.
async fn setup_server_with_blocklist() -> Result<(ServerHandle, Team)> {
    let mut config = DEFAULT_TEST_CONFIG.clone();
    config.internal_request_token = Some(INTERNAL_TOKEN.to_string());
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
    insert_config_in_hypercache(
        client.clone(),
        &team.api_token,
        json!({
            "supportedCompression": ["gzip", "gzip-js"],
            "sessionRecording": {"endpoint": "/s/"},
        }),
    )
    .await?;
    let server = ServerHandle::for_config(config).await;
    Ok((server, team))
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
    // An unblocked response either omits `sessionRecording` or copies the enabled object
    // from the cached remote config. Only the minimal response sets it to `false`.
    assert_eq!(body["sessionRecording"], json!(false));
    assert_eq!(body["supportedCompression"], json!(["gzip", "gzip-js"]));
}

#[rstest]
#[case::origin_host("/flags", &[("Origin", "https://example.com")])]
#[case::origin_subdomain("/flags", &[("Origin", "https://app.example.com:8443")])]
#[case::referer_fallback("/flags", &[("Origin", "null"), ("Referer", "https://www.example.com/page")])]
#[case::ipv4_address("/flags", &[("X-Forwarded-For", "203.0.113.7")])]
#[case::ipv4_cidr("/flags", &[("X-Forwarded-For", "198.51.100.42")])]
#[case::ipv6_cidr("/flags", &[("X-Forwarded-For", "2001:db8:abcd:12::1")])]
#[case::blocked_ip_behind_spoofed_entry("/flags", &[("X-Forwarded-For", "192.0.2.1, 203.0.113.7")])]
#[case::decide_host("/decide", &[("Origin", "https://example.com")])]
#[case::decide_ip("/decide", &[("X-Forwarded-For", "203.0.113.7")])]
#[tokio::test]
async fn blocked_caller_gets_minimal_response(
    #[case] path: &str,
    #[case] headers: &[(&str, &str)],
) -> Result<()> {
    let (server, team) = setup_server_with_blocklist().await?;

    let res = post(&server, path, &team.api_token, "2", headers).await;

    assert_eq!(res.status(), StatusCode::OK);
    assert_minimal_response(&res.json().await?, "flags");
    Ok(())
}

#[tokio::test]
async fn blocked_caller_through_legacy_decide_proxy_gets_minimal_response() -> Result<()> {
    let (server, team) = setup_server_with_blocklist().await?;

    let res = post(
        &server,
        "/decide",
        &team.api_token,
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
#[case::internal_request_from_blocked_ip(&[("Authorization", "Bearer internal-test-token"), ("X-Forwarded-For", "203.0.113.7")])]
#[tokio::test]
async fn unblocked_caller_reaches_evaluation(#[case] headers: &[(&str, &str)]) -> Result<()> {
    let (server, team) = setup_server_with_blocklist().await?;

    let res = post(&server, "/flags", &team.api_token, "1", headers).await;

    assert_eq!(res.status(), StatusCode::OK);
    let body: Value = res.json().await?;
    assert!(
        body["featureFlags"].get("flag1").is_some(),
        "unblocked request should evaluate flags; got {body}"
    );
    Ok(())
}

#[rstest]
#[case::blocked(&[("Origin", "https://example.com")], false)]
#[case::unblocked(&[("Origin", "https://example.org")], true)]
#[tokio::test]
async fn only_unblocked_caller_is_billed(
    #[case] headers: &[(&str, &str)],
    #[case] billed: bool,
) -> Result<()> {
    let (server, team) = setup_server_with_blocklist().await?;
    let client = setup_redis_client(Some(DEFAULT_TEST_CONFIG.redis_url.clone())).await;
    let billing_key = get_team_request_key(team.id, FlagRequestType::Decide);
    client.del(billing_key.clone()).await.unwrap();

    // Bracket the request: the record lands in whichever 2-minute bucket it crosses.
    let bucket_before = current_bucket();
    let res = post(&server, "/flags", &team.api_token, "2", headers).await;
    assert_eq!(res.status(), StatusCode::OK);
    let bucket_after = current_bucket();

    if billed {
        let counter = poll_for_billing_counter_across_buckets(
            &client,
            &billing_key,
            bucket_before,
            bucket_after,
        )
        .await;
        assert_eq!(counter, "1");
    } else {
        // Wait ~5 flush windows so a delayed first tick cannot hide an erroneous `record()`.
        tokio::time::sleep(std::time::Duration::from_millis(500)).await;
        for bucket in bucket_before..=bucket_after {
            let counter = client.hget(billing_key.clone(), bucket.to_string()).await;
            assert!(counter.is_err(), "blocked request was billed: {counter:?}");
        }
    }
    Ok(())
}
