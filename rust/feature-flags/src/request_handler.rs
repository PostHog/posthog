use crate::{
    api::{FlagError, FlagValue, FlagsResponse},
    database::Client,
    flag_definitions::FeatureFlagList,
    flag_matching::FeatureFlagMatcher,
    flag_request::FlagRequest,
    geoip::GeoIpService,
    router,
};
use axum::{extract::State, http::HeaderMap};
use bytes::Bytes;
use serde::Deserialize;
use serde_json::Value;
use std::sync::Arc;
use std::{collections::HashMap, net::IpAddr};
use tracing::error;

#[derive(Deserialize, Default)]
pub enum Compression {
    #[default]
    Unsupported,
    #[serde(rename = "gzip", alias = "gzip-js")]
    Gzip,
}

impl Compression {
    pub fn as_str(&self) -> &'static str {
        match self {
            Compression::Gzip => "gzip",
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
        .extract_and_verify_token(state.redis.clone(), state.postgres.clone())
        .await?;
    let team = request
        .get_team_from_cache_or_pg(&token, state.redis.clone(), state.postgres.clone())
        .await?;
    let distinct_id = request.extract_distinct_id()?;
    let person_property_overrides = get_person_property_overrides(
        !request.geoip_disable.unwrap_or(false),
        request.person_properties.clone(),
        &ip,
        &state.geoip,
    );
    let group_property_overrides = request.group_properties.clone();

    let feature_flags_from_cache_or_pg = request
        .get_flags_from_cache_or_pg(team.id, state.redis.clone(), state.postgres.clone())
        .await?;

    let flags_response = evaluate_feature_flags(
        distinct_id,
        feature_flags_from_cache_or_pg,
        Some(state.postgres.clone()),
        person_property_overrides,
        group_property_overrides,
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
    geoip_service: &GeoIpService,
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
    match headers
        .get("content-type")
        .map_or("", |v| v.to_str().unwrap_or(""))
    {
        "application/json" => FlagRequest::from_bytes(body),
        ct => Err(FlagError::RequestDecodingError(format!(
            "unsupported content type: {}",
            ct
        ))),
    }
}

/// Evaluate feature flags for a given distinct_id
/// - Returns a map of feature flag keys to their values
/// - If an error occurs while evaluating a flag, it will be logged and the flag will be omitted from the result
pub async fn evaluate_feature_flags(
    distinct_id: String,
    feature_flags_from_cache_or_pg: FeatureFlagList,
    database_client: Option<Arc<dyn Client + Send + Sync>>,
    person_property_overrides: Option<HashMap<String, Value>>,
    group_property_overrides: Option<HashMap<String, HashMap<String, Value>>>,
) -> FlagsResponse {
    let mut matcher = FeatureFlagMatcher::new(
        distinct_id.clone(),
        database_client,
        person_property_overrides,
        group_property_overrides,
    );
    let mut feature_flags = HashMap::new();
    let mut error_while_computing_flags = false;
    let feature_flag_list = feature_flags_from_cache_or_pg.flags;

    for flag in feature_flag_list {
        if !flag.active || flag.deleted {
            continue;
        }

        match matcher.get_match(&flag).await {
            Ok(flag_match) => {
                let flag_value = if flag_match.matches {
                    match flag_match.variant {
                        Some(variant) => FlagValue::String(variant),
                        None => FlagValue::Boolean(true),
                    }
                } else {
                    FlagValue::Boolean(false)
                };
                feature_flags.insert(flag.key.clone(), flag_value);
            }
            Err(e) => {
                error_while_computing_flags = true;
                error!(
                    "Error evaluating feature flag '{}' for distinct_id '{}': {:?}",
                    flag.key, distinct_id, e
                );
            }
        }
    }

    FlagsResponse {
        error_while_computing_flags,
        feature_flags,
    }
}

#[cfg(test)]
mod tests {
    use crate::{
        config::Config,
        flag_definitions::{FeatureFlag, FlagFilters, FlagGroupType, OperatorType, PropertyFilter},
        test_utils::setup_pg_client,
    };

    use super::*;
    use axum::http::HeaderMap;
    use serde_json::json;
    use std::net::Ipv4Addr;

    fn create_test_geoip_service() -> GeoIpService {
        let config = Config::default_test_config();
        GeoIpService::new(&config).expect("Failed to create GeoIpService for testing")
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
        let pg_client = setup_pg_client(None).await;
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
            "user123".to_string(),
            feature_flag_list,
            Some(pg_client),
            Some(person_properties),
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
    fn test_compression_as_str() {
        assert_eq!(Compression::Gzip.as_str(), "gzip");
        assert_eq!(Compression::Unsupported.as_str(), "unsupported");
    }
}
