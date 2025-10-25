# LLMA Integration Test Suite

## Overview

This document describes the Rust integration test suite for the LLM Analytics capture service. These tests validate HTTP endpoint behavior, multipart parsing, and validation logic without requiring external dependencies.

**Implementation Requirement**: Each phase in the implementation plan must pass its corresponding integration tests before proceeding to the next phase. This ensures incremental validation and prevents regression as new features are added.

**See Also**: `llma-acceptance-test-suite.md` for end-to-end tests that require full PostHog infrastructure.

## Test Architecture

### Test Environment

- **In-Memory Router**: Axum router running in test process using `axum-test-helper::TestClient`
- **Multipart Construction**: Using `reqwest::multipart::Form` to build proper multipart bodies
- **Mock Dependencies**: Mock Redis, time source, and event sink for isolation
- **No External Services**: No database, S3, Kafka, or real authentication required

### Test Framework

- **Integration Tests**: Capture service tests from HTTP request through parsing and validation
- **Parameterized Tests**: Test variations across different event types, blob sizes, and configurations
- **Async Testing**: Support for testing concurrent requests and large payload processing
- **Test Utilities**:
  - `CapturingSink`: Mock event sink that stores events in memory for Kafka output verification
  - `FixedTime`: Deterministic time source for reproducible tests
  - `TestSink`: Simple no-op sink for HTTP endpoint tests

### Test Data

- **AI Event Types**: Primarily `$ai_generation` for validation testing
- **Blob Sizes**: Small (< 1KB), Medium (~100KB), Empty
- **Content Types**: `application/json`, `text/plain`, `application/octet-stream`
- **Multipart Boundaries**: Various boundary strings including custom boundaries

## Test Scenarios

**Phase Completion Requirement**: All integration tests for a phase must pass before implementation can proceed to the next phase. This gate ensures quality and prevents compound issues from multiple incomplete features.

### Phase 1: HTTP Endpoint

#### Scenario 1.1: Basic Routing

- **Test**: Verify `/i/v0/ai` endpoint is accessible and returns correct response codes
- **Validation**: HTTP 200 for valid requests, proper error codes for invalid requests
- **Tests Implemented**:
  - `test_ai_endpoint_get_returns_405`: GET requests return 405
  - `test_ai_endpoint_put_returns_405`: PUT requests return 405
  - `test_ai_endpoint_delete_returns_405`: DELETE requests return 405
  - `test_ai_endpoint_no_auth_returns_401`: No auth header returns 401

#### Scenario 1.2: Multipart Parsing

- **Test**: Send multipart requests with various boundary strings and blob configurations
- **Validation**: All parts parsed correctly, blob data extracted without corruption
- **Variations**: Different boundary formats, multiple blobs, mixed content types
- **Tests Implemented**:
  - `test_multipart_parsing_with_multiple_blobs`: Parse 4 parts (event + 3 blobs)
  - `test_multipart_parsing_with_mixed_content_types`: JSON, text, binary
  - `test_multipart_parsing_with_large_blob`: Large blob (~100KB)
  - `test_multipart_parsing_with_empty_blob`: Empty blob handling

#### Scenario 1.3: Boundary Validation

- **Test**: Send requests with malformed boundaries, missing boundaries, boundary collisions
- **Validation**: Appropriate error responses, no server crashes, proper error logging
- **Tests Implemented**:
  - `test_multipart_missing_boundary_returns_400`: Missing boundary parameter
  - `test_multipart_corrupted_boundary_returns_400`: Mismatched boundary

#### Scenario 1.4: Basic Validation

- **Test**: Send events with valid/invalid event types, missing required properties, duplicate blob properties
- **Validation**: Only accepted AI event types (`$ai_generation`, `$ai_trace`, `$ai_span`, `$ai_embedding`, `$ai_metric`, `$ai_feedback`) are processed; invalid events rejected with proper error messages
- **Tests Implemented**:
  - `test_all_allowed_ai_event_types_accepted`: All six accepted event types pass validation
  - `test_invalid_ai_event_type_returns_400`: Invalid AI event types rejected (e.g., `$ai_unknown`, `$ai_custom`)
  - `test_invalid_event_name_not_ai_prefix_returns_400`: Non-AI event names rejected
  - `test_invalid_event_name_regular_event_returns_400`: Regular events rejected (e.g., `$pageview`)
  - `test_invalid_event_name_custom_event_returns_400`: Custom events rejected
  - `test_missing_required_ai_properties_returns_400`: Missing `$ai_model`
  - `test_empty_event_name_returns_400`: Empty event names
  - `test_missing_distinct_id_returns_400`: Missing distinct_id
  - `test_multipart_event_not_first_returns_400`: Event part ordering

#### Scenario 1.5: Content Type Validation

- **Test**: Send requests with wrong content type or empty body
- **Validation**: Only `multipart/form-data` accepted
- **Tests Implemented**:
  - `test_ai_endpoint_wrong_content_type_returns_400`: Non-multipart type
  - `test_ai_endpoint_empty_body_returns_400`: Empty body

#### Scenario 1.6: Kafka Publishing and S3 Placeholders

- **Test**: Verify events are correctly published to Kafka with S3 placeholder URLs
- **Validation**: Events contain S3 placeholders with sequential byte ranges pointing to same file
- **Tests Implemented**:
  - `test_ai_event_published_to_kafka`: Basic event publishing verification
  - `test_ai_event_with_blobs_published_with_s3_placeholders`: S3 placeholder URL format and sequential ranges
  - `test_ai_event_with_multiple_blobs_sequential_ranges`: Multiple blobs with correct sequential byte ranges
  - `test_ai_event_metadata_preserved_in_kafka`: Event metadata preservation in Kafka

### Phase 5: Authorization

#### Scenario 5.1: Request Signature Verification

- **Test**: Test signature validation for various request formats
- **Validation**: Valid signatures accepted, invalid signatures rejected

#### Scenario 5.2: Pre-processing Authentication

- **Test**: Verify authentication occurs before multipart parsing
- **Validation**: Invalid auth rejected immediately, no resource consumption for unauthorized requests

### Phase 7: Compression

#### Scenario 7.1: Client-side Compression

- **Test**: Send pre-compressed blobs with `Content-Encoding: gzip`
- **Validation**: Compressed blobs stored correctly, decompression works for retrieval

#### Scenario 7.2: Server-side Compression

- **Test**: Send uncompressed JSON/text blobs
- **Validation**: Server compresses before S3 storage, compression metadata preserved

### Phase 8: Schema Validation

#### Scenario 8.1: Event Schema Validation

- **Test**: Send events conforming to and violating strict schemas for each AI event type
- **Validation**: Valid events accepted, invalid events rejected with detailed error messages
- **Variations**: Missing required fields, extra properties, wrong data types

#### Scenario 8.2: Content-Type Validation

- **Test**: Send blobs with various Content-Type headers
- **Validation**: Supported types accepted, unsupported types handled according to policy

#### Scenario 8.3: Content-Length Validation

- **Test**: Mismatched Content-Length headers and actual blob sizes
- **Validation**: Mismatches detected and handled appropriately

## Error Recovery and Edge Cases

### Edge Case Scenarios

#### Scenario E.1: Malformed Requests

- **Test**: Invalid JSON, corrupted multipart data, missing required headers
- **Validation**: Graceful error handling, no server crashes, proper error responses

## Local Development Testing

### Test Implementation

**Location**: `rust/capture/tests/integration_ai_endpoint.rs`

**Framework**: Tokio async tests with `axum-test-helper`

**Dependencies**:

- `reqwest` with `multipart` feature for constructing test requests
- `axum-test-helper` for in-memory HTTP testing
- `serde_json` for JSON manipulation

### Running Tests

```bash
# Run all AI endpoint integration tests
cargo test --test integration_ai_endpoint

# Run specific test
cargo test --test integration_ai_endpoint test_multipart_parsing_with_multiple_blobs

# Run with detailed output
cargo test --test integration_ai_endpoint -- --nocapture
```

### Test Characteristics

- Run in-memory with no external dependencies
- Mock Redis, time source, and event sink
- Fast execution suitable for CI/CD
- Test HTTP request/response handling only

## Phase Gating

- **Mandatory Testing**: All integration tests for a phase must pass before proceeding to implementation of the next phase
- **Regression Prevention**: Previous phase tests continue to run to ensure no regression
- **Incremental Validation**: Each phase builds upon validated functionality from previous phases
