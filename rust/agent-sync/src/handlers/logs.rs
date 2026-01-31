use axum::{
    extract::{Path, Query, State},
    Extension, Json,
};
use uuid::Uuid;

use crate::app::AppState;
use crate::error::Result;
use crate::types::{AgentEvent, AuthContext, LogsQuery};

pub async fn get_logs(
    State(state): State<AppState>,
    Path((project_id, task_id, run_id)): Path<(i64, Uuid, Uuid)>,
    Query(params): Query<LogsQuery>,
    Extension(auth): Extension<AuthContext>,
) -> Result<Json<Vec<AgentEvent>>> {
    state
        .auth
        .authorize_run(auth.user_id, project_id, &task_id, &run_id)
        .await?;

    tracing::debug!(
        project_id = project_id,
        task_id = %task_id,
        run_id = %run_id,
        user_id = auth.user_id,
        "Fetching logs"
    );

    let limit = params
        .limit
        .map(|l| l.clamp(1, state.max_logs_limit))
        .unwrap_or(state.max_logs_limit);

    let events = state
        .log_store
        .get_logs(&run_id, params.after, Some(limit))
        .await?;

    Ok(Json(events))
}
