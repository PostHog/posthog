use axum::{
    extract::{Path, State},
    http::StatusCode,
    Extension, Json,
};
use chrono::Utc;
use uuid::Uuid;

use crate::app::AppState;
use crate::error::Result;
use crate::types::{AgentEvent, AuthContext};

fn extract_entry_type(message: &serde_json::Value) -> String {
    message
        .get("method")
        .and_then(|m| m.as_str())
        .unwrap_or("unknown")
        .to_string()
}

pub async fn post_sync(
    State(state): State<AppState>,
    Path((project_id, task_id, run_id)): Path<(i64, Uuid, Uuid)>,
    Extension(auth): Extension<AuthContext>,
    Json(message): Json<serde_json::Value>,
) -> Result<StatusCode> {
    state
        .auth
        .authorize_run(auth.user_id, project_id, &task_id, &run_id)
        .await?;

    tracing::debug!(
        project_id = project_id,
        task_id = %task_id,
        run_id = %run_id,
        user_id = auth.user_id,
        "Posting sync message"
    );

    let team_id = auth.team_id.ok_or_else(|| {
        crate::error::AppError::Internal("User has no team_id".to_string())
    })?;
    let now = Utc::now();

    let event = AgentEvent {
        team_id: team_id.into(),
        task_id,
        run_id,
        sequence: now.timestamp_micros() as u64,
        timestamp: now,
        entry_type: extract_entry_type(&message),
        entry: message,
    };

    state.publisher.publish(&event).await?;

    Ok(StatusCode::ACCEPTED)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn test_extract_entry_type() {
        let message = json!({
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {}
        });
        assert_eq!(extract_entry_type(&message), "session/update");

        let message = json!({"data": "test"});
        assert_eq!(extract_entry_type(&message), "unknown");
    }
}
