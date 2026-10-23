use std::sync::Arc;

use axum::{extract::Json, http::StatusCode};
use chrono::Utc;
use common_kafka::kafka_producer::send_keyed_iter_to_kafka;
use common_types::embedding::{
    EmbeddingRecord, EmbeddingRequest, EmbeddingResponse, EmbeddingResult, ModelResult,
};
use metrics::counter;
use serde::{Deserialize, Serialize};
use tracing::{error, warn};
use uuid::Uuid;

use crate::{
    app_context::AppContext,
    handle_single,
    metrics_utils::{RequestLabels, DROPPED_REQUESTS},
    organization::apply_ai_opt_in,
    record_recently_seen,
};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StoredEmbeddingResponse {
    pub results: Vec<ModelResult>,
}

/// Embeds and stores a document exactly as a Kafka request would, and also returns the
/// vectors, so a caller that needs them does not pay for a second embedding.
/// Callers retry 5xx and give up on 4xx, as with the ad hoc endpoint.
pub async fn handle_stored_request(
    context: Arc<AppContext>,
    request: EmbeddingRequest,
) -> Result<Json<StoredEmbeddingResponse>, StatusCode> {
    let team_id = request.team_id;
    // Labelled like `/generate/ad_hoc`: the request's free-form fields would let any caller mint new metric series.
    let labels = RequestLabels::default().and([("from", "api_stored")]);

    let request = match apply_ai_opt_in(&context, request, team_id).await {
        Ok(Some(request)) => request,
        Ok(None) => {
            counter!(
                DROPPED_REQUESTS,
                labels.and([("cause", "ai_opt_in")]).render()
            )
            .increment(1);
            warn!("Stored embedding request for team {team_id} rejected: organization not opted in to ai features");
            return Err(StatusCode::FORBIDDEN);
        }
        Err(e) => {
            error!(
                "Stored embedding request for team {team_id} failed to resolve organization: {e:?}"
            );
            return Err(StatusCode::INTERNAL_SERVER_ERROR);
        }
    };

    if request.models.is_empty() {
        return Err(StatusCode::BAD_REQUEST);
    }
    if !fits_in_kafka_message(&context, &request) {
        counter!(
            DROPPED_REQUESTS,
            labels.and([("cause", "too_large")]).render()
        )
        .increment(1);
        warn!(
            "Stored embedding request for team {team_id} rejected: document too large to publish"
        );
        return Err(StatusCode::PAYLOAD_TOO_LARGE);
    }

    let mut results = Vec::with_capacity(request.models.len());
    for model in &request.models {
        let (model, embedding) = handle_single(context.clone(), *model, &request, labels.clone())
            .await
            .map_err(|e| {
                error!("Stored embedding request for team {team_id} failed: {e:?}");
                StatusCode::INTERNAL_SERVER_ERROR
            })?;
        results.push(ModelResult {
            model,
            outcome: EmbeddingResult::Success { embedding },
        });
    }

    let response = EmbeddingResponse { request, results };
    let records: Vec<EmbeddingRecord> = response.clone().into();

    emit(&context, &context.config.response_topic, [&response]).await?;
    // Capture immediately before Kafka assigns ClickHouse inserted_at, as the Kafka path does.
    let emitted_at = Utc::now();
    emit(&context, &context.config.output_topic, &records).await?;
    record_recently_seen(&context, &records, emitted_at).await;

    Ok(Json(StoredEmbeddingResponse {
        results: response.results,
    }))
}

// Upper bound on one JSON-encoded 3072-dimension vector, which the published messages add to the request.
const VECTOR_JSON_BYTES: usize = 96 * 1024;
// librdkafka's default `message.max.bytes`.
const DEFAULT_KAFKA_MESSAGE_MAX_BYTES: usize = 1_000_000;

// Rejects up front a document whose messages Kafka would refuse, so the caller does not retry paid embedding work.
fn fits_in_kafka_message(context: &AppContext, request: &EmbeddingRequest) -> bool {
    let max_bytes = context
        .config
        .kafka
        .kafka_producer_message_max_bytes
        .map_or(DEFAULT_KAFKA_MESSAGE_MAX_BYTES, |v| v as usize);
    let request_bytes = serde_json::to_vec(request).map_or(usize::MAX, |b| b.len());
    request_bytes.saturating_add(request.models.len() * VECTOR_JSON_BYTES) <= max_bytes
}

async fn emit<T: Serialize>(
    context: &AppContext,
    topic: &str,
    items: impl IntoIterator<Item = T>,
) -> Result<(), StatusCode> {
    let results = send_keyed_iter_to_kafka(
        &context.producer,
        topic,
        |_| Some(Uuid::now_v7().to_string()),
        items,
    )
    .await;
    for result in results {
        if let Err(e) = result {
            error!("Stored embedding request failed to emit to {topic}: {e:?}");
            return Err(StatusCode::INTERNAL_SERVER_ERROR);
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use common_types::embedding::EmbeddingModel;
    use serde_json::json;

    use super::*;

    #[test]
    fn response_shape_matches_what_the_python_client_reads() {
        let response = StoredEmbeddingResponse {
            results: vec![ModelResult {
                model: EmbeddingModel::OpenAITextEmbeddingLarge,
                outcome: EmbeddingResult::Success {
                    embedding: vec![0.5, -0.25],
                },
            }],
        };
        assert_eq!(
            serde_json::to_value(&response).unwrap(),
            json!({"results": [{"model": "text-embedding-3-large-3072", "outcome": "success", "embedding": [0.5, -0.25]}]})
        );
    }
}
