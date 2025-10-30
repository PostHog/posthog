use std::collections::HashMap;

use anyhow::Error;
use chrono::Utc;
use common_types::{CapturedEvent, InternallyCapturedEvent, RawEvent};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use tracing::error;
use uuid::Uuid;

use super::TransformContext;
use crate::cache::{group_cache::GroupChanges, GroupCache};

mod identify;

/// Represents a group that has changed properties
#[derive(Debug, Clone)]
pub struct ChangedGroup {
    pub group_type: String,
    pub group_key: String,
    pub changes: GroupChanges,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct AmplitudeData {
    pub path: Option<String>,
    #[serde(
        default,
        deserialize_with = "crate::parse::serialization::deserialize_flexible_bool"
    )]
    pub user_properties_updated: bool,
    #[serde(rename = "group_first_event", default)]
    pub group_first_event: HashMap<String, Value>,
    #[serde(rename = "group_ids", default)]
    pub group_ids: HashMap<String, Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct AmplitudeEvent {
    #[serde(rename = "$insert_id")]
    pub insert_id: Option<String>,
    #[serde(rename = "$insert_key")]
    pub insert_key: Option<String>,
    #[serde(rename = "$schema")]
    pub schema: Option<String>,
    pub adid: Option<String>,
    pub amplitude_attribution_ids: Option<Value>,
    pub amplitude_event_type: Option<String>,
    #[serde(default)]
    pub amplitude_id: i64,
    #[serde(default)]
    pub app: i64,
    pub city: Option<String>,
    pub client_event_time: Option<String>,
    pub client_upload_time: Option<String>,
    pub country: Option<String>,
    #[serde(default)]
    pub data: AmplitudeData,
    pub data_type: Option<String>,
    pub device_brand: Option<String>,
    pub device_carrier: Option<String>,
    pub device_family: Option<String>,
    pub device_id: Option<String>,
    pub device_manufacturer: Option<String>,
    pub device_model: Option<String>,
    pub device_type: Option<String>,
    pub dma: Option<String>,
    #[serde(default)]
    pub event_id: i64,
    #[serde(default)]
    pub event_properties: HashMap<String, Value>,
    pub event_time: Option<String>,
    pub event_type: Option<String>,
    pub global_user_properties: Option<Value>,
    #[serde(default)]
    pub group_properties: HashMap<String, HashMap<String, HashMap<String, Value>>>,
    #[serde(default)]
    pub groups: HashMap<String, Vec<String>>,
    pub idfa: Option<String>,
    pub ip_address: Option<String>,
    #[serde(
        default,
        deserialize_with = "crate::parse::serialization::deserialize_flexible_option_bool"
    )]
    pub is_attribution_event: Option<bool>,
    pub language: Option<String>,
    pub library: Option<String>,
    pub location_lat: Option<f64>,
    pub location_lng: Option<f64>,
    pub os_name: Option<String>,
    pub os_version: Option<String>,
    pub partner_id: Option<String>,
    #[serde(
        default,
        deserialize_with = "crate::parse::serialization::deserialize_flexible_option_bool"
    )]
    pub paying: Option<bool>,
    #[serde(default)]
    pub plan: HashMap<String, Value>,
    pub platform: Option<String>,
    pub processed_time: Option<String>,
    pub region: Option<String>,
    pub sample_rate: Option<f64>,
    pub server_received_time: Option<String>,
    pub server_upload_time: Option<String>,
    #[serde(default)]
    pub session_id: i64,
    pub source_id: Option<String>,
    pub start_version: Option<String>,
    pub user_creation_time: Option<String>,
    pub user_id: Option<String>,
    #[serde(default)]
    pub user_properties: HashMap<String, Value>,
    pub uuid: Option<String>,
    pub version_name: Option<String>,
}

/// Detect which groups have changed properties since last seen
fn detect_group_changes(
    team_id: i32,
    groups: &HashMap<String, Vec<String>>,
    group_properties: &HashMap<String, HashMap<String, HashMap<String, Value>>>,
    group_cache: &dyn GroupCache,
) -> Result<Vec<ChangedGroup>, Error> {
    let mut changed_groups = Vec::new();

    // Iterate through each group type in the groups field
    for (group_type, group_keys) in groups {
        // For each group key of this type
        for group_key in group_keys {
            // Check if we have properties for this group type and key
            let properties = group_properties
                .get(group_type)
                .and_then(|type_props| type_props.get(group_key))
                .cloned()
                .unwrap_or_default();

            // Check if properties have changed
            if let Some(changes) =
                group_cache.get_group_changes(team_id, group_type, group_key, &properties)
            {
                changed_groups.push(ChangedGroup {
                    group_type: group_type.clone(),
                    group_key: group_key.clone(),
                    changes,
                });

                // Mark as seen with current properties
                group_cache.mark_group_seen(team_id, group_type, group_key, &properties)?;
            }
        }
    }

    Ok(changed_groups)
}

/// Create a PostHog group identify event
fn create_group_identify_event(
    context: &TransformContext,
    distinct_id: String,
    group_type: String,
    group_key: String,
    changes: GroupChanges,
    timestamp: chrono::DateTime<chrono::Utc>,
) -> Result<InternallyCapturedEvent, Error> {
    let event_uuid = Uuid::now_v7();

    let mut properties = serde_json::Map::new();
    properties.insert("$group_type".to_string(), Value::String(group_type));
    properties.insert("$group_key".to_string(), Value::String(group_key.clone()));

    // Add properties to set (always include, even if empty)
    properties.insert(
        "$group_set".to_string(),
        Value::Object(changes.set.into_iter().collect()),
    );

    // Add properties to unset (if any)
    if !changes.unset.is_empty() {
        properties.insert(
            "$group_unset".to_string(),
            Value::Array(changes.unset.into_iter().map(Value::String).collect()),
        );
    }

    // Mark this as a historical migration event
    properties.insert("historical_migration".to_string(), Value::Bool(true));
    properties.insert(
        "analytics_source".to_string(),
        Value::String("amplitude".to_string()),
    );
    properties.insert(
        "$import_job_id".to_string(),
        Value::String(context.job_id.to_string()),
    );

    let raw_event = RawEvent {
        event: "$groupidentify".to_string(),
        properties: properties.into_iter().collect(),
        timestamp: Some(timestamp.to_rfc3339()),
        distinct_id: Some(Value::String(distinct_id.clone())),
        uuid: Some(event_uuid),
        token: Some(context.token.clone()),
        offset: None,
        set: None,
        set_once: None,
    };

    let captured_event = CapturedEvent {
        uuid: event_uuid,
        distinct_id,
        ip: "".to_string(),
        data: serde_json::to_string(&raw_event)?,
        now: timestamp.format("%Y-%m-%d %H:%M:%S%.3f").to_string(),
        sent_at: None,
        token: context.token.clone(),
        event: "$groupidentify".to_string(),
        timestamp,
        is_cookieless_mode: false,
        historical_migration: true,
    };

    Ok(InternallyCapturedEvent {
        team_id: context.team_id,
        inner: captured_event,
    })
}

/// Add groups to event properties
fn add_groups_to_properties(
    properties: &mut HashMap<String, Value>,
    groups: &HashMap<String, Vec<String>>,
) {
    // Create the $groups object with raw group types (no index mapping)
    let mut groups_object = serde_json::Map::new();

    for (group_type, group_values) in groups {
        if let Some(first_value) = group_values.first() {
            groups_object.insert(group_type.clone(), Value::String(first_value.clone()));
        }
    }

    if !groups_object.is_empty() {
        properties.insert("$groups".to_string(), Value::Object(groups_object));
    }
}

impl AmplitudeEvent {
    pub fn parse_fn(
        context: TransformContext,
        event_transform: impl Fn(RawEvent) -> Result<Option<RawEvent>, Error>,
    ) -> impl Fn(Self) -> Result<Vec<InternallyCapturedEvent>, Error> {
        move |amp| {
            let token = context.token.clone();
            let team_id = context.team_id;

            let Some(event_type_raw) = &amp.event_type else {
                return Ok(vec![]);
            };

            let event_type = match event_type_raw.as_str() {
                "session_start" => return Ok(vec![]),
                "[Amplitude] Page Viewed" => "$pageview".to_string(),
                "[Amplitude] Element Clicked" | "[Amplitude] Element Changed" => {
                    "$autocapture".to_string()
                }
                _ => event_type_raw.clone(),
            };

            let distinct_id = get_distinct_id(&amp);

            let event_uuid = amp
                .uuid
                .as_ref()
                .and_then(|u| Uuid::parse_str(u).ok())
                .unwrap_or_else(Uuid::now_v7);

            let timestamp = parse_timestamp(&amp)?;

            let mut properties = amp.event_properties.clone();

            let device_type = match amp.device_type.as_deref() {
                Some("Windows") | Some("Linux") => Some("Desktop"),
                Some("iOS") | Some("Android") => Some("Mobile"),
                _ => None,
            };

            if let Some(user_id) = &amp.user_id {
                properties.insert(
                    "$amplitude_user_id".to_string(),
                    Value::String(user_id.clone()),
                );
            }
            if let Some(device_id) = &amp.device_id {
                properties.insert(
                    "$amplitude_device_id".to_string(),
                    Value::String(device_id.clone()),
                );
                properties.insert("$device_id".to_string(), Value::String(device_id.clone()));
            }
            if amp.event_id != 0 {
                properties.insert(
                    "$amplitude_event_id".to_string(),
                    Value::Number(amp.event_id.into()),
                );
            }
            if amp.session_id != 0 {
                properties.insert(
                    "$amplitude_session_id".to_string(),
                    Value::Number(amp.session_id.into()),
                );
            }

            if let Some(country) = &amp.country {
                properties.insert(
                    "$geoip_country_name".to_string(),
                    Value::String(country.clone()),
                );
            }
            if let Some(city) = &amp.city {
                properties.insert("$geoip_city_name".to_string(), Value::String(city.clone()));
            }
            if let Some(region) = &amp.region {
                properties.insert(
                    "$geoip_subdivision_1_name".to_string(),
                    Value::String(region.clone()),
                );
            }

            if let Some(os_name) = &amp.os_name {
                properties.insert("$browser".to_string(), Value::String(os_name.clone()));
            }
            if let Some(device_type_val) = &amp.device_type {
                properties.insert("$os".to_string(), Value::String(device_type_val.clone()));
            }
            if let Some(os_version) = &amp.os_version {
                if let Ok(version_int) = os_version.parse::<i64>() {
                    properties.insert(
                        "$browser_version".to_string(),
                        Value::Number(version_int.into()),
                    );
                } else {
                    properties.insert(
                        "$browser_version".to_string(),
                        Value::String(os_version.clone()),
                    );
                }
            }
            if let Some(dt) = device_type {
                properties.insert("$device_type".to_string(), Value::String(dt.to_string()));
            }

            if let Some(ip) = &amp.ip_address {
                properties.insert("$ip".to_string(), Value::String(ip.clone()));
            }

            if let Some(page_url) = amp.event_properties.get("[Amplitude] Page URL") {
                properties.insert("$current_url".to_string(), page_url.clone());
            }
            if let Some(page_domain) = amp.event_properties.get("[Amplitude] Page Domain") {
                properties.insert("$host".to_string(), page_domain.clone());
            }
            if let Some(page_path) = amp.event_properties.get("[Amplitude] Page Path") {
                properties.insert("$pathname".to_string(), page_path.clone());
            }
            if let Some(viewport_height) = amp.event_properties.get("[Amplitude] Viewport Height") {
                properties.insert("$viewport_height".to_string(), viewport_height.clone());
            }
            if let Some(viewport_width) = amp.event_properties.get("[Amplitude] Viewport Width") {
                properties.insert("$viewport_width".to_string(), viewport_width.clone());
            }
            if let Some(referrer) = amp.event_properties.get("referrer") {
                properties.insert("$referrer".to_string(), referrer.clone());
            }
            if let Some(referring_domain) = amp.event_properties.get("referring_domain") {
                properties.insert("$referring_domain".to_string(), referring_domain.clone());
            }

            let mut set_once = HashMap::new();

            let handle_empty_value = |val: Option<&Value>| -> Option<Value> {
                match val {
                    Some(Value::String(s)) if s == "EMPTY" => None,
                    Some(v) => Some(v.clone()),
                    None => None,
                }
            };

            if let Some(initial_referrer) =
                handle_empty_value(amp.user_properties.get("initial_referrer"))
            {
                set_once.insert("$initial_referrer".to_string(), initial_referrer);
            }
            if let Some(initial_referring_domain) =
                handle_empty_value(amp.user_properties.get("initial_referring_domain"))
            {
                set_once.insert(
                    "$initial_referring_domain".to_string(),
                    initial_referring_domain,
                );
            }
            if let Some(initial_utm_source) =
                handle_empty_value(amp.user_properties.get("initial_utm_source"))
            {
                set_once.insert("$initial_utm_source".to_string(), initial_utm_source);
            }
            if let Some(initial_utm_medium) =
                handle_empty_value(amp.user_properties.get("initial_utm_medium"))
            {
                set_once.insert("$initial_utm_medium".to_string(), initial_utm_medium);
            }
            if let Some(initial_utm_campaign) =
                handle_empty_value(amp.user_properties.get("initial_utm_campaign"))
            {
                set_once.insert("$initial_utm_campaign".to_string(), initial_utm_campaign);
            }
            if let Some(initial_utm_content) =
                handle_empty_value(amp.user_properties.get("initial_utm_content"))
            {
                set_once.insert("$initial_utm_content".to_string(), initial_utm_content);
            }

            let mut set = HashMap::new();
            // Add user properties to set
            if let Some(device_type_val) = &amp.device_type {
                set.insert("$os".to_string(), Value::String(device_type_val.clone()));
            }
            if let Some(os_name) = &amp.os_name {
                set.insert("$browser".to_string(), Value::String(os_name.clone()));
            }
            if let Some(dt) = device_type {
                set.insert("$device_type".to_string(), Value::String(dt.to_string()));
            }
            if let Some(page_url) = amp.event_properties.get("[Amplitude] Page URL") {
                set.insert("$current_url".to_string(), page_url.clone());
            }
            if let Some(page_path) = amp.event_properties.get("[Amplitude] Page Path") {
                set.insert("$pathname".to_string(), page_path.clone());
            }
            if let Some(os_version) = &amp.os_version {
                set.insert(
                    "$browser_version".to_string(),
                    Value::String(os_version.clone()),
                );
            }
            if let Some(referrer) = amp.event_properties.get("referrer") {
                set.insert("$referrer".to_string(), referrer.clone());
            }
            if let Some(referring_domain) = amp.event_properties.get("referring_domain") {
                set.insert("$referring_domain".to_string(), referring_domain.clone());
            }
            if let Some(city) = &amp.city {
                set.insert("$geoip_city_name".to_string(), Value::String(city.clone()));
            }
            if let Some(region) = &amp.region {
                set.insert(
                    "$geoip_subdivision_1_name".to_string(),
                    Value::String(region.clone()),
                );
            }
            if let Some(country) = &amp.country {
                set.insert(
                    "$geoip_country_name".to_string(),
                    Value::String(country.clone()),
                );
            }

            properties.insert("historical_migration".to_string(), Value::Bool(true));
            properties.insert(
                "analytics_source".to_string(),
                Value::String("amplitude".to_string()),
            );
            properties.insert(
                "$import_job_id".to_string(),
                Value::String(context.job_id.to_string()),
            );

            // Add groups to the regular event properties BEFORE creating RawEvent
            if !amp.groups.is_empty() {
                add_groups_to_properties(&mut properties, &amp.groups);
            }

            let raw_event = RawEvent {
                token: Some(token.clone()),
                distinct_id: Some(Value::String(distinct_id.clone())),
                uuid: Some(event_uuid),
                event: event_type,
                properties: properties.clone(),
                timestamp: Some(timestamp.to_rfc3339()),
                set: if set.is_empty() { None } else { Some(set) },
                set_once: if set_once.is_empty() {
                    None
                } else {
                    Some(set_once)
                },
                offset: None,
            };

            let Some(raw_event) = event_transform(raw_event)? else {
                return Ok(vec![]);
            };

            let mut events = Vec::new();

            // Check if we need to inject an $identify event
            if context.generate_identify_events {
                if let (Some(user_id), Some(device_id)) = (&amp.user_id, &amp.device_id) {
                    // Check cache to see if we've seen this user-device combination
                    let cache_result = context
                        .identify_cache
                        .has_seen_user_device(team_id, user_id, device_id);

                    match cache_result {
                        Ok(has_seen) => {
                            if !has_seen {
                                // Create and inject $identify event
                                let identify_uuid = Uuid::now_v7();
                                let identify_event = identify::create_identify_event(
                                    team_id,
                                    &token,
                                    user_id,
                                    device_id,
                                    identify_uuid,
                                    timestamp,
                                )?;

                                events.push(identify_event);

                                // Mark as seen in cache
                                let mark_result = context
                                    .identify_cache
                                    .mark_seen_user_device(team_id, user_id, device_id);

                                if let Err(e) = mark_result {
                                    error!("Failed to mark seen in identify cache for team {} user {} device {}: {}", team_id, user_id, device_id, e);
                                }
                            }
                        }
                        Err(e) => {
                            error!(
                                "Failed to check identify cache for team {} user {} device {}: {}",
                                team_id, user_id, device_id, e
                            );
                        }
                    }
                }
            }

            // Process group identify events if enabled
            if context.generate_group_identify_events
                && (!amp.groups.is_empty() || !amp.group_properties.is_empty())
            {
                match detect_group_changes(
                    team_id,
                    &amp.groups,
                    &amp.group_properties,
                    context.group_cache.as_ref(),
                ) {
                    Ok(changed_groups) => {
                        for changed_group in changed_groups {
                            match create_group_identify_event(
                                &context,
                                distinct_id.clone(),
                                changed_group.group_type,
                                changed_group.group_key,
                                changed_group.changes,
                                timestamp,
                            ) {
                                Ok(group_event) => {
                                    events.push(group_event);
                                }
                                Err(e) => {
                                    error!("Failed to create group identify event: {}", e);
                                }
                            }
                        }
                    }
                    Err(e) => {
                        error!("Failed to detect group changes: {}", e);
                    }
                }
            }

            // Only add the original event if import_events is enabled
            if context.import_events {
                let inner = CapturedEvent {
                    uuid: event_uuid,
                    distinct_id,
                    ip: amp.ip_address.unwrap_or_else(|| "127.0.0.1".to_string()),
                    data: serde_json::to_string(&raw_event)?,
                    now: Utc::now().to_rfc3339(),
                    sent_at: None,
                    token,
                    event: raw_event.event.clone(),
                    timestamp,
                    is_cookieless_mode: false,
                    historical_migration: true,
                };

                events.push(InternallyCapturedEvent { team_id, inner });
            }

            Ok(events)
        }
    }
}

fn get_distinct_id(amp: &AmplitudeEvent) -> String {
    if let Some(user_id) = &amp.user_id {
        if !user_id.is_empty() {
            return user_id.clone();
        }
    }

    if let Some(device_id) = &amp.device_id {
        if !device_id.is_empty() {
            return device_id.clone();
        }
    }

    Uuid::now_v7().to_string()
}

fn parse_timestamp_string(time_str: &str) -> Result<chrono::DateTime<Utc>, chrono::ParseError> {
    chrono::NaiveDateTime::parse_from_str(time_str, "%Y-%m-%d %H:%M:%S%.f")
        .or_else(|_| chrono::NaiveDateTime::parse_from_str(time_str, "%Y-%m-%d %H:%M:%S"))
        .map(|dt| dt.and_utc())
}

fn parse_timestamp(amp: &AmplitudeEvent) -> Result<chrono::DateTime<Utc>, Error> {
    if let Some(event_time) = &amp.event_time {
        if let Ok(timestamp) = parse_timestamp_string(event_time) {
            return Ok(timestamp);
        }
    }

    if let Some(client_event_time) = &amp.client_event_time {
        if let Ok(timestamp) = parse_timestamp_string(client_event_time) {
            return Ok(timestamp);
        }
    }

    if let Some(server_received_time) = &amp.server_received_time {
        if let Ok(timestamp) = parse_timestamp_string(server_received_time) {
            return Ok(timestamp);
        }
    }

    // If all timestamp parsing fails, use current time as last resort
    Ok(Utc::now())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn create_test_context() -> TransformContext {
        use crate::cache::{MockGroupCache, MockIdentifyCache};
        use std::sync::Arc;

        TransformContext {
            team_id: 123,
            token: "test_token".to_string(),
            job_id: Uuid::now_v7(),
            identify_cache: Arc::new(MockIdentifyCache::new()),
            group_cache: Arc::new(MockGroupCache::new()),
            import_events: true,
            generate_identify_events: false,
            generate_group_identify_events: false,
        }
    }

    fn identity_transform(event: RawEvent) -> Result<Option<RawEvent>, Error> {
        Ok(Some(event))
    }

    #[test]
    fn test_basic_amplitude_event() {
        let amp_event = AmplitudeEvent {
            insert_id: Some("test_insert_id".to_string()),
            event_type: Some("button_click".to_string()),
            user_id: Some("user123".to_string()),
            device_id: Some("device456".to_string()),
            event_time: Some("2023-10-15 14:30:00".to_string()),
            event_properties: [("action".to_string(), json!("click"))]
                .iter()
                .cloned()
                .collect(),
            ..Default::default()
        };

        let parser = AmplitudeEvent::parse_fn(create_test_context(), identity_transform);
        let result = parser(amp_event).unwrap();
        let result = result.into_iter().next().unwrap();

        assert_eq!(result.team_id, 123);
        assert_eq!(result.inner.token, "test_token");
        assert_eq!(result.inner.distinct_id, "user123");

        let data: RawEvent = serde_json::from_str(&result.inner.data).unwrap();
        assert_eq!(data.event, "button_click");
        assert_eq!(data.properties.get("action"), Some(&json!("click")));
        assert_eq!(
            data.properties.get("historical_migration"),
            Some(&json!(true))
        );
        assert_eq!(
            data.properties.get("analytics_source"),
            Some(&json!("amplitude"))
        );
    }

    #[test]
    fn test_pageview_event_transformation() {
        let amp_event = AmplitudeEvent {
            event_type: Some("[Amplitude] Page Viewed".to_string()),
            user_id: Some("user123".to_string()),
            event_properties: [
                (
                    "[Amplitude] Page URL".to_string(),
                    json!("https://example.com/page"),
                ),
                ("[Amplitude] Page Domain".to_string(), json!("example.com")),
                ("[Amplitude] Page Path".to_string(), json!("/page")),
            ]
            .iter()
            .cloned()
            .collect(),
            ..Default::default()
        };

        let parser = AmplitudeEvent::parse_fn(create_test_context(), identity_transform);
        let result = parser(amp_event).unwrap();
        let result = result.into_iter().next().unwrap();

        let data: RawEvent = serde_json::from_str(&result.inner.data).unwrap();
        assert_eq!(data.event, "$pageview");
        assert_eq!(
            data.properties.get("$current_url"),
            Some(&json!("https://example.com/page"))
        );
        assert_eq!(data.properties.get("$host"), Some(&json!("example.com")));
        assert_eq!(data.properties.get("$pathname"), Some(&json!("/page")));
    }

    #[test]
    fn test_autocapture_event_transformation() {
        let amp_event = AmplitudeEvent {
            event_type: Some("[Amplitude] Element Clicked".to_string()),
            user_id: Some("user123".to_string()),
            ..Default::default()
        };

        let parser = AmplitudeEvent::parse_fn(create_test_context(), identity_transform);
        let result = parser(amp_event).unwrap();
        let result = result.into_iter().next().unwrap();

        let data: RawEvent = serde_json::from_str(&result.inner.data).unwrap();
        assert_eq!(data.event, "$autocapture");
    }

    #[test]
    fn test_session_start_filtered_out() {
        let amp_event = AmplitudeEvent {
            event_type: Some("session_start".to_string()),
            user_id: Some("user123".to_string()),
            ..Default::default()
        };

        let parser = AmplitudeEvent::parse_fn(create_test_context(), identity_transform);
        let result = parser(amp_event).unwrap();

        assert!(result.is_empty());
    }

    #[test]
    fn test_device_and_location_properties() {
        let amp_event = AmplitudeEvent {
            event_type: Some("test_event".to_string()),
            user_id: Some("user123".to_string()),
            device_type: Some("iOS".to_string()),
            os_name: Some("iOS".to_string()),
            os_version: Some("15.0".to_string()),
            country: Some("United States".to_string()),
            city: Some("San Francisco".to_string()),
            region: Some("California".to_string()),
            ip_address: Some("192.168.1.1".to_string()),
            ..Default::default()
        };

        let parser = AmplitudeEvent::parse_fn(create_test_context(), identity_transform);
        let result = parser(amp_event).unwrap();
        let result = result.into_iter().next().unwrap();

        let data: RawEvent = serde_json::from_str(&result.inner.data).unwrap();
        assert_eq!(data.properties.get("$device_type"), Some(&json!("Mobile")));
        assert_eq!(data.properties.get("$browser"), Some(&json!("iOS")));
        assert_eq!(
            data.properties.get("$browser_version"),
            Some(&json!("15.0"))
        );
        assert_eq!(
            data.properties.get("$geoip_country_name"),
            Some(&json!("United States"))
        );
        assert_eq!(
            data.properties.get("$geoip_city_name"),
            Some(&json!("San Francisco"))
        );
        assert_eq!(
            data.properties.get("$geoip_subdivision_1_name"),
            Some(&json!("California"))
        );
        assert_eq!(data.properties.get("$ip"), Some(&json!("192.168.1.1")));
        assert_eq!(result.inner.ip, "192.168.1.1");
    }

    #[test]
    fn test_user_properties_set_once() {
        let amp_event = AmplitudeEvent {
            event_type: Some("test_event".to_string()),
            user_id: Some("user123".to_string()),
            user_properties: [
                ("initial_referrer".to_string(), json!("https://google.com")),
                ("initial_utm_source".to_string(), json!("google")),
                ("initial_utm_medium".to_string(), json!("cpc")),
                ("initial_utm_campaign".to_string(), json!("winter_sale")),
            ]
            .iter()
            .cloned()
            .collect(),
            ..Default::default()
        };

        let parser = AmplitudeEvent::parse_fn(create_test_context(), identity_transform);
        let result = parser(amp_event).unwrap();
        let result = result.into_iter().next().unwrap();

        let data: RawEvent = serde_json::from_str(&result.inner.data).unwrap();
        let set_once = data.set_once.unwrap();
        assert_eq!(
            set_once.get("$initial_referrer"),
            Some(&json!("https://google.com"))
        );
        assert_eq!(set_once.get("$initial_utm_source"), Some(&json!("google")));
        assert_eq!(set_once.get("$initial_utm_medium"), Some(&json!("cpc")));
        assert_eq!(
            set_once.get("$initial_utm_campaign"),
            Some(&json!("winter_sale"))
        );
    }

    #[test]
    fn test_empty_user_properties_filtered() {
        let amp_event = AmplitudeEvent {
            event_type: Some("test_event".to_string()),
            user_id: Some("user123".to_string()),
            user_properties: [
                ("initial_referrer".to_string(), json!("EMPTY")),
                ("initial_utm_source".to_string(), json!("google")),
            ]
            .iter()
            .cloned()
            .collect(),
            ..Default::default()
        };

        let parser = AmplitudeEvent::parse_fn(create_test_context(), identity_transform);
        let result = parser(amp_event).unwrap();
        let result = result.into_iter().next().unwrap();

        let data: RawEvent = serde_json::from_str(&result.inner.data).unwrap();
        let set_once = data.set_once.unwrap();
        assert!(!set_once.contains_key("$initial_referrer"));
        assert_eq!(set_once.get("$initial_utm_source"), Some(&json!("google")));
    }

    #[test]
    fn test_timestamp_parsing_multiple_formats() {
        let test_cases = vec![
            ("2023-10-15 14:30:00", true),
            ("2023-10-15 14:30:00.123", true),
            ("invalid-timestamp", false),
        ];

        for (timestamp_str, should_parse) in test_cases {
            let amp_event = AmplitudeEvent {
                event_type: Some("test_event".to_string()),
                user_id: Some("user123".to_string()),
                event_time: Some(timestamp_str.to_string()),
                ..Default::default()
            };

            let parser = AmplitudeEvent::parse_fn(create_test_context(), identity_transform);
            let result = parser(amp_event).unwrap();

            if should_parse {
                assert!(!result.is_empty());
                let data: RawEvent = serde_json::from_str(&result[0].inner.data).unwrap();
                assert!(data.timestamp.is_some());
            }
        }
    }

    #[test]
    fn test_distinct_id_fallback() {
        // Test with user_id
        let amp_event = AmplitudeEvent {
            event_type: Some("test_event".to_string()),
            user_id: Some("user123".to_string()),
            device_id: Some("device456".to_string()),
            ..Default::default()
        };

        let parser = AmplitudeEvent::parse_fn(create_test_context(), identity_transform);
        let result = parser(amp_event).unwrap();
        let result = result.into_iter().next().unwrap();
        assert_eq!(result.inner.distinct_id, "user123");

        // Test with device_id only
        let amp_event = AmplitudeEvent {
            event_type: Some("test_event".to_string()),
            user_id: None,
            device_id: Some("device456".to_string()),
            ..Default::default()
        };

        let parser = AmplitudeEvent::parse_fn(create_test_context(), identity_transform);
        let result = parser(amp_event).unwrap();
        let result = result.into_iter().next().unwrap();
        assert_eq!(result.inner.distinct_id, "device456");

        // Test with neither (should generate UUID)
        let amp_event = AmplitudeEvent {
            event_type: Some("test_event".to_string()),
            user_id: None,
            device_id: None,
            ..Default::default()
        };

        let parser = AmplitudeEvent::parse_fn(create_test_context(), identity_transform);
        let result = parser(amp_event).unwrap();
        let result = result.into_iter().next().unwrap();
        assert!(!result.inner.distinct_id.is_empty());
        assert!(Uuid::parse_str(&result.inner.distinct_id).is_ok());
    }

    #[test]
    fn test_amplitude_specific_properties() {
        let amp_event = AmplitudeEvent {
            event_type: Some("test_event".to_string()),
            user_id: Some("user123".to_string()),
            device_id: Some("device456".to_string()),
            amplitude_id: 789,
            event_id: 101112,
            session_id: 131415,
            ..Default::default()
        };

        let parser = AmplitudeEvent::parse_fn(create_test_context(), identity_transform);
        let result = parser(amp_event).unwrap();
        let result = result.into_iter().next().unwrap();

        let data: RawEvent = serde_json::from_str(&result.inner.data).unwrap();
        assert_eq!(
            data.properties.get("$amplitude_user_id"),
            Some(&json!("user123"))
        );
        assert_eq!(
            data.properties.get("$amplitude_device_id"),
            Some(&json!("device456"))
        );
        assert_eq!(data.properties.get("$device_id"), Some(&json!("device456")));
        assert_eq!(
            data.properties.get("$amplitude_event_id"),
            Some(&json!(101112))
        );
        assert_eq!(
            data.properties.get("$amplitude_session_id"),
            Some(&json!(131415))
        );
    }

    #[test]
    fn test_missing_event_type() {
        let amp_event = AmplitudeEvent {
            event_type: None,
            user_id: Some("user123".to_string()),
            ..Default::default()
        };

        let parser = AmplitudeEvent::parse_fn(create_test_context(), identity_transform);
        let result = parser(amp_event).unwrap();

        assert!(result.is_empty());
    }

    #[test]
    fn test_amplitude_identify_injection_first_time() {
        use crate::cache::MockIdentifyCache;
        use crate::parse::content::TransformContext;
        use std::collections::HashMap;
        use std::sync::Arc;

        let amp_event = AmplitudeEvent {
            event_type: Some("test_event".to_string()),
            user_id: Some("user123".to_string()),
            device_id: Some("device456".to_string()),
            event_time: Some("2023-10-15 14:30:00".to_string()),
            event_properties: {
                let mut props = HashMap::new();
                props.insert("action".to_string(), serde_json::json!("click"));
                props
            },
            amplitude_id: 789,
            event_id: 101112,
            session_id: 131415,
            ..Default::default()
        };

        // Create context with identify injection enabled and mock cache
        let context = TransformContext {
            team_id: 123,
            token: "test_token".to_string(),
            job_id: Uuid::now_v7(),
            identify_cache: Arc::new(MockIdentifyCache::new()),
            group_cache: Arc::new(crate::cache::MockGroupCache::new()),
            import_events: true,
            generate_identify_events: true,
            generate_group_identify_events: false,
        };

        let parser = AmplitudeEvent::parse_fn(context, identity_transform);
        let result = parser(amp_event).unwrap();

        // Should have 2 events: identify event + original event
        assert_eq!(result.len(), 2);

        // First event should be identify event
        let identify_event = &result[0];
        assert_eq!(identify_event.team_id, 123);
        let identify_data: serde_json::Value =
            serde_json::from_str(&identify_event.inner.data).unwrap();
        assert_eq!(identify_data["event"], "$identify");
        assert_eq!(identify_data["distinct_id"], "user123");
        assert_eq!(
            identify_data["properties"]["$anon_distinct_id"],
            "device456"
        );
        // Verify identify event has the required properties
        assert_eq!(identify_data["properties"]["$amplitude_user_id"], "user123");
        assert_eq!(
            identify_data["properties"]["$amplitude_device_id"],
            "device456"
        );
        assert_eq!(identify_data["properties"]["historical_migration"], true);
        assert_eq!(identify_data["properties"]["analytics_source"], "amplitude");

        // Verify identify event uses the same timestamp as the original event
        assert_eq!(identify_data["timestamp"], "2023-10-15T14:30:00+00:00");

        // Second event should be original event
        let original_event = &result[1];
        assert_eq!(original_event.team_id, 123);
        let original_data: serde_json::Value =
            serde_json::from_str(&original_event.inner.data).unwrap();
        assert_eq!(original_data["event"], "test_event");
        assert_eq!(original_data["distinct_id"], "user123");
    }

    #[test]
    fn test_amplitude_identify_injection_duplicate() {
        use crate::cache::MockIdentifyCache;
        use crate::parse::content::TransformContext;
        use std::sync::Arc;

        // First event with same user-device pair
        let amp_event1 = AmplitudeEvent {
            event_type: Some("test_event1".to_string()),
            user_id: Some("user123".to_string()),
            device_id: Some("device456".to_string()),
            event_time: Some("2023-10-15 14:30:00".to_string()),
            ..Default::default()
        };

        // Second event with same user-device pair
        let amp_event2 = AmplitudeEvent {
            event_type: Some("test_event2".to_string()),
            user_id: Some("user123".to_string()),
            device_id: Some("device456".to_string()),
            event_time: Some("2023-10-15 14:30:01".to_string()),
            ..Default::default()
        };

        // Create shared mock cache to track state between calls
        let cache = Arc::new(MockIdentifyCache::new());

        let context = TransformContext {
            team_id: 123,
            token: "test_token".to_string(),
            job_id: Uuid::now_v7(),
            identify_cache: cache.clone(),
            group_cache: Arc::new(crate::cache::MockGroupCache::new()),
            import_events: true,
            generate_identify_events: true,
            generate_group_identify_events: false,
        };

        let parser = AmplitudeEvent::parse_fn(context, identity_transform);

        // First event should generate identify event
        let result1 = parser(amp_event1).unwrap();
        assert_eq!(result1.len(), 2); // identify + original
        let identify_data: serde_json::Value =
            serde_json::from_str(&result1[0].inner.data).unwrap();
        assert_eq!(identify_data["event"], "$identify");

        // Second event should NOT generate identify event (already seen in cache)
        let result2 = parser(amp_event2).unwrap();
        assert_eq!(result2.len(), 1); // only original event
        let original_data: serde_json::Value =
            serde_json::from_str(&result2[0].inner.data).unwrap();
        assert_eq!(original_data["event"], "test_event2");
    }

    #[test]
    fn test_amplitude_identify_injection_disabled() {
        use crate::cache::MockIdentifyCache;
        use crate::parse::content::TransformContext;
        use std::sync::Arc;

        let amp_event = AmplitudeEvent {
            event_type: Some("test_event".to_string()),
            user_id: Some("user123".to_string()),
            device_id: Some("device456".to_string()),
            event_time: Some("2023-10-15 14:30:00".to_string()),
            ..Default::default()
        };

        // Create context with identify injection disabled
        let context = TransformContext {
            team_id: 123,
            token: "test_token".to_string(),
            job_id: Uuid::now_v7(),
            identify_cache: Arc::new(MockIdentifyCache::new()),
            group_cache: Arc::new(crate::cache::MockGroupCache::new()),
            import_events: true,
            generate_identify_events: false, // Disabled
            generate_group_identify_events: false,
        };

        let parser = AmplitudeEvent::parse_fn(context, identity_transform);
        let result = parser(amp_event).unwrap();

        // Should have only 1 event (no identify event)
        assert_eq!(result.len(), 1);

        // The event should be the original event
        let event = &result[0];
        assert_eq!(event.team_id, 123);
        let data: serde_json::Value = serde_json::from_str(&event.inner.data).unwrap();
        assert_eq!(data["event"], "test_event");
        assert_eq!(data["distinct_id"], "user123");
    }

    #[test]
    fn test_amplitude_identify_with_cache_failure() {
        use crate::cache::MockIdentifyCache;
        use crate::parse::content::TransformContext;
        use std::sync::Arc;

        let amp_event = AmplitudeEvent {
            event_type: Some("test_event".to_string()),
            user_id: Some("user123".to_string()),
            device_id: Some("device456".to_string()),
            event_time: Some("2023-10-15 14:30:00".to_string()),
            ..Default::default()
        };

        // Create context with identify injection enabled
        let context = TransformContext {
            team_id: 123,
            token: "test_token".to_string(),
            job_id: Uuid::now_v7(),
            identify_cache: Arc::new(MockIdentifyCache::new()),
            group_cache: Arc::new(crate::cache::MockGroupCache::new()),
            import_events: true,
            generate_identify_events: true,
            generate_group_identify_events: false,
        };

        let parser = AmplitudeEvent::parse_fn(context, identity_transform);

        // First parse should work fine
        let result1 = parser(amp_event.clone()).unwrap();
        assert_eq!(result1.len(), 2);

        // TODO: Add test for cache failure scenarios once we have better error handling
        // This would require mocking cache failures or using a cache that can fail
    }

    #[test]
    fn test_amplitude_mixed_events_with_identify() {
        use crate::cache::MockIdentifyCache;
        use crate::parse::content::TransformContext;
        use std::sync::Arc;

        // Event with user_id and device_id (should generate identify)
        let amp_event_with_both = AmplitudeEvent {
            event_type: Some("event_with_both".to_string()),
            user_id: Some("user123".to_string()),
            device_id: Some("device456".to_string()),
            event_time: Some("2023-10-15 14:30:00".to_string()),
            ..Default::default()
        };

        // Event with only user_id (should not generate identify)
        let amp_event_user_only = AmplitudeEvent {
            event_type: Some("event_user_only".to_string()),
            user_id: Some("user789".to_string()),
            device_id: None,
            event_time: Some("2023-10-15 14:30:01".to_string()),
            ..Default::default()
        };

        // Event with only device_id (should not generate identify)
        let amp_event_device_only = AmplitudeEvent {
            event_type: Some("event_device_only".to_string()),
            user_id: None,
            device_id: Some("device999".to_string()),
            event_time: Some("2023-10-15 14:30:02".to_string()),
            ..Default::default()
        };

        // Event with neither (should not generate identify)
        let amp_event_neither = AmplitudeEvent {
            event_type: Some("event_neither".to_string()),
            user_id: None,
            device_id: None,
            event_time: Some("2023-10-15 14:30:03".to_string()),
            ..Default::default()
        };

        // Create context with identify injection enabled
        let context = TransformContext {
            team_id: 123,
            token: "test_token".to_string(),
            job_id: Uuid::now_v7(),
            identify_cache: Arc::new(MockIdentifyCache::new()),
            group_cache: Arc::new(crate::cache::MockGroupCache::new()),
            import_events: true,
            generate_identify_events: true,
            generate_group_identify_events: false,
        };

        let parser = AmplitudeEvent::parse_fn(context, identity_transform);

        // Test event with both user_id and device_id
        let result1 = parser(amp_event_with_both).unwrap();
        assert_eq!(result1.len(), 2); // identify + original
        let identify_data: serde_json::Value =
            serde_json::from_str(&result1[0].inner.data).unwrap();
        assert_eq!(identify_data["event"], "$identify");
        let original_data: serde_json::Value =
            serde_json::from_str(&result1[1].inner.data).unwrap();
        assert_eq!(original_data["event"], "event_with_both");

        // Test event with only user_id
        let result2 = parser(amp_event_user_only).unwrap();
        assert_eq!(result2.len(), 1); // only original
        let data: serde_json::Value = serde_json::from_str(&result2[0].inner.data).unwrap();
        assert_eq!(data["event"], "event_user_only");

        // Test event with only device_id
        let result3 = parser(amp_event_device_only).unwrap();
        assert_eq!(result3.len(), 1); // only original
        let data: serde_json::Value = serde_json::from_str(&result3[0].inner.data).unwrap();
        assert_eq!(data["event"], "event_device_only");

        // Test event with neither
        let result4 = parser(amp_event_neither).unwrap();
        assert_eq!(result4.len(), 1); // only original
        let data: serde_json::Value = serde_json::from_str(&result4[0].inner.data).unwrap();
        assert_eq!(data["event"], "event_neither");
    }

    #[test]
    fn test_amplitude_identify_import_events_disabled() {
        use crate::cache::MockIdentifyCache;
        use crate::parse::content::TransformContext;
        use std::sync::Arc;

        let amp_event = AmplitudeEvent {
            event_type: Some("test_event".to_string()),
            user_id: Some("user123".to_string()),
            device_id: Some("device456".to_string()),
            event_time: Some("2023-10-15 14:30:00".to_string()),
            ..Default::default()
        };

        // Create context with import_events disabled but identify injection enabled
        let context = TransformContext {
            team_id: 123,
            token: "test_token".to_string(),
            job_id: Uuid::now_v7(),
            identify_cache: Arc::new(MockIdentifyCache::new()),
            group_cache: Arc::new(crate::cache::MockGroupCache::new()),
            import_events: false, // Disabled
            generate_identify_events: true,
            generate_group_identify_events: false,
        };

        let parser = AmplitudeEvent::parse_fn(context, identity_transform);
        let result = parser(amp_event).unwrap();

        // Should have only 1 event (identify event, but no original event)
        assert_eq!(result.len(), 1);

        // The event should be the identify event
        let event = &result[0];
        assert_eq!(event.team_id, 123);
        let data: serde_json::Value = serde_json::from_str(&event.inner.data).unwrap();
        assert_eq!(data["event"], "$identify");
        assert_eq!(data["distinct_id"], "user123");
    }

    #[test]
    fn test_group_identify_first_time() {
        use crate::cache::{MockGroupCache, MockIdentifyCache};
        use std::collections::HashMap;
        use std::sync::Arc;

        let mut groups = HashMap::new();
        groups.insert("company".to_string(), vec!["acme-corp".to_string()]);

        let mut group_properties = HashMap::new();
        let mut company_props = HashMap::new();
        company_props.insert("acme-corp".to_string(), {
            let mut props = HashMap::new();
            props.insert("name".to_string(), json!("Acme Corporation"));
            props.insert("industry".to_string(), json!("Technology"));
            props
        });
        group_properties.insert("company".to_string(), company_props);

        let amp_event = AmplitudeEvent {
            event_type: Some("test_event".to_string()),
            user_id: Some("user123".to_string()),
            device_id: Some("device456".to_string()),
            event_time: Some("2023-10-15 14:30:00".to_string()),
            groups,
            group_properties,
            ..Default::default()
        };

        let context = TransformContext {
            team_id: 123,
            token: "test_token".to_string(),
            job_id: Uuid::now_v7(),
            identify_cache: Arc::new(MockIdentifyCache::new()),
            group_cache: Arc::new(MockGroupCache::new()),
            import_events: true,
            generate_identify_events: false,
            generate_group_identify_events: true,
        };

        let parser = AmplitudeEvent::parse_fn(context, identity_transform);
        let result = parser(amp_event).unwrap();

        // Should have 2 events: group identify + original event
        assert_eq!(result.len(), 2);

        // First event should be group identify event
        let group_identify_event = &result[0];
        assert_eq!(group_identify_event.team_id, 123);
        let group_identify_data: serde_json::Value =
            serde_json::from_str(&group_identify_event.inner.data).unwrap();
        assert_eq!(group_identify_data["event"], "$groupidentify");
        assert_eq!(group_identify_data["properties"]["$group_type"], "company");
        assert_eq!(group_identify_data["properties"]["$group_key"], "acme-corp");
        assert_eq!(
            group_identify_data["properties"]["$group_set"]["name"],
            "Acme Corporation"
        );
        assert_eq!(
            group_identify_data["properties"]["$group_set"]["industry"],
            "Technology"
        );

        // Verify historical migration flag is present
        assert_eq!(
            group_identify_data["properties"]["historical_migration"],
            true
        );
        assert_eq!(
            group_identify_data["properties"]["analytics_source"],
            "amplitude"
        );

        // Verify timestamp is preserved from the original event
        assert_eq!(
            group_identify_data["timestamp"],
            "2023-10-15T14:30:00+00:00"
        );

        // Second event should be original event with groups
        let original_event = &result[1];
        let original_data: serde_json::Value =
            serde_json::from_str(&original_event.inner.data).unwrap();
        assert_eq!(original_data["event"], "test_event");
        assert_eq!(
            original_data["properties"]["$groups"]["company"],
            "acme-corp"
        );
    }

    #[test]
    fn test_group_properties_unchanged() {
        use crate::cache::{MockGroupCache, MockIdentifyCache};
        use std::collections::HashMap;
        use std::sync::Arc;

        let mut groups = HashMap::new();
        groups.insert("company".to_string(), vec!["acme-corp".to_string()]);

        let mut group_properties = HashMap::new();
        let mut company_props = HashMap::new();
        company_props.insert("acme-corp".to_string(), {
            let mut props = HashMap::new();
            props.insert("name".to_string(), json!("Acme Corporation"));
            props
        });
        group_properties.insert("company".to_string(), company_props.clone());

        let amp_event1 = AmplitudeEvent {
            event_type: Some("test_event1".to_string()),
            user_id: Some("user123".to_string()),
            device_id: Some("device456".to_string()),
            groups: groups.clone(),
            group_properties: group_properties.clone(),
            ..Default::default()
        };

        let amp_event2 = AmplitudeEvent {
            event_type: Some("test_event2".to_string()),
            user_id: Some("user123".to_string()),
            device_id: Some("device456".to_string()),
            groups,
            group_properties,
            ..Default::default()
        };

        let group_cache = Arc::new(MockGroupCache::new());
        let context = TransformContext {
            team_id: 123,
            token: "test_token".to_string(),
            job_id: Uuid::now_v7(),
            identify_cache: Arc::new(MockIdentifyCache::new()),
            group_cache: group_cache.clone(),
            import_events: true,
            generate_identify_events: false,
            generate_group_identify_events: true,
        };

        let parser = AmplitudeEvent::parse_fn(context, identity_transform);

        // First event should generate group identify event
        let result1 = parser(amp_event1).unwrap();
        assert_eq!(result1.len(), 2); // group identify + original

        // Second event should NOT generate group identify event (unchanged properties)
        let result2 = parser(amp_event2).unwrap();
        assert_eq!(result2.len(), 1); // only original event
        let original_data: serde_json::Value =
            serde_json::from_str(&result2[0].inner.data).unwrap();
        assert_eq!(original_data["event"], "test_event2");
        assert_eq!(
            original_data["properties"]["$groups"]["company"],
            "acme-corp"
        );
    }

    #[test]
    fn test_group_properties_changed() {
        use crate::cache::{MockGroupCache, MockIdentifyCache};
        use std::collections::HashMap;
        use std::sync::Arc;

        let mut groups = HashMap::new();
        groups.insert("company".to_string(), vec!["acme-corp".to_string()]);

        // First set of properties
        let mut group_properties1 = HashMap::new();
        let mut company_props1 = HashMap::new();
        company_props1.insert("acme-corp".to_string(), {
            let mut props = HashMap::new();
            props.insert("name".to_string(), json!("Acme Corporation"));
            props.insert("size".to_string(), json!(250));
            props
        });
        group_properties1.insert("company".to_string(), company_props1);

        // Second set of properties (changed size)
        let mut group_properties2 = HashMap::new();
        let mut company_props2 = HashMap::new();
        company_props2.insert("acme-corp".to_string(), {
            let mut props = HashMap::new();
            props.insert("name".to_string(), json!("Acme Corporation"));
            props.insert("size".to_string(), json!(300)); // Changed
            props
        });
        group_properties2.insert("company".to_string(), company_props2);

        let amp_event1 = AmplitudeEvent {
            event_type: Some("test_event1".to_string()),
            groups: groups.clone(),
            group_properties: group_properties1,
            ..Default::default()
        };

        let amp_event2 = AmplitudeEvent {
            event_type: Some("test_event2".to_string()),
            groups,
            group_properties: group_properties2,
            ..Default::default()
        };

        let group_cache = Arc::new(MockGroupCache::new());
        let context = TransformContext {
            team_id: 123,
            token: "test_token".to_string(),
            job_id: Uuid::now_v7(),
            identify_cache: Arc::new(MockIdentifyCache::new()),
            group_cache: group_cache.clone(),
            import_events: true,
            generate_identify_events: false,
            generate_group_identify_events: true,
        };

        let parser = AmplitudeEvent::parse_fn(context, identity_transform);

        // First event should generate group identify event
        let result1 = parser(amp_event1).unwrap();
        assert_eq!(result1.len(), 2); // group identify + original

        // Second event should also generate group identify event (changed properties)
        let result2 = parser(amp_event2).unwrap();
        assert_eq!(result2.len(), 2); // group identify + original

        let group_identify_data: serde_json::Value =
            serde_json::from_str(&result2[0].inner.data).unwrap();
        assert_eq!(group_identify_data["event"], "$groupidentify");
        assert_eq!(group_identify_data["properties"]["$group_set"]["size"], 300);

        // Verify timestamp is set (should not be empty or null)
        assert!(group_identify_data["timestamp"].is_string());
        assert!(!group_identify_data["timestamp"]
            .as_str()
            .unwrap()
            .is_empty());
    }

    #[test]
    fn test_multiple_groups() {
        use crate::cache::{MockGroupCache, MockIdentifyCache};
        use std::collections::HashMap;
        use std::sync::Arc;

        let mut groups = HashMap::new();
        groups.insert("company".to_string(), vec!["acme-corp".to_string()]);
        groups.insert("team".to_string(), vec!["engineering".to_string()]);

        let mut group_properties = HashMap::new();

        let mut company_props = HashMap::new();
        company_props.insert("acme-corp".to_string(), {
            let mut props = HashMap::new();
            props.insert("name".to_string(), json!("Acme Corporation"));
            props
        });
        group_properties.insert("company".to_string(), company_props);

        let mut team_props = HashMap::new();
        team_props.insert("engineering".to_string(), {
            let mut props = HashMap::new();
            props.insert("name".to_string(), json!("Engineering Team"));
            props
        });
        group_properties.insert("team".to_string(), team_props);

        let amp_event = AmplitudeEvent {
            event_type: Some("test_event".to_string()),
            groups,
            group_properties,
            ..Default::default()
        };

        let context = TransformContext {
            team_id: 123,
            token: "test_token".to_string(),
            job_id: Uuid::now_v7(),
            identify_cache: Arc::new(MockIdentifyCache::new()),
            group_cache: Arc::new(MockGroupCache::new()),
            import_events: true,
            generate_identify_events: false,
            generate_group_identify_events: true,
        };

        let parser = AmplitudeEvent::parse_fn(context, identity_transform);
        let result = parser(amp_event).unwrap();

        // Should have 3 events: 2 group identify + 1 original event
        assert_eq!(result.len(), 3);

        // Check group identify events have timestamps
        let group_identify1_data: serde_json::Value =
            serde_json::from_str(&result[0].inner.data).unwrap();
        let group_identify2_data: serde_json::Value =
            serde_json::from_str(&result[1].inner.data).unwrap();

        assert!(group_identify1_data["timestamp"].is_string());
        assert!(group_identify2_data["timestamp"].is_string());
        assert!(!group_identify1_data["timestamp"]
            .as_str()
            .unwrap()
            .is_empty());
        assert!(!group_identify2_data["timestamp"]
            .as_str()
            .unwrap()
            .is_empty());

        // Check original event has both groups
        let original_event = &result[2];
        let original_data: serde_json::Value =
            serde_json::from_str(&original_event.inner.data).unwrap();
        assert_eq!(
            original_data["properties"]["$groups"]["company"],
            "acme-corp"
        );
        assert_eq!(
            original_data["properties"]["$groups"]["team"],
            "engineering"
        );
    }

    #[test]
    fn test_groups_without_properties() {
        use crate::cache::{MockGroupCache, MockIdentifyCache};
        use std::collections::HashMap;
        use std::sync::Arc;

        let mut groups = HashMap::new();
        groups.insert("company".to_string(), vec!["acme-corp".to_string()]);

        let amp_event = AmplitudeEvent {
            event_type: Some("test_event".to_string()),
            groups,
            group_properties: HashMap::new(), // No group properties
            ..Default::default()
        };

        let context = TransformContext {
            team_id: 123,
            token: "test_token".to_string(),
            job_id: Uuid::now_v7(),
            identify_cache: Arc::new(MockIdentifyCache::new()),
            group_cache: Arc::new(MockGroupCache::new()),
            import_events: true,
            generate_identify_events: false,
            generate_group_identify_events: true,
        };

        let parser = AmplitudeEvent::parse_fn(context, identity_transform);
        let result = parser(amp_event).unwrap();

        // Should have 2 events: group identify (with empty props) + original event
        assert_eq!(result.len(), 2);

        let group_identify_data: serde_json::Value =
            serde_json::from_str(&result[0].inner.data).unwrap();
        assert_eq!(group_identify_data["event"], "$groupidentify");
        assert_eq!(group_identify_data["properties"]["$group_set"], json!({}));

        let original_data: serde_json::Value = serde_json::from_str(&result[1].inner.data).unwrap();
        assert_eq!(
            original_data["properties"]["$groups"]["company"],
            "acme-corp"
        );
    }

    #[test]
    fn test_group_identify_timestamp_preservation() {
        use crate::cache::{MockGroupCache, MockIdentifyCache};
        use std::collections::HashMap;
        use std::sync::Arc;

        let mut groups = HashMap::new();
        groups.insert("company".to_string(), vec!["acme-corp".to_string()]);

        let mut group_properties = HashMap::new();
        let mut company_props = HashMap::new();
        company_props.insert("acme-corp".to_string(), {
            let mut props = HashMap::new();
            props.insert("name".to_string(), json!("Acme Corporation"));
            props
        });
        group_properties.insert("company".to_string(), company_props);

        // Use a specific timestamp that's not "now"
        let specific_timestamp = "2023-10-15T14:30:00+00:00";

        let amp_event = AmplitudeEvent {
            event_type: Some("test_event".to_string()),
            user_id: Some("user123".to_string()),
            device_id: Some("device456".to_string()),
            event_time: Some("2023-10-15 14:30:00".to_string()),
            groups,
            group_properties,
            ..Default::default()
        };

        let context = TransformContext {
            team_id: 123,
            token: "test_token".to_string(),
            job_id: Uuid::now_v7(),
            identify_cache: Arc::new(MockIdentifyCache::new()),
            group_cache: Arc::new(MockGroupCache::new()),
            import_events: true,
            generate_identify_events: false,
            generate_group_identify_events: true,
        };

        let parser = AmplitudeEvent::parse_fn(context, identity_transform);
        let result = parser(amp_event).unwrap();

        // Should have 2 events: group identify + original event
        assert_eq!(result.len(), 2);

        // Check group identify event timestamp
        let group_identify_event = &result[0];
        let group_identify_data: serde_json::Value =
            serde_json::from_str(&group_identify_event.inner.data).unwrap();

        assert_eq!(group_identify_data["event"], "$groupidentify");
        assert_eq!(group_identify_data["timestamp"], specific_timestamp);

        // Verify the timestamp is not a "now" timestamp
        let now = chrono::Utc::now();
        assert_ne!(group_identify_data["timestamp"], now.to_rfc3339());

        // Check original event also has the same timestamp
        let original_event = &result[1];
        let original_data: serde_json::Value =
            serde_json::from_str(&original_event.inner.data).unwrap();
        assert_eq!(original_data["timestamp"], specific_timestamp);
    }

    #[test]
    fn test_group_identify_disabled() {
        use crate::cache::{MockGroupCache, MockIdentifyCache};
        use std::collections::HashMap;
        use std::sync::Arc;

        let mut groups = HashMap::new();
        groups.insert("company".to_string(), vec!["acme-corp".to_string()]);

        let amp_event = AmplitudeEvent {
            event_type: Some("test_event".to_string()),
            groups,
            ..Default::default()
        };

        let context = TransformContext {
            team_id: 123,
            token: "test_token".to_string(),
            job_id: Uuid::now_v7(),
            identify_cache: Arc::new(MockIdentifyCache::new()),
            group_cache: Arc::new(MockGroupCache::new()),
            import_events: true,
            generate_identify_events: false,
            generate_group_identify_events: false, // Disabled
        };

        let parser = AmplitudeEvent::parse_fn(context, identity_transform);
        let result = parser(amp_event).unwrap();

        // Should have only 1 event (no group identify event)
        assert_eq!(result.len(), 1);

        let original_data: serde_json::Value = serde_json::from_str(&result[0].inner.data).unwrap();
        assert_eq!(original_data["event"], "test_event");
        assert_eq!(
            original_data["properties"]["$groups"]["company"],
            "acme-corp"
        );
    }

    #[test]
    fn test_job_id_in_amplitude_event() {
        use crate::cache::{MockGroupCache, MockIdentifyCache};
        use std::sync::Arc;

        let test_job_id = Uuid::now_v7();

        let amp_event = AmplitudeEvent {
            event_type: Some("test_event".to_string()),
            user_id: Some("user123".to_string()),
            ..Default::default()
        };

        let context = TransformContext {
            team_id: 123,
            token: "test_token".to_string(),
            job_id: test_job_id,
            identify_cache: Arc::new(MockIdentifyCache::new()),
            group_cache: Arc::new(MockGroupCache::new()),
            import_events: true,
            generate_identify_events: false,
            generate_group_identify_events: false,
        };

        let parser = AmplitudeEvent::parse_fn(context, identity_transform);
        let result = parser(amp_event).unwrap();

        assert_eq!(result.len(), 1);

        let data: RawEvent = serde_json::from_str(&result[0].inner.data).unwrap();
        assert_eq!(
            data.properties.get("$import_job_id"),
            Some(&json!(test_job_id.to_string()))
        );
    }

    #[test]
    fn test_user_properties_updated_string_bool() {
        // Test that user_properties_updated accepts string "true"
        let json = r#"{
            "data": {
                "user_properties_updated": "true"
            }
        }"#;
        let event: AmplitudeEvent = serde_json::from_str(json).unwrap();
        assert!(event.data.user_properties_updated);

        // Test that user_properties_updated accepts string "false"
        let json = r#"{
            "data": {
                "user_properties_updated": "false"
            }
        }"#;
        let event: AmplitudeEvent = serde_json::from_str(json).unwrap();
        assert!(!event.data.user_properties_updated);

        // Test with actual boolean
        let json = r#"{
            "data": {
                "user_properties_updated": true
            }
        }"#;
        let event: AmplitudeEvent = serde_json::from_str(json).unwrap();
        assert!(event.data.user_properties_updated);

        // Test with string "1"
        let json = r#"{
            "data": {
                "user_properties_updated": "1"
            }
        }"#;
        let event: AmplitudeEvent = serde_json::from_str(json).unwrap();
        assert!(event.data.user_properties_updated);
    }

    #[test]
    fn test_is_attribution_event_string_bool() {
        // Test with string "true"
        let json = r#"{"is_attribution_event": "true"}"#;
        let event: AmplitudeEvent = serde_json::from_str(json).unwrap();
        assert_eq!(event.is_attribution_event, Some(true));

        // Test with string "false"
        let json = r#"{"is_attribution_event": "false"}"#;
        let event: AmplitudeEvent = serde_json::from_str(json).unwrap();
        assert_eq!(event.is_attribution_event, Some(false));

        // Test with string "1"
        let json = r#"{"is_attribution_event": "1"}"#;
        let event: AmplitudeEvent = serde_json::from_str(json).unwrap();
        assert_eq!(event.is_attribution_event, Some(true));

        // Test with actual boolean
        let json = r#"{"is_attribution_event": true}"#;
        let event: AmplitudeEvent = serde_json::from_str(json).unwrap();
        assert_eq!(event.is_attribution_event, Some(true));

        // Test with null
        let json = r#"{"is_attribution_event": null}"#;
        let event: AmplitudeEvent = serde_json::from_str(json).unwrap();
        assert_eq!(event.is_attribution_event, None);

        // Test with missing field
        let json = r#"{}"#;
        let event: AmplitudeEvent = serde_json::from_str(json).unwrap();
        assert_eq!(event.is_attribution_event, None);
    }

    #[test]
    fn test_paying_string_bool() {
        // Test with string "true"
        let json = r#"{"paying": "true"}"#;
        let event: AmplitudeEvent = serde_json::from_str(json).unwrap();
        assert_eq!(event.paying, Some(true));

        // Test with string "0"
        let json = r#"{"paying": "0"}"#;
        let event: AmplitudeEvent = serde_json::from_str(json).unwrap();
        assert_eq!(event.paying, Some(false));

        // Test with integer
        let json = r#"{"paying": 1}"#;
        let event: AmplitudeEvent = serde_json::from_str(json).unwrap();
        assert_eq!(event.paying, Some(true));

        // Test with actual boolean
        let json = r#"{"paying": false}"#;
        let event: AmplitudeEvent = serde_json::from_str(json).unwrap();
        assert_eq!(event.paying, Some(false));

        // Test with missing field
        let json = r#"{}"#;
        let event: AmplitudeEvent = serde_json::from_str(json).unwrap();
        assert_eq!(event.paying, None);
    }

    #[test]
    fn test_job_id_in_group_identify_event() {
        use crate::cache::{MockGroupCache, MockIdentifyCache};
        use std::collections::HashMap;
        use std::sync::Arc;

        let test_job_id = Uuid::now_v7();

        let mut groups = HashMap::new();
        groups.insert("company".to_string(), vec!["acme-corp".to_string()]);

        let mut group_properties = HashMap::new();
        let mut company_props = HashMap::new();
        company_props.insert("acme-corp".to_string(), {
            let mut props = HashMap::new();
            props.insert("name".to_string(), json!("Acme Corporation"));
            props
        });
        group_properties.insert("company".to_string(), company_props);

        let amp_event = AmplitudeEvent {
            event_type: Some("test_event".to_string()),
            user_id: Some("user123".to_string()),
            groups,
            group_properties,
            ..Default::default()
        };

        let context = TransformContext {
            team_id: 123,
            token: "test_token".to_string(),
            job_id: test_job_id,
            identify_cache: Arc::new(MockIdentifyCache::new()),
            group_cache: Arc::new(MockGroupCache::new()),
            import_events: true,
            generate_identify_events: false,
            generate_group_identify_events: true,
        };

        let parser = AmplitudeEvent::parse_fn(context, identity_transform);
        let result = parser(amp_event).unwrap();

        assert_eq!(result.len(), 2);

        let group_identify_data: serde_json::Value =
            serde_json::from_str(&result[0].inner.data).unwrap();
        assert_eq!(group_identify_data["event"], "$groupidentify");
        assert_eq!(
            group_identify_data["properties"]["$import_job_id"],
            json!(test_job_id.to_string())
        );

        let original_data: serde_json::Value = serde_json::from_str(&result[1].inner.data).unwrap();
        assert_eq!(
            original_data["properties"]["$import_job_id"],
            json!(test_job_id.to_string())
        );
    }

    #[test]
    fn test_captured_event_has_historical_migration_and_now_fields() {
        let before_test = Utc::now();

        let amp_event = AmplitudeEvent {
            insert_id: Some("test_insert_id".to_string()),
            event_type: Some("test_event".to_string()),
            user_id: Some("user123".to_string()),
            event_time: Some("2023-10-15 14:30:00".to_string()),
            ..Default::default()
        };

        let parser = AmplitudeEvent::parse_fn(create_test_context(), identity_transform);
        let result = parser(amp_event).unwrap();
        let captured_event = result.into_iter().next().unwrap();

        let after_test = Utc::now();

        assert_eq!(
            captured_event.inner.historical_migration, true,
            "historical_migration field must be true for batch import events"
        );

        assert!(
            !captured_event.inner.now.is_empty(),
            "now field must be set for events"
        );

        let now_timestamp = chrono::DateTime::parse_from_rfc3339(&captured_event.inner.now)
            .expect("now should be valid RFC3339 timestamp")
            .with_timezone(&Utc);
        assert!(
            now_timestamp >= before_test && now_timestamp <= after_test,
            "now timestamp should be current (between test start and end)"
        );

        let serialized = serde_json::to_value(&captured_event.inner).unwrap();
        assert_eq!(
            serialized["historical_migration"],
            json!(true),
            "historical_migration must be in serialized output"
        );
        assert!(
            serialized["now"].is_string(),
            "now must be a string in serialized output"
        );
    }
}
