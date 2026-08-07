// Prometheus metrics for the integration-service.
//
// Cardinality is caller × provider × key. Both the caller set (the client registry) and
// the key set (src/providers.ts) are fixed configuration, so the series count is bounded
// — but only because nothing here ever takes a label value from a request. A key a caller
// names that the manifest does not define is recorded under a constant label instead; see
// policy/resolve.ts. Never add a per-team or per-request label.
//
// The rotation metrics are the reason this service is worth instrumenting at all. See
// the note on previousVersionUseTotal — "was the old value still needed" is the
// question a rotation actually turns on, and it is not the same question as "did we
// serve the old value".

import { Counter, Gauge, Histogram, Registry, collectDefaultMetrics } from 'prom-client'

import type { ResolveOutcome } from './types.js'

export const register = new Registry()

collectDefaultMetrics({ register, prefix: 'integration_service_' })

// ---------------------------------------------------------------------------
// Resolve / audit
// ---------------------------------------------------------------------------

export const resolveTotal = new Counter({
    name: 'integration_secret_resolve_total',
    help: 'Credential field resolutions, by caller and outcome',
    labelNames: ['caller', 'provider', 'key', 'result'],
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

// The one that gates retiring an old value.
//
// We serve both values during a rotation and cannot observe which one the caller's
// request to the third party actually succeeded with — so this is NOT inferred here.
// It is reported by the caller: a client that fell back to the previous value lists
// that key in the signed `previous_used` claim on its next resolve. Signed, so it
// cannot be forged by anything that is not already an authorized caller, and free of
// an extra round trip.
//
// When this stays at zero across the quiet window AND current-value reads are
// non-zero, the old value is safe to delete. Zero on its own is not evidence — it is
// equally consistent with nothing reading the credential at all.
export const previousVersionUseTotal = new Counter({
    name: 'integration_secret_previous_version_use_total',
    help: 'Times a caller reported that only the previous value worked against the third party',
    labelNames: ['caller', 'provider', 'key'],
    registers: [register],
})

export const secretAgeSeconds = new Gauge({
    name: 'integration_secret_age_seconds',
    help: 'Age of a provider secret current version, for "not rotated in N days" alerting',
    labelNames: ['provider'],
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
    help: 'Age of the oldest snapshot still being served because refresh is failing (0 when healthy)',
    labelNames: ['provider'],
    registers: [register],
})

export const storeErrorsTotal = new Counter({
    name: 'integration_secret_store_errors_total',
    help: 'Failed reads from the backing secret store',
    labelNames: ['provider'],
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

export function observeResolve(caller: string, provider: string, key: string, result: ResolveOutcome): void {
    resolveTotal.labels({ caller, provider, key, result }).inc()
    if (result === 'ok') {
        lastResolvedTimestamp.labels({ provider, key }).set(Date.now() / 1000)
    }
}

export function observeKms(op: 'generate_data_key' | 'decrypt', result: 'ok' | 'error'): void {
    kmsOperationsTotal.labels({ op, result }).inc()
}
