use std::ops::Deref;
use std::sync::Arc;

use axum::{debug_handler, Json};
use bytes::Bytes;
// TODO: stream this instead
use axum::extract::{MatchedPath, Query, State};
use axum::http::{HeaderMap, Method};
use axum_client_ip::InsecureClientIp;
use base64::Engine;
use metrics::counter;
use tracing::instrument;

use crate::limiters::billing::QuotaResource;
use crate::prometheus::report_dropped_events;
use crate::v0_request::{Compression, ProcessingContext, RawRequest};
use crate::{
    api::{CaptureError, CaptureResponse, CaptureResponseCode, DataType, ProcessedEvent},
    router, sinks,
    utils::uuid_v7,
    v0_request::{EventFormData, EventQuery, RawEvent},
};

/// Flexible endpoint that targets wide compatibility with the wide range of requests
/// currently processed by posthog-events (analytics events capture). Replay is out
/// of scope and should be processed on a separate endpoint.
///
/// Because it must accommodate several shapes, it is inefficient in places. A v1
/// endpoint should be created, that only accepts the BatchedRequest payload shape.

#[instrument(
    skip_all,
    fields(
        path,
        token,
        batch_size,
        user_agent,
        content_encoding,
        content_type,
        version,
        compression,
        historical_migration
    )
)]
#[debug_handler]
pub async fn event(
    state: State<router::State>,
    InsecureClientIp(ip): InsecureClientIp,
    meta: Query<EventQuery>,
    headers: HeaderMap,
    method: Method,
    path: MatchedPath,
    body: Bytes,
) -> Result<Json<CaptureResponse>, CaptureError> {
    let user_agent = headers
        .get("user-agent")
        .map_or("unknown", |v| v.to_str().unwrap_or("unknown"));
    let content_encoding = headers
        .get("content-encoding")
        .map_or("unknown", |v| v.to_str().unwrap_or("unknown"));

    let comp = match meta.compression {
        None => String::from("unknown"),
        Some(Compression::Gzip) => String::from("gzip"),
        Some(Compression::Unsupported) => String::from("unsupported"),
    };

    tracing::Span::current().record("user_agent", user_agent);
    tracing::Span::current().record("content_encoding", content_encoding);
    tracing::Span::current().record("version", meta.lib_version.clone());
    tracing::Span::current().record("compression", comp.as_str());
    tracing::Span::current().record("method", method.as_str());
    tracing::Span::current().record("path", path.as_str().trim_end_matches('/'));

    let request = match headers
        .get("content-type")
        .map_or("", |v| v.to_str().unwrap_or(""))
    {
        "application/x-www-form-urlencoded" => {
            tracing::Span::current().record("content_type", "application/x-www-form-urlencoded");

            let input: EventFormData = serde_urlencoded::from_bytes(body.deref()).map_err(|e| {
                tracing::error!("failed to decode body: {}", e);
                CaptureError::RequestDecodingError(String::from("invalid form data"))
            })?;
            let payload = base64::engine::general_purpose::STANDARD
                .decode(input.data)
                .map_err(|e| {
                    tracing::error!("failed to decode form data: {}", e);
                    CaptureError::RequestDecodingError(String::from("missing data field"))
                })?;
            RawRequest::from_bytes(payload.into())
        }
        ct => {
            tracing::Span::current().record("content_type", ct);

            RawRequest::from_bytes(body)
        }
    }?;

    let sent_at = request.sent_at().or(meta.sent_at());
    let token = match request.extract_and_verify_token() {
        Ok(token) => token,
        Err(err) => {
            report_dropped_events("token_shape_invalid", request.events().len() as u64);
            return Err(err);
        }
    };
    let historical_migration = request.historical_migration();
    let events = request.events(); // Takes ownership of request

    tracing::Span::current().record("token", &token);
    tracing::Span::current().record("historical_migration", historical_migration);
    tracing::Span::current().record("batch_size", events.len());

    if events.is_empty() {
        return Err(CaptureError::EmptyBatch);
    }

    counter!("capture_events_received_total").increment(events.len() as u64);

    let context = ProcessingContext {
        lib_version: meta.lib_version.clone(),
        sent_at,
        token,
        now: state.timesource.current_time(),
        client_ip: ip.to_string(),
        historical_migration,
    };

    let billing_limited = state
        .billing
        .is_limited(context.token.as_str(), QuotaResource::Events)
        .await;

    if billing_limited {
        report_dropped_events("over_quota", events.len() as u64);

        // for v0 we want to just return ok 🙃
        // this is because the clients are pretty dumb and will just retry over and over and
        // over...
        //
        // for v1, we'll return a meaningful error code and error, so that the clients can do
        // something meaningful with that error
        return Ok(Json(CaptureResponse {
            status: CaptureResponseCode::Ok,
        }));
    }

    tracing::debug!(context=?context, events=?events, "decoded request");

    if let Err(err) = process_events(state.sink.clone(), &events, &context).await {
        let cause = match err {
            // TODO: automate this with a macro
            CaptureError::EmptyDistinctId => "empty_distinct_id",
            CaptureError::MissingDistinctId => "missing_distinct_id",
            CaptureError::MissingEventName => "missing_event_name",
            _ => "process_events_error",
        };
        report_dropped_events(cause, events.len() as u64);
        tracing::log::warn!("rejected invalid payload: {}", err);
        return Err(err);
    }

    Ok(Json(CaptureResponse {
        status: CaptureResponseCode::Ok,
    }))
}

pub async fn options() -> Result<Json<CaptureResponse>, CaptureError> {
    Ok(Json(CaptureResponse {
        status: CaptureResponseCode::Ok,
    }))
}

#[instrument(skip_all)]
pub fn process_single_event(
    event: &RawEvent,
    context: &ProcessingContext,
) -> Result<ProcessedEvent, CaptureError> {
    if event.event.is_empty() {
        return Err(CaptureError::MissingEventName);
    }

    let data_type = match context.historical_migration {
        true => DataType::AnalyticsHistorical,
        false => DataType::AnalyticsMain,
    };

    let data = serde_json::to_string(&event).map_err(|e| {
        tracing::error!("failed to encode data field: {}", e);
        CaptureError::NonRetryableSinkError
    })?;

    Ok(ProcessedEvent {
        data_type,
        uuid: event.uuid.unwrap_or_else(uuid_v7),
        distinct_id: event.extract_distinct_id()?,
        ip: context.client_ip.clone(),
        data,
        now: context.now.clone(),
        sent_at: context.sent_at,
        token: context.token.clone(),
    })
}

#[instrument(skip_all, fields(events = events.len()))]
pub async fn process_events<'a>(
    sink: Arc<dyn sinks::Event + Send + Sync>,
    events: &'a [RawEvent],
    context: &'a ProcessingContext,
) -> Result<(), CaptureError> {
    let events: Vec<ProcessedEvent> = events
        .iter()
        .map(|e| process_single_event(e, context))
        .collect::<Result<Vec<ProcessedEvent>, CaptureError>>()?;

    tracing::debug!(events=?events, "processed {} events", events.len());

    if events.len() == 1 {
        sink.send(events[0].clone()).await
    } else {
        sink.send_batch(events).await
    }
}
