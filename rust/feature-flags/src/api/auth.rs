use crate::{api::errors::FlagError, router::State as AppState, team::team_models::Team};
use axum::http::HeaderMap;
use common_database::PostgresReader;
use serde::{Deserialize, Serialize};
use tracing::{debug, warn};

/// Token prefix constants
const SECRET_TOKEN_PREFIX: &str = "phs_";

/// Cache key prefix for per-token auth entries (must match Python TOKEN_CACHE_PREFIX)
pub const TOKEN_CACHE_PREFIX: &str = "posthog:auth_token:";

/// 30-day TTL for cache entries. Rust is the sole writer; Python only reads and deletes.
pub const TOKEN_CACHE_TTL_SECONDS: u64 = 30 * 24 * 60 * 60;

/// Scopes that grant feature flag access (must match SQL WHERE clause in validate_personal_api_key_with_scopes_for_team)
const SCOPE_WILDCARD: &str = "*";
const SCOPE_FEATURE_FLAG_READ: &str = "feature_flag:read";
const SCOPE_FEATURE_FLAG_WRITE: &str = "feature_flag:write";

/// Cached token metadata written to Redis
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type")]
pub enum TokenAuthData {
    #[serde(rename = "secret")]
    Secret { team_id: i32 },
    #[serde(rename = "personal")]
    Personal {
        user_id: i32,
        org_ids: Vec<String>,
        scoped_teams: Option<Vec<i32>>,
        scoped_orgs: Option<Vec<String>>,
        scopes: Option<Vec<String>>,
    },
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

    let token_hash = hash_token_value(token);
    let pg_reader: PostgresReader = state.database_pools.non_persons_reader.clone();
    let token_owned = token.to_string();

    let result = state
        .auth_token_cache
        .get_or_load(&token_hash, |_key| async {
            match Team::from_pg_by_secret_token(pg_reader, &token_owned).await {
                Ok(team) => Ok::<_, FlagError>(Some(TokenAuthData::Secret { team_id: team.id })),
                Err(e) => {
                    warn!(error = %e, "Secret API token not found");
                    Ok(None)
                }
            }
        })
        .await?;

    match result.value {
        Some(TokenAuthData::Secret { team_id }) if team_id == expected_team_id => {
            debug!(team_id = team_id, "Secret API token validated");
            Ok(())
        }
        Some(TokenAuthData::Secret { team_id }) => {
            warn!(
                cached_team_id = team_id,
                expected_team_id = expected_team_id,
                "Secret API token belongs to a different team"
            );
            Err(FlagError::SecretApiTokenInvalid)
        }
        _ => Err(FlagError::SecretApiTokenInvalid),
    }
}

/// Hash a token value using SHA256
/// Ported from PostHog's `hash_key_value` function in `posthog/models/personal_api_key.py`
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
            ..
        } => {
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

            // Check scopes
            if let Some(scope_list) = scopes {
                if !scope_list.is_empty() {
                    let has_access = scope_list.iter().any(|s| {
                        s == SCOPE_WILDCARD
                            || s == SCOPE_FEATURE_FLAG_READ
                            || s == SCOPE_FEATURE_FLAG_WRITE
                    });
                    if !has_access {
                        debug!(scopes = ?scope_list, "Cached personal API key lacks feature flag scopes");
                        return Err(FlagError::PersonalApiKeyInvalid);
                    }
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
/// Returns Ok(()) if the personal API key has access to the specified team
pub async fn validate_personal_api_key_with_scopes_for_team(
    state: &AppState,
    key: &str,
    team: &Team,
) -> Result<(), FlagError> {
    use sqlx::Row;

    debug!(team_id = team.id, "Validating personal API key for team");

    let sha256_hash = hash_token_value(key);
    let pg_reader: PostgresReader = state.database_pools.non_persons_reader.clone();
    let hash_for_loader = sha256_hash.clone();

    let result = state
        .auth_token_cache
        .get_or_load(&sha256_hash, |_key| async move {
            let mut conn = pg_reader.get_connection().await.map_err(FlagError::from)?;

            let query = r#"
                SELECT
                    pak.id as key_id,
                    pak.scopes,
                    pak.scoped_teams,
                    pak.scoped_organizations,
                    u.id as user_id,
                    ARRAY(
                        SELECT om.organization_id::text
                        FROM posthog_organizationmembership om
                        WHERE om.user_id = u.id
                    ) as org_ids
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
                .bind(&hash_for_loader)
                .fetch_optional(&mut *conn)
                .await
                .map_err(FlagError::from)?;

            match row_result {
                Some(row) => {
                    let user_id: i32 = row.get("user_id");
                    let scoped_teams: Option<Vec<i32>> = row.try_get("scoped_teams").ok();
                    let scoped_organizations: Option<Vec<String>> =
                        row.try_get("scoped_organizations").ok();
                    let scopes: Option<Vec<String>> = row.try_get("scopes").ok();
                    let org_ids: Vec<String> = row.try_get("org_ids").unwrap_or_default();

                    Ok::<_, FlagError>(Some(TokenAuthData::Personal {
                        user_id,
                        org_ids,
                        scoped_teams,
                        scoped_orgs: scoped_organizations,
                        scopes,
                    }))
                }
                None => {
                    warn!("Personal API key not found or doesn't have required scopes");
                    Ok(None)
                }
            }
        })
        .await?;

    match &result.value {
        Some(data) => {
            validate_personal_key_metadata(data, team)?;
            debug!(team_id = team.id, "Personal API key validated successfully");
            Ok(())
        }
        None => Err(FlagError::PersonalApiKeyInvalid),
    }
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
        let data = TokenAuthData::Secret { team_id: 42 };
        let json = serde_json::to_string(&data).unwrap();
        assert!(json.contains("\"type\":\"secret\""));
        assert!(json.contains("\"team_id\":42"));

        let parsed: TokenAuthData = serde_json::from_str(&json).unwrap();
        match parsed {
            TokenAuthData::Secret { team_id } => assert_eq!(team_id, 42),
            _ => panic!("Expected Secret variant"),
        }
    }

    #[test]
    fn test_token_auth_data_serialization_personal() {
        let data = TokenAuthData::Personal {
            user_id: 7,
            org_ids: vec!["uuid-1".to_string()],
            scoped_teams: Some(vec![1, 2]),
            scoped_orgs: None,
            scopes: Some(vec!["feature_flag:read".to_string()]),
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
            org_ids: vec!["550e8400-e29b-41d4-a716-446655440000".to_string()],
            scoped_teams: Some(vec![1, 2]),
            scoped_orgs: None,
            scopes: Some(vec!["feature_flag:read".to_string()]),
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
            org_ids: vec!["550e8400-e29b-41d4-a716-446655440000".to_string()],
            scoped_teams: Some(vec![1, 2]),
            scoped_orgs: None,
            scopes: Some(vec!["feature_flag:read".to_string()]),
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
            org_ids: vec!["00000000-0000-0000-0000-000000000000".to_string()],
            scoped_teams: None,
            scoped_orgs: None,
            scopes: None,
        };

        assert!(validate_personal_key_metadata(&data, &team).is_err());
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
            org_ids: vec!["550e8400-e29b-41d4-a716-446655440000".to_string()],
            scoped_teams: None,
            scoped_orgs: None,
            scopes: None,
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
            org_ids: vec!["550e8400-e29b-41d4-a716-446655440000".to_string()],
            scoped_teams: None,
            scoped_orgs: None,
            scopes: Some(vec!["*".to_string()]),
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
            org_ids: vec!["550e8400-e29b-41d4-a716-446655440000".to_string()],
            scoped_teams: None,
            scoped_orgs: Some(vec![
                "550e8400-e29b-41d4-a716-446655440000".to_string(),
            ]),
            scopes: None,
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
            org_ids: vec!["550e8400-e29b-41d4-a716-446655440000".to_string()],
            scoped_teams: None,
            scoped_orgs: Some(vec!["aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee".to_string()]),
            scopes: None,
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
            org_ids: vec!["550e8400-e29b-41d4-a716-446655440000".to_string()],
            scoped_teams: None,
            scoped_orgs: None,
            scopes: Some(vec!["session_recording:read".to_string()]),
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

        let data = TokenAuthData::Secret { team_id: 1 };

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
            org_ids: vec!["550e8400-e29b-41d4-a716-446655440000".to_string()],
            scoped_teams: None,
            scoped_orgs: None,
            scopes: Some(vec!["feature_flag:write".to_string()]),
        };

        assert!(validate_personal_key_metadata(&data, &team).is_ok());
    }

    #[test]
    fn test_validate_personal_key_metadata_empty_scoped_vecs_treated_as_unscoped() {
        // Some(vec![]) means "no restriction" for scoped_teams, scoped_orgs, and scopes —
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
            org_ids: vec!["550e8400-e29b-41d4-a716-446655440000".to_string()],
            scoped_teams: Some(vec![]),  // empty = no restriction, team 99 should pass
            scoped_orgs: Some(vec![]),   // empty = no restriction
            scopes: Some(vec![]),        // empty = no restriction
        };

        assert!(validate_personal_key_metadata(&data, &team).is_ok());
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
            org_ids: vec![],
            scoped_teams: None,
            scoped_orgs: None,
            scopes: None,
        };

        assert!(validate_personal_key_metadata(&data, &team).is_ok());
    }
}
