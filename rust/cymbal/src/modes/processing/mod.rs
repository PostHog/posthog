//! Processing mode: the error-tracking HTTP `/process` pipeline. This is the
//! default mode and wraps the full [`AppContext`] (Kafka, Redis, issue cache,
//! remote-resolution pool) behind the HTTP server. Everything under this module
//! is processing-only; the shared symbol-resolution kernel lives in
//! [`crate::core`].

use std::sync::Arc;

use crate::app_context::AppContext;
use crate::server::start_server;

pub mod app_context;
pub mod config;
pub mod fingerprinting;
pub mod issue_resolution;
pub mod normalization;
pub mod router;
pub mod rules;
pub mod server;
pub mod stages;
pub mod teams;
pub mod tokenizer;
pub mod types;

pub use config::ProcessingConfig;

pub async fn run(config: ProcessingConfig) {
    let context = Arc::new(AppContext::from_config(&config).await.unwrap());
    start_server(config.clone(), context).await;
}
