use std::collections::HashMap;

use app_context::AppContext;
use common_types::ClickHouseEvent;
use error::{EventError, UnhandledError};
use fingerprinting::generate_fingerprint;
use issue_resolution::{create_issue, load_issue_override};
use sqlx::PgPool;
use tracing::warn;
use types::{ErrProps, Exception, Stacktrace};
use uuid::Uuid;

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

    let exceptions = match take_exception_list(event.uuid, &mut props) {
        Ok(r) => r,
        Err(e) => {
            warn!("Failed to take exception list: {}", e);
            // Add an error message, and patch the event properties back up.
            props.add_error_message(format!("Failed to take exception list: {}", e));
            event.properties = Some(serde_json::to_string(&props).unwrap());
            return Ok(Some(event));
        }
    };

    let mut results = Vec::new();
    for exception in exceptions.into_iter() {
        // If we get an unhandled error during exception processing, we return an error, which should
        // cause the caller to drop the offset without storing it - unhandled exceptions indicate
        // a dependency is down, or some bug, adn we want to take lag in those situations.
        results.push(process_exception(context, event.team_id, exception).await?);
    }

    let fingerprint = generate_fingerprint(&results);

    let resolved_issue_id = resolve_issue(&context.pool, event.team_id, &fingerprint).await?;

    props.fingerprint = Some(fingerprint);
    props.resolved_issue_id = Some(resolved_issue_id);
    props.exception_list = Some(results);

    event.properties = Some(serde_json::to_string(&props).unwrap());

    Ok(Some(event))
}

fn get_props(event: &ClickHouseEvent) -> Result<ErrProps, EventError> {
    if event.event != "$exception" {
        return Err(EventError::WrongEventType(event.event.clone(), event.uuid));
    }

    let Some(properties) = &event.properties else {
        return Err(EventError::NoProperties(event.uuid));
    };

    let properties: ErrProps = match serde_json::from_str(properties) {
        Ok(r) => r,
        Err(e) => {
            return Err(EventError::InvalidProperties(event.uuid, e.to_string()));
        }
    };

    Ok(properties)
}

fn take_exception_list(event_id: Uuid, props: &mut ErrProps) -> Result<Vec<Exception>, EventError> {
    let Some(exception_list) = props.exception_list.as_mut() else {
        return Err(EventError::NoExceptionList(event_id));
    };

    if exception_list.is_empty() {
        return Err(EventError::EmptyExceptionList(event_id));
    }

    Ok(std::mem::take(exception_list))
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

async fn resolve_issue(
    pool: &PgPool,
    team_id: i32,
    fingerprint: &str,
) -> Result<Uuid, UnhandledError> {
    let existing = load_issue_override(pool, team_id, fingerprint).await?;

    let issue_fingerprint = match existing {
        Some(f) => f,
        None => create_issue(pool, team_id, fingerprint).await?,
    };

    Ok(issue_fingerprint.issue_id)
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
