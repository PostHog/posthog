import { rateLimitChecksTotal, rateLimitErrorsTotal } from './metrics'

// Redis ops needed by the rate limiter. Kept separate from RedisLike so the
// limiter can be unit-tested with a focused mock without dragging in scan/del.
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
    // Seconds until the current window resets. Equals `windowSeconds` on the
    // first request in a window; clamped to `>= 1` so Retry-After is never 0
    // when a limit trips at the very end of the window.
    resetSeconds: number
}

// Defaults sit above the highest existing PostHog REST endpoint limits
// (1200/min for symbol-set uploads, 12000/hour sustained) so the MCP server
// gives agent workflows extra headroom while still capping a runaway client.
// Burst caps a tight loop on a single token (~25 req/sec); sustained caps
// long-running automation across an hour.
export const DEFAULT_BURST_LIMIT: RateLimitConfig = {
    scope: 'mcp_burst',
    limit: 1500,
    windowSeconds: 60,
}

export const DEFAULT_SUSTAINED_LIMIT: RateLimitConfig = {
    scope: 'mcp_sustained',
    limit: 15000,
    windowSeconds: 3600,
}

export class RateLimiter {
    constructor(
        private readonly redis: RedisRateLimitOps,
        private readonly limits: RateLimitConfig[]
    ) {}

    // Check all configured limits for the given identifier. Returns the first
    // tripped limit (so the response carries that scope's Retry-After), or the
    // tightest remaining if all pass. Fails open on Redis errors — better to
    // serve traffic than to take MCP down because Redis hiccupped.
    async check(identifier: string): Promise<RateLimitResult | null> {
        const results: RateLimitResult[] = []
        for (const limit of this.limits) {
            try {
                results.push(await this.checkOne(identifier, limit))
            } catch (err) {
                rateLimitErrorsTotal.inc({ scope: limit.scope })
                console.error(`[RateLimiter] check failed for ${limit.scope}:`, err)
                // Fail open: a single failed check doesn't deny the request.
            }
        }
        if (results.length === 0) {
            return null
        }
        const blocked = results.find((r) => !r.allowed)
        if (blocked) {
            return blocked
        }
        return results.reduce((min, r) => (r.remaining < min.remaining ? r : min), results[0]!)
    }

    private async checkOne(identifier: string, limit: RateLimitConfig): Promise<RateLimitResult> {
        const key = `mcp:rl:${limit.scope}:${identifier}`
        const count = await this.redis.incr(key)

        // On the very first request of a window the key has no TTL — set it.
        // Subsequent INCRs leave the TTL untouched so we get a fixed window.
        if (count === 1) {
            await this.redis.expire(key, limit.windowSeconds)
        }

        const allowed = count <= limit.limit
        if (allowed) {
            rateLimitChecksTotal.inc({ scope: limit.scope, result: 'allowed' })
            return {
                allowed,
                scope: limit.scope,
                limit: limit.limit,
                remaining: Math.max(0, limit.limit - count),
                resetSeconds: limit.windowSeconds,
            }
        }

        // Blocked path: read TTL so Retry-After reflects the actual window
        // remaining, not a guess. If the TTL got lost (rare: EXPIRE call failed
        // on the first request) re-set it so we don't lock the user out
        // indefinitely on a stuck key.
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

// Build a 429 response with standard rate-limit headers. Body is plain text so
// MCP clients without JSON-RPC framing for non-2xx responses still get a
// readable message.
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
