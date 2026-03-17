use crate::{api::errors::FlagError, router::State as AppState, team::team_models::Team};
use axum::http::HeaderMap;
use common_database::PostgresReader;
use tracing::{debug, warn};

/// Token prefix constants
const SECRET_TOKEN_PREFIX: &str = "phs_";

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

/// Validates team secret API token and returns Team object
pub async fn validate_secret_api_token(state: &AppState, token: &str) -> Result<Team, FlagError> {
    debug!("Validating team token");

    let pg_reader: PostgresReader = state.database_pools.non_persons_reader.clone();

    // Secret tokens are validated directly against PostgreSQL
    // (they are not cached in HyperCache team_metadata)
    Team::from_pg_by_secret_token(pg_reader, token)
        .await
        .map_err(|_| FlagError::TokenValidationError)
}

/// Validates that a secret API token matches the specified team
/// Returns Ok(()) if the token belongs to the team, Err otherwise
pub async fn validate_secret_api_token_for_team(
    state: &AppState,
    token: &str,
    expected_team_id: i32,
) -> Result<(), FlagError> {
    debug!(
        expected_team_id = expected_team_id,
        "Validating secret API token for team"
    );

    // Fetch the team using the secret token
    let pg_reader: PostgresReader = state.database_pools.non_persons_reader.clone();
    let team = Team::from_pg_by_secret_token(pg_reader, token)
        .await
        .map_err(|e| {
            warn!(error = %e, "Secret API token not found");
            FlagError::SecretApiTokenInvalid
        })?;

    // Verify the team ID matches
    if team.id != expected_team_id {
        warn!(
            secret_token_team_id = team.id,
            expected_team_id = expected_team_id,
            "Secret API token belongs to a different team"
        );
        return Err(FlagError::SecretApiTokenInvalid);
    }

    debug!(team_id = team.id, "Secret API token validated successfully");

    Ok(())
}

/// Validates a project secret API key (from posthog_projectsecretapikey table) for a specific team.
/// Returns the key ID on success.
pub async fn validate_project_secret_api_key_for_team(
    state: &AppState,
    token: &str,
    expected_team_id: i32,
) -> Result<String, FlagError> {
    use sqlx::Row;

    debug!(
        expected_team_id = expected_team_id,
        "Validating project secret API key for team"
    );

    let secure_value = hash_key_value(token);

    let pg_reader: PostgresReader = state.database_pools.non_persons_reader.clone();
    let mut conn = pg_reader.get_connection().await?;

    let query = r#"
        SELECT id
        FROM posthog_projectsecretapikey
        WHERE secure_value = $1
          AND team_id = $2
          AND (
              scopes IS NULL
              OR scopes = '{*}'
              OR 'feature_flag:read' = ANY(scopes)
              OR 'feature_flag:write' = ANY(scopes)
          )
    "#;

    let row = sqlx::query(query)
        .bind(&secure_value)
        .bind(expected_team_id)
        .fetch_optional(&mut *conn)
        .await?
        .ok_or_else(|| {
            warn!("Project secret API key not found, wrong team, or missing required scopes");
            FlagError::SecretApiTokenInvalid
        })?;

    let key_id: String = row.get("id");

    debug!(
        key_id = %key_id,
        team_id = expected_team_id,
        "Project secret API key validated successfully"
    );

    Ok(key_id)
}

/// Hash an API key value using SHA256
/// Ported from PostHog's `hash_key_value` function in `posthog/models/personal_api_key.py`
/// Used by both PersonalAPIKey and ProjectSecretAPIKey
pub(crate) fn hash_key_value(value: &str) -> String {
    use sha2::{Digest, Sha256};

    // No salt — see https://github.com/jazzband/django-rest-knox/issues/188
    let mut hasher = Sha256::new();
    hasher.update(value.as_bytes());
    let result = hasher.finalize();
    format!("sha256${}", hex::encode(result))
}

/// Validates personal API key with feature flag scopes for a specific team
/// Returns the PAK id (String) on success for use in last_used_at tracking
pub async fn validate_personal_api_key_with_scopes_for_team(
    state: &AppState,
    key: &str,
    team: &Team,
) -> Result<String, FlagError> {
    use sqlx::Row;

    debug!(team_id = team.id, "Validating personal API key for team");

    let secure_value = hash_key_value(key);

    let pg_reader: PostgresReader = state.database_pools.non_persons_reader.clone();
    let mut conn = pg_reader.get_connection().await?;

    // Query for PersonalAPIKey with scope validation
    // The key must:
    // 1. Have an active user
    // 2. Have either no scopes (full access) OR have feature_flag:read or feature_flag:write scopes
    let query = r#"
        SELECT
            pak.id as key_id,
            pak.scopes,
            pak.scoped_teams,
            pak.scoped_organizations,
            u.id as user_id,
            u.is_active as user_is_active,
            u.current_organization_id as user_organization_id
        FROM posthog_personalapikey pak
        INNER JOIN posthog_user u ON pak.user_id = u.id
        WHERE pak.secure_value = $1
          AND u.is_active = true
          AND (
              pak.scopes IS NULL
              OR pak.scopes = '{*}'
              OR 'feature_flag:read' = ANY(pak.scopes)
              OR 'feature_flag:write' = ANY(pak.scopes)
          )
    "#;

    let row = sqlx::query(query)
        .bind(&secure_value)
        .fetch_optional(&mut *conn)
        .await?
        .ok_or_else(|| {
            warn!("Personal API key not found or doesn't have required scopes");
            FlagError::PersonalApiKeyInvalid
        })?;

    let pak_id: String = row.get("key_id");

    // Validate scoped_teams restriction
    let scoped_teams: Option<Vec<i32>> = row.try_get("scoped_teams").ok();
    if let Some(ref teams) = scoped_teams {
        if !teams.is_empty() && !teams.contains(&team.id) {
            warn!(
                team_id = team.id,
                scoped_teams = ?teams,
                "Personal API key does not have access to this team"
            );
            return Err(FlagError::PersonalApiKeyInvalid);
        }
    }

    // Validate organization access (MANDATORY for teams with organization_id)
    // Personal API keys can only access teams in organizations where the user is a current member
    let user_id: i32 = row.get("user_id");
    let user_organization_id: uuid::Uuid = row.get("user_organization_id");
    let scoped_organizations: Option<Vec<String>> = row.try_get("scoped_organizations").ok();

    // Handle teams with or without organization_id
    if let Some(team_organization_id) = team.organization_id {
        let team_organization_id_str = team_organization_id.to_string();

        // Check organization access:
        // 1. If scoped_organizations has entries, the team's org must be in the list
        // 2. The user must always be a current member of the team's organization
        if let Some(orgs) = scoped_organizations.as_ref() {
            if !orgs.is_empty() && !orgs.contains(&team_organization_id_str) {
                warn!(
                    user_id = user_id,
                    team_organization_id = %team_organization_id_str,
                    scoped_organizations = ?orgs,
                    "Personal API key scope does not include this organization"
                );
                return Err(FlagError::PersonalApiKeyInvalid);
            }
        }

        let has_org_access: bool = sqlx::query_scalar(
            "SELECT EXISTS(SELECT 1 FROM posthog_organizationmembership WHERE user_id = $1 AND organization_id = $2)"
        )
        .bind(user_id)
        .bind(team_organization_id)
        .fetch_one(&mut *conn)
        .await?;

        if !has_org_access {
            warn!(
                user_organization_id = %user_organization_id,
                team_organization_id = %team_organization_id_str,
                scoped_organizations = ?scoped_organizations,
                "Personal API key does not have access to this organization"
            );
            return Err(FlagError::PersonalApiKeyInvalid);
        }
    } else {
        // Legacy team without organization_id - skip organization validation
        debug!(
            team_id = team.id,
            user_organization_id = %user_organization_id,
            "Team has no organization_id, skipping organization validation (legacy team)"
        );
    }

    debug!(
        user_id = user_id,
        team_id = team.id,
        user_organization_id = %user_organization_id,
        team_organization_id = ?team.organization_id,
        scoped_teams = ?scoped_teams,
        scoped_organizations = ?scoped_organizations,
        "Personal API key validated successfully"
    );

    Ok(pak_id)
}

#[cfg(test)]
mod tests {
    use super::*;

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

    // Ported from PostHog's `test_hash_key_values` function in `posthog/api/test/test_personal_api_keys.py`
    #[test]
    fn test_hash_key_value() {
        let result = hash_key_value("test_key_12345");
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
}
