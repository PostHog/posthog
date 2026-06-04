import { beforeEach, describe, expect, it, vi } from 'vitest'

import { rateLimitBlockedByTeam } from '@/hono/metrics'
import { recordRateLimitBlock } from '@/hono/rate-limit-telemetry'
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
    })

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
})
