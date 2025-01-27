use std::collections::HashMap;

use bytes::Bytes;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use tracing::instrument;

use crate::api::errors::FlagError;

#[derive(Debug, Clone, Copy)]
pub enum FlagRequestType {
    Decide,
    LocalEvaluation,
}

#[derive(Default, Debug, Deserialize, Serialize)]
pub struct FlagRequest {
    #[serde(
        alias = "$token",
        alias = "api_key",
        skip_serializing_if = "Option::is_none"
    )]
    pub token: Option<String>,
    #[serde(alias = "$distinct_id", skip_serializing_if = "Option::is_none")]
    pub distinct_id: Option<String>,
    pub geoip_disable: Option<bool>,
    #[serde(default)]
    pub person_properties: Option<HashMap<String, Value>>,
    #[serde(default)]
    pub groups: Option<HashMap<String, Value>>,
    #[serde(default)]
    pub group_properties: Option<HashMap<String, HashMap<String, Value>>>,
    #[serde(alias = "$anon_distinct_id", skip_serializing_if = "Option::is_none")]
    pub anon_distinct_id: Option<String>,
    pub ip_address: Option<String>,
}

impl FlagRequest {
    /// Takes a request payload and tries to read it.
    /// Only supports base64 encoded payloads or uncompressed utf-8 as json.
    #[instrument(skip_all)]
    pub fn from_bytes(bytes: Bytes) -> Result<FlagRequest, FlagError> {
        tracing::debug!(len = bytes.len(), "decoding new request");

        let payload = String::from_utf8(bytes.to_vec()).map_err(|e| {
            tracing::error!("failed to decode body: {}", e);
            FlagError::RequestDecodingError(String::from("invalid body encoding"))
        })?;

        tracing::debug!(json = payload, "decoded event data");

        // Attempt to parse as JSON, rejecting invalid JSON
        match serde_json::from_str::<FlagRequest>(&payload) {
            Ok(request) => Ok(request),
            Err(e) => {
                tracing::error!("failed to parse JSON: {}", e);
                Err(FlagError::RequestDecodingError(String::from(
                    "invalid JSON",
                )))
            }
        }
    }

    /// Extracts the token from the request.
    /// If the token is missing or empty, an error is returned.
    pub fn extract_token(&self) -> Result<String, FlagError> {
        match &self.token {
            Some(token) if !token.is_empty() => Ok(token.clone()),
            _ => Err(FlagError::NoTokenError),
        }
    }

    /// Extracts the distinct_id from the request.
    /// If the distinct_id is missing or empty, an error is returned.
    pub fn extract_distinct_id(&self) -> Result<String, FlagError> {
        let distinct_id = match &self.distinct_id {
            None => return Err(FlagError::MissingDistinctId),
            Some(id) => id,
        };

        match distinct_id.len() {
            0 => Err(FlagError::EmptyDistinctId),
            1..=200 => Ok(distinct_id.to_owned()),
            _ => Ok(distinct_id.chars().take(200).collect()),
        }
    }

    /// Extracts the properties from the request.
    /// If the request contains person_properties, they are returned.
    // TODO do I even need this one?
    pub fn extract_properties(&self) -> HashMap<String, Value> {
        let mut properties = HashMap::new();
        if let Some(person_properties) = &self.person_properties {
            properties.extend(person_properties.clone());
        }
        properties
    }
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;

    use crate::api::errors::FlagError;

    use crate::flags::flag_request::FlagRequest;
    use crate::flags::flag_service::FlagService;
    use crate::utils::test_utils::{
        insert_new_team_in_redis, setup_pg_reader_client, setup_redis_client,
    };
    use bytes::Bytes;
    use serde_json::json;

    #[test]
    fn empty_distinct_id_not_accepted() {
        let json = json!({
            "distinct_id": "",
            "token": "my_token1",
        });
        let bytes = Bytes::from(json.to_string());

        let flag_payload = FlagRequest::from_bytes(bytes).expect("failed to parse request");

        match flag_payload.extract_distinct_id() {
            Err(FlagError::EmptyDistinctId) => (),
            _ => panic!("expected empty distinct id error"),
        };
    }

    #[test]
    fn too_large_distinct_id_is_truncated() {
        let json = json!({
            "distinct_id": "a".repeat(210),
            "token": "my_token1",
        });
        let bytes = Bytes::from(json.to_string());

        let flag_payload = FlagRequest::from_bytes(bytes).expect("failed to parse request");

        assert_eq!(flag_payload.extract_distinct_id().unwrap().len(), 200);
    }

    #[test]
    fn distinct_id_is_returned_correctly() {
        let json = json!({
            "$distinct_id": "alakazam",
            "token": "my_token1",
        });
        let bytes = Bytes::from(json.to_string());

        let flag_payload = FlagRequest::from_bytes(bytes).expect("failed to parse request");

        match flag_payload.extract_distinct_id() {
            Ok(id) => assert_eq!(id, "alakazam"),
            _ => panic!("expected distinct id"),
        };
    }

    #[tokio::test]
    async fn token_is_returned_correctly() {
        let redis_client = setup_redis_client(None);
        let pg_client = setup_pg_reader_client(None).await;
        let team = insert_new_team_in_redis(redis_client.clone())
            .await
            .expect("Failed to insert new team in Redis");

        let json = json!({
            "$distinct_id": "alakazam",
            "token": team.api_token,
        });
        let bytes = Bytes::from(json.to_string());

        let flag_payload = FlagRequest::from_bytes(bytes).expect("failed to parse request");

        let token = flag_payload
            .extract_token()
            .expect("failed to extract token");

        let flag_service = FlagService::new(redis_client.clone(), pg_client.clone());

        match flag_service.verify_token(&token).await {
            Ok(extracted_token) => assert_eq!(extracted_token, team.api_token),
            Err(e) => panic!("Failed to extract and verify token: {:?}", e),
        };
    }

    #[test]
    fn test_extract_properties() {
        let flag_request = FlagRequest {
            person_properties: Some(HashMap::from([
                ("key1".to_string(), json!("value1")),
                ("key2".to_string(), json!(42)),
            ])),
            ..Default::default()
        };

        let properties = flag_request.extract_properties();
        assert_eq!(properties.len(), 2);
        assert_eq!(properties.get("key1").unwrap(), &json!("value1"));
        assert_eq!(properties.get("key2").unwrap(), &json!(42));
    }

    #[tokio::test]
    async fn test_error_cases() {
        let redis_client = setup_redis_client(None);
        let pg_client = setup_pg_reader_client(None).await;

        // Test invalid token
        let flag_request = FlagRequest {
            token: Some("invalid_token".to_string()),
            ..Default::default()
        };
        let result = flag_request
            .extract_token()
            .expect("failed to extract token");

        let flag_service = FlagService::new(redis_client.clone(), pg_client.clone());
        assert!(matches!(
            flag_service.verify_token(&result).await,
            Err(FlagError::TokenValidationError)
        ));

        // Test missing distinct_id
        let flag_request = FlagRequest {
            token: Some("valid_token".to_string()),
            distinct_id: None,
            ..Default::default()
        };
        let result = flag_request.extract_distinct_id();
        assert!(matches!(result, Err(FlagError::MissingDistinctId)));
    }
}
