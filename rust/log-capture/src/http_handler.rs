use axum::{
    extract::State,
    http::{HeaderMap, StatusCode},
    response::Json,
    routing::post,
    Router,
};
use bytes::Bytes;
use opentelemetry_proto::tonic::collector::logs::v1::{
    ExportLogsServiceRequest,
};
use prost::Message;
use tracing::error;
use serde_json::json;

use crate::{
    auth::extract_team_id_from_http_headers,
    log_record::LogRow,
    service::Service,
    json_converter::{JsonLogEntry, convert_custom_log_to_log_row}
};

/// HTTP handler for OTLP logs
pub async fn export_logs_http(
    State(service): State<Service>,
    headers: HeaderMap,
    body: Bytes,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    let team_id = extract_team_id_from_http_headers(&headers, &service.config.jwt_secret)
        .map_err(|e| {
            error!("Authentication failed: {}", e);
            (
                StatusCode::UNAUTHORIZED,
                Json(json!({"error": format!("Authentication failed: {}", e)})),
            )
        })?;

    let team_id = team_id.parse::<i32>().map_err(|e| {
        error!("Failed to parse team_id '{}' as i32: {}", team_id, e);
        (
            StatusCode::BAD_REQUEST,
            Json(json!({"error": format!("Invalid team_id format: {}", e)})),
        )
    })?;

    // Decode protobuf message from HTTP body
    let export_request = ExportLogsServiceRequest::decode(body.as_ref()).map_err(|e| {
        error!("Failed to decode protobuf: {}", e);
        (
            StatusCode::BAD_REQUEST,
            Json(json!({"error": format!("Failed to decode protobuf: {}", e)})),
        )
    })?;

    process_otlp_logs(&service, team_id, export_request).await
}

/// Convert developer-friendly json logs format to LogRecord
pub async fn export_logs_json(
    State(service): State<Service>,
    headers: HeaderMap,
    body: Bytes,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    let team_id = extract_team_id_from_http_headers(&headers, &service.config.jwt_secret)
        .map_err(|e| {
            error!("Authentication failed: {}", e);
            (
                StatusCode::UNAUTHORIZED,
                Json(json!({"error": format!("Authentication failed: {}", e)})),
            )
        })?;

    let team_id = team_id.parse::<i32>().map_err(|e| {
        error!("Failed to parse team_id '{}' as i32: {}", team_id, e);
        (
            StatusCode::BAD_REQUEST,
            Json(json!({"error": format!("Invalid team_id format: {}", e)})),
        )
    })?;

    let json_str = String::from_utf8(body.to_vec()).map_err(|e| {
        error!("Failed to decode JSON body as UTF-8: {}", e);
        (
            StatusCode::BAD_REQUEST,
            Json(json!({"error": "Invalid UTF-8 in JSON body"})),
        )
    })?;

    let log_entries: Vec<JsonLogEntry> = serde_json::from_str(&json_str).map_err(|e| {
        error!("Failed to parse JSON logs: {}", e);
        (
            StatusCode::BAD_REQUEST,
            Json(json!({"error": format!("Failed to parse JSON logs: {}", e)})),
        )
    })?;

    process_custom_json_logs(&service, team_id, log_entries).await
}

pub async fn export_traces_http(
    State(_service): State<Service>,
    _headers: HeaderMap,
    _body: Bytes,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    Ok(Json(json!({})))
}

async fn process_otlp_logs(
    service: &Service,
    team_id: i32,
    export_request: ExportLogsServiceRequest,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    let mut insert = service
        .clickhouse_writer
        .client
        .insert(&service.config.clickhouse_table)
        .map_err(|e| {
            error!("Failed to create ClickHouse insert: {}", e);
            (
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(json!({"error": format!("Failed to create ClickHouse insert: {}", e)})),
            )
        })?;

    for resource_logs in export_request.resource_logs {
        for scope_logs in resource_logs.scope_logs {
            for log_record in scope_logs.log_records {
                let row = LogRow::new(
                    team_id,
                    log_record,
                    resource_logs.resource.clone(),
                    scope_logs.scope.clone(),
                )
                .map_err(|e| {
                    error!("Failed to create LogRow: {}", e);
                    (
                        StatusCode::INTERNAL_SERVER_ERROR,
                        Json(json!({"error": "Failed to process log record"})),
                    )
                })?;

                insert.write(&row).await.map_err(|e| {
                    error!("Failed to insert log into ClickHouse: {}", e);
                    (
                        StatusCode::INTERNAL_SERVER_ERROR,
                        Json(json!({"error": "Failed to insert log"})),
                    )
                })?;
            }
        }
    }

    insert.end().await.map_err(|e| {
        error!("Failed to end ClickHouse insert: {}", e);
        (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(json!({"error": "Failed to complete insert"})),
        )
    })?;

    // Return empty JSON object per OTLP spec
    Ok(Json(json!({})))
}

async fn process_custom_json_logs(
    service: &Service,
    team_id: i32,
    log_entries: Vec<JsonLogEntry>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    let mut insert = service
        .clickhouse_writer
        .client
        .insert(&service.config.clickhouse_table)
        .map_err(|e| {
            error!("Failed to create ClickHouse insert: {}", e);
            (
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(json!({"error": format!("Failed to create ClickHouse insert: {}", e)})),
            )
        })?;

    for log_entry in &log_entries {
        let row = convert_custom_log_to_log_row(team_id, log_entry.clone()).map_err(|e| {
            error!("Failed to convert log entry: {}", e);
            (
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(json!({"error": format!("Failed to process log entry: {}", e)})),
            )
        })?;

        insert.write(&row).await.map_err(|e| {
            error!("Failed to insert log into ClickHouse: {}", e);
            (
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(json!({"error": "Failed to insert log"})),
            )
        })?;
    }

    insert.end().await.map_err(|e| {
        error!("Failed to end ClickHouse insert: {}", e);
        (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(json!({"error": "Failed to complete insert"})),
        )
    })?;

    Ok(Json(json!({
        "status": "success",
        "processed": log_entries.len()
    })))
}

pub fn create_http_router(service: Service) -> Router {
    Router::new()
        .route("/v1/logs", post(export_logs_http))
        .route("/v1/logs/json", post(export_logs_json))
        .route("/v1/traces", post(export_traces_http))
        .with_state(service)
}
