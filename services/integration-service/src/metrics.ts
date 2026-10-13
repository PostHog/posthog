// No label value ever comes from a request: a key name becomes a label only once the mount
// is known to carry it, anything else collapses to a constant, and the untrusted `caller`
// claim is not a label at all. prom-client holds every series for the pod's lifetime, so an
// unbounded label set is a memory leak a caller could drive.

import { Counter, Gauge, Histogram, Registry, collectDefaultMetrics } from 'prom-client'

import type { ResolveOutcome } from './types'

export const register = new Registry()

collectDefaultMetrics({ register, prefix: 'integration_service_' })

export const resolveTotal = new Counter({
    name: 'integration_secret_resolve_total',
    help: 'Secret resolutions, by deployment, key and outcome',
    labelNames: ['deployment', 'key', 'result'],
    registers: [register],
})

export const lastResolvedTimestamp = new Gauge({
    name: 'integration_secret_last_resolved_timestamp',
    help: 'Unix timestamp of the last successful resolution of a secret',
    labelNames: ['key'],
    registers: [register],
})

// How much traffic is reading a secret that is mid-rotation. Says nothing about whether
// anyone needed the previous value.
export const previousVersionServedTotal = new Counter({
    name: 'integration_secret_previous_version_served_total',
    // Metric name kept as-is: renaming it would break every dashboard and alert already reading
    // it. The help text carries the correction.
    help: 'Responses in which a staged, incoming (<KEY>_FALLBACKS) value was included alongside the live one',
    labelNames: ['key'],
    registers: [register],
})

// An unreadable mount keeps the secrets already held rather than failing every read, so
// this gauge is the only sign of that degradation. Alert on it.
export const servingStaleSeconds = new Gauge({
    name: 'integration_secret_serving_stale_seconds',
    help: 'Age of the secrets still being served because the mount could not be re-read (0 when healthy)',
    registers: [register],
})

export const mountErrorsTotal = new Counter({
    name: 'integration_secret_store_errors_total',
    help: 'Reads of the secret mount that returned nothing',
    registers: [register],
})

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

export function observeResolve(deployment: string, key: string, result: ResolveOutcome): void {
    resolveTotal.labels({ deployment, key, result }).inc()
    if (result === 'ok') {
        lastResolvedTimestamp.labels({ key }).set(Date.now() / 1000)
    }
}
