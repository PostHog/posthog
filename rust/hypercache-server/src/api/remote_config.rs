use crate::{
    config_cache::{get_cached_data, CacheNamespace},
    router::State as AppState,
    sanitize::sanitize_config_for_client,
    token::{Token, TokenError},
};
use axum::{
    extract::{Path, State},
    http::{HeaderMap, Method, StatusCode},
    response::{IntoResponse, Json, Response},
};
use common_metrics::inc;
use serde_json::Value;
use tracing::info;

const REMOTE_CONFIG_COUNTER: &str = "remote_config_requests_total";

/// Cache-Control and Vary headers matching Django's `add_config_cache_headers`.
fn config_cache_headers() -> [(&'static str, &'static str); 2] {
    [
        ("cache-control", "public, max-age=300"),
        ("vary", "Origin, Referer"),
    ]
}

/// Parse and validate a path token, returning the appropriate HTTP error on failure.
#[allow(clippy::result_large_err)]
fn parse_token(raw: &str) -> Result<Token, Response> {
    Token::parse(raw).map_err(|e| {
        let status = match e {
            TokenError::Empty => StatusCode::UNAUTHORIZED,
            TokenError::TooLong | TokenError::InvalidCharacters => StatusCode::BAD_REQUEST,
        };
        inc(
            REMOTE_CONFIG_COUNTER,
            &[
                ("endpoint".to_string(), "config".to_string()),
                ("result".to_string(), "invalid_token".to_string()),
            ],
            1,
        );
        (status, e.to_string()).into_response()
    })
}

/// Fetch config from HyperCache, returning the raw value.
///
/// Returns `Ok(config)` on hit, or an HTTP error response on failure:
/// - 404 for unknown tokens (cache miss / explicit missing marker)
///
/// The `Token` type guarantees format validity at construction time.
async fn get_validated_config(state: &AppState, token: &Token) -> Result<Value, Response> {
    match get_cached_data(
        &state.config_hypercache_reader,
        state.config_negative_cache.as_ref(),
        CacheNamespace::Array,
        token.as_str(),
    )
    .await
    {
        Some(value) => {
            inc(
                REMOTE_CONFIG_COUNTER,
                &[
                    ("endpoint".to_string(), "config".to_string()),
                    ("result".to_string(), "hit".to_string()),
                ],
                1,
            );
            Ok(value)
        }
        None => {
            inc(
                REMOTE_CONFIG_COUNTER,
                &[
                    ("endpoint".to_string(), "config".to_string()),
                    ("result".to_string(), "not_found".to_string()),
                ],
                1,
            );
            info!(token = %token, "Remote config not found");
            Err(StatusCode::NOT_FOUND.into_response())
        }
    }
}

/// `GET /array/:token/config` — returns JSON config blob.
///
/// Reads pre-computed config from HyperCache (written by Django's RemoteConfig.sync).
/// Public endpoint — no auth beyond token validation.
///
/// Response headers: `Cache-Control: public, max-age=300`, `Vary: Origin, Referer`
pub async fn config_endpoint(
    State(state): State<AppState>,
    Path(raw_token): Path<String>,
    headers: HeaderMap,
    method: Method,
) -> Response {
    if method == Method::OPTIONS {
        return (StatusCode::NO_CONTENT, [("allow", "GET, OPTIONS, HEAD")]).into_response();
    }
    if method == Method::HEAD {
        return (
            StatusCode::OK,
            config_cache_headers(),
            [("content-type", "application/json")],
            axum::body::Body::empty(),
        )
            .into_response();
    }

    let token = match parse_token(&raw_token) {
        Ok(t) => t,
        Err(r) => return r,
    };

    let mut config = match get_validated_config(&state, &token).await {
        Ok(c) => c,
        Err(r) => return r,
    };

    sanitize_config_for_client(&mut config, &headers);

    (StatusCode::OK, config_cache_headers(), Json(config)).into_response()
}

/// `GET /array/:token/config.js` — returns JS wrapper around config.
///
/// Wraps the config JSON in an IIFE that sets `window._POSTHOG_REMOTE_CONFIG[token]`
/// with the config and site apps. This is what the SDK snippet loads.
///
/// Response headers: same cache headers + `Content-Type: application/javascript`
///
/// Safety: `Token` guarantees `[a-zA-Z0-9_-]` — cannot break out of the
/// single-quoted JS string interpolation below.
pub async fn config_js_endpoint(
    State(state): State<AppState>,
    Path(raw_token): Path<String>,
    headers: HeaderMap,
    method: Method,
) -> Response {
    if method == Method::OPTIONS {
        return (StatusCode::NO_CONTENT, [("allow", "GET, OPTIONS, HEAD")]).into_response();
    }
    if method == Method::HEAD {
        return (
            StatusCode::OK,
            [
                ("content-type", "application/javascript"),
                ("cache-control", "public, max-age=300"),
                ("vary", "Origin, Referer"),
            ],
            axum::body::Body::empty(),
        )
            .into_response();
    }

    let token = match parse_token(&raw_token) {
        Ok(t) => t,
        Err(r) => return r,
    };

    let mut config = match get_validated_config(&state, &token).await {
        Ok(c) => c,
        Err(r) => return r,
    };

    // Extract siteAppsJS (raw JS strings) before sanitization removes it
    let site_apps_js = config
        .as_object_mut()
        .and_then(|obj| obj.remove("siteAppsJS"))
        .and_then(|v| {
            if let Value::Array(arr) = v {
                Some(
                    arr.into_iter()
                        .filter_map(|item| {
                            if let Value::String(s) = item {
                                Some(s)
                            } else {
                                None
                            }
                        })
                        .collect::<Vec<String>>(),
                )
            } else {
                None
            }
        })
        .unwrap_or_default();

    // Remove siteApps (minimal metadata) — the JS version has the full JS instead
    if let Some(obj) = config.as_object_mut() {
        obj.remove("siteApps");
    }

    sanitize_config_for_client(&mut config, &headers);

    let config_json = match serde_json::to_string(&config) {
        Ok(s) => s,
        Err(e) => {
            tracing::error!(token = %token, error = %e, "Failed to serialize config");
            return StatusCode::INTERNAL_SERVER_ERROR.into_response();
        }
    };
    let site_apps_joined = site_apps_js.join(",");

    let js_content = format!(
        "(function() {{\n\
         \x20 window._POSTHOG_REMOTE_CONFIG = window._POSTHOG_REMOTE_CONFIG || {{}};\n\
         \x20 window._POSTHOG_REMOTE_CONFIG['{token}'] = {{\n\
         \x20   config: {config_json},\n\
         \x20   siteApps: [{site_apps_joined}]\n\
         \x20 }}\n\
         }})();"
    );

    (
        StatusCode::OK,
        [
            ("content-type", "application/javascript"),
            ("cache-control", "public, max-age=300"),
            ("vary", "Origin, Referer"),
        ],
        js_content,
    )
        .into_response()
}

#[cfg(test)]
mod tests {
    use crate::test_utils::helpers::*;
    use axum::http::StatusCode;
    use common_redis::MockRedisClient;
    use serde_json::json;

    #[test]
    fn test_config_js_template_format() {
        let config = json!({"sessionRecording": true, "heatmaps": false});
        let config_json = serde_json::to_string(&config).unwrap();
        let site_apps_joined = "";
        let token = "phc_test123";

        let js = format!(
            "(function() {{\n\
             \x20 window._POSTHOG_REMOTE_CONFIG = window._POSTHOG_REMOTE_CONFIG || {{}};\n\
             \x20 window._POSTHOG_REMOTE_CONFIG['{token}'] = {{\n\
             \x20   config: {config_json},\n\
             \x20   siteApps: [{site_apps_joined}]\n\
             \x20 }}\n\
             }})();"
        );

        assert!(js.contains("window._POSTHOG_REMOTE_CONFIG"));
        assert!(js.contains("phc_test123"));
        assert!(js.contains("\"sessionRecording\":true"));
        assert!(js.contains("siteApps: []"));
    }

    #[test]
    fn test_config_js_template_with_site_apps() {
        let config_json = "{}";
        let site_apps_joined = ["function() { return 1; }", "function() { return 2; }"].join(",");
        let token = "phc_test";

        let js = format!(
            "(function() {{\n\
             \x20 window._POSTHOG_REMOTE_CONFIG = window._POSTHOG_REMOTE_CONFIG || {{}};\n\
             \x20 window._POSTHOG_REMOTE_CONFIG['{token}'] = {{\n\
             \x20   config: {config_json},\n\
             \x20   siteApps: [{site_apps_joined}]\n\
             \x20 }}\n\
             }})();"
        );

        assert!(js.contains("siteApps: [function() { return 1; },function() { return 2; }]"));
    }

    // --- Endpoint integration tests ---

    #[tokio::test]
    async fn test_config_invalid_token_returns_400() {
        let surveys = mock_reader("surveys", "surveys.json", MockRedisClient::new());
        let config = mock_reader("array", "config.json", MockRedisClient::new());
        let router = test_router(surveys, config);

        let (status, _) = get(&router, "/array/token.with.dots/config").await;
        assert_eq!(status, StatusCode::BAD_REQUEST);
    }

    #[tokio::test]
    async fn test_config_missing_returns_404() {
        let surveys = mock_reader("surveys", "surveys.json", MockRedisClient::new());
        let config = mock_reader("array", "config.json", MockRedisClient::new());
        let router = test_router(surveys, config);

        let (status, _) = get(&router, "/array/phc_unknown/config").await;
        assert_eq!(status, StatusCode::NOT_FOUND);
    }

    #[tokio::test]
    async fn test_config_hit_returns_json_with_cache_headers() {
        let token = "phc_config_test";
        let key = cache_key("array", "config.json", token);

        let config_data = json!({
            "sessionRecording": {"endpoint": "/s/"},
            "heatmaps": true,
            "token": token
        });

        let mut mock = MockRedisClient::new();
        mock = mock.get_raw_bytes_ret(&key, Ok(pickle_json(&config_data)));

        let surveys = mock_reader("surveys", "surveys.json", MockRedisClient::new());
        let config = mock_reader("array", "config.json", mock);
        let router = test_router(surveys, config);

        let (status, body, headers) =
            get_with_headers(&router, &format!("/array/{token}/config"), vec![]).await;

        assert_eq!(status, StatusCode::OK);
        assert_eq!(
            headers.get("cache-control").unwrap().to_str().unwrap(),
            "public, max-age=300"
        );
        assert_eq!(
            headers.get("vary").unwrap().to_str().unwrap(),
            "Origin, Referer"
        );

        let parsed: serde_json::Value = serde_json::from_str(&body).unwrap();
        assert_eq!(parsed["heatmaps"], json!(true));
        assert_eq!(parsed["token"], json!(token));
    }

    #[tokio::test]
    async fn test_config_sanitizes_site_apps_js() {
        let token = "phc_sanitize_test";
        let key = cache_key("array", "config.json", token);

        let config_data = json!({
            "heatmaps": true,
            "siteAppsJS": ["function() {}"],
            "siteApps": [{"id": 1}]
        });

        let mut mock = MockRedisClient::new();
        mock = mock.get_raw_bytes_ret(&key, Ok(pickle_json(&config_data)));

        let surveys = mock_reader("surveys", "surveys.json", MockRedisClient::new());
        let config = mock_reader("array", "config.json", mock);
        let router = test_router(surveys, config);

        let (status, body) = get(&router, &format!("/array/{token}/config")).await;
        assert_eq!(status, StatusCode::OK);

        let parsed: serde_json::Value = serde_json::from_str(&body).unwrap();
        assert!(
            parsed.get("siteAppsJS").is_none(),
            "siteAppsJS should be removed"
        );
        assert!(
            parsed.get("siteApps").is_some(),
            "siteApps should be preserved"
        );
    }

    #[tokio::test]
    async fn test_config_js_returns_javascript() {
        let token = "phc_js_test";
        let key = cache_key("array", "config.json", token);

        let config_data = json!({
            "heatmaps": true,
            "siteAppsJS": ["function() { return 1; }"],
            "siteApps": [{"id": 1}]
        });

        let mut mock = MockRedisClient::new();
        mock = mock.get_raw_bytes_ret(&key, Ok(pickle_json(&config_data)));

        let surveys = mock_reader("surveys", "surveys.json", MockRedisClient::new());
        let config = mock_reader("array", "config.json", mock);
        let router = test_router(surveys, config);

        let (status, body, headers) =
            get_with_headers(&router, &format!("/array/{token}/config.js"), vec![]).await;

        assert_eq!(status, StatusCode::OK);
        assert_eq!(
            headers.get("content-type").unwrap().to_str().unwrap(),
            "application/javascript"
        );

        assert!(body.contains("window._POSTHOG_REMOTE_CONFIG"));
        assert!(body.contains(token));
        assert!(body.contains("siteApps: [function() { return 1; }]"));
        // siteApps metadata should be removed from config JSON
        assert!(!body.contains("\"siteApps\""));
        // siteAppsJS should be removed from config JSON
        assert!(!body.contains("\"siteAppsJS\""));
    }

    #[tokio::test]
    async fn test_config_js_missing_returns_404() {
        let surveys = mock_reader("surveys", "surveys.json", MockRedisClient::new());
        let config = mock_reader("array", "config.json", MockRedisClient::new());
        let router = test_router(surveys, config);

        let (status, _) = get(&router, "/array/phc_unknown/config.js").await;
        assert_eq!(status, StatusCode::NOT_FOUND);
    }

    #[tokio::test]
    async fn test_negative_cache_short_circuits_config_miss() {
        let surveys = mock_reader("surveys", "surveys.json", MockRedisClient::new());
        let config = mock_reader("array", "config.json", MockRedisClient::new());
        let (router, _surveys_nc, config_nc) = test_router_with_negative_cache(surveys, config);

        let token = "phc_neg_cache_test";

        // First request: cache miss → populates negative cache, returns 404
        let (status, _) = get(&router, &format!("/array/{token}/config")).await;
        assert_eq!(status, StatusCode::NOT_FOUND);
        assert!(
            config_nc.contains(token),
            "miss should populate config negative cache"
        );

        // Second request: negative cache hit → returns 404 without hitting Redis
        let (status2, _) = get(&router, &format!("/array/{token}/config")).await;
        assert_eq!(status2, StatusCode::NOT_FOUND);
    }
}
