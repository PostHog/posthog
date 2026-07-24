import { rateLimitChecksTotal, rateLimitErrorsTotal } from './metrics'

export interface RedisRateLimitOps {
    incr(key: string): Promise<number>
    expire(key: string, seconds: number): Promise<number>
    ttl(key: string): Promise<number>
}

export interface RateLimitConfig {
    scope: string
    limit: number
    windowSeconds: number
}

export interface RateLimitResult {
    allowed: boolean
    scope: string
    limit: number
    remaining: number
    resetSeconds: number
}

// Match PostHog's default REST API throttle (BurstRateThrottle /
// SustainedRateThrottle in posthog/rate_limit.py).
export const DEFAULT_BURST_LIMIT: RateLimitConfig = {
    scope: 'mcp_burst',
    limit: 480,
    windowSeconds: 60,
}

export const DEFAULT_SUSTAINED_LIMIT: RateLimitConfig = {
    scope: 'mcp_sustained',
    limit: 4800,
    windowSeconds: 3600,
}

export class RateLimiter {
    constructor(
        private readonly redis: RedisRateLimitOps,
        private readonly limits: RateLimitConfig[]
    ) {}

    // Fails open on per-limit Redis errors — serving traffic beats taking MCP
    // down when Redis hiccups.
    async check(identifier: string): Promise<RateLimitResult | null> {
        const results = await Promise.all(
            this.limits.map((limit) =>
                this.checkOne(identifier, limit).catch((err) => {
                    rateLimitErrorsTotal.inc({ scope: limit.scope })
                    console.error(`[RateLimiter] check failed for ${limit.scope}:`, err)
                    return null
                })
            )
        )

        let blocked: RateLimitResult | null = null
        let tightest: RateLimitResult | null = null
        for (const r of results) {
            if (!r) {
                continue
            }
            if (!r.allowed && !blocked) {
                blocked = r
            }
            if (!tightest || r.remaining < tightest.remaining) {
                tightest = r
            }
        }
        return blocked ?? tightest
    }

    private async checkOne(identifier: string, limit: RateLimitConfig): Promise<RateLimitResult> {
        const key = `mcp:rl:${limit.scope}:${identifier}`
        const count = await this.redis.incr(key)

        // First request in window has no TTL — set it. Subsequent INCRs leave
        // it alone so the window stays fixed rather than sliding.
        if (count === 1) {
            await this.redis.expire(key, limit.windowSeconds)
        }

        if (count <= limit.limit) {
            rateLimitChecksTotal.inc({ scope: limit.scope, result: 'allowed' })
            return {
                allowed: true,
                scope: limit.scope,
                limit: limit.limit,
                remaining: limit.limit - count,
                resetSeconds: limit.windowSeconds,
            }
        }

        // If EXPIRE was lost on the first request, re-set TTL so a stuck key
        // can't lock the user out forever.
        let ttl = await this.redis.ttl(key)
        if (ttl < 0) {
            await this.redis.expire(key, limit.windowSeconds)
            ttl = limit.windowSeconds
        }
        rateLimitChecksTotal.inc({ scope: limit.scope, result: 'blocked' })
        return {
            allowed: false,
            scope: limit.scope,
            limit: limit.limit,
            remaining: 0,
            resetSeconds: Math.max(1, ttl),
        }
    }
}

// Plain-text body so MCP clients without JSON-RPC framing on non-2xx still
// get a readable message.
export function buildRateLimitResponse(result: RateLimitResult): Response {
    return new Response(`Rate limit exceeded (${result.scope}). Retry after ${result.resetSeconds}s.`, {
        status: 429,
        headers: {
            'Content-Type': 'text/plain; charset=utf-8',
            'Retry-After': String(result.resetSeconds),
            'X-RateLimit-Limit': String(result.limit),
            'X-RateLimit-Remaining': String(result.remaining),
            'X-RateLimit-Reset': String(result.resetSeconds),
            'X-RateLimit-Scope': result.scope,
        },
    })
}
