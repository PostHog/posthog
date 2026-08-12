# S3 Integration Tests

## Running Integration Tests

The integration tests run against the dev stack's `objectstorage` service — SeaweedFS, S3 API on port 19000.

From the PostHog root directory:

```bash
# Start object storage and wait until it is ready
docker compose -f docker-compose.dev-full.yml up objectstorage -d --wait

# Run the integration tests
cd rust/common/s3
cargo test -- --ignored

# Stop it when done
docker compose -f docker-compose.dev-full.yml stop objectstorage
```

Wait for readiness rather than just for the container to start: SeaweedFS registers the
`object_storage_root_user` identity through a background bootstrap loop and returns
`InvalidAccessKeyId` until that completes. The service's healthcheck gates on that
bootstrap, so `--wait` is what makes these tests deterministic.

Credentials are set by the compose service:

- Access key: `object_storage_root_user`
- Secret key: `object_storage_root_password`

## Unit Tests

Unit tests don't need object storage and exercise the mock implementation:

```bash
cargo test --lib
```
