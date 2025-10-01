use crate::{api::errors::FlagError, flags::flag_request::FlagRequest};
use common_geoip::GeoIpClient;
use serde_json::Value;
use std::{collections::HashMap, net::IpAddr};

use super::types::{RequestContext, RequestPropertyOverrides};

pub fn prepare_overrides(
    context: &RequestContext,
    request: &FlagRequest,
) -> Result<RequestPropertyOverrides, FlagError> {
    let geoip_disabled = request.geoip_disable.unwrap_or(false);
    let person_property_overrides = get_person_property_overrides(
        geoip_disabled,
        request.person_properties.clone(),
        &context.ip,
        &context.state.geoip,
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

pub fn get_person_property_overrides(
    geoip_disabled: bool,
    person_properties: Option<HashMap<String, Value>>,
    ip: &IpAddr,
    geoip_service: &GeoIpClient,
) -> Option<HashMap<String, Value>> {
    match (!geoip_disabled, person_properties) {
        (true, Some(mut props)) => {
            if let Some(geoip_props) = geoip_service.get_geoip_properties(&ip.to_string()) {
                props.extend(geoip_props.into_iter().map(|(k, v)| (k, Value::String(v))));
            }
            Some(props)
        }
        (true, None) => {
            if let Some(geoip_props) = geoip_service.get_geoip_properties(&ip.to_string()) {
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
            } else {
                None
            }
        }
        (false, Some(props)) => Some(props),
        (false, None) => None,
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
    use crate::flags::flag_request::FlagRequest;
    use serde_json::json;

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
}
