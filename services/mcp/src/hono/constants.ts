import { resolveAuthorizationServerUrl } from '@/lib/oauth-constants'
import type { Env } from '@/tools/types'

export {
    USER_AGENT,
    type GetUserAgentOptions,
    getUserAgent,
    POSTHOG_US_BASE_URL,
    POSTHOG_EU_BASE_URL,
    toCloudRegion,
    getBaseUrlForRegion,
    MCP_DOCS_URL,
    OAUTH_PROXY_URL,
    OAUTH_SCOPES_SUPPORTED,
} from '@/lib/oauth-constants'

/**
 * Custom API base URL for self-hosted PostHog instances.
 *
 * WARNING: In PostHog Production, this should NOT be set.
 * The code automatically handles US/EU region routing via getAuthorizationServerUrl().
 * Only set this for self-hosted PostHog deployments.
 */
export const getCustomApiBaseUrl = (): string | undefined => process.env.POSTHOG_API_BASE_URL || undefined

export const getAuthorizationServerUrl = (): string => resolveAuthorizationServerUrl(getCustomApiBaseUrl())

export function getEnv(): Env {
    // Tests set `TEST=1` to short-circuit features that need real network (e.g.
    // context-mill GitHub fetch). Mirrors the Cloudflare miniflare binding.
    const extras: Record<string, string | undefined> = {}
    if (process.env.TEST) {
        extras.TEST = process.env.TEST
    }
    return {
        INKEEP_API_KEY: process.env.INKEEP_API_KEY || undefined,
        POSTHOG_API_BASE_URL: process.env.POSTHOG_API_BASE_URL || undefined,
        MCP_APPS_BASE_URL: process.env.MCP_APPS_BASE_URL || undefined,
        POSTHOG_MCP_APPS_ANALYTICS_BASE_URL: process.env.POSTHOG_MCP_APPS_ANALYTICS_BASE_URL || undefined,
        POSTHOG_UI_APPS_TOKEN: process.env.POSTHOG_UI_APPS_TOKEN || undefined,
        POSTHOG_ANALYTICS_API_KEY: process.env.POSTHOG_ANALYTICS_API_KEY || undefined,
        POSTHOG_ANALYTICS_HOST: process.env.POSTHOG_ANALYTICS_HOST || undefined,
        ...extras,
    }
}

// Per-instance idle session TTL. Stale entries are evicted lazily on access; this
// caps how long a streamable/SSE session can sit unused in memory before being dropped.
export const SESSION_TTL_MS = 30 * 60 * 1000

// Hard cap on concurrent in-memory sessions per pod. Acts as a back-pressure signal:
// once full, we run a compaction sweep before rejecting new connections.
export const MAX_SESSIONS_PER_INSTANCE = 10_000

// Header allow-list for CORS preflight. Kept here so the routing layer doesn't carry
// a magic literal of header names.
export const ALLOWED_REQUEST_HEADERS = [
    'Authorization',
    'Content-Type',
    'mcp-session-id',
    'x-posthog-organization-id',
    'x-posthog-project-id',
    'x-posthog-mcp-version',
    'x-posthog-readonly',
    'x-posthog-mcp-consumer',
    'x-posthog-mcp-mode',
] as const

// Auth-server fallback paths that MCP clients sometimes hit directly on this server
// (instead of following the RFC 9728 metadata). These are routed through `matchAuthServerRedirect`.
export const AUTH_REDIRECT_PATHS = [
    '/.well-known/oauth-authorization-server',
    '/.well-known/jwks.json',
    '/oauth/*',
    '/register',
    '/authorize',
    '/token',
] as const
