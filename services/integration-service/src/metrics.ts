// Prometheus metrics.
//
// Every label value comes from fixed configuration in code, never from a request: an
// unknown key and an unrecognised product both collapse to a constant (policy/resolve.ts,
// products.ts). Never add a per-team or per-request label.

import { Counter, Gauge, Histogram, Registry, collectDefaultMetrics } from 'prom-client'

import type { CallerIdentity, ResolveOutcome } from './types'

export const register = new Registry()

collectDefaultMetrics({ register, prefix: 'integration_service_' })

// ---------------------------------------------------------------------------
// Resolve / audit
// ---------------------------------------------------------------------------

export const resolveTotal = new Counter({
    name: 'integration_secret_resolve_total',
    help: 'Credential field resolutions, by deployment, product and outcome',
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

// How much traffic is reading a field that is mid-rotation. Says nothing about whether
// anyone needed the previous value.
export const previousVersionServedTotal = new Counter({
    name: 'integration_secret_previous_version_served_total',
    help: 'Responses in which a previous (<KEY>_FALLBACKS) value was included alongside the current one',
    labelNames: ['provider', 'key'],
    registers: [register],
})

export const secretAgeSeconds = new Gauge({
    name: 'integration_secret_age_seconds',
    help: 'Time since the mounted secret last changed, for "not rotated in N days" alerting',
    registers: [register],
})

// ---------------------------------------------------------------------------
// Mount health
// ---------------------------------------------------------------------------

// An unreadable mount keeps the last snapshot rather than failing every read, so this
// gauge is the only sign of that degradation. Alert on it.
export const servingStaleSeconds = new Gauge({
    name: 'integration_secret_serving_stale_seconds',
    help: 'Age of the snapshot still being served because the mount could not be re-read (0 when healthy)',
    registers: [register],
})

export const storeErrorsTotal = new Counter({
    name: 'integration_secret_store_errors_total',
    help: 'Reads of the secret mount that returned nothing',
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

// The signing-key reload fails open so a malformed edit cannot lock a running fleet out.
// These two make that alertable: staleness on the gauge means a revocation has not landed
// on this pod.
export const signingKeysLastLoadedTimestamp = new Gauge({
    name: 'integration_service_signing_keys_last_loaded_timestamp',
    help: 'Unix timestamp of the last successful load of the caller signing keys',
    registers: [register],
})

export const signingKeyReloadFailuresTotal = new Counter({
    name: 'integration_service_signing_key_reload_failures_total',
    help: 'Background signing-key reloads that failed, leaving the previous key set in place',
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
