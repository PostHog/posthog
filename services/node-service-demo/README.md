# Node service demo

This temporary service validates `@posthog/node-service`, the service scaffold, production bundling, Docker builds, and database-backed tests. Remove it after the runtime has a permanent adopter.

The service stores named counters in Postgres:

- `POST /api/counters/:name/increment`
- `GET /api/counters/:name`

## Run locally

Start Postgres through the repository development stack, apply migrations, then run:

```bash
pnpm --filter=@posthog/node-service-demo migrate
pnpm --filter=@posthog/node-service-demo dev
```

The service listens on port 4010 by default.

## Run all tests

Prepare the repository test database:

```bash
docker compose -f docker-compose.dev.yml up -d db
TEST=1 SECRET_KEY=abcdef uv run python manage.py setup_test_environment --only-postgres
```

Run the unit, integration, and end-to-end suites with timing reports:

```bash
pnpm --filter=@posthog/node-service-demo test:ci
```

The integration and end-to-end suites refuse to use a database without `test` in its name. They apply the same migrations used outside tests.

## Database migrations

Versioned SQL migrations live in `migrations/` and run through [`@posthog/node-migrations`](/packages/node-migrations/README.md). The shared migration command records applied versions and uses a PostgreSQL advisory lock. This service has no custom build or migration scripts.

The service does not run migrations during startup. Run them as a separate deployment step:

```bash
pnpm --filter=@posthog/node-service-demo build
DATABASE_URL=postgres://... pnpm --filter=@posthog/node-service-demo migrate:production
```

## Build the image

```bash
pnpm --filter=@posthog/node-service-demo docker:build
```

The image contains `/code/migrate.mjs` and `/code/migrations` for a separate migration job. Its default command starts only the HTTP service. Run its migration entrypoint with:

```bash
docker run --rm \
    -e DATABASE_URL=postgres://... \
    posthog-node-service-demo \
    node --enable-source-maps /code/migrate.mjs --service node-service-demo
```
