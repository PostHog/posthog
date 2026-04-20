# AI Endpoint Parity Analysis

## Overview

This document compares the `/i/v0/ai` endpoint with the `/i/v0/e` (events) endpoint to identify feature gaps that need to be addressed to bring the AI endpoint to parity.

## Endpoint Comparison

### File References

- `/i/v0/e` handler: `rust/capture/src/v0_endpoint.rs:118`
- `/i/v0/ai` handler: `rust/capture/src/ai_endpoint.rs:71`
- Quota limiter: `rust/capture/src/limiters.rs`
- Token dropper: `rust/common/limiters/src/token_dropper.rs`

## Responsibility Matrix

### Features Only in `/i/v0/e` (Events Endpoint)

| Feature | Description | Priority | Status |
|---------|-------------|----------|--------|
| **Quota limiting and billing checks** | Apply quota limiter checks via `state.quota_limiter.check_and_filter()`. Drop events if billing limits are exceeded. | **HIGH** | ✅ DONE |
| **Token dropper filtering** | Filter events based on token dropper rules (rate limiting per token + distinct_id basis) | **HIGH** | ✅ DONE |
| **Historical rerouting** | Apply historical rerouting logic based on event timestamp age | **MEDIUM** | Not needed |

### Features Only in `/i/v0/ai` (AI Endpoint)

| Feature | Description | Notes |
|---------|-------------|-------|
| Multipart form-data parsing | Parse and validate multipart requests with events + blobs | AI-specific |
| Authorization header requirement | Require `Bearer <token>` in Authorization header | AI-specific |
| AI event type validation | Validate against 6 allowed AI event types: `$ai_generation`, `$ai_trace`, `$ai_span`, `$ai_embedding`, `$ai_metric`, `$ai_feedback` | AI-specific |
| `$ai_model` property validation | Ensure `$ai_model` is present and non-empty | AI-specific |
| Blob part handling | Handle blob parts and generate S3 placeholders | AI-specific |
| Byte range calculation | Calculate byte ranges for blob parts in concatenated format | AI-specific |
| Content-Type validation per part | Validate Content-Type for each multipart part | AI-specific |
| Strict size limits per part type | 32KB event, 960KB properties + event, configurable total | AI-specific |
| Duplicate property name detection | Prevent duplicate property names across parts | AI-specific |

### Features Present in Both

| Feature | Implementation Status |
|---------|----------------------|
| Gzip decompression | ✅ Both |
| Token validation | ✅ Both (format check, reject personal API keys) |
| Timestamp computation with clock skew correction | ✅ Both |
| Client IP extraction | ✅ Both |
| UUID handling | ✅ Both (generate v7 if missing) |
| Internal event IP redaction | ✅ Both (`capture_internal` property) |
| Kafka/sink publishing | ✅ Both |
| Metrics tracking middleware | ✅ Both |
| CORS handling | ✅ Both |
| User agent tracking | ✅ Both |

## Implemented Features

### 1. Quota Limiting and Billing Checks ✅ DONE

**Implementation:** The AI endpoint now enforces quota limits using the `LLMEvents` quota resource.

**How it works:**

1. After parsing the event metadata (event name, distinct_id), the endpoint calls `state.quota_limiter.check_and_filter()` with a single-element vector
2. The `is_llm_event()` predicate matches all `$ai_*` events
3. If over quota, returns HTTP 429 (Too Many Requests) with "billing limit reached" error
4. Metrics are reported via `capture_quota_limit_exceeded` and `capture_events_dropped_total`

**Key changes:**

- Added `HasEventName` trait to `common_types` for generic quota checking
- Refactored `check_and_filter` to be generic over `T: HasEventName`
- Implemented `HasEventName` for `EventMetadata` struct in AI endpoint

### 2. Token Dropper Filtering ✅ DONE

**Implementation:** The AI endpoint now checks the token dropper before processing blob parts.

**How it works:**

1. After parsing just the event metadata (via `retrieve_event_metadata()`), checks `state.token_dropper.should_drop(token, distinct_id)`
2. If dropped, returns HTTP 429 (Too Many Requests) with "billing limit reached" error
3. Metrics reported via `report_dropped_events("token_dropper", 1)`
4. Early return avoids parsing potentially large blob parts for dropped events

**Optimization:** The token dropper check happens before parsing blob parts, saving processing time when events are dropped.

### 3. Historical Rerouting - Not Needed

AI endpoint hardcodes `historical_migration: false`. This is intentional because:

- AI events are expected to be real-time (not backfilled)
- Historical rerouting adds complexity without clear benefit for AI use case
- Can be added later if backfill support is needed

## Notes

- The AI endpoint's unique features (multipart parsing, blob handling, etc.) are intentional and should be preserved
- Some differences are by design rather than gaps:
  - **Event type filtering**: `/e` uses denylist (blocks `$performance_event`), AI uses allowlist (only accepts 6 `$ai_*` events)
  - **Single event vs batch**: AI processes single events, `/e` supports batches
- Focus parity efforts on security, billing, and abuse prevention features
