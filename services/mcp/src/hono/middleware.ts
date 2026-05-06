import { type MiddlewareHandler } from 'hono'
import { cors } from 'hono/cors'

import type { RedisLike } from './cache/RedisCache'
import { ALLOWED_REQUEST_HEADERS } from './constants'
import type { HonoEnv } from './types'

export const securityHeaders: MiddlewareHandler<HonoEnv> = async (c, next) => {
    await next()
    c.header('X-Content-Type-Options', 'nosniff')
    c.header('X-Frame-Options', 'DENY')
}

// Origins allowed to send credentialed-style cross-origin requests. Server-to-server
// MCP clients (Claude Code, Cursor, etc.) don't have an Origin and pass through fine;
// browser-context callers must come from the PostHog UI or the wizard.
//
// `MCP_ALLOWED_ORIGINS` is a comma-separated env override for self-hosted/dev. Localhost
// origins are allowed in non-production for local UI development.
const STATIC_ALLOWED_ORIGINS = ['https://us.posthog.com', 'https://eu.posthog.com', 'https://app.posthog.com']

function isAllowedOrigin(origin: string): boolean {
    if (STATIC_ALLOWED_ORIGINS.includes(origin)) {
        return true
    }
    const extra = process.env.MCP_ALLOWED_ORIGINS
    if (extra && extra.split(',').map((o) => o.trim()).includes(origin)) {
        return true
    }
    if (process.env.NODE_ENV !== 'production' && /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(origin)) {
        return true
    }
    return false
}

export const corsMiddleware: MiddlewareHandler<HonoEnv> = cors({
    origin: (origin) => (origin && isAllowedOrigin(origin) ? origin : null),
    allowMethods: ['GET', 'POST', 'DELETE', 'OPTIONS'],
    allowHeaders: [...ALLOWED_REQUEST_HEADERS],
    exposeHeaders: ['mcp-session-id'],
    maxAge: 86400,
})

export function attachRedis(redis: RedisLike): MiddlewareHandler<HonoEnv> {
    return async (c, next) => {
        c.set('redis', redis)
        await next()
    }
}
