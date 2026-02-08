use std::{collections::HashMap, sync::Arc};

use axum::{
    extract::{Json, Path, State},
    response::IntoResponse,
};
use chrono::Utc;
use common_types::format::parse_datetime_assuming_utc;
use reqwest::StatusCode;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use thiserror::Error;
use tracing::warn;
use uuid::Uuid;

use crate::{
    app_context::AppContext,
    error::UnhandledError,
    fingerprinting::resolve_fingerprint,
    issue_resolution::{resolve_issue, IssueStatus},
    types::{OutputErrProps, RawErrProps},
};

// Actual errors - invalid requests or processing failures
#[derive(Debug, Error)]
pub enum ProcessEventError {
    #[error("Failed to parse event: {0}")]
    InvalidRequest(#[from] serde_json::Error),
    #[error("Exception list cannot be empty")]
    EmptyExceptionList,
    #[error("Team ID mismatch: path team_id {path} does not match payload team_id {payload}")]
    TeamIdMismatch { path: i32, payload: i32 },
    #[error("Failed to process event: {0}")]
    ProcessingError(#[from] UnhandledError),
}

impl ProcessEventError {
    fn to_status_code(&self) -> StatusCode {
        match self {
            ProcessEventError::InvalidRequest(_) => StatusCode::BAD_REQUEST,
            ProcessEventError::EmptyExceptionList => StatusCode::BAD_REQUEST,
            ProcessEventError::TeamIdMismatch { .. } => StatusCode::BAD_REQUEST,
            ProcessEventError::ProcessingError(_) => StatusCode::INTERNAL_SERVER_ERROR,
        }
    }

    fn to_json(&self) -> Json<Value> {
        Json(json!({ "error": self.to_string() }))
    }
}

impl IntoResponse for ProcessEventError {
    fn into_response(self) -> axum::response::Response {
        (self.to_status_code(), self.to_json()).into_response()
    }
}

// Successful outcomes - both are valid responses to a well-formed request
#[derive(Debug, Serialize)]
pub struct ProcessEventResponse {
    issue_id: Uuid,
    issue_status: IssueStatus,
    #[serde(skip_serializing_if = "Option::is_none")]
    event: Option<OutputErrProps>,
}

impl IntoResponse for ProcessEventResponse {
    fn into_response(self) -> axum::response::Response {
        (StatusCode::OK, Json(self)).into_response()
    }
}

// Given a Clickhouse Event's properties, we care about the contents
// of only a small subset. This struct is used to give us a strongly-typed
// "view" of those event properties we care about.
#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct ResolvedExceptionEvent {
    pub uuid: Uuid,
    pub timestamp: String,
    pub team_id: i32,
    #[serde(flatten)]
    pub error_properties: RawErrProps,
    #[serde(flatten)]
    // A catch-all for all the properties we don't "care" about, so when we send back to kafka we don't lose any info
    pub other: HashMap<String, Value>,
}

pub async fn process_event(
    Path(team_id): Path<i32>,
    State(ctx): State<Arc<AppContext>>,
    Json(event): Json<ResolvedExceptionEvent>,
) -> Result<ProcessEventResponse, ProcessEventError> {
    // Validate that team_id in path matches team_id in payload
    if team_id != event.team_id {
        return Err(ProcessEventError::TeamIdMismatch {
            path: team_id,
            payload: event.team_id,
        });
    }

    // Validate that exception list is not empty
    if event.error_properties.exception_list.is_empty() {
        return Err(ProcessEventError::EmptyExceptionList);
    }

    // Generate fingerprint (uses resolved frames for hashing, or applies grouping rules)
    let fingerprint = resolve_fingerprint(&ctx, team_id, &event.error_properties).await?;

    let fingerprinted = event.error_properties.to_fingerprinted(fingerprint);

    // Extract name and description for the issue
    let name = fingerprinted
        .proposed_issue_name
        .clone()
        .unwrap_or_else(|| fingerprinted.exception_list[0].exception_type.clone());

    let description = fingerprinted
        .proposed_issue_description
        .clone()
        .unwrap_or_else(|| fingerprinted.exception_list[0].exception_message.clone());

    let event_timestamp = parse_datetime_assuming_utc(&event.timestamp).unwrap_or_else(|e| {
        warn!(
            event = event.uuid.to_string(),
            "Failed to get event timestamp, using current time, error: {:?}", e
        );
        Utc::now()
    });

    // Resolve issue (create new or find existing)
    let issue = resolve_issue(
        ctx.clone(),
        team_id,
        name,
        description,
        event_timestamp,
        fingerprinted.clone(),
    )
    .await?;

    // Check if issue is suppressed
    if issue.status == IssueStatus::Suppressed {
        return Ok(ProcessEventResponse {
            issue_id: issue.id,
            issue_status: issue.status,
            event: None,
        });
    }

    // Return output
    Ok(ProcessEventResponse {
        issue_id: issue.id,
        issue_status: issue.status,
        event: Some(fingerprinted.to_output(issue.id)),
    })
}
