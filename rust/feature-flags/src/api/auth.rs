use crate::{
    api::errors::FlagError, database::get_connection_with_metrics,
    metrics::consts::LEGACY_TOKEN_MIRROR_SHADOW_COUNTER, router::State as AppState,
    team::team_models::Team,
};
use axum::http::HeaderMap;
use common_database::PostgresReader;
use metrics::counter;
use serde::{Deserialize, Serialize};
use std::time::Duration;
use tokio::sync::Semaphore;
use tracing::{debug, warn};

/// Token prefix constants
const SECRET_TOKEN_PREFIX: &str = "phs_";

/// Cache key prefix for per-token auth entries (must match Python TOKEN_CACHE_PREFIX)
pub const TOKEN_CACHE_PREFIX: &str = "posthog:auth_token:";

/// Scopes that grant feature flag access (must match SQL WHERE clause in validate_personal_api_key_with_scopes_for_team)
const SCOPE_WILDCARD: &str = "*";
const SCOPE_FEATURE_FLAG_READ: &str = "feature_flag:read";
const SCOPE_FEATURE_FLAG_WRITE: &str = "feature_flag:write";

/// Cached token metadata written to Redis
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type")]
pub enum TokenAuthData {
    #[serde(rename = "secret")]
    Secret {
        team_id: i32,
        /// The team's public API token, used to look up team metadata from
        /// HyperCache when `?token=` is omitted. `#[serde(default)]` ensures
        /// backwards compatibility with cached entries that predate this field.
        #[serde(default)]
        api_token: Option<String>,
    },
    #[serde(rename = "personal")]
    Personal {
        user_id: i32,
        key_id: Option<String>,
        org_ids: Vec<String>,
        scoped_teams: Option<Vec<i32>>,
        scoped_orgs: Option<Vec<String>>,
        scopes: Option<Vec<String>>,
        /// The user's `current_team_id`, used only by remote_config's `@current` resolution.
        /// `#[serde(default)]` keeps backwards compatibility with cached entries that predate
        /// this field (they resolve as `None` until the entry refreshes).
        #[serde(default)]
        current_team_id: Option<i32>,
        /// When the key stops working; `None` means it never expires. Checked on every use,
        /// including cache hits, so an entry cannot outlive the key. `#[serde(default)]` keeps
        /// backwards compatibility with cached entries that predate this field.
        #[serde(default)]
        expires_at: Option<chrono::DateTime<chrono::Utc>>,
    },
    #[serde(rename = "project_secret")]
    ProjectSecret {
        team_id: i32,
        key_id: String,
        scopes: Option<Vec<String>>,
        /// See `Secret::api_token` for rationale.
        #[serde(default)]
        api_token: Option<String>,
    },
}

/// A validated `phs_` bearer token. `project_secret_key_id` is set only when the token was a
/// project secret API key; the team-level secret token has no key row to stamp usage on.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SecretTokenAuth {
    pub team_id: i32,
    pub api_token: Option<String>,
    pub project_secret_key_id: Option<String>,
}

impl SecretTokenAuth {
    pub fn method_label(&self) -> &'static str {
        if self.project_secret_key_id.is_some() {
            "project_secret_api_key"
        } else {
            "secret_api_key"
        }
    }
}

/// Extracts bearer token from Authorization header
pub fn extract_bearer_token(headers: &HeaderMap) -> Option<String> {
    headers
        .get("authorization")
        .and_then(|h| h.to_str().ok())
        .and_then(|s| s.strip_prefix("Bearer "))
        .map(|t| t.trim().to_string())
        .filter(|t| !t.is_empty())
}

/// Extracts team secret API token from Authorization header only
/// Only tokens starting with SECRET_TOKEN_PREFIX are considered secret API tokens
pub fn extract_team_secret_token(headers: &HeaderMap) -> Option<String> {
    extract_bearer_token(headers).filter(|token| token.starts_with(SECRET_TOKEN_PREFIX))
}

/// Extracts personal API key from Authorization header
pub fn extract_personal_api_key(headers: &HeaderMap) -> Result<Option<String>, FlagError> {
    // If it's not a team token (doesn't start with SECRET_TOKEN_PREFIX), treat as personal API key
    Ok(extract_bearer_token(headers).filter(|token| !token.starts_with(SECRET_TOKEN_PREFIX)))
}

/// Validates a phs_-prefixed token and checks it belongs to the expected team.
/// Same as `validate_secret_api_token` but with the team_id cross-check.
pub async fn validate_secret_api_token_for_team(
    state: &AppState,
    token: &str,
    expected_team_id: i32,
) -> Result<SecretTokenAuth, FlagError> {
    let result = validate_secret_api_token(state, token).await?;

    if result.team_id != expected_team_id {
        warn!(
            cached_team_id = result.team_id,
            expected_team_id = expected_team_id,
            "Token belongs to a different team"
        );
        return Err(FlagError::SecretApiTokenInvalid);
    }

    Ok(result)
}

/// Validates a phs_-prefixed token without checking against a specific team.
///
/// Used when the `?token=` query parameter is omitted and the team must be derived
/// from the secret token itself.
///
/// Only works for Secret and ProjectSecret tokens (which are team-scoped).
/// Personal API keys are multi-team and cannot be used to derive a team.
pub async fn validate_secret_api_token(
    state: &AppState,
    token: &str,
) -> Result<SecretTokenAuth, FlagError> {
    let token_hash = hash_token_value(token);
    let pg_reader: PostgresReader = state.database_pools.non_persons_reader.clone();
    let token_owned = token.to_string();
    let hash_for_loader = token_hash.clone();
    let accept_team_secret_tokens = *state.config.accept_team_secret_tokens;
    // The shadow only informs the flip, so it has nothing to compare once legacy is off.
    let mirror_shadow = accept_team_secret_tokens && *state.config.legacy_token_mirror_shadow;

    let result = state
        .auth_token_cache
        .get_or_load(&token_hash, |_key| {
            load_token_from_pg(
                pg_reader,
                &token_owned,
                &hash_for_loader,
                accept_team_secret_tokens,
                mirror_shadow,
            )
        })
        .await?;

    match result.value {
        Some(TokenAuthData::Secret {
            team_id, api_token, ..
        }) => {
            debug!(
                team_id = team_id,
                "Secret API token validated (no token param)"
            );
            Ok(SecretTokenAuth {
                team_id,
                api_token,
                project_secret_key_id: None,
            })
        }
        Some(TokenAuthData::ProjectSecret {
            team_id,
            api_token,
            key_id,
            ..
        }) => {
            debug!(
                team_id = team_id,
                "Project secret API key validated (no token param)"
            );
            Ok(SecretTokenAuth {
                team_id,
                api_token,
                project_secret_key_id: Some(key_id),
            })
        }
        _ => Err(FlagError::SecretApiTokenInvalid),
    }
}

/// Load token auth data from PostgreSQL: posthog_team secret tokens first when
/// `accept_team_secret_tokens` is true (see `Config::accept_team_secret_tokens`), then
/// ProjectSecretAPIKeys.
///
/// Extracted from `validate_secret_api_token_for_team` for testability.
async fn load_token_from_pg(
    pg_reader: PostgresReader,
    plaintext_token: &str,
    hashed_token: &str,
    accept_team_secret_tokens: bool,
    mirror_shadow: bool,
) -> Result<Option<TokenAuthData>, FlagError> {
    use sqlx::Row;

    if accept_team_secret_tokens {
        // Try Team.secret_api_token / secret_api_token_backup first.
        // Only fall through to PSAK on RowNotFound; propagate transient DB errors immediately
        // to avoid doubling DB work during outages.
        match Team::from_pg_by_secret_token(pg_reader.clone(), plaintext_token).await {
            Ok(team) => {
                if mirror_shadow {
                    drop(spawn_mirror_shadow_check(
                        pg_reader.clone(),
                        hashed_token.to_string(),
                        team.id,
                    ));
                }
                return Ok(Some(TokenAuthData::Secret {
                    team_id: team.id,
                    api_token: Some(team.api_token),
                }));
            }
            Err(FlagError::RowNotFound) => { /* token not in posthog_team, try PSAK below */ }
            Err(e) => return Err(e),
        }
    }

    // Try ProjectSecretAPIKey (JOIN with posthog_team to get api_token for HyperCache lookups)
    let mut conn =
        get_connection_with_metrics(&pg_reader, "non_persons_reader", "fetch_project_secret_key")
            .await?;
    let query = format!(
        r#"
        SELECT k.id, k.team_id, k.scopes, t.api_token
        FROM posthog_projectsecretapikey k
        JOIN posthog_team t ON t.id = k.team_id
        WHERE k.secure_value = $1
          AND {PSAK_FLAG_SCOPE_FILTER}
    "#
    );

    match sqlx::query(&query)
        .bind(hashed_token)
        .fetch_optional(&mut *conn)
        .await
        .map_err(FlagError::from)?
    {
        Some(row) => {
            let key_id: String = row.try_get("id")?;
            let team_id: i32 = row.try_get("team_id")?;
            let scopes: Option<Vec<String>> = row.try_get("scopes")?;
            let api_token: String = row.try_get("api_token")?;
            Ok(Some(TokenAuthData::ProjectSecret {
                team_id,
                key_id,
                scopes,
                api_token: Some(api_token),
            }))
        }
        None => {
            warn!(
                checked_posthog_team = accept_team_secret_tokens,
                "phs_ token not found in project secret API key table"
            );
            Ok(None)
        }
    }
}

/// Shared by the real PSAK lookup and the mirror shadow query so the predicates cannot
/// drift. The key table must be aliased as `k`.
const PSAK_FLAG_SCOPE_FILTER: &str = "(
              k.scopes IS NULL
              OR '*' = ANY(k.scopes)
              OR 'feature_flag:read' = ANY(k.scopes)
              OR 'feature_flag:write' = ANY(k.scopes)
          )";

// One in-flight check per pod: the definitions fleet's non_persons_reader pool is tiny,
// and when Redis degrades the loader runs per request. The flip gate reads the rates of
// missing and team_mismatch results, so skipping excess checks (counted as "skipped")
// loses nothing.
static MIRROR_SHADOW_PERMITS: Semaphore = Semaphore::const_new(1);

// Bounds only the query, not the pool checkout (acquire_timeout covers that):
// statement_timeout cannot unblock a client whose socket stopped responding.
const MIRROR_SHADOW_TIMEOUT: Duration = Duration::from_secs(5);

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum MirrorShadowResult {
    Match,
    Missing,
    TeamMismatch,
    Revoked,
    Error,
    Timeout,
}

impl MirrorShadowResult {
    const fn as_label(self) -> &'static str {
        match self {
            Self::Match => "match",
            Self::Missing => "missing",
            Self::TeamMismatch => "team_mismatch",
            Self::Revoked => "revoked",
            Self::Error => "error",
            Self::Timeout => "timeout",
        }
    }
}

/// Transitional (#66179): after a successful legacy-token auth, check in the background
/// that the PSAK lookup replacing the legacy branch post-flip resolves this token to the
/// same team. Fire-and-forget: it never delays or fails the auth path, and while the
/// auth cache is healthy it only runs on cache misses, so the extra query is bounded by
/// unique active tokens per cache TTL, not by request volume. Returns the task handle
/// (None when skipped) so tests can await the classification.
fn spawn_mirror_shadow_check(
    pg_reader: PostgresReader,
    hashed_token: String,
    team_id: i32,
) -> Option<tokio::task::JoinHandle<MirrorShadowResult>> {
    let Ok(permit) = MIRROR_SHADOW_PERMITS.try_acquire() else {
        counter!(LEGACY_TOKEN_MIRROR_SHADOW_COUNTER, "result" => "skipped").increment(1);
        return None;
    };
    Some(tokio::spawn(async move {
        let _permit = permit;
        let result = mirror_shadow_result(pg_reader, &hashed_token, team_id).await;
        match result {
            MirrorShadowResult::Match => {}
            // Quiet: leak revocation deleted the mirror row on purpose; do not backfill.
            MirrorShadowResult::Revoked => {}
            // Already logged with the error at the query site.
            MirrorShadowResult::Error | MirrorShadowResult::Timeout => {}
            MirrorShadowResult::Missing => warn!(
                team_id = team_id,
                "Legacy token has no usable PSAK mirror row"
            ),
            MirrorShadowResult::TeamMismatch => warn!(
                team_id = team_id,
                "Legacy token's PSAK mirror row belongs to another team"
            ),
        }
        counter!(LEGACY_TOKEN_MIRROR_SHADOW_COUNTER, "result" => result.as_label()).increment(1);
        result
    }))
}

/// Classify a legacy token's PSAK mirror state. Uses the same scope filter as the real
/// PSAK lookup in `load_token_from_pg`, so `Match` means the post-flip lookup would
/// authenticate this token hash for this team.
async fn mirror_shadow_result(
    pg_reader: PostgresReader,
    hashed_token: &str,
    team_id: i32,
) -> MirrorShadowResult {
    let mut conn = match get_connection_with_metrics(
        &pg_reader,
        "non_persons_reader",
        "legacy_token_mirror_shadow",
    )
    .await
    {
        Ok(conn) => conn,
        Err(e) => {
            warn!(team_id = team_id, error = %e, "Legacy token mirror shadow could not get a connection");
            return MirrorShadowResult::Error;
        }
    };
    let query = format!(
        r#"
        SELECT
            (SELECT k.team_id FROM posthog_projectsecretapikey k
              WHERE k.secure_value = $1 AND {PSAK_FLAG_SCOPE_FILTER}) AS team_id,
            EXISTS (
                SELECT 1 FROM posthog_revokedteamsecrettoken WHERE secure_value = $1
            ) AS revoked
    "#
    );
    match tokio::time::timeout(
        MIRROR_SHADOW_TIMEOUT,
        sqlx::query_as::<_, (Option<i32>, bool)>(&query)
            .bind(hashed_token)
            .fetch_one(&mut *conn),
    )
    .await
    {
        Ok(Ok((Some(row_team_id), _))) if row_team_id == team_id => MirrorShadowResult::Match,
        Ok(Ok((Some(_), _))) => MirrorShadowResult::TeamMismatch,
        Ok(Ok((None, true))) => MirrorShadowResult::Revoked,
        Ok(Ok((None, false))) => MirrorShadowResult::Missing,
        Ok(Err(e)) => {
            warn!(team_id = team_id, error = %e, "Legacy token mirror shadow query failed");
            MirrorShadowResult::Error
        }
        Err(_) => {
            // Return-to-pool pings with no deadline; closing frees the slot instead.
            conn.close_on_drop();
            warn!(
                team_id = team_id,
                "Legacy token mirror shadow query timed out"
            );
            MirrorShadowResult::Timeout
        }
    }
}

/// Load personal API key auth data from PostgreSQL.
///
/// Extracted from `validate_personal_api_key_with_scopes_for_team` for consistency
/// with `load_token_from_pg`.
async fn load_personal_key_from_pg(
    pg_reader: PostgresReader,
    hashed_token: &str,
) -> Result<Option<TokenAuthData>, FlagError> {
    use sqlx::Row;

    let mut conn = pg_reader.get_connection().await.map_err(FlagError::from)?;

    let query = r#"
        SELECT
            pak.id as key_id,
            pak.scopes,
            pak.scoped_teams,
            pak.scoped_organizations,
            pak.expires_at,
            u.id as user_id,
            u.current_team_id,
            ARRAY(
                SELECT om.organization_id::text
                FROM posthog_organizationmembership om
                WHERE om.user_id = u.id
            ) as org_ids
        FROM posthog_personalapikey pak
        INNER JOIN posthog_user u ON pak.user_id = u.id
        WHERE pak.secure_value = $1
          AND u.is_active = true
    "#;

    match sqlx::query(query)
        .bind(hashed_token)
        .fetch_optional(&mut *conn)
        .await
        .map_err(FlagError::from)?
    {
        Some(row) => {
            let key_id: String = row.try_get("key_id")?;
            let user_id: i32 = row.try_get("user_id")?;
            let scoped_teams: Option<Vec<i32>> = row.try_get("scoped_teams")?;
            let scoped_organizations: Option<Vec<String>> = row.try_get("scoped_organizations")?;
            let scopes: Option<Vec<String>> = row.try_get("scopes")?;
            let org_ids: Vec<String> = row.try_get("org_ids")?;
            let current_team_id: Option<i32> = row.try_get("current_team_id")?;
            let expires_at: Option<chrono::DateTime<chrono::Utc>> = row.try_get("expires_at")?;

            Ok(Some(TokenAuthData::Personal {
                user_id,
                key_id: Some(key_id),
                org_ids,
                scoped_teams,
                scoped_orgs: scoped_organizations,
                scopes,
                current_team_id,
                expires_at,
            }))
        }
        None => {
            warn!("Personal API key not found");
            Ok(None)
        }
    }
}

/// Resolves the current team id for a personal API key's user — Django's `user.current_team`,
/// used only by the remote_config endpoint's `@current` project resolution. Goes through the
/// shared `auth_token_cache` (same loader as `validate_personal_api_key_with_scopes_for_team`),
/// so it does no uncached DB work before the request is authenticated and throttled, and the
/// subsequent `authenticate` call reuses the warm cache entry. Returns `Ok(None)` when the key is
/// valid but the user has no current team set (Django: 404), and `Err(PersonalApiKeyInvalid)`
/// (401) when the key is unknown or the user is inactive.
pub async fn current_team_id_for_personal_api_key(
    state: &AppState,
    key: &str,
) -> Result<Option<i32>, FlagError> {
    let sha256_hash = hash_token_value(key);
    let pg_reader: PostgresReader = state.database_pools.non_persons_reader.clone();
    let hash_for_loader = sha256_hash.clone();

    let result = state
        .auth_token_cache
        .get_or_load(&sha256_hash, |_key| async move {
            load_personal_key_from_pg(pg_reader, &hash_for_loader).await
        })
        .await?;

    match &result.value {
        Some(TokenAuthData::Personal {
            current_team_id, ..
        }) => Ok(*current_team_id),
        // Unknown key, inactive user, or a non-personal credential hashing to this value: an
        // invalid credential (-> 401), not a missing project. Matches
        // `validate_personal_api_key_with_scopes_for_team`'s not-found behaviour.
        Some(_) | None => Err(FlagError::PersonalApiKeyInvalid),
    }
}

/// Hash a token value using SHA256
/// Ported from PostHog's `hash_key_value` function in `posthog/models/utils.py`
/// Used by both PersonalAPIKey and ProjectSecretAPIKey
pub(crate) fn hash_token_value(value: &str) -> String {
    use sha2::{Digest, Sha256};

    // No salt — see https://github.com/jazzband/django-rest-knox/issues/188
    let mut hasher = Sha256::new();
    hasher.update(value.as_bytes());
    let result = hasher.finalize();
    format!("sha256${}", hex::encode(result))
}

/// Validates cached personal API key metadata against the team
fn validate_personal_key_metadata(data: &TokenAuthData, team: &Team) -> Result<(), FlagError> {
    match data {
        TokenAuthData::Personal {
            org_ids,
            scoped_teams,
            scoped_orgs,
            scopes,
            expires_at,
            ..
        } => {
            // Same rule as Django's PersonalAPIKey.is_expired: the expiry instant itself is expired
            if expires_at.is_some_and(|expiry| expiry <= chrono::Utc::now()) {
                debug!("Personal API key has expired");
                return Err(FlagError::PersonalApiKeyInvalid);
            }

            // Check scoped_teams restriction
            if let Some(teams) = scoped_teams {
                if !teams.is_empty() && !teams.contains(&team.id) {
                    debug!(
                        team_id = team.id,
                        scoped_teams = ?teams,
                        "Cached personal API key not scoped to this team"
                    );
                    return Err(FlagError::PersonalApiKeyInvalid);
                }
            }

            // Check scopes — return 403 (not 401) when the key is valid but lacks permissions
            if let Some(scope_list) = scopes {
                if scope_list.is_empty() {
                    debug!("Personal API key has an explicit empty scopes list; no access");
                    return Err(FlagError::PersonalApiKeyInsufficientScopes);
                }

                let has_access = scope_list.iter().any(|s| {
                    s == SCOPE_WILDCARD
                        || s == SCOPE_FEATURE_FLAG_READ
                        || s == SCOPE_FEATURE_FLAG_WRITE
                });
                if !has_access {
                    debug!(scopes = ?scope_list, "Personal API key lacks feature flag scopes");
                    return Err(FlagError::PersonalApiKeyInsufficientScopes);
                }
            }

            // Check organization access
            if let Some(team_org_id) = team.organization_id {
                let team_org_str = team_org_id.to_string();

                // Check scoped_organizations restriction
                if let Some(orgs) = scoped_orgs {
                    if !orgs.is_empty() && !orgs.contains(&team_org_str) {
                        debug!(
                            team_organization_id = %team_org_str,
                            scoped_orgs = ?orgs,
                            "Cached personal API key not scoped to this organization"
                        );
                        return Err(FlagError::PersonalApiKeyInvalid);
                    }
                }

                // Check user is a member of the team's organization
                if !org_ids.contains(&team_org_str) {
                    debug!(
                        team_organization_id = %team_org_str,
                        "Cached personal API key user not a member of team's organization"
                    );
                    return Err(FlagError::PersonalApiKeyInvalid);
                }
            }

            Ok(())
        }
        _ => Err(FlagError::PersonalApiKeyInvalid),
    }
}

/// Validates personal API key with feature flag scopes for a specific team
/// Returns the PAK id (String) on success for use in last_used_at tracking
pub async fn validate_personal_api_key_with_scopes_for_team(
    state: &AppState,
    key: &str,
    team: &Team,
) -> Result<String, FlagError> {
    debug!(team_id = team.id, "Validating personal API key for team");

    let sha256_hash = hash_token_value(key);
    let pg_reader: PostgresReader = state.database_pools.non_persons_reader.clone();
    let hash_for_loader = sha256_hash.clone();

    let result = state
        .auth_token_cache
        .get_or_load(&sha256_hash, |_key| async move {
            load_personal_key_from_pg(pg_reader, &hash_for_loader).await
        })
        .await?;

    match &result.value {
        Some(data) => {
            validate_personal_key_metadata(data, team)?;
            let pak_id = match data {
                TokenAuthData::Personal { key_id, .. } => key_id.clone().ok_or_else(|| {
                    warn!("Cached personal API key missing key_id (stale cache entry)");
                    FlagError::PersonalApiKeyInvalid
                })?,
                _ => return Err(FlagError::PersonalApiKeyInvalid),
            };
            debug!(team_id = team.id, "Personal API key validated successfully");
            Ok(pak_id)
        }
        None => Err(FlagError::PersonalApiKeyInvalid),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The mirror shadow check (#66179) must classify a legacy token's PSAK mirror
    /// state the way the post-flip lookup would resolve it: same team with usable
    /// scopes is a match, a row for another team is the cross-team case, and no row
    /// (or a row without flag scopes) means the token dies at the flip. A leak-revoked
    /// hash is its own class: it must not read as a backfill candidate.
    #[rstest::rstest]
    #[case::mirror_row_same_team("same_team", MirrorShadowResult::Match)]
    #[case::mirror_row_other_team("other_team", MirrorShadowResult::TeamMismatch)]
    #[case::mirror_row_without_flag_scopes("wrong_scopes", MirrorShadowResult::Missing)]
    #[case::no_mirror_row("none", MirrorShadowResult::Missing)]
    #[case::leak_revoked("revoked", MirrorShadowResult::Revoked)]
    #[tokio::test]
    async fn test_mirror_shadow_result_classification(
        #[case] row: &str,
        #[case] expected: MirrorShadowResult,
    ) {
        use crate::utils::test_utils::TestContext;

        let context = TestContext::new(None).await;
        let (team, secret_token, _) = context
            .create_team_with_secret_token(None, None, None)
            .await
            .unwrap();
        match row {
            "same_team" => {
                context
                    .create_project_secret_api_key_with_value(
                        team.id,
                        "Migrated legacy secret API key",
                        Some(vec!["feature_flag:read", "support_ticket:read"]),
                        &secret_token,
                    )
                    .await
                    .unwrap();
            }
            "other_team" => {
                let other_team = context.insert_new_team(None).await.unwrap();
                context
                    .create_project_secret_api_key_with_value(
                        other_team.id,
                        "Migrated legacy secret API key",
                        Some(vec!["feature_flag:read"]),
                        &secret_token,
                    )
                    .await
                    .unwrap();
            }
            "wrong_scopes" => {
                context
                    .create_project_secret_api_key_with_value(
                        team.id,
                        "Migrated legacy secret API key",
                        Some(vec!["support_ticket:read"]),
                        &secret_token,
                    )
                    .await
                    .unwrap();
            }
            "none" => {}
            "revoked" => {
                context
                    .create_revoked_team_secret_token(team.id, &secret_token)
                    .await
                    .unwrap();
            }
            _ => unreachable!(),
        }

        let hashed = hash_token_value(&secret_token);
        let result =
            mirror_shadow_result(context.non_persons_reader.clone(), &hashed, team.id).await;
        assert_eq!(result, expected);
    }

    /// Guards the wiring, not the classification: if a refactor stopped the spawned
    /// shadow from running (or from reaching the classifier), the flip gate would read
    /// green by absence of data. The single global permit may be held by a concurrent
    /// test, so acquiring retries briefly.
    #[tokio::test]
    async fn test_spawn_mirror_shadow_check_classifies_in_background() {
        use crate::utils::test_utils::TestContext;

        let context = TestContext::new(None).await;
        let (team, secret_token, _) = context
            .create_team_with_secret_token(None, None, None)
            .await
            .unwrap();
        let hashed = hash_token_value(&secret_token);

        let spawn_with_retry = |hashed: String, team_id: i32| {
            let pg_reader = context.non_persons_reader.clone();
            async move {
                for _ in 0..100 {
                    if let Some(handle) =
                        spawn_mirror_shadow_check(pg_reader.clone(), hashed.clone(), team_id)
                    {
                        return handle;
                    }
                    tokio::time::sleep(Duration::from_millis(20)).await;
                }
                panic!("no mirror shadow permit became available");
            }
        };

        let handle = spawn_with_retry(hashed.clone(), team.id).await;
        assert_eq!(handle.await.unwrap(), MirrorShadowResult::Missing);

        context
            .create_project_secret_api_key_with_value(
                team.id,
                "Migrated legacy secret API key",
                Some(vec!["feature_flag:read"]),
                &secret_token,
            )
            .await
            .unwrap();
        let handle = spawn_with_retry(hashed, team.id).await;
        assert_eq!(handle.await.unwrap(), MirrorShadowResult::Match);
    }

    #[test]
    fn test_extract_team_secret_token_from_header() {
        use axum::http::HeaderMap;

        let mut headers = HeaderMap::new();
        headers.insert("authorization", "Bearer phs_123456789".parse().unwrap());

        let result = extract_team_secret_token(&headers);
        assert_eq!(result, Some("phs_123456789".to_string()));
    }

    #[test]
    fn test_extract_team_secret_token_requires_phs_prefix() {
        use axum::http::HeaderMap;

        let mut headers = HeaderMap::new();
        // Personal API key (phx_*) should not be extracted as secret token
        headers.insert("authorization", "Bearer phx_personal_key".parse().unwrap());

        let result = extract_team_secret_token(&headers);
        assert_eq!(result, None);
    }

    #[test]
    fn test_extract_personal_api_key() {
        use axum::http::HeaderMap;

        let mut headers = HeaderMap::new();
        headers.insert(
            "authorization",
            "Bearer phx_personal_key_123".parse().unwrap(),
        );

        let result = extract_personal_api_key(&headers).unwrap();
        assert_eq!(result, Some("phx_personal_key_123".to_string()));

        // Should not extract team tokens (phs_*)
        headers.insert("authorization", "Bearer phs_team_token".parse().unwrap());
        let result = extract_personal_api_key(&headers).unwrap();
        assert_eq!(result, None);
    }

    #[test]
    fn test_hash_token_value() {
        let result = hash_token_value("test_key_12345");
        assert_eq!(
            result,
            "sha256$45af89b510a3279a817f851de5d3f95b73485d58ec2672a39e52d8aeeb014059"
        );
    }

    #[test]
    fn test_extract_bearer_token() {
        use axum::http::HeaderMap;

        // Test valid bearer token
        let mut headers = HeaderMap::new();
        headers.insert("authorization", "Bearer my_token_123".parse().unwrap());
        let result = extract_bearer_token(&headers);
        assert_eq!(result, Some("my_token_123".to_string()));

        // Test with extra whitespace
        headers.insert("authorization", "Bearer   my_token_456  ".parse().unwrap());
        let result = extract_bearer_token(&headers);
        assert_eq!(result, Some("my_token_456".to_string()));

        // Test missing Bearer prefix
        headers.insert("authorization", "my_token_789".parse().unwrap());
        let result = extract_bearer_token(&headers);
        assert_eq!(result, None);

        // Test empty token
        headers.insert("authorization", "Bearer ".parse().unwrap());
        let result = extract_bearer_token(&headers);
        assert_eq!(result, None);

        // Test no authorization header
        let empty_headers = HeaderMap::new();
        let result = extract_bearer_token(&empty_headers);
        assert_eq!(result, None);
    }

    #[test]
    fn test_token_auth_data_serialization_secret() {
        let data = TokenAuthData::Secret {
            team_id: 42,
            api_token: Some("phc_test123".to_string()),
        };
        let json = serde_json::to_string(&data).unwrap();
        assert!(json.contains("\"type\":\"secret\""));
        assert!(json.contains("\"team_id\":42"));
        assert!(json.contains("\"api_token\":\"phc_test123\""));

        let parsed: TokenAuthData = serde_json::from_str(&json).unwrap();
        match parsed {
            TokenAuthData::Secret { team_id, api_token } => {
                assert_eq!(team_id, 42);
                assert_eq!(api_token, Some("phc_test123".to_string()));
            }
            _ => panic!("Expected Secret variant"),
        }
    }

    #[test]
    fn test_token_auth_data_deserializes_old_secret_without_api_token() {
        // Old cached entries don't have api_token — serde(default) should give None
        let json = r#"{"type":"secret","team_id":42}"#;
        let parsed: TokenAuthData = serde_json::from_str(json).unwrap();
        match parsed {
            TokenAuthData::Secret { team_id, api_token } => {
                assert_eq!(team_id, 42);
                assert_eq!(api_token, None);
            }
            _ => panic!("Expected Secret variant"),
        }
    }

    #[test]
    fn test_token_auth_data_deserializes_old_project_secret_without_api_token() {
        // Old cached entries don't have api_token — serde(default) should give None
        let json = r#"{"type":"project_secret","team_id":99,"key_id":"psak_abc","scopes":["feature_flag:read"]}"#;
        let parsed: TokenAuthData = serde_json::from_str(json).unwrap();
        match parsed {
            TokenAuthData::ProjectSecret {
                team_id, api_token, ..
            } => {
                assert_eq!(team_id, 99);
                assert_eq!(api_token, None);
            }
            _ => panic!("Expected ProjectSecret variant"),
        }
    }

    #[test]
    fn test_token_auth_data_serialization_personal() {
        let data = TokenAuthData::Personal {
            user_id: 7,
            key_id: Some("test-key-id".to_string()),
            org_ids: vec!["uuid-1".to_string()],
            scoped_teams: Some(vec![1, 2]),
            scoped_orgs: None,
            scopes: Some(vec!["feature_flag:read".to_string()]),
            current_team_id: None,
            expires_at: None,
        };
        let json = serde_json::to_string(&data).unwrap();
        assert!(json.contains("\"type\":\"personal\""));

        let parsed: TokenAuthData = serde_json::from_str(&json).unwrap();
        match parsed {
            TokenAuthData::Personal {
                user_id,
                org_ids,
                scoped_teams,
                ..
            } => {
                assert_eq!(user_id, 7);
                assert_eq!(org_ids, vec!["uuid-1"]);
                assert_eq!(scoped_teams, Some(vec![1, 2]));
            }
            _ => panic!("Expected Personal variant"),
        }
    }

    #[test]
    fn test_token_auth_data_serialization_project_secret() {
        let data = TokenAuthData::ProjectSecret {
            team_id: 99,
            key_id: "psak_abc123".to_string(),
            scopes: Some(vec!["feature_flag:read".to_string()]),
            api_token: Some("phc_proj_test".to_string()),
        };
        let json = serde_json::to_string(&data).unwrap();
        assert!(json.contains("\"type\":\"project_secret\""));
        assert!(json.contains("\"team_id\":99"));
        assert!(json.contains("\"key_id\":\"psak_abc123\""));
        assert!(json.contains("\"api_token\":\"phc_proj_test\""));

        let parsed: TokenAuthData = serde_json::from_str(&json).unwrap();
        match parsed {
            TokenAuthData::ProjectSecret {
                team_id,
                key_id,
                scopes,
                api_token,
            } => {
                assert_eq!(team_id, 99);
                assert_eq!(key_id, "psak_abc123");
                assert_eq!(scopes, Some(vec!["feature_flag:read".to_string()]));
                assert_eq!(api_token, Some("phc_proj_test".to_string()));
            }
            _ => panic!("Expected ProjectSecret variant"),
        }
    }

    #[test]
    fn test_token_auth_data_serialization_project_secret_null_scopes() {
        let data = TokenAuthData::ProjectSecret {
            team_id: 1,
            key_id: "key_id".to_string(),
            scopes: None,
            api_token: None,
        };
        let json = serde_json::to_string(&data).unwrap();
        let parsed: TokenAuthData = serde_json::from_str(&json).unwrap();
        match parsed {
            TokenAuthData::ProjectSecret { scopes, .. } => assert_eq!(scopes, None),
            _ => panic!("Expected ProjectSecret variant"),
        }
    }

    #[test]
    fn test_validate_personal_key_metadata_allows_valid_access() {
        let team = Team {
            id: 1,
            organization_id: Some(
                uuid::Uuid::parse_str("550e8400-e29b-41d4-a716-446655440000").unwrap(),
            ),
            ..Default::default()
        };

        let data = TokenAuthData::Personal {
            user_id: 42,
            key_id: None,
            org_ids: vec!["550e8400-e29b-41d4-a716-446655440000".to_string()],
            scoped_teams: Some(vec![1, 2]),
            scoped_orgs: None,
            scopes: Some(vec!["feature_flag:read".to_string()]),
            current_team_id: None,
            expires_at: None,
        };

        assert!(validate_personal_key_metadata(&data, &team).is_ok());
    }

    #[test]
    fn test_validate_personal_key_metadata_rejects_wrong_team() {
        let team = Team {
            id: 99,
            organization_id: Some(
                uuid::Uuid::parse_str("550e8400-e29b-41d4-a716-446655440000").unwrap(),
            ),
            ..Default::default()
        };

        let data = TokenAuthData::Personal {
            user_id: 42,
            key_id: None,
            org_ids: vec!["550e8400-e29b-41d4-a716-446655440000".to_string()],
            scoped_teams: Some(vec![1, 2]),
            scoped_orgs: None,
            scopes: Some(vec!["feature_flag:read".to_string()]),
            current_team_id: None,
            expires_at: None,
        };

        assert!(validate_personal_key_metadata(&data, &team).is_err());
    }

    #[test]
    fn test_validate_personal_key_metadata_rejects_wrong_org() {
        let team = Team {
            id: 1,
            organization_id: Some(
                uuid::Uuid::parse_str("550e8400-e29b-41d4-a716-446655440000").unwrap(),
            ),
            ..Default::default()
        };

        let data = TokenAuthData::Personal {
            user_id: 42,
            key_id: None,
            org_ids: vec!["00000000-0000-0000-0000-000000000000".to_string()],
            scoped_teams: None,
            scoped_orgs: None,
            scopes: None,
            current_team_id: None,
            expires_at: None,
        };

        assert!(validate_personal_key_metadata(&data, &team).is_err());
    }

    /// An expired key must fail even when every other check passes, including from a cached
    /// entry that was written before the key expired.
    #[rstest::rstest]
    #[case::expired_a_minute_ago(Some(chrono::Utc::now() - chrono::Duration::minutes(1)), false)]
    #[case::expires_in_a_day(Some(chrono::Utc::now() + chrono::Duration::days(1)), true)]
    #[case::never_expires(None, true)]
    fn test_validate_personal_key_metadata_checks_expiry(
        #[case] expires_at: Option<chrono::DateTime<chrono::Utc>>,
        #[case] expected_ok: bool,
    ) {
        let team = Team {
            id: 1,
            organization_id: Some(
                uuid::Uuid::parse_str("550e8400-e29b-41d4-a716-446655440000").unwrap(),
            ),
            ..Default::default()
        };

        let data = TokenAuthData::Personal {
            user_id: 42,
            key_id: None,
            org_ids: vec!["550e8400-e29b-41d4-a716-446655440000".to_string()],
            scoped_teams: None,
            scoped_orgs: None,
            scopes: Some(vec!["feature_flag:read".to_string()]),
            current_team_id: None,
            expires_at,
        };

        assert_eq!(
            validate_personal_key_metadata(&data, &team).is_ok(),
            expected_ok
        );
    }

    #[test]
    fn test_validate_personal_key_metadata_allows_unscoped() {
        let team = Team {
            id: 1,
            organization_id: Some(
                uuid::Uuid::parse_str("550e8400-e29b-41d4-a716-446655440000").unwrap(),
            ),
            ..Default::default()
        };

        let data = TokenAuthData::Personal {
            user_id: 42,
            key_id: None,
            org_ids: vec!["550e8400-e29b-41d4-a716-446655440000".to_string()],
            scoped_teams: None,
            scoped_orgs: None,
            scopes: None,
            current_team_id: None,
            expires_at: None,
        };

        assert!(validate_personal_key_metadata(&data, &team).is_ok());
    }

    #[test]
    fn test_validate_personal_key_metadata_allows_wildcard_scope() {
        let team = Team {
            id: 1,
            organization_id: Some(
                uuid::Uuid::parse_str("550e8400-e29b-41d4-a716-446655440000").unwrap(),
            ),
            ..Default::default()
        };

        let data = TokenAuthData::Personal {
            user_id: 42,
            key_id: None,
            org_ids: vec!["550e8400-e29b-41d4-a716-446655440000".to_string()],
            scoped_teams: None,
            scoped_orgs: None,
            scopes: Some(vec!["*".to_string()]),
            current_team_id: None,
            expires_at: None,
        };

        assert!(validate_personal_key_metadata(&data, &team).is_ok());
    }

    #[test]
    fn test_validate_personal_key_metadata_allows_matching_scoped_org() {
        let team = Team {
            id: 1,
            organization_id: Some(
                uuid::Uuid::parse_str("550e8400-e29b-41d4-a716-446655440000").unwrap(),
            ),
            ..Default::default()
        };

        let data = TokenAuthData::Personal {
            user_id: 42,
            key_id: None,
            org_ids: vec!["550e8400-e29b-41d4-a716-446655440000".to_string()],
            scoped_teams: None,
            scoped_orgs: Some(vec!["550e8400-e29b-41d4-a716-446655440000".to_string()]),
            scopes: None,
            current_team_id: None,
            expires_at: None,
        };

        assert!(validate_personal_key_metadata(&data, &team).is_ok());
    }

    #[test]
    fn test_validate_personal_key_metadata_rejects_wrong_scoped_org() {
        let team = Team {
            id: 1,
            organization_id: Some(
                uuid::Uuid::parse_str("550e8400-e29b-41d4-a716-446655440000").unwrap(),
            ),
            ..Default::default()
        };

        let data = TokenAuthData::Personal {
            user_id: 42,
            key_id: None,
            org_ids: vec!["550e8400-e29b-41d4-a716-446655440000".to_string()],
            scoped_teams: None,
            scoped_orgs: Some(vec!["aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee".to_string()]),
            scopes: None,
            current_team_id: None,
            expires_at: None,
        };

        assert!(validate_personal_key_metadata(&data, &team).is_err());
    }

    #[test]
    fn test_validate_personal_key_metadata_rejects_insufficient_scopes() {
        let team = Team {
            id: 1,
            organization_id: Some(
                uuid::Uuid::parse_str("550e8400-e29b-41d4-a716-446655440000").unwrap(),
            ),
            ..Default::default()
        };

        let data = TokenAuthData::Personal {
            user_id: 42,
            key_id: None,
            org_ids: vec!["550e8400-e29b-41d4-a716-446655440000".to_string()],
            scoped_teams: None,
            scoped_orgs: None,
            scopes: Some(vec!["session_recording:read".to_string()]),
            current_team_id: None,
            expires_at: None,
        };

        assert!(validate_personal_key_metadata(&data, &team).is_err());
    }

    #[test]
    fn test_validate_personal_key_metadata_rejects_secret_variant() {
        let team = Team {
            id: 1,
            organization_id: Some(
                uuid::Uuid::parse_str("550e8400-e29b-41d4-a716-446655440000").unwrap(),
            ),
            ..Default::default()
        };

        let data = TokenAuthData::Secret {
            team_id: 1,
            api_token: None,
        };

        assert!(validate_personal_key_metadata(&data, &team).is_err());
    }

    #[test]
    fn test_validate_personal_key_metadata_rejects_project_secret_variant() {
        let team = Team {
            id: 1,
            organization_id: Some(
                uuid::Uuid::parse_str("550e8400-e29b-41d4-a716-446655440000").unwrap(),
            ),
            ..Default::default()
        };

        let data = TokenAuthData::ProjectSecret {
            team_id: 1,
            key_id: "psak_abc123".to_string(),
            scopes: Some(vec!["feature_flag:read".to_string()]),
            api_token: None,
        };

        assert!(validate_personal_key_metadata(&data, &team).is_err());
    }

    #[test]
    fn test_validate_personal_key_metadata_allows_write_scope() {
        let team = Team {
            id: 1,
            organization_id: Some(
                uuid::Uuid::parse_str("550e8400-e29b-41d4-a716-446655440000").unwrap(),
            ),
            ..Default::default()
        };

        let data = TokenAuthData::Personal {
            user_id: 42,
            key_id: None,
            org_ids: vec!["550e8400-e29b-41d4-a716-446655440000".to_string()],
            scoped_teams: None,
            scoped_orgs: None,
            scopes: Some(vec!["feature_flag:write".to_string()]),
            current_team_id: None,
            expires_at: None,
        };

        assert!(validate_personal_key_metadata(&data, &team).is_ok());
    }

    #[test]
    fn test_validate_personal_key_metadata_allows_mixed_scopes_with_valid_one() {
        let team = Team {
            id: 1,
            organization_id: Some(
                uuid::Uuid::parse_str("550e8400-e29b-41d4-a716-446655440000").unwrap(),
            ),
            ..Default::default()
        };

        let data = TokenAuthData::Personal {
            user_id: 42,
            key_id: None,
            org_ids: vec!["550e8400-e29b-41d4-a716-446655440000".to_string()],
            scoped_teams: None,
            scoped_orgs: None,
            scopes: Some(vec![
                "session_recording:read".to_string(),
                "feature_flag:read".to_string(),
            ]),
            current_team_id: None,
            expires_at: None,
        };

        assert!(validate_personal_key_metadata(&data, &team).is_ok());
    }

    #[test]
    fn test_validate_personal_key_metadata_empty_scoped_vecs_treated_as_unscoped() {
        // Some(vec![]) means "no restriction" for scoped_teams and scoped_orgs —
        // same semantics as None. The SQL can return either representation.
        let team = Team {
            id: 99,
            organization_id: Some(
                uuid::Uuid::parse_str("550e8400-e29b-41d4-a716-446655440000").unwrap(),
            ),
            ..Default::default()
        };

        let data = TokenAuthData::Personal {
            user_id: 42,
            key_id: None,
            org_ids: vec!["550e8400-e29b-41d4-a716-446655440000".to_string()],
            scoped_teams: Some(vec![]), // empty = no restriction, team 99 should pass
            scoped_orgs: Some(vec![]),  // empty = no restriction
            scopes: None,               // None = no restriction
            current_team_id: None,
            expires_at: None,
        };

        assert!(validate_personal_key_metadata(&data, &team).is_ok());
    }

    #[test]
    fn test_validate_personal_key_metadata_empty_scopes_rejected() {
        // Django enforces allow_empty=False on scopes and the auth-time check
        // rejects empty lists. Mirror that here for defense in depth.
        let team = Team {
            id: 1,
            organization_id: Some(
                uuid::Uuid::parse_str("550e8400-e29b-41d4-a716-446655440000").unwrap(),
            ),
            ..Default::default()
        };

        let data = TokenAuthData::Personal {
            user_id: 42,
            key_id: None,
            org_ids: vec!["550e8400-e29b-41d4-a716-446655440000".to_string()],
            scoped_teams: None,
            scoped_orgs: None,
            scopes: Some(vec![]),
            current_team_id: None,
            expires_at: None,
        };

        assert!(matches!(
            validate_personal_key_metadata(&data, &team),
            Err(FlagError::PersonalApiKeyInsufficientScopes)
        ));
    }

    #[test]
    fn test_validate_personal_key_metadata_allows_no_org_team() {
        let team = Team {
            id: 1,
            organization_id: None,
            ..Default::default()
        };

        let data = TokenAuthData::Personal {
            user_id: 42,
            key_id: None,
            org_ids: vec![],
            scoped_teams: None,
            scoped_orgs: None,
            scopes: None,
            current_team_id: None,
            expires_at: None,
        };

        assert!(validate_personal_key_metadata(&data, &team).is_ok());
    }

    #[tokio::test]
    async fn test_load_token_from_pg_propagates_db_errors_instead_of_falling_through() {
        use async_trait::async_trait;
        use common_database::{Client, CustomDatabaseError, PoolStats};
        use sqlx::pool::PoolConnection;
        use sqlx::Postgres;
        use std::sync::atomic::{AtomicUsize, Ordering};
        use std::sync::Arc;

        /// A mock database client that always fails with a connection error
        /// and tracks how many times get_connection was called.
        struct FailingClient {
            call_count: AtomicUsize,
        }

        impl FailingClient {
            fn new() -> Self {
                Self {
                    call_count: AtomicUsize::new(0),
                }
            }

            fn calls(&self) -> usize {
                self.call_count.load(Ordering::SeqCst)
            }
        }

        #[async_trait]
        impl Client for FailingClient {
            async fn get_connection(
                &self,
            ) -> Result<PoolConnection<Postgres>, CustomDatabaseError> {
                self.call_count.fetch_add(1, Ordering::SeqCst);
                Err(CustomDatabaseError::Other(sqlx::Error::PoolClosed))
            }

            fn get_pool_stats(&self) -> Option<PoolStats> {
                None
            }
        }

        let client = Arc::new(FailingClient::new());
        let pg_reader: common_database::PostgresReader = client.clone();

        let result =
            load_token_from_pg(pg_reader, "phs_test_token", "sha256$fake", true, false).await;

        // The first query (Team::from_pg_by_secret_token) should fail with DatabaseUnavailable.
        // The function should propagate that error immediately, NOT fall through to the
        // ProjectSecretAPIKey query. If it falls through, get_connection would be called
        // a second time for the PSAK query.
        assert!(result.is_err(), "Expected error to be propagated");
        assert!(
            matches!(result, Err(FlagError::DatabaseUnavailable)),
            "Expected DatabaseUnavailable, got: {:?}",
            result
        );
        assert_eq!(
            client.calls(),
            1,
            "get_connection should be called exactly once — the DB error from the \
             Team secret token lookup should be propagated, not swallowed"
        );
    }
}
