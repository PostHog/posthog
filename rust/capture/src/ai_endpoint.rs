use axum::body::Body;
use axum::extract::{MatchedPath, State};
use axum::http::HeaderMap;
use axum::response::Json;
use axum_client_ip::InsecureClientIp;
use bytes::Bytes;
use common_types::{CapturedEvent, HasEventName};
use futures::stream;
use limiters::redis::QuotaResource;
use metrics::counter;
use multer::{parse_boundary, Multipart};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use time::format_description::well_known::Iso8601;
use time::OffsetDateTime;
use tracing::{debug, error, warn};
use uuid::Uuid;

use common_ingestion_warnings::WarningRequestContext;

use crate::ai_rejection::{AiFailure, AiRejection, ALLOWED_AI_EVENTS};
use crate::api::{CaptureError, CaptureResponse, CaptureResponseCode};
use crate::event_restrictions::{
    AppliedRestrictions, EventContext as RestrictionEventContext, Pipeline,
};
use crate::events::ai_byte_limit::charge_ai_bytes;
use crate::events::overflow_stamping::stamp_overflow_reason;
use crate::extractors::extract_body_with_timeout;
use crate::ingestion_warnings::ai::emit_ai_failure_warning;
use crate::ingestion_warnings::{unknown_if_missing, within_bound};
use crate::payload::decompression::decompress_gzip_to_bytes;
use crate::prometheus::{report_dropped_events, report_internal_error_metrics};
use crate::router::State as AppState;
use crate::timestamp;
use crate::token::validate_token;
use crate::v0_request::{
    exceeds_max_ai_event_bytes, DataType, ProcessedEvent, ProcessedEventMetadata,
};
use crate::v1::gateway_provenance as gp;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PartInfo {
    pub name: String,
    pub length: usize,
    #[serde(rename = "content-type")]
    pub content_type: Option<String>,
    #[serde(rename = "content-encoding")]
    pub content_encoding: Option<String>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct AIEndpointResponse {
    pub accepted_parts: Vec<PartInfo>,
}

/// Metadata extracted from the event part for early checks (token dropper, quota)
#[derive(Debug)]
struct EventMetadata {
    event_name: String,
    distinct_id: String,
    event_json: Value,
    event_part_info: PartInfo,
}

impl EventMetadata {
    fn event_uuid(&self) -> Option<String> {
        self.event_json
            .as_object()
            .and_then(|obj| obj.get("uuid"))
            .and_then(|v| v.as_str())
            .map(String::from)
    }
}

impl HasEventName for EventMetadata {
    fn event_name(&self) -> &str {
        &self.event_name
    }
}

/// Raw multipart parts retrieved from the request
#[derive(Debug)]
struct RetrievedMultipartParts {
    event_json: Value,
    properties_json: Value,
    accepted_parts: Vec<PartInfo>,
}

/// Result of parsing multipart AI event data
#[derive(Debug)]
struct ParsedMultipartData {
    accepted_parts: Vec<PartInfo>,
    event: Value,
    event_name: String,
    distinct_id: String,
    event_uuid: Uuid,
    timestamp: Option<String>,
    sent_at: Option<OffsetDateTime>,
}

pub async fn ai_handler(
    State(state): State<AppState>,
    ip: Option<InsecureClientIp>,
    path: MatchedPath,
    headers: HeaderMap,
    body: Body,
) -> Result<Json<AIEndpointResponse>, CaptureError> {
    let emitter = state.ingestion_warning_emitter.clone();
    // Filled by the inner handler once the token is known, and enriched once the
    // event part parses. Staying `None` is what keeps pre-token failures — an
    // oversized body, a missing Bearer header — from emitting a warning nobody
    // can be attributed for.
    let mut attribution = None;

    let result = ai_handler_inner(state, ip, path, headers, body, &mut attribution).await;

    let failure = match result {
        Ok(response) => return Ok(response),
        Err(failure) => failure,
    };

    if let Some(request) = attribution.as_ref() {
        emit_ai_failure_warning(emitter.as_deref(), request, &failure);
    }

    let err = CaptureError::from(failure);
    report_internal_error_metrics(err.to_metric_tag(), "ai");
    Err(err)
}

async fn ai_handler_inner(
    state: AppState,
    ip: Option<InsecureClientIp>,
    path: MatchedPath,
    headers: HeaderMap,
    body: Body,
    attribution: &mut Option<WarningRequestContext>,
) -> Result<Json<AIEndpointResponse>, AiFailure> {
    debug!("Received request to /i/v0/ai endpoint");

    // Extract body with timed streaming (same pattern as analytics/recordings handlers)
    // Use 110% of ai_max_sum_of_parts_bytes to account for multipart overhead (matches DefaultBodyLimit layer)
    let body_limit = (state.ai_max_sum_of_parts_bytes as f64 * 1.1) as usize;
    let body = extract_body_with_timeout(
        body,
        body_limit,
        state.body_chunk_read_timeout,
        state.body_read_chunk_size_kb,
        path.as_str(),
    )
    .await?;

    // Check for empty body
    if body.is_empty() {
        return Err(CaptureError::EmptyPayload.into());
    }

    // Authenticate before any CPU/memory-intensive decompression work
    let auth_header = headers
        .get("authorization")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("");

    if !auth_header.starts_with("Bearer ") {
        return Err(CaptureError::NoTokenError.into());
    }

    let token = &auth_header[7..]; // Remove "Bearer " prefix
    validate_token(token).map_err(CaptureError::from)?;

    // Everything from here on is attributable. SDK identity isn't known yet —
    // it lives in the event part's properties — so warnings raised before that
    // part parses stamp the unknown fallback.
    *attribution = Some(ai_request_context(token, path.as_str(), None));

    // Check for Content-Encoding header and decompress if needed
    let content_encoding = headers
        .get("content-encoding")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("");

    let decompressed_body = if content_encoding.eq_ignore_ascii_case("gzip") {
        debug!("Decompressing gzip-encoded request body");
        Bytes::from(decompress_gzip_to_bytes(&body, body_limit)?)
    } else {
        body
    };

    // Check content type - must be multipart/form-data
    let content_type = headers
        .get("content-type")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("");

    if !content_type.starts_with("multipart/form-data") {
        return Err(AiRejection::NotMultipart.into());
    }

    // Extract boundary from Content-Type header using multer's built-in parser
    let boundary =
        parse_boundary(content_type).map_err(|e| AiRejection::InvalidBoundary(e.to_string()))?;

    // Capture body size for logging (before we move the Bytes)
    let body_size = decompressed_body.len();

    // Create multipart parser once - reused for all parsing steps
    let body_stream = stream::once(std::future::ready(Ok::<Bytes, std::io::Error>(
        decompressed_body,
    )));
    let mut multipart = Multipart::new(body_stream, &boundary);

    // Step 1: Retrieve event metadata (parses only the first 'event' part)
    let event_metadata = retrieve_event_metadata(&mut multipart).await?;

    // The event part carries $lib/$lib_version, so attribution can be upgraded
    // from the unknown fallback for everything that fails after this point.
    *attribution = Some(ai_request_context(
        token,
        path.as_str(),
        Some(&event_metadata.event_json),
    ));

    // Step 2: Check event restrictions early - before parsing remaining parts
    let applied_restrictions = if let Some(ref service) = state.event_restriction_service {
        let uuid_str = event_metadata.event_uuid();
        let event_ctx = RestrictionEventContext {
            distinct_id: Some(&event_metadata.distinct_id),
            session_id: None,
            event_name: Some(&event_metadata.event_name),
            event_uuid: uuid_str.as_deref(),
            now_ts: state.timesource.current_time().timestamp(),
        };

        let applied = service
            .get_restrictions(token, &event_ctx, Pipeline::Ai)
            .await;

        if applied.should_drop() {
            report_dropped_events("event_restriction_drop", 1);
            return Ok(Json(AIEndpointResponse {
                accepted_parts: vec![],
            }));
        }

        applied
    } else {
        AppliedRestrictions::default()
    };

    // Step 3: Check token dropper - before parsing remaining parts
    // Token dropper silently drops events (returns 200) to avoid alerting clients
    if state
        .token_dropper
        .should_drop(token, &event_metadata.distinct_id)
    {
        report_dropped_events("token_dropper", 1);
        // Return success response with empty accepted_parts to avoid alerting clients
        return Ok(Json(AIEndpointResponse {
            accepted_parts: vec![],
        }));
    }

    // AI-gateway provenance: a fresh, valid signature marks the event trusted.
    // Verify here, before the quota limiter, while distinct_id (in the signed tuple)
    // is known; the outcome gates the limiter below and the stamp/strip before Kafka.
    // sig + signed_at + request_id ride in headers.
    // TODO: relocate gateway_provenance out of v1/ now the v0 path uses it too.
    let gw_sig = gp::parse_signature(&headers);
    let gw_outcome = match (state.ai_gateway_signing_secret.as_deref(), gw_sig.as_ref()) {
        (Some(secret), Some(sig)) => gp::verify(
            secret.as_bytes(),
            token,
            &event_metadata.distinct_id,
            sig,
            state.timesource.current_time(),
        ),
        _ => gp::Provenance::Invalid,
    };
    let gw_request_id = gw_sig.map(|s| s.request_id).unwrap_or_default();
    let gw_trusted = gw_outcome == gp::Provenance::Verified && !gw_request_id.is_empty();

    // Step 4: quota limiter. Verified gateway events are wallet-billed, so they're
    // exempt from the scoped LLM-events quota but still subject to the team's global
    // Events quota (matching the v1 flow).
    let event_metadata = if gw_trusted {
        if state
            .quota_limiter
            .is_quota_limited_v1(token, &QuotaResource::Events)
            .await
        {
            return Err(CaptureError::BillingLimit.into());
        }
        event_metadata
    } else {
        // We pass a single-element vec and check if it's filtered out
        let filtered = state
            .quota_limiter
            .check_and_filter(token, vec![event_metadata])
            .await?;

        // If the event was filtered out by quota limiter, return billing limit error
        filtered
            .into_iter()
            .next()
            .ok_or(CaptureError::BillingLimit)?
    };

    // Step 5: Retrieve and validate remaining multipart parts (continues parsing from multipart)
    let parts =
        retrieve_multipart_parts(&mut multipart, event_metadata, state.ai_max_event_bytes).await?;

    // Step 6: Parse the parts
    let mut parsed = parse_multipart_data(parts)?;

    // AI-gateway provenance: stamp the trusted marker (overwriting client values) on a
    // verified event, else strip the whole $ai_gateway* namespace so a forged marker
    // can't reach billing. The verified metric always fires; the strip metric only fires
    // when a gateway prop was actually present, so ordinary $ai_* events stay silent.
    if let Some(event_obj) = parsed.event.as_object_mut() {
        if gw_trusted {
            // A verified event was exempted from the LLM-events quota, so it must carry
            // the stamp or billing would double-count it toward AIO. Guarantee a
            // properties object here rather than relying on validate_event_structure
            // having produced one, so the exemption and the stamp can't drift apart.
            let properties = event_obj
                .entry("properties")
                .or_insert_with(|| Value::Object(serde_json::Map::new()));
            if !properties.is_object() {
                *properties = Value::Object(serde_json::Map::new());
            }
            if let Some(properties) = properties.as_object_mut() {
                gp::stamp_verified(properties, &gw_request_id);
                counter!(gp::PROVENANCE_METRIC, "reason" => "verified").increment(1);
            }
        } else if let Some(properties) = event_obj
            .get_mut("properties")
            .and_then(|p| p.as_object_mut())
        {
            let before = properties.len();
            let forged = properties.contains_key(gp::VERIFIED_PROPERTY);
            gp::strip_gateway(properties);
            if properties.len() != before {
                let reason = if forged {
                    "forged"
                } else if gw_outcome == gp::Provenance::Stale {
                    "stale"
                } else {
                    "stripped"
                };
                counter!(gp::PROVENANCE_METRIC, "reason" => reason).increment(1);
            }
        }
    }

    // Step 8: Build Kafka event
    // Extract IP address, defaulting to 127.0.0.1 if not available (e.g., in tests)
    let client_ip = ip
        .map(|InsecureClientIp(addr)| addr.to_string())
        .unwrap_or_else(|| "127.0.0.1".to_string());
    let (accepted_parts, mut processed_event) =
        build_kafka_event(parsed, token, &client_ip, &state, &applied_restrictions)?;

    // Step 8a: Charge the AI lane's per-project byte budget. This endpoint
    // builds its event at the handler and reaches the sink through neither
    // analytics pipeline, so without this a sender could spend an unbounded
    // number of bytes here while the same bytes on `/i/v0/ai/batch` are capped.
    //
    // Charged on the serialized event the sink would produce, which is the
    // measure the legacy path charges, and after restrictions, quota, and the
    // combined-size ceiling — nothing that was never going to publish spends
    // the project's budget.
    //
    // An over-budget event answers 200 with no accepted parts, the shape this
    // handler already uses for the token dropper and for a `DropEvent`
    // restriction. A rate drop is ops-imposed, so it is reported to the client
    // only as "nothing was accepted", never as a request failure.
    if let Some(ref limiter) = state.ai_byte_rate_limiter {
        if charge_ai_bytes(limiter, token, processed_event.event.data.len()).await {
            report_dropped_events("ai_byte_rate_limited", 1);
            return Ok(Json(AIEndpointResponse {
                accepted_parts: vec![],
            }));
        }
    }

    // Step 8b: Apply the in-process OverflowLimiter governor. The analytics
    // pipeline stamps overflow reasons inside `process_events`, but AI
    // bypasses that path, so we invoke the shared helper here to preserve
    // OverflowLimiter parity on `capture-ai-*` deploys (where
    // `OVERFLOW_ENABLED=true`). `force_overflow` already stamped on
    // `processed_event.metadata` by `build_kafka_event` is honored by the
    // helper's short-circuit.
    stamp_overflow_reason(
        std::slice::from_mut(&mut processed_event),
        state.overflow_limiter.as_ref(),
        state.ai_events_overflow_limiter.as_ref(),
    );

    // Step 9: Send event to Kafka
    state.sink.send(processed_event).await.map_err(|e| {
        warn!("Failed to send AI event to Kafka: {:?}", e);
        e
    })?;

    // Log request details for debugging
    debug!("AI endpoint request validated and sent to Kafka successfully");
    debug!("Body size: {} bytes", body_size);
    debug!("Content-Type: {}", content_type);
    debug!("Boundary: {}", boundary);
    debug!("Token: {}...", &token[..std::cmp::min(8, token.len())]);
    debug!("Accepted parts: {}", accepted_parts.len());

    let response = AIEndpointResponse { accepted_parts };

    Ok(Json(response))
}

pub async fn options() -> Result<CaptureResponse, CaptureError> {
    Ok(CaptureResponse {
        status: CaptureResponseCode::Ok,
        quota_limited: None,
    })
}

/// Warning attribution for an AI request.
///
/// The endpoint has no `PostHog-Sdk-Info` contract, so SDK identity comes from
/// the event's own `$lib`/`$lib_version` properties. `event` is `None` before the
/// event part has parsed, which is when several rejections fire, so both fields
/// fall back to the unknown placeholder rather than dropping the keys.
fn ai_request_context(token: &str, path: &str, event: Option<&Value>) -> WarningRequestContext {
    let properties = event
        .and_then(|e| e.as_object())
        .and_then(|obj| obj.get("properties"))
        .and_then(|props| props.as_object());
    let property = |key: &str| {
        properties
            .and_then(|props| props.get(key))
            .and_then(|v| v.as_str())
            .and_then(|v| within_bound(v.to_string()))
    };

    WarningRequestContext {
        token: token.to_string(),
        lib: unknown_if_missing(property("$lib").as_deref()),
        lib_version: unknown_if_missing(property("$lib_version").as_deref()),
        path: path.to_string(),
    }
}

/// Retrieve event metadata from the first multipart part for early checks.
/// This parses only the 'event' part to extract event_name and distinct_id
/// before processing the rest of the multipart body.
/// The multipart parser is passed in and will be reused for remaining parts.
async fn retrieve_event_metadata(
    multipart: &mut Multipart<'_>,
) -> Result<EventMetadata, AiRejection> {
    // Get the first field - must be 'event'
    let field = multipart
        .next_field()
        .await
        .map_err(|e| AiRejection::MultipartParseFailed(e.to_string()))?
        .ok_or(AiRejection::MissingEventPart)?;

    let field_name = field.name().unwrap_or("unknown").to_string();
    let content_type = field.content_type().map(|ct| ct.to_string());
    let content_encoding = field
        .headers()
        .get("content-encoding")
        .and_then(|v| v.to_str().ok())
        .map(|s| s.to_string());

    // Validate that the first part is the event part
    if field_name != "event" {
        return Err(AiRejection::FirstPartNotEvent(field_name));
    }

    // Read the field data
    let field_data = field
        .bytes()
        .await
        .map_err(|e| AiRejection::FieldDataUnreadable(e.to_string()))?;

    // Process the event part
    let (event_json, event_part_info) =
        process_event_part(field_data, content_type, content_encoding)?;

    // Extract event_name and distinct_id
    let event_obj = event_json.as_object().ok_or(AiRejection::EventNotObject)?;

    let event_name = event_obj
        .get("event")
        .and_then(|v| v.as_str())
        .ok_or(AiRejection::EventMissingName)?
        .to_string();

    let distinct_id = event_obj
        .get("distinct_id")
        .and_then(|v| v.as_str())
        .ok_or(AiRejection::EventMissingDistinctId)?
        .to_string();

    Ok(EventMetadata {
        event_name,
        distinct_id,
        event_json,
        event_part_info,
    })
}

/// Build a Kafka event from parsed multipart data
fn build_kafka_event(
    parsed: ParsedMultipartData,
    token: &str,
    client_ip: &str,
    state: &AppState,
    restrictions: &AppliedRestrictions,
) -> Result<(Vec<PartInfo>, ProcessedEvent), CaptureError> {
    // Get current time
    let now = state.timesource.current_time();

    // Convert sent_at to chrono DateTime for timestamp computation
    // If conversion fails, treat it as if sent_at wasn't provided (rather than using epoch)
    let sent_at_utc = parsed
        .sent_at
        .and_then(|sa| chrono::DateTime::from_timestamp(sa.unix_timestamp(), sa.nanosecond()));

    // Extract $ignore_sent_at from event properties
    let ignore_sent_at = parsed
        .event
        .as_object()
        .and_then(|obj| obj.get("properties"))
        .and_then(|props| props.as_object())
        .and_then(|props| props.get("$ignore_sent_at"))
        .and_then(|v| v.as_bool())
        .unwrap_or(false);

    // Compute timestamp
    let computed_timestamp = timestamp::parse_event_timestamp(
        parsed.timestamp.as_deref(),
        None, // offset
        sent_at_utc,
        ignore_sent_at,
        now,
    )
    .timestamp;

    // Serialize the event to JSON (this is what goes in the "data" field)
    let data = serde_json::to_string(&parsed.event).map_err(|e| {
        error!("Failed to serialize AI event: {}", e);
        CaptureError::NonRetryableSinkError
    })?;

    // Redact the IP address of internally-generated events when tagged as such
    let resolved_ip = if parsed
        .event
        .as_object()
        .and_then(|obj| obj.get("properties"))
        .and_then(|props| props.as_object())
        .map(|props| props.contains_key("capture_internal"))
        .unwrap_or(false)
    {
        "127.0.0.1".to_string()
    } else {
        client_ip.to_string()
    };

    // Create CapturedEvent
    let captured_event = CapturedEvent {
        uuid: parsed.event_uuid,
        distinct_id: parsed.distinct_id.clone(),
        session_id: None,
        ip: resolved_ip,
        data,
        now: now.to_rfc3339_opts(chrono::SecondsFormat::AutoSi, true),
        sent_at: parsed.sent_at,
        token: token.to_string(),
        event: parsed.event_name.clone(),
        timestamp: computed_timestamp,
        is_cookieless_mode: false,
        historical_migration: false,
    };

    // Create metadata
    let metadata = ProcessedEventMetadata {
        data_type: DataType::AiEvents,
        session_id: None,
        computed_timestamp: Some(computed_timestamp),
        event_name: parsed.event_name,
        force_overflow: restrictions.force_overflow(),
        skip_person_processing: restrictions.skip_person_processing(),
        redirect_to_dlq: restrictions.redirect_to_dlq(),
        redirect_to_topic: restrictions.redirect_to_topic().map(|s| s.to_string()),
        skip_heatmap_processing: false,
        overflow_reason: None,
        distinct_id_truncated_from: None,
    };

    // Create ProcessedEvent
    let processed_event = ProcessedEvent {
        event: captured_event,
        metadata,
    };

    Ok((parsed.accepted_parts, processed_event))
}

/// Process the event metadata part
fn process_event_part(
    field_data: Bytes,
    content_type: Option<String>,
    content_encoding: Option<String>,
) -> Result<(Value, PartInfo), AiRejection> {
    const MAX_EVENT_SIZE: usize = 32 * 1024; // 32KB

    let event_size = field_data.len();

    // Check event size limit
    if event_size > MAX_EVENT_SIZE {
        return Err(AiRejection::EventPartTooBig {
            size: event_size,
            max: MAX_EVENT_SIZE,
        });
    }

    // Parse the event JSON
    let event_json_str =
        std::str::from_utf8(&field_data).map_err(|_| AiRejection::EventPartNotUtf8)?;

    let event_json =
        serde_json::from_str(event_json_str).map_err(|_| AiRejection::EventPartNotJson)?;

    let part_info = PartInfo {
        name: "event".to_string(),
        length: field_data.len(),
        content_type,
        content_encoding,
    };

    debug!("Event part parsed successfully");
    Ok((event_json, part_info))
}

/// Process the event properties part
fn process_properties_part(
    field_data: Bytes,
    content_type: Option<String>,
    content_encoding: Option<String>,
) -> Result<(Value, PartInfo), AiRejection> {
    // Parse the properties JSON
    let properties_json_str =
        std::str::from_utf8(&field_data).map_err(|_| AiRejection::PropertiesPartNotUtf8)?;

    let properties_json = serde_json::from_str(properties_json_str)
        .map_err(|_| AiRejection::PropertiesPartNotJson)?;

    let part_info = PartInfo {
        name: "event.properties".to_string(),
        length: field_data.len(),
        content_type,
        content_encoding,
    };

    debug!("Properties part parsed successfully");
    Ok((properties_json, part_info))
}

/// Retrieve and validate multipart parts from the request body.
/// The event metadata (first part) has already been parsed by retrieve_event_metadata.
/// Continues parsing from where retrieve_event_metadata left off.
async fn retrieve_multipart_parts(
    multipart: &mut Multipart<'_>,
    event_metadata: EventMetadata,
    max_event_bytes: u64,
) -> Result<RetrievedMultipartParts, AiRejection> {
    let mut part_count = 0;
    let mut accepted_parts = Vec::new();
    let mut properties_json: Option<Value> = None;
    let event_size: usize = event_metadata.event_part_info.length;
    let mut properties_size: usize = 0;

    // Add the pre-parsed event part info
    accepted_parts.push(event_metadata.event_part_info);

    // Parse each part
    while let Some(field) = multipart
        .next_field()
        .await
        .map_err(|e| AiRejection::MultipartParseFailed(e.to_string()))?
    {
        part_count += 1;

        // Extract all field information before consuming the field
        let field_name = field.name().unwrap_or("unknown").to_string();
        let content_type = field.content_type().map(|ct| ct.to_string());
        let content_encoding = field
            .headers()
            .get("content-encoding")
            .and_then(|v| v.to_str().ok())
            .map(|s| s.to_string());

        debug!(
            "Processing multipart field: {} (part #{})",
            field_name, part_count
        );

        // Event part was already consumed by retrieve_event_metadata - reject duplicates
        if field_name == "event" {
            return Err(AiRejection::DuplicateEventPart);
        }

        // Read the field data to get the length (this consumes the field)
        let field_data = field
            .bytes()
            .await
            .map_err(|e| AiRejection::FieldDataUnreadable(e.to_string()))?;

        // Process based on field name
        if field_name == "event.properties" {
            properties_size = field_data.len();
            let (properties, part_info) =
                process_properties_part(field_data, content_type, content_encoding)?;
            properties_json = Some(properties);
            accepted_parts.push(part_info);
        } else {
            return Err(AiRejection::UnknownField(field_name));
        }
    }

    // The event and its properties are merged into one event downstream, so the
    // deployment's per-event ceiling applies to their sum. Rejecting here keeps
    // an oversized event off the producer, whose own cap would refuse it only
    // after the whole body had been read.
    let combined_size = event_size + properties_size;
    if exceeds_max_ai_event_bytes(combined_size, max_event_bytes) {
        return Err(AiRejection::EventAndPropertiesTooBig {
            size: combined_size,
            max: max_event_bytes as usize,
        });
    }

    // Use the event JSON from the pre-parsed metadata
    let event = event_metadata.event_json;

    // Check for conflicting properties sources
    let has_embedded_properties = event
        .as_object()
        .and_then(|obj| obj.get("properties"))
        .is_some();

    if has_embedded_properties && properties_json.is_some() {
        return Err(AiRejection::ConflictingProperties);
    }

    // Determine which properties to use:
    // - If there's a separate event.properties part, use it
    // - If there's no separate part, extract embedded properties from the event
    // - If neither exists, use empty object
    let final_properties = if let Some(props) = properties_json {
        props
    } else {
        // No separate part - check for embedded properties
        event
            .as_object()
            .and_then(|obj| obj.get("properties").cloned())
            .unwrap_or(serde_json::json!({}))
    };

    debug!("Multipart parts retrieved: {part_count} parts processed");

    Ok(RetrievedMultipartParts {
        event_json: event,
        properties_json: final_properties,
        accepted_parts,
    })
}

/// Parse retrieved multipart parts and validate event structure.
fn parse_multipart_data(
    parts: RetrievedMultipartParts,
) -> Result<ParsedMultipartData, AiRejection> {
    // Merge properties into the event
    let mut event = parts.event_json;
    if let Some(event_obj) = event.as_object_mut() {
        event_obj.insert("properties".to_string(), parts.properties_json);
    } else {
        return Err(AiRejection::EventNotObject);
    }

    // Now validate the complete event structure
    validate_event_structure(&event)?;

    // Extract event_name, distinct_id, uuid, and timestamp for later use
    let event_name = event
        .as_object()
        .and_then(|obj| obj.get("event"))
        .and_then(|v| v.as_str())
        .ok_or(AiRejection::EventNameRequired)?
        .to_string();

    let distinct_id = event
        .as_object()
        .and_then(|obj| obj.get("distinct_id"))
        .and_then(|v| v.as_str())
        .ok_or(AiRejection::DistinctIdRequired)?
        .to_string();

    // Extract and validate UUID
    let event_uuid = event
        .as_object()
        .and_then(|obj| obj.get("uuid"))
        .and_then(|v| v.as_str())
        .ok_or(AiRejection::EventUuidRequired)
        .and_then(|uuid_str| {
            Uuid::parse_str(uuid_str).map_err(|e| AiRejection::EventUuidInvalid(e.to_string()))
        })?;

    let timestamp = event
        .as_object()
        .and_then(|obj| obj.get("timestamp"))
        .and_then(|v| v.as_str())
        .map(|s| s.to_string());

    // Extract and parse sent_at
    let sent_at = event
        .as_object()
        .and_then(|obj| obj.get("sent_at"))
        .and_then(|v| v.as_str())
        .and_then(|sent_at_str| OffsetDateTime::parse(sent_at_str, &Iso8601::DEFAULT).ok());

    Ok(ParsedMultipartData {
        accepted_parts: parts.accepted_parts,
        event,
        event_name,
        distinct_id,
        event_uuid,
        timestamp,
        sent_at,
    })
}

/// Validate the structure and content of an AI event
fn validate_event_structure(event: &Value) -> Result<(), AiRejection> {
    // Check if event is an object
    let event_obj = event.as_object().ok_or(AiRejection::EventNotObject)?;

    // Validate event name
    let event_name = event_obj
        .get("event")
        .and_then(|v| v.as_str())
        .ok_or(AiRejection::EventMissingName)?;

    if event_name.is_empty() {
        return Err(AiRejection::EventNameEmpty);
    }

    if !ALLOWED_AI_EVENTS.contains(&event_name) {
        return Err(AiRejection::EventNameNotAllowed(event_name.to_string()));
    }

    // Validate distinct_id
    let distinct_id = event_obj
        .get("distinct_id")
        .and_then(|v| v.as_str())
        .ok_or(AiRejection::EventMissingDistinctId)?;

    if distinct_id.is_empty() {
        return Err(AiRejection::DistinctIdEmpty);
    }

    // Validate properties object
    let properties = event_obj
        .get("properties")
        .and_then(|v| v.as_object())
        .ok_or(AiRejection::EventMissingProperties)?;

    // Validate required AI properties
    if !properties.contains_key("$ai_model") {
        return Err(AiRejection::AiModelMissing);
    }

    let ai_model = properties
        .get("$ai_model")
        .and_then(|v| v.as_str())
        .ok_or(AiRejection::AiModelNotString)?;

    if ai_model.is_empty() {
        return Err(AiRejection::AiModelEmpty);
    }

    debug!(
        "Event validation passed: event='{}', distinct_id='{}', ai_model='{}'",
        event_name, distinct_id, ai_model
    );

    Ok(())
}
