use std::cell::RefCell;
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
use rand::Rng;
use rand::{rngs::ThreadRng, thread_rng};
use serde_json::json;
use serde_json::Value;
use tracing::{debug, error, info, instrument, warn, Span};

use crate::prometheus::{report_dropped_events, report_internal_error_metrics};
use crate::v0_request::{
    Compression, DataType, ProcessedEvent, ProcessedEventMetadata, ProcessingContext, RawRequest,
};
use crate::{
    api::{CaptureError, CaptureResponse, CaptureResponseCode},
    router, sinks,
    utils::{
        decode_base64, decode_form, extract_and_verify_token, extract_compression,
        extract_lib_version, is_likely_base64, is_likely_urlencoded_form, uuid_v7, Base64Option,
        FORM_MIME_TYPE, MAX_PAYLOAD_SNIPPET_SIZE,
    },
    v0_request::{EventFormData, EventQuery},
};

// TEMPORARY: used to trigger sampling of chatty log line
thread_local! {
    static RNG: RefCell<ThreadRng> = RefCell::new(thread_rng());
}

/// handle_legacy owns the /e, /capture, /track, and /engage capture endpoints
#[instrument(
    skip_all,
    fields(
        method,
        path,
        user_agent,
        content_type,
        content_encoding,
        x_request_id,
        token,
        historical_migration,
        lib_version,
        compression,
        params_lib_version,
        params_compression,
        batch_size
    )
)]
async fn handle_legacy(
    state: &State<router::State>,
    InsecureClientIp(ip): &InsecureClientIp,
    query_params: &mut EventQuery,
    headers: &HeaderMap,
    method: &Method,
    path: &MatchedPath,
    body: Bytes,
) -> Result<(ProcessingContext, Vec<RawEvent>), CaptureError> {
    // this endpoint handles:
    // - GET or POST requests w/payload that is one of:
    //   1. possibly base64-wrapped, possibly GZIP or LZ64 compressed JSON payload
    //   2. possibly base64-wrapped, urlencoded form where "data" is the key for JSON payload
    //
    // When POST body isn't the payload, the POST form fields or
    // GET query params should contain the following:
    //     - data        = JSON payload which may itself be compressed or base64 encoded or both
    //     - compression = hint to how "data" is encoded or compressed
    //     - lib_version = SDK version that submitted the request

    // capture arguments and add to logger, processing context
    Span::current().record("path", path.as_str());
    let user_agent = headers
        .get("user-agent")
        .map_or("unknown", |v| v.to_str().unwrap_or("unknown"));
    Span::current().record("user_agent", user_agent);
    let content_type = headers
        .get("content-type")
        .map_or("unknown", |v| v.to_str().unwrap_or("unknown"));
    Span::current().record("content_type", content_type);
    let content_encoding = headers
        .get("content-encoding")
        .map_or("unknown", |v| v.to_str().unwrap_or("unknown"));
    Span::current().record("content_encoding", content_encoding);
    let request_id = headers
        .get("x-request-id")
        .map_or("unknown", |v| v.to_str().unwrap_or("unknown"));
    Span::current().record("request_id", request_id);

    // TODO(eli): temporary peek at these
    if query_params.lib_version.is_some() {
        Span::current().record(
            "params_lib_version",
            format!("{:?}", query_params.lib_version.as_ref()),
        );
    }
    if query_params.compression.is_some() {
        Span::current().record(
            "params_compression",
            format!("{}", query_params.compression.unwrap()),
        );
    }

    debug!("entering handle_legacy");

    // unpack the payload - it may be in a GET query param or POST body
    let raw_payload: Bytes = if query_params.data.as_ref().is_some_and(|d| !d.is_empty()) {
        let tmp_vec = std::mem::take(&mut query_params.data);
        Bytes::from(tmp_vec.unwrap())
    } else if !body.is_empty() {
        body
    } else {
        let err = CaptureError::EmptyPayload;
        error!("missing payload on {:?} request", method);
        return Err(err);
    };

    // first round of processing: is this byte payload entirely base64 encoded?
    // unwrap for downstream processing if so, leave it alone if not
    let payload = if !is_likely_urlencoded_form(&raw_payload)
        && is_likely_base64(&raw_payload, Base64Option::Strict)
    {
        decode_base64(&raw_payload, "optimisitc_decode_raw_payload")
            .map_or(raw_payload, Bytes::from)
    } else {
        raw_payload
    };

    // attempt to decode POST payload if it is form data. if
    // successful, the form data will be processed downstream
    let form: EventFormData = match content_type {
        FORM_MIME_TYPE => {
            if is_likely_urlencoded_form(&payload) {
                let mut form = decode_form(&payload)?;

                // corner case: if the form "data" payload is Base64 encoded,
                // we need to restore the '+' chars that were urldecoded to spaces
                // for the downstream decoding steps like LZ64 to work with
                if form
                    .data
                    .as_ref()
                    .is_some_and(|d| is_likely_base64(d.as_bytes(), Base64Option::Loose))
                {
                    form.data = Some(form.data.unwrap().replace(" ", "+"));
                }
                form
            } else {
                let max_chars = std::cmp::min(payload.len(), MAX_PAYLOAD_SNIPPET_SIZE);
                let form_data_snippet = String::from_utf8(payload[..max_chars].to_vec())
                    .unwrap_or(String::from("INVALID_UTF8"));
                error!(
                    form_data = form_data_snippet,
                    "expected form data in {} request payload", *method
                );
                let err = CaptureError::RequestDecodingError(String::from(
                    "expected form data in request payload",
                ));
                return Err(err);
            }
        }

        // if "data" is unpopulated, the non-form payload will be processed downstream
        _ => EventFormData {
            data: None,
            compression: None,
            lib_version: None,
        },
    };

    // different SDKs stash these in different places. take the best we find
    let compression = extract_compression(&form, query_params, headers);
    Span::current().record("compression", format!("{}", compression));
    let lib_version = extract_lib_version(&form, query_params);
    Span::current().record("lib_version", &lib_version);

    debug!("payload processed: passing to RawRequest::from_bytes");

    // if the "data" attribute is populated in the form, process it.
    // otherwise, pass the (possibly decoded) byte payload
    let data = form.data.map_or(payload, Bytes::from);
    let request = RawRequest::from_bytes(
        data,
        compression,
        request_id,
        state.event_size_limit,
        path.as_str().to_string(),
    )?;

    let sent_at = request.sent_at().or(query_params.sent_at());
    let historical_migration = request.historical_migration();
    Span::current().record("historical_migration", historical_migration);

    // if this was a batch request, retrieve this now for later validation
    let maybe_batch_token = request.get_batch_token();

    // consumes the parent request, so it's no longer in scope to extract metadata from
    let events = match request.events(path.as_str()) {
        Ok(events) => events,
        Err(e) => return Err(e),
    };
    Span::current().record("batch_size", events.len());

    let token = match extract_and_verify_token(&events, maybe_batch_token) {
        Ok(token) => token,
        Err(err) => {
            return Err(err);
        }
    };
    Span::current().record("token", &token);

    // TEMPORARY: conditionally sample targeted event submissions
    let roll = RNG.with_borrow_mut(|rng| rng.gen_range(0.0..100.0));
    if compression == Compression::Base64 && roll < state.base64_detect_percent {
        // API token, req path etc. should be logged here by tracing lib
        info!("handle_legacy: candidate team for base64 issue")
    }

    counter!("capture_events_received_total", &[("legacy", "true")]).increment(events.len() as u64);

    let context = ProcessingContext {
        lib_version,
        sent_at,
        token,
        now: state.timesource.current_time(),
        client_ip: ip.to_string(),
        request_id: request_id.to_string(),
        path: path.as_str().to_string(),
        is_mirror_deploy: false,
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

    debug!(context=?context,
        event_count=?events.len(),
        "handle_legacy: successfully hydrated events");
    Ok((context, events))
}

/// Flexible endpoint that targets wide compatibility with the wide range of requests
/// currently processed by posthog-events (analytics events capture). Replay is out
/// of scope and should be processed on a separate endpoint.
///
/// Because it must accommodate several shapes, it is inefficient in places. A v1
/// endpoint should be created, that only accepts the BatchedRequest payload shape.
///
/// NOTE: handle_common owns the /i and /batch capture endpoints
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
    let request_id = headers
        .get("x-request-id")
        .map_or("unknown", |v| v.to_str().unwrap_or("unknown"));
    Span::current().record("user_agent", user_agent);
    Span::current().record("content_encoding", content_encoding);
    Span::current().record("request_id", request_id);
    Span::current().record("method", method.as_str());
    Span::current().record("path", path.as_str().trim_end_matches('/'));

    // TODO(eli): add event_legacy compression and lib_version extraction into this flow if we don't unify entirely
    let resolved_cmp = format!("{}", meta.compression.unwrap_or_default());
    Span::current().record("version", meta.lib_version.clone());
    Span::current().record("compression", resolved_cmp);

    let request = match headers
        .get("content-type")
        .map_or("", |v| v.to_str().unwrap_or(""))
    {
        "application/x-www-form-urlencoded" => {
            Span::current().record("content_type", "application/x-www-form-urlencoded");

            let input: EventFormData = serde_urlencoded::from_bytes(body.deref()).map_err(|e| {
                error!("failed to decode urlencoded form body: {}", e);
                CaptureError::RequestDecodingError(String::from("invalid urlencoded form data"))
            })?;

            if input.data.is_none() || input.data.as_ref().is_some_and(|d| d.is_empty()) {
                return Err(CaptureError::EmptyPayload);
            }

            let payload = base64::engine::general_purpose::STANDARD
                .decode(input.data.unwrap())
                .map_err(|e| {
                    error!("failed to decode base64 form data: {}", e);
                    CaptureError::RequestDecodingError(String::from(
                        "missing or invalid data field",
                    ))
                })?;

            // by setting compression "unsupported" here, we route handle_common
            // outputs into the old RawRequest hydration behavior, prior to adding
            // handle_legacy shims. handle_common doesn't extract compression hints
            // as reliably as it should, and is probably losing some data due to
            // this. We'll circle back once the legacy shims ship
            RawRequest::from_bytes(
                payload.into(),
                Compression::Unsupported,
                request_id,
                state.event_size_limit,
                path.as_str().to_string(),
            )
        }
        ct => {
            Span::current().record("content_type", ct);
            // see above for details
            RawRequest::from_bytes(
                body,
                Compression::Unsupported,
                request_id,
                state.event_size_limit,
                path.as_str().to_string(),
            )
        }
    }?;

    let sent_at = request.sent_at().or(meta.sent_at());
    let historical_migration = request.historical_migration();
    Span::current().record("historical_migration", historical_migration);

    // if this was a batch request, retrieve this now for later validation
    let maybe_batch_token = request.get_batch_token();

    // consumes the parent request, so it's no longer in scope to extract metadata from
    let events = match request.events(path.as_str()) {
        Ok(events) => events,
        Err(e) => return Err(e),
    };
    Span::current().record("batch_size", events.len());

    let token = match extract_and_verify_token(&events, maybe_batch_token) {
        Ok(token) => token,
        Err(err) => {
            return Err(err);
        }
    };
    Span::current().record("token", &token);

    counter!("capture_events_received_total").increment(events.len() as u64);

    let context = ProcessingContext {
        lib_version: meta.lib_version.clone(),
        sent_at,
        token,
        now: state.timesource.current_time(),
        client_ip: ip.to_string(),
        request_id: request_id.to_string(),
        path: path.as_str().to_string(),
        is_mirror_deploy: false,
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

    debug!(context=?context, events=?events, "decoded request");

    Ok((context, events))
}

#[instrument(
    skip(state, body, meta),
    fields(params_lib_version, params_compression)
)]
#[debug_handler]
pub async fn event_legacy(
    state: State<router::State>,
    ip: InsecureClientIp,
    meta: Query<EventQuery>,
    headers: HeaderMap,
    method: Method,
    path: MatchedPath,
    body: Bytes,
) -> Result<CaptureResponse, CaptureError> {
    let mut params: EventQuery = meta.0;

    // TODO(eli): temporary peek at these
    if params.lib_version.is_some() {
        Span::current().record(
            "params_lib_version",
            format!("{:?}", params.lib_version.as_ref()),
        );
    }
    if params.compression.is_some() {
        Span::current().record(
            "params_compression",
            format!("{}", params.compression.unwrap()),
        );
    }

    match handle_legacy(&state, &ip, &mut params, &headers, &method, &path, body).await {
        Err(CaptureError::BillingLimit) => {
            // Short term: return OK here to avoid clients retrying over and over
            // Long term: v1 endpoints will return richer errors, sync w/SDK behavior
            Ok(CaptureResponse {
                status: CaptureResponseCode::Ok,
                quota_limited: None,
            })
        }

        Err(CaptureError::EmptyPayloadFiltered) => {
            // as per legacy behavior, for now we'll silently accept these submissions
            // when invalid event type filtering has resulted in an empty event payload
            Ok(CaptureResponse {
                status: CaptureResponseCode::Ok,
                quota_limited: None,
            })
        }

        Err(err) => {
            report_internal_error_metrics(err.to_metric_tag(), "parsing");
            error!("event_legacy: request payload processing error: {:?}", err);
            Err(err)
        }

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
                report_dropped_events(err.to_metric_tag(), events.len() as u64);
                report_internal_error_metrics(err.to_metric_tag(), "processing");
                error!("event_legacy: rejected invalid payload: {}", err);
                return Err(err);
            }

            Ok(CaptureResponse {
                status: if params.beacon {
                    CaptureResponseCode::NoContent
                } else {
                    CaptureResponseCode::Ok
                },
                quota_limited: None,
            })
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
pub async fn event(
    state: State<router::State>,
    ip: InsecureClientIp,
    params: Query<EventQuery>,
    headers: HeaderMap,
    method: Method,
    path: MatchedPath,
    body: Bytes,
) -> Result<CaptureResponse, CaptureError> {
    match handle_common(&state, &ip, &params, &headers, &method, &path, body).await {
        Err(CaptureError::BillingLimit) => {
            // for v0 we want to just return ok 🙃
            // this is because the clients are pretty dumb and will just retry over and over and
            // over...
            //
            // for v1, we'll return a meaningful error code and error, so that the clients can do
            // something meaningful with that error
            Ok(CaptureResponse {
                status: CaptureResponseCode::Ok,
                quota_limited: None,
            })
        }

        Err(CaptureError::EmptyPayloadFiltered) => {
            // as per legacy behavior, for now we'll silently accept these submissions
            // when invalid event type filtering has resulted in an empty event payload
            Ok(CaptureResponse {
                status: CaptureResponseCode::Ok,
                quota_limited: None,
            })
        }

        Err(err) => {
            report_internal_error_metrics(err.to_metric_tag(), "parsing");
            Err(err)
        }

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
                report_internal_error_metrics(err.to_metric_tag(), "processing");
                warn!("rejected invalid payload: {}", err);
                return Err(err);
            }

            Ok(CaptureResponse {
                status: if params.beacon {
                    CaptureResponseCode::NoContent
                } else {
                    CaptureResponseCode::Ok
                },
                quota_limited: None,
            })
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
    params: Query<EventQuery>,
    headers: HeaderMap,
    method: Method,
    path: MatchedPath,
    body: Bytes,
) -> Result<CaptureResponse, CaptureError> {
    match handle_common(&state, &ip, &params, &headers, &method, &path, body).await {
        Err(CaptureError::BillingLimit) => Ok(CaptureResponse {
            status: CaptureResponseCode::Ok,
            quota_limited: Some(vec!["recordings".to_string()]),
        }),
        Err(err) => Err(err),
        Ok((context, events)) => {
            let count = events.len() as u64;
            if let Err(err) = process_replay_events(state.sink.clone(), events, &context).await {
                report_dropped_events(err.to_metric_tag(), count);
                report_internal_error_metrics(err.to_metric_tag(), "process_replay_events");
                warn!("rejected invalid payload: {:?}", err);
                return Err(err);
            }
            Ok(CaptureResponse {
                status: if params.beacon {
                    CaptureResponseCode::NoContent
                } else {
                    CaptureResponseCode::Ok
                },
                quota_limited: None,
            })
        }
    }
}

pub async fn options() -> Result<Json<CaptureResponse>, CaptureError> {
    Ok(Json(CaptureResponse {
        status: CaptureResponseCode::Ok,
        quota_limited: None,
    }))
}

#[instrument(skip_all, fields(event_name, request_id))]
pub fn process_single_event(
    event: &RawEvent,
    historical_cfg: router::HistoricalConfig,
    context: &ProcessingContext,
) -> Result<ProcessedEvent, CaptureError> {
    if event.event.is_empty() {
        return Err(CaptureError::MissingEventName);
    }
    Span::current().record("event_name", &event.event);
    Span::current().record("is_mirror_deploy", context.is_mirror_deploy);
    Span::current().record("request_id", &context.request_id);

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
        error!("failed to encode data field: {}", e);
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

#[instrument(skip_all, fields(events = events.len(), request_id))]
pub async fn process_events<'a>(
    sink: Arc<dyn sinks::Event + Send + Sync>,
    dropper: Arc<TokenDropper>,
    historical_cfg: router::HistoricalConfig,
    events: &'a [RawEvent],
    context: &'a ProcessingContext,
) -> Result<(), CaptureError> {
    Span::current().record("request_id", &context.request_id);
    Span::current().record("is_mirror_deploy", context.is_mirror_deploy);

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

    debug!(
        event_count = events.len(),
        "process_event: batch successful"
    );

    if events.len() == 1 {
        sink.send(events[0].clone()).await
    } else {
        sink.send_batch(events).await
    }
}

#[instrument(skip_all, fields(events = events.len(), session_id, request_id))]
pub async fn process_replay_events<'a>(
    sink: Arc<dyn sinks::Event + Send + Sync>,
    mut events: Vec<RawEvent>,
    context: &'a ProcessingContext,
) -> Result<(), CaptureError> {
    Span::current().record("request_id", &context.request_id);

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
    Span::current().record("session_id", session_id_str);

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
