use std::collections::HashMap;

use app_context::AppContext;
use common_kafka::kafka_consumer::Offset;
use common_types::ClickHouseEvent;
use error::{EventError, UnhandledError};
use fingerprinting::generate_fingerprint;
use tracing::warn;
use types::{ErrProps, Exception, Stacktrace};
use uuid::Uuid;

pub mod app_context;
pub mod config;
pub mod error;
pub mod fingerprinting;
pub mod frames;
pub mod langs;
pub mod metric_consts;
pub mod symbol_store;
pub mod types;

pub async fn handle_event(
    context: &AppContext,
    event: ClickHouseEvent,
    offset: Offset,
) -> Result<Option<ClickHouseEvent>, UnhandledError> {
    let mut props = match get_props(&event) {
        Ok(r) => r,
        Err(e) => {
            offset.store().unwrap();
            warn!("Failed to get props: {}", e);
            // Drop exceptions with no properties - our users don't care about them, and neither do we.
            return Ok(None);
        }
    };

    let exceptions = match take_exception_list(event.uuid, &mut props) {
        Ok(r) => r,
        Err(e) => {
            offset.store().unwrap();
            warn!("Failed to take exception list: {}", e);
            // Some exceptions don't have an exception list - if that's the case, we just pass them on.
            // TODO - we should probably drop these exceptions to, I'm not sure
            return Ok(Some(event));
        }
    };

    let mut results = Vec::new();
    for exception in exceptions.into_iter() {
        // If we get an unhandled error during exception processing, we drop the offset without storing it,
        // which means we'll take lag, but won't lose data.
        results.push(process_exception(context, event.team_id, exception).await?);
    }

    props.fingerprint = Some(generate_fingerprint(&results));
    props.exception_list = Some(results);

    // "But we can open the box" said toad.
    let mut event = event;
    event.properties = Some(serde_json::to_string(&props).unwrap());

    // We've processed the exception event succesffully, so we can store the offset.
    offset.store().unwrap();

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
    let Some(mut exception_list) = props.exception_list.as_mut() else {
        return Err(EventError::NoExceptionList(event_id));
    };

    if exception_list.is_empty() {
        return Err(EventError::EmptyExceptionList(event_id));
    }

    Ok(std::mem::take(&mut exception_list))
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
