//! `GET /api/projects/{project_id}/feature_flags/{key}/remote_config`
//!
//! Port of Django's `FeatureFlagViewSet.remote_config`. Returns a remote-config flag's
//! payload, decrypting encrypted payloads **only** for personal-API-key callers
//! (project-secret callers get the redacted marker), matching Django exactly.
//!
//! Auth/scoping mirrors Django's KLUDGE: `project_id` from the URL is used as a team id
//! for the credential check, and the flag is looked up by `team.project_id == project_id`.
//! Session-cookie auth is intentionally not ported (not an SDK path), same as
//! `flag_definitions`.

use crate::{
    api::{auth, errors::FlagError},
    database::get_connection_with_metrics,
    flags::{flag_payload_decryptor::REDACTED_PAYLOAD_VALUE, flag_service::FlagService},
    router::State as AppState,
};
use axum::{
    debug_handler,
    extract::{Path, State},
    http::{HeaderMap, Method, StatusCode},
    response::{IntoResponse, Json, Response},
};
use serde_json::Value;
use tracing::warn;

enum AuthOutcome {
    Authorized {
        should_decrypt: bool,
    },
    /// Credential is valid but not for this project (Django: 403 team mismatch).
    Forbidden,
    /// No team with id == project_id (Django: `view.team` raises -> 404 "Project not found").
    ProjectNotFound,
}

#[debug_handler]
pub async fn remote_config(
    State(state): State<AppState>,
    Path((project_id, key)): Path<(i64, String)>,
    method: Method,
    headers: HeaderMap,
) -> Result<Response, FlagError> {
    if method != Method::GET {
        return Ok(StatusCode::METHOD_NOT_ALLOWED.into_response());
    }

    let should_decrypt = match authenticate(&state, project_id, &headers).await? {
        AuthOutcome::Authorized { should_decrypt } => should_decrypt,
        AuthOutcome::Forbidden => return Ok(StatusCode::FORBIDDEN.into_response()),
        AuthOutcome::ProjectNotFound => return Ok(StatusCode::NOT_FOUND.into_response()),
    };

    // Flag lookup scoped to the project. 404 if missing or not a remote config flag.
    let Some((filters, is_remote_configuration, has_encrypted_payloads)) =
        load_remote_config_flag(&state, project_id, &key).await?
    else {
        return Ok(StatusCode::NOT_FOUND.into_response());
    };
    if is_remote_configuration != Some(true) {
        return Ok(StatusCode::NOT_FOUND.into_response());
    }

    // Django returns `filters["payloads"]["true"] or None` (falsy -> null).
    let raw = filters
        .get("payloads")
        .and_then(|p| p.get("true"))
        .filter(|v| !is_falsy(v))
        .cloned();

    if has_encrypted_payloads != Some(true) {
        return Ok(Json(raw.unwrap_or(Value::Null)).into_response());
    }

    // Encrypted: personal-key callers get plaintext, everyone else the redacted marker.
    let body = if should_decrypt {
        match raw {
            Some(Value::String(token)) => {
                let Some(decryptor) = state.flag_payload_decryptor.as_ref() else {
                    return Err(FlagError::Internal(
                        "no FLAGS_SECRET_KEYS configured; cannot decrypt remote config payload"
                            .to_string(),
                    ));
                };
                match decryptor.decrypt(&token) {
                    Ok(plaintext) => Value::String(plaintext),
                    Err(e) => {
                        warn!("remote_config payload decrypt failed: {e}");
                        return Err(FlagError::Internal(
                            "failed to decrypt remote config payload".to_string(),
                        ));
                    }
                }
            }
            _ => Value::Null,
        }
    } else {
        Value::String(REDACTED_PAYLOAD_VALUE.to_string())
    };

    Ok(Json(body).into_response())
}

/// Mirrors Python truthiness for `payloads.get("true") or None`: absent, JSON null,
/// and empty string are treated as no payload.
fn is_falsy(v: &Value) -> bool {
    match v {
        Value::Null => true,
        Value::String(s) => s.is_empty(),
        _ => false,
    }
}

fn flag_service(state: &AppState) -> FlagService {
    FlagService::new(
        state.redis_client.clone(),
        state.database_pools.non_persons_reader.clone(),
        state.team_hypercache_reader.clone(),
        state.flags_hypercache_reader.clone(),
        state.flag_definitions_cache.clone(),
        state.team_negative_cache.clone(),
        *state.config.skip_pg_team_fallback,
    )
}

/// Authenticates and resolves the decrypt gate, mirroring Django.
///
/// - `phs_` (team/project secret): the token's team must be `project_id`, else 403.
///   Never decrypts.
/// - `phx_` (personal API key): validated (scopes + access) against the team whose id
///   is `project_id`. Decrypts.
async fn authenticate(
    state: &AppState,
    project_id: i64,
    headers: &HeaderMap,
) -> Result<AuthOutcome, FlagError> {
    if let Some(token) = auth::extract_team_secret_token(headers) {
        let (team_id, _api_token, _is_project_secret) =
            auth::validate_secret_api_token(state, &token).await?;
        // Django: authenticated_team.id == view.team.id, where view.team = Team(id=project_id).
        if i64::from(team_id) != project_id {
            return Ok(AuthOutcome::Forbidden);
        }
        return Ok(AuthOutcome::Authorized {
            should_decrypt: false,
        });
    }

    if let Some(key) = auth::extract_personal_api_key(headers)? {
        let team_id: i32 = match i32::try_from(project_id) {
            Ok(id) => id,
            Err(_) => return Ok(AuthOutcome::ProjectNotFound),
        };
        // view.team = Team(id=project_id); missing -> 404.
        let team = match flag_service(state).get_team_by_id(team_id).await {
            Ok(team) => team,
            Err(FlagError::SecretApiTokenInvalid) | Err(FlagError::RowNotFound) => {
                return Ok(AuthOutcome::ProjectNotFound)
            }
            Err(e) => return Err(e),
        };
        auth::validate_personal_api_key_with_scopes_for_team(state, &key, &team).await?;
        return Ok(AuthOutcome::Authorized {
            should_decrypt: true,
        });
    }

    Err(FlagError::NoAuthenticationProvided)
}

/// Loads `(filters, is_remote_configuration, has_encrypted_payloads)` for a flag matched
/// by numeric id (if `key` is all digits) or key, scoped to `team.project_id == project_id`.
/// Uses its own query — not the flag-list path, which excludes encrypted RC flags.
async fn load_remote_config_flag(
    state: &AppState,
    project_id: i64,
    key: &str,
) -> Result<Option<(Value, Option<bool>, Option<bool>)>, FlagError> {
    let client: common_database::PostgresReader = state.database_pools.non_persons_reader.clone();
    let mut conn = get_connection_with_metrics(&client, "non_persons_reader", "remote_config")
        .await
        .map_err(|e| {
            warn!("remote_config: failed to get db connection: {e}");
            FlagError::DatabaseUnavailable
        })?;

    // Treat the segment as a flag id only if it is all digits AND fits in i64. An
    // oversized all-digits segment can't match any real flag id, so it's a 404 — and
    // parsing it must not panic on user-controlled input.
    let parsed_id: Option<i64> = if !key.is_empty() && key.bytes().all(|b| b.is_ascii_digit()) {
        match key.parse::<i64>() {
            Ok(id) => Some(id),
            Err(_) => return Ok(None),
        }
    } else {
        None
    };

    let result = if let Some(id) = parsed_id {
        sqlx::query_as::<_, (Value, Option<bool>, Option<bool>)>(
            "SELECT f.filters, f.is_remote_configuration, f.has_encrypted_payloads \
             FROM posthog_featureflag f JOIN posthog_team t ON f.team_id = t.id \
             WHERE t.project_id = $1 AND f.deleted = false AND f.id = $2 LIMIT 1",
        )
        .bind(project_id)
        .bind(id)
        .fetch_optional(&mut *conn)
        .await
    } else {
        sqlx::query_as::<_, (Value, Option<bool>, Option<bool>)>(
            "SELECT f.filters, f.is_remote_configuration, f.has_encrypted_payloads \
             FROM posthog_featureflag f JOIN posthog_team t ON f.team_id = t.id \
             WHERE t.project_id = $1 AND f.deleted = false AND f.key = $2 LIMIT 1",
        )
        .bind(project_id)
        .bind(key)
        .fetch_optional(&mut *conn)
        .await
    };

    result.map_err(|e| {
        warn!("remote_config flag query failed: {e}");
        FlagError::DatabaseUnavailable
    })
}
