use std::sync::Arc;

use anyhow::Result;
use common_kafka::kafka_consumer::Offset;
use common_types::error_tracking::{EmbeddingRecord, NewFingerprint};

use crate::app_context::AppContext;

pub mod app_context;
pub mod config;
pub mod metric_consts;

pub async fn handle_batch(
    _fingerprints: Vec<NewFingerprint>,
    _offsets: &[Offset],
    _context: Arc<AppContext>,
) -> Result<Vec<EmbeddingRecord>> {
    // Your implementation here
    Ok(vec![]) // For now, we'll just eat the new fingerprint messages
}
