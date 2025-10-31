# AI Endpoint Parity Analysis

## Overview

This document compares the `/i/v0/ai` endpoint with the `/i/v0/e` (events) endpoint to identify feature gaps that need to be addressed to bring the AI endpoint to parity.

## Endpoint Comparison

### File References
- `/i/v0/e` handler: `rust/capture/src/v0_endpoint.rs:118`
- `/i/v0/ai` handler: `rust/capture/src/ai_endpoint.rs:71`
- Quota limiter: `rust/capture/src/limiters/mod.rs:17`
- Token dropper: `rust/capture/src/limiters/token_bucket.rs:1`

## Responsibility Matrix

### Features Only in `/i/v0/e` (Events Endpoint)

| Feature | Description | Priority |
|---------|-------------|----------|
| **Quota limiting and billing checks** | Apply quota limiter checks via `state.quota_limiter.check_and_filter()`. Drop events if billing limits are exceeded. | **HIGH** |
| **Token dropper filtering** | Filter events based on token dropper rules (rate limiting per token + distinct_id basis) | **HIGH** |
| **Data type routing** | Determine data type routing (AnalyticsMain, AnalyticsHistorical, ClientIngestionWarning, HeatmapMain, ExceptionMain) | **MEDIUM** |
| **Historical rerouting** | Apply historical rerouting logic based on event timestamp age | **MEDIUM** |
| Multiple request format support | Support for array, batch, single, engage formats | **LOW** (AI has specific multipart format) |
| Multiple compression formats | Support GZIP, LZ64, Base64 detection | **LOW** (AI only needs GZIP) |
| Batch request support | Accept and process multiple events in a single request | **N/A** (AI processes one event per request by design) |

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

## Critical Gaps for AI Endpoint

### 1. Quota Limiting and Billing Checks (HIGH PRIORITY)

**Current State:** The AI endpoint has no quota or billing limit enforcement.

**How `/e` does it:** Calls `state.quota_limiter.check_and_filter()` on `Vec<RawEvent>` after token validation but before event processing (`v0_endpoint.rs:225-228`). Returns `CaptureError::BillingLimit` if exceeded, which is handled to return 200 OK without sending to Kafka.

**Required Changes:**
- AI endpoint needs to adapt this for single-event case (not a Vec)
- Call quota limiter after multipart parsing but before building Kafka event
- Handle `BillingLimit` error: return 200 OK without sending to Kafka
- Add appropriate error tracking and metrics

**Impact:** Without this, AI events bypass billing limits and quota enforcement entirely.

### 2. Token Dropper Filtering (HIGH PRIORITY)

**Current State:** The AI endpoint has no token dropper (rate limiting) support.

**How `/e` does it:** After processing events to `ProcessedEvent`, filters the Vec by calling `dropper.should_drop(&token, &distinct_id)` for each event (`v0_endpoint.rs:507-514`). Dropped events are not sent to Kafka and metrics are reported.

**Required Changes:**
- After building the `ProcessedEvent` in AI endpoint, check `state.token_dropper.should_drop()`
- If dropped: report metrics via `report_dropped_events("token_dropper", 1)` and return 200 OK without sending to Kafka
- If not dropped: proceed to send to Kafka as usual

**Impact:** No protection against abuse or rate limiting for AI endpoints.

### 3. Data Type Routing (MEDIUM PRIORITY)

**Current State:** AI endpoint hardcodes `DataType::AnalyticsMain` (`ai_endpoint.rs:278`).

**How `/e` does it:** Routes events based on event name and context (`v0_endpoint.rs:411-417`):
- `$$client_ingestion_warning` → ClientIngestionWarning
- `$exception` → ExceptionMain
- `$$heatmap` → HeatmapMain
- If `historical_migration=true` → AnalyticsHistorical
- Otherwise → AnalyticsMain

**Considerations:**
- AI events have a strict allowlist of 6 event types, none of which are `$$client_ingestion_warning`, `$exception`, or `$$heatmap`
- Historical migration flag is not exposed in AI endpoint
- Current hardcoding is likely intentional - AI events don't need special routing

**Required Decision:** Determine if AI events need multi-type routing or if AnalyticsMain is sufficient. Likely can remain as-is.

### 4. Historical Rerouting (MEDIUM PRIORITY)

**Current State:** AI endpoint has no historical data rerouting based on timestamp age. It hardcodes `historical_migration: false` (`ai_endpoint.rs:273`).

**How `/e` does it:** After computing event timestamp, checks `historical_cfg.should_reroute(data_type, computed_timestamp)` which compares event age against a configured threshold (`v0_endpoint.rs:459-466`). Old events get rerouted to `DataType::AnalyticsHistorical`.

**Considerations:**
- Does the AI use case need historical event support? (e.g., backfilling old AI traces)
- What is the expected latency for AI event ingestion? (typically real-time)
- AI events with large blobs may have different performance characteristics for historical processing

**Required Decision:** Determine if historical rerouting is needed for AI events. Likely not needed for initial implementation.

## Notes

- The AI endpoint's unique features (multipart parsing, blob handling, etc.) are intentional and should be preserved
- Some differences are by design rather than gaps:
  - **Event type filtering**: `/e` uses denylist (blocks `$performance_event`), AI uses allowlist (only accepts 6 `$ai_*` events)
  - **Single event vs batch**: AI processes single events, `/e` supports batches
- Focus parity efforts on security, billing, and abuse prevention features
