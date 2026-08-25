import { type MiddlewareHandler } from 'hono'

import { httpRequestDurationSeconds, httpRequestsTotal, inflightRequests, routeLabel } from './metrics'

const DEV_LOG_VISIBLE_HEADERS = new Set([
    'accept',
    'content-length',
    'content-type',
    'mcp-protocol-version',
    'user-agent',
])

export const devRequestLogger: MiddlewareHandler = async (c, next) => {
    const headers: Record<string, string> = {}
    c.req.raw.headers.forEach((value, key) => {
        headers[key] = DEV_LOG_VISIBLE_HEADERS.has(key.toLowerCase()) ? value : '[REDACTED]'
    })

    const url = new URL(c.req.url)
    console.info('[MCP dev]', {
        method: c.req.method,
        pathname: url.pathname,
        queryParameters: [...new Set(url.searchParams.keys())],
        headers,
        body: {
            present: c.req.raw.body !== null,
            contentLength: c.req.header('content-length') ?? 'unknown',
            contentType: c.req.header('content-type') ?? 'unknown',
        },
    })

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
