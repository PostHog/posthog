use anyhow::Result;
use reqwest::header::{CONTENT_TYPE, USER_AGENT};
use reqwest::StatusCode;
use rstest::rstest;
use serde_json::json;

use feature_flags::api::types::{FlagsResponse, LegacyFlagsResponse};
use feature_flags::config::{BotFilterMode, FlexBool, DEFAULT_TEST_CONFIG};
use feature_flags::utils::test_utils::{
    insert_flags_for_team_in_redis, insert_new_team_in_redis, setup_redis_client, TestContext,
};

use crate::common::*;

pub mod common;

const GOOGLEBOT_UA: &str =
    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)";
/// Reproduces the customer scenario: CloudFront rewrites the UA to its own
/// brand string before the request reaches us, so the UA matcher cannot fire.
const CLOUDFRONT_UA: &str = "Amazon CloudFront";
/// Inside a published Googlebot /27 (`66.249.66.0/27`). The classifier is
/// JSON-precise — 66.249.x.x is published as discrete /27s, with gaps
/// (e.g. .79.96/27 is NOT published), so we pin a stable interior IP from a
/// densely-covered /24.
const GOOGLEBOT_FORWARDED_IP: &str = "66.249.66.0";
/// Public-DNS IP, used as a benign baseline.
const BENIGN_FORWARDED_IP: &str = "8.8.8.8";

#[derive(Default)]
struct RequestOptions<'a> {
    user_agent: Option<&'a str>,
    forwarded_for: Option<&'a str>,
    /// Value for the `X-Original-Endpoint` header (set to `"decide"` to
    /// simulate the Python `/decide` proxy).
    original_endpoint: Option<&'a str>,
}

async fn post_flags(
    addr: std::net::SocketAddr,
    path: &str,
    body: serde_json::Value,
    user_agent: Option<&str>,
) -> reqwest::Response {
    post_flags_with_version(
        addr,
        path,
        body,
        RequestOptions {
            user_agent,
            ..Default::default()
        },
        "2",
    )
    .await
}

async fn post_flags_v1(
    addr: std::net::SocketAddr,
    path: &str,
    body: serde_json::Value,
    user_agent: Option<&str>,
) -> reqwest::Response {
    post_flags_with_version(
        addr,
        path,
        body,
        RequestOptions {
            user_agent,
            ..Default::default()
        },
        "1",
    )
    .await
}

async fn post_flags_with_options(
    addr: std::net::SocketAddr,
    path: &str,
    body: serde_json::Value,
    opts: RequestOptions<'_>,
) -> reqwest::Response {
    post_flags_with_version(addr, path, body, opts, "2").await
}

async fn post_flags_v1_with_options(
    addr: std::net::SocketAddr,
    path: &str,
    body: serde_json::Value,
    opts: RequestOptions<'_>,
) -> reqwest::Response {
    post_flags_with_version(addr, path, body, opts, "1").await
}

async fn post_flags_with_version(
    addr: std::net::SocketAddr,
    path: &str,
    body: serde_json::Value,
    opts: RequestOptions<'_>,
    version: &str,
) -> reqwest::Response {
    let client = reqwest::Client::new();
    let url = format!("http://{}{}?v={}", addr, path, version);
    let mut req = client
        .post(url)
        .body(body.to_string())
        .header(CONTENT_TYPE, "application/json");
    if let Some(ua) = opts.user_agent {
        req = req.header(USER_AGENT, ua);
    }
    if let Some(xff) = opts.forwarded_for {
        req = req.header("X-Forwarded-For", xff);
    }
    if let Some(endpoint) = opts.original_endpoint {
        req = req.header("X-Original-Endpoint", endpoint);
    }
    req.send().await.expect("failed to send request")
}

/// Server with one configured flag, so tests can tell a short-circuit
/// (empty flags) apart from full evaluation (flag present).
async fn setup_server_with_a_flag(
    config: feature_flags::config::Config,
) -> (ServerHandle, String /* token */) {
    let client = setup_redis_client(Some(config.redis_url.clone())).await;
    let team = insert_new_team_in_redis(client.clone()).await.unwrap();
    let token = team.api_token.clone();
    let context = TestContext::new(None).await;
    context.insert_new_team(Some(team.id)).await.unwrap();
    insert_flags_for_team_in_redis(client.clone(), team.id, None)
        .await
        .unwrap();
    let server = ServerHandle::for_config(config).await;
    (server, token)
}

/// Short-circuit path across /flags and /decide, with one UA per
/// category plus a UA that only matches the generic `bot/` substring.
#[rstest]
#[case("/flags", GOOGLEBOT_UA)]
#[case("/decide", GOOGLEBOT_UA)]
#[case(
    "/flags",
    "Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)"
)]
#[case(
    "/flags",
    "Mozilla/5.0 (compatible; AhrefsBot/7.0; +http://ahrefs.com/robot/)"
)]
#[case(
    "/flags",
    "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; GPTBot/1.0; +https://openai.com/gptbot)"
)]
#[case(
    "/flags",
    "Mozilla/5.0 (compatible; UnknownNewBot/1.0; +https://example.com/bot/)"
)]
#[tokio::test]
async fn bot_user_agent_short_circuits_with_minimal_response(
    #[case] path: &str,
    #[case] bot_ua: &str,
) -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let (server, token) = setup_server_with_a_flag(config).await;

    let payload = json!({
        "token": token,
        "distinct_id": "any-id",
    });

    let res = post_flags(server.addr, path, payload, Some(bot_ua)).await;
    assert_eq!(
        res.status(),
        StatusCode::OK,
        "{path} with UA {bot_ua:?} should get 200 OK"
    );

    let body: FlagsResponse = res.json().await?;
    assert!(
        body.flags.is_empty(),
        "{path} with UA {bot_ua:?}: bot request must not evaluate any flags; got {:?}",
        body.flags
    );
    assert!(!body.errors_while_computing_flags);
    // `supportedCompression` is only present on the minimal response, so
    // its presence distinguishes the short-circuit from a generic
    // empty-flags success.
    assert_eq!(
        body.config.get("supportedCompression"),
        Some(&json!(["gzip", "gzip-js"])),
        "{path} with UA {bot_ua:?}: response should match the minimal/GET shape"
    );

    Ok(())
}

/// Real browser UAs and the no-UA case must reach evaluation. Uses the v1
/// response shape to dodge `FlagDetails` deserialization quirks on success.
#[rstest]
#[case(Some("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"))]
#[case(Some("Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0"))]
#[case(Some("Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1"))]
#[case(Some("posthog-js/1.374.3"))]
#[case(None)]
#[tokio::test]
async fn non_bot_user_agent_reaches_evaluation(#[case] user_agent: Option<&str>) -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let (server, token) = setup_server_with_a_flag(config).await;

    let payload = json!({
        "token": token,
        "distinct_id": "any-id",
    });

    let res = post_flags_v1(server.addr, "/flags", payload, user_agent).await;
    assert_eq!(res.status(), StatusCode::OK);

    let body: LegacyFlagsResponse = res.json().await?;
    assert!(
        !body.feature_flags.is_empty(),
        "UA {user_agent:?}: non-bot request should reach evaluation; got empty response"
    );

    Ok(())
}

/// Customer scenario: CloudFront strips the UA so only the source IP is
/// usable for classification. `X-Forwarded-For` carries the real client IP.
#[rstest]
#[case("/flags", GOOGLEBOT_FORWARDED_IP)]
#[case("/decide", GOOGLEBOT_FORWARDED_IP)]
#[case("/flags", "207.46.13.42")] // Bingbot
#[case("/flags", "95.108.200.10")] // YandexBot
#[tokio::test]
async fn bot_ip_short_circuits_even_when_ua_is_benign(
    #[case] path: &str,
    #[case] forwarded_ip: &str,
) -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let (server, token) = setup_server_with_a_flag(config).await;

    let payload = json!({
        "token": token,
        "distinct_id": "any-id",
    });

    let res = post_flags_with_options(
        server.addr,
        path,
        payload,
        RequestOptions {
            user_agent: Some(CLOUDFRONT_UA),
            forwarded_for: Some(forwarded_ip),
            ..Default::default()
        },
    )
    .await;
    assert_eq!(res.status(), StatusCode::OK);

    let body: FlagsResponse = res.json().await?;
    assert!(
        body.flags.is_empty(),
        "{path} with XFF {forwarded_ip}: bot IP must short-circuit; got {:?}",
        body.flags
    );
    assert_eq!(
        body.config.get("supportedCompression"),
        Some(&json!(["gzip", "gzip-js"])),
        "{path} with XFF {forwarded_ip}: response should match minimal shape"
    );

    Ok(())
}

#[tokio::test]
async fn benign_ip_with_benign_ua_reaches_evaluation() -> Result<()> {
    // Public-DNS IP + non-bot UA: both signals miss, so the request must
    // run through the normal pipeline.
    let config = DEFAULT_TEST_CONFIG.clone();
    let (server, token) = setup_server_with_a_flag(config).await;

    let payload = json!({
        "token": token,
        "distinct_id": "any-id",
    });

    let res = post_flags_v1_with_options(
        server.addr,
        "/flags",
        payload,
        RequestOptions {
            user_agent: Some(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X) Chrome/120.0.0.0 Safari/537.36",
            ),
            forwarded_for: Some(BENIGN_FORWARDED_IP),
            ..Default::default()
        },
    )
    .await;
    assert_eq!(res.status(), StatusCode::OK);

    let body: LegacyFlagsResponse = res.json().await?;
    assert!(
        !body.feature_flags.is_empty(),
        "Benign UA + benign IP must reach evaluation"
    );

    Ok(())
}

/// In `Disabled` mode, neither signal short-circuits — bot-shaped requests
/// must reach evaluation regardless of which signal would have fired.
#[rstest]
#[case::ua_signal(Some(GOOGLEBOT_UA), None)]
#[case::ip_signal(Some(CLOUDFRONT_UA), Some(GOOGLEBOT_FORWARDED_IP))]
#[tokio::test]
async fn disabled_mode_skips_bot_filter_for_both_signals(
    #[case] user_agent: Option<&'static str>,
    #[case] forwarded_for: Option<&'static str>,
) -> Result<()> {
    let mut config = DEFAULT_TEST_CONFIG.clone();
    config.bot_filter_mode = BotFilterMode::Disabled;
    let (server, token) = setup_server_with_a_flag(config).await;

    let payload = json!({
        "token": token,
        "distinct_id": "any-id",
    });

    let res = post_flags_v1_with_options(
        server.addr,
        "/flags",
        payload,
        RequestOptions {
            user_agent,
            forwarded_for,
            ..Default::default()
        },
    )
    .await;
    assert_eq!(res.status(), StatusCode::OK);

    let body: LegacyFlagsResponse = res.json().await?;
    assert!(
        !body.feature_flags.is_empty(),
        "Disabled mode must let bot-shaped requests through the full pipeline (ua={user_agent:?}, xff={forwarded_for:?})"
    );

    Ok(())
}

/// When the IP rate-limiter has set the `rate_limit_warned` state for a
/// bot UA, the bot short-circuit must still return the minimal response
/// and must NOT surface the `X-PostHog-Rate-Limit-Warning` response
/// header — bots do not read response headers, so the explicit decision
/// at `endpoint::flags` is to keep the header off the bot path. This
/// test pins that invariant.
#[tokio::test]
async fn bot_response_does_not_carry_rate_limit_warning_header() -> Result<()> {
    let mut config = DEFAULT_TEST_CONFIG.clone();
    config.flags_ip_rate_limit_enabled = FlexBool(true);
    // log_only=true puts the IP limiter in warn-only mode: a request
    // that would otherwise be Blocked instead returns Warned.
    config.flags_ip_rate_limit_log_only = FlexBool(true);
    // burst=1 + warn_ratio=0.5 → derived warn capacity = 0 → no separate
    // warn limiter. The second request past the burst then hits the
    // enforce-side block, which warn_only converts to Warned.
    config.flags_ip_burst_size = 1;
    config.flags_warn_capacity_ratio = 0.5;
    // Slow refill so the second request is reliably past the cap.
    config.flags_ip_replenish_rate = 0.1;

    let (server, token) = setup_server_with_a_flag(config).await;

    let payload = json!({
        "token": token,
        "distinct_id": "any-id",
    });

    // Burn the burst token. Both requests use a Googlebot UA so both
    // short-circuit through the bot path; the first is Allowed, the
    // second triggers the rate-limit warn.
    let first = post_flags(server.addr, "/flags", payload.clone(), Some(GOOGLEBOT_UA)).await;
    assert_eq!(
        first.status(),
        StatusCode::OK,
        "first bot request must be admitted by the IP limiter"
    );
    let res = post_flags(server.addr, "/flags", payload, Some(GOOGLEBOT_UA)).await;

    assert_eq!(
        res.status(),
        StatusCode::OK,
        "bot UA must still short-circuit to 200 even when IP warn fires"
    );
    assert!(
        res.headers().get("X-PostHog-Rate-Limit-Warning").is_none(),
        "bot short-circuit must NOT surface X-PostHog-Rate-Limit-Warning, got {:?}",
        res.headers().get("X-PostHog-Rate-Limit-Warning"),
    );
    // Sanity-check: response is still the minimal bot envelope.
    let body: FlagsResponse = res.json().await?;
    assert!(body.flags.is_empty(), "bot path must not evaluate flags");
    assert_eq!(
        body.config.get("supportedCompression"),
        Some(&json!(["gzip", "gzip-js"])),
        "response should match the minimal-config marker"
    );

    Ok(())
}

/// Positive control for `bot_response_does_not_carry_rate_limit_warning_header`.
/// Same limiter config, non-bot UA: the second request must surface
/// `X-PostHog-Rate-Limit-Warning`.
#[tokio::test]
async fn non_bot_response_carries_rate_limit_warning_header() -> Result<()> {
    let mut config = DEFAULT_TEST_CONFIG.clone();
    config.flags_ip_rate_limit_enabled = FlexBool(true);
    config.flags_ip_rate_limit_log_only = FlexBool(true);
    config.flags_ip_burst_size = 1;
    config.flags_warn_capacity_ratio = 0.5;
    config.flags_ip_replenish_rate = 0.1;

    let (server, token) = setup_server_with_a_flag(config).await;

    let payload = json!({
        "token": token,
        "distinct_id": "any-id",
    });

    let benign_ua =
        Some("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/120.0.0.0 Safari/537.36");

    // Burn the burst token; second request hits the IP warn.
    let first = post_flags(server.addr, "/flags", payload.clone(), benign_ua).await;
    assert_eq!(
        first.status(),
        StatusCode::OK,
        "first non-bot request must be admitted by the IP limiter",
    );
    let res = post_flags(server.addr, "/flags", payload, benign_ua).await;
    assert_eq!(res.status(), StatusCode::OK);
    assert!(
        res.headers().get("X-PostHog-Rate-Limit-Warning").is_some(),
        "non-bot path must surface X-PostHog-Rate-Limit-Warning when IP warn fires",
    );

    Ok(())
}

/// A bot hit on the `X-Original-Endpoint: decide` path must return the
/// Decide envelope (`featureFlags`), not the Flags envelope (`flags` +
/// `featureFlagPayloads`). v=1 → array; v=2 → object.
#[rstest]
#[case("1")]
#[case("2")]
#[tokio::test]
async fn bot_via_decide_proxy_returns_decide_envelope(#[case] version: &str) -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let (server, token) = setup_server_with_a_flag(config).await;

    let payload = json!({
        "token": token,
        "distinct_id": "any-id",
    });

    let res = post_flags_with_version(
        server.addr,
        "/flags",
        payload,
        RequestOptions {
            user_agent: Some(GOOGLEBOT_UA),
            original_endpoint: Some("decide"),
            ..Default::default()
        },
        version,
    )
    .await;
    assert_eq!(res.status(), StatusCode::OK);

    let body: serde_json::Value = res.json().await?;

    // Asserting raw keys rather than deserializing into Decide*Response
    // pins down the envelope shape independently of the FlagValue layout.
    assert!(
        body.get("featureFlags").is_some(),
        "v={version}: bot via decide proxy must return a Decide envelope (no `featureFlags` key in {body})",
    );
    assert!(
        body.get("flags").is_none(),
        "v={version}: bot via decide proxy must NOT return the Flags envelope (found `flags` key in {body})",
    );

    let feature_flags = body
        .get("featureFlags")
        .expect("featureFlags key already asserted present");
    match version {
        "1" => {
            assert!(
                feature_flags.is_array(),
                "v=1 Decide envelope requires `featureFlags` to be an array, got {feature_flags}",
            );
            assert_eq!(
                feature_flags.as_array().map(|a| a.len()),
                Some(0),
                "bot short-circuit must return zero flags",
            );
        }
        "2" => {
            assert!(
                feature_flags.is_object(),
                "v=2 Decide envelope requires `featureFlags` to be an object, got {feature_flags}",
            );
            assert_eq!(
                feature_flags.as_object().map(|o| o.len()),
                Some(0),
                "bot short-circuit must return zero flags",
            );
        }
        other => panic!("unexpected version case {other}"),
    }

    // `supportedCompression` is only present on the minimal-response
    // payload, so it distinguishes the short-circuit from a full-eval
    // empty-flags result.
    assert_eq!(
        body.get("supportedCompression"),
        Some(&json!(["gzip", "gzip-js"])),
        "v={version}: response should carry the minimal-config marker",
    );

    Ok(())
}

/// A Googlebot UA must not exempt a client from per-IP rate limiting:
/// sending `burst_size + 1` requests from one IP returns 429 on the last.
#[tokio::test]
async fn ip_rate_limit_fires_before_bot_check_for_spoofed_ua() -> Result<()> {
    let mut config = DEFAULT_TEST_CONFIG.clone();
    config.flags_ip_rate_limit_enabled = FlexBool(true);
    config.flags_ip_rate_limit_log_only = FlexBool(false);
    config.flags_ip_burst_size = 3;
    // Slow refill so the burst is effectively the cap for the test.
    config.flags_ip_replenish_rate = 0.1;

    let (server, token) = setup_server_with_a_flag(config).await;

    let payload = json!({
        "token": token,
        "distinct_id": "any-id",
    });

    for i in 1..=3 {
        let res = post_flags(server.addr, "/flags", payload.clone(), Some(GOOGLEBOT_UA)).await;
        assert_eq!(
            res.status(),
            StatusCode::OK,
            "request {i} with Googlebot UA should be admitted by the IP limiter",
        );
    }

    let res = post_flags(server.addr, "/flags", payload, Some(GOOGLEBOT_UA)).await;
    assert_eq!(
        res.status(),
        StatusCode::TOO_MANY_REQUESTS,
        "burst+1 request with Googlebot UA must hit the IP rate limit",
    );
    let body: serde_json::Value = res.json().await?;
    assert_eq!(body["code"], "rate_limit_exceeded");

    Ok(())
}

/// In `LogOnly` mode (the prod default), a bot UA must not short-circuit.
/// The request continues through the normal pipeline and gets a real
/// evaluation back — observability of the classification is via the
/// `flags_bot_detected_total{mode="log_only"}` counter and the
/// `is_bot`/`bot_category`/`bot_source` fields on the canonical log line,
/// neither of which is asserted here (the response shape is the
/// user-visible behavior worth pinning end-to-end).
///
/// Both UA-driven and IP-driven classifications are covered so both code
/// paths in `bot_detection::classify_request` are exercised.
#[rstest]
#[case::ua_signal(Some(GOOGLEBOT_UA), None)]
#[case::ip_signal(Some(CLOUDFRONT_UA), Some(GOOGLEBOT_FORWARDED_IP))]
#[tokio::test]
async fn log_only_mode_stamps_but_does_not_short_circuit(
    #[case] user_agent: Option<&'static str>,
    #[case] forwarded_for: Option<&'static str>,
) -> Result<()> {
    let mut config = DEFAULT_TEST_CONFIG.clone();
    config.bot_filter_mode = BotFilterMode::LogOnly;
    let (server, token) = setup_server_with_a_flag(config).await;

    let payload = json!({
        "token": token,
        "distinct_id": "any-id",
    });

    let res = post_flags_v1_with_options(
        server.addr,
        "/flags",
        payload,
        RequestOptions {
            user_agent,
            forwarded_for,
            ..Default::default()
        },
    )
    .await;
    assert_eq!(res.status(), StatusCode::OK);

    let body: LegacyFlagsResponse = res.json().await?;
    assert!(
        !body.feature_flags.is_empty(),
        "LogOnly mode must let bot-shaped requests reach evaluation (ua={user_agent:?}, xff={forwarded_for:?})"
    );

    Ok(())
}
