/// Test utilities for constructing mock HyperCacheReaders and router state.
#[cfg(test)]
pub mod helpers {
    use std::sync::Arc;

    use axum::{
        body::Body,
        http::{Request, StatusCode},
        Router,
    };
    use common_hypercache::{HyperCacheConfig, HyperCacheReader, KeyType};
    use common_redis::MockRedisClient;
    use http_body_util::BodyExt;
    use tower::ServiceExt;

    use crate::router::State;

    /// Pickle a JSON value the way Django's HyperCache stores it.
    pub fn pickle_json(value: &serde_json::Value) -> Vec<u8> {
        let json_str = serde_json::to_string(value).unwrap();
        serde_pickle::to_vec(&json_str, Default::default()).unwrap()
    }

    /// Create a HyperCacheReader backed by a MockRedisClient.
    pub async fn mock_reader(
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
        Arc::new(
            HyperCacheReader::new(Arc::new(mock_redis), config)
                .await
                .unwrap(),
        )
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

    /// Build a test router with the given mock readers.
    pub fn test_router(
        surveys_reader: Arc<HyperCacheReader>,
        config_reader: Arc<HyperCacheReader>,
    ) -> Router {
        let state = State {
            surveys_hypercache_reader: surveys_reader,
            config_hypercache_reader: config_reader,
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
