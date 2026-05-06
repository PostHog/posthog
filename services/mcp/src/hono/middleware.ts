import { type MiddlewareHandler } from 'hono'

import type { RedisLike } from './cache/RedisCache'
import { httpRequestDurationSeconds, httpRequestsTotal, routeLabel } from './metrics'
import type { HonoEnv } from './types'

export const securityHeaders: MiddlewareHandler<HonoEnv> = async (c, next) => {
    await next()
    c.header('X-Content-Type-Options', 'nosniff')
    c.header('X-Frame-Options', 'DENY')
}

// Records request count + duration with a low-cardinality `route` label
// (see metrics.ts/routeLabel). `/metrics` itself is excluded so scrapes don't
// pollute the histogram.
export const httpMetrics: MiddlewareHandler<HonoEnv> = async (c, next) => {
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

export function attachRedis(redis: RedisLike): MiddlewareHandler<HonoEnv> {
    return async (c, next) => {
        c.set('redis', redis)
        await next()
    }
}
