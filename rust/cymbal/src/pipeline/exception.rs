use std::{
    collections::{hash_map::Entry, HashMap},
    sync::Arc,
};

use chrono::Utc;
use common_types::ClickHouseEvent;
use metrics::counter;
use serde_json::Value;
use tracing::{error, warn};
use uuid::Uuid;

use crate::{
    app_context::AppContext,
    assignment_rules::assign_issue,
    error::{EventError, PipelineResult, UnhandledError},
    fingerprinting::generate_fingerprint,
    issue_resolution::{resolve_issue, IssueStatus},
    metric_consts::{FRAME_RESOLUTION, SUPPRESSED_ISSUE_DROPPED_EVENTS},
    recursively_sanitize_properties,
    types::{FingerprintedErrProps, RawErrProps, Stacktrace},
};

use super::parse_ts_assuming_utc;

pub async fn do_exception_handling(
    mut events: Vec<PipelineResult>,
    context: Arc<AppContext>,
) -> Result<Vec<PipelineResult>, (usize, UnhandledError)> {
    // First pass through the event list, to get all the exception property sets
    // we'll process. Events we don't get exception properties from will be skipped
    // in all the following passes
    let mut indexed_props = Vec::new();
    for (index, event) in events.iter_mut().enumerate() {
        let Ok(event) = event else {
            continue; // some earlier stage already caused this event to be dropped, so we don't need to process it further.
        };
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
    // accidentally mutate or drop an event during processing - this ensures tha validity
    // of the indexes in indexed_props.
    let events = events;

    // Second pass, to spawn the relevant tokio tasks to resolve the frames
    let mut frame_resolve_handles = HashMap::new();
    for (index, props) in indexed_props.iter_mut() {
        let team_id = events[*index]
            .as_ref()
            .expect("no events have been dropped since indexed-property gathering")
            .team_id;
        for exception in props.exception_list.iter_mut() {
            exception.exception_id = Some(Uuid::now_v7().to_string());
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
        let Ok(event) = &events[index] else {
            // NOTE: we could "safely" continue here, but it'd be a correctness error I think.
            panic!("Event list modified since indexed property gathering");
        };
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
            let event_timestamp = parse_ts_assuming_utc(&event.timestamp).unwrap_or_else(|e| {
                warn!(
                    event = event.uuid.to_string(),
                    "Failed to get event timestamp, using current time, error: {:?}", e
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
        let issue = match handle.await.expect("issue resolution task did not panic") {
            Ok(i) => i,
            Err(e) => {
                let index =
                    find_index_with_matching_fingerprint(&fingerprint, &indexed_fingerprinted);
                return Err((index, e));
            }
        };
        resolved_issues.insert(fingerprint, issue);
    }

    // Fourth pass, to update the events with the resolved issues
    // Unfreeze the events list, since now we have to modify the events we processed
    let mut events = events;
    let mut to_drop = Vec::new();
    let mut assignment_rule_futs = HashMap::new();
    for (index, fingerprinted) in indexed_fingerprinted.into_iter() {
        let Ok(event) = &mut events[index] else {
            panic!("Event list modified since indexed property gathering");
        };
        let issue = resolved_issues
            .get(&fingerprinted.fingerprint)
            .cloned()
            .expect("Issue was resolved");

        let output = fingerprinted.to_output(issue.id);

        if matches!(issue.status, IssueStatus::Suppressed) {
            to_drop.push((index, issue.id));
        } else if issue.eligible_for_assignment
            && !assignment_rule_futs.contains_key(&issue.id)
            && context.config.auto_assignment_enabled
        {
            assignment_rule_futs.insert(
                issue.id,
                (
                    index,
                    tokio::spawn(assign_issue(context.clone(), issue.clone(), output.clone())),
                ),
            );
        }

        event.properties = Some(serde_json::to_string(&output).map_err(|e| (index, e.into()))?);
    }

    for (index, future) in assignment_rule_futs.into_values() {
        future
            .await
            .expect("assignment task did not panic")
            .map_err(|e| (index, e))?; // Wait on all the assignment rules to finish running
    }

    // Drop the suppressed events, replacing their entries in the event buffer with EventErrors
    // that indicate they were dropped due to being suppressed
    for (index, issue_id) in to_drop.into_iter() {
        counter!(SUPPRESSED_ISSUE_DROPPED_EVENTS).increment(1);
        events[index] = Err(EventError::Suppressed(issue_id));
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
        // TODO - the prep stage has already sanitized the properties, so maybe we don't need to do this again?
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
