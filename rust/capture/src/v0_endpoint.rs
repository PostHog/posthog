use std::sync::Arc;

use axum::{debug_handler, Json};
use bytes::Bytes;
// TODO: stream this instead
use axum::extract::{MatchedPath, Query, State};
use axum::http::{HeaderMap, Method};
use axum_client_ip::InsecureClientIp;
use chrono::DateTime;
use common_types::{CapturedEvent, RawEvent};
use metrics::counter;
use serde_json::json;
use serde_json::Value;
use tracing::{debug, error, instrument, warn, Span};

use crate::{
    api::{CaptureError, CaptureResponse, CaptureResponseCode},
    events::analytics::process_events,
    payload::{EventFormData, EventQuery},
    prometheus::{report_dropped_events, report_internal_error_metrics},
    router, sinks, timestamp,
    utils::{
        decode_base64, decode_form, extract_and_verify_token, extract_compression,
        extract_lib_version, is_likely_base64, is_likely_urlencoded_form, uuid_v7, Base64Option,
        FORM_MIME_TYPE, MAX_PAYLOAD_SNIPPET_SIZE,
    },
    v0_request::{
        DataType, ProcessedEvent, ProcessedEventMetadata, ProcessingContext, RawRequest,
    },
};

// EXAMPLE: use verbose_sample_percent env var to capture extra logging/metric details of interest
// let roll = thread_rng().with_borrow_mut(|rng| rng.gen_range(0.0..100.0));
// if roll < verbose_sample_percent { ... }

/// handle_event_payload owns processing of request payloads for the
/// /i/v0/e/, /batch/, /e/, /capture/, /track/, and /engage/ endpoints
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
async fn handle_event_payload(
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

    let is_mirror_deploy = state.is_mirror_deploy;
    Span::current().record("is_mirror_deploy", is_mirror_deploy);

    debug!("entering handle_event_payload");

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
    Span::current().record("compression", format!("{compression}"));
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
    let mut events = match request.events(path.as_str()) {
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

    counter!("capture_events_received_total", &[("legacy", "true")]).increment(events.len() as u64);

    let now = state.timesource.current_time();

    let context = ProcessingContext {
        lib_version,
        sent_at,
        token,
        now,
        client_ip: ip.to_string(),
        request_id: request_id.to_string(),
        path: path.as_str().to_string(),
        is_mirror_deploy,
        historical_migration,
        user_agent: Some(user_agent.to_string()),
    };

    // Apply all billing limit quotas and drop partial or whole
    // payload if any are exceeded for this token (team)
    debug!(context=?context, event_count=?events.len(), "handle_event_payload: evaluating quota limits");
    events = state
        .quota_limiter
        .check_and_filter(&context.token, events)
        .await?;

    debug!(context=?context,
        event_count=?events.len(),
        "handle_event_payload: successfully hydrated events");
    Ok((context, events))
}

#[instrument(
    skip(state, body, meta),
    fields(params_lib_version, params_compression)
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

    match handle_event_payload(&state, &ip, &mut params, &headers, &method, &path, body).await {
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
            report_internal_error_metrics(
                err.to_metric_tag(),
                "parsing",
                state.capture_mode.as_tag(),
            );
            error!("event: request payload parsing error: {:?}", err);
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
                report_internal_error_metrics(
                    err.to_metric_tag(),
                    "processing",
                    state.capture_mode.as_tag(),
                );
                warn!("event: rejected payload: {}", err);
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
    meta: Query<EventQuery>,
    headers: HeaderMap,
    method: Method,
    path: MatchedPath,
    body: Bytes,
) -> Result<CaptureResponse, CaptureError> {
    let mut params: EventQuery = meta.0;

    match handle_event_payload(&state, &ip, &mut params, &headers, &method, &path, body).await {
        Err(CaptureError::BillingLimit) => Ok(CaptureResponse {
            status: CaptureResponseCode::Ok,
            quota_limited: Some(vec!["recordings".to_string()]),
        }),
        Err(err) => {
            report_internal_error_metrics(
                err.to_metric_tag(),
                "parsing",
                state.capture_mode.as_tag(),
            );
            error!("recordings: request payload parsing error: {:?}", err);
            Err(err)
        }
        Ok((context, events)) => {
            let count = events.len() as u64;
            if let Err(err) = process_replay_events(state.sink.clone(), events, &context).await {
                report_dropped_events(err.to_metric_tag(), count);
                report_internal_error_metrics(
                    err.to_metric_tag(),
                    "processing",
                    state.capture_mode.as_tag(),
                );
                warn!("recordings:rejected payload: {:?}", err);
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

#[instrument(skip_all, fields(events = events.len(), session_id, request_id))]
pub async fn process_replay_events<'a>(
    sink: Arc<dyn sinks::Event + Send + Sync>,
    mut events: Vec<RawEvent>,
    context: &'a ProcessingContext,
) -> Result<(), CaptureError> {
    Span::current().record("request_id", &context.request_id);

    // Compute the actual event timestamp using our timestamp parsing logic from the first event
    let sent_at_utc = context.sent_at.map(|sa| {
        DateTime::from_timestamp(sa.unix_timestamp(), sa.nanosecond()).unwrap_or_default()
    });
    let ignore_sent_at = events[0]
        .properties
        .get("$ignore_sent_at")
        .and_then(|v| v.as_bool())
        .unwrap_or(false);

    let computed_timestamp = timestamp::parse_event_timestamp(
        events[0].timestamp.as_deref(),
        events[0].offset,
        sent_at_utc,
        ignore_sent_at,
        context.now,
    );

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
        computed_timestamp: Some(computed_timestamp), // Use computed event timestamp
        event_name: "$snapshot_items".to_string(),
    };

    // Serialize snapshot data on blocking thread pool to avoid blocking executor
    let serialized_data = serialize_snapshot_data_async(
        distinct_id.clone(),
        session_id.clone(),
        window_id.clone(),
        snapshot_source.clone(),
        snapshot_items,
        snapshot_library.clone(),
    )
    .await?;

    let event = CapturedEvent {
        uuid,
        distinct_id: distinct_id.clone(),
        session_id: Some(session_id_str.to_string()),
        ip: context.client_ip.clone(),
        data: serialized_data,
        now: context
            .now
            .to_rfc3339_opts(chrono::SecondsFormat::AutoSi, true),
        sent_at: context.sent_at,
        token: context.token.clone(),
        event: "$snapshot_items".to_string(),
        timestamp: computed_timestamp,
        is_cookieless_mode,
        historical_migration: context.historical_migration,
    };

    sink.send(ProcessedEvent { metadata, event }).await
}

/// Synchronously serialize snapshot data to JSON string
/// This function is CPU-intensive and should be called from a blocking thread pool
pub fn serialize_snapshot_data_sync(
    distinct_id: String,
    session_id: Value,
    window_id: Value,
    snapshot_source: Value,
    snapshot_items: Vec<Value>,
    snapshot_library: String,
) -> String {
    json!({
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
    .to_string()
}

/// Asynchronously serialize snapshot data by offloading to blocking thread pool
/// This prevents blocking the async executor with CPU-intensive JSON serialization
pub async fn serialize_snapshot_data_async(
    distinct_id: String,
    session_id: Value,
    window_id: Value,
    snapshot_source: Value,
    snapshot_items: Vec<Value>,
    snapshot_library: String,
) -> Result<String, CaptureError> {
    tokio::task::spawn_blocking(move || {
        serialize_snapshot_data_sync(
            distinct_id,
            session_id,
            window_id,
            snapshot_source,
            snapshot_items,
            snapshot_library,
        )
    })
    .await
    .map_err(|e| {
        error!("failed to spawn blocking task for snapshot serialization: {}", e);
        CaptureError::NonRetryableSinkError
    })
}

fn snapshot_library_fallback_from(user_agent: Option<&String>) -> Option<String> {
    user_agent?
        .split('/')
        .next()
        .map(|s| s.to_string())
        .filter(|s| s.contains("posthog"))
        .or(Some("web".to_string()))
}
