use std::sync::Arc;

use app_context::AppContext;
use chrono::{DateTime, Utc};
use common_types::ClickHouseEvent;
use error::{EventError, UnhandledError};
use fingerprinting::generate_fingerprint;
use issue_resolution::resolve_issue;
use metric_consts::FRAME_RESOLUTION;
use tracing::{error, warn};
use types::{Exception, RawErrProps, Stacktrace};

pub mod app_context;
pub mod config;
pub mod error;
pub mod fingerprinting;
pub mod frames;
pub mod hack;
pub mod issue_resolution;
pub mod langs;
pub mod metric_consts;
pub mod symbol_store;
pub mod types;

pub async fn handle_event(
    context: Arc<AppContext>,
    mut event: ClickHouseEvent,
) -> Result<ClickHouseEvent, UnhandledError> {
    let mut props = match get_props(&event) {
        Ok(r) => r,
        Err(e) => {
            warn!("Failed to get props: {}", e);

            if let Err(e) = add_error_to_event(&mut event, e) {
                // If we fail to add an error to an event, we just log it.
                // This can happen if we failed to read the properties
                // of the event in /any/ way, e.g. due to a serde recursion limit.
                // If that's the case, we will fail to add a new element to the
                // event properties storing the error message, so there's not much
                // we can do. We should consider whether we want to drop these events.
                error!("Failed to add error to event: {}", e);
            }
            return Ok(event);
        }
    };

    let exceptions = std::mem::take(&mut props.exception_list);

    if exceptions.is_empty() {
        props.add_error_message("No exceptions found on exception event");
        event.properties = Some(serde_json::to_string(&props).unwrap());
        return Ok(event);
    }

    let mut results = Vec::new();
    for exception in exceptions.into_iter() {
        // If we get an unhandled error during exception processing, we return an error, which should
        // cause the caller to drop the offset without storing it - unhandled exceptions indicate
        // a dependency is down, or some bug, adn we want to take lag in those situations.
        results.push(process_exception(context.clone(), event.team_id, exception).await?);
    }

    let fingerprint = generate_fingerprint(&results);
    props.exception_list = results;
    let fingerprinted = props.to_fingerprinted(fingerprint.clone());

    let event_timestamp = get_event_timestamp(&event).unwrap_or_else(|| {
        warn!("Failed to get event timestamp, using current time");
        Utc::now()
    });

    let mut output =
        resolve_issue(&context.pool, event.team_id, fingerprinted, event_timestamp).await?;

    // TODO - I'm not sure we actually want to do this? Maybe junk drawer stuff should end up in clickhouse, and
    // be directly queryable by users? Stripping it for now, so it only ends up in postgres
    output.strip_frame_junk();

    event.properties = Some(serde_json::to_string(&output).unwrap());

    Ok(event)
}

pub fn get_props(event: &ClickHouseEvent) -> Result<RawErrProps, EventError> {
    if event.event != "$exception" {
        return Err(EventError::WrongEventType(event.event.clone(), event.uuid));
    }

    let Some(properties) = &event.properties else {
        return Err(EventError::NoProperties(event.uuid));
    };

    let properties: RawErrProps = match serde_json::from_str(properties) {
        Ok(r) => r,
        Err(e) => {
            return Err(EventError::InvalidProperties(event.uuid, e.to_string()));
        }
    };

    Ok(properties)
}

async fn process_exception(
    context: Arc<AppContext>,
    team_id: i32,
    mut e: Exception,
) -> Result<Exception, UnhandledError> {
    let stack = std::mem::take(&mut e.stack);
    let Some(Stacktrace::Raw { frames }) = stack else {
        // This stack trace is already resolved, we have no work to do.
        e.stack = stack;
        return Ok(e);
    };

    if frames.is_empty() {
        // If the frame list was empty, we effectively just remove the stack from the exception,
        // making it stackless.
        return Ok(e);
    }

    let mut handles = Vec::with_capacity(frames.len());
    let mut resolved_frames = Vec::with_capacity(frames.len());

    for frame in frames.into_iter() {
        let context = context.clone();
        // Spawn a concurrent task for resolving every frame - we're careful elsewhere to
        // ensure this kind of concurrency is fine, although this "throw it at the wall"
        // data flow structure is pretty questionable. Once we switch to handling more than
        // 1 event at a time, we should re-group frames into associated groups and then
        // process those groups in-order (but the individual frames in them can still be
        // thrown at the wall), with some cross-group concurrency.
        handles.push(tokio::spawn(async move {
            context.worker_liveness.report_healthy().await;
            metrics::counter!(FRAME_RESOLUTION).increment(1);
            let res = context
                .resolver
                .resolve(&frame, team_id, &context.pool, &context.catalog)
                .await;
            context.worker_liveness.report_healthy().await;
            res
        }));
    }

    // Collect the results
    for handle in handles {
        // Joinhandles wrap the returned type in a Result, because if the task panics,
        // tokio catches it and returns an error. If any of our tasks panicked, we want
        // to propogate that panic, so we unwrap the outer Result here.
        let res = handle.await.unwrap()?;
        resolved_frames.push(res)
    }

    e.stack = Some(Stacktrace::Resolved {
        frames: resolved_frames,
    });

    Ok(e)
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
pub fn get_event_timestamp(event: &ClickHouseEvent) -> Option<DateTime<Utc>> {
    event.timestamp.parse::<DateTime<Utc>>().ok()
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
