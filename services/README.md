# Services

Independently deployed services with their own domain logic.

A service belongs here when it has its own deployment, owns domain logic that doesn't belong to any specific product, and isn't shared infrastructure or cross-cutting glue.

See [monorepo-layout.md](/docs/internal/monorepo-layout.md) for how services differ from products and platform.

## Node.js services

Scaffold a standalone Hono service with:

```bash
bin/hogli service:bootstrap <name>
```

The scaffold uses [`@posthog/node-service`](/packages/node-service/README.md) for structured logging, Prometheus metrics, optional OpenTelemetry spans, health endpoints, and graceful shutdown. It includes separate unit, integration, and end-to-end test layouts.

Use the repository-wide development stack for infrastructure-backed integration tests. Keep test resources isolated and refuse destructive setup against non-test databases. Apply versioned service migrations explicitly before tests and deployments rather than changing schemas during application startup. PostgreSQL services can use [`@posthog/node-migrations`](/packages/node-migrations/README.md) instead of implementing their own migration runner.

`services/node-service-demo/` is a temporary database-backed validation service. It will be removed after a permanent service adopts the runtime.
