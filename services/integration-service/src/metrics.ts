// Prometheus metrics for the integration-service.
//
// Cardinality is deployment × product × provider × key. Every one of those is drawn from
// fixed configuration in code, never from a request: a key the manifest does not define
// and a product we do not recognise both collapse to a constant. See policy/resolve.ts
// and deployments.ts. Never add a per-team or per-request label.
//
// Everything here is measured by this service. Nothing is reported to it by a caller, so
// no metric depends on a client being well behaved, current, or honest.

import { Counter, Gauge, Histogram, Registry, collectDefaultMetrics } from 'prom-client'

import type { CallerIdentity, ResolveOutcome } from './types.js'

export const register = new Registry()

collectDefaultMetrics({ register, prefix: 'integration_service_' })

// ---------------------------------------------------------------------------
// Resolve / audit
// ---------------------------------------------------------------------------

export const resolveTotal = new Counter({
    name: 'integration_secret_resolve_total',
    help: 'Credential field resolutions, by deployment, product and outcome',
    // `deployment` is authenticated; `product` is caller-supplied but collapsed to a
    // known set in deployments.ts, so both stay bounded.
    labelNames: ['deployment', 'product', 'provider', 'key', 'result'],
    registers: [register],
})

export const lastResolvedTimestamp = new Gauge({
    name: 'integration_secret_last_resolved_timestamp',
    help: 'Unix timestamp of the last successful resolution of a credential field',
    labelNames: ['provider', 'key'],
    registers: [register],
})

// ---------------------------------------------------------------------------
// Rotation
// ---------------------------------------------------------------------------

// How often we handed out a previous value at all — i.e. how much traffic is reading a
// field that is mid-rotation. Says nothing about whether anyone needed it.
export const previousVersionServedTotal = new Counter({
    name: 'integration_secret_previous_version_served_total',
    help: 'Responses in which a previous (AWSPREVIOUS) value was included alongside the current one',
    labelNames: ['provider', 'key'],
    registers: [register],
})

export const secretAgeSeconds = new Gauge({
    name: 'integration_secret_age_seconds',
    help: 'Age of the integration-service secret current version',
    registers: [register],
})

// ---------------------------------------------------------------------------
// Cache / storage health
// ---------------------------------------------------------------------------

export const cacheHitsTotal = new Counter({
    name: 'integration_secret_cache_hits_total',
    help: 'Provider snapshot lookups by the tier that served them',
    labelNames: ['layer'],
    registers: [register],
})

export const servingStaleSeconds = new Gauge({
    name: 'integration_secret_serving_stale_seconds',
    help: 'Age of the snapshot still being served because refresh is failing (0 when healthy)',
    registers: [register],
})

export const storeErrorsTotal = new Counter({
    name: 'integration_secret_store_errors_total',
    help: 'Failed reads from the backing secret store',
    registers: [register],
})

export const kmsOperationsTotal = new Counter({
    name: 'integration_secret_kms_operations_total',
    help: 'KMS calls made for envelope encryption',
    labelNames: ['op', 'result'],
    registers: [register],
})

export const usagePublishTotal = new Counter({
    name: 'integration_secret_usage_publish_total',
    help: 'Attempts to publish the usage rollup to the secrets index bucket',
    labelNames: ['result'],
    registers: [register],
})

// ---------------------------------------------------------------------------
// HTTP
// ---------------------------------------------------------------------------

export const httpRequestsTotal = new Counter({
    name: 'integration_service_http_requests_total',
    help: 'Total HTTP requests received',
    labelNames: ['method', 'route', 'status'],
    registers: [register],
})

export const httpRequestDurationSeconds = new Histogram({
    name: 'integration_service_http_request_duration_seconds',
    help: 'HTTP request duration in seconds',
    labelNames: ['method', 'route', 'status'],
    buckets: [0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5],
    registers: [register],
})

export const authFailuresTotal = new Counter({
    name: 'integration_service_auth_failures_total',
    help: 'Rejected requests, by why the token was not accepted',
    labelNames: ['reason'],
    registers: [register],
})

export const shuttingDown = new Gauge({
    name: 'integration_service_shutting_down',
    help: '1 if the service is in the process of shutting down, 0 otherwise',
    registers: [register],
})

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

export function observeResolve(
    identity: Pick<CallerIdentity, 'deployment' | 'product'>,
    provider: string,
    key: string,
    result: ResolveOutcome
): void {
    resolveTotal.labels({ deployment: identity.deployment, product: identity.product, provider, key, result }).inc()
    if (result === 'ok') {
        lastResolvedTimestamp.labels({ provider, key }).set(Date.now() / 1000)
    }
}

export function observeKms(op: 'generate_data_key' | 'decrypt', result: 'ok' | 'error'): void {
    kmsOperationsTotal.labels({ op, result }).inc()
}
