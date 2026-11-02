//! Port of `pipeline/parse-logs-message-step.ts`.

use std::sync::Arc;

use ingestion_framework::{drop, ok, KafkaMessage, Outcome, PipelineResult, ProcessingStep};
use metrics::counter;

use crate::internal_logs::INTERNAL_LOGS_HEADER;

use super::context::{parse_kafka_headers, quarantine_log_message, LogsPipelineContext};
use super::deps::Team;
use super::errors::NamedError;
use super::types::{parse_min_timestamp_header, parse_size_header, LogsIngestionMessage};

/// What a parse leaves for the next step: a message, or the failure of a quarantine.
pub struct ParseOutcome {
    pub parsed: Option<LogsIngestionMessage>,
    pub failure: Option<anyhow::Error>,
}

fn count_dropped(reason: &'static str) {
    counter!("logs_ingestion_message_dropped_count", "reason" => reason, "team_id" => "unknown")
        .increment(1);
}

async fn parse(
    context: &LogsPipelineContext,
    message: Arc<KafkaMessage>,
) -> anyhow::Result<PipelineResult<LogsIngestionMessage>> {
    let headers = parse_kafka_headers(&message);
    let token = match headers.get("token") {
        Some(t) if !t.is_empty() => t.to_string(),
        _ => {
            tracing::warn!("missing_token");
            count_dropped("missing_token");
            return Ok(drop("missing_token"));
        }
    };

    let team: Option<Team> = match context.deps.team_manager.get_team_by_token(&token).await {
        Ok(team) => team,
        Err(error) => {
            tracing::error!(error = %error, "team_lookup_error");
            count_dropped("team_lookup_error");
            return Ok(drop("team_lookup_error"));
        }
    };
    let Some(team) = team else {
        tracing::warn!(token_with_no_team = %token, "team_not_found");
        count_dropped("team_not_found");
        return Ok(drop("team_not_found"));
    };

    let bytes_uncompressed = parse_size_header(headers.get("bytes_uncompressed"));
    let bytes_uncompressed_records = parse_size_header(headers.get("bytes_uncompressed_records"));
    let bytes_compressed = parse_size_header(headers.get("bytes_compressed"));
    let record_count = parse_size_header(headers.get("record_count"));
    let (
        Some(bytes_uncompressed),
        Some(bytes_uncompressed_records),
        Some(bytes_compressed),
        Some(record_count),
    ) = (
        bytes_uncompressed,
        bytes_uncompressed_records,
        bytes_compressed,
        record_count,
    )
    else {
        tracing::error!(
            team_id = team.id,
            partition = message.partition,
            offset = message.offset,
            "logs_ingestion_invalid_size_headers"
        );
        let error = anyhow::Error::new(NamedError::new("Error", "invalid_size_headers"));
        quarantine_log_message(context, &message, &error, Some(&token), Some(team.id)).await?;
        return Ok(drop("invalid_size_headers"));
    };

    if bytes_uncompressed_records > bytes_uncompressed {
        counter!("logs_ingestion_records_bytes_exceed_payload_total", "team_id" => team.id.to_string()).increment(1);
    }

    let internal_logs = context.internal_logs_verifier.verify(
        headers.get(INTERNAL_LOGS_HEADER),
        team.id,
        headers.get("created_at"),
    );
    Ok(ok(LogsIngestionMessage {
        token,
        message: message.clone(),
        team_id: team.id,
        bytes_uncompressed,
        bytes_uncompressed_records,
        bytes_compressed,
        record_count,
        min_timestamp_micros: parse_min_timestamp_header(headers.get("min_timestamp")),
        backfill_requested: headers.get("backfill_days").is_some(),
        internal_logs,
    }))
}

/// Reads the capture-logs headers and resolves the team. A failed quarantine is carried as a
/// result, so the batch fails only once every message has settled.
pub fn create_settled_parse_step(
    context: Arc<LogsPipelineContext>,
) -> ProcessingStep<Arc<KafkaMessage>, ParseOutcome> {
    ProcessingStep::new("parseLogsMessageStep", move |message: Arc<KafkaMessage>| {
        let context = context.clone();
        async move {
            let result = match parse(&context, message.clone()).await {
                Ok(result) => result,
                Err(e) => {
                    // A failed quarantine of bad size headers: the second attempt names the DLQ error.
                    tracing::error!(error = %e, partition = message.partition, offset = message.offset, "logs_ingestion_parse_error");
                    count_dropped("parse_error");
                    if let Err(failure) =
                        quarantine_log_message(&context, &message, &e, None, None).await
                    {
                        return Ok(ok(ParseOutcome {
                            parsed: None,
                            failure: Some(failure),
                        }));
                    }
                    drop("parse_error")
                }
            };
            Ok(match result.outcome {
                Outcome::Ok(parsed) => ok(ParseOutcome {
                    parsed: Some(parsed),
                    failure: None,
                }),
                Outcome::NonOk(non_ok) => PipelineResult::new(Outcome::NonOk(non_ok)),
            })
        }
    })
}
