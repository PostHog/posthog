# LLM Analytics Capture Implementation Plan

## Overview

This document outlines the implementation steps for the LLM Analytics capture pipeline based on the design specified in `llma-capture-overview.md`.

## Implementation Phases

### Phase 0: Local Development Setup

#### 0.1 Routing Configuration

- [ ] Create new `/ai` endpoint in capture service
- [ ] Set up routing for `/ai` endpoint to capture service

#### 0.2 End-to-End Integration Tests

- [ ] Implement end-to-end integration tests for the full LLM analytics pipeline
- [ ] Create test scenarios with multipart requests and blob data
- [ ] Test Kafka message output and S3 storage integration
- [ ] Set up automated test suite for continuous validation

### Phase 1: HTTP Endpoint

#### 1.1 HTTP Endpoint Foundation

- [ ] Implement multipart/form-data request parsing
- [ ] Add server-side boundary validation
- [ ] Output events with blob placeholders to Kafka
- [ ] Implement error schema

#### 1.2 Basic Validation

- [ ] Implement `$ai_` event name prefix validation
- [ ] Validate blob part names against event properties
- [ ] Prevent blob overwriting of existing properties

#### 1.3 Initial Deployment

- [ ] Deploy capture-ai service to production with basic `/ai` endpoint
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
- [ ] Set up alerts for high error rates on `/ai` endpoint
- [ ] Set up alerts for high latency on `/ai` endpoint

#### 6.3 Runbooks

- [ ] Create runbook for capture-ai S3 connectivity issues

### Phase 7: Compression

#### 7.1 Compression Support

- [ ] Parse Content-Encoding headers from SDK requests
- [ ] Implement server-side compression for uncompressed text/JSON
- [ ] Add compression metadata to multipart files
- [ ] Handle mixed compressed/uncompressed blobs
- [ ] Track compression ratio effectiveness

### Phase 8: Schema Validation

#### 8.1 Schema Validation

- [ ] Create strict schema definitions for each AI event type
- [ ] Add schema validation for event payloads
- [ ] Validate Content-Type headers on blob parts
- [ ] Add Content-Length validation

### Phase 9: Limits (Optional)

#### 9.1 Request Validation & Limits

- [ ] Add request size limits and validation
- [ ] Add request rate limiting per team
- [ ] Implement payload size limits per team

### Phase 10: Data Deletion (Optional)

#### 10.1 Data Deletion (Choose One Approach)

- [ ] Option A: S3 expiry (passive) - rely on lifecycle policies
- [ ] Option B: S3 delete by prefix functionality
- [ ] Option C: Per-team encryption keys
