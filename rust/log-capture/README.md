# PostHog Log Capture Service

A service that receives OpenTelemetry Protocol (OTLP) logs via gRPC and processes them based on team authentication.

## Features

- Receives OTLP logs via gRPC on port 4317
- Authenticates clients using JWT tokens
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

Clients must authenticate by sending a valid JWT token in the Authorization header:

```http
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
cargo run --bin log_capture
```

### With Docker

```bash
docker build -t posthog/log-capture .
docker run -p 4317:4317 -p 8000:8000 -e JWT_SECRET=your_secret_key posthog/log-capture
```

## Sending Logs

You can configure any OpenTelemetry-compatible client to send logs to this service. Make sure to:

1. Set the gRPC endpoint to `http://your-service-host:4317`
2. Configure the client to include the JWT token in the Authorization header
3. Use the standard OTLP log format

## Endpoints

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
