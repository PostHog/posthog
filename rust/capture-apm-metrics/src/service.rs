//! OTLP metrics handler. Copied from `capture_logs::service::export_metrics_http`
//! so the series label gate can run between row building and the Kafka write
//! without a change to capture-logs. Parsing and flattening still come from the
//! capture-logs library.

use std::fs::File;
use std::io::Write;
use std::sync::Arc;

use axum::{
    extract::Query,
    extract::State,
    http::{HeaderMap, StatusCode},
    response::Json,
};
use bytes::Bytes;
use capture_logs::authorizer::{Authorizer, Signal};
use capture_logs::kafka::KafkaSink;
use capture_logs::metric_record::{flatten_metric, KafkaMetricRow};
use capture_logs::service::parse_otel_metrics_message;
use common_compression::{decompress_gzip_capped, has_gzip_magic_header, CompressionError};
use opentelemetry_proto::tonic::collector::metrics::v1::ExportMetricsServiceRequest;
use prost::Message;
use serde::Deserialize;
use serde_json::json;
use tracing::{debug, error, instrument};

use crate::series_label_gate::SeriesLabelGate;

#[derive(Clone)]
pub struct MetricsService {
    pub(crate) sink: KafkaSink,
    pub(crate) authorizer: Authorizer,
    pub(crate) max_request_body_size_bytes: usize,
    pub(crate) series_label_gate: Arc<SeriesLabelGate>,
}

#[derive(Deserialize)]
pub struct QueryParams {
    token: Option<String>,
}

impl MetricsService {
    pub fn new(
        kafka_sink: KafkaSink,
        authorizer: Authorizer,
        max_request_body_size_bytes: usize,
        series_label_gate: Arc<SeriesLabelGate>,
    ) -> Self {
        Self {
            sink: kafka_sink,
            authorizer,
            max_request_body_size_bytes,
            series_label_gate,
        }
    }
}

pub(crate) fn decode_body_if_gzip_magic(
    body: Bytes,
    max_request_body_size_bytes: usize,
) -> Result<Bytes, (StatusCode, Json<serde_json::Value>)> {
    if !has_gzip_magic_header(&body) {
        return Ok(body);
    }

    match decompress_gzip_capped(&body, max_request_body_size_bytes) {
        Ok(decompressed) => Ok(Bytes::from(decompressed)),
        Err(CompressionError::OutputTooLarge {
            decompressed,
            limit,
        }) => Err((
            StatusCode::PAYLOAD_TOO_LARGE,
            Json(json!({
                "error": format!("Decompressed request body exceeds limit ({decompressed} > {limit} bytes)")
            })),
        )),
        Err(e) => Err((
            StatusCode::BAD_REQUEST,
            Json(json!({"error": format!("Failed to decompress gzip request body: {e}")})),
        )),
    }
}

#[instrument(skip_all, fields(
    token = tracing::field::Empty,
    content_type = %headers.get("content-type")
        .and_then(|v| v.to_str().ok())
        .unwrap_or(""),
    user_agent = %headers.get("user-agent")
        .and_then(|v| v.to_str().ok())
        .unwrap_or(""),
    content_length = %headers.get("content-length")
        .and_then(|v| v.to_str().ok())
        .unwrap_or(""),
    content_encoding = %headers.get("content-encoding")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("")))
]
pub async fn export_metrics_http(
    State(service): State<MetricsService>,
    Query(query_params): Query<QueryParams>,
    headers: HeaderMap,
    body: Bytes,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    let token =
        service
            .authorizer
            .authorize(&headers, query_params.token.as_deref(), Signal::Metrics)?;

    tracing::Span::current().record("token", token);

    let body = decode_body_if_gzip_magic(body, service.max_request_body_size_bytes)?;

    let export_request = match ExportMetricsServiceRequest::decode(body.as_ref()) {
        Ok(request) => request,
        Err(proto_err) => match parse_otel_metrics_message(&body) {
            Ok(request) => request,
            Err(json_err) => {
                if let Err(e) =
                    File::create("/tmp/last_failed_metric_event.txt").and_then(|mut file| {
                        file.write_all(token.as_bytes())
                            .and_then(|_| file.write_all(&body))
                    })
                {
                    error!("Failed to write last failed metric event to file: {}", e);
                }
                error!(
                    "Failed to decode JSON: {} or Protobuf: {}",
                    json_err, proto_err
                );
                return Err((
                    StatusCode::BAD_REQUEST,
                    Json(
                        json!({"error": format!("Failed to decode JSON: {} or Protobuf: {}", json_err, proto_err)}),
                    ),
                ));
            }
        },
    };

    let mut rows: Vec<KafkaMetricRow> = Vec::new();
    let mut timestamps_overridden: u64 = 0;

    for resource_metrics in &export_request.resource_metrics {
        for scope_metrics in &resource_metrics.scope_metrics {
            for metric in &scope_metrics.metrics {
                let (metric_rows, overridden) = match flatten_metric(
                    metric.clone(),
                    resource_metrics.resource.as_ref(),
                    scope_metrics.scope.as_ref(),
                ) {
                    Ok(result) => result,
                    Err(e) => {
                        error!("Failed to flatten metric: {e}");
                        return Err((
                            StatusCode::BAD_REQUEST,
                            Json(json!({"error": "Bad input format provided"})),
                        ));
                    }
                };
                timestamps_overridden += overridden;
                rows.extend(metric_rows);
            }
        }
    }

    service.series_label_gate.apply(token, &mut rows);

    let row_count = rows.len();
    if let Err(e) = service
        .sink
        .write_metrics(token, rows, body.len() as u64, timestamps_overridden)
        .await
    {
        error!("Failed to send metrics to Kafka: {}", e);
        return Err((
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(json!({"error": "Internal server error"})),
        ));
    } else {
        debug!(
            "Successfully sent {} metric data points to Kafka",
            row_count
        );
    }

    Ok(Json(json!({})))
}
