// Prometheus metrics for the agent-proxy service.
//
// Metric names are byte-identical to their Python counterparts in
// products/tasks/backend/metrics.py so dashboards and alerts work across both
// the Python ASGI proxy and this Node service without changes.
//
// Cardinality is intentionally kept low: only origin_product and outcome are
// used as labels on the hot-path stream metrics. Never add per-run or per-team
// labels here.

import { Counter, Gauge, Histogram, Registry, collectDefaultMetrics } from 'prom-client'

import type { StreamConnectionOutcome } from '../lib/types.js'

export const register = new Registry()

// Collect default Node.js metrics (event loop lag, GC, memory, etc.) with a
// consistent prefix so they don't collide with application metric names.
collectDefaultMetrics({ register, prefix: 'agent_proxy_' })

// ---------------------------------------------------------------------------
// SSE stream connection metrics (names match Python counterparts exactly)
// ---------------------------------------------------------------------------

export const taskRunStreamConnectionsOpenedTotal = new Counter({
    name: 'posthog_tasks_task_run_stream_connections_opened_total',
    help: 'SSE task-run stream connections opened',
    labelNames: ['origin_product'],
    registers: [register],
})

export const taskRunStreamConnectionsClosedTotal = new Counter({
    name: 'posthog_tasks_task_run_stream_connections_closed_total',
    help: 'SSE task-run stream connections closed, labeled by how they ended',
    labelNames: ['origin_product', 'outcome'],
    registers: [register],
})

// Connection lifetimes span a few seconds (cold reconnect) to the 6h sandbox
// TTL. The 120s bucket is deliberate: it isolates connections cut at the
// Envoy/Contour response_timeout boundary from genuinely long-lived ones.
export const taskRunStreamConnectionDurationSeconds = new Histogram({
    name: 'posthog_tasks_task_run_stream_connection_duration_seconds',
    help: 'Lifetime of an SSE task-run stream connection',
    labelNames: ['origin_product', 'outcome'],
    buckets: [1, 5, 15, 30, 60, 120, 300, 600, 1800, 3600, 7200, 21600],
    registers: [register],
})

// Stream length is capped at TASK_RUN_STREAM_MAX_LENGTH (~20k); the top
// buckets show how close real runs get to the trim threshold.
export const taskRunStreamLengthOnConnect = new Histogram({
    name: 'posthog_tasks_task_run_stream_length_on_connect',
    help: 'Redis stream length observed when an SSE connection reconnects with a cursor',
    buckets: [10, 50, 100, 500, 1000, 2500, 5000, 10000, 15000, 20000],
    registers: [register],
})

export const taskRunStreamResumeGapTotal = new Counter({
    name: 'posthog_tasks_task_run_stream_resume_gap_total',
    help: 'SSE reconnects whose Last-Event-ID was already trimmed from Redis (events lost for that client)',
    labelNames: ['origin_product'],
    registers: [register],
})

// Connections turned away by the concurrency caps before any Redis work; reason is
// 'pod_capacity' (pod-wide total reached) or 'run_capacity' (per-run fanout reached).
export const taskRunStreamConnectionsRejectedTotal = new Counter({
    name: 'posthog_tasks_task_run_stream_connections_rejected_total',
    help: 'SSE task-run stream connections rejected by concurrency caps',
    labelNames: ['reason'],
    registers: [register],
})

// ---------------------------------------------------------------------------
// Ingest plane metrics
// ---------------------------------------------------------------------------

export const streamIngestEventsTotal = new Counter({
    name: 'posthog_tasks_stream_ingest_events_total',
    help: 'Sandbox-to-Node ingested events by acceptance result',
    labelNames: ['result'],
    registers: [register],
})

// ---------------------------------------------------------------------------
// HTTP infrastructure metrics
// ---------------------------------------------------------------------------

// Map parameterised route paths to stable label values so cardinality stays
// bounded. Dynamic segments (UUIDs, IDs) must never appear in label values.
export function routeLabel(pathname: string): string {
    // Probe and scrape paths are already stable.
    if (pathname === '/_health' || pathname === '/_readyz' || pathname === '/_metrics' || pathname === '/health') {
        return pathname
    }
    // SSE read leg: /v1/runs/<run>/stream
    if (/^\/v1\/runs\/[^/]+\/stream$/.test(pathname)) {
        return '/v1/runs/stream'
    }
    // NDJSON ingest leg: /v1/runs/<run>/ingest
    if (/^\/v1\/runs\/[^/]+\/ingest$/.test(pathname)) {
        return '/v1/runs/ingest'
    }
    return 'other'
}

export const httpRequestsTotal = new Counter({
    name: 'agent_proxy_http_requests_total',
    help: 'Total HTTP requests received',
    labelNames: ['method', 'route', 'status'],
    registers: [register],
})

export const httpRequestDurationSeconds = new Histogram({
    name: 'agent_proxy_http_request_duration_seconds',
    help: 'HTTP request duration in seconds',
    labelNames: ['method', 'route', 'status'],
    buckets: [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10],
    registers: [register],
})

export const inflightRequests = new Gauge({
    name: 'agent_proxy_http_requests_inflight',
    help: 'Number of HTTP requests currently being processed',
    labelNames: ['route'] as const,
    registers: [register],
})

export const shuttingDown = new Gauge({
    name: 'agent_proxy_shutting_down',
    help: '1 if the service is in the process of shutting down, 0 otherwise',
    registers: [register],
})

// Tracks the number of currently open SSE stream connections.
export const openSseStreams = new Gauge({
    name: 'agent_proxy_sse_open_streams',
    help: 'Number of SSE task-run stream connections currently open',
    registers: [register],
})

// ---------------------------------------------------------------------------
// Convenience wrappers (mirror the Python observe_* helpers)
// ---------------------------------------------------------------------------

export function observeStreamConnectionOpened(originProduct: string): void {
    taskRunStreamConnectionsOpenedTotal.labels({ origin_product: originProduct }).inc()
    openSseStreams.inc()
}

export function observeStreamConnectionClosed(
    originProduct: string,
    outcome: StreamConnectionOutcome,
    durationSeconds: number
): void {
    taskRunStreamConnectionsClosedTotal.labels({ origin_product: originProduct, outcome }).inc()
    taskRunStreamConnectionDurationSeconds.labels({ origin_product: originProduct, outcome }).observe(durationSeconds)
    openSseStreams.dec()
}

export function observeStreamLengthOnConnect(length: number): void {
    taskRunStreamLengthOnConnect.observe(length)
}

export function observeStreamResumeGap(originProduct: string): void {
    taskRunStreamResumeGapTotal.labels({ origin_product: originProduct }).inc()
}

export function observeStreamConnectionRejected(reason: string): void {
    taskRunStreamConnectionsRejectedTotal.labels({ reason }).inc()
}

export function observeStreamIngestEvents(opts: { accepted: number; duplicate: number }): void {
    if (opts.accepted > 0) {
        streamIngestEventsTotal.labels({ result: 'accepted' }).inc(opts.accepted)
    }
    if (opts.duplicate > 0) {
        streamIngestEventsTotal.labels({ result: 'duplicate' }).inc(opts.duplicate)
    }
}
