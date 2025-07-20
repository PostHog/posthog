# PostHog Log Capture Service

A service that receives logs via multiple protocols and formats, processing them based on team authentication.

## Features

- **OTLP Support**: Receives OpenTelemetry Protocol logs via gRPC and HTTP
- **Custom JSON**: Accepts simplified JSON log arrays for easy integration
- **Multi-format ingestion**: Protobuf OTLP and JSON on HTTP endpoints
- **JWT Authentication**: Secure team-based log isolation
- **ClickHouse Storage**: High-performance log storage and querying
- **Health & Metrics**: Monitoring endpoints and Prometheus metrics

## Configuration

The service is configured using environment variables:

### Server Configuration
| Variable | Default | Description |
|----------|---------|-------------|
| GRPC_BIND_HOST | :: | Host to bind the gRPC server |
| GRPC_BIND_PORT | 4317 | Port for the gRPC server |
| HTTP_BIND_HOST | :: | Host to bind the HTTP server |
| HTTP_BIND_PORT | 4318 | Port for the HTTP server |
| MGMT_BIND_HOST | :: | Host to bind the management server |
| MGMT_BIND_PORT | 8000 | Port for the management server |

### Authentication
| Variable | Default | Description |
|----------|---------|-------------|
| JWT_SECRET | (required) | Secret key for JWT validation |

### ClickHouse Configuration
| Variable | Default | Description |
|----------|---------|-------------|
| CLICKHOUSE_URL | (required) | ClickHouse server URL |
| CLICKHOUSE_DATABASE | default | ClickHouse database name |
| CLICKHOUSE_USER | default | ClickHouse username |
| CLICKHOUSE_PASSWORD | (empty) | ClickHouse password |
| CLICKHOUSE_TABLE | logs | ClickHouse table name |

### Batch Insert Configuration
| Variable | Default | Description |
|----------|---------|-------------|
| INSETER_PERIOD_MS | 1000 | Insert period in milliseconds |
| INSETER_MAX_BYTES | 50000000 | Maximum bytes per batch |
| INSETER_MAX_ROWS | 10000 | Maximum rows per batch |

## Authentication

Clients must authenticate by sending a valid JWT token in the Authorization header:

```
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0ZWFtX2lkIjoiMTIzNDU2Nzg5MCJ9.czOuiHUzSl8s9aJiPghhkGZP-WxI7K-I85XNY-bXRSQ
```

The JWT token must contain a `team_id` claim which is used to associate logs with a specific team.

**Example JWT Payload:**
```json
{
  "team_id": "your-team-id",
  "exp": 1735689600
}
```

## Sending Logs

### Option 1: Custom JSON (Recommended for new integrations)
Simple JSON array format for easy integration:

```bash
curl -X POST http://localhost:4318/v1/logs/json \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-jwt-token" \
  -d '[{
    "message": "User login successful",
    "timestamp": 1753016665117454000,
    "severity_text": "INFO",
    "trace_id": "b2ffad5e51d238eabf0b562869f29d25",
    "span_id": "0513a32db4496fa7",
    "attributes": {
      "user.id": "12345",
      "method": "POST",
      "endpoint": "/login"
    },
    "resources": {
      "service.name": "auth-service",
      "host.name": "web-01"
    }
  }]'
```

### Option 2: OTLP Protobuf (Standard OpenTelemetry)

**gRPC**: Configure OpenTelemetry client for `http://your-host:4317`  
**HTTP**: Send protobuf to `http://your-host:4318/v1/logs` with `Content-Type: application/x-protobuf`

Both require `Authorization: Bearer <jwt-token>` header.

## JSON Log Format

The `/v1/logs/json` endpoint accepts arrays of log objects with this structure:

```json
{
  "message": "Log message text",
  "timestamp": 1753016665117454000,
  "severity_text": "INFO",
  "severity_number": 9,
  "trace_id": "hex-encoded-trace-id",
  "span_id": "hex-encoded-span-id", 
  "trace_flags": 0,
  "attributes": {
    "key": "value"
  },
  "resources": {
    "service.name": "my-service",
    "host.name": "server-01"
  }
}
```

**Required**: `message`, `timestamp`  
**Optional**: All other fields

## Running the Service

### From Source

```bash
export RUST_LOG="debug" && export JWT_SECRET="xxx" && export CLICKHOUSE_URL="http://xxx:yyyy" && cargo run --bin log-capture
```

### With Docker

```bash
docker build -t posthog/log-capture .
docker run -p 4317:4317 -p 4318:4318 -p 8000:8000 \
  -e JWT_SECRET=your_secret_key \
  -e CLICKHOUSE_URL=http://clickhouse:8123 \
  posthog/log-capture
```

### Environment Variables Example

```bash
# Server configuration
export GRPC_BIND_HOST="::"
export GRPC_BIND_PORT=4317
export HTTP_BIND_HOST="::"
export HTTP_BIND_PORT=4318
export MGMT_BIND_HOST="::"
export MGMT_BIND_PORT=8000

# Authentication
export JWT_SECRET=your_secret_key

# ClickHouse
export CLICKHOUSE_URL=http://localhost:8123
export CLICKHOUSE_DATABASE=logs_db
export CLICKHOUSE_USER=default
export CLICKHOUSE_PASSWORD=password
export CLICKHOUSE_TABLE=logs

# Batch settings
export INSETER_PERIOD_MS=500
export INSETER_MAX_ROWS=5000
```

## Endpoints

### HTTP Server (Port 4318)
- `/v1/logs/json` - **Custom JSON logs** (array of log objects)
- `/v1/logs` - OTLP protobuf logs
- `/v1/traces` - OTLP traces

### gRPC Server (Port 4317)
- OTLP services for logs and traces

### Management Server (Port 8000)
- `/` - Service information
- `/_readiness` / `/_liveness` - Health probes
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