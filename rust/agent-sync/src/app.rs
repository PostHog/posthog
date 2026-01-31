use axum::{
    extract::State,
    http::StatusCode,
    middleware,
    routing::get,
    Router,
};
use sqlx::PgPool;
use std::sync::Arc;

use crate::auth::{auth_middleware, AuthService};
use crate::handlers::{get_logs, get_sync, post_sync};
use crate::kafka::EventPublisher;
use crate::store::LogStore;
use crate::streaming::FanoutRouter;

#[derive(Clone)]
pub struct AppState {
    pub auth: Arc<dyn AuthService>,
    pub log_store: Arc<dyn LogStore>,
    pub publisher: Arc<dyn EventPublisher>,
    pub router: Arc<FanoutRouter>,
    pub pg_pool: PgPool,
    pub max_logs_limit: u32,
    pub sse_keepalive_secs: u64,
}

pub fn create_router(state: AppState) -> Router {
    let api_routes = Router::new()
        .route(
            "/api/projects/:project_id/tasks/:task_id/runs/:run_id/sync",
            get(get_sync).post(post_sync),
        )
        .route(
            "/api/projects/:project_id/tasks/:task_id/runs/:run_id/logs",
            get(get_logs),
        )
        .layer(middleware::from_fn_with_state(state.clone(), auth_middleware));

    let health_routes = Router::new()
        .route("/", get(index))
        .route("/_liveness", get(liveness))
        .route("/_readiness", get(readiness));

    Router::new()
        .merge(api_routes)
        .merge(health_routes)
        .with_state(state)
}

async fn index() -> &'static str {
    "agent-sync service"
}

async fn liveness() -> &'static str {
    "ok"
}

async fn readiness(State(state): State<AppState>) -> Result<&'static str, StatusCode> {
    sqlx::query("SELECT 1")
        .execute(&state.pg_pool)
        .await
        .map_err(|_| StatusCode::SERVICE_UNAVAILABLE)?;

    state
        .log_store
        .health_check()
        .await
        .map_err(|_| StatusCode::SERVICE_UNAVAILABLE)?;

    Ok("ok")
}
