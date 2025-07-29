use std::collections::HashMap;

use anyhow::Error;
use chrono::Utc;
use common_types::{CapturedEvent, InternallyCapturedEvent, RawEvent};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use uuid::Uuid;

use super::TransformContext;

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct AmplitudeData {
    pub path: Option<String>,
    #[serde(default)]
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
    pub group_properties: HashMap<String, Value>,
    #[serde(default)]
    pub groups: HashMap<String, Value>,
    pub idfa: Option<String>,
    pub ip_address: Option<String>,
    pub is_attribution_event: Option<bool>,
    pub language: Option<String>,
    pub library: Option<String>,
    pub location_lat: Option<f64>,
    pub location_lng: Option<f64>,
    pub os_name: Option<String>,
    pub os_version: Option<String>,
    pub partner_id: Option<String>,
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

impl AmplitudeEvent {
    pub fn parse_fn(
        context: TransformContext,
        event_transform: impl Fn(RawEvent) -> Result<Option<RawEvent>, Error>,
    ) -> impl Fn(Self) -> Result<Option<InternallyCapturedEvent>, Error> {
        move |amp| {
            let token = context.token.clone();
            let team_id = context.team_id;

            let Some(event_type_raw) = &amp.event_type else {
                return Ok(None);
            };

            let event_type = match event_type_raw.as_str() {
                "session_start" => return Ok(None),
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

            let raw_event = RawEvent {
                token: Some(token.clone()),
                distinct_id: Some(Value::String(distinct_id.clone())),
                uuid: Some(event_uuid),
                event: event_type,
                properties,
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
                return Ok(None);
            };

            let inner = CapturedEvent {
                uuid: event_uuid,
                distinct_id,
                ip: amp.ip_address.unwrap_or_else(|| "127.0.0.1".to_string()),
                data: serde_json::to_string(&raw_event)?,
                now: Utc::now().to_rfc3339(),
                sent_at: None,
                token,
                is_cookieless_mode: false,
            };

            Ok(Some(InternallyCapturedEvent { team_id, inner }))
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
        TransformContext {
            team_id: 123,
            token: "test_token".to_string(),
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
        let result = parser(amp_event).unwrap().unwrap();

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
        let result = parser(amp_event).unwrap().unwrap();

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
        let result = parser(amp_event).unwrap().unwrap();

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

        assert!(result.is_none());
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
        let result = parser(amp_event).unwrap().unwrap();

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
        let result = parser(amp_event).unwrap().unwrap();

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
        let result = parser(amp_event).unwrap().unwrap();

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
                assert!(result.is_some());
                let data: RawEvent = serde_json::from_str(&result.unwrap().inner.data).unwrap();
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
        let result = parser(amp_event).unwrap().unwrap();
        assert_eq!(result.inner.distinct_id, "user123");

        // Test with device_id only
        let amp_event = AmplitudeEvent {
            event_type: Some("test_event".to_string()),
            user_id: None,
            device_id: Some("device456".to_string()),
            ..Default::default()
        };

        let parser = AmplitudeEvent::parse_fn(create_test_context(), identity_transform);
        let result = parser(amp_event).unwrap().unwrap();
        assert_eq!(result.inner.distinct_id, "device456");

        // Test with neither (should generate UUID)
        let amp_event = AmplitudeEvent {
            event_type: Some("test_event".to_string()),
            user_id: None,
            device_id: None,
            ..Default::default()
        };

        let parser = AmplitudeEvent::parse_fn(create_test_context(), identity_transform);
        let result = parser(amp_event).unwrap().unwrap();
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
        let result = parser(amp_event).unwrap().unwrap();

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

        assert!(result.is_none());
    }
}
