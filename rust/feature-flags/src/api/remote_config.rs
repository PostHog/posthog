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
    metrics::consts::REMOTE_CONFIG_AUTH_COUNTER,
    router::State as AppState,
    team::team_models::Team,
};
use axum::{
    debug_handler,
    extract::{Path, Query, State},
    http::{HeaderMap, Method, StatusCode},
    response::{IntoResponse, Json, Response},
};
use common_metrics::inc;
use serde::Deserialize;
use serde_json::Value;
use tracing::warn;

/// Query params. SDKs pass `?token=phc_...` (the project key) and call this with `@current`
/// as the URL segment; the token resolves the project, matching Django. `api_key` is Django's
/// accepted alias for `token` (see `get_token`).
#[derive(Deserialize)]
pub struct RemoteConfigQuery {
    token: Option<String>,
    api_key: Option<String>,
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
    // Non-GET methods are handled before auth, matching the sibling endpoint: HEAD -> 200 and
    // unsupported methods -> 405 with an Allow header. A CORS *preflight* OPTIONS (one carrying
    // Access-Control-Request-Method) is answered upstream by the permissive CORS layer with 200; a
    // bare OPTIONS falls through to here and `handle_non_get_method` returns 204. HEAD diverges from
    // Django, which maps HEAD to the GET action and runs the full pipeline -- an unauthenticated
    // HEAD is 401 there, 200 here -- but no SDK sends either method.
    if method != Method::GET {
        return Ok(flag_definitions::handle_non_get_method(&method));
    }

    // Resolve the effective `?token=` (Django's `get_token`: an empty value is absent, and
    // `?api_key=` is an alias). SDKs call this with `@current` as the URL segment plus a
    // `?token=phc_...` project key; Django resolves the project from the token first, so the token
    // wins when present (and `@current` never needs interpreting). Without a token, a numeric
    // segment is the project id, and `@current` resolves to the bearer credential's project (see
    // `resolve_current_team`); any other non-numeric segment 404s (Django's `int()` ValueError).
    let token_param = params
        .token
        .as_deref()
        .filter(|t| !t.is_empty())
        .or_else(|| params.api_key.as_deref().filter(|t| !t.is_empty()));

    // Resolve only what auth needs here: the team id, and (on the `?token=` path) the resolved
    // team. The project id is needed solely for the flag lookup, so it is computed after auth and
    // the throttle — no DB read happens before an unauthenticated caller is rejected.
    // `verify_token_and_get_team` is cache-backed, so the `?token=` path does no uncached DB work
    // at this point either, and `resolve_current_team` goes through the shared auth-token cache so
    // the bearer-only `@current` path doesn't either.
    let (scope_team_id, resolved_team): (i32, Option<Team>) = if let Some(token) = token_param {
        match state.flag_service().verify_token_and_get_team(token).await {
            // Keep the team so the personal-key auth path and the project lookup below don't
            // re-query it. Django raises AuthenticationFailed for an invalid `?token=`.
            Ok(team) => (team.id, Some(team)),
            Err(_) => return Ok(StatusCode::UNAUTHORIZED.into_response()),
        }
    } else if project_segment == "@current" {
        // `@current` without a `?token=`: resolve the project from the bearer credential,
        // mirroring Django (`current_team = team_from_request or user.current_team`). Server
        // SDKs fetch remote config exactly this way — a `phs_`/`phx_` bearer, `@current`, no
        // query token — so this must resolve, not 404. `Ok(None)` is a valid credential with no
        // current team (Django: 404 "Project not found"); a missing credential surfaces as 401.
        match resolve_current_team(&state, &headers).await? {
            Some(team) => (team.id, Some(team)),
            None => return Ok(StatusCode::NOT_FOUND.into_response()),
        }
    } else {
        match project_segment.parse::<i32>() {
            Ok(id) => (id, None),
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

    // Resolve the project to scope the flag lookup, now that the caller is authenticated and past
    // the throttle (deferred so no DB read precedes an unauthenticated rejection). On the
    // `?token=` path the cached team usually carries project_id; only entries predating that field
    // hit the DB, and a missing row means the team was deleted from Postgres but is still cached
    // -> 401 (as Django resolves the token against PG), not a 5xx. On the numeric path the segment
    // is itself the project id.
    let scope_project_id: i64 = match &resolved_team {
        Some(team) => match team.project_id {
            Some(pid) => pid,
            None => match project_id_for_team(&state, team.id).await? {
                Some(pid) => pid,
                None => return Ok(StatusCode::UNAUTHORIZED.into_response()),
            },
        },
        None => i64::from(scope_team_id),
    };

    // Flag lookup scoped to the project. 404 if missing or not a remote config flag (the query
    // filters on `is_remote_configuration`).
    let Some((filters, has_encrypted_payloads)) =
        load_remote_config_flag(&state, scope_project_id, &key).await?
    else {
        return Ok(StatusCode::NOT_FOUND.into_response());
    };

    let stored = filters.get("payloads").and_then(|p| p.get("true"));

    // Resolve the payload, mirroring Django's `Response(payloads["true"] or None)`: the stored
    // value (unencrypted), the decrypted plaintext (personal key), or the redacted marker (secret
    // key on an encrypted flag).
    //
    // Deliberate divergence on malformed rows: an encrypted flag missing the "true" entry makes
    // Django 500 (both credential paths index `decrypted_payloads["true"]` -> KeyError); a
    // non-string stored value makes the decrypt path feed `str(value)` to Fernet and 500 on
    // InvalidToken. Both are shapes the serializer shouldn't allow. We return gracefully instead
    // -- a missing payload is an empty body on either credential, and the redact path only marks a
    // payload that actually exists -- so phase 2 reads these rare rows as a known diff, not a bug.
    let payload: Option<Value> = if has_encrypted_payloads != Some(true) {
        stored.cloned()
    } else if should_decrypt {
        resolve_decrypted_payload(&state, stored)?
    } else {
        stored.map(|_| Value::String(REDACTED_PAYLOAD_VALUE.to_string()))
    };

    // Django applies `or None` to the final value and renders None as an empty body, not
    // the JSON literal `null`. Apply the falsy check after decryption so an empty decrypted
    // string nulls out too.
    match payload.filter(|v| !is_falsy(v)) {
        Some(v) => Ok(Json(v).into_response()),
        None => Ok(empty_ok_no_content_type()),
    }
}

/// Decrypts the stored ciphertext on the personal-key path. Returns `None` when there is no
/// stored value or it is not a string (Django 500s on those malformed rows; we render an empty
/// body instead). Errors (500) on a decrypt failure or a missing decryptor.
fn resolve_decrypted_payload(
    state: &AppState,
    stored: Option<&Value>,
) -> Result<Option<Value>, FlagError> {
    let Some(Value::String(token)) = stored else {
        return Ok(None);
    };
    let Some(decryptor) = state.flag_payload_decryptor.as_ref() else {
        return Err(FlagError::Internal(
            "no FLAGS_SECRET_KEYS configured; cannot decrypt remote config payload".to_string(),
        ));
    };
    decryptor
        .decrypt(token)
        .map(|plaintext| Some(Value::String(plaintext)))
        .map_err(|e| {
            warn!("remote_config payload decrypt failed: {e}");
            FlagError::Internal("failed to decrypt remote config payload".to_string())
        })
}

/// 200 with an empty body and no Content-Type (NOT a JSON `null`), matching DRF's `Response(None)`:
/// the renderer emits no bytes and DRF then deletes the Content-Type header.
fn empty_ok_no_content_type() -> Response {
    StatusCode::OK.into_response()
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
        let (team_id, _api_token, is_project_secret) =
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
        // Mirror the sibling's per-method auth counter; the secret-vs-personal split matters here
        // because it decides redact-vs-decrypt, so the mix is worth watching during phase 2/3.
        inc(
            REMOTE_CONFIG_AUTH_COUNTER,
            &[(
                "method".to_string(),
                if is_project_secret {
                    "project_secret_api_key".to_string()
                } else {
                    "secret_api_key".to_string()
                },
            )],
            1,
        );
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
        inc(
            REMOTE_CONFIG_AUTH_COUNTER,
            &[("method".to_string(), "personal_api_key".to_string())],
            1,
        );
        // Per-credential throttle bucket (Django keys on the hashed bearer token; the stable
        // pak id is an equivalent per-credential identifier for our in-memory limiter).
        let rate_limit_key = Some(pak_id.clone());

        // Track PAK usage so a key used only for remote config doesn't look dormant and get
        // rotated as unused. Shared with flag_definitions via the State helper.
        state.record_pak_last_used(pak_id).await;

        return Ok(AuthOutcome::Authorized {
            should_decrypt: true,
            team_id: scope_team_id,
            rate_limit_key,
        });
    }

    Err(FlagError::NoAuthenticationProvided)
}

/// Resolves the project scope for an `@current` request that has no `?token=`, from the bearer
/// credential — mirroring Django's `current_team = team_from_request or user.current_team`: a
/// team/project secret token (`phs_`) resolves its own team; a personal API key (`phx_`) resolves
/// its user's current team. `Ok(None)` means the credential is valid but has no current team
/// (Django: 404 "Project not found"); an absent or invalid credential surfaces as 401 via the
/// propagated error. The resolved team is re-validated by `authenticate`, so this only establishes scope.
async fn resolve_current_team(
    state: &AppState,
    headers: &HeaderMap,
) -> Result<Option<Team>, FlagError> {
    if let Some(token) = auth::extract_team_secret_token(headers) {
        let (team_id, _api_token, _is_project_secret) =
            auth::validate_secret_api_token(state, &token).await?;
        return Ok(Some(state.flag_service().get_team_by_id(team_id).await?));
    }
    if let Some(key) = auth::extract_personal_api_key(headers)? {
        return match auth::current_team_id_for_personal_api_key(state, &key).await? {
            Some(team_id) => Ok(Some(state.flag_service().get_team_by_id(team_id).await?)),
            None => Ok(None),
        };
    }
    Err(FlagError::NoAuthenticationProvided)
}

/// Resolves a team's `project_id`. Used on the `?token=` path only for cache entries that predate
/// the cached `project_id`, where the flag is scoped to the token team's project, not its team id.
/// Returns `None` when no such team exists (stale cache: team deleted from Postgres). `project_id`
/// is non-null (validated constraint), matching the flag-lookup JOINs that compare it directly.
async fn project_id_for_team(state: &AppState, team_id: i32) -> Result<Option<i64>, FlagError> {
    let client: common_database::PostgresReader = state.database_pools.non_persons_reader.clone();
    let mut conn = get_connection_with_metrics(&client, "non_persons_reader", "remote_config")
        .await
        .map_err(|e| {
            warn!("remote_config: failed to get db connection: {e}");
            FlagError::DatabaseUnavailable
        })?;
    let row: Option<(i64,)> =
        sqlx::query_as("SELECT project_id::bigint FROM posthog_team WHERE id = $1")
            .bind(team_id)
            .fetch_optional(&mut *conn)
            .await
            .map_err(|e| {
                warn!("remote_config project lookup failed: {e}");
                FlagError::DatabaseUnavailable
            })?;
    Ok(row.map(|r| r.0))
}

/// Loads `(filters, has_encrypted_payloads)` for a remote-config flag matched by numeric id (if
/// `key` is all digits) or key, scoped to `team.project_id == project_id`. The query filters on
/// `is_remote_configuration IS TRUE`, so a non-remote-config flag returns `None` and the caller
/// 404s. Uses its own query — not the flag-list path, which excludes encrypted RC flags.
async fn load_remote_config_flag(
    state: &AppState,
    project_id: i64,
    key: &str,
) -> Result<Option<(Value, Option<bool>)>, FlagError> {
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
        sqlx::query_as::<_, (Value, Option<bool>)>(
            "SELECT f.filters, f.has_encrypted_payloads \
             FROM posthog_featureflag f JOIN posthog_team t ON f.team_id = t.id \
             WHERE t.project_id = $1 AND f.deleted = false AND f.is_remote_configuration IS TRUE \
             AND f.id = $2 LIMIT 1",
        )
        .bind(project_id)
        .bind(id)
        .fetch_optional(&mut *conn)
        .await
    } else {
        sqlx::query_as::<_, (Value, Option<bool>)>(
            "SELECT f.filters, f.has_encrypted_payloads \
             FROM posthog_featureflag f JOIN posthog_team t ON f.team_id = t.id \
             WHERE t.project_id = $1 AND f.deleted = false AND f.is_remote_configuration IS TRUE \
             AND f.key = $2 LIMIT 1",
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

#[cfg(test)]
mod tests {
    use super::is_falsy;
    use serde_json::json;

    #[test]
    fn is_falsy_matches_python_truthiness() {
        // Django's `payloads["true"] or None` nulls out every falsy JSON value.
        assert!(is_falsy(&json!(null)));
        assert!(is_falsy(&json!(false)));
        assert!(is_falsy(&json!(0)));
        assert!(is_falsy(&json!(0.0)));
        assert!(is_falsy(&json!("")));
        assert!(is_falsy(&json!([])));
        assert!(is_falsy(&json!({})));
        // Truthy values pass through.
        assert!(!is_falsy(&json!(true)));
        assert!(!is_falsy(&json!(1)));
        assert!(!is_falsy(&json!("x")));
        assert!(!is_falsy(&json!([1])));
        assert!(!is_falsy(&json!({"k": "v"})));
    }
}
