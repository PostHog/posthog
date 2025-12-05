# LLM Analytics Capture Implementation Plan

## Overview

This document outlines the implementation steps for the LLM Analytics capture pipeline based on the design specified in `llma-capture-overview.md`.

## Implementation Phases

### Phase 0: Local Development Setup

#### 0.1 Routing Configuration

- [x] Create new `/i/v0/ai` endpoint in capture service
- [ ] Set up routing for `/i/v0/ai` endpoint to capture service

#### 0.2 End-to-End Integration Tests

- [x] Implement Rust integration tests for multipart parsing and validation
- [x] Create Python acceptance test scenarios with multipart requests and blob data
- [x] Test Kafka message output and S3 storage integration
- [ ] Set up automated test suite for continuous validation

### Phase 1: HTTP Endpoint

#### 1.1 HTTP Endpoint Foundation

- [x] Implement multipart/form-data request parsing
- [x] Add server-side boundary validation
- [x] Support separate `event.properties` multipart part
- [x] Implement gzip decompression for compressed requests
- [x] Output events with blob placeholders to Kafka
- [x] Implement error schema

#### 1.2 Basic Validation

- [x] Implement specific AI event type validation ($ai_generation, $ai_trace, $ai_span, $ai_embedding, $ai_metric, $ai_feedback)
- [x] Validate blob part names against event properties
- [x] Prevent blob overwriting of existing properties (reject if both embedded and separate properties)
- [x] Validate event part is first in multipart request
- [x] Validate required fields (event name, distinct_id, $ai_model)
- [x] Implement size limits (32KB event, 960KB combined, 25MB total, 27.5MB request body)

#### 1.3 Initial Deployment

- [ ] Deploy capture-ai service to production with basic `/i/v0/ai` endpoint
- [ ] Test basic multipart parsing and Kafka output functionality
- [ ] Verify endpoint responds correctly to AI events

### Phase 2: Basic S3 Uploads

#### 2.1 Simple S3 Upload (per blob)

- [ ] Upload individual blobs to S3 as separate objects
- [ ] Generate S3 URLs for blobs (including byte range parameters)
- [ ] Store S3 blob metadata
- [ ] Track S3 upload success/failure rates
- [ ] Monitor blob size distributions

### Phase 3: S3 Infrastructure & Deployment

#### 3.1 S3 Bucket Configuration

- [ ] Set up S3 buckets for dev and production environments
- [ ] Set up bucket structure with `llma/` prefix
- [ ] Configure S3 lifecycle policies for retention (30d default)
- [ ] Set up S3 access policies for capture service
- [ ] Create service accounts with appropriate S3 permissions

#### 3.2 Capture S3 Configuration

- [ ] Deploy capture-ai service to dev environment with S3 configuration
- [ ] Deploy capture-ai service to production environment with S3 configuration
- [ ] Set up IAM roles and permissions for capture-ai service
- [ ] Configure S3 read/write permissions
- [ ] Test S3 connectivity and uploads

### Phase 4: Multipart File Processing

#### 4.1 Multipart File Creation

- [ ] Implement multipart/mixed format
- [ ] Store metadata within multipart format
- [ ] Generate S3 URLs for blobs (including byte range parameters)

### Phase 5: Authorization

#### 5.1 Request Signature Verification

- [x] Implement basic API key validation (Bearer token authentication)
- [ ] Implement PostHog API key authentication
- [ ] Add request signature verification
- [ ] Validate API key before processing multipart data
- [ ] Add proper error responses for authentication failures
- [ ] Test authentication with valid and invalid keys

### Phase 6: Operations

#### 6.1 Monitoring Setup

- [ ] Set up monitoring dashboards for capture-ai

#### 6.2 Alerting

- [ ] Configure alerts for S3 upload failures
- [ ] Set up alerts for high error rates on `/i/v0/ai` endpoint
- [ ] Set up alerts for high latency on `/i/v0/ai` endpoint

#### 6.3 Runbooks

- [ ] Create runbook for capture-ai S3 connectivity issues

### Phase 7: Compression

#### 7.1 Compression Support

- [x] Parse Content-Encoding: gzip header for request-level compression
- [x] Implement streaming gzip decompression for compressed requests
- [x] Test with gzip-compressed multipart requests
- [ ] Implement server-side compression for uncompressed blobs before S3 storage
- [ ] Add compression metadata to S3 objects
- [ ] Track compression ratio effectiveness

### Phase 8: Schema Validation

#### 8.1 Schema Validation

- [x] Validate Content-Type headers on blob parts (required: application/json, text/plain, application/octet-stream)
- [x] Validate event JSON structure (event, distinct_id, properties fields)
- [x] Validate required AI properties ($ai_model)
- [x] Test with different supported content types
- [ ] Create comprehensive schema definitions for each AI event type
- [ ] Add detailed schema validation for event-specific properties
- [ ] Add Content-Length validation beyond size limits

### Phase 9: Limits (Optional)

#### 9.1 Request Validation & Limits

- [x] Add request size limits and validation (configurable via `ai_max_sum_of_parts_bytes`)
- [x] Implement event part size limit (32KB)
- [x] Implement combined event+properties size limit (960KB)
- [x] Implement total parts size limit (25MB default, configurable)
- [x] Implement request body size limit (110% of total parts limit)
- [x] Return 413 Payload Too Large for size violations
- [ ] Add request rate limiting per team
- [ ] Implement per-team payload size limits

### Phase 10: Data Deletion (Optional)

#### 10.1 Data Deletion (Choose One Approach)

- [ ] Option A: S3 expiry (passive) - rely on lifecycle policies
- [ ] Option B: S3 delete by prefix functionality
- [ ] Option C: Per-team encryption keys
