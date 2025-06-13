use std::collections::HashMap;

use anyhow::Error;
use chrono::Utc;
use common_types::{CapturedEvent, InternallyCapturedEvent, RawEvent};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use uuid::Uuid;

use super::TransformContext;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AmplitudeData {
    pub path: String,
    #[serde(default)]
    pub user_properties_updated: bool,
    #[serde(rename = "group_first_event")]
    pub group_first_event: HashMap<String, Value>,
    #[serde(rename = "group_ids")]
    pub group_ids: HashMap<String, Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AmplitudeEvent {
    #[serde(rename = "$insert_id")]
    pub insert_id: String,
    #[serde(rename = "$insert_key")]
    pub insert_key: Option<String>,
    #[serde(rename = "$schema")]
    pub schema: Option<String>,
    pub adid: Option<String>,
    pub amplitude_attribution_ids: Option<Value>,
    pub amplitude_event_type: Option<String>,
    pub amplitude_id: i64,
    pub app: i64,
    pub city: Option<String>,
    pub client_event_time: String,
    pub client_upload_time: String,
    pub country: Option<String>,
    pub data: AmplitudeData,
    pub data_type: String,
    pub device_brand: Option<String>,
    pub device_carrier: Option<String>,
    pub device_family: Option<String>,
    pub device_id: String,
    pub device_manufacturer: Option<String>,
    pub device_model: Option<String>,
    pub device_type: Option<String>,
    pub dma: Option<String>,
    pub event_id: i64,
    pub event_properties: HashMap<String, Value>,
    pub event_time: String,
    pub event_type: String,
    pub global_user_properties: Option<Value>,
    pub group_properties: HashMap<String, Value>,
    pub groups: HashMap<String, Value>,
    pub idfa: Option<String>,
    pub ip_address: Option<String>,
    pub is_attribution_event: Option<bool>,
    pub language: Option<String>,
    pub library: String,
    pub location_lat: Option<f64>,
    pub location_lng: Option<f64>,
    pub os_name: Option<String>,
    pub os_version: Option<String>,
    pub partner_id: Option<String>,
    pub paying: Option<bool>,
    pub plan: HashMap<String, Value>,
    pub platform: Option<String>,
    pub processed_time: String,
    pub region: Option<String>,
    pub sample_rate: Option<f64>,
    pub server_received_time: String,
    pub server_upload_time: String,
    pub session_id: i64,
    pub source_id: Option<String>,
    pub start_version: Option<String>,
    pub user_creation_time: Option<String>,
    pub user_id: String,
    pub user_properties: HashMap<String, Value>,
    pub uuid: String,
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

            let event_type = match amp.event_type.as_str() {
                "session_start" => return Ok(None),
                "[Amplitude] Page Viewed" => "$pageview".to_string(),
                "[Amplitude] Element Clicked" | "[Amplitude] Element Changed" => {
                    "$autocapture".to_string()
                }
                _ => amp.event_type.clone(),
            };

            let distinct_id = amp.user_id.clone();
            let event_uuid = Uuid::parse_str(&amp.uuid).unwrap_or_else(|_| Uuid::now_v7());

            let timestamp =
                chrono::NaiveDateTime::parse_from_str(&amp.event_time, "%Y-%m-%d %H:%M:%S%.f")
                    .or_else(|_| {
                        chrono::NaiveDateTime::parse_from_str(&amp.event_time, "%Y-%m-%d %H:%M:%S")
                    })
                    .map_err(|_| Error::msg("Invalid timestamp format"))?
                    .and_utc();

            let mut properties = amp.event_properties.clone();

            let device_type = match amp.device_type.as_deref() {
                Some("Windows") | Some("Linux") => Some("Desktop"),
                Some("iOS") | Some("Android") => Some("Mobile"),
                _ => None,
            };

            properties.insert(
                "$amplitude_user_id".to_string(),
                Value::String(amp.user_id.clone()),
            );
            properties.insert(
                "$amplitude_device_id".to_string(),
                Value::String(amp.device_id.clone()),
            );
            properties.insert(
                "$amplitude_event_id".to_string(),
                Value::Number(amp.event_id.into()),
            );
            properties.insert(
                "$amplitude_session_id".to_string(),
                Value::Number(amp.session_id.into()),
            );
            properties.insert(
                "$device_id".to_string(),
                Value::String(amp.device_id.clone()),
            );

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
