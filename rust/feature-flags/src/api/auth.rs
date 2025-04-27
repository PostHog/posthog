use crate::api::request_handler::RequestInfo;
use crate::client::database::Client;
use crate::flags::models::PersonalAPIKey;
use base64::engine::general_purpose;
use base64::Engine;
use chrono::{Duration, Utc};
use pbkdf2::pbkdf2_hmac_array;
use sha2::{Digest, Sha256};
use sqlx::FromRow;
use thiserror::Error;

#[derive(Debug, PartialEq, Eq)]
pub enum ApiKeySource {
    AuthorizationHeader,
    Body,
    Query,
}

#[derive(Error, Debug)]
pub enum AuthError {
    #[error("Invalid personal API key")]
    InvalidPersonalApiKey,

    #[error("No personal API key in request")]
    NoPersonalApiKey,

    #[error("Invalid key")]
    InvalidKey(String),

    #[error("Internal error: {0}")]
    Internal(String),

    #[error("Request decoding error: {0}")]
    RequestDecodingError(String),

    #[error("Invalid scopes: {0}")]
    InvalidScopes(String),
}

// Ported from auth.py
pub fn find_personal_api_key_with_source(
    request: &RequestInfo,
) -> Result<(String, ApiKeySource), AuthError> {
    // Per the docs: https://posthog.com/docs/api
    // We try to read the personal API token from these three places in order.
    // We use the first one we find.
    // The bearer token: Authorization: "Bearer ${POSTHOG_PERSONAL_API_KEY}"
    // The request body: { "personal_api_key": "..."}
    // The query param: ?personal_api_key=...
    // Then we return the key along with where we found it.

    let body = &request.body;
    let headers = &request.headers;
    let query = &request.meta;

    // We try to read the personal API token from the bearer token first.
    if let Some(auth_header) = headers.get("Authorization").and_then(|v| v.to_str().ok()) {
        let mut parts = auth_header.split_whitespace();
        match (parts.next(), parts.next()) {
            (Some("Bearer"), Some(token)) if !token.is_empty() => {
                return Ok((token.to_string(), ApiKeySource::AuthorizationHeader));
            }
            (Some("Bearer"), Some(_)) => {
                return Err(AuthError::NoPersonalApiKey);
            }
            _ => {}
        }
    }

    // We try to read the personal API token from the request body.
    if !body.is_empty() {
        let request_body = String::from_utf8(body.to_vec())
            .map_err(|e| AuthError::RequestDecodingError(e.to_string()))?;

        let request_body_json: serde_json::Value = serde_json::from_str(&request_body)
            .map_err(|e| AuthError::RequestDecodingError(e.to_string()))?;

        let personal_api_token = request_body_json
            .get("personal_api_key")
            .and_then(|v| v.as_str())
            .map(|s| s.to_string());

        if let Some(personal_api_token) = personal_api_token {
            return Ok((personal_api_token, ApiKeySource::Body));
        }
    }

    // Try to read it from the query string parameters.
    let personal_api_token = query.personal_api_key.clone();

    if let Some(personal_api_token) = personal_api_token {
        return Ok((personal_api_token, ApiKeySource::Query));
    }

    return Err(AuthError::NoPersonalApiKey);
}

const LEGACY_PERSONAL_API_KEY_SALT: &str = "posthog_personal_api_key";
const PERSONAL_API_KEY_MODES_TO_TRY: &[(&str, Option<u32>)] = &[
    ("sha256", None),
    ("pbkdf2", Some(260_000)),
    ("pbkdf2", Some(390_000)),
];

// Ported from auth.py
pub fn hash_key_value(
    value: &str,
    mode: &str,
    iterations: Option<u32>,
) -> Result<String, AuthError> {
    match mode {
        "pbkdf2" => {
            let iterations = iterations.ok_or_else(|| {
                AuthError::Internal(
                    "Iterations must be provided when using legacy PBKDF2 mode".to_string(),
                )
            })?;

            // 32 bytes output, just like Django
            let hash = pbkdf2_hmac_array::<Sha256, 32>(
                value.as_bytes(),
                LEGACY_PERSONAL_API_KEY_SALT.as_bytes(),
                iterations,
            );

            // Django's PBKDF2PasswordHasher encodes as: "pbkdf2_sha256$<iterations>$<salt>$<b64hash>"
            let hash_b64 = general_purpose::STANDARD.encode(hash);

            Ok(format!(
                "pbkdf2_sha256${}${}${}",
                iterations, LEGACY_PERSONAL_API_KEY_SALT, hash_b64
            ))
        }
        "sha256" => {
            if iterations.is_some() {
                return Err(AuthError::Internal(
                    "Iterations must not be provided when using simple hashing mode".to_string(),
                ));
            }

            let mut hasher = Sha256::new();
            hasher.update(value.as_bytes());
            Ok(format!("sha256${:x}", hasher.finalize()))
        }
        _ => Err(AuthError::Internal("Invalid hash mode".to_string())),
    }
}

// Ported from auth.py
pub async fn validate_personal_api_key(
    pool: &(dyn Client + Send + Sync),
    personal_api_key: &str,
    source: ApiKeySource,
) -> Result<PersonalAPIKey, AuthError> {
    let mut personal_api_key_row = None;
    let mut mode_used = None;

    // Try each mode until we find a match
    for &(mode, iterations) in PERSONAL_API_KEY_MODES_TO_TRY {
        let secure_value = hash_key_value(personal_api_key, mode, iterations)?;
        // The stored team_id is always null because personal API keys are no
        // longer scoped to a team, but a user.
        // TODO: We might want to consider using a LEFT JOIN to get the team_id
        // and organization_id for legacy personal API keys so that we can warn
        // on keys for users that don't have a team. I'm fine with leaving this
        // as is for now.
        let query = "SELECT 
                pk.id,
                u.current_team_id as team_id,
                t.organization_id,
                pk.user_id,
                pk.label,
                pk.value,
                pk.mask_value,
                pk.secure_value,
                pk.created_at,
                pk.last_used_at,
                pk.scopes,
                pk.scoped_teams,
                pk.scoped_organizations
            FROM posthog_personalapikey pk
            INNER JOIN posthog_user u ON pk.user_id = u.id
            INNER JOIN posthog_team t ON t.id = u.current_team_id
            WHERE pk.secure_value = $1 AND u.is_active = true";
        let rows = pool
            .run_query(query.to_string(), vec![secure_value], None)
            .await
            .map_err(|e| {
                tracing::error!("Failed to fetch personal API key from database: {}", e);
                AuthError::Internal(format!("Database query error: {}", e))
            })?;

        if let Some(row) = rows.first() {
            personal_api_key_row = Some(
                PersonalAPIKey::from_row(row)
                    .map_err(|e| AuthError::Internal(format!("Failed to parse row: {}", e)))?,
            );
            mode_used = Some(mode);
            break;
        }
    }

    let api_key = personal_api_key_row.ok_or_else(|| {
        AuthError::InvalidKey(format!(
            "Personal API key found in request {:?} is invalid.",
            source
        ))
    })?;

    // Upgrade the key if it's not using the latest mode (sha256)
    if mode_used.unwrap() != "sha256" {
        let secure_value = hash_key_value(personal_api_key, "sha256", None)?;
        let update_query = "UPDATE posthog_personalapikey SET secure_value = $1 WHERE id = $2";
        pool.run_query(
            update_query.to_string(),
            vec![secure_value, api_key.id.clone()],
            None,
        )
        .await
        .map_err(|e| {
            tracing::error!("Failed to update API key hash: {}", e);
            AuthError::Internal(format!("Failed to update API key hash: {}", e))
        })?;
    }

    Ok(api_key)
}

// Ported from auth.py
pub async fn authenticate_personal_api_key(
    pool: &(dyn Client + Send + Sync),
    request: &RequestInfo,
) -> Result<PersonalAPIKey, AuthError> {
    let (personal_api_key, source) = find_personal_api_key_with_source(request)?;
    let mut personal_api_key = validate_personal_api_key(pool, &personal_api_key, source).await?;

    // Update last_used_at if needed (if None or more than 1 hour ago)
    let now = Utc::now();
    let needs_update = match personal_api_key.last_used_at {
        None => true,
        Some(last) => now.signed_duration_since(last) > Duration::hours(1),
    };
    if needs_update {
        let update_query = "UPDATE posthog_personalapikey SET last_used_at = NOW() WHERE id = $1";
        pool.run_query(
            update_query.to_string(),
            vec![personal_api_key.id.clone()],
            None,
        )
        .await
        .map_err(|e| AuthError::Internal(format!("Failed to update last_used_at: {}", e)))?;
        // Update the struct in memory too
        personal_api_key.last_used_at = Some(now);
    }

    Ok(personal_api_key)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::api::request_handler::{FlagsQueryParams, RequestInfo};
    use crate::utils::test_utils::insert_personal_api_key_for_user;
    use axum::http::{HeaderMap, HeaderValue, Method};
    use bytes::Bytes;
    use uuid::Uuid;

    #[test]
    fn test_find_personal_api_key_with_source_from_bearer() {
        let mut headers = HeaderMap::new();
        headers.insert(
            "Authorization",
            HeaderValue::from_static("Bearer test-token"),
        );

        let request = RequestInfo {
            id: Uuid::new_v4(),
            ip: "127.0.0.1".parse().unwrap(),
            headers,
            body: Bytes::new(),
            method: Method::GET,
            meta: FlagsQueryParams {
                version: None,
                compression: None,
                lib_version: None,
                sent_at: None,
                personal_api_key: None,
            },
        };

        let (key, source) = find_personal_api_key_with_source(&request).unwrap();
        assert_eq!(key, "test-token");
        assert_eq!(source, ApiKeySource::AuthorizationHeader);
    }

    #[test]
    fn test_find_personal_api_token_from_body() {
        let request = RequestInfo {
            id: Uuid::new_v4(),
            ip: "127.0.0.1".parse().unwrap(),
            headers: HeaderMap::new(),
            body: Bytes::from(r#"{"personal_api_key": "test-token"}"#),
            method: Method::GET,
            meta: FlagsQueryParams {
                version: None,
                compression: None,
                lib_version: None,
                sent_at: None,
                personal_api_key: None,
            },
        };

        let (key, source) = find_personal_api_key_with_source(&request).unwrap();
        assert_eq!(key, "test-token");
        assert_eq!(source, ApiKeySource::Body);
    }

    #[test]
    fn test_find_personal_api_token_from_query() {
        let request = RequestInfo {
            id: Uuid::new_v4(),
            ip: "127.0.0.1".parse().unwrap(),
            headers: HeaderMap::new(),
            body: Bytes::new(),
            method: Method::GET,
            meta: FlagsQueryParams {
                version: None,
                compression: None,
                lib_version: None,
                sent_at: None,
                personal_api_key: Some("test-token".to_string()),
            },
        };

        let (key, source) = find_personal_api_key_with_source(&request).unwrap();
        assert_eq!(key, "test-token");
        assert_eq!(source, ApiKeySource::Query);
    }

    #[test]
    fn test_find_personal_api_token_priority() {
        // Test that bearer token takes precedence over body and query
        let mut headers = HeaderMap::new();
        headers.insert(
            "Authorization",
            HeaderValue::from_static("Bearer bearer-token"),
        );
        let request = RequestInfo {
            id: Uuid::new_v4(),
            ip: "127.0.0.1".parse().unwrap(),
            headers,
            body: Bytes::from(r#"{"personal_api_key": "body-token"}"#),
            method: Method::GET,
            meta: FlagsQueryParams {
                version: None,
                compression: None,
                lib_version: None,
                sent_at: None,
                personal_api_key: Some("query-token".to_string()),
            },
        };

        let (key, source) = find_personal_api_key_with_source(&request).unwrap();
        assert_eq!(key, "bearer-token");
        assert_eq!(source, ApiKeySource::AuthorizationHeader);
    }

    #[test]
    fn test_find_personal_api_token_missing() {
        let request = RequestInfo {
            id: Uuid::new_v4(),
            ip: "127.0.0.1".parse().unwrap(),
            headers: HeaderMap::new(),
            body: Bytes::new(),
            method: Method::GET,
            meta: FlagsQueryParams {
                version: None,
                compression: None,
                lib_version: None,
                sent_at: None,
                personal_api_key: None,
            },
        };

        let result = find_personal_api_key_with_source(&request);
        assert!(matches!(result, Err(AuthError::NoPersonalApiKey)));
    }

    #[test]
    fn test_find_personal_api_token_invalid_body() {
        let request = RequestInfo {
            id: Uuid::new_v4(),
            ip: "127.0.0.1".parse().unwrap(),
            headers: HeaderMap::new(),
            body: Bytes::from("invalid json"),
            method: Method::GET,
            meta: FlagsQueryParams {
                version: None,
                compression: None,
                lib_version: None,
                sent_at: None,
                personal_api_key: None,
            },
        };

        let result = find_personal_api_key_with_source(&request);
        assert!(matches!(result, Err(AuthError::RequestDecodingError(_))));
    }

    #[test]
    fn test_find_personal_api_key_with_source_empty_bearer() {
        let mut headers = HeaderMap::new();
        headers.insert("Authorization", HeaderValue::from_static("Bearer "));

        let request = RequestInfo {
            id: Uuid::new_v4(),
            ip: "127.0.0.1".parse().unwrap(),
            headers,
            body: Bytes::new(),
            method: Method::GET,
            meta: FlagsQueryParams {
                version: None,
                compression: None,
                lib_version: None,
                sent_at: None,
                personal_api_key: None,
            },
        };

        let result = find_personal_api_key_with_source(&request);
        assert!(matches!(result, Err(AuthError::NoPersonalApiKey)));
    }

    #[test]
    fn test_hash_key_value_sha256() {
        let value = "phx_XalGN9039Jm7WFAZwFSZQ3yv0Kgo7qJyOHe11b2fHaZU6FS";
        let hash = "sha256$a8991682dd3f0c6d22227115714af2d2e9f5da9978495e29c35f65f16ee52559";
        assert!(hash.starts_with("sha256$"));
        // Should be deterministic
        assert_eq!(hash, hash_key_value(value, "sha256", None).unwrap());
    }

    #[test]
    fn test_hash_key_value_pbkdf2() {
        let value = "testkey";
        let hash = hash_key_value(value, "pbkdf2", Some(260_000)).unwrap();
        assert!(hash.starts_with("pbkdf2_sha256$260000$posthog_personal_api_key$"));
    }

    #[test]
    fn test_hash_key_value_pbkdf2_missing_iterations() {
        let value = "testkey";
        let err = hash_key_value(value, "pbkdf2", None).unwrap_err();
        assert!(matches!(err, AuthError::Internal(_)));
    }

    #[test]
    fn test_hash_key_value_sha256_with_iterations_should_error() {
        let value = "testkey";
        let err = hash_key_value(value, "sha256", Some(123)).unwrap_err();
        assert!(matches!(err, AuthError::Internal(_)));
    }

    #[tokio::test]
    async fn test_validate_personal_api_key_valid() {
        use crate::utils::test_utils::setup_pg_reader_client;
        let client = setup_pg_reader_client(None).await;

        // Truncate the table to avoid unique constraint errors
        let mut conn = client
            .get_connection()
            .await
            .expect("Failed to get connection");
        sqlx::query("TRUNCATE TABLE posthog_personalapikey CASCADE")
            .execute(&mut *conn)
            .await
            .expect("Failed to truncate posthog_personalapikey");

        // Insert a team and get its user_id (adapt as needed for your schema)
        let team = crate::utils::test_utils::insert_new_team_in_pg(client.clone(), None)
            .await
            .expect("Failed to insert team");
        let user = crate::utils::test_utils::insert_user_for_team_in_pg(client.clone(), team.id)
            .await
            .expect("Failed to insert user");
        let user_id = user.id;
        let api_key_str = "phx_JVRb8fNi0XyIKGgUCyi29ZJUOXEr6NF2dKBy5Ws8XVeF11C";
        insert_personal_api_key_for_user(client.clone(), user_id, api_key_str)
            .await
            .expect("Failed to insert personal API key");

        let result = validate_personal_api_key(
            client.as_ref(),
            api_key_str,
            ApiKeySource::AuthorizationHeader,
        )
        .await;

        let api_key = result.expect("validate_personal_api_key failed");
        assert_eq!(
            api_key.secure_value.as_deref(),
            Some(
                hash_key_value(api_key_str, "sha256", None)
                    .unwrap()
                    .as_str()
            )
        );
        assert!(!api_key.id.is_empty());
    }

    #[tokio::test]
    async fn test_validate_personal_api_key_invalid() {
        use crate::utils::test_utils::setup_pg_reader_client;
        let client = setup_pg_reader_client(None).await;
        // This key is a valid format, but does not exist in the database
        let result = validate_personal_api_key(
            client.as_ref(),
            "phx_XalGN9039Jm7WFAZwFSZQ3yv0Kgo7qJyOHe11b2fHaZU6FS",
            ApiKeySource::AuthorizationHeader,
        )
        .await;
        assert!(matches!(result, Err(AuthError::InvalidKey(_))));
    }

    #[tokio::test]
    async fn test_authenticate_personal_api_key_valid() {
        use crate::utils::test_utils::{
            insert_new_team_in_pg, insert_personal_api_key_for_user, insert_user_for_team_in_pg,
            setup_pg_reader_client,
        };
        use axum::http::{HeaderMap, HeaderValue, Method};
        use bytes::Bytes;
        use uuid::Uuid;

        let client = setup_pg_reader_client(None).await;
        // Truncate the table to avoid unique constraint errors
        let mut conn = client
            .get_connection()
            .await
            .expect("Failed to get connection");
        sqlx::query("TRUNCATE TABLE posthog_personalapikey CASCADE")
            .execute(&mut *conn)
            .await
            .expect("Failed to truncate posthog_personalapikey");

        let team = insert_new_team_in_pg(client.clone(), None)
            .await
            .expect("Failed to insert team");
        let user = insert_user_for_team_in_pg(client.clone(), team.id)
            .await
            .expect("Failed to insert user");
        let api_key_str = "phx_KIwIaTavK0c4uE4s0iPj6Ir7uGpDhHpius8pKs80GZd0Srp";
        insert_personal_api_key_for_user(client.clone(), user.id, api_key_str)
            .await
            .expect("Failed to insert personal API key");

        let mut headers = HeaderMap::new();
        headers.insert(
            "Authorization",
            HeaderValue::from_str(&format!("Bearer {}", api_key_str)).unwrap(),
        );
        let request = RequestInfo {
            id: Uuid::new_v4(),
            ip: "127.0.0.1".parse().unwrap(),
            headers,
            body: Bytes::new(),
            method: Method::GET,
            meta: crate::api::request_handler::FlagsQueryParams::default(),
        };
        let api_key = authenticate_personal_api_key(client.as_ref(), &request)
            .await
            .expect("Should authenticate");
        assert_eq!(api_key.team_id, Some(team.id));
    }
}
