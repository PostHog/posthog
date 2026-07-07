use crate::{
    api::{
        body_read_metrics::BodyReadDuration,
        concurrency_metrics::ConcurrencyLimitWait,
        errors::{ClientFacingError, FlagError},
        flags_rate_limiter::RateLimitResult,
        types::{
            ConfigResponse, FlagsQueryParams, FlagsResponse, LegacyFlagsResponse, ServiceResponse,
        },
    },
    config::BotFilterMode,
    handler::{
        decoding, process_request, run_with_canonical_log, with_canonical_log,
        FlagsCanonicalLogLine, RequestContext,
    },
    metrics::consts::{
        FLAG_BOT_DETECTED_COUNTER, FLAG_RATE_LIMIT_CHECK_TIME_MS, FLAG_TOKEN_EXTRACT_TIME_MS,
    },
    router,
    utils::{bot_detection, user_agent::UserAgentInfo},
};
// TODO: stream this instead
use axum::extract::{Extension, MatchedPath, Query, State};
use axum::http::{HeaderMap, HeaderValue, Method, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::{debug_handler, Json};
use axum_client_ip::InsecureClientIp;
use bytes::Bytes;
use serde_json;
use std::collections::HashMap;
use std::net::IpAddr;
use std::sync::{Arc, OnceLock};
use tracing::Instrument;
use uuid::Uuid;

/// Extracts request ID from X-REQUEST-ID header, falling back to generating a new UUID if not present or invalid
/// Good for tracing logs from the Contour layer all the way to the property evaluation
fn extract_request_id(headers: &HeaderMap) -> Uuid {
    headers
        .get("X-REQUEST-ID")
        .and_then(|v| v.to_str().ok())
        .and_then(|s| s.parse::<Uuid>().ok())
        .unwrap_or_else(Uuid::new_v4)
}

/// Extracts client IP address from request headers, checking X-Forwarded-For first
/// then falling back to the direct client IP. Matches Python's get_ip_address function.
fn extract_client_ip(headers: &HeaderMap, fallback_ip: IpAddr) -> IpAddr {
    // Check X-Forwarded-For header first (case-insensitive)
    if let Some(forwarded_for) = headers.get("X-Forwarded-For") {
        if let Ok(forwarded_str) = forwarded_for.to_str() {
            // Take the first IP from the comma-separated list
            if let Some(first_ip) = forwarded_str.split(',').next() {
                let trimmed = first_ip.trim();

                // Strip port from IP address if present (Azure gateway compatibility)
                let ip_without_port = if trimmed.starts_with('[') {
                    // IPv6 with port (e.g., "[::1]:8080")
                    trimmed
                        .split(']')
                        .next()
                        .and_then(|s| s.strip_prefix('['))
                        .unwrap_or(trimmed)
                } else if trimmed.contains('.') {
                    // Likely IPv4 - check for port after the last dot
                    if let Some(colon_idx) = trimmed.rfind(':') {
                        if let Some(last_dot_idx) = trimmed.rfind('.') {
                            if colon_idx > last_dot_idx {
                                // Port comes after the last dot, so this is IPv4:port
                                &trimmed[..colon_idx]
                            } else {
                                // Colon before last dot? Malformed, return as-is
                                trimmed
                            }
                        } else {
                            // Has colon but no dot? Shouldn't happen for IPv4
                            trimmed
                        }
                    } else {
                        // No colon, just return the IP
                        trimmed
                    }
                } else {
                    // No dots and no brackets - assume IPv6 without port
                    // IPv6 can have colons as part of the address, so don't strip
                    trimmed
                };

                // Try to parse the IP address
                if let Ok(parsed_ip) = ip_without_port.parse::<IpAddr>() {
                    return parsed_ip;
                }
            }
        }
    }

    // Fall back to the direct client IP
    fallback_ip
}

/// Updates the canonical log with rate limit info and returns the error for early return.
fn rate_limit_error(error: FlagError) -> FlagError {
    with_canonical_log(|l| {
        l.rate_limited = true;
        l.set_error(&error);
    });
    error
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum BotFilterOutcome {
    /// No match, `Disabled` mode, or `LogOnly` classified — continue through
    /// the normal pipeline.
    Continue,
    /// `Enforced` classified — short-circuit with the minimal flags envelope.
    Reject,
}

/// Classify the request against the bot filter, stamp the canonical log,
/// and bump `flags_bot_detected_total`. Side effects are scoped so a unit
/// test can drive the function directly and inspect the log + recorded
/// metric without spinning up the request pipeline.
fn classify_and_stamp(
    log: &mut FlagsCanonicalLogLine,
    mode: &BotFilterMode,
    user_agent: Option<&str>,
    ip: IpAddr,
) -> BotFilterOutcome {
    if matches!(mode, BotFilterMode::Disabled) {
        return BotFilterOutcome::Continue;
    }
    let Some((category, source)) = bot_detection::classify_request(user_agent, ip) else {
        return BotFilterOutcome::Continue;
    };
    log.is_bot = true;
    log.bot_category = Some(category);
    log.bot_source = Some(source);

    let mode_label = match mode {
        BotFilterMode::LogOnly => "log_only",
        BotFilterMode::Enforced => "enforced",
        BotFilterMode::Disabled => unreachable!("guarded above"),
    };
    common_metrics::inc(
        FLAG_BOT_DETECTED_COUNTER,
        &[
            ("bot_category".to_string(), category.as_str().to_string()),
            ("bot_source".to_string(), source.as_str().to_string()),
            ("mode".to_string(), mode_label.to_string()),
        ],
        1,
    );

    match mode {
        BotFilterMode::Enforced => BotFilterOutcome::Reject,
        BotFilterMode::LogOnly => BotFilterOutcome::Continue,
        BotFilterMode::Disabled => unreachable!("guarded above"),
    }
}

/// Empty-flags + minimal-config response shared by the GET and bot-reject
/// paths. The envelope is selected by [`get_versioned_response`] so the
/// `is_from_legacy_decide × version` matrix lives in one place.
fn get_minimal_flags_response(
    headers: &HeaderMap,
    version: Option<&str>,
    is_from_legacy_decide: bool,
) -> Json<ServiceResponse> {
    let request_id = extract_request_id(headers);

    // `None` is preserved so `get_versioned_response` can apply its
    // decide/non-decide defaults.
    let version_num = version.map(|v| v.parse::<i32>().unwrap_or(1));

    let mut config = ConfigResponse::new();
    config.set(
        "supportedCompression",
        serde_json::json!(["gzip", "gzip-js"]),
    );
    config.set(
        "config",
        serde_json::json!({"enable_collect_everything": true}),
    );
    config.set("toolbarParams", serde_json::json!({}));
    config.set("isAuthenticated", serde_json::json!(false));
    config.set("sessionRecording", serde_json::json!(false));

    let mut response = FlagsResponse::new(false, HashMap::new(), None, request_id);
    response.config = config;

    let (service_response, _) =
        get_versioned_response(is_from_legacy_decide, version_num, response)
            .expect("get_versioned_response is total for any (bool, Option<i32>, FlagsResponse)");
    Json(service_response)
}

/// Determines the response format based on whether the request came from decide and the version parameter.
///
/// When the request is from decide (X-Original-Endpoint: decide):
/// - v=1 or missing -> DecideV1 response format
/// - v=2 -> DecideV2 response format  
/// - v=3 -> FlagsV1 response format
/// - v>=4 -> FlagsV2 response format
///
/// When the request is not from decide:
/// - v>=2 -> FlagsV2 response format
/// - v=1 or missing -> FlagsV1 response format
///
/// Returns a tuple of (response, format_name) for logging purposes
fn get_versioned_response(
    is_from_legacy_decide: bool,
    version: Option<i32>,
    response: FlagsResponse,
) -> Result<(ServiceResponse, &'static str), FlagError> {
    if is_from_legacy_decide {
        match version {
            Some(1) | None => Ok((
                ServiceResponse::DecideV1(crate::api::types::DecideV1Response::from_response(
                    response,
                )),
                "DecideV1",
            )),
            Some(2) => Ok((
                ServiceResponse::DecideV2(crate::api::types::DecideV2Response::from_response(
                    response,
                )),
                "DecideV2",
            )),
            Some(3) => Ok((
                ServiceResponse::Default(LegacyFlagsResponse::from_response(response)),
                "FlagsV1",
            )),
            Some(v) if v >= 4 => Ok((ServiceResponse::V2(response), "FlagsV2")),
            Some(_) => {
                // Any other version defaults to DecideV1
                Ok((
                    ServiceResponse::DecideV1(crate::api::types::DecideV1Response::from_response(
                        response,
                    )),
                    "DecideV1",
                ))
            }
        }
    } else {
        match version {
            Some(v) if v >= 2 => Ok((ServiceResponse::V2(response), "FlagsV2")),
            _ => Ok((
                ServiceResponse::Default(LegacyFlagsResponse::from_response(response)),
                "FlagsV1",
            )),
        }
    }
}

/// Feature flag evaluation endpoint.
/// Only supports a specific shape of data, and rejects any malformed data.
#[debug_handler]
#[allow(clippy::too_many_arguments)]
pub async fn flags(
    state: State<router::State>,
    InsecureClientIp(direct_ip): InsecureClientIp,
    Query(query_params): Query<FlagsQueryParams>,
    // Populated by the `record_concurrency_wait` middleware after
    // `ConcurrencyLimitLayer` hands off a permit. Optional so the handler
    // tolerates the layer pair being removed or temporarily disabled.
    concurrency_wait: Option<Extension<ConcurrencyLimitWait>>,
    // Populated by the `record_body_read` middleware after it buffers
    // the inbound POST body to memory. Optional so the handler tolerates
    // the shim being removed or absent on routes that bypass it (e.g. a
    // future `/flags`-only sub-router).
    body_read_duration: Option<Extension<BodyReadDuration>>,
    headers: HeaderMap,
    method: Method,
    path: MatchedPath,
    body: Bytes,
) -> Result<Response, FlagError> {
    let request_id = extract_request_id(&headers);

    // Extract client IP, checking X-Forwarded-For header first
    let ip = extract_client_ip(&headers, direct_ip);

    // Handle different HTTP methods (these don't need canonical logging)
    match method {
        Method::GET => {
            // The decide proxy forwards POSTs only, so GETs are always
            // direct hits (`is_from_legacy_decide = false`).
            return Ok(get_minimal_flags_response(
                &headers,
                query_params.version.as_deref(),
                false,
            )
            .into_response());
        }
        Method::POST => {
            // POST requests continue with full processing logic below
        }
        Method::HEAD => {
            // HEAD returns the same headers as GET but without body
            let response = (
                StatusCode::OK,
                [("content-type", "application/json")],
                axum::body::Body::empty(),
            )
                .into_response();
            return Ok(response);
        }
        Method::OPTIONS => {
            // OPTIONS should return allowed methods
            let response = (
                StatusCode::NO_CONTENT,
                [("allow", "GET, POST, OPTIONS, HEAD")],
            )
                .into_response();
            return Ok(response);
        }
        _ => {
            // Return 405 Method Not Allowed for all other methods
            let response = (
                StatusCode::METHOD_NOT_ALLOWED,
                [("allow", "GET, POST, OPTIONS, HEAD")],
            )
                .into_response();
            return Ok(response);
        }
    }

    // Convert IP to string once and reuse throughout the request
    let ip_string = ip.to_string();

    // Anchor for `flags_pre_handler_time_ms`. Covers all synchronous
    // pre-handler work (UA parse → IP rate-limit → bot check → token
    // rate-limit). The histogram is emitted from inside the canonical-log
    // scope once `team_id` is resolved.
    let pre_handler_start = std::time::Instant::now();

    // Parse User-Agent and extract SDK info for logging
    let user_agent = headers.get("user-agent").and_then(|v| v.to_str().ok());
    let ua_info = UserAgentInfo::parse(user_agent);

    let now_ms = chrono::Utc::now().timestamp_millis();

    // Contour sets X-Request-Start, so the timestamp is from trusted infrastructure.
    // We only filter out negative deltas (minor clock skew).
    let queue_time_ms: Option<i64> = headers
        .get("X-Request-Start")
        .and_then(|v| v.to_str().ok())
        .and_then(parse_request_start_ms)
        .map(|start_ms| now_ms - start_ms)
        .filter(|&delta| delta >= 0);

    // Concurrency-limit permit-wait, captured by the `record_concurrency_wait`
    // middleware. `as_millis()` returns `u128`; the `as u64` cast truncates
    // above `u64::MAX` ms — irrelevant in practice since reaching that bound
    // would take longer than the age of the universe.
    let concurrency_limit_wait_ms = concurrency_wait.map(|Extension(w)| w.0.as_millis() as u64);

    // Body-buffering wall-clock, captured by `record_body_read`. Sub-ms
    // precision (paired with the sub-ms-floor `BODY_READ_BUCKETS_MS`):
    // integer-ms truncation would collapse fast in-memory POSTs into the
    // 0-ms bucket and hide the very tail behavior the buckets exist to
    // surface.
    let body_read_ms = body_read_duration.map(|Extension(d)| d.0.as_secs_f64() * 1000.0);

    // Needed by both the bot short-circuit and the normal-path response
    // for envelope selection (Decide vs Flags shape).
    let is_from_legacy_decide = headers
        .get("X-Original-Endpoint")
        .and_then(|v| v.to_str().ok())
        .map(|v| v == "decide")
        .unwrap_or(false);

    // Mutable: the IP rate-limit and bot branches below mark fields on
    // it directly because they run outside the canonical-log scope.
    // Fields resolved inside `run_with_canonical_log` go through
    // `with_canonical_log()`.
    let mut canonical_log = FlagsCanonicalLogLine {
        request_id,
        ip: ip_string.clone(),
        user_agent: user_agent.map(|s| s.to_string()),
        lib: ua_info.lib_for_logging().map(str::to_string),
        // The decoded body can override this later. Until then, prefer SDK User-Agent over legacy query params.
        lib_version: initial_lib_version(&ua_info, &query_params),
        api_version: query_params.version.clone(),
        queue_time_ms,
        concurrency_limit_wait_ms,
        body_read_ms,
        ..Default::default()
    };

    // Runs before the bot check: UA matching is public and trivially
    // forgeable, so a spoofed Googlebot UA must still hit the per-IP
    // limiter. Mutates `canonical_log` directly since the task-local
    // scope has not been entered.
    let ip_rl_result = {
        let _t = common_metrics::timing_guard_high_precision(FLAG_RATE_LIMIT_CHECK_TIME_MS, &[])
            .label("kind", "ip");
        state.ip_rate_limiter.allow_request(&ip_string)
    };
    match ip_rl_result {
        RateLimitResult::Blocked => {
            let err = FlagError::ClientFacing(ClientFacingError::IpRateLimited);
            canonical_log.rate_limited = true;
            canonical_log.set_error(&err);
            // queue_time/body_read histograms emit with team_id="unknown".
            canonical_log.emit_short_circuit();
            return Err(err);
        }
        RateLimitResult::Warned => canonical_log.rate_limit_warned = true,
        RateLimitResult::Allowed => {}
    }

    // Runs after IP rate-limit (so spoofed UAs are still throttled) but
    // before token rate-limit, auth, billing, and evaluation. LogOnly
    // stamps the canonical log and falls through; Enforced short-circuits.
    let bot_outcome = classify_and_stamp(
        &mut canonical_log,
        &state.config.bot_filter_mode,
        user_agent,
        ip,
    );
    if bot_outcome == BotFilterOutcome::Reject {
        // `rate_limit_warned` stays on the canonical log but is not
        // surfaced as `X-PostHog-Rate-Limit-Warning`: bots do not read
        // response headers.
        canonical_log.emit_short_circuit();
        return Ok(get_minimal_flags_response(
            &headers,
            query_params.version.as_deref(),
            is_from_legacy_decide,
        )
        .into_response());
    }

    // Modify query params to enable config for decide requests
    let mut modified_query_params = query_params.clone();
    if is_from_legacy_decide && modified_query_params.config.is_none() {
        modified_query_params.config = Some(true);
    }

    // Default to v=2 and config=true when both params are missing
    // This provides the latest response format for clients that don't specify these params
    if modified_query_params.version.is_none() && modified_query_params.config.is_none() {
        modified_query_params.version = Some("2".to_string());
        modified_query_params.config = Some(true);
    }

    // Parse version from query params (needed for response formatting)
    let query_version = modified_query_params
        .version
        .as_deref()
        .map(|v| v.parse::<i32>().unwrap_or(1));

    // Install a body-logging side channel only when at least one team is
    // opted in. The OnceLock is filled inside the request decode flow with
    // the post-gzip / post-base64 bytes, and read back here once the
    // handler returns. This avoids decoding the body twice and ensures
    // base64-wrapped bodies log as their decoded JSON. `Arc::clone` here is
    // an O(1) refcount bump, paid only when at least one team is enabled.
    let decoded_body_slot = state
        .body_logger
        .has_any_enabled()
        .then(|| Arc::new(OnceLock::<Bytes>::new()));

    let context = RequestContext {
        request_id,
        state: state.clone(),
        ip,
        headers: headers.clone(),
        meta: modified_query_params,
        body,
        decoded_body_for_logging: decoded_body_slot.clone(),
    };

    // Create debug span for detailed tracing when debugging
    let _span = create_request_span(
        &headers,
        &query_params,
        &method,
        &path,
        &ip_string,
        request_id,
    );

    // Run the request within a canonical log scope.
    // All code within can use with_canonical_log() to update the log.
    //
    // Only the token-based rate limit runs here: it needs the parsed JSON
    // body, so it lives next to `process_request`. The IP-based limit
    // runs above, before the bot check, so a spoofed bot UA cannot
    // bypass it.
    let (result, mut log) = run_with_canonical_log(canonical_log, async {
        // Check token-based rate limit.
        // Extract token from body, use IP as fallback if extraction fails.
        // Time the JSON DOM scan separately — pathological large bodies
        // are the suspected outlier driver here.
        let rate_limit_key = {
            let _t = common_metrics::timing_guard_high_precision(FLAG_TOKEN_EXTRACT_TIME_MS, &[]);
            decoding::extract_token(&context.body)
        }
        .unwrap_or_else(|| ip_string.clone());
        let token_rl_result = {
            let _t =
                common_metrics::timing_guard_high_precision(FLAG_RATE_LIMIT_CHECK_TIME_MS, &[])
                    .label("kind", "token");
            state.flags_rate_limiter.allow_request(&rate_limit_key)
        };
        match token_rl_result {
            RateLimitResult::Blocked => {
                return Err(rate_limit_error(FlagError::ClientFacing(
                    ClientFacingError::TokenRateLimited,
                )));
            }
            // OR-combines with any IP warn already on the canonical log.
            RateLimitResult::Warned => with_canonical_log(|l| l.rate_limit_warned = true),
            RateLimitResult::Allowed => {}
        }

        // Stamp pre-handler duration into the canonical log just before we
        // hand off to async processing. `Instant::now()` is monotonic, so
        // this is robust to wall-clock jumps. Emission of the histogram is
        // deferred to `emit_timing_metrics` once `team_id` is resolved.
        let pre_handler_duration_ms = pre_handler_start.elapsed().as_millis() as u64;
        with_canonical_log(|l| l.pre_handler_duration_ms = Some(pre_handler_duration_ms));

        process_request(context).await
    })
    .instrument(_span)
    .await;

    // Emit DB operations metrics before the canonical log
    log.emit_db_operations_metrics();
    // Emit queue/pre-handler/concurrency-wait histograms with team_id labels.
    // Must run after `process_request` returns so `log.team_id` is populated.
    log.emit_timing_metrics();
    // Emit per-phase histograms accumulated by `PhaseGuard` drops inside
    // `process_request_inner`. Same `team_id` resolution requirement as
    // `emit_timing_metrics`, so it must run alongside it.
    log.emit_phase_metrics();

    match result {
        Ok(response) => {
            // Emit the body-log event before `response` is consumed by the
            // versioning step. Skipped when the team isn't opted in. The
            // request body bytes are the *decoded* form captured during
            // `parse_and_authenticate` — we never decode the body twice,
            // and base64-wrapped bodies log as JSON.
            let decoded_body = decoded_body_slot
                .as_ref()
                .and_then(|slot| slot.get().cloned());
            state
                .body_logger
                .log_response(request_id, log.team_id, decoded_body, &response);

            // Determine the response format based on whether request is from decide and version
            match get_versioned_response(is_from_legacy_decide, query_version, response) {
                Ok((versioned_response, _response_format)) => {
                    log.http_status = 200;
                    log.emit();

                    let mut response = Json(versioned_response).into_response();
                    if log.rate_limit_warned {
                        response.headers_mut().insert(
                            "X-PostHog-Rate-Limit-Warning",
                            HeaderValue::from_static("true"),
                        );
                    }
                    Ok(response)
                }
                Err(e) => {
                    log.emit_for_error(&e);
                    Err(e)
                }
            }
        }
        Err(e) => {
            log.emit_for_error(&e);
            Err(e)
        }
    }
}

fn initial_lib_version(ua_info: &UserAgentInfo, query_params: &FlagsQueryParams) -> Option<String> {
    ua_info
        .sdk_version
        .clone()
        .or_else(|| query_params.lib_version.clone())
}

fn create_request_span(
    headers: &HeaderMap,
    query_params: &FlagsQueryParams,
    method: &Method,
    path: &MatchedPath,
    ip: &str,
    request_id: Uuid,
) -> tracing::Span {
    let user_agent = headers
        .get("user-agent")
        .map_or("unknown", |v| v.to_str().unwrap_or("unknown"));
    let content_encoding = query_params
        .compression
        .as_ref()
        .map_or("none", |c| c.as_str());
    let content_type = headers
        .get("content-type")
        .map_or("unknown", |v| v.to_str().unwrap_or("unknown"));

    tracing::debug_span!(
        "request",
        user_agent = %user_agent,
        content_encoding = %content_encoding,
        content_type = %content_type,
        version = %query_params.version.as_deref().unwrap_or("unknown"),
        lib_version = %query_params.lib_version.as_deref().unwrap_or("unknown"),
        compression = %query_params.compression.as_ref().map_or("none", |c| c.as_str()),
        method = %method.as_str(),
        path = %path.as_str().trim_end_matches('/'),
        ip = %ip,
        sent_at = %query_params.sent_at.unwrap_or(0).to_string(),
        request_id = %request_id
    )
}

/// Parse the `X-Request-Start` header value into epoch milliseconds.
/// Contour sets this as `t=<epoch_seconds>.<fractional>` (e.g., `t=1774859827.782`).
/// Also accepts the bare numeric form without the `t=` prefix.
///
/// Parsing is intentionally strict: no whitespace trimming, no comma-splitting for
/// multi-value headers. This header is set exclusively by Contour in our infrastructure
/// with a well-defined format, and malformed values are silently dropped (returns `None`)
/// since this is metrics-only — strict rejection is the right tradeoff over accepting
/// ambiguous input.
///
/// Uses integer arithmetic to avoid f64 precision loss when converting seconds to ms.
fn parse_request_start_ms(value: &str) -> Option<i64> {
    let stripped = value.strip_prefix("t=").unwrap_or(value);
    if stripped.is_empty() {
        return None;
    }

    let (secs_str, frac_str) = match stripped.split_once('.') {
        Some((s, f)) => (s, Some(f)),
        None => (stripped, None),
    };

    let secs: i64 = secs_str.parse().ok()?;
    if secs < 0 {
        return None;
    }

    // Convert whole seconds to ms, guarding against overflow from extreme values.
    let mut ms = secs.checked_mul(1_000)?;

    // Parse up to 3 fractional digits as milliseconds, zero-padding on the right.
    // Reject if the fractional part is empty (trailing dot), contains non-digit characters,
    // or contains trailing garbage / multi-value separators.
    if let Some(frac) = frac_str {
        if frac.is_empty() || !frac.chars().all(|c| c.is_ascii_digit()) {
            return None;
        }
        let bytes = frac.as_bytes();
        // Compute ms from up to 3 fractional digits using integer arithmetic,
        // equivalent to right-padding with zeros and parsing as a 3-digit integer.
        let mut frac_ms: i64 = 0;
        let mut scale: i64 = 100; // hundreds, tens, ones
        for &b in bytes.iter().take(3) {
            frac_ms += (b - b'0') as i64 * scale;
            scale /= 10;
        }
        ms = ms.checked_add(frac_ms)?;
    }

    Some(ms)
}

#[cfg(test)]
mod tests {
    use crate::api::types::Compression;
    use rstest::rstest;

    use super::*;
    use axum::{
        body::Body,
        extract::{FromRequest, Request},
        http::Uri,
    };

    #[tokio::test]
    async fn test_query_param_extraction() {
        // Test case 1: Full query string
        let uri = Uri::from_static(
            "http://localhost:3001/flags/?v=3&compression=base64&ver=1.211.0&_=1738006794028",
        );
        let req = Request::builder().uri(uri).body(Body::empty()).unwrap();
        let Query(params) = Query::<FlagsQueryParams>::from_request(req, &())
            .await
            .unwrap();

        assert_eq!(params.version, Some("3".to_string()));
        assert_eq!(params.lib_version, Some("1.211.0".to_string()));
        assert_eq!(params.sent_at, Some(1738006794028));
        assert!(matches!(params.compression, Some(Compression::Base64)));

        // Test case 2: Partial query string
        let uri = Uri::from_static("http://localhost:3001/flags/?v=2&compression=gzip");
        let req = Request::builder().uri(uri).body(Body::empty()).unwrap();
        let Query(params) = Query::<FlagsQueryParams>::from_request(req, &())
            .await
            .unwrap();

        assert_eq!(params.version, Some("2".to_string()));
        assert!(matches!(params.compression, Some(Compression::Gzip)));
        assert_eq!(params.lib_version, None);
        assert_eq!(params.sent_at, None);

        // Test case 3: Empty query string
        let uri = Uri::from_static("http://localhost:3001/flags/");
        let req = Request::builder().uri(uri).body(Body::empty()).unwrap();
        let Query(params) = Query::<FlagsQueryParams>::from_request(req, &())
            .await
            .unwrap();

        assert_eq!(params.version, None);
        assert_eq!(params.compression, None);
        assert_eq!(params.lib_version, None);
        assert_eq!(params.sent_at, None);

        // Test case 4: Invalid compression type
        let uri = Uri::from_static("http://localhost:3001/flags/?compression=invalid");
        let req = Request::builder().uri(uri).body(Body::empty()).unwrap();
        let Query(params) = Query::<FlagsQueryParams>::from_request(req, &())
            .await
            .unwrap();

        assert!(matches!(params.compression, Some(Compression::Unsupported)));
    }

    #[test]
    fn test_initial_lib_version_prefers_user_agent_over_query_param() {
        let query_params = FlagsQueryParams {
            lib_version: Some("query-1.0".to_string()),
            ..Default::default()
        };
        let ua_info = UserAgentInfo::parse(Some("posthog-node/2.0"));

        assert_eq!(
            initial_lib_version(&ua_info, &query_params).as_deref(),
            Some("2.0")
        );
    }

    #[test]
    fn test_initial_lib_version_falls_back_to_query_param() {
        let query_params = FlagsQueryParams {
            lib_version: Some("query-1.0".to_string()),
            ..Default::default()
        };
        let ua_info = UserAgentInfo::parse(Some("Mozilla/5.0"));

        assert_eq!(
            initial_lib_version(&ua_info, &query_params).as_deref(),
            Some("query-1.0")
        );
    }

    #[test]
    fn test_default_params_logic() {
        // Test the parameter modification logic that's applied in the flags endpoint
        let mut params_both_none = FlagsQueryParams {
            version: None,
            config: None,
            compression: None,
            lib_version: None,
            sent_at: None,
            only_evaluate_survey_feature_flags: None,
            detailed_analysis: None,
            only_use_override_person_properties: None,
        };

        if params_both_none.version.is_none() && params_both_none.config.is_none() {
            params_both_none.version = Some("2".to_string());
            params_both_none.config = Some(true);
        }

        assert_eq!(params_both_none.version, Some("2".to_string()));
        assert_eq!(params_both_none.config, Some(true));

        // Test when only version is missing - no defaults should apply
        let mut params_version_missing = FlagsQueryParams {
            version: None,
            config: Some(false),
            compression: None,
            lib_version: None,
            sent_at: None,
            only_evaluate_survey_feature_flags: None,
            detailed_analysis: None,
            only_use_override_person_properties: None,
        };

        if params_version_missing.version.is_none() && params_version_missing.config.is_none() {
            params_version_missing.version = Some("2".to_string());
            params_version_missing.config = Some(true);
        }

        assert_eq!(params_version_missing.version, None);
        assert_eq!(params_version_missing.config, Some(false));

        // Test when only config is missing - no defaults should apply
        let mut params_config_missing = FlagsQueryParams {
            version: Some("1".to_string()),
            config: None,
            compression: None,
            lib_version: None,
            detailed_analysis: None,
            only_use_override_person_properties: None,
            sent_at: None,
            only_evaluate_survey_feature_flags: None,
        };

        if params_config_missing.version.is_none() && params_config_missing.config.is_none() {
            params_config_missing.version = Some("2".to_string());
            params_config_missing.config = Some(true);
        }

        assert_eq!(params_config_missing.version, Some("1".to_string()));
        assert_eq!(params_config_missing.config, None);
    }

    #[test]
    fn test_extract_client_ip() {
        use axum::http::HeaderValue;
        use std::net::{IpAddr, Ipv4Addr, Ipv6Addr};

        let fallback = IpAddr::V4(Ipv4Addr::new(127, 0, 0, 1));

        // Test case 1: X-Forwarded-For with single IP
        let mut headers = HeaderMap::new();
        headers.insert(
            "X-Forwarded-For",
            HeaderValue::from_str("192.168.1.1").unwrap(),
        );
        let ip = extract_client_ip(&headers, fallback);
        assert_eq!(ip, IpAddr::V4(Ipv4Addr::new(192, 168, 1, 1)));

        // Test case 2: X-Forwarded-For with multiple IPs (should take the first)
        headers.clear();
        headers.insert(
            "X-Forwarded-For",
            HeaderValue::from_str("10.0.0.1, 192.168.1.1, 172.16.0.1").unwrap(),
        );
        let ip = extract_client_ip(&headers, fallback);
        assert_eq!(ip, IpAddr::V4(Ipv4Addr::new(10, 0, 0, 1)));

        // Test case 3: X-Forwarded-For with IPv4 and port (Azure gateway compatibility)
        headers.clear();
        headers.insert(
            "X-Forwarded-For",
            HeaderValue::from_str("203.0.113.195:8080").unwrap(),
        );
        let ip = extract_client_ip(&headers, fallback);
        assert_eq!(ip, IpAddr::V4(Ipv4Addr::new(203, 0, 113, 195)));

        // Test case 4: X-Forwarded-For with IPv6
        headers.clear();
        headers.insert(
            "X-Forwarded-For",
            HeaderValue::from_str("2001:db8::8a2e:370:7334").unwrap(),
        );
        let ip = extract_client_ip(&headers, fallback);
        assert_eq!(
            ip,
            IpAddr::V6(Ipv6Addr::new(0x2001, 0xdb8, 0, 0, 0, 0x8a2e, 0x370, 0x7334))
        );

        // Test case 5: X-Forwarded-For with IPv6 and port
        headers.clear();
        headers.insert(
            "X-Forwarded-For",
            HeaderValue::from_str("[2001:db8::1]:8080").unwrap(),
        );
        let ip = extract_client_ip(&headers, fallback);
        assert_eq!(
            ip,
            IpAddr::V6(Ipv6Addr::new(0x2001, 0xdb8, 0, 0, 0, 0, 0, 1))
        );

        // Test case 6: No X-Forwarded-For header (should use fallback)
        headers.clear();
        let ip = extract_client_ip(&headers, fallback);
        assert_eq!(ip, fallback);

        // Test case 7: Invalid IP in X-Forwarded-For (should use fallback)
        headers.clear();
        headers.insert(
            "X-Forwarded-For",
            HeaderValue::from_str("invalid-ip").unwrap(),
        );
        let ip = extract_client_ip(&headers, fallback);
        assert_eq!(ip, fallback);

        // Test case 8: Empty X-Forwarded-For (should use fallback)
        headers.clear();
        headers.insert("X-Forwarded-For", HeaderValue::from_str("").unwrap());
        let ip = extract_client_ip(&headers, fallback);
        assert_eq!(ip, fallback);

        // Test case 9: IPv6 address that could be confused with IPv4:port
        headers.clear();
        headers.insert("X-Forwarded-For", HeaderValue::from_str("::1").unwrap());
        let ip = extract_client_ip(&headers, fallback);
        assert_eq!(ip, IpAddr::V6(Ipv6Addr::new(0, 0, 0, 0, 0, 0, 0, 1)));

        // Test case 10: Compact IPv6 address with few colons
        headers.clear();
        headers.insert("X-Forwarded-For", HeaderValue::from_str("fe80::1").unwrap());
        let ip = extract_client_ip(&headers, fallback);
        assert_eq!(ip, IpAddr::V6(Ipv6Addr::new(0xfe80, 0, 0, 0, 0, 0, 0, 1)));
    }

    #[test]
    fn test_extract_request_id() {
        use axum::http::HeaderValue;

        // Test with valid UUID in header
        let mut headers = HeaderMap::new();
        let valid_uuid = "550e8400-e29b-41d4-a716-446655440000";
        headers.insert("x-request-id", HeaderValue::from_static(valid_uuid));

        let extracted_id = extract_request_id(&headers);
        assert_eq!(extracted_id.to_string(), valid_uuid);

        // Test with invalid UUID in header - should generate new UUID
        let mut headers_invalid = HeaderMap::new();
        headers_invalid.insert("x-request-id", HeaderValue::from_static("invalid-uuid"));

        let extracted_id_invalid = extract_request_id(&headers_invalid);
        // Should be a valid UUID (not the invalid string)
        assert_ne!(extracted_id_invalid.to_string(), "invalid-uuid");
        assert!(extracted_id_invalid.to_string().len() == 36); // UUID format

        // Test without header - should generate new UUID
        let empty_headers = HeaderMap::new();
        let extracted_id_empty = extract_request_id(&empty_headers);
        assert!(extracted_id_empty.to_string().len() == 36); // UUID format

        // Two calls without header should generate different UUIDs
        let extracted_id_empty2 = extract_request_id(&empty_headers);
        assert_ne!(extracted_id_empty, extracted_id_empty2);
    }

    #[rstest]
    #[case("t=1774859827.782", Some(1774859827782))]
    #[case("1774859827.782", Some(1774859827782))]
    #[case("t=1774859827", Some(1774859827000))]
    #[case("t=", None)]
    #[case("t=abc", None)]
    #[case("", None)]
    #[case("not-a-number", None)]
    #[case("t=-1.0", None)]
    #[case("-100", None)]
    #[case("NaN", None)]
    #[case("inf", None)]
    #[case("t=Infinity", None)]
    #[case("t=-inf", None)]
    #[case(" t=1774859827.782", None)]
    #[case("t=1774859827.782 ", None)]
    #[case("t=1774859827.782, t=1774859828.000", None)]
    #[case("t=1774859827.", None)] // trailing dot with empty fractional part
    #[case("1774859827.7821", Some(1774859827782))] // extra digits beyond ms are truncated
    fn test_parse_request_start_ms(#[case] input: &str, #[case] expected: Option<i64>) {
        assert_eq!(parse_request_start_ms(input), expected);
    }

    mod bot_filter_tests {
        use super::*;
        use crate::utils::bot_detection::{BotCategory, BotSource};
        use metrics_util::debugging::DebuggingRecorder;
        use std::net::Ipv4Addr;

        const GOOGLEBOT_UA: &str =
            "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)";
        // Interior of `66.249.66.0/27` — a densely-covered Googlebot /24 in
        // the published JSON. The classifier is JSON-precise so unpublished
        // /27 gaps (e.g. `.79.96/27`) no longer match.
        const GOOGLEBOT_IP: IpAddr = IpAddr::V4(Ipv4Addr::new(66, 249, 66, 0));
        const BENIGN_IP: IpAddr = IpAddr::V4(Ipv4Addr::new(8, 8, 8, 8));
        const BENIGN_UA: &str = "Mozilla/5.0 (Macintosh; Intel Mac OS X) Chrome/120 Safari/537.36";

        fn fresh_log() -> FlagsCanonicalLogLine {
            FlagsCanonicalLogLine::new(Uuid::new_v4(), "10.0.0.1".to_string())
        }

        /// True iff `FLAG_BOT_DETECTED_COUNTER` was emitted with all three
        /// labels matching.
        fn counter_labels_match(
            recorder: &DebuggingRecorder,
            mode: &str,
            category: &str,
            source: &str,
        ) -> bool {
            recorder
                .snapshotter()
                .snapshot()
                .into_vec()
                .into_iter()
                .any(|(ckey, _, _, _)| {
                    let key = ckey.key();
                    if key.name() != FLAG_BOT_DETECTED_COUNTER {
                        return false;
                    }
                    let pairs: Vec<(String, String)> = key
                        .labels()
                        .map(|l| (l.key().to_string(), l.value().to_string()))
                        .collect();
                    pairs.iter().any(|(k, v)| k == "mode" && v == mode)
                        && pairs
                            .iter()
                            .any(|(k, v)| k == "bot_category" && v == category)
                        && pairs.iter().any(|(k, v)| k == "bot_source" && v == source)
                })
        }

        fn any_bot_counter_emitted(recorder: &DebuggingRecorder) -> bool {
            recorder
                .snapshotter()
                .snapshot()
                .into_vec()
                .into_iter()
                .any(|(ckey, _, _, _)| ckey.key().name() == FLAG_BOT_DETECTED_COUNTER)
        }

        #[test]
        fn disabled_mode_does_not_stamp_or_count() {
            let recorder = DebuggingRecorder::new();
            let mut log = fresh_log();
            let outcome = metrics::with_local_recorder(&recorder, || {
                classify_and_stamp(
                    &mut log,
                    &BotFilterMode::Disabled,
                    Some(GOOGLEBOT_UA),
                    GOOGLEBOT_IP,
                )
            });
            assert_eq!(outcome, BotFilterOutcome::Continue);
            assert!(!log.is_bot);
            assert_eq!(log.bot_category, None);
            assert_eq!(log.bot_source, None);
            assert!(!any_bot_counter_emitted(&recorder));
        }

        #[test]
        fn no_match_continues_without_stamping() {
            let recorder = DebuggingRecorder::new();
            let mut log = fresh_log();
            let outcome = metrics::with_local_recorder(&recorder, || {
                classify_and_stamp(
                    &mut log,
                    &BotFilterMode::Enforced,
                    Some(BENIGN_UA),
                    BENIGN_IP,
                )
            });
            assert_eq!(outcome, BotFilterOutcome::Continue);
            assert!(!log.is_bot);
            assert!(!any_bot_counter_emitted(&recorder));
        }

        #[test]
        fn log_only_ua_match_continues_and_records_observability() {
            let recorder = DebuggingRecorder::new();
            let mut log = fresh_log();
            let outcome = metrics::with_local_recorder(&recorder, || {
                classify_and_stamp(
                    &mut log,
                    &BotFilterMode::LogOnly,
                    Some(GOOGLEBOT_UA),
                    BENIGN_IP,
                )
            });
            assert_eq!(outcome, BotFilterOutcome::Continue);
            assert!(log.is_bot);
            assert_eq!(log.bot_category, Some(BotCategory::Google));
            assert_eq!(log.bot_source, Some(BotSource::UserAgent));
            assert!(counter_labels_match(
                &recorder,
                "log_only",
                "google",
                "user_agent"
            ));
        }

        #[test]
        fn log_only_ip_match_stamps_with_ip_source() {
            let recorder = DebuggingRecorder::new();
            let mut log = fresh_log();
            let outcome = metrics::with_local_recorder(&recorder, || {
                classify_and_stamp(
                    &mut log,
                    &BotFilterMode::LogOnly,
                    Some(BENIGN_UA),
                    GOOGLEBOT_IP,
                )
            });
            assert_eq!(outcome, BotFilterOutcome::Continue);
            assert!(log.is_bot);
            assert_eq!(log.bot_category, Some(BotCategory::Google));
            assert_eq!(log.bot_source, Some(BotSource::Ip));
            assert!(counter_labels_match(&recorder, "log_only", "google", "ip"));
        }

        #[test]
        fn enforced_match_rejects_and_records_observability() {
            let recorder = DebuggingRecorder::new();
            let mut log = fresh_log();
            let outcome = metrics::with_local_recorder(&recorder, || {
                classify_and_stamp(
                    &mut log,
                    &BotFilterMode::Enforced,
                    Some(GOOGLEBOT_UA),
                    BENIGN_IP,
                )
            });
            assert_eq!(outcome, BotFilterOutcome::Reject);
            assert!(log.is_bot);
            assert_eq!(log.bot_category, Some(BotCategory::Google));
            assert_eq!(log.bot_source, Some(BotSource::UserAgent));
            assert!(counter_labels_match(
                &recorder,
                "enforced",
                "google",
                "user_agent"
            ));
        }
    }
}
