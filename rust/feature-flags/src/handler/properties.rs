use crate::{api::errors::FlagError, flags::flag_request::FlagRequest};
use common_geoip::GeoIpClient;
use serde_json::Value;
use std::{collections::HashMap, net::IpAddr};

use super::types::{RequestContext, RequestPropertyOverrides};

pub fn prepare_overrides(
    context: &RequestContext,
    request: &FlagRequest,
) -> Result<RequestPropertyOverrides, FlagError> {
    prepare_overrides_inner(&context.ip, &context.state.geoip, request)
}

fn prepare_overrides_inner(
    ip: &IpAddr,
    geoip: &GeoIpClient,
    request: &FlagRequest,
) -> Result<RequestPropertyOverrides, FlagError> {
    let geoip_disabled = request.geoip_disable.unwrap_or(false);
    let person_property_overrides = get_person_property_overrides(
        geoip_disabled,
        request.distinct_id.as_deref(),
        request.person_properties.clone(),
        ip,
        geoip,
    );

    let groups = request.groups.clone();
    let group_property_overrides =
        get_group_property_overrides(groups.clone(), request.group_properties.clone());

    // Determine hash key with precedence: top-level anon_distinct_id > person_properties.$anon_distinct_id
    // Frontend SDKs automatically include anon_distinct_id at the top level.
    // Backend SDKs manually override the anon_distinct_id in person_properties if needed.
    let hash_key_override = request.anon_distinct_id.clone().or_else(|| {
        request
            .person_properties
            .as_ref()
            .and_then(|props| props.get("$anon_distinct_id"))
            .and_then(|v| v.as_str())
            .map(|s| s.to_string())
    });

    Ok(RequestPropertyOverrides {
        person_properties: person_property_overrides,
        group_properties: group_property_overrides,
        groups,
        hash_key: hash_key_override,
    })
}

/// Build merged person-property overrides for a request.
///
/// `distinct_id`, when `Some` and non-empty, is surfaced as a `distinct_id`
/// person property unless `person_properties` already contains one. Mirrors
/// Python local evaluation, which always exposes the request's distinct_id as
/// a person property. Returns `None` when the merged map is empty.
pub fn get_person_property_overrides(
    geoip_disabled: bool,
    distinct_id: Option<&str>,
    person_properties: Option<HashMap<String, Value>>,
    ip: &IpAddr,
    geoip_service: &GeoIpClient,
) -> Option<HashMap<String, Value>> {
    let mut props = person_properties.unwrap_or_default();

    if !geoip_disabled {
        if let Some(geoip_props) = geoip_service.get_geoip_properties(&ip.to_string()) {
            props.extend(geoip_props.into_iter().map(|(k, v)| (k, Value::String(v))));
        }
    }

    // Match Python local evaluation behavior by always exposing the top-level
    // distinct_id as a person property unless person_properties already has one.
    if let Some(distinct_id) = distinct_id.filter(|s| !s.is_empty()) {
        props
            .entry("distinct_id".to_string())
            .or_insert_with(|| Value::String(distinct_id.to_string()));
    }

    if props.is_empty() {
        None
    } else {
        Some(props)
    }
}

pub fn get_group_property_overrides(
    groups: Option<HashMap<String, Value>>,
    existing_overrides: Option<HashMap<String, HashMap<String, Value>>>,
) -> Option<HashMap<String, HashMap<String, Value>>> {
    match groups {
        Some(group_map) => {
            let group_key_overrides: HashMap<String, HashMap<String, Value>> = group_map
                .into_iter()
                .map(|(group_type, group_key)| {
                    let mut merged_props = existing_overrides
                        .as_ref()
                        .and_then(|m| m.get(&group_type))
                        .cloned()
                        .unwrap_or_default();
                    merged_props.insert("$group_key".to_string(), group_key);
                    (group_type, merged_props)
                })
                .collect();

            let mut result = existing_overrides.unwrap_or_default();
            result.extend(group_key_overrides);
            Some(result)
        }
        None => existing_overrides,
    }
}

#[cfg(test)]
mod tests {
    use crate::{config::Config, flags::flag_request::FlagRequest};
    use common_geoip::GeoIpClient;
    use rstest::rstest;
    use serde_json::json;
    use std::{
        collections::HashMap,
        net::{IpAddr, Ipv4Addr},
        sync::OnceLock,
    };

    use super::{get_person_property_overrides, prepare_overrides_inner};

    // Loading the ~60 MB GeoLite2 database on every test would dominate test
    // runtime; share one client across the test binary.
    fn test_geoip() -> &'static GeoIpClient {
        static GEOIP: OnceLock<GeoIpClient> = OnceLock::new();
        GEOIP.get_or_init(|| {
            let config = Config::default_test_config();
            GeoIpClient::new(config.get_maxmind_db_path())
                .expect("Failed to create GeoIpClient for testing")
        })
    }

    // Loopback so the real GeoIP database returns None and tests stay
    // focused on distinct_id/person_property merging behavior.
    const TEST_IP: IpAddr = IpAddr::V4(Ipv4Addr::LOCALHOST);

    #[test]
    fn test_anon_distinct_id_from_top_level() {
        let request = FlagRequest {
            anon_distinct_id: Some("anon123".to_string()),
            person_properties: Some(
                vec![("$anon_distinct_id".to_string(), json!("anon456"))]
                    .into_iter()
                    .collect(),
            ),
            ..Default::default()
        };

        let hash_key = request.anon_distinct_id.clone().or_else(|| {
            request
                .person_properties
                .as_ref()
                .and_then(|props| props.get("$anon_distinct_id"))
                .and_then(|v| v.as_str())
                .map(|s| s.to_string())
        });

        assert_eq!(
            hash_key,
            Some("anon123".to_string()),
            "Top-level anon_distinct_id should take precedence"
        );
    }

    #[test]
    fn test_anon_distinct_id_from_person_properties() {
        let request = FlagRequest {
            anon_distinct_id: None,
            person_properties: Some(
                vec![("$anon_distinct_id".to_string(), json!("anon456"))]
                    .into_iter()
                    .collect(),
            ),
            ..Default::default()
        };

        let hash_key = request.anon_distinct_id.clone().or_else(|| {
            request
                .person_properties
                .as_ref()
                .and_then(|props| props.get("$anon_distinct_id"))
                .and_then(|v| v.as_str())
                .map(|s| s.to_string())
        });

        assert_eq!(
            hash_key,
            Some("anon456".to_string()),
            "Should fallback to person_properties.$anon_distinct_id"
        );
    }

    #[test]
    fn test_anon_distinct_id_not_present() {
        let request = FlagRequest {
            anon_distinct_id: None,
            person_properties: Some(
                vec![("other_property".to_string(), json!("value"))]
                    .into_iter()
                    .collect(),
            ),
            ..Default::default()
        };

        let hash_key = request.anon_distinct_id.clone().or_else(|| {
            request
                .person_properties
                .as_ref()
                .and_then(|props| props.get("$anon_distinct_id"))
                .and_then(|v| v.as_str())
                .map(|s| s.to_string())
        });

        assert_eq!(
            hash_key, None,
            "Should be None when anon_distinct_id not present anywhere"
        );
    }

    #[test]
    fn test_anon_distinct_id_with_non_string_value() {
        let request = FlagRequest {
            anon_distinct_id: None,
            person_properties: Some(
                vec![("$anon_distinct_id".to_string(), json!(123))]
                    .into_iter()
                    .collect(),
            ),
            ..Default::default()
        };

        let hash_key = request.anon_distinct_id.clone().or_else(|| {
            request
                .person_properties
                .as_ref()
                .and_then(|props| props.get("$anon_distinct_id"))
                .and_then(|v| v.as_str())
                .map(|s| s.to_string())
        });

        assert_eq!(
            hash_key, None,
            "Should be None when anon_distinct_id in person_properties is not a string"
        );
    }

    #[test]
    fn test_person_property_overrides_include_top_level_distinct_id() {
        let overrides =
            get_person_property_overrides(true, Some("top_level_id"), None, &TEST_IP, test_geoip())
                .expect("distinct_id should create person overrides");

        assert_eq!(
            overrides.get("distinct_id"),
            Some(&json!("top_level_id")),
            "Top-level distinct_id should be available as a person property override"
        );
    }

    #[test]
    fn test_person_property_overrides_preserve_explicit_distinct_id_override() {
        let overrides = get_person_property_overrides(
            true,
            Some("top_level_id"),
            Some(HashMap::from([(
                "distinct_id".to_string(),
                json!("explicit_override"),
            )])),
            &TEST_IP,
            test_geoip(),
        )
        .expect("person properties should be returned");

        assert_eq!(
            overrides.get("distinct_id"),
            Some(&json!("explicit_override")),
            "Explicit person_properties.distinct_id should win over the top-level field"
        );
    }

    // Pass an unrelated person property so we know the empty-string filter is
    // what skipped the injection, not the empty-map shortcut at the bottom of
    // the function.
    #[test]
    fn test_person_property_overrides_skip_empty_top_level_distinct_id() {
        let overrides = get_person_property_overrides(
            true,
            Some(""),
            Some(HashMap::from([("foo".to_string(), json!("bar"))])),
            &TEST_IP,
            test_geoip(),
        )
        .expect("non-empty person properties should be returned");

        assert_eq!(overrides.get("distinct_id"), None);
        assert_eq!(overrides.get("foo"), Some(&json!("bar")));
    }

    #[rstest]
    #[case::surfaces_top_level(None, "request_only_user")]
    #[case::explicit_in_person_properties_wins(
        Some(HashMap::from([("distinct_id".to_string(), json!("explicit_user"))])),
        "explicit_user"
    )]
    fn test_prepare_overrides_distinct_id_propagation(
        #[case] person_properties: Option<HashMap<String, serde_json::Value>>,
        #[case] expected_distinct_id: &str,
    ) {
        let request = FlagRequest {
            distinct_id: Some("request_only_user".to_string()),
            person_properties,
            geoip_disable: Some(true),
            ..Default::default()
        };

        let overrides = prepare_overrides_inner(&TEST_IP, test_geoip(), &request)
            .expect("prepare_overrides should succeed");

        let person_properties = overrides
            .person_properties
            .expect("person properties should be populated");
        assert_eq!(
            person_properties.get("distinct_id"),
            Some(&json!(expected_distinct_id))
        );
    }
}
