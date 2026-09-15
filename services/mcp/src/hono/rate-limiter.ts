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

/**
 * Which bucket a request is billed to. `handshake` is session overhead —
 * opening a session, announcing readiness, keepalives, and reading the tool
 * catalog. `work` is everything that acts on project data.
 */
export type RequestCharge = 'handshake' | 'work'

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

// Same budget, separate keyspace: a client that reopens its session per prompt
// pays three requests before it does any work, and those must not spend the
// tool-call allowance. Handshakes stay bounded by the same numbers, which a
// working client never approaches.
export const DEFAULT_HANDSHAKE_BURST_LIMIT: RateLimitConfig = {
    ...DEFAULT_BURST_LIMIT,
    scope: 'mcp_handshake_burst',
}

export const DEFAULT_HANDSHAKE_SUSTAINED_LIMIT: RateLimitConfig = {
    ...DEFAULT_SUSTAINED_LIMIT,
    scope: 'mcp_handshake_sustained',
}

export class RateLimiter {
    private readonly limits: RateLimitConfig[]

    constructor(
        private readonly redis: RedisRateLimitOps,
        limits: RateLimitConfig[]
    ) {
        // Shortest window first, so a block costs the caller the window that
        // recovers soonest and leaves the longer windows untouched.
        this.limits = [...limits].sort((a, b) => a.windowSeconds - b.windowSeconds)
    }

    // Fails open on per-limit Redis errors — serving traffic beats taking MCP
    // down when Redis hiccups.
    async check(identifier: string): Promise<RateLimitResult | null> {
        let tightest: RateLimitResult | null = null
        for (const limit of this.limits) {
            const result = await this.checkOne(identifier, limit).catch((err) => {
                rateLimitErrorsTotal.inc({ scope: limit.scope })
                console.error(`[RateLimiter] check failed for ${limit.scope}:`, err)
                return null
            })
            if (!result) {
                continue
            }
            // One blocked window ends the check. Incrementing the remaining
            // windows here would let a client retrying through a 429 drain its
            // hourly bucket on requests the server never served.
            if (!result.allowed) {
                return result
            }
            if (!tightest || result.remaining < tightest.remaining) {
                tightest = result
            }
        }
        return tightest
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

/**
 * The limit table: one {@link RateLimiter} per charge, so handshake traffic and
 * real work never draw on the same bucket.
 */
export class ChargedRateLimiter {
    private readonly limiters: Record<RequestCharge, RateLimiter>

    constructor(redis: RedisRateLimitOps) {
        this.limiters = {
            work: new RateLimiter(redis, [DEFAULT_BURST_LIMIT, DEFAULT_SUSTAINED_LIMIT]),
            handshake: new RateLimiter(redis, [DEFAULT_HANDSHAKE_BURST_LIMIT, DEFAULT_HANDSHAKE_SUSTAINED_LIMIT]),
        }
    }

    check(identifier: string, charge: RequestCharge): Promise<RateLimitResult | null> {
        return this.limiters[charge].check(identifier)
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
