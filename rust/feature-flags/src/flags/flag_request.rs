use std::collections::HashMap;

use bytes::Bytes;
use serde::{Deserialize, Deserializer, Serialize};
use serde_json::Value;

use crate::api::errors::FlagError;
use crate::handler::flags::EvaluationRuntime;

fn deserialize_distinct_id<'de, D>(deserializer: D) -> Result<Option<String>, D::Error>
where
    D: Deserializer<'de>,
{
    #[derive(Deserialize)]
    #[serde(untagged)]
    enum StringOrNumber {
        String(String),
        Number(serde_json::Number),
    }

    let opt = Option::<StringOrNumber>::deserialize(deserializer)?;
    Ok(opt.map(|val| match val {
        StringOrNumber::String(s) => s,
        StringOrNumber::Number(n) => n.to_string(),
    }))
}

#[derive(Debug, Clone, Copy)]
pub enum FlagRequestType {
    Decide,
    FlagDefinitions,
}

#[derive(Default, Debug, Deserialize, Serialize)]
pub struct FlagRequest {
    #[serde(
        alias = "$token",
        alias = "api_key",
        skip_serializing_if = "Option::is_none"
    )]
    pub token: Option<String>,
    #[serde(
        alias = "$distinct_id",
        skip_serializing_if = "Option::is_none",
        deserialize_with = "deserialize_distinct_id",
        default
    )]
    pub distinct_id: Option<String>,
    pub geoip_disable: Option<bool>,
    // Web and mobile clients can configure this parameter to disable flags for a request.
    // It's mostly used for folks who want to save money on flag evaluations while still using
    // `/flags` to load the rest of their PostHog configuration.
    pub disable_flags: Option<bool>,
    #[serde(default, alias = "$properties")]
    pub person_properties: Option<HashMap<String, Value>>,
    #[serde(default, alias = "$groups")]
    pub groups: Option<HashMap<String, Value>>,
    #[serde(default, alias = "$group_properties")]
    pub group_properties: Option<HashMap<String, HashMap<String, Value>>>,
    #[serde(alias = "$anon_distinct_id", skip_serializing_if = "Option::is_none")]
    pub anon_distinct_id: Option<String>,
    pub ip_address: Option<String>,
    #[serde(default, alias = "flag_keys_to_evaluate")]
    pub flag_keys: Option<Vec<String>>,
    #[serde(default)]
    pub timezone: Option<String>,
    #[serde(default)]
    pub cookieless_hash_extra: Option<String>,
    #[serde(default)]
    pub evaluation_environments: Option<Vec<String>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub evaluation_runtime: Option<EvaluationRuntime>,
}

impl FlagRequest {
    /// Takes a request payload and tries to read it.
    /// Only supports base64 encoded payloads or uncompressed utf-8 as json.
    pub fn from_bytes(bytes: Bytes) -> Result<FlagRequest, FlagError> {
        // Handle UTF-8 conversion more gracefully, similar to form data handling
        let payload = match String::from_utf8(bytes.to_vec()) {
            Ok(s) => s,
            Err(e) => {
                tracing::warn!(
                    "Invalid UTF-8 in request body, using lossy conversion: {}",
                    e
                );
                // Use lossy conversion as fallback - this handles Android clients that might
                // send malformed UTF-8 sequences after decompression
                String::from_utf8_lossy(&bytes).into_owned()
            }
        };

        // Use json5 to parse, which handles NaN/Infinity natively
        let mut value: Value = match json5::from_str(&payload) {
            Ok(v) => v,
            Err(e) => {
                tracing::warn!("failed to parse JSON: {}", e);
                return Err(FlagError::RequestDecodingError(String::from(
                    "invalid JSON",
                )));
            }
        };

        Self::clean_non_finite_values(&mut value);

        // Deserialize the cleaned value into FlagRequest
        match serde_json::from_value::<FlagRequest>(value) {
            Ok(request) => Ok(request),
            Err(e) => {
                tracing::warn!("failed to parse JSON: {}", e);
                Err(FlagError::RequestDecodingError(String::from(
                    "invalid JSON",
                )))
            }
        }
    }

    /// Replaces non-finite numbers (NaN, Infinity, -Infinity) with null in a JSON Value
    /// This matches Python decide endpoint behavior: parse_constant=lambda x: None
    fn clean_non_finite_values(value: &mut Value) {
        match value {
            Value::Number(n) => {
                if let Some(f) = n.as_f64() {
                    if !f.is_finite() {
                        *value = Value::Null;
                    }
                }
            }
            Value::Object(map) => {
                for (_, v) in map.iter_mut() {
                    Self::clean_non_finite_values(v);
                }
            }
            Value::Array(arr) => {
                for v in arr.iter_mut() {
                    Self::clean_non_finite_values(v);
                }
            }
            _ => {}
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
            None => {
                tracing::warn!("Missing distinct_id in request");
                return Err(FlagError::MissingDistinctId);
            }
            Some(id) => id,
        };

        match distinct_id.len() {
            0..=200 => Ok(distinct_id.to_owned()),
            _ => Ok(distinct_id.chars().take(200).collect()),
        }
    }

    /// Extracts the properties from the request.
    /// If the request contains person_properties, they are returned.
    pub fn extract_properties(&self) -> HashMap<String, Value> {
        if let Some(person_properties) = &self.person_properties {
            let mut properties = HashMap::with_capacity(person_properties.len());
            properties.extend(person_properties.clone());
            properties
        } else {
            HashMap::new()
        }
    }

    /// Checks if feature flags should be disabled for this request.
    /// Returns true if disable_flags is explicitly set to true.
    pub fn is_flags_disabled(&self) -> bool {
        matches!(self.disable_flags, Some(true))
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

    // Default cache TTL for tests: 5 days in seconds
    const DEFAULT_CACHE_TTL_SECONDS: u64 = 432000;

    #[test]
    fn empty_distinct_id_is_accepted() {
        let json = json!({
            "distinct_id": "",
            "token": "my_token1",
        });
        let bytes = Bytes::from(json.to_string());

        let flag_payload = FlagRequest::from_bytes(bytes).expect("failed to parse request");

        match flag_payload.extract_distinct_id() {
            Ok(distinct_id) => assert_eq!(distinct_id, ""),
            Err(e) => panic!("expected empty distinct_id to be accepted, got error: {e}"),
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
    fn test_nan_infinity_handling() {
        // Test unquoted NaN/Infinity values are replaced with null
        let json_str = r#"{
            "distinct_id": "user123",
            "token": "my_token1",
            "person_properties": {
                "score": NaN,
                "max_value": Infinity,
                "min_value": -Infinity,
                "valid_number": 42.5,
                "text_with_nan": "NaN is not a number",
                "text_with_infinity": "Infinity stones"
            }
        }"#;
        let bytes = Bytes::from(json_str);

        let flag_payload = FlagRequest::from_bytes(bytes).expect("failed to parse request");

        // Check that NaN/Infinity were replaced with null
        let props = flag_payload.person_properties.unwrap();
        assert_eq!(props.get("score"), Some(&serde_json::Value::Null));
        assert_eq!(props.get("max_value"), Some(&serde_json::Value::Null));
        assert_eq!(props.get("min_value"), Some(&serde_json::Value::Null));

        // Check that valid number is preserved
        assert_eq!(props.get("valid_number"), Some(&json!(42.5)));

        // Check that strings containing "NaN" and "Infinity" are preserved
        assert_eq!(
            props.get("text_with_nan"),
            Some(&json!("NaN is not a number"))
        );
        assert_eq!(
            props.get("text_with_infinity"),
            Some(&json!("Infinity stones"))
        );
    }

    #[test]
    fn test_nested_nan_infinity_handling() {
        // Test deeply nested NaN/Infinity values are also replaced
        let json_str = r#"{
            "distinct_id": "user123",
            "token": "my_token1",
            "group_properties": {
                "company": {
                    "metrics": {
                        "revenue": NaN,
                        "growth": Infinity,
                        "nested_array": [1, 2, NaN, Infinity, -Infinity, 3],
                        "payload": "{'foo': NaN}"
                    }
                }
            }
        }"#;
        let bytes = Bytes::from(json_str);

        let flag_payload = FlagRequest::from_bytes(bytes).expect("failed to parse request");

        // Check nested replacements
        let group_props = flag_payload.group_properties.unwrap();
        let company = group_props.get("company").unwrap();
        let metrics = company.get("metrics").unwrap().as_object().unwrap();

        assert_eq!(metrics.get("revenue"), Some(&serde_json::Value::Null));
        assert_eq!(metrics.get("growth"), Some(&serde_json::Value::Null));

        // Check array values
        let array = metrics.get("nested_array").unwrap().as_array().unwrap();
        assert_eq!(array[0], json!(1));
        assert_eq!(array[1], json!(2));
        assert_eq!(array[2], serde_json::Value::Null); // NaN
        assert_eq!(array[3], serde_json::Value::Null); // Infinity
        assert_eq!(array[4], serde_json::Value::Null); // -Infinity
        assert_eq!(array[5], json!(3));

        // Check that string containing "NaN" is preserved
        assert_eq!(metrics.get("payload"), Some(&json!("{'foo': NaN}")));
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

    #[test]
    fn numeric_distinct_id_is_returned_correctly() {
        let json = json!({
            "$distinct_id": 8675309,
            "token": "my_token1",
        });
        let bytes = Bytes::from(json.to_string());

        let flag_payload = FlagRequest::from_bytes(bytes).expect("failed to parse request");

        match flag_payload.extract_distinct_id() {
            Ok(id) => assert_eq!(id, "8675309"),
            _ => panic!("expected distinct id"),
        };
    }

    #[test]
    fn missing_distinct_id_is_handled_correctly() {
        let json = json!({
            "token": "my_token1",
        });
        let bytes = Bytes::from(json.to_string());

        let flag_payload = FlagRequest::from_bytes(bytes).expect("failed to parse request");

        // First verify the field is None
        assert_eq!(flag_payload.distinct_id, Option::<String>::None);
    }

    #[test]
    fn float_distinct_id_is_handled_correctly() {
        let json = json!({
            "$distinct_id": 123.45,
            "token": "my_token1",
        });
        let bytes = Bytes::from(json.to_string());

        let flag_payload = FlagRequest::from_bytes(bytes).expect("failed to parse request");
        assert_eq!(flag_payload.distinct_id, Some("123.45".to_string()));
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

    #[test]
    fn test_extract_token() {
        let json = json!({
            "distinct_id": "alakazam",
            "token": "my_token1",
        });
        let bytes = Bytes::from(json.to_string());

        let flag_payload = FlagRequest::from_bytes(bytes).expect("failed to parse request");

        match flag_payload.extract_token() {
            Ok(token) => assert_eq!(token, "my_token1"),
            _ => panic!("expected token"),
        };

        let json = json!({
            "distinct_id": "alakazam",
            "token": "",
        });
        let bytes = Bytes::from(json.to_string());

        let flag_payload = FlagRequest::from_bytes(bytes).expect("failed to parse request");

        match flag_payload.extract_token() {
            Err(FlagError::NoTokenError) => (),
            _ => panic!("expected empty token error"),
        };

        let json = json!({
            "distinct_id": "alakazam",
        });
        let bytes = Bytes::from(json.to_string());

        let flag_payload = FlagRequest::from_bytes(bytes).expect("failed to parse request");

        match flag_payload.extract_token() {
            Err(FlagError::NoTokenError) => (),
            _ => panic!("expected no token error"),
        };
    }

    #[test]
    fn test_disable_flags() {
        // Test with disable_flags: true
        let json = json!({
            "distinct_id": "test_id",
            "token": "test_token",
            "disable_flags": true
        });
        let bytes = Bytes::from(json.to_string());
        let flag_payload = FlagRequest::from_bytes(bytes).expect("failed to parse request");
        assert!(flag_payload.is_flags_disabled());

        // Test with disable_flags: false
        let json = json!({
            "distinct_id": "test_id",
            "token": "test_token",
            "disable_flags": false
        });
        let bytes = Bytes::from(json.to_string());
        let flag_payload = FlagRequest::from_bytes(bytes).expect("failed to parse request");
        assert!(!flag_payload.is_flags_disabled());

        // Test without disable_flags field
        let json = json!({
            "distinct_id": "test_id",
            "token": "test_token"
        });
        let bytes = Bytes::from(json.to_string());
        let flag_payload = FlagRequest::from_bytes(bytes).expect("failed to parse request");
        assert!(!flag_payload.is_flags_disabled());
    }

    #[tokio::test]
    async fn token_is_returned_correctly() {
        let redis_client = setup_redis_client(None).await;
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

        let flag_service = FlagService::new(
            redis_client.clone(),
            redis_client.clone(),
            pg_client.clone(),
            DEFAULT_CACHE_TTL_SECONDS,
            DEFAULT_CACHE_TTL_SECONDS,
        );

        match flag_service.verify_token(&token).await {
            Ok(extracted_token) => assert_eq!(extracted_token, team.api_token),
            Err(e) => panic!("Failed to extract and verify token: {e:?}"),
        };
    }

    #[tokio::test]
    async fn test_error_cases() {
        let redis_reader_client = setup_redis_client(None).await;
        let redis_writer_client = setup_redis_client(None).await;
        let pg_client = setup_pg_reader_client(None).await;

        // Test invalid token
        let flag_request = FlagRequest {
            token: Some("invalid_token".to_string()),
            ..Default::default()
        };
        let result = flag_request
            .extract_token()
            .expect("failed to extract token");

        let flag_service = FlagService::new(
            redis_reader_client.clone(),
            redis_writer_client.clone(),
            pg_client.clone(),
            DEFAULT_CACHE_TTL_SECONDS,
            DEFAULT_CACHE_TTL_SECONDS,
        );
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

    #[test]
    fn test_flag_keys_field_accepts_flag_keys() {
        let json = json!({
            "distinct_id": "user123",
            "token": "my_token1",
            "flag_keys": ["flag1", "flag2", "flag3"]
        });
        let bytes = Bytes::from(json.to_string());

        let flag_payload = FlagRequest::from_bytes(bytes).expect("failed to parse request");

        assert!(flag_payload.flag_keys.is_some());
        let flag_keys = flag_payload.flag_keys.unwrap();
        assert_eq!(flag_keys.len(), 3);
        assert_eq!(flag_keys[0], "flag1");
        assert_eq!(flag_keys[1], "flag2");
        assert_eq!(flag_keys[2], "flag3");
    }

    #[test]
    fn test_flag_keys_field_accepts_flag_keys_to_evaluate() {
        // This test should fail until we add the alias
        let json = json!({
            "distinct_id": "user123",
            "token": "my_token1",
            "flag_keys_to_evaluate": ["flag1", "flag2", "flag3"]
        });
        let bytes = Bytes::from(json.to_string());

        let flag_payload = FlagRequest::from_bytes(bytes).expect("failed to parse request");

        // This assertion should fail because flag_keys_to_evaluate is not recognized
        assert!(
            flag_payload.flag_keys.is_some(),
            "flag_keys_to_evaluate should be parsed into flag_keys field"
        );
        let flag_keys = flag_payload.flag_keys.unwrap();
        assert_eq!(flag_keys.len(), 3);
        assert_eq!(flag_keys[0], "flag1");
        assert_eq!(flag_keys[1], "flag2");
        assert_eq!(flag_keys[2], "flag3");
    }

    #[test]
    fn test_evaluation_runtime_field() {
        use crate::handler::flags::EvaluationRuntime;

        // Test with evaluation_runtime: "server"
        let json = json!({
            "distinct_id": "user123",
            "token": "my_token1",
            "evaluation_runtime": "server"
        });
        let bytes = Bytes::from(json.to_string());
        let flag_payload = FlagRequest::from_bytes(bytes).expect("failed to parse request");
        assert_eq!(
            flag_payload.evaluation_runtime,
            Some(EvaluationRuntime::Server)
        );

        // Test with evaluation_runtime: "client"
        let json = json!({
            "distinct_id": "user123",
            "token": "my_token1",
            "evaluation_runtime": "client"
        });
        let bytes = Bytes::from(json.to_string());
        let flag_payload = FlagRequest::from_bytes(bytes).expect("failed to parse request");
        assert_eq!(
            flag_payload.evaluation_runtime,
            Some(EvaluationRuntime::Client)
        );

        // Test with evaluation_runtime: "all"
        let json = json!({
            "distinct_id": "user123",
            "token": "my_token1",
            "evaluation_runtime": "all"
        });
        let bytes = Bytes::from(json.to_string());
        let flag_payload = FlagRequest::from_bytes(bytes).expect("failed to parse request");
        assert_eq!(
            flag_payload.evaluation_runtime,
            Some(EvaluationRuntime::All)
        );

        // Test without evaluation_runtime field
        let json = json!({
            "distinct_id": "user123",
            "token": "my_token1"
        });
        let bytes = Bytes::from(json.to_string());
        let flag_payload = FlagRequest::from_bytes(bytes).expect("failed to parse request");
        assert_eq!(flag_payload.evaluation_runtime, None);

        // Test with invalid evaluation_runtime value - should default to "all" with warning
        let json = json!({
            "distinct_id": "user123",
            "token": "my_token1",
            "evaluation_runtime": "invalid_value"
        });
        let bytes = Bytes::from(json.to_string());
        let flag_payload = FlagRequest::from_bytes(bytes).expect("failed to parse request");
        // Invalid values default to "all" per our custom deserializer
        assert_eq!(
            flag_payload.evaluation_runtime,
            Some(EvaluationRuntime::All)
        );

        // Test with case-insensitive values
        let json = json!({
            "distinct_id": "user123",
            "token": "my_token1",
            "evaluation_runtime": "CLIENT"
        });
        let bytes = Bytes::from(json.to_string());
        let flag_payload = FlagRequest::from_bytes(bytes).expect("failed to parse request");
        assert_eq!(
            flag_payload.evaluation_runtime,
            Some(EvaluationRuntime::Client)
        );
    }

    #[test]
    fn test_groups_field_accepts_groups() {
        let json = json!({
            "distinct_id": "user123",
            "token": "my_token1",
            "groups": {
                "organization": "org_123",
                "company": "company_456"
            }
        });
        let bytes = Bytes::from(json.to_string());

        let flag_payload = FlagRequest::from_bytes(bytes).expect("failed to parse request");

        assert!(flag_payload.groups.is_some());
        let groups = flag_payload.groups.unwrap();
        assert_eq!(groups.len(), 2);
        assert_eq!(groups.get("organization").unwrap(), &json!("org_123"));
        assert_eq!(groups.get("company").unwrap(), &json!("company_456"));
    }

    #[test]
    fn test_groups_field_accepts_dollar_groups_for_backwards_compatibility() {
        let json = json!({
            "distinct_id": "user123",
            "token": "my_token1",
            "$groups": {
                "organization": "org_123",
                "company": "company_456"
            }
        });
        let bytes = Bytes::from(json.to_string());

        let flag_payload = FlagRequest::from_bytes(bytes).expect("failed to parse request");

        assert!(flag_payload.groups.is_some());
        let groups = flag_payload.groups.unwrap();
        assert_eq!(groups.len(), 2);
        assert_eq!(groups.get("organization").unwrap(), &json!("org_123"));
        assert_eq!(groups.get("company").unwrap(), &json!("company_456"));
    }

    #[test]
    fn test_person_properties_field_accepts_dollar_properties_for_backwards_compatibility() {
        let json = json!({
            "distinct_id": "user123",
            "token": "my_token1",
            "$properties": {
                "email": "user@example.com",
                "age": 25
            }
        });
        let bytes = Bytes::from(json.to_string());

        let flag_payload = FlagRequest::from_bytes(bytes).expect("failed to parse request");

        assert!(flag_payload.person_properties.is_some());
        let props = flag_payload.person_properties.unwrap();
        assert_eq!(props.len(), 2);
        assert_eq!(props.get("email").unwrap(), &json!("user@example.com"));
        assert_eq!(props.get("age").unwrap(), &json!(25));
    }

    #[test]
    fn test_group_properties_field_accepts_dollar_group_properties_for_backwards_compatibility() {
        let json = json!({
            "distinct_id": "user123",
            "token": "my_token1",
            "$group_properties": {
                "organization": {
                    "name": "ACME Corp",
                    "size": 100
                }
            }
        });
        let bytes = Bytes::from(json.to_string());

        let flag_payload = FlagRequest::from_bytes(bytes).expect("failed to parse request");

        assert!(flag_payload.group_properties.is_some());
        let group_props = flag_payload.group_properties.unwrap();
        assert_eq!(group_props.len(), 1);
        let org_props = group_props.get("organization").unwrap();
        assert_eq!(org_props.get("name").unwrap(), &json!("ACME Corp"));
        assert_eq!(org_props.get("size").unwrap(), &json!(100));
    }
}
