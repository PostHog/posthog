use std::collections::HashMap;

use anyhow::Error;
use celes::Country;
use chrono::{DateTime, Duration, Utc};
use common_types::{CapturedEvent, InternallyCapturedEvent, RawEvent};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use tracing::error;
use uuid::Uuid;

/// UUID namespace for generating deterministic UUIDs from Mixpanel $insert_id values.
/// This allows deduplication of events that may be imported multiple times.
/// Generated using `uuidgen` - this is a random UUID that serves as our namespace.
const MIXPANEL_INSERT_ID_NAMESPACE: Uuid = Uuid::from_bytes(*b"posthog_mixpanel");

use super::TransformContext;
use crate::parse::format::{extract_between, extract_field_name, UserFacingParseError};

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub struct MixpanelContentConfig {
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
    timestamp: i64,
    distinct_id: Option<String>,
    // Some Mixpanel exports carry identity on these fields rather than on
    // distinct_id. $user_id is the identified user; $device_id is the anonymous
    // device before identification.
    #[serde(rename = "$user_id")]
    user_id: Option<String>,
    #[serde(rename = "$device_id")]
    device_id: Option<String>,
    #[serde(flatten)]
    other: HashMap<String, Value>,
}

/// Implement schema-specific error messages for MixpanelEvent
/// That we can surface to the user to let them know what's wrong with the
/// data set they are trying to import
impl UserFacingParseError for MixpanelEvent {
    fn user_facing_schema_error(err: &serde_json::Error) -> String {
        let err_str = err.to_string();

        if err_str.contains("missing field") {
            if let Some(field_name) = extract_field_name(&err_str, "missing field `", "`") {
                return match field_name.as_str() {
                    "event" => "Missing required field 'event'. Each Mixpanel event must have an 'event' field with the event name (e.g., \"event\": \"page_view\").".to_string(),
                    "properties" => "Missing required field 'properties'. Each Mixpanel event must have a 'properties' object containing at least the 'time' field.".to_string(),
                    "time" => "Missing required field 'time' in 'properties'. Each Mixpanel event must have a timestamp (e.g., \"properties\": {\"time\": 1697379000}).".to_string(),
                    _ => format!("Missing required field '{field_name}'. Please check that your Mixpanel export includes this field."),
                };
            }
        }

        if err_str.contains("invalid type:") {
            let got = extract_between(&err_str, "invalid type: ", ", expected");
            let expected = extract_between(&err_str, "expected ", " at line");

            if let (Some(got), Some(expected)) = (got, expected) {
                if err_str.contains("`event`") || (expected == "a string" && err.column() < 15) {
                    return format!(
                        "The 'event' field must be a string (e.g., \"event\": \"page_view\"), but got {got}."
                    );
                }
                if err_str.contains("`time`") || expected.contains("i64") {
                    return format!(
                        "The 'time' field must be a Unix timestamp (integer), but got {got}. Use seconds since epoch (e.g., 1697379000)."
                    );
                }
                if expected.contains("map") || expected.contains("struct") {
                    return format!(
                        "Expected an object/map but got {got}. The 'properties' field must be a JSON object like {{\"time\": 1697379000}}."
                    );
                }
            }
        }

        // Fallback to generic message
        "The JSON structure doesn't match the expected Mixpanel event format. Required fields: 'event' (string), 'properties' (object with 'time' as integer timestamp).".to_string()
    }
}

// Based off sample data provided by customer.
impl MixpanelEvent {
    pub fn parse_fn(
        context: TransformContext,
        timestamp_offset: Duration,
        event_transform: impl Fn(RawEvent) -> Result<Option<RawEvent>, Error>,
    ) -> impl Fn(Self) -> Result<Vec<InternallyCapturedEvent>, Error> {
        move |mx| {
            let token = context.token.clone();
            let team_id = context.team_id;

            // Without a resolvable distinct id we cannot attach the event to a
            // person. Minting a random id would create a throwaway person per
            // event, so skip the event and count it instead.
            let Some(distinct_id) = get_distinct_id(&mx.properties) else {
                crate::metrics::mixpanel_event_skipped_no_distinct_id();
                return Ok(vec![]);
            };

            // Generate a deterministic UUID from $insert_id if present, otherwise use random UUIDv7.
            // This allows deduplication of events that may be imported multiple times.
            let event_uuid = mx
                .properties
                .other
                .get("$insert_id")
                .and_then(|v| v.as_str())
                .map(|insert_id| Uuid::new_v5(&MIXPANEL_INSERT_ID_NAMESPACE, insert_id.as_bytes()))
                .unwrap_or_else(Uuid::now_v7);

            // Was seeing timestamp values come in that were in seconds, not milliseconds
            // Do a quick heuristic check on the size of the timestamp to determine if it's in seconds or milliseconds
            let timestamp_value = mx.properties.timestamp;
            let timestamp_seconds = if timestamp_value > 10_000_000_000 {
                timestamp_value / 1000
            } else {
                timestamp_value
            };

            // We don't support subsecond precision for historical imports
            let timestamp = DateTime::<Utc>::from_timestamp(timestamp_seconds, 0)
                .ok_or(Error::msg("Invalid timestamp"))?
                + timestamp_offset;

            let user_id = non_empty(&mx.properties.user_id);
            let device_id = non_empty(&mx.properties.device_id);

            let properties = map_geoip_props(mx.properties.other);
            let mut properties = remove_mp_props(properties);

            if let Some(user_id) = &user_id {
                properties.insert(
                    "$mixpanel_user_id".to_string(),
                    Value::String(user_id.clone()),
                );
            }
            if let Some(device_id) = &device_id {
                properties.insert(
                    "$mixpanel_device_id".to_string(),
                    Value::String(device_id.clone()),
                );
            }

            // Promote recognised properties onto the person, so profiles are not
            // left empty. Ingestion writes person properties only from set/set_once.
            let (set, set_once) = build_person_properties(&properties);

            let properties = add_source_data(properties, context.job_id);

            let raw_event = RawEvent {
                token: Some(token.clone()),
                distinct_id: Some(Value::String(distinct_id.clone())),
                uuid: Some(event_uuid),
                event: map_event_names(mx.event),
                properties,
                // We send timestamps in iso 8601 format
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

            // Link the device to the user the first time we see the pair, so their
            // events resolve to one person. Mirrors the Amplitude importer.
            if context.generate_identify_events {
                if let (Some(user_id), Some(device_id)) = (&user_id, &device_id) {
                    match context
                        .identify_cache
                        .has_seen_user_device(team_id, user_id, device_id)
                    {
                        Ok(false) => {
                            let identify_event = create_identify_event(
                                team_id,
                                &token,
                                user_id,
                                device_id,
                                Uuid::now_v7(),
                                timestamp,
                            )?;
                            events.push(identify_event);

                            if let Err(e) = context
                                .identify_cache
                                .mark_seen_user_device(team_id, user_id, device_id)
                            {
                                error!(
                                    "Failed to mark seen in identify cache for team {team_id}: {e}"
                                );
                            }
                        }
                        Ok(true) => {}
                        Err(e) => {
                            error!("Failed to check identify cache for team {team_id}: {e}")
                        }
                    }
                }
            }

            // Only emit the event itself if import_events is enabled
            if context.import_events {
                let inner = CapturedEvent {
                    uuid: event_uuid,
                    distinct_id,
                    session_id: None,
                    ip: "127.0.0.1".to_string(),
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

fn non_empty(value: &Option<String>) -> Option<String> {
    value.as_ref().filter(|s| !s.is_empty()).cloned()
}

// PostHog-canonical properties that describe the person's latest session. Copied
// onto $set so the profile reflects the most recent values.
const PERSON_SET_KEYS: &[&str] = &[
    "$browser",
    "$browser_version",
    "$os",
    "$os_version",
    "$device",
    "$device_type",
    "$current_url",
    "$referrer",
    "$referring_domain",
    "$geoip_city_name",
    "$geoip_subdivision_1_name",
    "$geoip_country_code",
    "$geoip_country_name",
];

// First-touch properties. Copied onto $set_once so later events do not overwrite
// the first value seen for the person.
const PERSON_SET_ONCE_KEYS: &[&str] = &[
    "$initial_referrer",
    "$initial_referring_domain",
    "$initial_utm_source",
    "$initial_utm_medium",
    "$initial_utm_campaign",
    "$initial_utm_content",
    "$initial_utm_term",
];

fn build_person_properties(
    properties: &HashMap<String, Value>,
) -> (HashMap<String, Value>, HashMap<String, Value>) {
    let collect = |keys: &[&str]| {
        keys.iter()
            .filter_map(|key| properties.get(*key).map(|v| (key.to_string(), v.clone())))
            .collect()
    };

    (collect(PERSON_SET_KEYS), collect(PERSON_SET_ONCE_KEYS))
}

/// Create a PostHog $identify event that links a Mixpanel device id to a user id.
fn create_identify_event(
    team_id: i32,
    token: &str,
    user_id: &str,
    device_id: &str,
    event_uuid: Uuid,
    timestamp: DateTime<Utc>,
) -> Result<InternallyCapturedEvent, Error> {
    let mut properties = serde_json::Map::new();
    properties.insert(
        "$anon_distinct_id".to_string(),
        Value::String(device_id.to_string()),
    );
    properties.insert(
        "$mixpanel_user_id".to_string(),
        Value::String(user_id.to_string()),
    );
    properties.insert(
        "$mixpanel_device_id".to_string(),
        Value::String(device_id.to_string()),
    );
    properties.insert("historical_migration".to_string(), Value::Bool(true));
    properties.insert(
        "analytics_source".to_string(),
        Value::String("mixpanel".to_string()),
    );

    let raw_event = RawEvent {
        token: Some(token.to_string()),
        distinct_id: Some(Value::String(user_id.to_string())),
        uuid: Some(event_uuid),
        event: "$identify".to_string(),
        properties: properties.into_iter().collect(),
        timestamp: Some(timestamp.to_rfc3339()),
        set: None,
        set_once: None,
        offset: None,
    };

    let inner = CapturedEvent {
        uuid: event_uuid,
        distinct_id: user_id.to_string(),
        session_id: None,
        ip: "127.0.0.1".to_string(),
        data: serde_json::to_string(&raw_event)?,
        now: Utc::now().to_rfc3339(),
        sent_at: None,
        token: token.to_string(),
        event: "$identify".to_string(),
        timestamp,
        is_cookieless_mode: false,
        historical_migration: true,
    };

    Ok(InternallyCapturedEvent { team_id, inner })
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
    if let Some(distinct_id) = resolve_distinct_id(props) {
        return Some(distinct_id);
    }

    // Fall back to identity carried on $user_id / $device_id, which some exports
    // use instead of distinct_id.
    non_empty(&props.user_id).or_else(|| non_empty(&props.device_id))
}

fn resolve_distinct_id(props: &MixpanelProperties) -> Option<String> {
    let distinct_id = non_empty(&props.distinct_id);

    let before_identity = props
        .other
        .get("$distinct_id_before_identity")
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty());

    // Without a before-identity id, the set distinct id is the best we have.
    let Some(before_identity) = before_identity else {
        return distinct_id;
    };

    // If we don't have a distinct ID, return the before identity
    let Some(distinct_id) = distinct_id else {
        return Some(before_identity.to_string());
    };

    // For an anonymous distinct id, prefer the stable before-identity id.
    if distinct_id.starts_with("$device:") || is_anonymous_device_id(&distinct_id) {
        return Some(before_identity.to_string());
    }

    Some(distinct_id)
}

// Mixpanel device ids read as uppercase hex UUIDs (e.g. "1A2B3C4D-...").
// Require at least one uppercase letter so a purely numeric user id is not
// mistaken for a device id and discarded.
fn is_anonymous_device_id(id: &str) -> bool {
    id.chars().any(|c| c.is_ascii_uppercase())
        && id
            .chars()
            .all(|c| c.is_ascii_uppercase() || c == '-' || c.is_ascii_digit())
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

fn add_source_data(
    mut props: HashMap<String, Value>,
    job_id: uuid::Uuid,
) -> HashMap<String, Value> {
    props.insert("historical_migration".to_string(), Value::Bool(true));
    props.insert(
        "analytics_source".to_string(),
        Value::String("mixpanel".to_string()),
    );
    props.insert(
        "$import_job_id".to_string(),
        Value::String(job_id.to_string()),
    );
    props
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn identity_transform(event: RawEvent) -> Result<Option<RawEvent>, Error> {
        Ok(Some(event))
    }

    fn test_context(job_id: Uuid) -> TransformContext {
        TransformContext {
            team_id: 123,
            token: "test_token".to_string(),
            job_id,
            identify_cache: std::sync::Arc::new(crate::cache::MockIdentifyCache::new()),
            group_cache: std::sync::Arc::new(crate::cache::MockGroupCache::new()),
            import_events: true,
            generate_identify_events: false,
            generate_group_identify_events: false,
        }
    }

    fn props(distinct_id: Option<&str>, other: HashMap<String, Value>) -> MixpanelProperties {
        MixpanelProperties {
            timestamp: 1697379000,
            distinct_id: distinct_id.map(str::to_string),
            user_id: None,
            device_id: None,
            other,
        }
    }

    fn parse_one(context: TransformContext, event: MixpanelEvent) -> RawEvent {
        let parser = MixpanelEvent::parse_fn(context, Duration::seconds(0), identity_transform);
        let result = parser(event).unwrap();
        let captured = result.into_iter().next().unwrap();
        serde_json::from_str(&captured.inner.data).unwrap()
    }

    #[test]
    fn test_job_id_in_mixpanel_event() {
        let test_job_id = Uuid::now_v7();
        let mx_event = MixpanelEvent {
            event: "test_event".to_string(),
            properties: props(Some("user123"), HashMap::new()),
        };

        let data = parse_one(test_context(test_job_id), mx_event);

        assert_eq!(
            data.properties.get("$import_job_id"),
            Some(&json!(test_job_id.to_string()))
        );
        assert_eq!(
            data.properties.get("historical_migration"),
            Some(&json!(true))
        );
        assert_eq!(
            data.properties.get("analytics_source"),
            Some(&json!("mixpanel"))
        );
    }

    #[test]
    fn test_mixpanel_event_has_historical_migration_and_now_fields() {
        let before_test = Utc::now();
        let mx_event = MixpanelEvent {
            event: "test_event".to_string(),
            properties: props(Some("user123"), HashMap::new()),
        };

        let parser = MixpanelEvent::parse_fn(
            test_context(Uuid::now_v7()),
            Duration::seconds(0),
            identity_transform,
        );
        let result = parser(mx_event).unwrap();
        let result = result.into_iter().next().unwrap();

        let after_test = Utc::now();

        assert!(
            result.inner.historical_migration,
            "historical_migration field must be true for batch import events"
        );
        assert!(
            !result.inner.now.is_empty(),
            "now field must be set for events"
        );

        let now_timestamp = chrono::DateTime::parse_from_rfc3339(&result.inner.now)
            .expect("now should be valid RFC3339 timestamp")
            .with_timezone(&Utc);
        assert!(
            now_timestamp >= before_test && now_timestamp <= after_test,
            "now timestamp should be current (between test start and end)"
        );
    }

    #[test]
    fn test_deterministic_uuid_from_insert_id() {
        let make_event = || {
            let mut other = HashMap::new();
            other.insert("$insert_id".to_string(), json!("unique_insert_id_123"));
            MixpanelEvent {
                event: "test_event".to_string(),
                properties: props(Some("user123"), other),
            }
        };

        let parser1 = MixpanelEvent::parse_fn(
            test_context(Uuid::now_v7()),
            Duration::seconds(0),
            identity_transform,
        );
        let parser2 = MixpanelEvent::parse_fn(
            test_context(Uuid::now_v7()),
            Duration::seconds(0),
            identity_transform,
        );

        let result1 = parser1(make_event()).unwrap().into_iter().next().unwrap();
        let result2 = parser2(make_event()).unwrap().into_iter().next().unwrap();

        assert_eq!(
            result1.inner.uuid, result2.inner.uuid,
            "Events with the same $insert_id should have the same deterministic UUID"
        );

        let expected_uuid = Uuid::new_v5(&MIXPANEL_INSERT_ID_NAMESPACE, b"unique_insert_id_123");
        assert_eq!(
            result1.inner.uuid, expected_uuid,
            "UUID should be generated using UUID v5 from $insert_id"
        );
    }

    #[test]
    fn test_random_uuid_without_insert_id() {
        let make_event = || MixpanelEvent {
            event: "test_event".to_string(),
            properties: props(Some("user123"), HashMap::new()),
        };

        let parser = MixpanelEvent::parse_fn(
            test_context(Uuid::now_v7()),
            Duration::seconds(0),
            identity_transform,
        );

        let result1 = parser(make_event()).unwrap().into_iter().next().unwrap();
        let result2 = parser(make_event()).unwrap().into_iter().next().unwrap();

        assert_ne!(
            result1.inner.uuid, result2.inner.uuid,
            "Events without $insert_id should have different random UUIDs"
        );
    }

    #[test]
    fn test_event_without_any_distinct_id_is_skipped() {
        // Previously this minted a random UUID per event, creating a throwaway
        // person each time. Now the event is dropped instead.
        let mx_event = MixpanelEvent {
            event: "test_event".to_string(),
            properties: props(None, HashMap::new()),
        };

        let parser = MixpanelEvent::parse_fn(
            test_context(Uuid::now_v7()),
            Duration::seconds(0),
            identity_transform,
        );
        assert!(parser(mx_event).unwrap().is_empty());
    }

    #[test]
    fn test_distinct_id_falls_back_to_device_id() {
        let mut event = MixpanelEvent {
            event: "test_event".to_string(),
            properties: props(None, HashMap::new()),
        };
        event.properties.device_id = Some("DEVICE-ABC".to_string());

        let parser = MixpanelEvent::parse_fn(
            test_context(Uuid::now_v7()),
            Duration::seconds(0),
            identity_transform,
        );
        let captured = parser(event).unwrap().into_iter().next().unwrap();
        assert_eq!(captured.inner.distinct_id, "DEVICE-ABC");
    }

    #[test]
    fn test_distinct_id_falls_back_to_user_id() {
        let mut event = MixpanelEvent {
            event: "test_event".to_string(),
            properties: props(None, HashMap::new()),
        };
        event.properties.user_id = Some("user-42".to_string());
        event.properties.device_id = Some("DEVICE-ABC".to_string());

        let parser = MixpanelEvent::parse_fn(
            test_context(Uuid::now_v7()),
            Duration::seconds(0),
            identity_transform,
        );
        let captured = parser(event).unwrap().into_iter().next().unwrap();
        // The identified user id wins over the device id.
        assert_eq!(captured.inner.distinct_id, "user-42");
    }

    #[test]
    fn test_numeric_distinct_id_is_not_treated_as_anonymous() {
        // A purely numeric user id used to be discarded in favour of the device
        // id under $distinct_id_before_identity.
        let mut other = HashMap::new();
        other.insert(
            "$distinct_id_before_identity".to_string(),
            json!("DEVICE-UUID"),
        );
        let mx_event = MixpanelEvent {
            event: "test_event".to_string(),
            properties: props(Some("12345"), other),
        };

        let captured = MixpanelEvent::parse_fn(
            test_context(Uuid::now_v7()),
            Duration::seconds(0),
            identity_transform,
        )(mx_event)
        .unwrap()
        .into_iter()
        .next()
        .unwrap();
        assert_eq!(captured.inner.distinct_id, "12345");
    }

    #[test]
    fn test_uppercase_device_id_still_prefers_before_identity() {
        let mut other = HashMap::new();
        other.insert(
            "$distinct_id_before_identity".to_string(),
            json!("stable-id"),
        );
        let mx_event = MixpanelEvent {
            event: "test_event".to_string(),
            properties: props(Some("1A2B-3C4D"), other),
        };

        let captured = MixpanelEvent::parse_fn(
            test_context(Uuid::now_v7()),
            Duration::seconds(0),
            identity_transform,
        )(mx_event)
        .unwrap()
        .into_iter()
        .next()
        .unwrap();
        assert_eq!(captured.inner.distinct_id, "stable-id");
    }

    #[test]
    fn test_person_properties_populate_set_and_set_once() {
        let mut other = HashMap::new();
        other.insert("$browser".to_string(), json!("Chrome"));
        other.insert("mp_country_code".to_string(), json!("US"));
        other.insert("$initial_utm_source".to_string(), json!("google"));
        let mx_event = MixpanelEvent {
            event: "test_event".to_string(),
            properties: props(Some("user123"), other),
        };

        let data = parse_one(test_context(Uuid::now_v7()), mx_event);

        let set = data.set.expect("set should be populated");
        assert_eq!(set.get("$browser"), Some(&json!("Chrome")));
        assert_eq!(set.get("$geoip_country_code"), Some(&json!("US")));

        let set_once = data.set_once.expect("set_once should be populated");
        assert_eq!(set_once.get("$initial_utm_source"), Some(&json!("google")));
    }

    #[test]
    fn test_identify_event_injected_for_user_device_pair() {
        let mut context = test_context(Uuid::now_v7());
        context.generate_identify_events = true;

        let mut event = MixpanelEvent {
            event: "test_event".to_string(),
            properties: props(Some("user-42"), HashMap::new()),
        };
        event.properties.user_id = Some("user-42".to_string());
        event.properties.device_id = Some("DEVICE-ABC".to_string());

        let parser = MixpanelEvent::parse_fn(context, Duration::seconds(0), identity_transform);
        let result = parser(event).unwrap();

        assert_eq!(result.len(), 2, "expected an identify event plus the event");
        let identify: RawEvent = serde_json::from_str(&result[0].inner.data).unwrap();
        assert_eq!(identify.event, "$identify");
        assert_eq!(identify.distinct_id, Some(json!("user-42")));
        assert_eq!(
            identify.properties.get("$anon_distinct_id"),
            Some(&json!("DEVICE-ABC"))
        );
    }
}
