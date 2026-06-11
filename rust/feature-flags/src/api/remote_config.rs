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
//!
//! Not ported, consistent with `flag_definitions`/`local_evaluation` (so "matches Django"
//! does not extend to these): per-flag access control (advanced RBAC) is not enforced.
//! Personal-key callers are checked for scope and team/org membership only, not role-based
//! feature flag access, even though this endpoint can return decrypted payloads. OAuth
//! access tokens are also not accepted — any non-`phs_` bearer goes through personal-key
//! validation and gets 401; only `phs_` and `phx_` credentials work.

use crate::{
    api::{auth, errors::FlagError, flag_definitions},
    database::get_connection_with_metrics,
    flags::flag_payload_decryptor::REDACTED_PAYLOAD_VALUE,
    router::State as AppState,
};
use axum::{
    debug_handler,
    extract::{Path, State},
    http::{HeaderMap, Method, StatusCode},
    response::{IntoResponse, Json, Response},
};
use serde_json::Value;
use std::sync::Arc;
use tracing::warn;

enum AuthOutcome {
    Authorized {
        should_decrypt: bool,
        /// The team the request is scoped to (== project_id), used as the throttle key.
        team_id: i32,
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
    // Match the sibling endpoint: Django serves HEAD as 200 and answers OPTIONS with an
    // Allow header (DRF maps HEAD to the GET action), so probes and the phase 2 diff don't
    // diverge on method.
    if method != Method::GET {
        return Ok(flag_definitions::handle_non_get_method(&method));
    }

    let (should_decrypt, team_id) = match authenticate(&state, project_id, &headers).await? {
        AuthOutcome::Authorized {
            should_decrypt,
            team_id,
        } => (should_decrypt, team_id),
        AuthOutcome::Forbidden => return Ok(StatusCode::FORBIDDEN.into_response()),
        AuthOutcome::ProjectNotFound => return Ok(StatusCode::NOT_FOUND.into_response()),
    };

    // Per-team throttle (mirrors Django's RemoteConfigThrottle). After auth so only
    // authenticated callers count; before the DB lookup so it shields Postgres.
    state.remote_config_limiter.check_rate_limit(team_id)?;

    // Flag lookup scoped to the project. 404 if missing or not a remote config flag.
    let Some((filters, is_remote_configuration, has_encrypted_payloads)) =
        load_remote_config_flag(&state, project_id, &key).await?
    else {
        return Ok(StatusCode::NOT_FOUND.into_response());
    };
    if is_remote_configuration != Some(true) {
        return Ok(StatusCode::NOT_FOUND.into_response());
    }

    let stored = filters.get("payloads").and_then(|p| p.get("true"));

    // Resolve the payload, mirroring Django's `Response(payloads["true"] or None)`:
    // the stored value (unencrypted), the decrypted plaintext (personal key), or the
    // redacted marker (secret key on an encrypted flag).
    //
    // Deliberate divergence on malformed rows: when an encrypted flag is missing the
    // "true" entry, Django raises KeyError and 500s; with a non-string stored value it
    // feeds `str(value)` to Fernet and 500s on InvalidToken. Both are shapes the
    // serializer shouldn't allow. We return gracefully (no payload -> empty body) rather
    // than reproduce those 500s, so phase 2 will show these rare rows as a known diff.
    let payload: Option<Value> = if has_encrypted_payloads != Some(true) {
        stored.cloned()
    } else if should_decrypt {
        match stored {
            Some(Value::String(token)) => {
                let Some(decryptor) = state.flag_payload_decryptor.as_ref() else {
                    return Err(FlagError::Internal(
                        "no FLAGS_SECRET_KEYS configured; cannot decrypt remote config payload"
                            .to_string(),
                    ));
                };
                match decryptor.decrypt(token) {
                    Ok(plaintext) => Some(Value::String(plaintext)),
                    Err(e) => {
                        warn!("remote_config payload decrypt failed: {e}");
                        return Err(FlagError::Internal(
                            "failed to decrypt remote config payload".to_string(),
                        ));
                    }
                }
            }
            _ => None,
        }
    } else {
        Some(Value::String(REDACTED_PAYLOAD_VALUE.to_string()))
    };

    // Django applies `or None` to the final value and renders None as an empty body, not
    // the JSON literal `null`. Apply the falsy check after decryption so an empty decrypted
    // string nulls out too.
    match payload.filter(|v| !is_falsy(v)) {
        Some(v) => Ok(Json(v).into_response()),
        None => Ok(empty_json_ok()),
    }
}

/// 200 with an empty body and a JSON content type, matching DRF's `Response(None)`.
fn empty_json_ok() -> Response {
    (
        StatusCode::OK,
        [("content-type", "application/json")],
        axum::body::Body::empty(),
    )
        .into_response()
}

/// Mirrors Python truthiness for `payloads.get("true") or None`. In practice the payload
/// is always a JSON-encoded string, but cover every falsy JSON value so the behaviour
/// matches Python exactly: null, false, zero, and empty string/array/object.
fn is_falsy(v: &Value) -> bool {
    match v {
        Value::Null => true,
        Value::Bool(b) => !b,
        Value::Number(n) => n.as_f64() == Some(0.0),
        Value::String(s) => s.is_empty(),
        Value::Array(a) => a.is_empty(),
        Value::Object(o) => o.is_empty(),
    }
}

/// Authenticates and resolves the decrypt gate, mirroring Django.
///
/// - `phs_` (team/project secret): the token's team must be `project_id`. On mismatch,
///   403 if another team owns the project, 404 if no such project exists. Never decrypts.
/// - `phx_` (personal API key): validated (scopes + access) against the team whose id
///   is `project_id`. Decrypts.
async fn authenticate(
    state: &AppState,
    project_id: i64,
    headers: &HeaderMap,
) -> Result<AuthOutcome, FlagError> {
    // Team ids are i32, so a project_id outside that range can't name any team. Treat it
    // as 404 up front, the same for every auth method (Django resolves a missing project
    // to 404 regardless of credential).
    let project_id: i32 = match i32::try_from(project_id) {
        Ok(id) => id,
        Err(_) => return Ok(AuthOutcome::ProjectNotFound),
    };

    if let Some(token) = auth::extract_team_secret_token(headers) {
        let (team_id, _api_token, _is_project_secret) =
            auth::validate_secret_api_token(state, &token).await?;
        // Django: authenticated_team.id == view.team.id, where view.team = Team(id=project_id).
        if team_id != project_id {
            // Mismatch resolves like Django: 403 when a real (different) team owns the
            // project, 404 when no such team exists (Django's `view.team` raises). The
            // lookup only runs on this error path, never on the matching hot path.
            return match state.flag_service().get_team_by_id(project_id).await {
                Ok(_) => Ok(AuthOutcome::Forbidden),
                Err(FlagError::SecretApiTokenInvalid) | Err(FlagError::RowNotFound) => {
                    Ok(AuthOutcome::ProjectNotFound)
                }
                Err(e) => Err(e),
            };
        }
        return Ok(AuthOutcome::Authorized {
            should_decrypt: false,
            team_id,
        });
    }

    if let Some(key) = auth::extract_personal_api_key(headers)? {
        // view.team = Team(id=project_id); missing -> 404.
        let team = match state.flag_service().get_team_by_id(project_id).await {
            Ok(team) => team,
            Err(FlagError::SecretApiTokenInvalid) | Err(FlagError::RowNotFound) => {
                return Ok(AuthOutcome::ProjectNotFound)
            }
            Err(e) => return Err(e),
        };
        let pak_id =
            auth::validate_personal_api_key_with_scopes_for_team(state, &key, &team).await?;

        // Track PAK usage like flag_definitions does, so a key used only for remote config
        // doesn't look dormant and get rotated as unused. Advisory: shared Redis (not the
        // flags cache), and the DB write only fires when the debounce key is newly set.
        if !*state.config.skip_writes {
            let redis = state.redis_client.clone();
            let pg_writer: Arc<dyn common_database::Client + Send + Sync> =
                state.database_pools.non_persons_writer.clone();
            drop(super::pak_usage::record_pak_last_used(redis, pg_writer, pak_id).await);
        }

        return Ok(AuthOutcome::Authorized {
            should_decrypt: true,
            team_id: project_id,
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
