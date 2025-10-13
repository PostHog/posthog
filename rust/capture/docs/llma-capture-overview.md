# LLM Analytics Capture Overview

## Objective

Implement a dedicated capture pathway for LLM Analytics events that enables efficient processing of large-scale language model interactions. This specialized pipeline will:

- Store LLM inputs and outputs directly in S3 for scalable, cost-effective storage
- Route events through the main ingestion pipeline while bypassing the processing of large LLM context payloads
- Ensure the core analytics pipeline remains performant by separating heavy LLM content from standard event processing
- Enable dedicated processing of events containing LLM context through a separate evaluation service, allowing for specialized analysis and computation on LLM interactions

This approach allows us to capture comprehensive LLM usage data without impacting the performance of our primary event ingestion system.

## Supported Events

The LLM Analytics capture endpoint supports four primary AI event types. Events are sent to the `/i/v0/ai` endpoint with multipart payloads to handle large context data efficiently.

### `$ai_generation`

A generation represents a single call to an LLM (e.g., a chat completion request).

**Core Properties:**

- `$ai_trace_id` (required) - UUID to group AI events (e.g., conversation_id)
- `$ai_model` (required) - The model used (e.g., "gpt-4o", "claude-3-opus")
- `$ai_provider` (required) - The LLM provider (e.g., "openai", "anthropic", "gemini")
- `$ai_input` - List of messages sent to the LLM (can be stored as blob)
  - Can contain 300,000+ tokens, making blob storage essential
  - Each message has a `role` ("user", "system", or "assistant") and `content` array
  - Content types: text, image URLs, function calls
- `$ai_output_choices` - List of response choices from the LLM (can be stored as blob)
  - Each choice has a `role` and `content` array
- `$ai_input_tokens` - Number of tokens in the input
- `$ai_output_tokens` - Number of tokens in the output
- `$ai_span_id` (optional) - Unique identifier for this generation
- `$ai_span_name` (optional) - Name given to this generation
- `$ai_parent_id` (optional) - Parent span ID for tree view grouping
- `$ai_latency` (optional) - LLM call latency in seconds
- `$ai_http_status` (optional) - HTTP status code of the response
- `$ai_base_url` (optional) - Base URL of the LLM provider
- `$ai_request_url` (optional) - Full URL of the request
- `$ai_is_error` (optional) - Boolean indicating if the request was an error
- `$ai_error` (optional) - Error message or object

**Cost Properties** (optional, auto-calculated from model and token counts if not provided):

- `$ai_input_cost_usd` - Cost in USD of input tokens
- `$ai_output_cost_usd` - Cost in USD of output tokens
- `$ai_total_cost_usd` - Total cost in USD

**Cache Properties** (optional):

- `$ai_cache_read_input_tokens` - Number of tokens read from cache
- `$ai_cache_creation_input_tokens` - Number of tokens written to cache (Anthropic-specific)

**Model Parameters** (optional):

- `$ai_temperature` - Temperature parameter used
- `$ai_stream` - Whether the response was streamed
- `$ai_max_tokens` - Maximum tokens setting
- `$ai_tools` - Tools/functions available to the LLM

### `$ai_trace`

A trace represents a complete AI interaction flow (e.g., a full conversation or agent execution).

**Key Properties:**

- `$ai_trace_id` (required) - UUID identifying this trace
- `$ai_input_state` - Initial state of the trace (can be stored as blob)
- `$ai_output_state` - Final state of the trace (can be stored as blob)

### `$ai_span`

A span represents a logical unit of work within a trace (e.g., a tool call, a retrieval step).

**Key Properties:**

- `$ai_trace_id` (required) - Parent trace UUID
- `$ai_span_id` (required) - Unique identifier for this span
- `$ai_parent_id` (optional) - Parent span ID for nesting
- `$ai_span_name` - Name describing this span
- `$ai_input_state` - Input state for this span (can be stored as blob)
- `$ai_output_state` - Output state for this span (can be stored as blob)

### `$ai_embedding`

An embedding event captures vector generation for semantic search or RAG systems.

**Key Properties:**

- `$ai_trace_id` (required) - Parent trace UUID
- `$ai_model` (required) - Embedding model used
- `$ai_provider` (required) - Provider (e.g., "openai", "cohere")
- `$ai_input` - Text or data being embedded (can be stored as blob)
- `$ai_input_tokens` - Number of tokens in the input
- Note: Output vectors are typically not captured in events

### Standard Events (No Blob Storage Required)

These events are lightweight and processed through the regular pipeline:

- **`$ai_metric`** - Performance metrics, usage statistics
- **`$ai_feedback`** - User feedback on AI responses

### Blob Storage Strategy

Properties that can contain large payloads (marked as "can be stored as blob" above) should be sent as separate multipart parts with names like `event.properties.$ai_input` or `event.properties.$ai_output_choices`. This keeps the event JSON small while allowing arbitrarily large context data to be stored efficiently in S3.

**Reference:** [PostHog LLM Analytics Manual Capture Documentation](https://posthog.com/docs/llm-analytics/manual-capture)

## General Architecture

The LLM Analytics capture system implements a specialized data flow that efficiently handles large language model payloads:

### Data Flow

1. **Event Ingestion**
   - Events are transmitted using server-side PostHog SDKs via HTTP to a dedicated `/i/v0/ai` endpoint
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

The `/i/v0/ai` endpoint accepts multipart POST requests with the following structure:

#### Request Format

**Headers:**

- `Content-Type: multipart/form-data; boundary=<boundary>`
- Standard PostHog authentication headers

**Multipart Parts:**

1. **Event Part** (required)
   - `Content-Disposition: form-data; name="event"` (required)
   - `Content-Type: application/json` (required)
   - Body: Standard PostHog event JSON payload (without properties, or with properties that will be rejected if `event.properties` part is also present)

2. **Event Properties Part** (optional)
   - `Content-Disposition: form-data; name="event.properties"` (required)
   - `Content-Type: application/json` (required)
   - Body: JSON object containing event properties
   - Cannot be used together with embedded properties in the event part (request will be rejected with 400 Bad Request)
   - Properties from this part are merged into the event as the `properties` field

3. **Blob Parts** (optional, multiple allowed)
   - `Content-Disposition: form-data; name="event.properties.<property_name>"; filename="<blob_id>"` (required)
   - `Content-Type: application/octet-stream | application/json | text/plain` (required)
   - Body: Binary blob data
   - The part name follows the JSON path in the event object (e.g., `event.properties.$ai_input_state`)

**Allowed Part Headers:**

- `Content-Disposition` (required for all parts)
- `Content-Type` (required for all parts)
- No other headers are supported on individual parts (e.g., `Content-Encoding` is not allowed on parts)

**Note:** Individual parts cannot have their own compression. To compress the entire request payload, use the `Content-Encoding: gzip` header at the HTTP request level.

#### Example Request Structure

```http
POST /i/v0/ai HTTP/1.1
Content-Type: multipart/form-data; boundary=----boundary123

------boundary123
Content-Disposition: form-data; name="event"
Content-Type: application/json

{
  "event": "$ai_generation",
  "distinct_id": "user_123",
  "timestamp": "2024-01-15T10:30:00Z"
}

------boundary123
Content-Disposition: form-data; name="event.properties"
Content-Type: application/json

{
  "$ai_model": "gpt-4",
  "completion_tokens": 150
}

------boundary123
Content-Disposition: form-data; name="event.properties.$ai_input"; filename="blob_abc123"
Content-Type: application/json

[JSON LLM input data]

------boundary123
Content-Disposition: form-data; name="event.properties.$ai_output_choices"; filename="blob_def456"
Content-Type: application/json

[JSON LLM output data]

------boundary123
Content-Disposition: form-data; name="event.properties.$ai_embedding_vector"; filename="blob_ghi789"
Content-Type: application/octet-stream

[Binary embedding vector data]
------boundary123--
```

#### Boundary Collision Prevention

To prevent LLM data from accidentally containing the multipart boundary sequence:

1. **Client-side**: SDKs should generate a random boundary string and verify it doesn't appear in any blob data before using it
2. **Server-side**: If a boundary collision is detected during parsing, return a 400 error with instructions to retry with a different boundary
3. **Alternative**: Use Content-Transfer-Encoding: base64 for blob parts, though this increases payload size by ~33%

#### Processing Flow

1. **Parse multipart request**
   - Validate that the first part is the `event` part
   - Extract event JSON from the "event" part

2. **Handle event properties**
   - If `event.properties` part exists: extract properties JSON from it
   - If embedded properties exist in the event part AND `event.properties` part exists: reject with 400 Bad Request
   - Merge properties into the event (from `event.properties` part if present, otherwise use embedded properties)

3. **Validate event structure**
   - Check event name starts with `$ai_`
   - Verify required fields (distinct_id, properties, etc.)
   - Validate required AI properties (e.g., `$ai_model`)

4. **Collect all blob parts**
   - Extract property path from each part name (e.g., `event.properties.$ai_input`)
   - Store blob data with metadata (property path, content type, size)
   - Check for duplicate blob property names

5. **Validate size limits**
   - Event part ≤ 32KB
   - Event + properties combined ≤ 960KB
   - Sum of all parts ≤ 25MB (configurable)

6. **Create multipart file containing all blobs with index**

7. **Upload single multipart file to S3**
   - Generate S3 key using team_id, event_id, and random string
   - Include blob index in S3 object metadata

8. **Replace blob properties with S3 URLs**
   - Add properties to event with S3 URLs including byte ranges

9. **Send modified event to Kafka**

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

#### Supported Content Types for Blob Parts

The following content types are accepted for blob parts:

- `application/octet-stream` - For binary data
- `application/json` - For JSON formatted LLM context
- `text/plain` - For plain text LLM inputs/outputs

The event and event.properties parts must use `application/json`.

#### Content Type Handling

- All parts must include a Content-Type header
- Blob parts with unsupported content types are rejected with 400 Bad Request
- Blob parts missing Content-Type header are rejected with 400 Bad Request
- The Content-Type is stored within the multipart file for each part
- Content-Type is used by the evaluation service to determine how to parse each blob within the multipart file

### Compression

#### Request-Level Compression

The endpoint supports request-level gzip compression to reduce bandwidth usage:

- **Compression algorithm**: gzip
- **How to compress**: Add `Content-Encoding: gzip` header to the HTTP request and compress the entire multipart request body
- **Server behavior**: The capture service will detect the `Content-Encoding: gzip` header and decompress the entire request before processing the multipart data
- **Recommendation**: SDKs should compress large requests (e.g., > 10KB) to minimize network transfer time

**Example Compressed Request:**

```http
POST /i/v0/ai HTTP/1.1
Content-Type: multipart/form-data; boundary=----boundary123
Content-Encoding: gzip

[Gzipped multipart request body]
```

The entire multipart body (including all parts) is compressed as a single gzip stream.

#### Server-side Compression (S3 Storage)

For data received from SDKs (after request decompression, if any):

- The capture service will automatically compress the following content types before storing in S3:
  - `application/json`
  - `text/*` (all text subtypes)
- Binary formats (`application/octet-stream`) will not be automatically compressed
- Compression is applied before storing in S3
- S3 object metadata will indicate if server-side compression was applied
- This compression is transparent to clients and reduces storage costs

## Reliability Concerns

### S3 Upload Reliability

- S3 provides 99.99% uptime SLA, which meets our availability requirements
- Retry logic can be implemented at multiple layers:
  - In the capture service for failed S3 uploads
  - In the SDKs for failed requests to the capture endpoint
- Failed uploads should return appropriate error codes to clients for retry

## Security Concerns

### Preventing Malicious Uploads

- All requests to the `/i/v0/ai` endpoint must be authenticated using the project's private API key
- The capture service validates the API key before processing any multipart data
- This prevents unauthorized uploads and ensures blob storage is only used by legitimate PostHog projects

### Payload Authentication Implementation

The authentication process for LLM analytics events follows these steps:

1. **API Key Extraction**
   - Extract the API key from the request headers (e.g., `Authorization: Bearer <api_key>`)
   - API key must be present for all requests to `/i/v0/ai`

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
   - All events sent to `/i/v0/ai` must have an event name starting with `$ai_`
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
   All size limit violations return 413 Payload Too Large:
   - **Request body**: Maximum 27.5MB (110% of sum of all parts limit, enforced by Axum)
     - Computed as 110% of `AI_MAX_SUM_OF_PARTS_BYTES` to account for multipart overhead
     - This is the first check, applied before any request processing
   - **Event part**: Maximum 32KB (enforced by handler)
   - **Event + properties combined**: Maximum 960KB (1MB - 64KB, enforced by handler)
   - **Sum of all parts** (event, properties, and all blobs): Maximum 25MB (default, configurable via `AI_MAX_SUM_OF_PARTS_BYTES`, enforced by handler)
   - These limits are configurable via environment variables and can be adjusted per deployment

6. **Strict Schema Validation**
   - Each `$ai_` event type has a strictly defined schema
   - Events must conform exactly to their schema - no extra properties allowed
   - Required properties must be present with correct types
   - Blob properties must match expected blob fields for each event type
   - Non-conforming events are rejected with detailed validation errors

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
