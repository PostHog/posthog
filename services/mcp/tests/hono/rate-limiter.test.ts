import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
    buildRateLimitResponse,
    DEFAULT_BURST_LIMIT,
    DEFAULT_SUSTAINED_LIMIT,
    RateLimiter,
    type RedisRateLimitOps,
} from '@/hono/rate-limiter'

interface MockRedis extends RedisRateLimitOps {
    _ttls: Map<string, number>
}

function createMockRedis(): MockRedis {
    const counts = new Map<string, number>()
    const ttls = new Map<string, number>()
    return {
        incr: vi.fn(async (key: string) => {
            const next = (counts.get(key) ?? 0) + 1
            counts.set(key, next)
            return next
        }),
        expire: vi.fn(async (key: string, seconds: number) => {
            ttls.set(key, seconds)
            return 1
        }),
        ttl: vi.fn(async (key: string) => ttls.get(key) ?? -2),
        _ttls: ttls,
    }
}

describe('RateLimiter', () => {
    let redis: MockRedis

    beforeEach(() => {
        redis = createMockRedis()
    })

    it('allows requests under the limit', async () => {
        const limiter = new RateLimiter(redis, [{ scope: 'burst', limit: 3, windowSeconds: 60 }])
        const r1 = await limiter.check('user-a')
        const r2 = await limiter.check('user-a')
        const r3 = await limiter.check('user-a')
        expect(r1?.allowed).toBe(true)
        expect(r2?.allowed).toBe(true)
        expect(r3?.allowed).toBe(true)
        expect(r3?.remaining).toBe(0)
    })

    it('sets EXPIRE on the first request of a window and not on subsequent', async () => {
        const limiter = new RateLimiter(redis, [{ scope: 'burst', limit: 10, windowSeconds: 60 }])
        await limiter.check('user-a')
        await limiter.check('user-a')
        await limiter.check('user-a')
        expect(redis.expire).toHaveBeenCalledTimes(1)
        expect(redis.expire).toHaveBeenCalledWith('mcp:rl:burst:user-a', 60)
    })

    it('blocks requests over the limit and returns Retry-After info', async () => {
        const limiter = new RateLimiter(redis, [{ scope: 'burst', limit: 2, windowSeconds: 60 }])
        await limiter.check('user-a')
        await limiter.check('user-a')
        const blocked = await limiter.check('user-a')
        expect(blocked?.allowed).toBe(false)
        expect(blocked?.scope).toBe('burst')
        expect(blocked?.remaining).toBe(0)
        expect(blocked?.resetSeconds).toBeGreaterThan(0)
    })

    it('keys buckets per identifier', async () => {
        const limiter = new RateLimiter(redis, [{ scope: 'burst', limit: 1, windowSeconds: 60 }])
        const a1 = await limiter.check('user-a')
        const a2 = await limiter.check('user-a')
        const b1 = await limiter.check('user-b')
        expect(a1?.allowed).toBe(true)
        expect(a2?.allowed).toBe(false)
        expect(b1?.allowed).toBe(true)
    })

    it.each([
        { burstLimit: 2, sustainedLimit: 100, expectedScope: 'burst' },
        { burstLimit: 100, sustainedLimit: 2, expectedScope: 'sustained' },
    ])(
        'blocks on whichever limit trips first (burst=$burstLimit, sustained=$sustainedLimit → $expectedScope)',
        async ({ burstLimit, sustainedLimit, expectedScope }) => {
            const limiter = new RateLimiter(redis, [
                { scope: 'burst', limit: burstLimit, windowSeconds: 60 },
                { scope: 'sustained', limit: sustainedLimit, windowSeconds: 3600 },
            ])
            await limiter.check('user-a')
            await limiter.check('user-a')
            const result = await limiter.check('user-a')
            expect(result?.allowed).toBe(false)
            expect(result?.scope).toBe(expectedScope)
        }
    )

    it('reports the tightest remaining when all limits pass', async () => {
        const limiter = new RateLimiter(redis, [
            { scope: 'burst', limit: 10, windowSeconds: 60 },
            { scope: 'sustained', limit: 5, windowSeconds: 3600 },
        ])
        const result = await limiter.check('user-a')
        // burst remaining: 9, sustained remaining: 4 → sustained is tighter
        expect(result?.allowed).toBe(true)
        expect(result?.scope).toBe('sustained')
        expect(result?.remaining).toBe(4)
    })

    it('fails open if Redis errors on incr', async () => {
        const broken: RedisRateLimitOps = {
            incr: vi.fn(async () => {
                throw new Error('redis down')
            }),
            expire: vi.fn(async () => 1),
            ttl: vi.fn(async () => -2),
        }
        const limiter = new RateLimiter(broken, [{ scope: 'burst', limit: 1, windowSeconds: 60 }])
        const result = await limiter.check('user-a')
        expect(result).toBeNull()
    })

    it('re-sets TTL if it got lost on a blocked request', async () => {
        const limiter = new RateLimiter(redis, [{ scope: 'burst', limit: 1, windowSeconds: 60 }])
        await limiter.check('user-a')
        // Simulate the EXPIRE having failed: clear TTLs but keep the count.
        redis._ttls.clear()
        const blocked = await limiter.check('user-a')
        expect(blocked?.allowed).toBe(false)
        expect(blocked?.resetSeconds).toBe(60)
        expect(redis.expire).toHaveBeenCalledWith('mcp:rl:burst:user-a', 60)
    })

    it('matches PostHog REST API default throttle (480/min, 4800/hour)', () => {
        expect(DEFAULT_BURST_LIMIT).toEqual({ scope: 'mcp_burst', limit: 480, windowSeconds: 60 })
        expect(DEFAULT_SUSTAINED_LIMIT).toEqual({ scope: 'mcp_sustained', limit: 4800, windowSeconds: 3600 })
    })
})

describe('buildRateLimitResponse', () => {
    it('returns 429 with rate-limit headers', async () => {
        const response = buildRateLimitResponse({
            allowed: false,
            scope: 'burst',
            limit: 1500,
            remaining: 0,
            resetSeconds: 42,
        })
        expect(response.status).toBe(429)
        expect(response.headers.get('Retry-After')).toBe('42')
        expect(response.headers.get('X-RateLimit-Limit')).toBe('1500')
        expect(response.headers.get('X-RateLimit-Remaining')).toBe('0')
        expect(response.headers.get('X-RateLimit-Reset')).toBe('42')
        expect(response.headers.get('X-RateLimit-Scope')).toBe('burst')
        const body = await response.text()
        expect(body).toContain('burst')
        expect(body).toContain('42s')
    })
})
