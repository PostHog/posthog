use std::sync::Arc;

use crate::app_context::AppContext;
use axum::{
    extract::State,
    response::{IntoResponse, Response},
    routing::get,
    Router,
};
use common_metrics::setup_metrics_routes;
use eyre::Result;

pub async fn listen(app: Router, bind: String) -> Result<()> {
    let listener = tokio::net::TcpListener::bind(bind).await?;

    axum::serve(listener, app).await?;

    Ok(())
}

async fn index(State(context): State<Arc<AppContext>>) -> String {
    format!("cyclotron janitor {}", context.janitor_id)
}

async fn liveness(State(context): State<Arc<AppContext>>) -> Response {
    context.health.get_status().into_response()
}

pub fn app(context: Arc<AppContext>) -> Router {
    let metrics_enabled = context.metrics;
    let router = Router::new();

    let router = router
        .route("/", get(index))
        .route("/_readiness", get(index))
        .route("/_liveness", get(liveness));

    // setup_metrics_routes touches global objects, so we need to be able to selectively
    // disable it e.g. for tests
    let router = if metrics_enabled {
        setup_metrics_routes(router)
    } else {
        router
    };

    router.with_state(context)
}
