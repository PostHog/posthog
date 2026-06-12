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
    team::team_models::Team,
};
use axum::{
    debug_handler,
    extract::{Path, Query, State},
    http::{HeaderMap, Method, StatusCode},
    response::{IntoResponse, Json, Response},
};
use serde::Deserialize;
use serde_json::Value;
use std::sync::Arc;
use tracing::warn;

/// Query params. SDKs pass `?token=phc_...` (the project key) and call this with `@current`
/// as the URL segment; the token resolves the project, matching Django.
#[derive(Deserialize)]
pub struct RemoteConfigQuery {
    token: Option<String>,
}

enum AuthOutcome {
    Authorized {
        should_decrypt: bool,
        /// The team the request is scoped to, used for the throttle allowlist bypass.
        team_id: i32,
        /// Per-credential throttle key. `Some(pak_id)` for personal API keys (which Django
        /// throttles), `None` for secret keys (which Django does not throttle).
        rate_limit_key: Option<String>,
    },
    /// Credential is valid but not for this project (Django: 403 team mismatch).
    Forbidden,
    /// No team with the scoped id (Django: `view.team` raises -> 404 "Project not found").
    ProjectNotFound,
}

#[debug_handler]
pub async fn remote_config(
    State(state): State<AppState>,
    Path((project_segment, key)): Path<(String, String)>,
    Query(params): Query<RemoteConfigQuery>,
    method: Method,
    headers: HeaderMap,
) -> Result<Response, FlagError> {
    // Match the sibling endpoint: Django serves HEAD as 200 and answers OPTIONS with an
    // Allow header (DRF maps HEAD to the GET action), so probes and the phase 2 diff don't
    // diverge on method.
    if method != Method::GET {
        return Ok(flag_definitions::handle_non_get_method(&method));
    }

    // Resolve the target project. SDKs call this with `@current` as the URL segment plus a
    // `?token=phc_...` project key; Django resolves the project from the token first, so the
    // token wins when present (and `@current` never needs interpreting). Without a token, a
    // numeric segment is the project id; `@current` and other non-numeric values 404 — the
    // `@current`-without-token path resolves the caller's current team, which is not an SDK
    // call and is not ported (Django's `int()` ValueError also maps non-numeric to 404).
    let (scope_team_id, scope_project_id, resolved_team): (i32, i64, Option<Team>) =
        if let Some(token) = params.token.as_deref() {
            match state.flag_service().verify_token_and_get_team(token).await {
                Ok(team) => {
                    // The cached team payload carries project_id; only fall back to a query
                    // for cache entries written before the field existed.
                    let project_id = match team.project_id {
                        Some(pid) => pid,
                        None => project_id_for_team(&state, team.id).await?,
                    };
                    // Hold onto the team so the personal-key path below doesn't re-query it.
                    (team.id, project_id, Some(team))
                }
                // Django raises AuthenticationFailed for an invalid `?token=`.
                Err(_) => return Ok(StatusCode::UNAUTHORIZED.into_response()),
            }
        } else {
            match project_segment.parse::<i32>() {
                Ok(id) => (id, i64::from(id), None),
                Err(_) => return Ok(StatusCode::NOT_FOUND.into_response()),
            }
        };

    let (should_decrypt, team_id, rate_limit_key) =
        match authenticate(&state, scope_team_id, resolved_team.as_ref(), &headers).await? {
            AuthOutcome::Authorized {
                should_decrypt,
                team_id,
                rate_limit_key,
            } => (should_decrypt, team_id, rate_limit_key),
            AuthOutcome::Forbidden => return Ok(StatusCode::FORBIDDEN.into_response()),
            AuthOutcome::ProjectNotFound => return Ok(StatusCode::NOT_FOUND.into_response()),
        };

    // Throttle mirroring Django's RemoteConfigThrottle: only personal-API-key requests are
    // throttled, bucketed per credential, and allowlisted teams bypass. Secret-key requests
    // carry no `rate_limit_key` and are not throttled. Runs before the DB lookup to shield PG.
    if let Some(cred_key) = rate_limit_key {
        if !state
            .config
            .rate_limiting_allow_list_teams
            .0
            .contains(&team_id)
        {
            state.remote_config_limiter.check_rate_limit(cred_key)?;
        }
    }

    // Flag lookup scoped to the project. 404 if missing or not a remote config flag.
    let Some((filters, is_remote_configuration, has_encrypted_payloads)) =
        load_remote_config_flag(&state, scope_project_id, &key).await?
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

/// Authenticates and resolves the decrypt gate against the already-resolved scope team,
/// mirroring Django.
///
/// - `phs_` (team/project secret): the token's team must be `scope_team_id`. On mismatch,
///   403 if that team exists, 404 if it does not (Django's `view.team` raises). Never decrypts.
/// - `phx_` (personal API key): validated (scopes + access) against `Team(scope_team_id)`.
///   Decrypts.
async fn authenticate(
    state: &AppState,
    scope_team_id: i32,
    resolved_team: Option<&Team>,
    headers: &HeaderMap,
) -> Result<AuthOutcome, FlagError> {
    if let Some(token) = auth::extract_team_secret_token(headers) {
        let (team_id, _api_token, _is_project_secret) =
            auth::validate_secret_api_token(state, &token).await?;
        // Django: authenticated_team.id == view.team.id.
        if team_id != scope_team_id {
            // Mismatch resolves like Django: 403 when a real (different) team owns the
            // project, 404 when no such team exists (Django's `view.team` raises). The
            // lookup only runs on this error path, never on the matching hot path.
            return match state.flag_service().get_team_by_id(scope_team_id).await {
                Ok(_) => Ok(AuthOutcome::Forbidden),
                Err(FlagError::SecretApiTokenInvalid) | Err(FlagError::RowNotFound) => {
                    Ok(AuthOutcome::ProjectNotFound)
                }
                Err(e) => Err(e),
            };
        }
        // Secret-key requests are not throttled by Django's RemoteConfigThrottle.
        return Ok(AuthOutcome::Authorized {
            should_decrypt: false,
            team_id,
            rate_limit_key: None,
        });
    }

    if let Some(key) = auth::extract_personal_api_key(headers)? {
        // view.team = Team(scope_team_id); missing -> 404. Reuse the team the handler already
        // fetched on the `?token=` path; only query on the numeric-segment path where none was.
        let fetched;
        let team: &Team = match resolved_team {
            Some(t) => t,
            None => {
                fetched = match state.flag_service().get_team_by_id(scope_team_id).await {
                    Ok(team) => team,
                    Err(FlagError::SecretApiTokenInvalid) | Err(FlagError::RowNotFound) => {
                        return Ok(AuthOutcome::ProjectNotFound)
                    }
                    Err(e) => return Err(e),
                };
                &fetched
            }
        };
        let pak_id =
            auth::validate_personal_api_key_with_scopes_for_team(state, &key, team).await?;
        // Per-credential throttle bucket (Django keys on the hashed bearer token; the stable
        // pak id is an equivalent per-credential identifier for our in-memory limiter).
        let rate_limit_key = Some(pak_id.clone());

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
            team_id: scope_team_id,
            rate_limit_key,
        });
    }

    Err(FlagError::NoAuthenticationProvided)
}

/// Resolves a team's `project_id` (falling back to its own id if unset). Used on the
/// `?token=` path, where the flag is scoped to the token team's project, not its team id.
async fn project_id_for_team(state: &AppState, team_id: i32) -> Result<i64, FlagError> {
    let client: common_database::PostgresReader = state.database_pools.non_persons_reader.clone();
    let mut conn = get_connection_with_metrics(&client, "non_persons_reader", "remote_config")
        .await
        .map_err(|e| {
            warn!("remote_config: failed to get db connection: {e}");
            FlagError::DatabaseUnavailable
        })?;
    let row: (i64,) =
        sqlx::query_as("SELECT COALESCE(project_id, id)::bigint FROM posthog_team WHERE id = $1")
            .bind(team_id)
            .fetch_one(&mut *conn)
            .await
            .map_err(|e| {
                warn!("remote_config project lookup failed: {e}");
                FlagError::DatabaseUnavailable
            })?;
    Ok(row.0)
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
