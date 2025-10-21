# LLMA Integration Test Suite

## Overview

This document describes the high-level architecture and test scenarios for the LLM Analytics capture pipeline integration test suite. The tests validate the complete end-to-end flow from multipart request ingestion through S3 storage to event processing.

**Implementation Requirement**: Each phase in the implementation plan must pass its corresponding integration tests before proceeding to the next phase. This ensures incremental validation and prevents regression as new features are added.

## Test Architecture

### Test Environment

- **Local PostHog Deployment**: Complete local PostHog setup including capture service with `/ai` endpoint
- **S3-Compatible Storage**: Local S3-compatible storage for blob storage with direct access for verification
- **PostHog Query API**: Used to fetch processed events from the ingestion pipeline for validation
- **Direct S3 Access**: Test suite has direct S3 client access to verify blob storage and retrieval
- **Test Fixtures**: Predefined multipart requests with various blob sizes and types

### Test Framework

- **Integration Tests**: Full pipeline tests from HTTP request through ingestion to event storage
- **PostHog API Client**: Direct integration with PostHog query API to verify event processing
- **S3 Client**: Direct access to verify S3 blob storage, metadata, and retrieval
- **Parameterized Tests**: Test variations across different event types, blob sizes, and configurations
- **Async Testing**: Support for testing concurrent requests and large payload processing

### Test Data

- **AI Event Types**: `$ai_trace`, `$ai_span`, `$ai_generation`, `$ai_embedding`, `$ai_metric`, `$ai_feedback`
- **Blob Sizes**: Small (1KB), Medium (100KB), Large (1MB), Extra Large (10MB+)
- **Content Types**: `application/json`, `text/plain`, `application/octet-stream`
- **Compression**: Gzipped and uncompressed blobs
- **Encoding**: Raw binary, text, and base64-encoded blobs
- **Multipart Boundaries**: Various boundary strings to test collision handling

## Test Scenarios

**Phase Completion Requirement**: All integration tests for a phase must pass before implementation can proceed to the next phase. This gate ensures quality and prevents compound issues from multiple incomplete features.

### Phase 1: HTTP Endpoint

#### Scenario 1.1: Basic Routing

- **Test**: Verify `/ai` endpoint is accessible and returns correct response codes
- **Validation**: HTTP 200 for valid requests, proper error codes for invalid requests

#### Scenario 1.2: Multipart Parsing

- **Test**: Send multipart requests with various boundary strings and blob configurations
- **Validation**: All parts parsed correctly, blob data extracted without corruption§
- **Variations**: Different boundary formats, multiple blobs, mixed content types

#### Scenario 1.3: Boundary Validation

- **Test**: Send requests with malformed boundaries, missing boundaries, boundary collisions
- **Validation**: Appropriate error responses, no server crashes, proper error logging

#### Scenario 1.4: Event Processing Verification

- **Test**: Send multipart request and verify event reaches PostHog query API
- **Validation**: Use PostHog query API to fetch processed event, verify blob placeholders correctly inserted

#### Scenario 1.5: Basic Validation

- **Test**: Send events with invalid names (not starting with `$ai_`), duplicate blob properties
- **Validation**: Invalid events rejected, valid events processed, proper error messages

### Phase 2: Basic S3 Uploads

#### Scenario 2.1: Individual Blob Upload

- **Test**: Upload blobs of various sizes as separate S3 objects
- **Validation**: Verify each blob stored correctly, S3 URLs generated in event properties
- **Variations**: Small/medium/large blobs, different content types

#### Scenario 2.2: S3 URL Generation and Access

- **Test**: Verify generated S3 URLs in PostHog events point to accessible objects
- **Validation**: Query PostHog API for events, extract S3 URLs, verify blobs retrievable from S3

#### Scenario 2.3: Blob Metadata Storage

- **Test**: Verify S3 object metadata is stored correctly
- **Validation**: Use S3 client to inspect object metadata - Content-Type, size, team_id present

#### Scenario 2.4: Team Data Isolation

- **Test**: Multiple teams uploading simultaneously
- **Validation**: Verify S3 key prefixes are team-scoped, no cross-team data access, proper S3 path isolation

### Phase 3: S3 Infrastructure & Deployment

#### Scenario 3.1: S3 Bucket Configuration

- **Test**: Verify S3 bucket structure and lifecycle policies
- **Validation**: Use S3 client to verify correct `llma/` prefix structure, retention policies configured

### Phase 4: Multipart File Processing

#### Scenario 4.1: Multipart File Creation

- **Test**: Upload events with multiple blobs, verify multipart/mixed format
- **Validation**: Use S3 client to verify single S3 file contains all blobs, proper MIME boundaries, metadata preserved
- **Variations**: 2-10 blobs per event, mixed content types, different blob sizes

#### Scenario 4.2: Byte Range URLs and Access

- **Test**: Verify S3 URLs in PostHog events include correct byte range parameters
- **Validation**: Query PostHog API for events, verify URLs contain range parameters, use S3 client to test range requests

#### Scenario 4.3: Content Type Handling

- **Test**: Mix of JSON, text, and binary blobs in single multipart file
- **Validation**: Content types preserved in multipart format, correctly parsed

### Phase 5: Authorization

#### Scenario 5.1: API Key Authentication

- **Test**: Send requests with valid/invalid/missing API keys
- **Validation**: Valid keys accepted, invalid keys rejected with 401, proper error messages

#### Scenario 5.2: Request Signature Verification

- **Test**: Test signature validation for various request formats
- **Validation**: Valid signatures accepted, invalid signatures rejected

#### Scenario 5.3: Pre-processing Authentication

- **Test**: Verify authentication occurs before multipart parsing
- **Validation**: Invalid auth rejected immediately, no resource consumption for unauthorized requests

### Phase 7: Compression

#### Scenario 7.1: Client-side Compression

- **Test**: Send pre-compressed blobs with `Content-Encoding: gzip`
- **Validation**: Compressed blobs stored correctly, decompression works for retrieval

#### Scenario 7.2: Server-side Compression

- **Test**: Send uncompressed JSON/text blobs
- **Validation**: Server compresses before S3 storage, compression metadata preserved

#### Scenario 7.3: Mixed Compression

- **Test**: Single request with both compressed and uncompressed blobs
- **Validation**: Each blob handled according to its compression state

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

### Phase 9: Limits (Optional) - DO NOT IMPLEMENT, TBD

### Phase 10: Data Deletion (Optional) - DO NOT IMPLEMENT, TBD

### Cross-Team Isolation Testing

## Error Recovery and Edge Cases

### Edge Case Scenarios

#### Scenario E.1: Malformed Requests

- **Test**: Invalid JSON, corrupted multipart data, missing required headers
- **Validation**: Graceful error handling, no server crashes, proper error responses

#### Scenario E.2: S3 Service Interruption

- **Test**: Simulate S3 unavailability during uploads
- **Validation**: Proper error responses, retry logic works, no data loss

#### Scenario E.3: Kafka Unavailability

- **Test**: Simulate Kafka unavailability during event publishing
- **Validation**: Appropriate error handling, request failure communicated to client

## Local Development Testing

### Test Implementation

The integration test suite will be implemented in Rust to align with the capture service's existing toolchain and avoid introducing additional dependencies.

#### Test Structure

- **Location**: `tests/integration/llma/` directory within the capture service codebase
- **Framework**: Standard Rust testing framework with `tokio-test` for async operations
- **Dependencies**:
  - `reqwest` for HTTP client operations
  - `aws-sdk-s3` for S3 client operations
  - `serde_json` for JSON manipulation
  - `multipart` for constructing test requests

#### Test Organization

```text
tests/
└── integration/
    └── llma/
        ├── mod.rs              # Common test utilities and setup
        ├── phase_01_http.rs    # Phase 1: HTTP Endpoint tests
        ├── phase_02_s3.rs      # Phase 2: Basic S3 Upload tests
        ├── phase_03_infra.rs   # Phase 3: S3 Infrastructure tests
        ├── phase_04_multipart.rs # Phase 4: Multipart File tests
        ├── phase_05_auth.rs    # Phase 5: Authorization tests
        ├── phase_07_compression.rs # Phase 7: Compression tests
        ├── phase_08_validation.rs # Phase 8: Schema Validation tests
        └── fixtures/           # Test data and multipart request templates
```

### Local Test Environment Setup

#### Prerequisites

- **Local PostHog Instance**: Full PostHog deployment running locally
- **Local S3 Storage**: S3-compatible storage (configured via PostHog local setup)
- **Capture Service**: Running with `/ai` endpoint enabled
- **Test Configuration**: Environment variables for service endpoints and credentials

#### Environment Configuration

```bash
# PostHog Local Instance
export POSTHOG_HOST="http://localhost:8000"
export POSTHOG_API_KEY="test_api_key_123"
export POSTHOG_PROJECT_ID="1"

# Local S3 Configuration
export AWS_ENDPOINT_URL="http://localhost:9000"  # Local S3-compatible endpoint
export AWS_ACCESS_KEY_ID="minioadmin"
export AWS_SECRET_ACCESS_KEY="minioadmin"
export AWS_DEFAULT_REGION="us-east-1"
export LLMA_S3_BUCKET="posthog-llma-test"

# Capture Service
export CAPTURE_ENDPOINT="http://localhost:3000"
export LLMA_TEST_MODE="local"
```

### Test Execution

#### Running Tests

```bash
# Run all LLMA integration tests
cargo test --test llma_integration

# Run specific phase tests
cargo test --test llma_integration phase_01
cargo test --test llma_integration phase_02

# Run with detailed output
cargo test --test llma_integration -- --nocapture

# Run tests in sequence (important for phase gating)
cargo test --test llma_integration -- --test-threads=1
```

#### Test Utilities

Each test phase will include common utilities for:

- **Multipart Request Builder**: Construct multipart/form-data requests with event JSON and blob parts
- **S3 Client Wrapper**: Direct S3 operations for validation and cleanup
- **PostHog API Client**: Query PostHog API to verify event processing
- **Test Data Generators**: Create various blob sizes, content types, and event payloads
- **Cleanup Helpers**: Remove test data from S3 and PostHog between test runs

#### Test Data Management

- **Isolated Test Teams**: Each test uses unique team IDs to prevent interference
- **Cleanup Between Tests**: Automatic cleanup of S3 objects and PostHog test data
- **Fixture Data**: Predefined multipart requests and blob data for consistent testing
- **Random Data Generation**: Configurable blob sizes and content for stress testing

## Phase Gating

- **Mandatory Testing**: All integration tests for a phase must pass before proceeding to implementation of the next phase
- **Regression Prevention**: Previous phase tests continue to run to ensure no regression
- **Incremental Validation**: Each phase builds upon validated functionality from previous phases

## Production Testing

### Overview

For validating the LLM Analytics capture pipeline in production environments, the test suite can be configured to run against live PostHog instances with real AWS S3 storage.

### Configuration Requirements

#### PostHog Credentials

- **Project API Key**: PostHog project private API key for authentication
- **PostHog URL**: PostHog instance URL (cloud or self-hosted)
- **Project ID**: PostHog project identifier for query API access

#### AWS S3 Credentials

- **AWS Access Key ID**: Limited IAM user with read-only S3 access
- **AWS Secret Access Key**: Corresponding secret key
- **S3 Bucket Name**: Production S3 bucket name
- **Region**: AWS region for S3 bucket

### IAM Policy for S3 Read Access

The following IAM policy provides minimal read-only access for a specific team prefix:

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "s3:GetObject",
                "s3:GetObjectMetadata",
                "s3:ListBucket"
            ],
            "Resource": [
                "arn:aws:s3:::your-llma-bucket/llma/TEAM_ID/*",
                "arn:aws:s3:::your-llma-bucket"
            ],
            "Condition": {
                "StringLike": {
                    "s3:prefix": "llma/TEAM_ID/*"
                }
            }
        }
    ]
}
```

### AWS CLI Script for S3 Key Generation

A separate script (`generate-s3-test-keys.sh`) will be implemented to generate limited S3 read-only credentials for LLMA testing. The script will create IAM users with team-specific permissions and output the necessary environment variables for testing.

### Production Test Configuration

#### Environment Variables

```bash
# PostHog Configuration
export POSTHOG_PROJECT_API_KEY="your_posthog_api_key"
export POSTHOG_HOST="https://app.posthog.com"  # or your self-hosted URL
export POSTHOG_PROJECT_ID="12345"

# AWS S3 Configuration
export AWS_ACCESS_KEY_ID="your_limited_access_key"
export AWS_SECRET_ACCESS_KEY="your_limited_secret_key"
export AWS_DEFAULT_REGION="us-east-1"
export LLMA_S3_BUCKET="your-llma-bucket"
export LLMA_TEAM_ID="123"

# Test Configuration
export LLMA_TEST_MODE="production"
```

### Production Test Execution

#### Safety Measures

- **Read-Only Operations**: Production tests only read data, never write or modify
- **Team Isolation**: Tests only access data for the specified team ID
- **Rate Limiting**: Production tests include delays to avoid overwhelming services
- **Data Validation**: Verify S3 objects exist and are accessible without downloading large payloads

#### Usage Example

```bash
# Generate S3 test credentials (script to be implemented)
./generate-s3-test-keys.sh 123 posthog-llm-analytics

# Configure environment
source production-test.env

# Run production validation tests
pytest tests/integration/production/ -v --tb=short
```
