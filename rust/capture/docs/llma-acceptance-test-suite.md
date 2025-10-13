# LLMA Acceptance Test Suite

## Overview

This document describes the Python acceptance test suite for the LLM Analytics pipeline. These tests validate **end-to-end functionality** that requires real PostHog infrastructure: database, S3 storage, Kafka, authentication services, and the full ingestion pipeline.

**Implementation Requirement**: Each phase in the implementation plan must pass its corresponding acceptance tests before proceeding to the next phase. This ensures incremental validation and prevents regression as new features are added.

## Test Architecture

### Test Environment

- **Local PostHog Deployment**: Complete local PostHog setup including capture service with `/i/v0/ai` endpoint
- **S3-Compatible Storage**: Local S3-compatible storage for blob storage with direct access for verification
- **PostHog Query API**: Used to fetch processed events from the ingestion pipeline for validation
- **Direct S3 Access**: Test suite has direct S3 client access to verify blob storage and retrieval
- **Database**: PostgreSQL for team/token storage and event metadata
- **Kafka**: Event streaming for ingestion pipeline
- **ClickHouse**: Event storage and query API

### Test Framework

- **Acceptance Tests**: Full pipeline tests from HTTP request through ingestion to event storage
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

**Phase Completion Requirement**: All acceptance tests for a phase must pass before implementation can proceed to the next phase. This gate ensures quality and prevents compound issues from multiple incomplete features.

### Phase 1: HTTP Endpoint

#### Scenario 1.1: Event Processing Verification

- **Test**: Send multipart request and verify event reaches PostHog query API
- **Validation**: Use PostHog query API to fetch processed event, verify blob placeholders correctly inserted
- **Tests Implemented**:
  - `test_basic_ai_generation_event`: Full end-to-end event processing
  - `test_all_accepted_ai_event_types`: Verify all six supported AI event types are accepted and stored

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
- **Tests Implemented**:
  - `test_ai_endpoint_invalid_auth_returns_401`: Invalid token validation

### Phase 7: Compression

#### Scenario 7.1: Mixed Compression

- **Test**: Single request with both compressed and uncompressed blobs
- **Validation**: Each blob handled according to its compression state

### Phase 9: Limits (Optional) - DO NOT IMPLEMENT, TBD

### Phase 10: Data Deletion (Optional) - DO NOT IMPLEMENT, TBD

### Cross-Team Isolation Testing

## Error Recovery and Edge Cases

### Edge Case Scenarios

#### Scenario E.1: S3 Service Interruption

- **Test**: Simulate S3 unavailability during uploads
- **Validation**: Proper error responses, retry logic works, no data loss

#### Scenario E.2: Kafka Unavailability

- **Test**: Simulate Kafka unavailability during event publishing
- **Validation**: Appropriate error handling, request failure communicated to client

## Local Development Testing

### Test Implementation

The acceptance test suite is implemented in Python using pytest to test against full PostHog infrastructure.

#### Test Structure

- **Location**: `common/ingestion/acceptance_tests/test_llm_analytics.py`
- **Framework**: pytest with async support
- **Dependencies**:
  - `requests` for HTTP client operations
  - `boto3` for S3 client operations (when needed)
  - PostHog SDK or API for event querying
  - Django test utilities for setup

### Local Test Environment Setup

#### Prerequisites

- **Local PostHog Instance**: Full PostHog deployment running locally
- **Local S3 Storage**: S3-compatible storage (configured via PostHog local setup)
- **Capture Service**: Running with `/i/v0/ai` endpoint enabled
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
# Run all LLMA acceptance tests
pytest common/ingestion/acceptance_tests/test_llm_analytics.py -v

# Run specific test
pytest common/ingestion/acceptance_tests/test_llm_analytics.py::test_basic_ai_generation_event -v

# Run with detailed output
pytest common/ingestion/acceptance_tests/test_llm_analytics.py -v -s
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

- **Mandatory Testing**: All acceptance tests for a phase must pass before proceeding to implementation of the next phase
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
