use std::collections::HashMap;

use app_context::AppContext;
use common_types::ClickHouseEvent;
use error::{EventError, UnhandledError};
use fingerprinting::generate_fingerprint;
use issue_resolution::resolve_issue;
use tracing::warn;
use types::{Exception, RawErrProps, Stacktrace};

pub mod app_context;
pub mod config;
pub mod error;
pub mod fingerprinting;
pub mod frames;
pub mod issue_resolution;
pub mod langs;
pub mod metric_consts;
pub mod symbol_store;
pub mod types;

pub async fn handle_event(
    context: &AppContext,
    mut event: ClickHouseEvent,
) -> Result<Option<ClickHouseEvent>, UnhandledError> {
    let mut props = match get_props(&event) {
        Ok(r) => r,
        Err(e) => {
            warn!("Failed to get props: {}", e);
            add_error_to_event(&mut event, e)?;
            return Ok(Some(event));
        }
    };

    let exceptions = std::mem::take(&mut props.exception_list);

    if exceptions.is_empty() {
        props.add_error_message("No exceptions found on exception event");
        event.properties = Some(serde_json::to_string(&props).unwrap());
        return Ok(Some(event));
    }

    let mut results = Vec::new();
    for exception in exceptions.into_iter() {
        // If we get an unhandled error during exception processing, we return an error, which should
        // cause the caller to drop the offset without storing it - unhandled exceptions indicate
        // a dependency is down, or some bug, adn we want to take lag in those situations.
        results.push(process_exception(context, event.team_id, exception).await?);
    }

    let fingerprint = generate_fingerprint(&results);
    props.exception_list = results;
    let fingerprinted = props.to_fingerprinted(fingerprint.clone());

    let output = resolve_issue(&context.pool, event.team_id, fingerprinted).await?;

    event.properties = Some(serde_json::to_string(&output).unwrap());

    Ok(Some(event))
}

fn get_props(event: &ClickHouseEvent) -> Result<RawErrProps, EventError> {
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
    context: &AppContext,
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

    let mut results = Vec::with_capacity(frames.len());

    // Cluster the frames by symbol set
    // TODO - we really want to cluster across exceptions (and even across events),
    // rather than just within a single exception
    let mut groups = HashMap::new();
    for (i, frame) in frames.into_iter().enumerate() {
        let group = groups
            .entry(frame.symbol_set_ref())
            .or_insert_with(Vec::new);
        group.push((i, frame));
    }

    for (_, frames) in groups.into_iter() {
        for (i, frame) in frames {
            let resolved_frame = context
                .resolver
                .resolve(&frame, team_id, &context.pool, &context.catalog)
                .await?;
            results.push((i, resolved_frame));
        }
    }

    results.sort_unstable_by_key(|(i, _)| *i);

    e.stack = Some(Stacktrace::Resolved {
        frames: results.into_iter().map(|(_, frame)| frame).collect(),
    });

    Ok(e)
}

// This is stupidly expensive, since it round-trips the event through JSON, lol. We should change ClickhouseEvent to only do serde at the
// edges
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
