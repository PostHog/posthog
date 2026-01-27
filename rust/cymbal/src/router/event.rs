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

#[derive(Debug, Error)]
pub enum ProcessEventError {
    #[error("Failed to parse event: {0}")]
    InvalidRequest(#[from] serde_json::Error),
    #[error("Exception list cannot be empty")]
    EmptyExceptionList,
    #[error("Failed to process event: {0}")]
    ProcessingError(#[from] UnhandledError),
    #[error("Issue is suppressed: {0}")]
    Suppressed(Uuid),
}

impl ProcessEventError {
    fn to_status_code(&self) -> StatusCode {
        match self {
            ProcessEventError::InvalidRequest(_) => StatusCode::BAD_REQUEST,
            ProcessEventError::EmptyExceptionList => StatusCode::BAD_REQUEST,
            ProcessEventError::ProcessingError(_) => StatusCode::INTERNAL_SERVER_ERROR,
            ProcessEventError::Suppressed(_) => StatusCode::OK,
        }
    }

    fn to_json(&self) -> Json<Value> {
        match self {
            ProcessEventError::InvalidRequest(err) => Json(json!({ "error": err.to_string() })),
            ProcessEventError::EmptyExceptionList => {
                Json(json!({ "error": "Exception list cannot be empty" }))
            }
            ProcessEventError::ProcessingError(err) => Json(json!({ "error": err.to_string() })),
            ProcessEventError::Suppressed(issue_id) => {
                Json(json!({ "suppressed": true, "issue_id": issue_id.to_string() }))
            }
        }
    }
}

impl IntoResponse for ProcessEventError {
    fn into_response(self) -> axum::response::Response {
        (self.to_status_code(), self.to_json()).into_response()
    }
}

impl IntoResponse for OutputErrProps {
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
) -> Result<OutputErrProps, ProcessEventError> {
    // Validate that exception list is not empty
    if event.error_properties.exception_list.is_empty() {
        return Err(ProcessEventError::EmptyExceptionList);
    }

    // Acquire database connection for fingerprinting
    let mut conn = ctx
        .posthog_pool
        .acquire()
        .await
        .map_err(UnhandledError::from)?;

    // Generate fingerprint (uses resolved frames for hashing, or applies grouping rules)
    let fingerprint = resolve_fingerprint(
        &mut conn,
        &ctx.team_manager,
        team_id,
        &event.error_properties,
    )
    .await?;
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
    if matches!(issue.status, IssueStatus::Suppressed) {
        return Err(ProcessEventError::Suppressed(issue.id));
    }

    // Return output
    Ok(fingerprinted.to_output(issue.id))
}
