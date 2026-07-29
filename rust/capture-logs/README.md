# PostHog Log Capture Service

A service that receives OpenTelemetry Protocol (OTLP) logs via HTTP and processes them based on team authentication.

## Features

- Receives OTLP logs via HTTP on `/v1/logs` and `/i/v1/logs` endpoints
- Supports Protobuf and JSON formats
- Supports JSONL (JSON Lines) format for multiple log batches
- Authenticates clients using Bearer tokens or query parameters
- Associates logs with specific team IDs
- Health check endpoints
- Prometheus metrics

## Configuration

The service is configured using environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| BIND_HOST | :: | Host to bind the HTTP server |
| BIND_PORT | 4318 | Port for the HTTP server |
| MAX_REQUEST_BODY_SIZE_BYTES | 2097152 | Rejects larger request bodies, before and after gzip decompression |
| QUOTA_LIMITING_REDIS_URL | (falls back to `REDIS_URL`) | Redis holding the billing quota-limit sorted sets. Unset on both means quota is not enforced here |
| QUOTA_LIMITING_ENABLED | true | Killswitch for the capture-side quota rejection |
| QUOTA_LIMITING_REFRESH_INTERVAL_SECONDS | 30 | How often the quota-limited token snapshot is refreshed from Redis |
| QUOTA_LIMITING_RETRY_AFTER_SECONDS | 900 | Value advertised in `Retry-After` on a 429 |
| REDIS_KEY_PREFIX | (none) | Prefix for the quota-limit Redis keys |

## Authentication

Clients must authenticate by sending a valid token either:

1. In the Authorization header:

```http
Authorization: Bearer your-project-api-key
```

2. As a query parameter:

```http
POST /v1/logs?token=your-project-token
```

The token is your PostHog project token.

## Response codes

The status codes are chosen so that an OTLP client's built-in retry logic does the right thing without any PostHog-specific handling.
Per the [OTLP spec](https://opentelemetry.io/docs/specs/otlp/#failures-1), only 429, 502, 503 and 504 are retryable, and a client honours `Retry-After` on a retryable response.

| Status | Meaning | Client behavior |
|--------|---------|-----------------|
| 200 | Accepted | — |
| 401 | No token, or a token that cannot be a project API key (for example a `phx_` personal API key) | Permanent, so the client stops and surfaces the misconfiguration |
| 400 | Body could not be decoded as OTLP protobuf or JSON | Permanent |
| 413 | Body over `MAX_REQUEST_BODY_SIZE_BYTES` | Permanent |
| 429 | The project is over its billing quota for this signal, sent with `Retry-After` | Retryable, so the client backs off and resends later |

Logs, metrics and traces have separate quotas, so a project over its logs quota keeps ingesting metrics and traces.

`Retry-After` is a bounded poll interval rather than the moment the quota actually resets.
A billing limit runs to the end of the billing period, which can be weeks away, but it is also lifted as soon as a customer raises their limit, so advertising the true expiry would keep a recovered project dark for the rest of the period.

One misconfiguration is still answered 200: a well-formed token that belongs to no project.
Resolving a token to a team needs Postgres, which this service does not have, so those records are still dropped by the ingestion consumer.

## Running the Service

### From Source

```bash
cargo run --bin capture_logs
```

### With Docker

```bash
docker build -t posthog/capture-logs .
docker run -p 8000:8000 posthog/capture-logs
```

## Sending Logs

You can configure any OpenTelemetry-compatible client to send logs to this service. The service accepts:

### Single JSON Format

Standard OTLP ExportLogsServiceRequest as JSON:

```bash
curl -X POST http://localhost:8000/v1/logs \
  -H "Authorization: Bearer your-api-key" \
  -H "Content-Type: application/json" \
  -d '{"resourceLogs":[{"resource":{"attributes":[]},"scopeLogs":[{"logRecords":[{"body":{"stringValue":"Hello World"}}]}]}]}'
```

### JSONL Format (JSON Lines)

Multiple ExportLogsServiceRequest objects, one per line:

```bash
curl -X POST http://localhost:8000/v1/logs \
  -H "Authorization: Bearer your-api-key" \
  -H "Content-Type: application/json" \
  -d $'{"resourceLogs":[{"resource":{},"scopeLogs":[{"logRecords":[{"body":{"stringValue":"Log 1"}}]}]}]}\n{"resourceLogs":[{"resource":{},"scopeLogs":[{"logRecords":[{"body":{"stringValue":"Log 2"}}]}]}]}'
```

### Protobuf Format

Standard OTLP protobuf encoding is also supported.

Requirements:

1. Set the HTTP endpoint to `http://your-service-host:8000/v1/logs`
2. Include your PostHog project token in the Authorization header or as a query parameter
3. Use standard OTLP log format (JSON, JSONL, or Protobuf)

## Endpoints

### Log Ingestion

- `POST /v1/logs` - Accept OTLP logs (JSON, JSONL, or Protobuf)
- `POST /i/v1/logs` - Alternative endpoint for OTLP logs
- `OPTIONS /v1/logs` - CORS preflight support
- `OPTIONS /i/v1/logs` - CORS preflight support

### Management

- `/` - Basic information page
- `/_readiness` - Readiness probe for Kubernetes
- `/_liveness` - Liveness probe for Kubernetes
- `/metrics` - Prometheus metrics

## Development

### Running Tests

```bash
cargo test
```

### Building in Release Mode

```bash
cargo build --release
```
