import { collectDefaultMetrics, Counter, Gauge, Histogram, register } from 'prom-client'

collectDefaultMetrics({ prefix: 'mcp_' })

export const httpRequestsTotal = new Counter({
    name: 'mcp_http_requests_total',
    help: 'HTTP requests received by the Hono MCP server.',
    labelNames: ['method', 'route', 'status'] as const,
})

export const httpRequestDurationSeconds = new Histogram({
    name: 'mcp_http_request_duration_seconds',
    help: 'HTTP request duration by route.',
    labelNames: ['method', 'route', 'status'] as const,
    buckets: [0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300],
})

export const toolCallsTotal = new Counter({
    name: 'mcp_tool_calls_total',
    help: 'MCP tool dispatches.',
    labelNames: ['tool', 'status'] as const,
})

export const toolCallDurationSeconds = new Histogram({
    name: 'mcp_tool_call_duration_seconds',
    help: 'MCP tool dispatch duration.',
    labelNames: ['tool', 'status'] as const,
    buckets: [0.01, 0.05, 0.1, 0.5, 1, 2, 5, 10, 30, 60, 120, 300],
})

export const initDurationSeconds = new Histogram({
    name: 'mcp_init_duration_seconds',
    help: 'Session init duration (cold-start cost per new session).',
    buckets: [0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10],
})

export const shuttingDown = new Gauge({
    name: 'mcp_shutting_down',
    help: 'Set to 1 when the pod is draining for shutdown.',
})

export const initTotal = new Counter({
    name: 'mcp_init_total',
    help: 'MCP session init outcomes.',
    labelNames: ['status'] as const,
})

export const inflightRequests = new Gauge({
    name: 'mcp_inflight_requests',
    help: 'Number of in-flight HTTP requests.',
    labelNames: ['route'] as const,
})

export const toolErrorsTotal = new Counter({
    name: 'mcp_tool_errors_total',
    help: 'MCP tool errors by category.',
    labelNames: ['tool', 'error_type'] as const,
})

export const redisOperationsTotal = new Counter({
    name: 'mcp_redis_operations_total',
    help: 'Redis cache and connection operations by outcome.',
    labelNames: ['operation', 'status'] as const,
})

export const authFailuresTotal = new Counter({
    name: 'mcp_auth_failures_total',
    help: 'Authentication failures on /mcp requests.',
    labelNames: ['reason'] as const,
})

export const rateLimitChecksTotal = new Counter({
    name: 'mcp_rate_limit_checks_total',
    help: 'Rate limit checks on /mcp requests, by scope and outcome.',
    labelNames: ['scope', 'result'] as const,
})

export const rateLimitErrorsTotal = new Counter({
    name: 'mcp_rate_limit_errors_total',
    help: 'Rate limit Redis op failures (request still served — fail-open).',
    labelNames: ['scope'] as const,
})

export const rateLimitBlockedByTeam = new Counter({
    name: 'mcp_rate_limit_blocked_by_team_total',
    help: 'Rate limit blocks on /mcp requests, by scope and team.',
    labelNames: ['scope', 'team_id'] as const,
})

export const contextMillRevalidationsTotal = new Counter({
    name: 'mcp_context_mill_revalidations_total',
    help: 'Context-mill resource revalidation attempts by caller and result.',
    labelNames: ['source', 'status', 'result'] as const,
})

// Typed-confirm two-tool paradigm (`confirmed_action`):
//
// - `prepares_total`/`executes_total` count outcomes of each phase. Watch
//   the prepare→execute conversion ratio per tool to detect tools the LLM
//   prepares but never executes (user declines or model loses track) and
//   tools the LLM executes repeatedly (replay attempts).
// - `refusals_total` breaks down execute refusals by reason so we can tune
//   TTL, signing-key rotation, and tool descriptions against real failure
//   modes instead of guessing.
export const confirmedActionPreparesTotal = new Counter({
    name: 'mcp_confirmed_action_prepares_total',
    help: 'Outcomes of -prepare tool calls under the typed-confirm paradigm.',
    labelNames: ['tool', 'status'] as const,
})

export const confirmedActionExecutesTotal = new Counter({
    name: 'mcp_confirmed_action_executes_total',
    help: 'Outcomes of -execute tool calls under the typed-confirm paradigm.',
    labelNames: ['tool', 'status'] as const,
})

export const confirmedActionRefusalsTotal = new Counter({
    name: 'mcp_confirmed_action_refusals_total',
    help: 'Reasons -execute calls were refused (wrong word, bad signature, expired, replay, mismatch).',
    labelNames: ['tool', 'reason'] as const,
})

// 1 if the codec + nonce ledger were installed at boot, 0 otherwise. A
// single boot-time console.error is easy to lose; this lets ops alert
// directly on `mcp_confirmed_action_runtime_installed == 0` regardless
// of whether anyone has tried a -prepare/-execute call yet.
export const confirmedActionRuntimeInstalled = new Gauge({
    name: 'mcp_confirmed_action_runtime_installed',
    help: 'Whether the typed-confirm runtime was installed successfully at boot (1 = yes, 0 = misconfigured / MCP_SIGNED_STATE_KEY missing).',
})

export const contextMillRevalidationDurationSeconds = new Histogram({
    name: 'mcp_context_mill_revalidation_duration_seconds',
    help: 'Context-mill resource revalidation duration.',
    labelNames: ['source', 'status'] as const,
    buckets: [0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30],
})

export const contextMillCacheEventsTotal = new Counter({
    name: 'mcp_context_mill_cache_events_total',
    help: 'Context-mill resource cache events.',
    labelNames: ['event'] as const,
})

export const contextMillManifestEntries = new Gauge({
    name: 'mcp_context_mill_manifest_entries',
    help: 'Latest successfully loaded context-mill slim manifest entry count.',
})

export const contextMillBodyReadsTotal = new Counter({
    name: 'mcp_context_mill_body_reads_total',
    help: 'Context-mill resource body reads by outcome.',
    labelNames: ['status'] as const,
})

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
