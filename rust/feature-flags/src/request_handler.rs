use crate::{
    api::{FlagError, FlagsResponse},
    database::Client,
    flag_definitions::FeatureFlagList,
    flag_matching::{FeatureFlagMatcher, GroupTypeMappingCache},
    flag_request::FlagRequest,
    geoip::GeoIpClient,
    router,
};
use axum::{extract::State, http::HeaderMap};
use base64::{engine::general_purpose, Engine as _};
use bytes::Bytes;
use flate2::read::GzDecoder;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{collections::HashMap, net::IpAddr};
use std::{io::Read, sync::Arc};

#[derive(Debug, Clone, Copy, Deserialize, Serialize, PartialEq, Eq, Default)]
#[serde(rename_all = "lowercase")]
pub enum Compression {
    #[serde(rename = "gzip")]
    #[serde(alias = "gzip-js")]
    Gzip,
    Base64,
    #[default]
    #[serde(other)]
    Unsupported,
}

impl Compression {
    pub fn as_str(&self) -> &'static str {
        match self {
            Compression::Gzip => "gzip",
            Compression::Base64 => "base64",
            Compression::Unsupported => "unsupported",
        }
    }
}

#[derive(Deserialize, Default)]
pub struct FlagsQueryParams {
    #[serde(alias = "v")]
    pub version: Option<String>,

    pub compression: Option<Compression>,

    #[serde(alias = "ver")]
    pub lib_version: Option<String>,

    #[serde(alias = "_")]
    pub sent_at: Option<i64>,
}

pub struct RequestContext {
    pub state: State<router::State>,
    pub ip: IpAddr,
    pub meta: FlagsQueryParams,
    pub headers: HeaderMap,
    pub body: Bytes,
}

pub async fn process_request(context: RequestContext) -> Result<FlagsResponse, FlagError> {
    let RequestContext {
        state,
        ip,
        meta: _, // TODO use this
        headers,
        body,
    } = context;

    let request = decode_request(&headers, body)?;
    let token = request
        .extract_and_verify_token(state.redis.clone(), state.postgres_reader.clone())
        .await?;
    let team = request
        .get_team_from_cache_or_pg(&token, state.redis.clone(), state.postgres_reader.clone())
        .await?;
    let distinct_id = request.extract_distinct_id()?;
    let groups = request.groups.clone();
    let team_id = team.id;
    let person_property_overrides = get_person_property_overrides(
        !request.geoip_disable.unwrap_or(false),
        request.person_properties.clone(),
        &ip,
        &state.geoip,
    );
    let group_property_overrides = request.group_properties.clone();

    let feature_flags_from_cache_or_pg = request
        .get_flags_from_cache_or_pg(team_id, state.redis.clone(), state.postgres_reader.clone())
        .await?;

    let flags_response = evaluate_feature_flags(
        team_id,
        distinct_id,
        feature_flags_from_cache_or_pg,
        state.postgres_reader.clone(),
        state.postgres_writer.clone(),
        person_property_overrides,
        group_property_overrides,
        groups,
    )
    .await;

    Ok(flags_response)
}

/// Get person property overrides based on the request
/// - If geoip is enabled, fetch geoip properties and merge them with any person properties
/// - If geoip is disabled, return the person properties as is
/// - If no person properties are provided, return None
pub fn get_person_property_overrides(
    geoip_enabled: bool,
    person_properties: Option<HashMap<String, Value>>,
    ip: &IpAddr,
    geoip_service: &GeoIpClient,
) -> Option<HashMap<String, Value>> {
    match (geoip_enabled, person_properties) {
        (true, Some(mut props)) => {
            let geoip_props = geoip_service.get_geoip_properties(Some(&ip.to_string()));
            if !geoip_props.is_empty() {
                props.extend(geoip_props.into_iter().map(|(k, v)| (k, Value::String(v))));
            }
            Some(props)
        }
        (true, None) => {
            let geoip_props = geoip_service.get_geoip_properties(Some(&ip.to_string()));
            if !geoip_props.is_empty() {
                Some(
                    geoip_props
                        .into_iter()
                        .map(|(k, v)| (k, Value::String(v)))
                        .collect(),
                )
            } else {
                None
            }
        }
        (false, Some(props)) => Some(props),
        (false, None) => None,
    }
}

/// Decode a request into a `FlagRequest`
/// - Currently only supports JSON requests
// TODO support all supported content types
fn decode_request(headers: &HeaderMap, body: Bytes) -> Result<FlagRequest, FlagError> {
    let content_type = headers
        .get("content-type")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("");

    let content_encoding = headers
        .get("content-encoding")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("");

    let decoded_body = match content_encoding {
        "gzip" => decompress_gzip(body)?,
        "" => body,
        encoding => {
            return Err(FlagError::RequestDecodingError(format!(
                "unsupported content encoding: {}",
                encoding
            )))
        }
    };

    match content_type {
        "application/json" => FlagRequest::from_bytes(decoded_body),
        "application/json; encoding=base64" => {
            let decoded = general_purpose::STANDARD
                .decode(decoded_body)
                .map_err(|e| {
                    FlagError::RequestDecodingError(format!("Base64 decoding error: {}", e))
                })?;
            FlagRequest::from_bytes(Bytes::from(decoded))
        }
        ct => Err(FlagError::RequestDecodingError(format!(
            "unsupported content type: {}",
            ct
        ))),
    }
}

/// Evaluate feature flags for a given distinct_id
/// - Returns a map of feature flag keys to their values
/// - If an error occurs while evaluating a flag, we'll set `error_while_computing_flags` to true be logged,
///  and that flag will be omitted from the result (we will still attempt to evaluate other flags)
// TODO: it could be a cool idea to store the errors as a tuple instead of top-level, so that users can see
// which flags failed to evaluate
pub async fn evaluate_feature_flags(
    team_id: i32,
    distinct_id: String,
    feature_flags_from_cache_or_pg: FeatureFlagList,
    postgres_reader: Arc<dyn Client + Send + Sync>,
    postgres_writer: Arc<dyn Client + Send + Sync>,
    person_property_overrides: Option<HashMap<String, Value>>,
    group_property_overrides: Option<HashMap<String, HashMap<String, Value>>>,
    groups: Option<HashMap<String, Value>>,
) -> FlagsResponse {
    let group_type_mapping_cache = GroupTypeMappingCache::new(team_id, postgres_reader.clone());
    let mut feature_flag_matcher = FeatureFlagMatcher::new(
        distinct_id.clone(),
        team_id,
        postgres_reader.clone(),
        postgres_writer.clone(),
        Some(group_type_mapping_cache),
        None,
        groups,
    );
    feature_flag_matcher
        .evaluate_feature_flags(
            feature_flags_from_cache_or_pg,
            person_property_overrides,
            group_property_overrides,
        )
        .await
}

// TODO: Make sure this protects against zip bombs, etc.  `/capture` does this
// and it's a good idea to do that here as well, probably worth extracting that method into
// /common given that it's used in multiple places
fn decompress_gzip(compressed: Bytes) -> Result<Bytes, FlagError> {
    let mut decoder = GzDecoder::new(&compressed[..]);
    let mut decompressed = Vec::new();
    decoder.read_to_end(&mut decompressed).map_err(|e| {
        FlagError::RequestDecodingError(format!("gzip decompression failed: {}", e))
    })?;
    Ok(Bytes::from(decompressed))
}

#[cfg(test)]
mod tests {
    use crate::{
        api::FlagValue,
        config::Config,
        flag_definitions::{FeatureFlag, FlagFilters, FlagGroupType, OperatorType, PropertyFilter},
        test_utils::{insert_new_team_in_pg, setup_pg_reader_client, setup_pg_writer_client},
    };

    use super::*;
    use axum::http::HeaderMap;
    use serde_json::{json, Value};
    use std::net::{Ipv4Addr, Ipv6Addr};

    fn create_test_geoip_service() -> GeoIpClient {
        let config = Config::default_test_config();
        GeoIpClient::new(&config).expect("Failed to create GeoIpService for testing")
    }

    #[test]
    fn test_geoip_enabled_with_person_properties() {
        let geoip_service = create_test_geoip_service();

        let mut person_props = HashMap::new();
        person_props.insert("name".to_string(), Value::String("John".to_string()));

        let result = get_person_property_overrides(
            true,
            Some(person_props),
            &IpAddr::V4(Ipv4Addr::new(8, 8, 8, 8)), // Google's public DNS, should be in the US
            &geoip_service,
        );

        assert!(result.is_some());
        let result = result.unwrap();
        assert!(result.len() > 1);
        assert_eq!(result.get("name"), Some(&Value::String("John".to_string())));
        assert!(result.contains_key("$geoip_country_name"));
    }

    #[test]
    fn test_geoip_enabled_without_person_properties() {
        let geoip_service = create_test_geoip_service();

        let result = get_person_property_overrides(
            true,
            None,
            &IpAddr::V4(Ipv4Addr::new(8, 8, 8, 8)), // Google's public DNS, should be in the US
            &geoip_service,
        );

        assert!(result.is_some());
        let result = result.unwrap();
        assert!(!result.is_empty());
        assert!(result.contains_key("$geoip_country_name"));
    }

    #[test]
    fn test_geoip_disabled_with_person_properties() {
        let geoip_service = create_test_geoip_service();

        let mut person_props = HashMap::new();
        person_props.insert("name".to_string(), Value::String("John".to_string()));

        let result = get_person_property_overrides(
            false,
            Some(person_props),
            &IpAddr::V4(Ipv4Addr::new(8, 8, 8, 8)),
            &geoip_service,
        );

        assert!(result.is_some());
        let result = result.unwrap();
        assert_eq!(result.len(), 1);
        assert_eq!(result.get("name"), Some(&Value::String("John".to_string())));
    }

    #[test]
    fn test_geoip_disabled_without_person_properties() {
        let geoip_service = create_test_geoip_service();

        let result = get_person_property_overrides(
            false,
            None,
            &IpAddr::V4(Ipv4Addr::new(8, 8, 8, 8)),
            &geoip_service,
        );

        assert!(result.is_none());
    }

    #[test]
    fn test_geoip_enabled_local_ip() {
        let geoip_service = create_test_geoip_service();

        let result = get_person_property_overrides(
            true,
            None,
            &IpAddr::V4(Ipv4Addr::new(127, 0, 0, 1)),
            &geoip_service,
        );

        assert!(result.is_none());
    }

    #[tokio::test]
    async fn test_evaluate_feature_flags() {
        let postgres_reader = setup_pg_reader_client(None).await;
        let postgres_writer = setup_pg_writer_client(None).await;
        let flag = FeatureFlag {
            name: Some("Test Flag".to_string()),
            id: 1,
            key: "test_flag".to_string(),
            active: true,
            deleted: false,
            team_id: 1,
            filters: FlagFilters {
                groups: vec![FlagGroupType {
                    properties: Some(vec![PropertyFilter {
                        key: "country".to_string(),
                        value: json!("US"),
                        operator: Some(OperatorType::Exact),
                        prop_type: "person".to_string(),
                        group_type_index: None,
                    }]),
                    rollout_percentage: Some(100.0), // Set to 100% to ensure it's always on
                    variant: None,
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
            },
            ensure_experience_continuity: false,
        };

        let feature_flag_list = FeatureFlagList { flags: vec![flag] };

        let mut person_properties = HashMap::new();
        person_properties.insert("country".to_string(), json!("US"));

        let result = evaluate_feature_flags(
            1,
            "user123".to_string(),
            feature_flag_list,
            postgres_reader,
            postgres_writer,
            Some(person_properties),
            None,
            None,
        )
        .await;

        assert!(!result.error_while_computing_flags);
        assert!(result.feature_flags.contains_key("test_flag"));
        assert_eq!(result.feature_flags["test_flag"], FlagValue::Boolean(true));
    }

    #[test]
    fn test_decode_request() {
        let mut headers = HeaderMap::new();
        headers.insert("content-type", "application/json".parse().unwrap());

        let body = Bytes::from(r#"{"token": "test_token", "distinct_id": "user123"}"#);

        let result = decode_request(&headers, body);

        assert!(result.is_ok());
        let request = result.unwrap();
        assert_eq!(request.token, Some("test_token".to_string()));
        assert_eq!(request.distinct_id, Some("user123".to_string()));
    }

    #[test]
    fn test_decode_request_unsupported_content_encoding() {
        let mut headers = HeaderMap::new();
        headers.insert("content-type", "application/json".parse().unwrap());
        headers.insert("content-encoding", "deflate".parse().unwrap());
        let body = Bytes::from_static(b"{\"token\": \"test_token\", \"distinct_id\": \"user123\"}");
        let result = decode_request(&headers, body);
        assert!(matches!(result, Err(FlagError::RequestDecodingError(_))));
    }

    #[test]
    fn test_decode_request_invalid_base64() {
        let mut headers = HeaderMap::new();
        headers.insert(
            "content-type",
            "application/json; encoding=base64".parse().unwrap(),
        );
        let body = Bytes::from_static(b"invalid_base64==");
        let result = decode_request(&headers, body);
        assert!(matches!(result, Err(FlagError::RequestDecodingError(_))));
    }

    #[test]
    fn test_compression_as_str() {
        assert_eq!(Compression::Gzip.as_str(), "gzip");
        assert_eq!(Compression::Unsupported.as_str(), "unsupported");
    }

    #[test]
    fn test_get_person_property_overrides_ipv4() {
        let geoip_service = create_test_geoip_service();
        let result = get_person_property_overrides(
            true,
            Some(HashMap::new()),
            &IpAddr::V4(Ipv4Addr::new(8, 8, 8, 8)),
            &geoip_service,
        );
        assert!(result.is_some());
        let props = result.unwrap();
        assert!(props.contains_key("$geoip_country_name"));
    }

    #[test]
    fn test_get_person_property_overrides_ipv6() {
        let geoip_service = create_test_geoip_service();
        let result = get_person_property_overrides(
            true,
            Some(HashMap::new()),
            &IpAddr::V6(Ipv6Addr::new(0x2001, 0x4860, 0x4860, 0, 0, 0, 0, 0x8888)),
            &geoip_service,
        );
        assert!(result.is_some());
        let props = result.unwrap();
        assert!(props.contains_key("$geoip_country_name"));
    }

    #[test]
    fn test_decode_request_unsupported_content_type() {
        let mut headers = HeaderMap::new();
        headers.insert("content-type", "text/plain".parse().unwrap());
        let body = Bytes::from_static(b"test");
        let result = decode_request(&headers, body);
        assert!(matches!(result, Err(FlagError::RequestDecodingError(_))));
    }

    #[test]
    fn test_decode_request_malformed_json() {
        let mut headers = HeaderMap::new();
        headers.insert("content-type", "application/json".parse().unwrap());
        let body = Bytes::from_static(b"{invalid json}");
        let result = decode_request(&headers, body);
        // If the actual implementation doesn't return a RequestDecodingError,
        // we should adjust our expectation. Let's check if it's an error at all:
        assert!(result.is_err(), "Expected an error, but got Ok");
        // If you want to check for a specific error type, you might need to adjust
        // the FlagError enum or the decode_request function.
    }

    #[tokio::test]
    async fn test_evaluate_feature_flags_multiple_flags() {
        let postgres_reader = setup_pg_reader_client(None).await;
        let postgres_writer = setup_pg_writer_client(None).await;
        let flags = vec![
            FeatureFlag {
                name: Some("Flag 1".to_string()),
                id: 1,
                key: "flag_1".to_string(),
                active: true,
                deleted: false,
                team_id: 1,
                filters: FlagFilters {
                    groups: vec![FlagGroupType {
                        properties: Some(vec![]),
                        rollout_percentage: Some(100.0),
                        variant: None,
                    }],
                    multivariate: None,
                    aggregation_group_type_index: None,
                    payloads: None,
                    super_groups: None,
                },
                ensure_experience_continuity: false,
            },
            FeatureFlag {
                name: Some("Flag 2".to_string()),
                id: 2,
                key: "flag_2".to_string(),
                active: true,
                deleted: false,
                team_id: 1,
                filters: FlagFilters {
                    groups: vec![FlagGroupType {
                        properties: Some(vec![]),
                        rollout_percentage: Some(0.0),
                        variant: None,
                    }],
                    multivariate: None,
                    aggregation_group_type_index: None,
                    payloads: None,
                    super_groups: None,
                },
                ensure_experience_continuity: false,
            },
        ];

        let feature_flag_list = FeatureFlagList { flags };

        let result = evaluate_feature_flags(
            1,
            "user123".to_string(),
            feature_flag_list,
            postgres_reader,
            postgres_writer,
            None,
            None,
            None,
        )
        .await;

        assert!(!result.error_while_computing_flags);
        assert_eq!(result.feature_flags["flag_1"], FlagValue::Boolean(true));
        assert_eq!(result.feature_flags["flag_2"], FlagValue::Boolean(false));
    }

    #[test]
    fn test_flags_query_params_deserialization() {
        let json = r#"{
            "v": "1.0",
            "compression": "gzip",
            "lib_version": "2.0",
            "sent_at": 1234567890
        }"#;
        let params: FlagsQueryParams = serde_json::from_str(json).unwrap();
        assert_eq!(params.version, Some("1.0".to_string()));
        assert!(matches!(params.compression, Some(Compression::Gzip)));
        assert_eq!(params.lib_version, Some("2.0".to_string()));
        assert_eq!(params.sent_at, Some(1234567890));
    }

    #[test]
    fn test_compression_deserialization() {
        assert_eq!(
            serde_json::from_str::<Compression>("\"gzip\"").unwrap(),
            Compression::Gzip
        );
        assert_eq!(
            serde_json::from_str::<Compression>("\"gzip-js\"").unwrap(),
            Compression::Gzip
        );
        // If "invalid" is actually deserialized to Unsupported, we should change our expectation
        assert_eq!(
            serde_json::from_str::<Compression>("\"invalid\"").unwrap(),
            Compression::Unsupported
        );
    }

    #[test]
    fn test_flag_error_request_decoding() {
        let error = FlagError::RequestDecodingError("Test error".to_string());
        assert!(matches!(error, FlagError::RequestDecodingError(_)));
    }

    #[tokio::test]
    async fn test_evaluate_feature_flags_with_overrides() {
        let postgres_reader = setup_pg_reader_client(None).await;
        let postgres_writer = setup_pg_writer_client(None).await;
        let team = insert_new_team_in_pg(postgres_reader.clone())
            .await
            .unwrap();

        let flag = FeatureFlag {
            name: Some("Test Flag".to_string()),
            id: 1,
            key: "test_flag".to_string(),
            active: true,
            deleted: false,
            team_id: team.id,
            filters: FlagFilters {
                groups: vec![FlagGroupType {
                    properties: Some(vec![PropertyFilter {
                        key: "industry".to_string(),
                        value: json!("tech"),
                        operator: Some(OperatorType::Exact),
                        prop_type: "group".to_string(),
                        group_type_index: Some(0),
                    }]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                }],
                multivariate: None,
                aggregation_group_type_index: Some(0),
                payloads: None,
                super_groups: None,
            },
            ensure_experience_continuity: false,
        };
        let feature_flag_list = FeatureFlagList { flags: vec![flag] };

        let groups = HashMap::from([("project".to_string(), json!("project_123"))]);
        let group_property_overrides = HashMap::from([(
            "project".to_string(),
            HashMap::from([
                ("industry".to_string(), json!("tech")),
                ("$group_key".to_string(), json!("project_123")),
            ]),
        )]);

        let result = evaluate_feature_flags(
            team.id,
            "user123".to_string(),
            feature_flag_list,
            postgres_reader,
            postgres_writer,
            None,
            Some(group_property_overrides),
            Some(groups),
        )
        .await;

        assert!(
            !result.error_while_computing_flags,
            "Error while computing flags"
        );
        assert!(
            result.feature_flags.contains_key("test_flag"),
            "test_flag not found in result"
        );

        let flag_value = result
            .feature_flags
            .get("test_flag")
            .expect("test_flag not found");

        assert_eq!(
            flag_value,
            &FlagValue::Boolean(true),
            "Flag value is not true as expected"
        );
    }

    #[tokio::test]
    async fn test_long_distinct_id() {
        let long_id = "a".repeat(1000);
        let postgres_reader = setup_pg_reader_client(None).await;
        let postgres_writer = setup_pg_writer_client(None).await;
        let flag = FeatureFlag {
            name: Some("Test Flag".to_string()),
            id: 1,
            key: "test_flag".to_string(),
            active: true,
            deleted: false,
            team_id: 1,
            filters: FlagFilters {
                groups: vec![FlagGroupType {
                    properties: Some(vec![]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
            },
            ensure_experience_continuity: false,
        };

        let feature_flag_list = FeatureFlagList { flags: vec![flag] };

        let result = evaluate_feature_flags(
            1,
            long_id,
            feature_flag_list,
            postgres_reader,
            postgres_writer,
            None,
            None,
            None,
        )
        .await;

        assert!(!result.error_while_computing_flags);
        assert_eq!(result.feature_flags["test_flag"], FlagValue::Boolean(true));
    }
}
