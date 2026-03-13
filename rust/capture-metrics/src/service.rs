use crate::metric_record::{flatten_metric, KafkaMetricRow};
use axum::{
    extract::Query,
    extract::State,
    http::{HeaderMap, StatusCode},
    response::Json,
};
use bytes::Bytes;
use limiters::token_dropper::TokenDropper;
use opentelemetry_proto::tonic::collector::metrics::v1::ExportMetricsServiceRequest;
use prost::Message;
use serde::Deserialize;
use serde_json::{json, Value};
use std::fs::File;
use std::io::Write;
use std::sync::Arc;

use crate::kafka::KafkaSink;

use tracing::{debug, error, instrument};

/// Patch empty OTEL JSON values — same workaround as capture-logs for
/// https://github.com/open-telemetry/opentelemetry-rust/issues/1253
pub fn patch_otel_json(v: &mut Value) {
    match v {
        Value::Object(map) => {
            if let Some(inner) = map.get_mut("value") {
                if inner.is_object() && inner.as_object().map(|obj| obj.is_empty()).unwrap_or(false)
                {
                    *inner = Value::Null;
                }
            }
            for (_, val) in map.iter_mut() {
                patch_otel_json(val);
            }
        }
        Value::Array(arr) => {
            for val in arr.iter_mut() {
                patch_otel_json(val);
            }
        }
        _ => {}
    }
}

pub fn parse_otel_message(
    json_bytes: &Bytes,
) -> Result<ExportMetricsServiceRequest, anyhow::Error> {
    if let Ok(mut v) = serde_json::from_slice::<Value>(json_bytes) {
        patch_otel_json(&mut v);
        let result: ExportMetricsServiceRequest = serde_json::from_value(v)?;
        return Ok(result);
    }

    let json_str = std::str::from_utf8(json_bytes)?;
    let lines: Vec<&str> = json_str
        .lines()
        .filter(|line| !line.trim().is_empty())
        .collect();

    let mut merged_request = ExportMetricsServiceRequest {
        resource_metrics: Vec::new(),
    };

    for line in lines {
        let mut v: Value = serde_json::from_str(line)?;
        patch_otel_json(&mut v);
        let request: ExportMetricsServiceRequest = serde_json::from_value(v)?;
        merged_request
            .resource_metrics
            .extend(request.resource_metrics);
    }

    Ok(merged_request)
}

#[derive(Clone)]
pub struct Service {
    pub(crate) sink: KafkaSink,
    pub(crate) token_dropper: Arc<TokenDropper>,
}

#[derive(Deserialize)]
pub struct QueryParams {
    token: Option<String>,
}

impl Service {
    pub async fn new(
        kafka_sink: KafkaSink,
        token_dropper: Arc<TokenDropper>,
    ) -> Result<Self, anyhow::Error> {
        Ok(Self {
            sink: kafka_sink,
            token_dropper,
        })
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
    State(service): State<Service>,
    Query(query_params): Query<QueryParams>,
    headers: HeaderMap,
    body: Bytes,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    if !headers.contains_key("Authorization") && query_params.token.is_none() {
        error!("No token provided");
        return Err((
            StatusCode::UNAUTHORIZED,
            Json(json!({"error": "No token provided"})),
        ));
    }

    let token = if headers.contains_key("Authorization") {
        match headers["Authorization"]
            .to_str()
            .unwrap_or("")
            .split("Bearer ")
            .last()
        {
            Some(token) if !token.is_empty() => token,
            _ => {
                error!("No token provided");
                return Err((
                    StatusCode::UNAUTHORIZED,
                    Json(json!({"error": "No token provided"})),
                ));
            }
        }
    } else {
        match query_params.token {
            Some(ref token) if !token.is_empty() => token,
            _ => {
                error!("No token provided");
                return Err((
                    StatusCode::UNAUTHORIZED,
                    Json(json!({"error": "No token provided"})),
                ));
            }
        }
    };
    if service.token_dropper.should_drop(token, "") {
        return Err((
            StatusCode::UNAUTHORIZED,
            Json(json!({"error": "Invalid token"})),
        ));
    }

    tracing::Span::current().record("token", token);

    let export_request = match ExportMetricsServiceRequest::decode(body.as_ref()) {
        Ok(request) => request,
        Err(proto_err) => match parse_otel_message(&body) {
            Ok(request) => request,
            Err(json_err) => {
                if let Err(e) =
                    File::create("/tmp/last_failed_metric_event.txt").and_then(|mut file| {
                        file.write_all(token.as_bytes())
                            .and_then(|_| file.write_all(&body))
                    })
                {
                    error!("Failed to write last failed event to file: {}", e);
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

    let row_count = rows.len();
    if let Err(e) = service
        .sink
        .write(token, rows, body.len() as u64, timestamps_overridden)
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

pub async fn options_handler(
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    Ok(Json(json!({})))
}
