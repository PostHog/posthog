use std::{
    collections::{hash_map::Entry, HashMap},
    sync::Arc,
};

use app_context::AppContext;
use chrono::{DateTime, NaiveDateTime, Utc};
use common_types::ClickHouseEvent;
use error::{EventError, UnhandledError};
use fingerprinting::generate_fingerprint;
use issue_resolution::resolve_issue;
use metric_consts::FRAME_RESOLUTION;
use serde_json::Value;
use tracing::{error, warn};
use types::{FingerprintedErrProps, RawErrProps, Stacktrace};
use uuid::Uuid;

pub mod app_context;
pub mod config;
pub mod error;
pub mod fingerprinting;
pub mod frames;
pub mod issue_resolution;
pub mod langs;
pub mod metric_consts;
pub mod posthog_utils;
pub mod symbol_store;
pub mod types;

pub async fn handle_events(
    context: Arc<AppContext>,
    mut events: Vec<ClickHouseEvent>,
) -> Result<Vec<ClickHouseEvent>, (usize, UnhandledError)> {
    // First pass through the event list, to get all the exception property sets
    // we'll process. Events we don't get exception properties from will be skipped
    // in all the following passes
    let mut indexed_props = Vec::new();
    for (index, event) in events.iter_mut().enumerate() {
        match get_props(event) {
            Ok(r) => indexed_props.push((index, r)),
            Err(e) => {
                warn!(team = event.team_id, "Failed to get props: {}", e);
                if let Err(e) = add_error_to_event(event, e) {
                    // If we fail to add an error to an event, we just log it.
                    // This can happen if we failed to read the properties
                    // of the event at all, e.g. due to a serde recursion limit.
                    error!(team = event.team_id, "Failed to add error to event: {}", e);
                }
                continue;
            }
        };
    }

    // Freeze the events list as immutable until the final stage, to ensure we don't
    // accidentally mutate or drop an event during processing.
    let events = events;

    // Second pass, to spawn the relevant tokio tasks to resolve the frames
    let mut frame_resolve_handles = HashMap::new();
    for (index, props) in indexed_props.iter_mut() {
        let team_id = events[*index].team_id;
        for exception in props.exception_list.iter_mut() {
            let frames = match exception.stack.take() {
                Some(Stacktrace::Raw { frames }) => {
                    if frames.is_empty() {
                        continue;
                    }
                    frames
                }
                Some(Stacktrace::Resolved { frames }) => {
                    // This stack trace is already resolved, we have no work to do.
                    exception.stack = Some(Stacktrace::Resolved { frames });
                    continue;
                }
                None => {
                    continue; // It was None before and it's none after the take
                }
            };

            for frame in frames.iter() {
                let id = frame.frame_id();
                if frame_resolve_handles.contains_key(&id) {
                    // We've already spawned a task to resolve this frame, so we don't need to do it again.
                    continue;
                }

                // We need a cloned frame to move into the closure below
                let frame = frame.clone();
                let context = context.clone();
                // Spawn a concurrent task for resolving every frame
                let handle = tokio::spawn(async move {
                    context.worker_liveness.report_healthy().await;
                    metrics::counter!(FRAME_RESOLUTION).increment(1);
                    let res = context
                        .resolver
                        .resolve(&frame, team_id, &context.pool, &context.catalog)
                        .await;
                    context.worker_liveness.report_healthy().await;
                    res
                });
                frame_resolve_handles.insert(id, handle);
            }

            // Put the frames back on the exception, now that we're done mutating them until we've
            // gathered our lookup table.
            exception.stack = Some(Stacktrace::Raw { frames });
        }
    }

    // Collect the results of frame resolution
    let mut frame_lookup_table = HashMap::new();
    for (id, handle) in frame_resolve_handles.into_iter() {
        let res = match handle.await.expect("Frame resolve task didn't panic") {
            Ok(r) => r,
            Err(e) => {
                let index = find_index_with_matching_frame_id(&id, &indexed_props);
                return Err((index, e));
            }
        };
        frame_lookup_table.insert(id, res);
    }

    // Third pass, to map the unresolved frames into resolved ones, fingerprint them, and kick
    // off issue resolution for any new fingerprints. This time we consume the RawErrorProps list,
    // converting each entry into a fingerprinted one.
    let mut indexed_fingerprinted = Vec::new();
    let mut issue_handles = HashMap::new();
    for (index, mut props) in indexed_props.into_iter() {
        let event = &events[index];
        let team_id = event.team_id;
        for exception in props.exception_list.iter_mut() {
            exception.stack = exception
                .stack
                .take()
                .map(|s| {
                    s.resolve(&frame_lookup_table).ok_or(UnhandledError::Other(
                        "Stacktrace::resolve returned None".to_string(),
                    ))
                })
                .transpose()
                .map_err(|e| (index, e))?
        }

        let proposed = generate_fingerprint(&props.exception_list);
        let fingerprinted = props.to_fingerprinted(proposed);
        // We do this because the input props might have come with a fingerprint, and if they did, we want to resolve that
        // issue, not the one associated with the generated fingerprint.
        let to_resolve = fingerprinted.fingerprint.clone();
        if let Entry::Vacant(e) = issue_handles.entry(to_resolve.clone()) {
            let name = fingerprinted.exception_list[0].exception_type.clone();
            let description = fingerprinted.exception_list[0].exception_message.clone();
            let event_timestamp = get_event_timestamp(event).unwrap_or_else(|| {
                warn!(
                    event = event.uuid.to_string(),
                    "Failed to get event timestamp, using current time"
                );
                Utc::now()
            });

            let m_fingerprint = to_resolve.clone();
            let m_context = context.clone();
            let handle = tokio::spawn(async move {
                resolve_issue(
                    &m_context,
                    team_id,
                    &m_fingerprint,
                    name,
                    description,
                    event_timestamp,
                )
                .await
            });
            e.insert(handle);
        }

        indexed_fingerprinted.push((index, fingerprinted));
    }

    // Collect the results of issue resolution
    let mut resolved_issues = HashMap::new();
    for (fingerprint, handle) in issue_handles.into_iter() {
        let issue_id = match handle.await.expect("issue resolution task did not panic") {
            Ok(id) => id,
            Err(e) => {
                let index =
                    find_index_with_matching_fingerprint(&fingerprint, &indexed_fingerprinted);
                return Err((index, e));
            }
        };
        resolved_issues.insert(fingerprint, issue_id);
    }

    // Fourth pass, to update the events with the resolved issues
    // Unfreeze the events list, since now we have to modify the events we processed
    let mut events = events;
    for (index, fingerprinted) in indexed_fingerprinted.into_iter() {
        let event = &mut events[index];
        let issue_id = resolved_issues
            .get(&fingerprinted.fingerprint)
            .cloned()
            .expect("Issue was resolved");
        let output = fingerprinted.to_output(issue_id);
        event.properties = Some(serde_json::to_string(&output).map_err(|e| (index, e.into()))?);
    }

    Ok(events)
}

pub fn get_props(event: &ClickHouseEvent) -> Result<RawErrProps, EventError> {
    if event.event != "$exception" {
        return Err(EventError::WrongEventType(event.event.clone(), event.uuid));
    }

    let Some(properties) = &event.properties else {
        return Err(EventError::NoProperties(event.uuid));
    };

    let mut properties: Value = match serde_json::from_str(properties) {
        Ok(r) => r,
        Err(e) => {
            return Err(EventError::InvalidProperties(event.uuid, e.to_string()));
        }
    };

    if let Some(v) = properties
        .as_object_mut()
        .and_then(|o| o.get_mut("$exception_list"))
    {
        // We PG sanitize the exception list, because the strings in it can end up in PG kind of arbitrarily.
        recursively_sanitize_properties(event.uuid, v, 0)?;
    }

    let props: RawErrProps = match serde_json::from_value(properties) {
        Ok(r) => r,
        Err(e) => {
            return Err(EventError::InvalidProperties(event.uuid, e.to_string()));
        }
    };

    if props.exception_list.is_empty() {
        return Err(EventError::EmptyExceptionList(event.uuid));
    }

    Ok(props)
}

// Remove null bytes from all strings found in an arbitrary JSON structure.
fn recursively_sanitize_properties(
    id: Uuid,
    value: &mut Value,
    depth: usize,
) -> Result<(), EventError> {
    if depth > 64 {
        // We don't want to recurse too deeply, in case we have a circular reference or something.
        return Err(EventError::InvalidProperties(
            id,
            "Recursion limit exceeded".to_string(),
        ));
    }
    match value {
        Value::Object(map) => {
            for (_, v) in map.iter_mut() {
                recursively_sanitize_properties(id, v, depth + 1)?;
            }
        }
        Value::Array(arr) => {
            for v in arr.iter_mut() {
                recursively_sanitize_properties(id, v, depth + 1)?;
            }
        }
        Value::String(s) => {
            if needs_sanitization(s) {
                warn!("Sanitizing null bytes from string in event {}", id);
                *s = sanitize_string(s.clone());
            }
        }
        _ => {}
    }
    Ok(())
}

// Postgres doesn't like nulls (u0000) in strings, so we replace them with uFFFD.
pub fn sanitize_string(s: String) -> String {
    s.replace('\u{0000}', "\u{FFFD}")
}

pub fn needs_sanitization(s: &str) -> bool {
    s.contains('\u{0000}')
}

// This is expensive, since it round-trips the event through JSON.
// We could maybe change ClickhouseEvent to only do serde at the edges
pub fn add_error_to_event(
    event: &mut ClickHouseEvent,
    e: impl ToString,
) -> Result<(), UnhandledError> {
    let mut props = event.take_raw_properties()?;
    let mut errors = match props.remove("$cymbal_errors") {
        Some(serde_json::Value::Array(errors)) => errors,
        _ => Vec::new(),
    };

    errors.push(serde_json::Value::String(e.to_string()));
    props.insert(
        "$cymbal_errors".to_string(),
        serde_json::Value::Array(errors),
    );
    event.set_raw_properties(props)?;
    Ok(())
}

// "Clickhouse format" timestamps are in UTC, with no timezone information, e.g. "2021-08-02 12:34:56.789"
// TODO - we could make use of common_kafka::kafka_messages::de/serialise_datetime here, but that drops
// the fractional seconds, which we might want to keep? For now, go with this, we can consolidate later.
pub fn get_event_timestamp(event: &ClickHouseEvent) -> Option<DateTime<Utc>> {
    NaiveDateTime::parse_from_str(&event.timestamp, "%Y-%m-%d %H:%M:%S%.f")
        .map(|ndt| ndt.and_utc())
        .ok()
}

fn find_index_with_matching_frame_id(id: &str, list: &[(usize, RawErrProps)]) -> usize {
    for (index, props) in list.iter() {
        for exception in props.exception_list.iter() {
            if let Some(Stacktrace::Raw { frames }) = &exception.stack {
                for frame in frames {
                    if frame.frame_id() == id {
                        return *index;
                    }
                }
            }
        }
    }
    0
}

fn find_index_with_matching_fingerprint(
    fingerprint: &str,
    list: &[(usize, FingerprintedErrProps)],
) -> usize {
    for (index, props) in list.iter() {
        if props.fingerprint == fingerprint {
            return *index;
        }
    }
    0
}

#[cfg(test)]
mod test {
    use common_types::{ClickHouseEvent, PersonMode};
    use uuid::Uuid;

    use crate::get_event_timestamp;

    #[test]
    pub fn test_timestamp_parsing() {
        let mut event = ClickHouseEvent {
            uuid: Uuid::now_v7(),
            team_id: 1,
            project_id: 1,
            event: "test".to_string(),
            distinct_id: "test".to_string(),
            properties: None,
            person_id: None,
            timestamp: "2021-08-02 12:34:56.789".to_string(),
            created_at: "2021-08-02 12:34:56.789".to_string(),
            elements_chain: "".to_string(),
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
            person_mode: PersonMode::Propertyless,
        };

        let ts = get_event_timestamp(&event).unwrap();
        assert_eq!(ts.to_rfc3339(), "2021-08-02T12:34:56.789+00:00");

        event.timestamp = "invalid".to_string();

        let ts = get_event_timestamp(&event);
        assert!(ts.is_none());
    }
}
