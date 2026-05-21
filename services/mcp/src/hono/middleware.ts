import { type MiddlewareHandler } from 'hono'

import { httpRequestDurationSeconds, httpRequestsTotal, routeLabel } from './metrics'

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
    const stop = httpRequestDurationSeconds.startTimer({ method, route })
    await next()
    const status = String(c.res.status)
    httpRequestsTotal.inc({ method, route, status })
    stop({ method, route, status })
}
