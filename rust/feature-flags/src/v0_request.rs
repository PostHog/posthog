use std::{collections::HashMap, sync::Arc};

use bytes::Bytes;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use tracing::instrument;

use crate::{
    api::FlagError, database::Client as DatabaseClient, redis::Client as RedisClient, team::Team,
};

#[derive(Deserialize, Default)]
pub struct FlagsQueryParams {
    #[serde(alias = "v")]
    pub version: Option<String>,
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
    // TODO: better type this since we know its going to be a nested json
    #[serde(default)]
    pub group_properties: Option<HashMap<String, Value>>,
    #[serde(alias = "$anon_distinct_id", skip_serializing_if = "Option::is_none")]
    pub anon_distinct_id: Option<String>,
}

impl FlagRequest {
    /// Takes a request payload and tries to read it.
    /// Only supports base64 encoded payloads or uncompressed utf-8 as json.
    #[instrument(skip_all)]
    pub fn from_bytes(bytes: Bytes) -> Result<FlagRequest, FlagError> {
        tracing::debug!(len = bytes.len(), "decoding new request");
        // TODO: Add base64 decoding
        let payload = String::from_utf8(bytes.into()).map_err(|e| {
            tracing::error!("failed to decode body: {}", e);
            FlagError::RequestDecodingError(String::from("invalid body encoding"))
        })?;

        tracing::debug!(json = payload, "decoded event data");
        Ok(serde_json::from_str::<FlagRequest>(&payload)?)
    }

    pub async fn extract_and_verify_token(
        &self,
        redis_client: Arc<dyn RedisClient + Send + Sync>,
        pg_client: Arc<dyn DatabaseClient + Send + Sync>,
    ) -> Result<String, FlagError> {
        let token = match self {
            FlagRequest {
                token: Some(token), ..
            } => token.to_string(),
            _ => return Err(FlagError::NoTokenError),
        };

        match Team::from_redis(redis_client.clone(), token.clone()).await {
            Ok(_) => Ok(token),
            Err(_) => {
                // Fallback: Check PostgreSQL if not found in Redis
                match Team::from_pg(pg_client, token.clone()).await {
                    Ok(team) => {
                        // Token found in PostgreSQL, update Redis cache
                        if let Err(e) = Team::update_redis_cache(redis_client, team).await {
                            tracing::warn!("Failed to update Redis cache: {}", e);
                        }
                        Ok(token)
                    }
                    Err(_) => Err(FlagError::TokenValidationError),
                }
            }
        }
    }

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
}

#[cfg(test)]
mod tests {
    use crate::api::FlagError;
    use crate::v0_request::FlagRequest;
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
            "distinct_id": std::iter::repeat("a").take(210).collect::<String>(),
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
}
