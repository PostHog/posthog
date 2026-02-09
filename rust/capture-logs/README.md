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
| HOST | 0.0.0.0 | Host to bind the HTTP server |
| PORT | 8000 | Port for the HTTP server |
| JWT_SECRET | posthog_default_jwt_secret | Secret key for JWT validation |

## Authentication

Clients must authenticate by sending a valid token either:

1. In the Authorization header:

```http
Authorization: Bearer your-project-api-key
```

2. As a query parameter:

```http
POST /v1/logs?token=your-project-api-key
```

The token is your PostHog project API key.

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
2. Include your PostHog project API key in the Authorization header or as a query parameter
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
