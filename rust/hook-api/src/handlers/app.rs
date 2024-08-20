use std::convert::Infallible;

use axum::{extract::DefaultBodyLimit, routing, Router};
use tower::limit::ConcurrencyLimitLayer;

use hook_common::pgqueue::PgQueue;

use super::webhook;

pub fn add_routes(
    router: Router,
    pg_pool: PgQueue,
    hog_mode: bool,
    max_body_size: usize,
    concurrency_limit: usize,
) -> Router {
    let router = router
        .route("/", routing::get(index))
        .route("/_readiness", routing::get(index))
        .route("/_liveness", routing::get(index)); // No async loop for now, just check axum health

    if hog_mode {
        router.route(
            "/hoghook",
            routing::post(webhook::post_hoghook)
                .with_state(pg_pool)
                .layer::<_, Infallible>(ConcurrencyLimitLayer::new(concurrency_limit))
                .layer(DefaultBodyLimit::max(max_body_size)),
        )
    } else {
        router.route(
            "/webhook",
            routing::post(webhook::post_webhook)
                .with_state(pg_pool)
                .layer::<_, Infallible>(ConcurrencyLimitLayer::new(concurrency_limit))
                .layer(DefaultBodyLimit::max(max_body_size)),
        )
    }
}

pub async fn index() -> &'static str {
    "rusty-hook api"
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::{
        body::Body,
        http::{Request, StatusCode},
    };
    use hook_common::pgqueue::PgQueue;
    use http_body_util::BodyExt; // for `collect`
    use sqlx::PgPool;
    use tower::ServiceExt; // for `call`, `oneshot`, and `ready`

    #[sqlx::test(migrations = "../migrations")]
    async fn index(db: PgPool) {
        let pg_queue = PgQueue::new_from_pool("test_index", db).await;
        let hog_mode = false;

        let app = add_routes(Router::new(), pg_queue, hog_mode, 1_000_000, 10);

        let response = app
            .oneshot(Request::builder().uri("/").body(Body::empty()).unwrap())
            .await
            .unwrap();

        assert_eq!(response.status(), StatusCode::OK);

        let body = response.into_body().collect().await.unwrap().to_bytes();
        assert_eq!(&body[..], b"rusty-hook api");
    }
}
