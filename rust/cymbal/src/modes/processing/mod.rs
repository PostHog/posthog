//! Processing mode: the error-tracking HTTP `/process` pipeline. This is the
//! default mode and wraps the full [`AppContext`] (Kafka, Redis, issue cache,
//! remote-resolution pool) behind the HTTP server. Everything under this module
//! is processing-only; the shared symbol-resolution kernel lives in
//! [`crate::core`].

use std::sync::Arc;

use crate::app_context::AppContext;
use crate::config::Config;
use crate::server::start_server;

pub mod app_context;
pub mod fingerprinting;
pub mod issue_resolution;
pub mod analytics;
pub mod rules;
pub mod router;
pub mod server;
pub mod signals;
pub mod stages;
pub mod teams;
pub mod tokenizer;

pub async fn run(config: Config) {
    let context = Arc::new(AppContext::from_config(&config).await.unwrap());
    start_server(config.clone(), context).await;
}
