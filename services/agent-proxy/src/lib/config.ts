// Environment variable loading and validation for the agent-proxy service.
//
// Required vars (must be present in production / NODE_ENV=production):
//   TASKS_REDIS_URL
//   SANDBOX_JWT_PUBLIC_KEY
//   AGENT_PROXY_DJANGO_CALLBACK_URL
//
// Optional with defaults:
//   SANDBOX_JWT_PUBLIC_KEY_SECONDARY    — extra public key trusted during key rotation
//   TASKS_AGENT_PROXY_CORS_ORIGINS      — comma-separated origins; '' disables CORS
//   AGENT_PROXY_MAX_CONCURRENT_STREAMS  — default 1000; per-pod cap on open SSE streams
//   AGENT_PROXY_MAX_STREAMS_PER_RUN     — default 25; per-run cap on open SSE streams
//   AGENT_PROXY_METRICS_TOKEN           — default ''; bearer token gating /_metrics when set
//   PORT                                — default 8003
//   HOST                                — default '0.0.0.0'
//   SHUTDOWN_GRACE_MS                   — default 300000 (5 min)
//   SHUTDOWN_PRESTOP_DELAY_MS           — default 0

import { getEnv, type KnownEnvKey } from './env.js'
import { logger } from './logging.js'

export interface Config {
    redisUrl: string
    // PEM strings with real newlines (backslash-n sequences normalized before storage). The
    // primary key first, then an optional rotation-secondary key; a token verifies against any.
    sandboxJwtPublicKeysPem: string[]
    // Parsed from comma-separated TASKS_AGENT_PROXY_CORS_ORIGINS; '*' = all origins
    corsOrigins: Set<string>
    // Base URL of the internal Django service (no trailing slash)
    djangoCallbackBaseUrl: string
    // Shared secret sent as X-Agent-Proxy-Secret on the Django callback so Django can prove the call
    // came from this proxy and not directly from a sandbox. Empty disables it (local/dev).
    agentProxyCallbackSecret: string
    // Each open SSE stream holds a dedicated Redis connection, so these caps protect the Redis
    // maxclients budget: a pod-wide total and a per-run fanout limit (one stream-read token must
    // not be able to exhaust the pod).
    maxConcurrentStreams: number
    maxStreamsPerRun: number
    // Bearer token gating /_metrics when set. Deployments scrape metrics in-cluster via
    // annotation-based Prometheus, which sends no auth header, so this stays optional and the
    // route stays open for that scrape; external exposure is blocked at the ingress instead.
    metricsToken: string
    port: number
    host: string
    shutdownGraceMs: number
    shutdownPrestopDelayMs: number
}

// Replace every literal two-character sequence `\n` (backslash + n, as stored
// in environment variables) with a real newline (0x0A), so the PEM can be
// parsed by importSPKI. Must run before any call to importSPKI.
export function normalizePemKey(raw: string): string {
    return raw.replace(/\\n/g, '\n')
}

function parseCorsOrigins(raw: string): Set<string> {
    if (!raw.trim()) {
        return new Set()
    }
    return new Set(
        raw
            .split(',')
            .map((s) => s.trim())
            .filter(Boolean)
    )
}

function requireEnv(name: KnownEnvKey, isProd: boolean): string {
    const value = getEnv(name)
    if (!value) {
        if (isProd) {
            logger.error('config:missing_required_env', { name })
            process.exit(1)
        }
        return ''
    }
    return value
}

export function loadConfig(): Config {
    const isProd = getEnv('NODE_ENV') === 'production'

    // nosemgrep: trailofbits.generic.redis-unencrypted-transport.redis-unencrypted-transport
    const localRedisFallbackUrl = 'redis://localhost:6379'
    const redisUrl = getEnv('TASKS_REDIS_URL') ?? (isProd ? requireEnv('TASKS_REDIS_URL', true) : localRedisFallbackUrl)

    // Primary key (required) plus an optional secondary trusted during a key rotation overlap.
    const sandboxJwtPublicKeysPem = [
        normalizePemKey(requireEnv('SANDBOX_JWT_PUBLIC_KEY', isProd)),
        normalizePemKey(getEnv('SANDBOX_JWT_PUBLIC_KEY_SECONDARY') ?? ''),
    ].filter((pem) => pem.length > 0)

    const djangoCallbackBaseUrl = requireEnv('AGENT_PROXY_DJANGO_CALLBACK_URL', isProd)

    const agentProxyCallbackSecret = getEnv('AGENT_PROXY_CALLBACK_SECRET') ?? ''

    const maxConcurrentStreamsRaw = getEnv('AGENT_PROXY_MAX_CONCURRENT_STREAMS')
    const maxConcurrentStreams = maxConcurrentStreamsRaw !== undefined ? parseInt(maxConcurrentStreamsRaw, 10) : 1000
    if (Number.isNaN(maxConcurrentStreams) || maxConcurrentStreams <= 0) {
        logger.error('config:invalid_max_concurrent_streams', { raw: maxConcurrentStreamsRaw })
        process.exit(1)
    }

    const maxStreamsPerRunRaw = getEnv('AGENT_PROXY_MAX_STREAMS_PER_RUN')
    const maxStreamsPerRun = maxStreamsPerRunRaw !== undefined ? parseInt(maxStreamsPerRunRaw, 10) : 25
    if (Number.isNaN(maxStreamsPerRun) || maxStreamsPerRun <= 0) {
        logger.error('config:invalid_max_streams_per_run', { raw: maxStreamsPerRunRaw })
        process.exit(1)
    }

    const metricsToken = getEnv('AGENT_PROXY_METRICS_TOKEN') ?? ''

    const corsOrigins = parseCorsOrigins(getEnv('TASKS_AGENT_PROXY_CORS_ORIGINS') ?? '')

    const portRaw = getEnv('PORT')
    const port = portRaw !== undefined ? parseInt(portRaw, 10) : 8003
    if (Number.isNaN(port)) {
        logger.error('config:invalid_port', { raw: portRaw })
        process.exit(1)
    }

    const host = getEnv('HOST') ?? '0.0.0.0'

    const graceRaw = getEnv('SHUTDOWN_GRACE_MS')
    const shutdownGraceMs = graceRaw !== undefined ? parseInt(graceRaw, 10) : 300_000
    const prestopRaw = getEnv('SHUTDOWN_PRESTOP_DELAY_MS')
    const shutdownPrestopDelayMs = prestopRaw !== undefined ? parseInt(prestopRaw, 10) : 0

    return {
        redisUrl,
        sandboxJwtPublicKeysPem,
        corsOrigins,
        djangoCallbackBaseUrl,
        agentProxyCallbackSecret,
        maxConcurrentStreams,
        maxStreamsPerRun,
        metricsToken,
        port,
        host,
        shutdownGraceMs,
        shutdownPrestopDelayMs,
    }
}
