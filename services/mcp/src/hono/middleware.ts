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

export const corsMiddleware: MiddlewareHandler<HonoEnv> = cors({
    origin: (origin) => origin,
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
