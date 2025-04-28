use std::ops::Deref;
use std::sync::Arc;

use axum::{debug_handler, Json};
use bytes::Bytes;
// TODO: stream this instead
use axum::extract::{MatchedPath, Query, State};
use axum::http::{HeaderMap, Method};
use axum_client_ip::InsecureClientIp;
use base64::Engine;
use chrono::{DateTime, Duration, Utc};
use common_types::{CapturedEvent, RawEvent};
use limiters::token_dropper::TokenDropper;
use metrics::counter;
use serde_json::json;
use serde_json::Value;
use tracing::instrument;

use crate::prometheus::report_dropped_events;
use crate::v0_request::{
    Compression, DataType, ProcessedEvent, ProcessedEventMetadata, ProcessingContext, RawRequest,
};
use crate::{
    api::{CaptureError, CaptureResponse, CaptureResponseCode},
    router, sinks,
    utils::uuid_v7,
    v0_request::{EventFormData, EventQuery},
};

/// Flexible endpoint that targets wide compatibility with the wide range of requests
/// currently processed by posthog-events (analytics events capture). Replay is out
/// of scope and should be processed on a separate endpoint.
///
/// Because it must accommodate several shapes, it is inefficient in places. A v1
/// endpoint should be created, that only accepts the BatchedRequest payload shape.
async fn handle_common(
    state: &State<router::State>,
    InsecureClientIp(ip): &InsecureClientIp,
    meta: &EventQuery,
    headers: &HeaderMap,
    method: &Method,
    path: &MatchedPath,
    body: Bytes,
) -> Result<(ProcessingContext, Vec<RawEvent>), CaptureError> {
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
            RawRequest::from_bytes(payload.into(), state.event_size_limit)
        }
        ct => {
            tracing::Span::current().record("content_type", ct);

            RawRequest::from_bytes(body, state.event_size_limit)
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
        tracing::log::warn!("rejected empty batch");
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
        user_agent: Some(user_agent.to_string()),
    };

    let billing_limited = state
        .billing_limiter
        .is_limited(context.token.as_str())
        .await;

    if billing_limited {
        report_dropped_events("over_quota", events.len() as u64);

        return Err(CaptureError::BillingLimit);
    }

    tracing::debug!(context=?context, events=?events, "decoded request");

    Ok((context, events))
}

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
    ip: InsecureClientIp,
    meta: Query<EventQuery>,
    headers: HeaderMap,
    method: Method,
    path: MatchedPath,
    body: Bytes,
) -> Result<Json<CaptureResponse>, CaptureError> {
    match handle_common(&state, &ip, &meta, &headers, &method, &path, body).await {
        Err(CaptureError::BillingLimit) => {
            // for v0 we want to just return ok 🙃
            // this is because the clients are pretty dumb and will just retry over and over and
            // over...
            //
            // for v1, we'll return a meaningful error code and error, so that the clients can do
            // something meaningful with that error
            Ok(Json(CaptureResponse {
                status: CaptureResponseCode::Ok,
                quota_limited: None,
            }))
        }
        Err(err) => Err(err),
        Ok((context, events)) => {
            if let Err(err) = process_events(
                state.sink.clone(),
                state.token_dropper.clone(),
                state.historical_cfg.clone(),
                &events,
                &context,
            )
            .await
            {
                let cause = match err {
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
                quota_limited: None,
            }))
        }
    }
}

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
pub async fn recording(
    state: State<router::State>,
    ip: InsecureClientIp,
    meta: Query<EventQuery>,
    headers: HeaderMap,
    method: Method,
    path: MatchedPath,
    body: Bytes,
) -> Result<Json<CaptureResponse>, CaptureError> {
    match handle_common(&state, &ip, &meta, &headers, &method, &path, body).await {
        Err(CaptureError::BillingLimit) => Ok(Json(CaptureResponse {
            status: CaptureResponseCode::Ok,
            quota_limited: Some(vec!["recordings".to_string()]),
        })),
        Err(err) => Err(err),
        Ok((context, events)) => {
            let count = events.len() as u64;
            if let Err(err) = process_replay_events(state.sink.clone(), events, &context).await {
                let cause = match err {
                    CaptureError::MissingDistinctId => "missing_distinct_id",
                    CaptureError::MissingSessionId => "missing_session_id",
                    CaptureError::MissingWindowId => "missing_window_id",
                    CaptureError::MissingEventName => "missing_event_name",
                    CaptureError::RequestDecodingError(_) => "request_decoding_error",
                    CaptureError::RequestParsingError(_) => "request_parsing_error",
                    CaptureError::EventTooBig => "event_too_big",
                    CaptureError::NonRetryableSinkError => "sink_error",
                    CaptureError::InvalidSessionId => "invalid_session_id",
                    CaptureError::MissingSnapshotData => "missing_snapshot_data",
                    _ => "process_events_error",
                };
                report_dropped_events(cause, count);
                tracing::log::warn!("rejected invalid payload: {}", err);
                return Err(err);
            }
            Ok(Json(CaptureResponse {
                status: CaptureResponseCode::Ok,
                quota_limited: None,
            }))
        }
    }
}

pub async fn options() -> Result<Json<CaptureResponse>, CaptureError> {
    Ok(Json(CaptureResponse {
        status: CaptureResponseCode::Ok,
        quota_limited: None,
    }))
}

#[instrument(skip_all)]
pub fn process_single_event(
    event: &RawEvent,
    historical_cfg: router::HistoricalConfig,
    context: &ProcessingContext,
) -> Result<ProcessedEvent, CaptureError> {
    if event.event.is_empty() {
        return Err(CaptureError::MissingEventName);
    }

    let data_type = match (event.event.as_str(), context.historical_migration) {
        ("$$client_ingestion_warning", _) => DataType::ClientIngestionWarning,
        ("$exception", _) => DataType::ExceptionMain,
        ("$$heatmap", _) => DataType::HeatmapMain,
        (_, true) => DataType::AnalyticsHistorical,
        (_, false) => DataType::AnalyticsMain,
    };

    // only should be used to check if historical topic
    // rerouting should be applied to this event
    let raw_event_timestamp =
        event
            .timestamp
            .as_ref()
            .and_then(|ts| match DateTime::parse_from_rfc3339(ts) {
                Ok(dt) => Some(dt),
                Err(_) => None,
            });

    let data = serde_json::to_string(&event).map_err(|e| {
        tracing::error!("failed to encode data field: {}", e);
        CaptureError::NonRetryableSinkError
    })?;

    let mut metadata = ProcessedEventMetadata {
        data_type,
        session_id: None,
    };

    let event = CapturedEvent {
        uuid: event.uuid.unwrap_or_else(uuid_v7),
        distinct_id: event
            .extract_distinct_id()
            .ok_or(CaptureError::MissingDistinctId)?,
        ip: context.client_ip.clone(),
        data,
        now: context.now.clone(),
        sent_at: context.sent_at,
        token: context.token.clone(),
        is_cookieless_mode: event
            .extract_is_cookieless_mode()
            .ok_or(CaptureError::InvalidCookielessMode)?,
    };

    // if this event was historical but not assigned to the right topic
    // by the submitting user (i.e. no historical prop flag in event)
    // we should route it there using event#now if older than 1 day
    let should_reroute_event = if raw_event_timestamp.is_some() {
        let days_stale = Duration::days(historical_cfg.historical_rerouting_threshold_days);
        let threshold = Utc::now() - days_stale;
        let decision = raw_event_timestamp.unwrap().to_utc() <= threshold;
        if decision {
            counter!(
                "capture_events_rerouted_historical",
                &[("reason", "timestamp")]
            )
            .increment(1);
        }
        decision
    } else {
        let decision = historical_cfg.should_reroute(&event.key());
        if decision {
            counter!(
                "capture_events_rerouted_historical",
                &[("reason", "key_or_token")]
            )
            .increment(1);
        }
        decision
    };

    if metadata.data_type == DataType::AnalyticsMain
        && historical_cfg.enable_historical_rerouting
        && should_reroute_event
    {
        metadata.data_type = DataType::AnalyticsHistorical;
    }

    Ok(ProcessedEvent { metadata, event })
}

#[instrument(skip_all, fields(events = events.len()))]
pub async fn process_events<'a>(
    sink: Arc<dyn sinks::Event + Send + Sync>,
    dropper: Arc<TokenDropper>,
    historical_cfg: router::HistoricalConfig,
    events: &'a [RawEvent],
    context: &'a ProcessingContext,
) -> Result<(), CaptureError> {
    let mut events: Vec<ProcessedEvent> = events
        .iter()
        .map(|e| process_single_event(e, historical_cfg.clone(), context))
        .collect::<Result<Vec<ProcessedEvent>, CaptureError>>()?;

    events.retain(|e| {
        if dropper.should_drop(&e.event.token, &e.event.distinct_id) {
            report_dropped_events("token_dropper", 1);
            false
        } else {
            true
        }
    });

    tracing::debug!(events=?events, "processed {} events", events.len());

    if events.len() == 1 {
        sink.send(events[0].clone()).await
    } else {
        sink.send_batch(events).await
    }
}

#[instrument(skip_all, fields(events = events.len()))]
pub async fn process_replay_events<'a>(
    sink: Arc<dyn sinks::Event + Send + Sync>,
    mut events: Vec<RawEvent>,
    context: &'a ProcessingContext,
) -> Result<(), CaptureError> {
    // Grab metadata about the whole batch from the first event before
    // we drop all the events as we rip out the snapshot data
    let session_id = events[0]
        .properties
        .remove("$session_id")
        .ok_or(CaptureError::MissingSessionId)?;

    // Validate session_id is a valid UUID
    let session_id_str = session_id.as_str().ok_or(CaptureError::InvalidSessionId)?;

    // Reject session_ids that are too long, or that contains non-alphanumeric characters,
    // this is a proxy for "not a valid UUID"
    // we can't just reject non-UUIDv7 strings because
    // some running versions of PostHog JS in the wild are still pre-version 1.73.0
    // when we started sending valid UUIDv7 session_ids
    // at time of writing they are ~4-5% of all sessions
    // they'll be having a bad time generally but replay probably works a little for them
    // so we don't drop non-UUID strings, but we use length as a proxy definitely bad UUIDs
    if session_id_str.len() > 70
        || !session_id_str
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '-')
    {
        return Err(CaptureError::InvalidSessionId);
    }

    let window_id = events[0]
        .properties
        .remove("$window_id")
        .unwrap_or(session_id.clone());
    let uuid = events[0].uuid.unwrap_or_else(uuid_v7);
    let distinct_id = events[0]
        .extract_distinct_id()
        .ok_or(CaptureError::MissingDistinctId)?;
    let snapshot_source = events[0]
        .properties
        .remove("$snapshot_source")
        .unwrap_or(Value::String(String::from("web")));
    let is_cookieless_mode = events[0]
        .extract_is_cookieless_mode()
        .ok_or(CaptureError::InvalidCookielessMode)?;
    let snapshot_library = events[0]
        .properties
        .remove("$lib")
        .and_then(|v| v.as_str().map(|v| v.to_string()))
        // missing lib could be one of multiple libraries, so we try to fall back to user agent
        .or_else(|| snapshot_library_fallback_from(context.user_agent.as_ref()))
        .unwrap_or_else(|| String::from("unknown"));

    let mut snapshot_items: Vec<Value> = Vec::with_capacity(events.len());
    for mut event in events {
        let Some(snapshot_data) = event.properties.remove("$snapshot_data") else {
            return Err(CaptureError::MissingSnapshotData);
        };
        match snapshot_data {
            Value::Array(value) => {
                snapshot_items.extend(value);
            }
            Value::Object(value) => {
                snapshot_items.push(Value::Object(value));
            }
            _ => {
                return Err(CaptureError::MissingSnapshotData);
            }
        }
    }

    let metadata = ProcessedEventMetadata {
        data_type: DataType::SnapshotMain,
        session_id: Some(session_id_str.to_string()),
    };

    let event = CapturedEvent {
        uuid,
        distinct_id: distinct_id.clone(),
        ip: context.client_ip.clone(),
        data: json!({
            "event": "$snapshot_items",
            "properties": {
                "distinct_id": distinct_id,
                "$session_id": session_id,
                "$window_id": window_id,
                "$snapshot_source": snapshot_source,
                "$snapshot_items": snapshot_items,
                "$lib": snapshot_library,
            }
        })
        .to_string(),
        now: context.now.clone(),
        sent_at: context.sent_at,
        token: context.token.clone(),
        is_cookieless_mode,
    };

    sink.send(ProcessedEvent { metadata, event }).await
}

fn snapshot_library_fallback_from(user_agent: Option<&String>) -> Option<String> {
    user_agent?
        .split('/')
        .next()
        .map(|s| s.to_string())
        .filter(|s| s.contains("posthog"))
        .or(Some("web".to_string()))
}
