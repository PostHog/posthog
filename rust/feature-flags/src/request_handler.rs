use crate::{
    api::{FlagError, FlagValue, FlagsResponse},
    database::Client,
    flag_definitions::FeatureFlagList,
    flag_matching::FeatureFlagMatcher,
    flag_request::FlagRequest,
    geoip::get_geoip_properties,
    router,
};
use axum::{extract::State, http::HeaderMap};
use bytes::Bytes;
use serde::Deserialize;
use serde_json::Value;
use std::sync::Arc;
use std::{collections::HashMap, net::IpAddr};
use tracing::{error, warn};

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
    let geoip_enabled = request.geoip_disable.unwrap_or(true);
    let person_properties = request.person_properties.clone();

    let person_property_overrides =
        extend_person_properties(person_properties, &ip.to_string(), geoip_enabled);

    // let group_property_overrides = request.group_properties.clone();

    let all_feature_flags = request
        .get_flags_from_cache_or_pg(team.id, state.redis.clone(), state.postgres.clone())
        .await?;

    let flags_response = evaluate_feature_flags(
        distinct_id,
        all_feature_flags,
        Some(state.postgres.clone()),
        person_property_overrides,
        // group_property_overrides,
    )
    .await;

    Ok(flags_response)
}

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

pub fn extend_person_properties(
    person_properties: Option<HashMap<String, Value>>,
    ip: &str,
    geoip_enabled: bool,
) -> Option<HashMap<String, Value>> {
    let mut extended_properties = person_properties;

    if geoip_enabled {
        let geoip_properties: HashMap<String, String> = get_geoip_properties(Some(ip));
        match extended_properties {
            Some(ref mut props) => {
                props.extend(
                    geoip_properties
                        .into_iter()
                        .map(|(k, v)| (k, Value::String(v))),
                );
            }
            None => {
                // Create a new HashMap with Value type
                extended_properties = Some(
                    geoip_properties
                        .into_iter()
                        .map(|(k, v)| (k, Value::String(v)))
                        .collect(),
                );
            }
        }
    }

    extended_properties
}

pub async fn evaluate_feature_flags(
    distinct_id: String,
    feature_flag_list: FeatureFlagList,
    database_client: Option<Arc<dyn Client + Send + Sync>>,
    person_property_overrides: Option<HashMap<String, Value>>,
    // group_property_overrides: Option<HashMap<String, HashMap<String, Value>>>,
) -> FlagsResponse {
    let mut matcher = FeatureFlagMatcher::new(
        distinct_id.clone(),
        database_client,
        person_property_overrides,
        // group_property_overrides,
    );
    let mut feature_flags = HashMap::new();
    let mut error_while_computing_flags = false;
    let all_feature_flags = feature_flag_list.flags;

    for flag in all_feature_flags {
        if !flag.active || flag.deleted {
            continue;
        }

        let flag_match = matcher.get_match(&flag).await;

        let flag_value = if flag_match.matches {
            match flag_match.variant {
                Some(variant) => FlagValue::String(variant),
                None => FlagValue::Boolean(true),
            }
        } else {
            FlagValue::Boolean(false)
        };

        feature_flags.insert(flag.key.clone(), flag_value);

        if let Err(e) = matcher
            .get_person_properties_from_cache_or_db(flag.team_id, distinct_id.clone())
            .await
        {
            error_while_computing_flags = true;
            error!(
                "Error fetching properties for feature flag '{}' and distinct_id '{}': {:?}",
                flag.key, distinct_id, e
            );
        }
    }

    if error_while_computing_flags {
        warn!(
            "Errors occurred while computing feature flags for distinct_id '{}'",
            distinct_id
        );
    }

    FlagsResponse {
        error_while_computing_flags,
        feature_flags,
    }
}

#[cfg(test)]
mod tests {
    use crate::{
        flag_definitions::{FeatureFlag, FlagFilters, FlagGroupType, OperatorType, PropertyFilter},
        test_utils::setup_pg_client,
    };

    use super::*;
    use axum::http::HeaderMap;
    use serde_json::json;

    #[test]
    fn test_extend_person_properties() {
        let mut person_props = HashMap::new();
        person_props.insert("existing_prop".to_string(), json!("value"));

        let extended_props = extend_person_properties(Some(person_props.clone()), "1.1.1.1", false);

        assert!(extended_props.is_some());
        let extended_props = extended_props.unwrap();
        assert!(extended_props.contains_key("existing_prop"));
        // Since geoip is disabled, the length should be exactly 1
        assert_eq!(extended_props.len(), 1);

        // Test with geoip enabled
        let extended_props = extend_person_properties(Some(person_props), "13.106.122.3", true);
        assert!(extended_props.is_some());
        let extended_props = extended_props.unwrap();
        // The length should be greater than 1 if geoip properties were added
        assert!(extended_props.len() > 1);
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
