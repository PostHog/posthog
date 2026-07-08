import { beforeEach, describe, expect, it, vi } from 'vitest'

import { rateLimitBlockedByTeam } from '@/hono/metrics'
import { __resetTrackedTeamIds, recordRateLimitBlock } from '@/hono/rate-limit-telemetry'
import type { RateLimitResult } from '@/hono/rate-limiter'
import type { RequestProperties } from '@/lib/request-properties'

function blocked(scope = 'mcp_sustained'): RateLimitResult {
    return { allowed: false, scope, limit: 4800, remaining: 0, resetSeconds: 60 }
}

function makeProps(overrides: Partial<RequestProperties> = {}): RequestProperties {
    return { apiToken: 'token', userHash: 'hash-a', ...overrides } as RequestProperties
}

async function teamValue(teamId: string, scope = 'mcp_sustained'): Promise<number> {
    const data = await rateLimitBlockedByTeam.get()
    const match = data.values.find((v) => v.labels.team_id === teamId && v.labels.scope === scope)
    return match?.value ?? 0
}

describe('recordRateLimitBlock', () => {
    beforeEach(() => {
        rateLimitBlockedByTeam.reset()
        __resetTrackedTeamIds()
    })

    async function totalSeries(): Promise<number> {
        return (await rateLimitBlockedByTeam.get()).values.length
    }

    it('labels by the client-supplied project id without touching redis', async () => {
        const get = vi.fn()
        await recordRateLimitBlock({ get } as never, makeProps({ projectId: '123' }), blocked())
        expect(await teamValue('123')).toBe(1)
        expect(get).not.toHaveBeenCalled()
    })

    it('falls back to the cached team id when no header is present', async () => {
        const get = vi.fn(async (key: string) => (key === 'mcp:token:hash-a:projectId' ? JSON.stringify('456') : null))
        await recordRateLimitBlock({ get } as never, makeProps(), blocked())
        expect(await teamValue('456')).toBe(1)
    })

    it('uses the unresolved bucket when the team is unknown', async () => {
        const get = vi.fn(async () => null)
        await recordRateLimitBlock({ get } as never, makeProps(), blocked())
        expect(await teamValue('unresolved')).toBe(1)
    })

    it('never throws and still records when the cache read fails', async () => {
        const get = vi.fn(async () => {
            throw new Error('redis down')
        })
        await expect(recordRateLimitBlock({ get } as never, makeProps(), blocked())).resolves.toBeUndefined()
        expect(await teamValue('unresolved')).toBe(1)
    })

    it('logs the block with the project id and a token redacted to its last 4 chars', async () => {
        const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
        const get = vi.fn()
        await recordRateLimitBlock(
            { get } as never,
            makeProps({ projectId: '123', apiToken: 'phx_secrettoken9876' }),
            blocked('mcp_burst')
        )
        expect(warn).toHaveBeenCalledWith(
            '[RateLimiter] rate limited',
            JSON.stringify({ scope: 'mcp_burst', projectId: '123', token: '****9876' })
        )
        warn.mockRestore()
    })

    it.each([['not-a-number'], ['12345678901234567890'], ['1; DROP']])(
        'buckets a non-numeric or oversized project id %j as unresolved',
        async (projectId) => {
            const get = vi.fn()
            await recordRateLimitBlock({ get } as never, makeProps({ projectId }), blocked())
            expect(await teamValue('unresolved')).toBe(1)
            expect(get).not.toHaveBeenCalled()
        }
    )

    it('caps distinct team series and routes the overflow to other', async () => {
        const get = vi.fn()
        for (let i = 0; i < 1500; i += 1) {
            await recordRateLimitBlock({ get } as never, makeProps({ projectId: String(i) }), blocked())
        }
        // 1000 real teams + the "other" overflow bucket = 1001 series, never 1500
        expect(await totalSeries()).toBe(1001)
        expect(await teamValue('other')).toBe(500)
    })
})
