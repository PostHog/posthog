# S3 Integration Tests

## Running Integration Tests

The integration tests require SeaweedFS S3 to be running locally on port 8333.

### Option 1: Using PostHog Docker Compose (Recommended)

From the PostHog root directory:

```bash
# Start just the SeaweedFS service
docker compose -f docker-compose.dev.yml up seaweedfs -d

# Run the integration tests
cd rust/common/s3
cargo test -- --ignored

# Stop SeaweedFS when done
docker compose -f docker-compose.dev.yml down seaweedfs
```

### Option 2: Using Docker directly

```bash
# Start SeaweedFS with S3 enabled
docker run --rm -p 8333:8333 chrislusf/seaweedfs server -s3 -s3.port=8333

# Run the integration tests
cargo test -- --ignored
```

### Checking if SeaweedFS is Running

You can verify SeaweedFS S3 is running by hitting: http://localhost:8333

Credentials used by tests:

- Access key: `any`
- Secret: `any`

## Unit Tests

Unit tests don't require S3:

```bash
cargo test --lib
```
