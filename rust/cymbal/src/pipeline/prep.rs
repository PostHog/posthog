use std::collections::HashMap;

use chrono::{DateTime, Duration, Utc};
use common_types::{
    format::{format_ch_datetime, parse_datetime_assuming_utc},
    CapturedEvent, ClickHouseEvent, PersonMode, RawEvent, Team,
};
use serde_json::Value;
use tracing::warn;

use crate::{
    error::{EventError, PipelineFailure, PipelineResult},
    recursively_sanitize_properties, sanitize_string,
};

use super::{exception::add_error_to_event, IncomingEvent};

// Adds team info, and folds set, set_once and ip address data into the event properties
pub fn prepare_events(
    events: Vec<IncomingEvent>,
    teams_lut: HashMap<String, Option<Team>>,
) -> Result<Vec<PipelineResult>, PipelineFailure> {
    let mut buffer = Vec::with_capacity(events.len());

    for (i, event) in events.into_iter().enumerate() {
        match event {
            IncomingEvent::ClickhouseReady(event) => {
                buffer.push(Ok(event));
            }
            IncomingEvent::Captured(outer) => {
                let maybe_team = teams_lut
                    .get(&sanitize_string(outer.token.to_string()))
                    .expect("Team lookup table is fully populated");

                let Some(team) = maybe_team else {
                    warn!("Received event for unknown team token: {}", outer.token);
                    buffer.push(Err(EventError::NoTeamForToken(outer.token)));
                    continue;
                };

                // If we get an event we can't deserialize at all, we have to drop it. This is a rare
                // case where we put the whole event into the error, so we can DLQ it later for offline
                // analysis
                let mut raw_event: Value = match serde_json::from_str(&outer.data) {
                    Ok(event) => event,
                    Err(e) => {
                        buffer.push(Err(EventError::FailedToDeserialize(
                            Box::new(outer.clone()),
                            format!("{e:?}"),
                        )));
                        continue;
                    }
                };

                // If we fail to sanitize the event, we should discard it as unprocessable
                if let Err(e) = recursively_sanitize_properties(outer.uuid, &mut raw_event, 0) {
                    buffer.push(Err(e));
                    continue;
                }

                // We've seen invalid (string) offsets come in, I /think/ from django capture. Rather than dropping the whole
                // event, we just check prior to deserialization that the offset is a number, and if not, we discard it.
                let raw_event = sanitize_offset(raw_event);

                // Now parse it out into the relevant structure. At this point, failure to convert from
                // the raw json object to a RawEvent indicates some pipeline error, and we should fail and
                // take lag until it's fixed (so we return an UnhandledError here)
                let raw_event: RawEvent =
                    serde_json::from_value(raw_event).map_err(|e| (i, e.into()))?;

                // Bit of a mouthful, but basically, if the event has a timestamp, try to parse it,
                // and store an event error if we can't. If the event has no timestamp, use the instant
                // the event was captured.
                let timestamp = match &raw_event.timestamp {
                    Some(ts) => parse_datetime_assuming_utc(ts),
                    None => Ok(parse_datetime_assuming_utc(&outer.now)
                        .expect("CapturedEvent::now is always valid")), // Set by capture, should always be valid
                };

                // NOTE: we diverge from analytics ingestion here, by dropping events with an invalid timestamp,
                // rather than passing them through. I think this is reasonable, because we're a new product.
                let timestamp = match timestamp {
                    Ok(ts) => ts,
                    Err(e) => {
                        buffer.push(Err(EventError::InvalidTimestamp(
                            raw_event.timestamp.unwrap_or_default(),
                            e.to_string(),
                        )));
                        continue;
                    }
                };

                let person_mode = get_person_mode(&raw_event, team);
                let event = transform_event(&outer, raw_event, timestamp, person_mode, team);
                buffer.push(Ok(event));
            }
        }
    }

    Ok(buffer)
}

fn transform_event(
    outer: &CapturedEvent,   // Has NOT been sanitized at this point
    mut raw_event: RawEvent, // Has been sanitized at this point
    timestamp: DateTime<Utc>,
    person_mode: PersonMode,
    team: &Team,
) -> ClickHouseEvent {
    if team.anonymize_ips {
        raw_event.properties.remove("$ip");
    } else {
        // Fold the ip the event was sent from into the event properties
        raw_event
            .properties
            .insert("$ip".to_string(), Value::String(outer.ip.clone()));
    }

    // Fold in $set and $set_once properties
    let set = raw_event.set;
    let set_once = raw_event.set_once;

    if let Some(set) = set {
        raw_event
            .properties
            .insert("$set".to_string(), serde_json::to_value(set).unwrap());
    }

    if let Some(set_once) = set_once {
        raw_event.properties.insert(
            "$set_once".to_string(),
            serde_json::to_value(set_once).unwrap(),
        );
    }

    let mut sent_at = outer
        .get_sent_at_as_rfc3339()
        .map(|sa| parse_datetime_assuming_utc(&sa).expect("sent_at is a valid datetime"));

    if raw_event
        .properties
        .get("$ignore_sent_at")
        .and_then(|f| f.as_bool())
        .unwrap_or_default()
    {
        sent_at = None;
    }

    let now = parse_datetime_assuming_utc(&outer.now).expect("CapturedEvent::now is always valid");

    let timestamp = resolve_timestamp(timestamp, sent_at, now, raw_event.offset);

    let timestamp_was_invalid = timestamp.is_none();

    let timestamp = timestamp.unwrap_or(now);

    let mut event = ClickHouseEvent {
        uuid: outer.uuid,
        team_id: team.id,
        project_id: team.project_id,
        event: raw_event.event,
        distinct_id: sanitize_string(outer.distinct_id.to_string()),
        properties: Some(
            serde_json::to_string(&raw_event.properties)
                .expect("Json data just deserialized can be serialized"),
        ),
        person_id: None,
        timestamp: format_ch_datetime(timestamp),
        created_at: format_ch_datetime(Utc::now()),
        elements_chain: None, // TODO - we skip elements chain extraction for now, but should implement it eventually
        person_created_at: None,
        person_properties: None,
        group0_properties: None,
        group1_properties: None,
        group2_properties: None,
        group3_properties: None,
        group4_properties: None,
        group0_created_at: None,
        group1_created_at: None,
        group2_created_at: None,
        group3_created_at: None,
        group4_created_at: None,
        person_mode,
    };

    if timestamp_was_invalid {
        add_error_to_event(&mut event, "Timestamp was future dated")
            .expect("We can parse the raw event we just serialised")
    }

    // At this point, all event contents have been sanitized
    event
}

// Person mode set to Full by default, Propertyless if $process_person_profile is false
// or the team has person processing disabled
fn get_person_mode(raw_event: &RawEvent, team: &Team) -> PersonMode {
    let event_disables = raw_event
        .properties
        .get("disable_person_processing")
        .is_some_and(|v| v.as_bool().unwrap_or(false));

    if team.person_processing_opt_out.unwrap_or(false) || event_disables {
        PersonMode::Propertyless
    } else {
        PersonMode::Full
    }
}

// This function exists because of https://github.com/PostHog/posthog/blob/6c2f119571edb10a23ec711c6f6e2b6155d76ef9/plugin-server/src/worker/ingestion/timestamps.ts#L81.
// We specifically diverge by only filtering out timestamps dated in the future.
pub fn resolve_timestamp(
    found_timestamp: DateTime<Utc>, // The instant the exception occurred, or was caught.
    _sent_at: Option<DateTime<Utc>>, // The instant the exception was sent by the client. It can diverge from the timestamp in the case of e.g. offline event buffering.
    _now: DateTime<Utc>,             // The moment capture received the event.
    offset: Option<i64>, // An offset, in milliseconds, between the event's timestamp and UTC.
) -> Option<DateTime<Utc>> {
    // The function referenced above attempts to adjust for clock skew between the client sending the event and the
    // server receiving it, but without a way to differentiate between transmission delay and clock skew, this
    // is a bit of a fools errand. We simply do not try to do it, and don't apply any adjustment beyond the offset.
    let found = found_timestamp + Duration::milliseconds(offset.unwrap_or(0));

    if found < Utc::now() + Duration::hours(1) {
        Some(found)
    } else {
        None
    }
}

fn sanitize_offset(raw_event: Value) -> Value {
    let Value::Object(raw_event) = raw_event else {
        return raw_event; // The rest of the pipeline will handle this case
    };

    let Some(offset) = raw_event.get("offset") else {
        return Value::Object(raw_event);
    };

    let raw_event = match offset {
        Value::Number(_) => raw_event,
        _ => {
            let mut raw_event = raw_event;
            raw_event.remove("offset");
            raw_event
        }
    };

    Value::Object(raw_event)
}
