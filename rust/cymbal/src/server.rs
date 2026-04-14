use std::sync::Arc;

use common_metrics::{serve, setup_metrics_routes};
use tracing::info;

use crate::{app_context::AppContext, config::Config, router::get_router};

pub async fn start_server(config: Config, context: Arc<AppContext>) -> () {
    let router = get_router(context);
    let router = setup_metrics_routes(router);
    let bind = format!("{}:{}", config.host, config.port);
    info!("Server started and listening on {}", bind);
    serve(router, &bind)
        .await
        .expect("failed to start serving metrics");
}
