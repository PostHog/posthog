# PostHog Log Capture Service

A service that receives OpenTelemetry Protocol (OTLP) logs via both gRPC and HTTP and processes them based on team authentication.

## Features

- Receives OTLP logs via gRPC on port 4317 (default)
- Receives OTLP logs via HTTP on port 4318 (default)
- Receives OTLP traces via gRPC on port 4317 (default)
- Receives OTLP traces via HTTP on port 4318 (default)
- Authenticates clients using JWT tokens
- Associates logs with specific team IDs
- Stores logs in ClickHouse
- Health check endpoints on port 8000 (default)
- Prometheus metrics
- CORS support for HTTP endpoints

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

### Example JWT Payload

```json
{
  "team_id": "your-team-id",
  "exp": 1735689600  // Optional expiration time
}
```

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

## Sending Logs

### gRPC (Traditional OTLP)
Configure your OpenTelemetry client to send to:
- **Endpoint**: `http://your-service-host:4317`
- **Protocol**: gRPC
- **Headers**: `Authorization: Bearer <jwt-token>`

### HTTP (OTLP over HTTP)
Configure your OpenTelemetry client to send to:
- **Logs Endpoint**: `http://your-service-host:4318/v1/logs`
- **Traces Endpoint**: `http://your-service-host:4318/v1/traces`
- **Protocol**: HTTP/1.1 or HTTP/2
- **Content-Type**: `application/x-protobuf`
- **Headers**: `Authorization: Bearer <jwt-token>`

Both protocols use the same:
- JWT authentication mechanism
- Protobuf message format
- Processing pipeline
- ClickHouse storage

## Endpoints

### gRPC Server (Port 4317)
- OTLP gRPC services for logs and traces

### HTTP Server (Port 4318)
- `/v1/logs` - OTLP logs endpoint (POST)
- `/v1/traces` - OTLP traces endpoint (POST)

### Management Server (Port 8000)
- `/` - Basic information page
- `/_readiness` - Readiness probe
- `/_liveness` - Liveness probe
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