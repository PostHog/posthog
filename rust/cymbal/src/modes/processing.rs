//! Processing mode: the error-tracking HTTP `/process` pipeline. This is the
//! default mode and wraps the full [`AppContext`] (Kafka, Redis, issue cache,
//! remote-resolution pool) behind the HTTP server.

use std::sync::Arc;

use crate::app_context::AppContext;
use crate::config::Config;
use crate::server::start_server;

pub async fn run(config: Config) {
    let context = Arc::new(AppContext::from_config(&config).await.unwrap());
    start_server(config.clone(), context).await;
}
