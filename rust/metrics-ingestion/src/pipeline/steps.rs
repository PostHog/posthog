//! The steps of `metrics-ingestion-pipeline.ts`, with Node's step names, which the DLQ `dlq_step` header carries.

use std::sync::Arc;

use ingestion_framework::result_handling::produce_message_to_dlq;
use ingestion_framework::{
    dlq, drop, ok, ChunkProcessingStep, Headers, KafkaMessage, OutputMessage, PipelineResult,
    ProcessingStep, SideEffect, WithBatch,
};
use logs_ingestion::pipeline::context::parse_kafka_headers;

use super::consumer::MetricsPipelineContext;
use super::retry::{
    error_name, is_retriable, retry_after_first_failure, PRODUCE_RETRY, RESOLVE_TEAM_RETRY,
};
use super::types::{
    MetricsIngestionMessage, MetricsPipelineInput, MetricsSizes, DEFAULT_METRICS_RETENTION_DAYS,
    METRICS_OUTPUT, QUOTA_RESOURCE,
};
use super::usage::{kafka_message_usage_identity, MetricsUsageBatchContext};

pub type Batched<T> = WithBatch<T, MetricsUsageBatchContext>;

const SIZE_HEADERS: [&str; 4] = [
    "bytes_uncompressed",
    "bytes_uncompressed_records",
    "bytes_compressed",
    "record_count",
];
const MAX_SAFE_INTEGER: f64 = 9_007_199_254_740_991.0;

fn count_dropped(reason: &'static str, team_id: Arc<str>) {
    metrics::counter!("metrics_ingestion_message_dropped_count", "reason" => reason, "team_id" => team_id)
        .increment(1);
}

fn count_dlq(reason: Arc<str>, team_id: Arc<str>) {
    metrics::counter!("metrics_ingestion_message_dlq_count", "reason" => reason, "team_id" => team_id)
        .increment(1);
}

/// A missing header counts as 0. A negative value makes the Prometheus counters throw in Node, so only non-negative safe integers are valid.
pub fn parse_size_header(value: Option<&str>) -> Option<u64> {
    let Some(value) = value else { return Some(0) };
    if value.is_empty() || !value.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    // `Number(value)` rounds a long digit string to a double first.
    let parsed: f64 = value.parse().ok()?;
    (parsed <= MAX_SAFE_INTEGER).then_some(parsed as u64)
}

/// `parseMetricsHeadersStep`.
pub fn parse_metrics_headers(
    message: &KafkaMessage,
) -> Result<(Headers, String, MetricsSizes), &'static str> {
    let headers = parse_kafka_headers(message);
    let token = match headers.get("token") {
        Some(token) if !token.is_empty() => token.to_string(),
        _ => {
            tracing::error!("missing_token");
            return Err("missing_token");
        }
    };
    let parsed = SIZE_HEADERS.map(|name| parse_size_header(headers.get(name)));
    let [Some(bytes_uncompressed), Some(bytes_uncompressed_records), Some(bytes_compressed), Some(record_count)] =
        parsed
    else {
        let invalid: Vec<&str> = SIZE_HEADERS
            .iter()
            .zip(parsed)
            .filter(|(_, v)| v.is_none())
            .map(|(name, _)| *name)
            .collect();
        tracing::error!(headers = ?invalid, "invalid_size_header");
        return Err("invalid_size_header");
    };
    Ok((
        headers,
        token,
        MetricsSizes {
            bytes_uncompressed,
            bytes_uncompressed_records,
            bytes_compressed,
            record_count,
        },
    ))
}

/// `resolveMetricsTeamStep`. `Err` is a retriable lookup error, which the retry wraps and then fails the batch with.
async fn resolve_team(
    context: &MetricsPipelineContext,
    token: &str,
) -> anyhow::Result<PipelineResult<i64>> {
    let deps = &context.deps;
    let lookup = if token == "phc_local" && deps.dev_env {
        deps.team_manager.get_team(1).await
    } else {
        deps.team_manager.get_team_by_token(token).await
    };
    match lookup {
        Err(error) if is_retriable(&error) == Some(true) => Err(error),
        Err(error) => {
            tracing::error!(%error, "team_lookup_error");
            count_dlq(Arc::from("team_lookup_error"), Arc::from("unknown"));
            Ok(dlq("team_lookup_error", Some(error)))
        }
        Ok(None) => {
            tracing::error!(token_with_no_team = token, "team_not_found");
            count_dropped("team_not_found", Arc::from("unknown"));
            Ok(drop("team_not_found"))
        }
        Ok(Some(team)) => Ok(ok(team.id)),
    }
}

/// `prepareMetricsMessageStep`: parse the headers, resolve the team, record the received usage, and drop quota-limited teams.
pub fn create_prepare_metrics_message_step(
    context: Arc<MetricsPipelineContext>,
) -> ProcessingStep<Batched<MetricsPipelineInput>, Batched<MetricsIngestionMessage>> {
    ProcessingStep::new(
        "prepareMetricsMessageStep",
        move |input: Batched<MetricsPipelineInput>| {
            let context = context.clone();
            async move {
                let (kafka_headers, token, sizes) = match parse_metrics_headers(&input.message) {
                    Ok(parsed) => parsed,
                    Err(reason) => {
                        count_dropped(reason, Arc::from("unknown"));
                        return Ok(drop(reason));
                    }
                };
                let resolved = retry_after_first_failure(
                    || resolve_team(&context, &token),
                    RESOLVE_TEAM_RETRY,
                )
                .await?;
                let team_id = match resolved.outcome {
                    ingestion_framework::Outcome::Ok(team_id) => team_id,
                    ingestion_framework::Outcome::NonOk(non_ok) => {
                        return Ok(PipelineResult::new(ingestion_framework::Outcome::NonOk(
                            non_ok,
                        )))
                    }
                };
                input.batch.usage.lock().unwrap().record_received(
                    team_id,
                    sizes.bytes_uncompressed as f64,
                    sizes.record_count as f64,
                );
                if context
                    .deps
                    .quota_limiting
                    .is_team_token_quota_limited(&token, QUOTA_RESOURCE)
                    .await?
                {
                    input.batch.usage.lock().unwrap().record_dropped(
                        team_id,
                        sizes.bytes_uncompressed as f64,
                        sizes.record_count as f64,
                    );
                    count_dropped("quota_limited", Arc::from(team_id.to_string()));
                    return Ok(drop("quota_limited"));
                }
                let message = input.message.clone();
                Ok(ok(WithBatch {
                    value: MetricsIngestionMessage {
                        message,
                        kafka_headers,
                        token,
                        team_id,
                        sizes,
                    },
                    batch: input.batch,
                }))
            }
        },
    )
}

/// `rateLimitMetricsStep`. Allowed usage is recorded here, before the produce, so a message that later goes to the DLQ is still billed.
pub fn create_rate_limit_metrics_step(
    context: Arc<MetricsPipelineContext>,
) -> ChunkProcessingStep<Batched<MetricsIngestionMessage>, Batched<MetricsIngestionMessage>> {
    ChunkProcessingStep::new(
        "rateLimitMetricsStep",
        move |values: Vec<Batched<MetricsIngestionMessage>>| {
            let context = context.clone();
            async move {
                let messages: Vec<&MetricsIngestionMessage> =
                    values.iter().map(|v| &v.value).collect();
                let dropped = context.rate_limiter.dropped(&messages).await?;
                Ok(values
                    .into_iter()
                    .zip(dropped)
                    .map(|(value, dropped)| {
                        let m = &value.value;
                        let mut usage = value.batch.usage.lock().unwrap();
                        if dropped {
                            usage.record_dropped(
                                m.team_id,
                                m.sizes.bytes_uncompressed as f64,
                                m.sizes.record_count as f64,
                            );
                            count_dropped("rate_limited", Arc::from(m.team_id.to_string()));
                            return drop("rate_limited");
                        }
                        usage.record_allowed(
                            m.team_id,
                            kafka_message_usage_identity(&m.message),
                            m.sizes.bytes_uncompressed as f64,
                            m.sizes.record_count as f64,
                            m.sizes.bytes_uncompressed_records as f64,
                        );
                        std::mem::drop(usage);
                        ok(value)
                    })
                    .collect())
            }
        },
    )
}

/// `produceMetricsStep`. The produce runs as a side effect. A message that still fails after the retries goes to the DLQ, and a
/// failed DLQ write rejects the side effect, so the consumer stores no offsets and the batch replays.
pub fn create_produce_metrics_step(
    context: Arc<MetricsPipelineContext>,
) -> ProcessingStep<Batched<MetricsIngestionMessage>, ()> {
    ProcessingStep::sync(
        "produceMetricsStep",
        move |input: Batched<MetricsIngestionMessage>| {
            let input = input.value;
            let team_label = input.team_id.to_string();
            let Some(value) = input.message.value.clone() else {
                count_dropped("null_value", Arc::from(team_label));
                return Ok(drop("null_value"));
            };
            let mut headers = input.kafka_headers.clone();
            headers.set("token", input.token.clone());
            headers.set("team_id", team_label.clone());
            headers.set("retention-days", DEFAULT_METRICS_RETENTION_DAYS.to_string());
            // ClickHouse counts each row toward the partition it was read from too, so the freshness checkpoint sees a lagging partition.
            headers.set("source_topic", input.message.topic.clone());
            headers.set("source_partition", input.message.partition.to_string());
            if context.deps.source_offset_header {
                headers.set("source_offset", input.message.offset.to_string());
            }
            let output = OutputMessage {
                value: Some(value),
                key: None,
                headers,
            };
            let outputs = context.deps.outputs.clone();
            let side_effect = SideEffect::spawn(async move {
                let produced = retry_after_first_failure(
                    || outputs.produce(METRICS_OUTPUT, output.clone()),
                    PRODUCE_RETRY,
                )
                .await;
                let Err(error) = produced else { return Ok(()) };
                count_dlq(
                    Arc::from(error_name(&error)),
                    Arc::from(team_label.as_str()),
                );
                let mut dlq_message = (*input.message).clone();
                dlq_message
                    .headers
                    .push(("token".to_string(), Some(input.token.into_bytes())));
                dlq_message
                    .headers
                    .push(("team_id".to_string(), Some(team_label.into_bytes())));
                produce_message_to_dlq(
                    outputs.as_ref(),
                    &dlq_message,
                    &error.to_string(),
                    "produceMetricsStep",
                    true,
                )
                .await
            });
            Ok(ok(()).with_side_effect(side_effect))
        },
    )
}
