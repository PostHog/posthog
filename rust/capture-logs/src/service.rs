use crate::log_record::KafkaLogRow;
use axum::{
    extract::State,
    http::{HeaderMap, StatusCode},
    response::Json,
};
use bytes::Bytes;
use limiters::token_dropper::TokenDropper;
use opentelemetry_proto::tonic::collector::logs::v1::ExportLogsServiceRequest;
use prost::Message;
use serde_json::json;
use std::sync::Arc;

use crate::kafka::KafkaSink;

use tracing::{debug, error};

#[derive(Clone)]
pub struct Service {
    sink: KafkaSink,
    token_dropper: Arc<TokenDropper>,
}

impl Service {
    pub async fn new(
        kafka_sink: KafkaSink,
        token_dropper: TokenDropper,
    ) -> Result<Self, anyhow::Error> {
        Ok(Self {
            sink: kafka_sink,
            token_dropper: token_dropper.into(),
        })
    }
}

pub async fn export_logs_http(
    State(service): State<Service>,
    headers: HeaderMap,
    body: Bytes,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    // The Project API key must be passed in as a Bearer token in the Authorization header
    if !headers.contains_key("Authorization") {
        error!("No Authorization header");
        return Err((
            StatusCode::UNAUTHORIZED,
            Json(json!({"error": format!("No Authorization header")})),
        ));
    }

    let token = match headers["Authorization"]
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
                Json(json!({"error": format!("No token provided")})),
            ));
        }
    };
    if service.token_dropper.should_drop(token, "") {
        return Err((
            StatusCode::UNAUTHORIZED,
            Json(json!({"error": format!("Invalid token")})),
        ));
    }
    let export_request = ExportLogsServiceRequest::decode(body.as_ref()).map_err(|e| {
        error!("Failed to decode protobuf: {}", e);
        (
            StatusCode::BAD_REQUEST,
            Json(json!({"error": format!("Failed to decode protobuf: {}", e)})),
        )
    })?;

    let mut rows: Vec<KafkaLogRow> = Vec::new();
    for resource_logs in export_request.resource_logs {
        for scope_logs in resource_logs.scope_logs {
            for log_record in scope_logs.log_records {
                let row = match KafkaLogRow::new(
                    log_record,
                    resource_logs.resource.clone(),
                    scope_logs.scope.clone(),
                ) {
                    Ok(row) => row,
                    Err(e) => {
                        error!("Failed to create LogRow: {e}");
                        return Err((
                            StatusCode::BAD_REQUEST,
                            Json(json!({"error": format!("Bad input format provided")})),
                        ));
                    }
                };
                rows.push(row);
            }
        }
    }

    if let Err(e) = service.sink.write(token, rows, body.len() as u64).await {
        error!("Failed to send logs to Kafka: {}", e);
        return Err((
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(json!({"error": format!("Internal server error")})),
        ));
    } else {
        debug!("Successfully sent logs to Kafka");
    }

    // Return empty JSON object per OTLP spec
    Ok(Json(json!({})))
}
