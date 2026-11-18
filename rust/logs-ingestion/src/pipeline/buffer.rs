use std::time::Instant;

use metrics::histogram;

use crate::avro::{decode_container, encode_container};
use crate::content_weights::{run_pipeline_stages, DropStats, PipelineStage};
use crate::normalize::{
    buffer_processing_mode, transform_decoded_log_records_in_place, BufferProcessingMode,
    LogsSettings,
};
use crate::pii::{PiiScrubStats, EMPTY_PII};
use crate::record::LogRecord;

/// Runs after normalize and before the stages: it sees every record post-scrub and pre-drop.
pub type RecordsVisitor<'a> = Box<dyn FnMut(&[LogRecord]) -> anyhow::Result<()> + Send + 'a>;

#[derive(Debug)]
pub enum BufferValue {
    Original,
    Encoded(Vec<u8>),
    Dropped,
}

pub struct ProcessedBuffer {
    pub value: BufferValue,
    pub pii: PiiScrubStats,
    pub drops: DropStats,
}

pub async fn process_log_message_buffer(
    buffer: &[u8],
    settings: &LogsSettings,
    mut visitor: Option<RecordsVisitor<'_>>,
    stages: &[PipelineStage],
) -> anyhow::Result<ProcessedBuffer> {
    let mode = buffer_processing_mode(settings, stages.len(), visitor.is_some());
    if mode == BufferProcessingMode::Passthrough {
        return Ok(ProcessedBuffer {
            value: BufferValue::Original,
            pii: EMPTY_PII,
            drops: DropStats::default(),
        });
    }

    let start = Instant::now();
    let mut codec = "unknown".to_string();
    let result = async {
        let container = decode_container(buffer)?;
        codec = container.codec.clone();
        let mut records: Vec<LogRecord> = container
            .records
            .into_iter()
            .map(LogRecord::from_value)
            .collect();
        let pii = transform_decoded_log_records_in_place(&mut records, settings);
        if let Some(visit) = visitor.as_mut() {
            visit(&records)?;
        }
        let (kept, drops) = run_pipeline_stages(records, stages).await?;
        if kept.is_empty() {
            return Ok(ProcessedBuffer {
                value: BufferValue::Dropped,
                pii,
                drops,
            });
        }
        if mode == BufferProcessingMode::DecodeOnly {
            return Ok(ProcessedBuffer {
                value: BufferValue::Original,
                pii,
                drops,
            });
        }
        let values: Vec<_> = kept.into_iter().map(LogRecord::into_value).collect();
        let encoded = encode_container(&container.schema, &container.codec, &values)?;
        Ok(ProcessedBuffer {
            value: BufferValue::Encoded(encoded),
            pii,
            drops,
        })
    }
    .await;
    histogram!(
        "logs_ingestion_processing_duration_seconds",
        "json_parse_enabled" => settings.json_parse_logs.unwrap_or(false).to_string(),
        "pii_scrub_enabled" => settings.pii_scrub_logs.unwrap_or(false).to_string(),
        "attribute_extraction_enabled" => settings.attribute_key().is_some().to_string(),
        "compression_codec" => codec
    )
    .record(start.elapsed().as_secs_f64());
    result
}
