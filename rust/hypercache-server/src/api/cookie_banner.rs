use crate::{
    config_cache::{get_cached_data, CacheNamespace},
    router::State as AppState,
    token::{Token, TokenError},
};
use axum::{
    extract::{Path, State},
    http::{Method, StatusCode},
    response::{IntoResponse, Response},
};
use common_metrics::inc;
use tracing::info;

const COOKIE_BANNER_COUNTER: &str = "cookie_banner_requests_total";

fn cookie_banner_headers() -> [(&'static str, &'static str); 3] {
    [
        ("content-type", "application/javascript"),
        ("cache-control", "public, max-age=300"),
        ("vary", "Origin, Referer"),
    ]
}

fn count(result: &str) {
    inc(
        COOKIE_BANNER_COUNTER,
        &[
            ("endpoint".to_string(), "cookie_banner_js".to_string()),
            ("result".to_string(), result.to_string()),
        ],
        1,
    );
}

/// `GET /array/:token/cookie-banner.js` — the standalone cookie banner runtime.
///
/// Serves the pre-built consent-management script from HyperCache (written by
/// `products.cookie_banner.backend.artifact.sync_cookie_banner_artifact`), stored
/// as `{"js": "<code>"}`. Customers load it as the first script on the page, before
/// posthog-js. Public endpoint — no auth beyond token validation; the payload is
/// per-team, never per-visitor, and nothing about the requester is recorded.
pub async fn cookie_banner_js_endpoint(
    State(state): State<AppState>,
    Path(raw_token): Path<String>,
    method: Method,
) -> Response {
    if method == Method::OPTIONS {
        return (StatusCode::NO_CONTENT, [("allow", "GET, OPTIONS, HEAD")]).into_response();
    }
    if method == Method::HEAD {
        return (
            StatusCode::OK,
            cookie_banner_headers(),
            axum::body::Body::empty(),
        )
            .into_response();
    }

    let token = match Token::parse(&raw_token) {
        Ok(t) => t,
        Err(e) => {
            let status = match e {
                TokenError::Empty => StatusCode::UNAUTHORIZED,
                TokenError::TooLong | TokenError::InvalidCharacters => StatusCode::BAD_REQUEST,
            };
            count("invalid_token");
            return (status, e.to_string()).into_response();
        }
    };

    let value = match get_cached_data(
        &state.cookie_banner_hypercache_reader,
        state.cookie_banner_negative_cache.as_ref(),
        CacheNamespace::CookieBanner,
        token.as_str(),
    )
    .await
    {
        Some(value) => value,
        None => {
            count("not_found");
            info!(token = %token, "Cookie banner not found");
            return StatusCode::NOT_FOUND.into_response();
        }
    };

    let js = match value.get("js").and_then(|v| v.as_str()) {
        Some(js) => js.to_owned(),
        None => {
            count("malformed");
            tracing::error!(token = %token, "Cookie banner artifact has no 'js' string");
            return StatusCode::INTERNAL_SERVER_ERROR.into_response();
        }
    };

    count("hit");
    (StatusCode::OK, cookie_banner_headers(), js).into_response()
}

#[cfg(test)]
mod tests {
    use crate::test_utils::helpers::*;
    use axum::http::StatusCode;
    use common_redis::MockRedisClient;
    use serde_json::json;

    fn banner_artifact(js: &str) -> serde_json::Value {
        json!({ "js": js })
    }

    #[tokio::test]
    async fn test_hit_returns_javascript_with_cache_headers() {
        let token = "phc_banner_test";
        let key = cache_key("array", "cookie-banner.js", token);
        let js_code = "(function(){var TOKEN='phc_banner_test';})();";

        let mut mock = MockRedisClient::new();
        mock = mock.get_raw_bytes_ret(&key, Ok(pickle_json(&banner_artifact(js_code))));

        let router = test_router_cookie_banner(mock);
        let (status, body, headers) =
            get_with_headers(&router, &format!("/array/{token}/cookie-banner.js"), vec![]).await;

        assert_eq!(status, StatusCode::OK);
        assert_eq!(body, js_code);
        assert_eq!(
            headers.get("content-type").unwrap().to_str().unwrap(),
            "application/javascript"
        );
        assert_eq!(
            headers.get("cache-control").unwrap().to_str().unwrap(),
            "public, max-age=300"
        );
        assert_eq!(
            headers.get("vary").unwrap().to_str().unwrap(),
            "Origin, Referer"
        );
    }

    #[tokio::test]
    async fn test_missing_returns_404() {
        let router = test_router_cookie_banner(MockRedisClient::new());
        let (status, _) = get(&router, "/array/phc_unknown/cookie-banner.js").await;
        assert_eq!(status, StatusCode::NOT_FOUND);
    }

    #[tokio::test]
    async fn test_invalid_token_returns_400() {
        let router = test_router_cookie_banner(MockRedisClient::new());
        let (status, _) = get(&router, "/array/token.with.dots/cookie-banner.js").await;
        assert_eq!(status, StatusCode::BAD_REQUEST);
    }

    #[tokio::test]
    async fn test_artifact_without_js_key_returns_500() {
        let token = "phc_malformed";
        let key = cache_key("array", "cookie-banner.js", token);

        let mut mock = MockRedisClient::new();
        mock = mock.get_raw_bytes_ret(&key, Ok(pickle_json(&json!({"nope": true}))));

        let router = test_router_cookie_banner(mock);
        let (status, _) = get(&router, &format!("/array/{token}/cookie-banner.js")).await;
        assert_eq!(status, StatusCode::INTERNAL_SERVER_ERROR);
    }

    #[tokio::test]
    async fn test_head_and_options() {
        let router = test_router_cookie_banner(MockRedisClient::new());

        let (status, _, headers) =
            request_with_method(&router, "HEAD", "/array/phc_head_test/cookie-banner.js").await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(
            headers.get("content-type").unwrap().to_str().unwrap(),
            "application/javascript"
        );

        let (status, _, _) =
            request_with_method(&router, "OPTIONS", "/array/phc_head_test/cookie-banner.js").await;
        assert_eq!(status, StatusCode::NO_CONTENT);
    }

    #[tokio::test]
    async fn test_banner_miss_does_not_tombstone_config() {
        // Negative-cache isolation: most teams have no banner, and a banner miss must
        // never start 404ing the same token's /config requests.
        let token = "phc_isolation_test";
        let config_key = cache_key("array", "config.json", token);
        let config_data = json!({"heatmaps": true, "token": token});

        let mut config_mock = MockRedisClient::new();
        config_mock = config_mock.get_raw_bytes_ret(&config_key, Ok(pickle_json(&config_data)));

        let (router, config_nc, cookie_banner_nc) =
            test_router_cookie_banner_with_negative_caches(MockRedisClient::new(), config_mock);

        let (status, _) = get(&router, &format!("/array/{token}/cookie-banner.js")).await;
        assert_eq!(status, StatusCode::NOT_FOUND);
        assert!(
            cookie_banner_nc.contains(token),
            "banner miss should tombstone the cookie banner cache"
        );
        assert!(
            !config_nc.contains(token),
            "banner miss must not tombstone the config cache"
        );

        let (status, _) = get(&router, &format!("/array/{token}/config")).await;
        assert_eq!(status, StatusCode::OK);
    }
}
