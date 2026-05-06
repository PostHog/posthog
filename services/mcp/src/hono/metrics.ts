// Prometheus instrumentation for the Hono runtime. CF Workers can't host a
// scrape endpoint, so this lives Hono-side only. Metrics are registered on
// `prom-client`'s default registry (singleton) — the long-lived Node process
// is what makes that pattern fit; CF's per-request isolation does not.
import { collectDefaultMetrics, Counter, Gauge, Histogram, register } from 'prom-client'

// Default process-level metrics: heap, GC, event-loop lag, file descriptors, etc.
collectDefaultMetrics({ prefix: 'mcp_' })

// HTTP request volume by route + status. Path is normalized to a small set of
// known prefixes so cardinality stays bounded — raw URLs would blow up the
// metric (UI-app static asset paths, well-known per-resource paths).
export const httpRequestsTotal = new Counter({
    name: 'mcp_http_requests_total',
    help: 'HTTP requests received by the Hono MCP server.',
    labelNames: ['method', 'route', 'status'] as const,
})

export const httpRequestDurationSeconds = new Histogram({
    name: 'mcp_http_request_duration_seconds',
    help: 'HTTP request duration by route.',
    labelNames: ['method', 'route', 'status'] as const,
    // Wide range: health checks land in the 1ms bucket, tool calls in 100ms-10s.
    buckets: [0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30],
})

// Active streamable-HTTP sessions on this pod. Pair with the cap to dashboard
// "headroom" — `mcp_sessions_active / MAX_SESSIONS_PER_INSTANCE`.
export const sessionsActive = new Gauge({
    name: 'mcp_sessions_active',
    help: 'Active streamable HTTP sessions on this pod.',
})

// Reservation outcome at the back-pressure layer. `accepted` increments on
// every successful `reserve()`; `rejected` fires when the pod cap is hit and
// `compact()` couldn't free a slot — the saturation signal to alert on.
export const sessionReservationsTotal = new Counter({
    name: 'mcp_session_reservations_total',
    help: 'Outcomes from SessionStore.reserve().',
    labelNames: ['result'] as const,
})

// MCP tool dispatch outcomes. `status` is `success` | `error` | `validation_error`.
// Cardinality on `tool` is bounded by the registered tool catalog.
export const toolCallsTotal = new Counter({
    name: 'mcp_tool_calls_total',
    help: 'MCP tool dispatches.',
    labelNames: ['tool', 'status'] as const,
})

export const toolCallDurationSeconds = new Histogram({
    name: 'mcp_tool_call_duration_seconds',
    help: 'MCP tool dispatch duration.',
    labelNames: ['tool', 'status'] as const,
    buckets: [0.01, 0.05, 0.1, 0.5, 1, 2, 5, 10, 30, 60],
})

// HonoMcpServer.init() — fans out to PostHog API + flag eval + cache reads on
// every cold session. Slow tail here is the single biggest cold-start signal.
export const initDurationSeconds = new Histogram({
    name: 'mcp_init_duration_seconds',
    help: 'HonoMcpServer.init() duration (cold-start cost per new session).',
    buckets: [0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10],
})

// 0 normally, flips to 1 the moment SIGTERM lands. Useful in dashboards to
// align deploy windows with traffic dips and to confirm the readiness flip
// actually fired before pods went away.
export const shuttingDown = new Gauge({
    name: 'mcp_shutting_down',
    help: 'Set to 1 when the pod is draining for shutdown.',
})

// Map a request URL to a low-cardinality label. Anything not matched falls
// into `other` so a pathological client can't fan out the histogram series.
export function routeLabel(pathname: string): string {
    if (pathname === '/mcp' || pathname.startsWith('/mcp/')) {
        return '/mcp'
    }
    if (pathname === '/sse' || pathname.startsWith('/sse/')) {
        return '/sse'
    }
    if (pathname.startsWith('/.well-known/oauth-protected-resource')) {
        return '/.well-known/oauth-protected-resource'
    }
    if (pathname.startsWith('/ui-apps/')) {
        return '/ui-apps'
    }
    if (pathname === '/health' || pathname === '/healthz' || pathname === '/readyz') {
        return pathname
    }
    if (pathname === '/' || pathname === '/metrics') {
        return pathname
    }
    return 'other'
}

export { register }
