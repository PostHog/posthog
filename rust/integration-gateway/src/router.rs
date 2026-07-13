use std::collections::HashMap;

use axum::extract::State;
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::routing::post;
use axum::{Json, Router};
use common_metrics::inc;
use serde::{Deserialize, Serialize};
use serde_json::json;
use uuid::Uuid;

use crate::app_context::AppState;
use crate::audit::{self, AuditEvent};
use crate::auth::AuthedCaller;
use crate::integrations::DecryptedIntegration;
use crate::metrics_consts;

#[derive(Deserialize)]
pub struct FetchRequest {
    pub integration_ids: Vec<i64>,
}

#[derive(Serialize)]
pub struct FetchResponse {
    /// integration id (as a string key) -> decrypted integration, or null when the id doesn't
    /// exist or belongs to another team (indistinguishable on purpose).
    pub integrations: HashMap<String, Option<DecryptedIntegration>>,
}

/// Merge the credential API (which carries `AppState`) onto a stateless base router (health/index).
pub fn merge_api_routes(app: Router, state: AppState) -> Router {
    let api = Router::new()
        .route("/api/v1/credentials/fetch", post(fetch_credentials))
        .with_state(state);
    app.merge(api)
}

async fn fetch_credentials(
    State(state): State<AppState>,
    caller: AuthedCaller,
    Json(req): Json<FetchRequest>,
) -> Response {
    if req.integration_ids.len() > state.max_batch_size {
        return (
            StatusCode::BAD_REQUEST,
            Json(json!({ "error": format!("too many integration_ids (max {})", state.max_batch_size) })),
        )
            .into_response();
    }

    let request_id = Uuid::new_v4().to_string();

    let outcome = match state
        .service
        .get_for_team(caller.team_id, &req.integration_ids)
        .await
    {
        Ok(outcome) => outcome,
        Err(e) => {
            tracing::error!(error = %e, request_id, "integration fetch failed");
            inc(
                metrics_consts::FETCH_TOTAL,
                &[
                    ("caller".to_string(), caller.caller.clone()),
                    ("result".to_string(), "error".to_string()),
                ],
                1,
            );
            return (
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(json!({ "error": "internal error" })),
            )
                .into_response();
        }
    };

    // Preserve request order/keys: every requested id appears in the response, resolved or null.
    let mut integrations: HashMap<String, Option<DecryptedIntegration>> =
        HashMap::with_capacity(req.integration_ids.len());
    let mut resolved_ids: Vec<i64> = Vec::new();
    for id in &req.integration_ids {
        match outcome.resolved.get(id) {
            Some(v) => {
                resolved_ids.push(*id);
                integrations.insert(id.to_string(), Some((**v).clone()));
            }
            None => {
                integrations.insert(id.to_string(), None);
            }
        }
    }

    audit::emit(&AuditEvent {
        caller: &caller.caller,
        team_id: caller.team_id,
        requested: &req.integration_ids,
        resolved: &resolved_ids,
        cache_hits: outcome.cache_hits,
        db_loaded: outcome.db_loaded,
        request_id: &request_id,
    });

    inc(
        metrics_consts::FETCH_TOTAL,
        &[
            ("caller".to_string(), caller.caller.clone()),
            ("result".to_string(), "ok".to_string()),
        ],
        1,
    );

    (StatusCode::OK, Json(FetchResponse { integrations })).into_response()
}
