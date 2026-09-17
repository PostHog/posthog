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
| MANAGEMENT_BIND_HOST | :: | Host to bind the health check and metrics server |
| MANAGEMENT_BIND_PORT | 8080 | Port for the health check and metrics server |
| MAX_REQUEST_BODY_SIZE_BYTES | 2097152 | Rejects larger request bodies, before and after gzip decompression |
| FIREHOSE_MAX_REQUEST_BODY_SIZE_BYTES | 8388608 | Body cap for the Amazon Data Firehose route only |
| DROP_EVENTS_BY_TOKEN | (none) | Comma-separated tokens to drop |

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

| Status | Meaning | Client behavior |
|--------|---------|-----------------|
| 200 | Accepted | — |
| 400 | Body could not be decoded as OTLP protobuf or JSON | Permanent |
| 401 | No token, or a token that cannot be a project API key (for example a `phx_` personal API key) | Permanent, so the client stops and surfaces the misconfiguration |
| 413 | Body over `MAX_REQUEST_BODY_SIZE_BYTES` | Permanent |

The 401 covers shape only: empty, over 64 characters, non-ASCII, containing a null byte, or
prefixed `phx_`. None of those can be a project API key, so answering 200 and dropping the
records downstream only hides the misconfiguration from whoever is sending the data. This is
the same check, and the same status, that event capture applies to the same input.

One misconfiguration is still answered 200: a well-formed token that belongs to no project.
Resolving a token to a team needs Postgres, which this service does not have, so those records
are still dropped by the ingestion consumer. Event capture does not validate this at the edge
either.

A project over its billing quota is also still answered 200 and dropped by the consumer.

Rejections are counted on `capture_logs_requests_rejected_total{reason, signal}`, where `reason`
is one of `missing_token`, `dropped_token` or `invalid_token`.

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

## Amazon Data Firehose (CloudWatch Logs)

`POST /i/v1/logs/aws/firehose` and `POST /i/v1/logs/aws/firehose/<source_id>` implement the [Firehose HTTP endpoint destination contract](https://docs.aws.amazon.com/firehose/latest/dev/httpdeliveryrequestresponse.html).
A customer creates a Firehose stream with this URL as its HTTP endpoint and the project API key as the stream's access key, then subscribes CloudWatch log groups to the stream.

- Auth: the project API key in `X-Amz-Firehose-Access-Key`, or a Bearer `Authorization` header for manual testing.
  A pasted `Bearer` prefix in the access key field is tolerated.
  The same shape check as every other route applies.
- `<source_id>` is optional.
  When present it must be a UUID; it is forwarded as the `source_id` Kafka header and the `posthog.source_id` attribute so PostHog can attribute delivery health to a configured log source and drop traffic for a disabled one.
  Without it the route behaves like the Datadog intake.
- Each Firehose record is one CloudWatch subscription batch (base64, usually gzip).
  Every `logEvents` entry becomes a log row.
  `CONTROL_MESSAGE` records are acknowledged and skipped.
  A record that is not a CloudWatch envelope (VPC flow logs, WAF) is split on newlines.
  A record that cannot be decoded at all is skipped and counted, so one bad record does not make Firehose retry the good ones.
- Row mapping: `body` = message; `timestamp` = the event timestamp; `service.name` is inferred from the log group (`/aws/lambda/<fn>` → `<fn>`, `/aws/rds/instance/<id>/...` → `<id>`, else the group name) unless a Firehose common attribute `service.name` is set.
  Resource attributes are `cloud.provider=aws`, `cloud.account.id`, `cloud.region` (from `X-Amz-Firehose-Source-Arn`), `aws.log.group.name`, `aws.log.stream.name`, plus any common attributes; the AWS facts win over a common attribute of the same name.
  Severity comes from a JSON `level`/`severity` key or a leading `ERROR`/`WARN`/`INFO`/`DEBUG` token, else `info`.
- Rows are chunked into Kafka messages sized at half the producer's `message.max.bytes`, because a decoded Firehose request can be far larger than one message.
  Batches are produced concurrently.
  Delivery is at-least-once: a Kafka failure returns 500, Firehose redelivers the whole request with the same request id, and the batches already produced are duplicated.
- Size limits: the request body is capped by `FIREHOSE_MAX_REQUEST_BODY_SIZE_BYTES` (default 8 MiB, above the 2 MiB used by the other routes because Firehose buffers whole MiB and base64 adds a third), and the decoded records of one request are capped at eight times that.
  Either limit answers 413, which Firehose treats as permanent, so the failed batch lands in the customer's S3 backup bucket.
- Every response carries the contract body: `{"requestId", "timestamp"}` on 200, plus `"errorMessage"` on 400 (unparseable body, non-UUID source id, no decodable record), 401 (missing or invalid access key), 413 and 500 (Kafka).
  Rejections raised by the body-size and decompression layers are re-shaped into the same body.
- Recommended stream settings: buffer 1 MB / 60 s, GZIP content encoding, retry 300 s, S3 backup for failed data only.

Metrics: `capture_logs_firehose_records_total{kind}` (`data`, `control`, `raw`, `invalid`) and `capture_logs_firehose_events_total`.
Request outcomes are on the shared `http_requests_total{path,status}` and rejected tokens on `capture_logs_requests_rejected_total`.

## Endpoints

### Log Ingestion

- `POST /v1/logs` - Accept OTLP logs (JSON, JSONL, or Protobuf)
- `POST /i/v1/logs` - Alternative endpoint for OTLP logs
- `POST /i/v1/logs/datadog[/<token>]` - Datadog agent intake
- `POST /i/v1/logs/aws/firehose[/<source_id>]` - Amazon Data Firehose HTTP endpoint destination
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
