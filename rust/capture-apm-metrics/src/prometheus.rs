//! Prometheus remote-write handler. Copied from
//! `capture_logs::endpoints::prometheus::export_prometheus_remote_write_http`
//! so the series label gate can run between row building and the Kafka write
//! without a change to capture-logs. Decoding and row building still come from
//! the capture-logs library.

use axum::extract::{Path, Query, State};
use axum::http::{HeaderMap, StatusCode};
use axum::Json;
use bytes::Bytes;
use capture_logs::authorizer::Signal;
use capture_logs::endpoints::prometheus::{
    decode_write_request, estimate_expanded_bytes, write_request_to_kafka_rows,
};
use serde::Deserialize;
use serde_json::json;
use tracing::{debug, error, instrument};

use crate::service::MetricsService;

/// How much larger than the (already decompression-capped) request body the
/// expanded row set may be. Row building clones the series label map per
/// sample and the whole batch becomes a single Kafka message, so a 2 wire-byte
/// sample expands to hundreds of bytes — legitimate senders (Prometheus
/// defaults to 2k samples per send, vmagent to 10k rows per block) stay far
/// below this; only expansion-bomb payloads exceed it.
const MAX_EXPANSION_FACTOR: u64 = 16;

#[derive(Deserialize)]
pub struct RemoteWriteQueryParams {
    token: Option<String>,
}

/// Resolve the project token from (in order) the URL path, the Authorization
/// header (Bearer or bare), or the `token` query param — matching the
/// flexibility remote-write senders actually have.
fn extract_token(
    path_token: Option<String>,
    headers: &HeaderMap,
    query_token: Option<&str>,
) -> Option<String> {
    if let Some(token) = path_token {
        if !token.is_empty() {
            return Some(token);
        }
    }
    if let Some(auth) = headers.get("authorization").and_then(|v| v.to_str().ok()) {
        let token = auth
            .strip_prefix("Bearer ")
            .or_else(|| auth.strip_prefix("bearer "))
            .unwrap_or(auth)
            .trim();
        if !token.is_empty() {
            return Some(token.to_string());
        }
    }
    query_token.filter(|t| !t.is_empty()).map(str::to_string)
}

/// Prometheus remote-write v1 ingestion endpoint.
///
/// Snappy-decodes the protobuf body, maps it to `KafkaMetricRow` records, and
/// produces them through the shared `KafkaSink` so the rest of the pipeline is
/// identical to OTLP ingestion. Response codes follow remote-write semantics:
/// 204 on success, 400 on a permanent decode failure (sender drops the batch),
/// 5xx on a transient produce failure (sender retries).
#[instrument(skip_all, fields(
    token = tracing::field::Empty,
    user_agent = %headers.get("user-agent")
        .and_then(|v| v.to_str().ok())
        .unwrap_or(""),
    content_length = %headers.get("content-length")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("")))
]
pub async fn export_prometheus_remote_write_http(
    State(service): State<MetricsService>,
    path_token: Option<Path<String>>,
    Query(query_params): Query<RemoteWriteQueryParams>,
    headers: HeaderMap,
    body: Bytes,
) -> Result<StatusCode, (StatusCode, Json<serde_json::Value>)> {
    let token = match extract_token(
        path_token.map(|Path(t)| t),
        &headers,
        query_params.token.as_deref(),
    ) {
        Some(token) => token,
        None => {
            error!("No token provided");
            return Err((
                StatusCode::UNAUTHORIZED,
                Json(json!({"error": "No token provided"})),
            ));
        }
    };

    service
        .authorizer
        .authorize_token(&token, Signal::Metrics)?;

    tracing::Span::current().record("token", &token);

    let (write_request, uncompressed_bytes) =
        match decode_write_request(&body, service.max_request_body_size_bytes) {
            Ok(decoded) => decoded,
            Err(e) => {
                error!("Failed to decode remote-write request: {e}");
                return Err((
                    StatusCode::BAD_REQUEST,
                    Json(json!({ "error": format!("{e}") })),
                ));
            }
        };

    // 400, not 5xx: a batch that expands past the limit will never fit, so the
    // sender must drop it rather than retry it forever.
    let expanded = estimate_expanded_bytes(&write_request);
    let max_expanded = MAX_EXPANSION_FACTOR * service.max_request_body_size_bytes as u64;
    if expanded > max_expanded {
        error!(
            "Rejecting remote-write request expanding to ~{expanded} bytes (limit {max_expanded})"
        );
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({
                "error": format!("request expands to too many samples (~{expanded} > {max_expanded} bytes); send smaller batches")
            })),
        ));
    }

    let (mut rows, timestamps_overridden) = write_request_to_kafka_rows(write_request);
    service.series_label_gate.apply(&token, &mut rows);
    let row_count = rows.len();

    if let Err(e) = service
        .sink
        .write_metrics(&token, rows, uncompressed_bytes, timestamps_overridden)
        .await
    {
        error!("Failed to send remote-write metrics to Kafka: {e}");
        return Err((
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(json!({"error": "Internal server error"})),
        ));
    }

    debug!("Sent {row_count} remote-write data points to Kafka");
    Ok(StatusCode::NO_CONTENT)
}
