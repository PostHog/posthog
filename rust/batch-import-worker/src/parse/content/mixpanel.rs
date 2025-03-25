use std::collections::HashMap;

use anyhow::Error;
use celes::Country;
use chrono::{DateTime, Duration, Utc};
use common_types::{CapturedEvent, InternallyCapturedEvent, RawEvent};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use uuid::Uuid;

use super::TransformContext;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub struct MixpanelContentConfig {
    #[serde(default)] // Defaults to false
    pub skip_no_distinct_id: bool,
    // We had a customer report that mixpanel used to have a timestamp offsets bug, and they wanted to
    // update all event timestamps as they were being ingested.
    pub timestamp_offset_seconds: Option<i64>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub struct MixpanelEvent {
    event: String,
    properties: MixpanelProperties,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub struct MixpanelProperties {
    #[serde(rename = "time")]
    timestamp_ms: i64,
    distinct_id: Option<String>,
    #[serde(flatten)]
    other: HashMap<String, Value>,
}

// Based off sample data provided by customer.
impl MixpanelEvent {
    pub fn parse_fn(
        context: TransformContext,
        skip_no_distinct_id: bool,
        timestamp_offset: Duration,
        event_transform: impl Fn(RawEvent) -> Result<Option<RawEvent>, Error>,
    ) -> impl Fn(Self) -> Result<Option<InternallyCapturedEvent>, Error> {
        move |mx| {
            let token = context.token.clone();
            let team_id = context.team_id;

            let distinct_id = match (get_distinct_id(&mx.properties), skip_no_distinct_id) {
                (Some(distinct_id), _) => distinct_id,
                (None, true) => return Ok(None),
                (None, false) => Uuid::now_v7().to_string(),
            };

            let event_uuid = Uuid::now_v7();
            // We don't support subsecond precision for historical imports
            let timestamp = DateTime::<Utc>::from_timestamp(mx.properties.timestamp_ms / 1000, 0)
                .ok_or(Error::msg("Invalid timestamp"))?;

            let timestamp = timestamp + timestamp_offset;

            let properties = mx.properties.other;
            let properties = map_geoip_props(properties);
            let properties = remove_mp_props(properties);
            let properties = add_source_data(properties);

            let raw_event = RawEvent {
                token: Some(token.clone()),
                distinct_id: Some(Value::String(distinct_id.clone())),
                uuid: Some(event_uuid),
                event: map_event_names(mx.event),
                properties,
                // We send timestamps in iso 8601 format
                timestamp: Some(timestamp.to_rfc3339()),
                set: None,
                set_once: None,
                offset: None,
            };

            let Some(raw_event) = event_transform(raw_event)? else {
                return Ok(None);
            };

            let inner = CapturedEvent {
                uuid: event_uuid,
                distinct_id,
                ip: "127.0.0.1".to_string(),
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

// Maps mixpanel event names to posthog event names
pub fn map_event_names(event: String) -> String {
    // TODO - add more as you find them
    match event.as_str() {
        "$mp_web_page_view" => "$pageview".to_string(),
        _ => event,
    }
}

fn get_distinct_id(props: &MixpanelProperties) -> Option<String> {
    let distinct_id = props.distinct_id.clone();
    let Some(before_identity) = props.other.get("$distinct_id_before_identity") else {
        return distinct_id;
    };

    // If it's not a string, return the set distinct ID
    let Some(before_identity) = before_identity.as_str() else {
        return distinct_id;
    };

    // If we don't have a distinct ID, return the before identity
    let Some(distinct_id) = distinct_id else {
        return Some(before_identity.to_string());
    };

    // If the distinct_id starts with "$device:", it's an anonymous ID
    if distinct_id.starts_with("$device:") {
        return Some(before_identity.to_string());
    }

    // If the distinct_id contains only uppercase letters and dashes, it's an anonymous ID
    if distinct_id
        .chars()
        .all(|c| c.is_ascii_uppercase() || c == '-' || c.is_ascii_digit())
    {
        return Some(before_identity.to_string());
    }

    // We default to using the distinct ID
    Some(distinct_id)
}

const GEOIP_PROP_MAPPINGS: &[(&str, &str)] = &[
    ("$city", "$geoip_city_name"),
    ("$region", "$geoip_subdivision_1_name"),
    ("mp_country_code", "$geoip_country_code"),
];

fn map_geoip_props(mut props: HashMap<String, Value>) -> HashMap<String, Value> {
    for (from, to) in GEOIP_PROP_MAPPINGS {
        if let Some(value) = props.remove(*from) {
            props.insert(to.to_string(), value);
        }
    }

    if let Some(code) = props.get("$geoip_country_code").and_then(|c| c.as_str()) {
        if let Some(country_name) = map_country_code(code) {
            props.insert(
                "$geoip_country_name".to_string(),
                Value::String(country_name),
            );
        }
    }

    props
}

// We have to do some mapping because maxmind doesn't precisely follow ISO3166
// Names taken from: http://www.geonames.org/countries/
const LONG_NAME_MAP: &[(&str, &str)] = &[
    ("The United States of America", "United States"),
    (
        "The United Kingdom Of Great Britain And Northern Ireland",
        "United Kingdom",
    ),
    ("The United Arab Emirates", "United Arab Emirates"),
];

fn map_country_code(code: &str) -> Option<String> {
    let country = Country::from_alpha2(code).ok()?;

    for (long_name, short_name) in LONG_NAME_MAP {
        if country.long_name == *long_name {
            return Some(short_name.to_string());
        }
    }

    Some(country.long_name.to_string())
}

const MP_PROPS_TO_REMOVE: &[&str] = &[
    "$mp_api_endpoint",
    "mp_processing_time_ms",
    "$insert_id",
    "$geo_source",
    "$mp_api_timestamp_ms",
];

fn remove_mp_props(mut props: HashMap<String, Value>) -> HashMap<String, Value> {
    for prop in MP_PROPS_TO_REMOVE {
        props.remove(*prop);
    }

    props
}

fn add_source_data(mut props: HashMap<String, Value>) -> HashMap<String, Value> {
    props.insert("historical_migration".to_string(), Value::Bool(true));
    props.insert(
        "analytics_source".to_string(),
        Value::String("mixpanel".to_string()),
    );
    props
}
