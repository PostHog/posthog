/// Integration tests for hypercache-server.
///
/// These tests require Docker services running (Redis + MinIO/S3):
///   docker compose -f docker-compose.dev.yml up redis7 objectstorage -d
///
/// The tests write real data to Redis and S3, start the actual HTTP server,
/// and verify the full request flow including cache fallback behavior.
/// Test payloads are based on real production data shapes.
use std::net::SocketAddr;
use std::sync::Arc;
use std::time::Duration;

use common_hypercache::{HyperCacheConfig, KeyType};
use common_redis::{Client as RedisClientTrait, RedisClient};
use serde_json::{json, Value};
use tokio::net::TcpListener;
use tokio::sync::Notify;

use hypercache_server::config::Config;

// -- Realistic test fixtures matching production data shapes --

fn realistic_survey_payload() -> Value {
    json!({
        "surveys": [{
            "id": "019d71e9-a034-0000-1cb9-77ab3a8f70a5",
            "name": "Open feedback (2026-04-09 13:03)",
            "type": "popover",
            "questions": [{
                "id": "e6577639-62f0-4c38-9f46-e20aa6e4652c",
                "type": "open",
                "question": "What can we do to improve our product?",
                "description": "",
                "descriptionContentType": "text"
            }],
            "appearance": {
                "backgroundColor": "#ffffff",
                "borderColor": "#e5e7eb",
                "borderRadius": "10px",
                "boxPadding": "20px 24px",
                "boxShadow": "0 4px 12px rgba(0, 0, 0, 0.15)",
                "disabledButtonOpacity": "0.6",
                "displayThankYouMessage": true,
                "fontFamily": "inherit",
                "inputBackground": "#f9fafb",
                "maxWidth": "300px",
                "placeholder": "Start typing...",
                "position": "right",
                "ratingButtonActiveColor": "#1d1f27",
                "ratingButtonColor": "#f3f4f6",
                "shuffleQuestions": false,
                "submitButtonColor": "#1d1f27",
                "submitButtonTextColor": "#ffffff",
                "tabPosition": "right",
                "textColor": "#1d1f27",
                "textSubtleColor": "#939393",
                "thankYouMessageHeader": "Thank you for your feedback!",
                "whiteLabel": false,
                "widgetColor": "black",
                "widgetLabel": "Feedback",
                "widgetType": "tab",
                "zIndex": "2147482647"
            },
            "conditions": {
                "seenSurveyWaitPeriodInDays": 30
            },
            "schedule": "always",
            "start_date": "2026-04-09T11:03:49.512000Z",
            "end_date": null,
            "current_iteration": null,
            "current_iteration_start_date": null,
            "enable_partial_responses": true,
            "internal_targeting_flag_key": "survey-targeting-b98ec7ae12-custom"
        }],
        "survey_config": null
    })
}

fn realistic_config_payload() -> Value {
    json!({
        "analytics": {"endpoint": "/i/v0/e/"},
        "autocaptureExceptions": false,
        "autocapture_opt_out": false,
        "captureDeadClicks": false,
        "capturePerformance": {
            "network_timing": true,
            "web_vitals": true,
            "web_vitals_allowed_metrics": null
        },
        "conversations": false,
        "defaultIdentifiedOnly": true,
        "elementsChainAsString": true,
        "errorTracking": {
            "autocaptureExceptions": false,
            "suppressionRules": []
        },
        "hasFeatureFlags": true,
        "heatmaps": true,
        "logs": {"captureConsoleLogs": false},
        "productTours": false,
        "sessionRecording": {
            "canvasFps": null,
            "canvasQuality": null,
            "consoleLogRecordingEnabled": true,
            "domains": [],
            "endpoint": "/s/",
            "eventTriggers": [],
            "linkedFlag": null,
            "masking": null,
            "minimumDurationMilliseconds": null,
            "networkPayloadCapture": null,
            "recordCanvas": false,
            "recorderVersion": "v2",
            "sampleRate": null,
            "scriptConfig": {"script": "posthog-recorder"},
            "triggerMatchType": null,
            "urlBlocklist": [],
            "urlTriggers": [],
            "version": 1
        },
        "siteApps": [],
        "siteAppsJS": [],
        "supportedCompression": ["gzip", "gzip-js"],
        "surveys": [{
            "id": "019d71e9-a034-0000-1cb9-77ab3a8f70a5",
            "name": "Open feedback (2026-04-09 13:03)",
            "type": "popover"
        }],
        "token": "phc_test_token"
    })
}

fn config_with_domain_restriction() -> Value {
    let mut config = realistic_config_payload();
    config["sessionRecording"]["domains"] =
        json!(["https://allowed.example.com", "https://*.myapp.io"]);
    config
}

fn config_with_site_apps() -> Value {
    let mut config = realistic_config_payload();
    config["siteApps"] = json!([{"id": "app1", "url": "/site_app/token/hash/"}]);
    config["siteAppsJS"] = json!([
        "\n{\n  id: 'app1',\n  init: function(config) { return (function() { return { init: function() {} }; })().init(config) }\n}"
    ]);
    config
}

// -- Test infrastructure --

struct TestServer {
    addr: SocketAddr,
    shutdown: Arc<Notify>,
    redis: RedisClient,
    s3: aws_sdk_s3::Client,
    s3_bucket: String,
}

impl TestServer {
    async fn start() -> anyhow::Result<Self> {
        std::env::set_var("AWS_ACCESS_KEY_ID", "object_storage_root_user");
        std::env::set_var("AWS_SECRET_ACCESS_KEY", "object_storage_root_password");

        let config = Config {
            address: "127.0.0.1:0".parse().unwrap(),
            redis_url: "redis://localhost:6379/".to_string(),
            redis_reader_url: String::new(),
            redis_timeout_ms: 1000,
            object_storage_region: "us-east-1".to_string(),
            object_storage_bucket: "posthog".to_string(),
            object_storage_endpoint: "http://localhost:19000".to_string(),
            enable_metrics: hypercache_server::config::FlexBool(false),
            debug: hypercache_server::config::FlexBool(true),
            max_concurrency: 100,
            otel_url: None,
            otel_sampling_rate: 1.0,
            otel_service_name: "hypercache-server-test".to_string(),
            otel_export_timeout_secs: 3,
            otel_log_level: tracing::level_filters::LevelFilter::ERROR,
            continuous_profiling: common_continuous_profiling::ContinuousProfilingConfig::default(),
        };

        let listener = TcpListener::bind("127.0.0.1:0").await?;
        let addr = listener.local_addr()?;
        let notify = Arc::new(Notify::new());
        let shutdown = notify.clone();

        let config_clone = config.clone();
        tokio::spawn(async move {
            hypercache_server::server::serve(config_clone, listener, async move {
                notify.notified().await
            })
            .await
        });

        tokio::time::sleep(Duration::from_millis(200)).await;

        let redis = RedisClient::with_config(
            config.redis_url.clone(),
            common_redis::CompressionConfig::disabled(),
            common_redis::RedisValueFormat::default(),
            Some(Duration::from_millis(1000)),
            Some(Duration::from_millis(5000)),
        )
        .await?;

        let aws_config = aws_config::defaults(aws_config::BehaviorVersion::latest())
            .region(aws_config::Region::new("us-east-1"))
            .endpoint_url("http://localhost:19000")
            .load()
            .await;

        let s3 = aws_sdk_s3::Client::from_conf(
            aws_sdk_s3::config::Builder::from(&aws_config)
                .force_path_style(true)
                .build(),
        );

        Ok(TestServer {
            addr,
            shutdown,
            redis,
            s3,
            s3_bucket: config.object_storage_bucket,
        })
    }

    fn url(&self, path: &str) -> String {
        format!("http://{}{}", self.addr, path)
    }

    fn hc_config(&self, namespace: &str, value: &str) -> HyperCacheConfig {
        let mut config = HyperCacheConfig::new(
            namespace.to_string(),
            value.to_string(),
            "us-east-1".to_string(),
            self.s3_bucket.clone(),
        );
        config.token_based = true;
        config
    }

    async fn write_to_redis(
        &self,
        namespace: &str,
        value: &str,
        token: &str,
        data: &Value,
    ) -> anyhow::Result<()> {
        let config = self.hc_config(namespace, value);
        let key = config.get_redis_cache_key(&KeyType::string(token));
        let json_str = serde_json::to_string(data)?;
        self.redis.set(key, json_str).await?;
        Ok(())
    }

    async fn write_to_s3(
        &self,
        namespace: &str,
        value: &str,
        token: &str,
        data: &Value,
    ) -> anyhow::Result<()> {
        let config = self.hc_config(namespace, value);
        let key = config.get_s3_cache_key(&KeyType::string(token));
        let json_str = serde_json::to_string(data)?;
        self.s3
            .put_object()
            .bucket(&self.s3_bucket)
            .key(&key)
            .body(json_str.into_bytes().into())
            .send()
            .await?;
        Ok(())
    }

    async fn clear_redis(&self, namespace: &str, value: &str, token: &str) -> anyhow::Result<()> {
        let config = self.hc_config(namespace, value);
        let key = config.get_redis_cache_key(&KeyType::string(token));
        drop(self.redis.del(key).await);
        Ok(())
    }

    async fn clear_s3(&self, namespace: &str, value: &str, token: &str) -> anyhow::Result<()> {
        let config = self.hc_config(namespace, value);
        let key = config.get_s3_cache_key(&KeyType::string(token));
        drop(
            self.s3
                .delete_object()
                .bucket(&self.s3_bucket)
                .key(&key)
                .send()
                .await,
        );
        Ok(())
    }

    async fn cleanup(&self, namespace: &str, value: &str, token: &str) -> anyhow::Result<()> {
        self.clear_redis(namespace, value, token).await?;
        self.clear_s3(namespace, value, token).await?;
        Ok(())
    }
}

impl Drop for TestServer {
    fn drop(&mut self) {
        self.shutdown.notify_one();
    }
}

// -- Surveys: Redis hit --

#[tokio::test]
async fn test_surveys_redis_hit() -> anyhow::Result<()> {
    let server = TestServer::start().await?;
    let token = "phc_inttest_surveys_redis";
    let data = realistic_survey_payload();

    server
        .write_to_redis("surveys", "surveys.json", token, &data)
        .await?;

    let resp = reqwest::get(server.url(&format!("/api/surveys?token={token}"))).await?;
    assert_eq!(resp.status(), 200);

    let body: Value = resp.json().await?;
    assert_eq!(
        body["surveys"][0]["id"],
        "019d71e9-a034-0000-1cb9-77ab3a8f70a5"
    );
    assert_eq!(body["surveys"][0]["type"], "popover");
    assert_eq!(
        body["surveys"][0]["questions"][0]["question"],
        "What can we do to improve our product?"
    );
    assert_eq!(body["survey_config"], json!(null));

    server.cleanup("surveys", "surveys.json", token).await?;
    Ok(())
}

// -- Surveys: S3 fallback (Redis miss) --

#[tokio::test]
async fn test_surveys_s3_fallback() -> anyhow::Result<()> {
    let server = TestServer::start().await?;
    let token = "phc_inttest_surveys_s3";
    let data = realistic_survey_payload();

    server
        .write_to_s3("surveys", "surveys.json", token, &data)
        .await?;
    server.clear_redis("surveys", "surveys.json", token).await?;

    let resp = reqwest::get(server.url(&format!("/api/surveys?token={token}"))).await?;
    assert_eq!(resp.status(), 200);

    let body: Value = resp.json().await?;
    assert_eq!(
        body["surveys"][0]["name"],
        "Open feedback (2026-04-09 13:03)"
    );
    assert_eq!(
        body["surveys"][0]["appearance"]["backgroundColor"],
        "#ffffff"
    );

    server.cleanup("surveys", "surveys.json", token).await?;
    Ok(())
}

// -- Surveys: complete miss --

#[tokio::test]
async fn test_surveys_complete_miss_returns_empty() -> anyhow::Result<()> {
    let server = TestServer::start().await?;
    let token = "phc_inttest_surveys_miss";

    server.cleanup("surveys", "surveys.json", token).await?;

    let resp = reqwest::get(server.url(&format!("/api/surveys?token={token}"))).await?;
    assert_eq!(resp.status(), 200);

    let body: Value = resp.json().await?;
    assert_eq!(body["surveys"], json!([]));
    assert_eq!(body["survey_config"], json!(null));

    Ok(())
}

// -- Surveys: missing token --

#[tokio::test]
async fn test_surveys_missing_token_returns_401() -> anyhow::Result<()> {
    let server = TestServer::start().await?;

    let resp = reqwest::get(server.url("/api/surveys")).await?;
    assert_eq!(resp.status(), 401);

    Ok(())
}

// -- Config: Redis hit with cache headers --

#[tokio::test]
async fn test_config_redis_hit_with_headers() -> anyhow::Result<()> {
    let server = TestServer::start().await?;
    let token = "phc_inttest_config_redis";
    let data = realistic_config_payload();

    server
        .write_to_redis("array", "config.json", token, &data)
        .await?;

    let resp = reqwest::get(server.url(&format!("/array/{token}/config"))).await?;
    assert_eq!(resp.status(), 200);
    assert_eq!(
        resp.headers().get("cache-control").unwrap().to_str()?,
        "public, max-age=300"
    );

    let body: Value = resp.json().await?;
    assert_eq!(body["hasFeatureFlags"], json!(true));
    assert_eq!(body["heatmaps"], json!(true));
    assert_eq!(body["analytics"]["endpoint"], "/i/v0/e/");
    assert_eq!(body["supportedCompression"], json!(["gzip", "gzip-js"]));
    // sessionRecording should be preserved as object (empty domains = allow all)
    assert!(body["sessionRecording"].is_object());
    // domains should be stripped from response
    assert!(body["sessionRecording"].get("domains").is_none());
    // siteAppsJS should be removed
    assert!(body.get("siteAppsJS").is_none());

    server.cleanup("array", "config.json", token).await?;
    Ok(())
}

// -- Config: S3 fallback --

#[tokio::test]
async fn test_config_s3_fallback() -> anyhow::Result<()> {
    let server = TestServer::start().await?;
    let token = "phc_inttest_config_s3";
    let data = realistic_config_payload();

    server
        .write_to_s3("array", "config.json", token, &data)
        .await?;
    server.clear_redis("array", "config.json", token).await?;

    let resp = reqwest::get(server.url(&format!("/array/{token}/config"))).await?;
    assert_eq!(resp.status(), 200);

    let body: Value = resp.json().await?;
    assert_eq!(body["heatmaps"], json!(true));
    assert_eq!(body["elementsChainAsString"], json!(true));

    server.cleanup("array", "config.json", token).await?;
    Ok(())
}

// -- Config: complete miss → 404 --

#[tokio::test]
async fn test_config_complete_miss_returns_404() -> anyhow::Result<()> {
    let server = TestServer::start().await?;
    let token = "phc_inttest_config_miss";

    server.cleanup("array", "config.json", token).await?;

    let resp = reqwest::get(server.url(&format!("/array/{token}/config"))).await?;
    assert_eq!(resp.status(), 404);

    Ok(())
}

// -- Config: invalid token → 400 --

#[tokio::test]
async fn test_config_invalid_token_returns_400() -> anyhow::Result<()> {
    let server = TestServer::start().await?;

    let resp = reqwest::get(server.url("/array/token.with.dots/config")).await?;
    assert_eq!(resp.status(), 400);

    Ok(())
}

// -- Config: domain restriction sanitization --

#[tokio::test]
async fn test_config_domain_restriction_blocks_unknown_origin() -> anyhow::Result<()> {
    let server = TestServer::start().await?;
    let token = "phc_inttest_domains";
    let data = config_with_domain_restriction();

    server
        .write_to_redis("array", "config.json", token, &data)
        .await?;

    // No Origin header → not permitted → sessionRecording disabled
    let resp = reqwest::get(server.url(&format!("/array/{token}/config"))).await?;
    assert_eq!(resp.status(), 200);

    let body: Value = resp.json().await?;
    assert_eq!(body["sessionRecording"], json!(false));

    server.cleanup("array", "config.json", token).await?;
    Ok(())
}

// -- Config.js: returns JS with site apps --

#[tokio::test]
async fn test_config_js_with_site_apps() -> anyhow::Result<()> {
    let server = TestServer::start().await?;
    let token = "phc_inttest_configjs";
    let data = config_with_site_apps();

    server
        .write_to_redis("array", "config.json", token, &data)
        .await?;

    let resp = reqwest::get(server.url(&format!("/array/{token}/config.js"))).await?;
    assert_eq!(resp.status(), 200);
    assert_eq!(
        resp.headers().get("content-type").unwrap().to_str()?,
        "application/javascript"
    );
    assert_eq!(
        resp.headers().get("cache-control").unwrap().to_str()?,
        "public, max-age=300"
    );

    let body = resp.text().await?;
    // JS wrapper structure
    assert!(body.starts_with("(function() {"));
    assert!(body.contains(&format!("window._POSTHOG_REMOTE_CONFIG['{token}']")));
    // Site apps JS should be in the siteApps array (raw JS, not JSON)
    assert!(body.contains("siteApps: ["));
    assert!(body.contains("init: function(config)"));
    // siteAppsJS and siteApps should NOT appear in the config JSON
    assert!(!body.contains("\"siteAppsJS\""));
    assert!(!body.contains("\"siteApps\""));

    server.cleanup("array", "config.json", token).await?;
    Ok(())
}

// -- Config.js: missing → 404 --

#[tokio::test]
async fn test_config_js_missing_returns_404() -> anyhow::Result<()> {
    let server = TestServer::start().await?;
    let token = "phc_inttest_configjs_miss";

    server.cleanup("array", "config.json", token).await?;

    let resp = reqwest::get(server.url(&format!("/array/{token}/config.js"))).await?;
    assert_eq!(resp.status(), 404);

    Ok(())
}

// -- Health endpoints --

#[tokio::test]
async fn test_health_endpoints() -> anyhow::Result<()> {
    let server = TestServer::start().await?;

    let resp = reqwest::get(server.url("/")).await?;
    assert_eq!(resp.status(), 200);
    assert_eq!(resp.text().await?, "hypercache-server");

    let resp = reqwest::get(server.url("/_readiness")).await?;
    assert_eq!(resp.status(), 200);

    let resp = reqwest::get(server.url("/_liveness")).await?;
    assert_eq!(resp.status(), 200);

    // Sourcemap requests should 404 with a matched route (not unmatched)
    let resp = reqwest::get(server.url("/array/phc_test/config.js.map")).await?;
    assert_eq!(resp.status(), 404);

    Ok(())
}
