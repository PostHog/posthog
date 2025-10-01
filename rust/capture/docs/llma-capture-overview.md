# LLM Analytics Capture Overview

## Objective

Implement a dedicated capture pathway for LLM Analytics events that enables efficient processing of large-scale language model interactions. This specialized pipeline will:

- Store LLM inputs and outputs directly in S3 for scalable, cost-effective storage
- Route events through the main ingestion pipeline while bypassing the processing of large LLM context payloads
- Ensure the core analytics pipeline remains performant by separating heavy LLM content from standard event processing
- Enable dedicated processing of events containing LLM context through a separate evaluation service, allowing for specialized analysis and computation on LLM interactions

This approach allows us to capture comprehensive LLM usage data without impacting the performance of our primary event ingestion system.

## Supported Events

### Events with Large Context Payloads

These events contain substantial LLM context that requires blob storage:

- **`$ai_trace`**
  - `$ai_input_state`
  - `$ai_output_state`

- **`$ai_span`**
  - `$ai_input_state`
  - `$ai_output_state`

- **`$ai_generation`**
  - `$ai_input` - Can contain 300,000+ LLM tokens, making blob storage essential
  - `$ai_output_choices`

- **`$ai_embedding`**
  - `$ai_input`
  - Note: Output data is not currently included in the event payload, though this may be added in future iterations

### Standard Events

These events can be processed through the regular pipeline without blob storage:

- **`$ai_metric`** - Lightweight metric data that doesn't require offloading
- **`$ai_feedback`** - User feedback events that remain small enough for standard processing

### Future Considerations

The event schema is designed to accommodate future multimodal content types, including:

- Images
- Audio
- Video
- Files

These additions will leverage the same blob storage infrastructure when implemented.

## General Architecture

The LLM Analytics capture system implements a specialized data flow that efficiently handles large language model payloads:

### Data Flow

1. **Event Ingestion**
   - Events are transmitted using server-side PostHog SDKs via HTTP to a dedicated `/ai` endpoint
   - Requests utilize multipart payloads containing:
     - Event payload (metadata and standard properties)
     - Binary blobs containing LLM context (e.g., input state, output state property values)

2. **Blob Processing**
   - The capture service extracts blob data from multipart requests
   - Blobs are uploaded directly to S3 for persistent storage
   - Upon successful upload, the corresponding AI state properties in the event are replaced with S3 URLs
   - This transformation replaces inline LLM data with S3 references

3. **Event Routing**
   - Modified events (now containing S3 references instead of raw LLM data) are published to the standard Kafka topic
   - Events flow through the regular ingestion pipeline without the overhead of processing large LLM payloads

4. **Evaluation Pipeline**
   - A dedicated evaluation service consumes events from the ingestion pipeline's output topic
   - For events requiring LLM context analysis:
     - The service fetches the corresponding blobs from S3 using the stored URLs
     - Performs specialized evaluation and analysis on the LLM interactions
     - Generates new evaluation events with insights and metrics
   - These evaluation events are fed back into the system for further analytics

## Design

### HTTP Endpoint

The `/ai` endpoint accepts multipart POST requests with the following structure:

#### Request Format

**Headers:**

- `Content-Type: multipart/form-data; boundary=<boundary>`
- Standard PostHog authentication headers

**Multipart Parts:**

1. **Event Part** (required)
   - `Content-Disposition: form-data; name="event"`
   - `Content-Type: application/json`
   - Body: Standard PostHog event JSON payload

2. **Blob Parts** (optional, multiple allowed)
   - `Content-Disposition: form-data; name="event.properties.<property_name>"; filename="<blob_id>"`
   - `Content-Type: application/octet-stream` (or `application/json`, `text/plain`, etc.)
   - `Content-Encoding: gzip` (optional, for compressed data)
   - `Content-Length: <size>` (size of the blob part in bytes)
   - Body: Binary blob data (optionally gzip compressed)
   - The part name follows the JSON path in the event object (e.g., `event.properties.$ai_input_state`)

#### Example Request Structure

```http
POST /ai HTTP/1.1
Content-Type: multipart/form-data; boundary=----boundary123

------boundary123
Content-Disposition: form-data; name="event"
Content-Type: application/json

{
  "event": "$ai_generation",
  "properties": {
    "model": "gpt-4",
    "completion_tokens": 150
  },
  "timestamp": "2024-01-15T10:30:00Z"
}

------boundary123
Content-Disposition: form-data; name="event.properties.$ai_input"; filename="blob_abc123"
Content-Type: application/json
Content-Encoding: gzip
Content-Length: 2048

[Gzipped JSON LLM input data]

------boundary123
Content-Disposition: form-data; name="event.properties.$ai_output_choices"; filename="blob_def456"
Content-Type: application/json
Content-Length: 5120

[Uncompressed JSON LLM output data]

------boundary123
Content-Disposition: form-data; name="event.properties.$ai_embedding_vector"; filename="blob_ghi789"
Content-Type: application/octet-stream
Content-Length: 16384

[Binary embedding vector data]
------boundary123--
```

#### Boundary Collision Prevention

To prevent LLM data from accidentally containing the multipart boundary sequence:

1. **Client-side**: SDKs should generate a random boundary string and verify it doesn't appear in any blob data before using it
2. **Server-side**: If a boundary collision is detected during parsing, return a 400 error with instructions to retry with a different boundary
3. **Alternative**: Use Content-Transfer-Encoding: base64 for blob parts, though this increases payload size by ~33%

#### Processing Flow

1. Parse multipart request
2. Extract event JSON from the "event" part
3. Collect all blob parts:
   - Extract property path from each part name
   - Verify the property doesn't already exist in the event JSON
   - Store blob data with metadata (property path, content type, size)
4. Create multipart file containing all blobs with index
5. Upload single multipart file to S3:
   - Generate S3 key using team_id, event_id, and random string
   - Include blob index in S3 object metadata
6. Add properties to event with S3 URLs including byte ranges
7. Send modified event to Kafka

### S3 Storage

All blobs for an event are stored as a single multipart file in S3:

#### Format

**Multipart/mixed format** - Similar to email MIME, with boundaries separating each blob part

#### Bucket Structure

```text
s3://<bucket>/
  llma/
    <team_id>/
      <YYYY-MM-DD>/
        <event_id>_<random_string>.multipart
```

With retention prefixes:

```text
s3://<bucket>/
  llma/
    <retention>/
      <team_id>/
        <YYYY-MM-DD>/
          <event_id>_<random_string>.multipart
```

#### Storage Details

- **Bucket**: Dedicated bucket or shared bucket with `llma/` prefix
- **Partitioning**: By team_id and date for efficient access patterns and lifecycle policies
- **Object naming**: Combination of event_id and random string
- **File format**: Contains all blobs for a single event in multipart format
- **Metadata**: S3 object metadata includes:
  - `team_id`
  - `event_id`
  - `upload_timestamp`
  - `content_type` (multipart/mixed or similar)
  - Index of blob positions within the file

#### Event Property Format

Properties contain S3 URLs with byte range parameters:

```json
{
  "event": "$ai_generation",
  "properties": {
    "$ai_input": "s3://bucket/llma/123/2024-01-15/event_456_x7y9z.multipart?range=0-50000",
    "$ai_output_choices": "s3://bucket/llma/123/2024-01-15/event_456_x7y9z.multipart?range=50001-75000",
    "model": "gpt-4",
    "completion_tokens": 150
  }
}
```

#### Access Patterns

- **Individual blob access**: Use S3 range requests to fetch specific blobs
- **Full event access**: Download entire multipart file when multiple blobs are needed
- The evaluation service can optimize by detecting when multiple properties reference the same file

#### Example S3 paths

Without retention prefix (default 30 days):

```text
s3://posthog-llm-analytics/llma/123/2024-01-15/event_456_x7y9z.multipart
s3://posthog-llm-analytics/llma/456/2024-01-15/event_789_a3b5c.multipart
```

With retention prefixes:

```text
s3://posthog-llm-analytics/llma/30d/123/2024-01-15/event_012_m2n4p.multipart
s3://posthog-llm-analytics/llma/90d/456/2024-01-15/event_345_q6r8s.multipart
s3://posthog-llm-analytics/llma/1y/789/2024-01-15/event_678_t1u3v.multipart
```

#### Access Control

- Write access: Only capture service
- Read access: Capture service, evaluation service, and authorized backend services

#### Lifecycle Policies

- Default retention: 30 days
- Optional retention prefixes for different durations (e.g., `30d/`, `90d/`, `1y/`)
- Since S3 paths are stored in events, retention can be determined at upload time without later computation

### Content Types

#### Supported Content Types

The following content types are accepted for blob parts:

- `application/octet-stream` - Default for binary data
- `application/json` - JSON formatted LLM context
- `text/plain` - Plain text LLM inputs/outputs

#### Content Type Handling

- Blob parts must include a Content-Type header
- The Content-Type is stored within the multipart file for each part
- Content-Type is used by the evaluation service to determine how to parse each blob within the multipart file

### Compression

#### Client-side Compression

SDKs should compress blob payloads before transmission to reduce bandwidth usage:

- Compression algorithm: gzip
- Compressed parts should include `Content-Encoding: gzip` header
- Original Content-Type should be preserved (e.g., `Content-Type: application/json` with `Content-Encoding: gzip`)

#### Server-side Compression

For uncompressed data received from SDKs:

- The capture service will automatically compress the following content types:
  - `application/json`
  - `text/*` (all text subtypes)
- Binary formats (`application/octet-stream`) will not be automatically compressed
- Compression is applied before storing in S3
- S3 object metadata will indicate if server-side compression was applied

#### Example Headers

Compressed blob part from SDK:

```http
Content-Disposition: form-data; name="event.properties.$ai_input"; filename="blob_abc123"
Content-Type: application/json
Content-Encoding: gzip

[Gzipped JSON data]
```

## Reliability Concerns

### S3 Upload Reliability

- S3 provides 99.99% uptime SLA, which meets our availability requirements
- Retry logic can be implemented at multiple layers:
  - In the capture service for failed S3 uploads
  - In the SDKs for failed requests to the capture endpoint
- Failed uploads should return appropriate error codes to clients for retry

## Security Concerns

### Preventing Malicious Uploads

- All requests to the `/ai` endpoint must be authenticated using the project's private API key
- The capture service validates the API key before processing any multipart data
- This prevents unauthorized uploads and ensures blob storage is only used by legitimate PostHog projects

### Payload Authentication Implementation

The authentication process for LLM analytics events follows these steps:

1. **API Key Extraction**
   - Extract the API key from the request headers (e.g., `Authorization: Bearer <api_key>`)
   - API key must be present for all requests to `/ai`

2. **Early Validation**
   - Validate the API key format and existence before parsing multipart data
   - Reject requests with missing or malformed keys immediately (400 Bad Request)

3. **Team Resolution**
   - Look up the team associated with the API key
   - Cache team lookups to minimize database queries
   - Return 401 Unauthorized for invalid keys

4. **Request Processing**
   - Only after successful authentication, begin parsing the multipart payload
   - This prevents processing and storing data from unauthenticated requests
   - Team ID from authentication is used for S3 path generation

5. **Error Handling**
   - Authentication failures should not reveal whether a key exists
   - Use consistent error messages to prevent key enumeration attacks

### Tenant Isolation

- S3 paths include team IDs as part of the directory structure
- Every service accessing S3 must validate that the requesting team has access to the path
- Services must never allow cross-team access to S3 blobs
- Path traversal attempts must be detected and blocked
- Optional: Per-team encryption keys can provide additional isolation by making data cryptographically inaccessible without the correct team's key

### Data Deletion

Three approaches for handling data deletion requests:

1. **S3 Expiry (Passive)**
   - Rely on S3 lifecycle policies to automatically delete expired blobs
   - No immediate action required for deletion requests
   - Simple implementation but data remains accessible until expiry
   - Suitable for compliance requirements with defined retention periods

2. **S3 Delete by Prefix**
   - Use S3's delete by prefix functionality to remove all objects for a team
   - Simple to implement but requires listing and deleting potentially many objects
   - Example: Delete all data for team 123:

     ```bash
     aws s3 rm s3://posthog-llm-analytics/llma/123/ --recursive
     ```

     Or using S3 API to delete objects with prefix `llma/123/`

3. **Per-Team Encryption**
   - Encrypt blobs with per-team encryption keys
   - Data deletion achieved by deleting the team's encryption key
   - More complex but provides immediate cryptographic deletion
   - Reduces S3 API calls for large-scale deletions
   - Security benefit: accessing data requires fetching the team's encryption key every time
   - Easier to audit and verify that services only access data for the correct team, as key fetching code is centralized

### Payload Schema Verification

The capture service enforces strict validation on incoming events:

1. **Event Name Validation**
   - All events sent to `/ai` must have an event name starting with `$ai_`
   - Requests with non-AI events are rejected with 400 Bad Request
   - This ensures the endpoint is only used for its intended purpose

2. **Required Fields**
   - Event must contain standard PostHog event fields (event, properties, timestamp)
   - Properties object must be present, even if empty

3. **Blob Property Validation**
   - Blob part names indicate which properties they populate
   - Blobs cannot overwrite existing properties in the event JSON
   - If a blob targets a property that already exists in the event, the request is rejected

4. **Property Path Validation**
   - Blob part names must match valid property paths in the event JSON
   - Nested property paths are supported (e.g., `event.properties.nested.$ai_input`)

5. **Size Limits**
   - Maximum total payload size enforced for security (e.g., 100MB default)
   - Limits can be configured per team to accommodate different use cases
   - Event JSON payload has a separate maximum size limit
   - Individual blob parts have maximum size limits

6. **Strict Schema Validation**
   - Each `$ai_` event type has a strictly defined schema
   - Events must conform exactly to their schema - no extra properties allowed
   - Required properties must be present with correct types
   - Blob properties must match expected blob fields for each event type
   - Non-conforming events are rejected with detailed validation errors

## Open Questions

- Should the capture service validate Content-Types of blob parts against a whitelist, or accept any Content-Type provided by the client?

## Rejected Solutions

### WarpStream-based Processing

**Architecture:**

- Push entire request payloads (including large LLM content) to WarpStream, which supports large messages
- A separate service consumes from WarpStream and uploads blobs to S3
- Events are then forwarded to the regular ingestion pipeline

**Downsides:**

- WarpStream is less reliable than S3, reducing overall system availability
- Additional transfer costs for moving data through WarpStream
- Additional processing costs for the intermediate service
- No meaningful batching opportunity - the service would upload files to S3 individually, same as direct upload from capture
- Adds complexity and another point of failure without significant benefits
