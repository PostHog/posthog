/// Test utilities for constructing mock HyperCacheReaders and router state.
#[cfg(test)]
pub mod helpers {
    use std::sync::Arc;

    use axum::{
        body::Body,
        http::{Request, StatusCode},
        Router,
    };
    use common_cache::NegativeCache;
    use common_hypercache::{HyperCacheConfig, HyperCacheReader, KeyType};
    use common_redis::MockRedisClient;
    use common_s3::{MockS3Client, S3Client, S3Error};
    use http_body_util::BodyExt;
    use tower::ServiceExt;

    use crate::router::State;

    /// Pickle a JSON value the way Django's HyperCache stores it.
    pub fn pickle_json(value: &serde_json::Value) -> Vec<u8> {
        let json_str = serde_json::to_string(value).unwrap();
        serde_pickle::to_vec(&json_str, Default::default()).unwrap()
    }

    /// S3 mock that returns NotFound for all keys.
    pub fn dummy_s3_client() -> Arc<dyn S3Client + Send + Sync> {
        let mut mock_s3 = MockS3Client::new();
        mock_s3.expect_get_string().returning(|_, key| {
            let key_owned = key.to_string();
            Box::pin(async move { Err(S3Error::NotFound(key_owned)) })
        });
        Arc::new(mock_s3)
    }

    /// Create a HyperCacheReader backed by a MockRedisClient and a dummy S3.
    pub fn mock_reader(
        namespace: &str,
        value: &str,
        mock_redis: MockRedisClient,
    ) -> Arc<HyperCacheReader> {
        let mut config = HyperCacheConfig::new(
            namespace.to_string(),
            value.to_string(),
            "us-east-1".to_string(),
            "test-bucket".to_string(),
        );
        config.token_based = true;
        Arc::new(HyperCacheReader::new_with_s3_client(
            Arc::new(mock_redis),
            dummy_s3_client(),
            config,
        ))
    }

    /// Get the Redis cache key for a token-based HyperCache lookup.
    pub fn cache_key(namespace: &str, value: &str, token: &str) -> String {
        let mut config = HyperCacheConfig::new(
            namespace.to_string(),
            value.to_string(),
            "us-east-1".to_string(),
            "test-bucket".to_string(),
        );
        config.token_based = true;
        config.get_redis_cache_key(&KeyType::string(token))
    }

    /// Build a test router with the given mock readers (no negative cache).
    pub fn test_router(
        surveys_reader: Arc<HyperCacheReader>,
        config_reader: Arc<HyperCacheReader>,
    ) -> Router {
        build_router(
            surveys_reader,
            config_reader,
            mock_reader("array", "cookie-banner.js", MockRedisClient::new()),
            None,
            None,
            None,
        )
    }

    /// Build a test router with negative caches enabled, returning the router
    /// and handles to both caches for assertion.
    pub fn test_router_with_negative_cache(
        surveys_reader: Arc<HyperCacheReader>,
        config_reader: Arc<HyperCacheReader>,
    ) -> (Router, NegativeCache, NegativeCache) {
        let surveys_nc = NegativeCache::new(100, 300);
        let config_nc = NegativeCache::new(100, 300);
        let router = build_router(
            surveys_reader,
            config_reader,
            mock_reader("array", "cookie-banner.js", MockRedisClient::new()),
            Some(surveys_nc.clone()),
            Some(config_nc.clone()),
            None,
        );
        (router, surveys_nc, config_nc)
    }

    /// Build a test router around a cookie banner mock; surveys/config are empty.
    pub fn test_router_cookie_banner(cookie_banner_redis: MockRedisClient) -> Router {
        build_router(
            mock_reader("surveys", "surveys.json", MockRedisClient::new()),
            mock_reader("array", "config.json", MockRedisClient::new()),
            mock_reader("array", "cookie-banner.js", cookie_banner_redis),
            None,
            None,
            None,
        )
    }

    /// Build a test router with a cookie banner mock, a config mock, and negative
    /// caches on both, returning (router, config_nc, cookie_banner_nc).
    pub fn test_router_cookie_banner_with_negative_caches(
        cookie_banner_redis: MockRedisClient,
        config_redis: MockRedisClient,
    ) -> (Router, NegativeCache, NegativeCache) {
        let config_nc = NegativeCache::new(100, 300);
        let cookie_banner_nc = NegativeCache::new(100, 300);
        let router = build_router(
            mock_reader("surveys", "surveys.json", MockRedisClient::new()),
            mock_reader("array", "config.json", config_redis),
            mock_reader("array", "cookie-banner.js", cookie_banner_redis),
            None,
            Some(config_nc.clone()),
            Some(cookie_banner_nc.clone()),
        );
        (router, config_nc, cookie_banner_nc)
    }

    fn build_router(
        surveys_reader: Arc<HyperCacheReader>,
        config_reader: Arc<HyperCacheReader>,
        cookie_banner_reader: Arc<HyperCacheReader>,
        surveys_negative_cache: Option<NegativeCache>,
        config_negative_cache: Option<NegativeCache>,
        cookie_banner_negative_cache: Option<NegativeCache>,
    ) -> Router {
        let state = State {
            surveys_hypercache_reader: surveys_reader,
            config_hypercache_reader: config_reader,
            cookie_banner_hypercache_reader: cookie_banner_reader,
            surveys_negative_cache,
            config_negative_cache,
            cookie_banner_negative_cache,
        };

        Router::new()
            .route(
                "/api/surveys",
                axum::routing::any(crate::api::surveys::surveys_endpoint),
            )
            .route(
                "/array/:token/config",
                axum::routing::any(crate::api::remote_config::config_endpoint),
            )
            .route(
                "/array/:token/config.js",
                axum::routing::any(crate::api::remote_config::config_js_endpoint),
            )
            .route(
                "/array/:token/cookie-banner.js",
                axum::routing::any(crate::api::cookie_banner::cookie_banner_js_endpoint),
            )
            .with_state(state)
    }

    /// Send a GET request to the test router and return (status, body string).
    pub async fn get(router: &Router, uri: &str) -> (StatusCode, String) {
        let request = Request::builder().uri(uri).body(Body::empty()).unwrap();

        let response = router.clone().oneshot(request).await.unwrap();
        let status = response.status();
        let body = response.into_body().collect().await.unwrap().to_bytes();
        let body_str = String::from_utf8(body.to_vec()).unwrap();

        (status, body_str)
    }

    /// Send a POST request with form-encoded body.
    pub async fn post_form(router: &Router, uri: &str, form_body: &str) -> (StatusCode, String) {
        let request = Request::builder()
            .method("POST")
            .uri(uri)
            .header("content-type", "application/x-www-form-urlencoded")
            .body(Body::from(form_body.to_owned()))
            .unwrap();

        let response = router.clone().oneshot(request).await.unwrap();
        let status = response.status();
        let body = response.into_body().collect().await.unwrap().to_bytes();
        let body_str = String::from_utf8(body.to_vec()).unwrap();

        (status, body_str)
    }

    /// Send a request with an arbitrary method, returning (status, body, headers).
    pub async fn request_with_method(
        router: &Router,
        method: &str,
        uri: &str,
    ) -> (StatusCode, String, axum::http::HeaderMap) {
        let request = Request::builder()
            .method(method)
            .uri(uri)
            .body(Body::empty())
            .unwrap();

        let response = router.clone().oneshot(request).await.unwrap();
        let status = response.status();
        let resp_headers = response.headers().clone();
        let body = response.into_body().collect().await.unwrap().to_bytes();
        let body_str = String::from_utf8(body.to_vec()).unwrap();

        (status, body_str, resp_headers)
    }

    /// Send a GET request with custom headers.
    pub async fn get_with_headers(
        router: &Router,
        uri: &str,
        headers: Vec<(&str, &str)>,
    ) -> (StatusCode, String, axum::http::HeaderMap) {
        let mut builder = Request::builder().uri(uri);
        for (key, value) in headers {
            builder = builder.header(key, value);
        }
        let request = builder.body(Body::empty()).unwrap();

        let response = router.clone().oneshot(request).await.unwrap();
        let status = response.status();
        let resp_headers = response.headers().clone();
        let body = response.into_body().collect().await.unwrap().to_bytes();
        let body_str = String::from_utf8(body.to_vec()).unwrap();

        (status, body_str, resp_headers)
    }
}
