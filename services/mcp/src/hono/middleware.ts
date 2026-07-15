import { type MiddlewareHandler } from 'hono'

import { SENSITIVE_HEADERS } from '@/lib/logging'
import { redactToken } from '@/lib/utils'

import { httpRequestDurationSeconds, httpRequestsTotal, inflightRequests, routeLabel } from './metrics'

const DEV_LOG_BODY_LIMIT = 10_000

// Dev-only wire tap: dumps method, path, headers, and body for every request so
// local MCP client traffic can be inspected. Only registered when
// NODE_ENV === 'development' (see createApp) — never in production, where
// bodies and headers can carry customer data. The bearer token keeps its last
// 4 chars (redactToken) so requests can be told apart without leaking the key.
export const devRequestLogger: MiddlewareHandler = async (c, next) => {
    const headers: Record<string, string> = {}
    c.req.raw.headers.forEach((value, key) => {
        const lower = key.toLowerCase()
        if (lower === 'authorization') {
            headers[key] = redactToken(value.split(' ').pop() ?? '')
        } else if (SENSITIVE_HEADERS.includes(lower)) {
            headers[key] = '[REDACTED]'
        } else {
            headers[key] = value
        }
    })

    let body = '<empty>'
    if (c.req.raw.body) {
        // Clone so reading the body here doesn't consume the stream the
        // dispatcher reads from c.req.raw downstream.
        body = await c.req.raw
            .clone()
            .text()
            .catch(() => '<unreadable>')
        if (body.length > DEV_LOG_BODY_LIMIT) {
            body = `${body.slice(0, DEV_LOG_BODY_LIMIT)}… [truncated, ${body.length} chars total]`
        }
    }

    const url = new URL(c.req.url)
    console.info(
        `[MCP dev] ${c.req.method} ${url.pathname}${url.search}\nheaders: ${JSON.stringify(headers, null, 2)}\nbody: ${body}`
    )

    await next()
}

export const securityHeaders: MiddlewareHandler = async (c, next) => {
    await next()
    c.header('X-Content-Type-Options', 'nosniff')
    c.header('X-Frame-Options', 'DENY')
}

export const httpMetrics: MiddlewareHandler = async (c, next) => {
    const url = new URL(c.req.url)
    if (url.pathname === '/metrics') {
        await next()
        return
    }
    const route = routeLabel(url.pathname)
    const method = c.req.method
    inflightRequests.inc({ route })
    const stop = httpRequestDurationSeconds.startTimer({ method, route })
    try {
        await next()
    } finally {
        const status = String(c.res.status)
        httpRequestsTotal.inc({ method, route, status })
        stop({ method, route, status })
        inflightRequests.dec({ route })
    }
}
