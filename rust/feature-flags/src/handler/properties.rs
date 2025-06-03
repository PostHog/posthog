use crate::{api::errors::FlagError, flags::flag_request::FlagRequest};
use common_geoip::GeoIpClient;
use serde_json::Value;
use std::{collections::HashMap, net::IpAddr};

use super::types::{RequestContext, RequestPropertyOverrides};

pub fn prepare_overrides(
    context: &RequestContext,
    request: &FlagRequest,
) -> Result<RequestPropertyOverrides, FlagError> {
    let geoip_enabled = !request.geoip_disable.unwrap_or(false);
    let person_property_overrides = get_person_property_overrides(
        geoip_enabled,
        request.person_properties.clone(),
        &context.ip,
        &context.state.geoip,
    );

    let groups = request.groups.clone();
    let group_property_overrides =
        get_group_property_overrides(groups.clone(), request.group_properties.clone());

    let hash_key_override = request.anon_distinct_id.clone();

    Ok(RequestPropertyOverrides {
        person_properties: person_property_overrides,
        group_properties: group_property_overrides,
        groups,
        hash_key: hash_key_override,
    })
}

pub fn get_person_property_overrides(
    geoip_enabled: bool,
    person_properties: Option<HashMap<String, Value>>,
    ip: &IpAddr,
    geoip_service: &GeoIpClient,
) -> Option<HashMap<String, Value>> {
    match (geoip_enabled, person_properties) {
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
