# S3 Integration Tests

## Running Integration Tests

The integration tests require MinIO to be running locally on port 19000.

### Option 1: Using PostHog Docker Compose (Recommended)

From the PostHog root directory:

```bash
# Start just the MinIO service
docker-compose -f docker-compose.dev-full.yml up objectstorage -d

# Run the integration tests
cd rust/common/s3
cargo test -- --ignored

# Stop MinIO when done
docker-compose -f docker-compose.dev-full.yml down objectstorage
```

### Option 2: Using Docker directly

```bash
# Start MinIO with PostHog's credentials
docker run -p 19000:19000 -p 19001:19001 \
  -e MINIO_ROOT_USER=object_storage_root_user \
  -e MINIO_ROOT_PASSWORD=object_storage_root_password \
  minio/minio:RELEASE.2025-04-22T22-12-26Z \
  server --address ":19000" --console-address ":19001" /data

# Run the integration tests
cargo test -- --ignored
```

### Checking if MinIO is Running

You can verify MinIO is running by visiting: http://localhost:19001 (MinIO Console)

Login credentials:

- Username: `object_storage_root_user`
- Password: `object_storage_root_password`

## Unit Tests

Unit tests don't require MinIO and test the mock implementation:

```bash
cargo test --lib
```
