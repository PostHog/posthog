use crate::{
    api::errors::FlagError, flags::flag_request::FlagRequest,
    metrics::consts::GEOIP_PROPERTIES_DIFFER_FROM_LOOKUP_COUNTER,
};
use common_cookieless::COOKIELESS_SENTINEL_VALUE;
use common_geoip::GeoIpClient;
use common_metrics::inc;
use serde_json::Value;
use std::{
    collections::{hash_map::Entry, HashMap},
    net::IpAddr,
};

use super::canonical_log::with_canonical_log;
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

    Ok(RequestPropertyOverrides {
        person_properties: person_property_overrides,
        group_properties: group_property_overrides,
        groups,
        hash_key: get_hash_key_override(request),
    })
}

/// Determines the hash key with precedence: top-level anon_distinct_id > person_properties.$anon_distinct_id
/// Frontend SDKs automatically include anon_distinct_id at the top level.
/// Backend SDKs manually override the anon_distinct_id in person_properties if needed.
///
/// The cookieless sentinel is never a hash key. Every cookieless visitor sends the same
/// sentinel, so using it would give all of them the same variant.
fn get_hash_key_override(request: &FlagRequest) -> Option<String> {
    request
        .anon_distinct_id
        .clone()
        .or_else(|| {
            request
                .person_properties
                .as_ref()
                .and_then(|props| props.get("$anon_distinct_id"))
                .and_then(|v| v.as_str())
                .map(|s| s.to_string())
        })
        .filter(|id| id != COOKIELESS_SENTINEL_VALUE)
}

/// Flags requests that supplied a `$geoip_*` value disagreeing with the lookup. These are the
/// requests where keeping supplied values produces a different evaluation input than letting the
/// lookup win, so the counter sizes the behavior difference between the two precedences.
/// A JSON null counts as absent: it carries no value to compare against the lookup, so it can't
/// be a divergence.
fn record_geoip_divergence(
    person_properties: &HashMap<String, Value>,
    geoip_props: &HashMap<String, String>,
) {
    let diverged = geoip_props.iter().any(|(key, resolved)| {
        person_properties.get(key).is_some_and(|supplied| {
            !supplied.is_null() && supplied.as_str() != Some(resolved.as_str())
        })
    });
    if diverged {
        inc(GEOIP_PROPERTIES_DIFFER_FROM_LOOKUP_COUNTER, &[], 1);
        with_canonical_log(|log| log.geoip_properties_differ_from_lookup = true);
    }
}

/// Builds the person property overrides for a request, filling in GeoIP-derived properties
/// unless GeoIP is disabled.
///
/// GeoIP only fills gaps: a `$geoip_*` key the caller sent explicitly is kept as-is, because the
/// IP we geolocate is whoever the request appears to come from. For a server-side caller that
/// doesn't forward the end user's IP, that's its own server, so a caller that resolved geo itself
/// is the authority for those keys.
pub fn get_person_property_overrides(
    geoip_disabled: bool,
    person_properties: Option<HashMap<String, Value>>,
    ip: &IpAddr,
    geoip_service: &GeoIpClient,
) -> Option<HashMap<String, Value>> {
    if geoip_disabled {
        return person_properties;
    }

    let geoip_props = geoip_service
        .get_geoip_properties(&ip.to_string())
        .unwrap_or_default();
    if geoip_props.is_empty() {
        return person_properties;
    }

    let mut props = person_properties.unwrap_or_default();
    record_geoip_divergence(&props, &geoip_props);
    for (key, value) in geoip_props {
        match props.entry(key) {
            Entry::Vacant(slot) => {
                slot.insert(Value::String(value));
            }
            // A JSON null means the caller had no value rather than that it supplied one.
            // Callers clear a property with `$unset`, so a null here is a gap to fill.
            Entry::Occupied(mut slot) if slot.get().is_null() => {
                slot.insert(Value::String(value));
            }
            Entry::Occupied(_) => {}
        }
    }

    Some(props)
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
    use super::get_hash_key_override;
    use crate::flags::flag_request::FlagRequest;
    use rstest::rstest;
    use serde_json::{json, Value};

    #[rstest]
    #[case::top_level_wins(Some("anon123"), Some(json!("anon456")), Some("anon123"))]
    #[case::falls_back_to_person_properties(None, Some(json!("anon456")), Some("anon456"))]
    #[case::not_present(None, None, None)]
    #[case::non_string_person_property(None, Some(json!(123)), None)]
    #[case::cookieless_sentinel_top_level(Some("$posthog_cookieless"), None, None)]
    #[case::cookieless_sentinel_person_property(None, Some(json!("$posthog_cookieless")), None)]
    #[case::cookieless_sentinel_top_level_with_person_property(
        Some("$posthog_cookieless"),
        Some(json!("anon456")),
        None
    )]
    fn test_hash_key_override(
        #[case] top_level: Option<&str>,
        #[case] person_property: Option<Value>,
        #[case] expected: Option<&str>,
    ) {
        let request = FlagRequest {
            anon_distinct_id: top_level.map(str::to_string),
            person_properties: person_property
                .map(|v| [("$anon_distinct_id".to_string(), v)].into_iter().collect()),
            ..Default::default()
        };

        assert_eq!(
            get_hash_key_override(&request),
            expected.map(str::to_string)
        );
    }
}
