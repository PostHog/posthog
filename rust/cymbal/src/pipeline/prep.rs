use std::collections::HashMap;

use chrono::{DateTime, Utc};
use common_types::{CapturedEvent, ClickHouseEvent, PersonMode, RawEvent, Team};
use serde_json::Value;

use crate::{
    error::{EventError, PipelineFailure, PipelineResult},
    recursively_sanitize_properties,
};

use super::{format_ch_timestamp, parse_ts_assuming_utc, IncomingEvent};

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
                    .get(&outer.token)
                    .expect("Team lookup table is fully populated");

                let Some(team) = maybe_team else {
                    buffer.push(Err(EventError::NoTeamForToken(outer.token)));
                    continue;
                };

                // If we get an event we can't deserialize at all, that indicates a pipeline bug,
                // so return a PipelineFailure
                let mut raw_event: Value =
                    serde_json::from_str(&outer.data).map_err(|e| (i, e.into()))?;

                // If we fail to sanitize the event, we should discard it as unprocessable
                if let Err(e) = recursively_sanitize_properties(outer.uuid, &mut raw_event, 30) {
                    buffer.push(Err(e));
                    continue;
                }

                // Now parse it out into the relevant structure. Same reasoning as above re:
                // returning a PipelineFailure
                let raw_event: RawEvent =
                    serde_json::from_value(raw_event).map_err(|e| (i, e.into()))?;

                // Bit of a mouthful, but basically, if the event has a timestamp, try to parse it,
                // and store an event error if we can't. If the event has no timestamp, use the current time.
                let timestamp = match &raw_event.timestamp {
                    Some(ts) => parse_ts_assuming_utc(ts),
                    None => Ok(Utc::now()),
                };

                // TODO - should we drop these, or should we add an error to the event and then pass them through
                // with the timestamp set to now?
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
    outer: &CapturedEvent,
    mut raw_event: RawEvent,
    timestamp: DateTime<Utc>,
    person_mode: PersonMode,
    team: &Team,
) -> ClickHouseEvent {
    // Fold the ip the event was sent from into the event properties
    raw_event
        .properties
        .insert("$ip".to_string(), Value::String(outer.ip.clone()));

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

    // TODO - offset and sent_at handling

    ClickHouseEvent {
        uuid: outer.uuid,
        team_id: team.id,
        project_id: team.project_id,
        event: raw_event.event,
        distinct_id: outer.distinct_id.clone(),
        properties: Some(
            serde_json::to_string(&raw_event.properties)
                .expect("Json data just deserialized can be serialized"),
        ),
        person_id: None,
        timestamp: format_ch_timestamp(timestamp),
        created_at: format_ch_timestamp(Utc::now()),
        elements_chain: None,
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
    }
}

// Person mode set to Full by default, Propertyless if $process_person_profile is false
// or the team has person processing disabled
fn get_person_mode(raw_event: &RawEvent, team: &Team) -> PersonMode {
    let event_disables = raw_event
        .properties
        .get("disable_person_processing")
        .map_or(false, |v| v.as_bool().unwrap_or(false));

    if team.person_processing_opt_out.unwrap_or(false) || event_disables {
        PersonMode::Propertyless
    } else {
        PersonMode::Full
    }
}
