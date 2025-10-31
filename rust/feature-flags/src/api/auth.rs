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

/// Hash a personal API key value using legacy PBKDF2 mode
/// Ported from PostHog's `hash_key_value` function in `posthog/models/personal_api_key.py`
fn hash_legacy_pbkdf2_key(value: &str, iterations: u32) -> String {
    use pbkdf2::pbkdf2_hmac;
    use sha2::Sha256;

    let salt = b"posthog_personal_api_key";

    // Compute PBKDF2-HMAC-SHA256 hash
    let mut hash = [0u8; 32]; // 256 bits / 8 = 32 bytes
    pbkdf2_hmac::<Sha256>(value.as_bytes(), salt, iterations, &mut hash);

    // Encode hash in base64 and format like Django: pbkdf2_sha256$iterations$salt$hash
    let hash_b64 = base64::Engine::encode(&base64::engine::general_purpose::STANDARD, hash);
    format!(
        "pbkdf2_sha256${}${}${}",
        iterations,
        String::from_utf8_lossy(salt),
        hash_b64
    )
}

/// Hash a personal API key value using the specified mode
/// Ported from PostHog's `hash_key_value` function in `posthog/models/personal_api_key.py`
fn hash_personal_api_key(value: &str, mode: &str, iterations: Option<u32>) -> String {
    use sha2::{Digest, Sha256};

    match mode {
        // Current simple hashing mode
        "sha256" => {
            if iterations.is_some() {
                panic!("Iterations must not be provided when using simple hashing mode");
            }

            // Inspiration on why no salt:
            // https://github.com/jazzband/django-rest-knox/issues/188
            let mut hasher = Sha256::new();
            hasher.update(value.as_bytes());
            let result = hasher.finalize();
            format!("sha256${}", hex::encode(result))
        }
        // Legacy PBKDF2 mode
        "pbkdf2" => {
            let iterations = iterations.expect("Iterations must be provided for pbkdf2 mode");
            hash_legacy_pbkdf2_key(value, iterations)
        }
        _ => panic!("Unsupported hashing mode: {mode}"),
    }
}

/// Validates personal API key with feature flag scopes for a specific team
/// Returns Ok(()) if the personal API key has access to the specified team
pub async fn validate_personal_api_key_with_scopes_for_team(
    state: &AppState,
    key: &str,
    team: &Team,
) -> Result<(), FlagError> {
    use sqlx::Row;

    debug!(team_id = team.id, "Validating personal API key for team");

    // Try all hashing modes to find the key
    let modes_to_try = vec![
        ("sha256", None),
        ("pbkdf2", Some(260000)),
        ("pbkdf2", Some(390000)),
    ];

    let pg_reader: PostgresReader = state.database_pools.non_persons_reader.clone();
    let mut conn = pg_reader.get_connection().await?;

    for (mode, iterations) in modes_to_try {
        let secure_value = hash_personal_api_key(key, mode, iterations);

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

        let row_result = sqlx::query(query)
            .bind(&secure_value)
            .fetch_optional(&mut *conn)
            .await?;

        if let Some(row) = row_result {
            // Validate scoped_teams restriction
            let scoped_teams: Option<Vec<i32>> = row.try_get("scoped_teams").ok();
            if let Some(ref teams) = scoped_teams {
                if !teams.is_empty() && !teams.contains(&team.id) {
                    warn!(
                        team_id = team.id,
                        scoped_teams = ?teams,
                        "Personal API key does not have access to this team"
                    );
                    return Err(FlagError::PersonalApiKeyInvalid(
                        "Authorization header".to_string(),
                    ));
                }
            }

            // Validate organization access (MANDATORY for teams with organization_id)
            // Personal API keys can only access teams in organizations where the user is a member,
            // unless explicitly scoped to specific organizations via scoped_organizations
            let user_id: i32 = row.get("user_id");
            let user_organization_id: uuid::Uuid = row.get("user_organization_id");
            let scoped_organizations: Option<Vec<String>> =
                row.try_get("scoped_organizations").ok();

            // Handle teams with or without organization_id
            if let Some(team_organization_id) = team.organization_id {
                let team_organization_id_str = team_organization_id.to_string();

                // Check organization access:
                // - If scoped_organizations has entries: team's org must be in the list
                // - Otherwise (NULL or empty): user must be a member of the team's org
                let has_org_access = match scoped_organizations.as_ref() {
                    Some(orgs) if !orgs.is_empty() => orgs.contains(&team_organization_id_str),
                    _ => {
                        // Check if user is a member of the team's organization
                        let is_member: bool = sqlx::query_scalar(
                            "SELECT EXISTS(SELECT 1 FROM posthog_organizationmembership WHERE user_id = $1 AND organization_id = $2)"
                        )
                        .bind(user_id)
                        .bind(team_organization_id)
                        .fetch_one(&mut *conn)
                        .await?;
                        is_member
                    }
                };

                if !has_org_access {
                    warn!(
                        user_organization_id = %user_organization_id,
                        team_organization_id = %team_organization_id_str,
                        scoped_organizations = ?scoped_organizations,
                        "Personal API key does not have access to this organization"
                    );
                    return Err(FlagError::PersonalApiKeyInvalid(
                        "Authorization header".to_string(),
                    ));
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

            return Ok(());
        }
    }

    warn!("Personal API key not found or doesn't have required scopes");
    Err(FlagError::PersonalApiKeyInvalid(
        "Authorization header".to_string(),
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    use rstest::rstest;

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
    #[rstest]
    #[case(
        "sha256",
        None,
        "sha256$45af89b510a3279a817f851de5d3f95b73485d58ec2672a39e52d8aeeb014059"
    )]
    #[case(
        "pbkdf2",
        Some(1),
        "pbkdf2_sha256$1$posthog_personal_api_key$vzzA4fHFTiUipScUeDJ4+NjuXwAWWu2AFRbk/JUs6Ck="
    )]
    #[case("pbkdf2", Some(260000), "pbkdf2_sha256$260000$posthog_personal_api_key$eeRy21dbVoEzYND0NVLfjXxgNeO67SeBRrwQr6bbhK4=")]
    fn test_hash_personal_api_key(
        #[case] algorithm: &str,
        #[case] iterations: Option<u32>,
        #[case] expected_hash: &str,
    ) {
        let result = hash_personal_api_key("test_key_12345", algorithm, iterations);
        assert_eq!(result, expected_hash);
    }

    #[test]
    #[should_panic(expected = "Iterations must be provided for pbkdf2 mode")]
    fn test_hash_personal_api_key_pbkdf2_requires_iterations() {
        hash_personal_api_key("test_key", "pbkdf2", None);
    }

    #[test]
    #[should_panic(expected = "Iterations must not be provided when using simple hashing mode")]
    fn test_hash_personal_api_key_sha256_forbids_iterations() {
        hash_personal_api_key("test_key", "sha256", Some(100));
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
