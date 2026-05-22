use std::future::ready;

use axum::{routing::get, Router};
use lifecycle::{LivenessHandler, ReadinessHandler};

pub fn root_router(readiness: ReadinessHandler, liveness: LivenessHandler) -> Router {
    Router::new()
        .route("/", get(index))
        .route(
            "/_readiness",
            get(move || {
                let r = readiness.clone();
                async move { r.check().await }
            }),
        )
        .route("/_liveness", get(move || ready(liveness.check())))
}

async fn index() -> &'static str {
    "opensearch-indexer"
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::{
        body::Body,
        http::{Request, StatusCode},
    };
    use lifecycle::{ComponentOptions, Manager};
    use tower::ServiceExt;

    fn build_test_router() -> Router {
        let mut manager = Manager::builder("test")
            .with_trap_signals(false)
            .with_prestop_check(false)
            .build();
        let _handle = manager.register("http", ComponentOptions::new().is_observability(true));
        root_router(manager.readiness_handler(), manager.liveness_handler())
    }

    #[tokio::test]
    async fn root_returns_service_name() {
        let app = build_test_router();
        let resp = app
            .oneshot(Request::builder().uri("/").body(Body::empty()).unwrap())
            .await
            .unwrap();
        assert_eq!(resp.status(), StatusCode::OK);
        let bytes = axum::body::to_bytes(resp.into_body(), 128).await.unwrap();
        assert_eq!(&bytes[..], b"opensearch-indexer");
    }

    #[tokio::test]
    async fn readiness_returns_ok_while_running() {
        let app = build_test_router();
        let resp = app
            .oneshot(
                Request::builder()
                    .uri("/_readiness")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(resp.status(), StatusCode::OK);
    }

    #[tokio::test]
    async fn liveness_returns_ok() {
        let app = build_test_router();
        let resp = app
            .oneshot(
                Request::builder()
                    .uri("/_liveness")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(resp.status(), StatusCode::OK);
    }
}
