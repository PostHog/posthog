import { afterEach, describe, expect, it, vi } from 'vitest'

import { GuidanceProductState } from '@/hono/guidance/product-state'
import type { ResolvedState } from '@/hono/request-state-resolver'

import { makeToolExecutorState } from '../shared/test-utils'
import { makeGuidanceRedis } from './helpers/guidance-redis-stubs'

function makeState(
    options: {
        project?: () => Promise<unknown>
        request?: () => Promise<unknown>
    } = {}
): { state: ResolvedState; request: ReturnType<typeof vi.fn> } {
    const state = makeToolExecutorState([], { suppressAnalytics: false })
    const request = vi.fn(options.request ?? (async () => ({ exists: true })))
    state.context.stateManager = {
        getCachedOrFetchProject: vi.fn(options.project ?? (async () => ({ ingested_event: true }))),
        getProjectId: vi.fn().mockResolvedValue('42'),
    } as any
    state.context.api = { request } as any
    return { state, request }
}

describe('GuidanceProductState', () => {
    afterEach(() => {
        vi.useRealTimers()
    })

    it.each([
        [true, '1', 86_400],
        [false, '0', 600],
    ])('caches exists=%s across evaluations with its own TTL', async (exists, stored, ttl) => {
        const redis = makeGuidanceRedis()
        const set = vi.spyOn(redis, 'set')
        const { state, request } = makeState({ request: async () => ({ exists }) })

        await expect(new GuidanceProductState(redis, state).hasErrorTrackingIssues()).resolves.toBe(exists)
        await expect(new GuidanceProductState(redis, state).hasErrorTrackingIssues()).resolves.toBe(exists)

        expect(request).toHaveBeenCalledTimes(1)
        expect(set).toHaveBeenCalledWith(expect.stringContaining(':42'), stored, 'EX', ttl)
    })

    it.each([
        ['user', { distinctId: 'another-user' }],
        ['scope set', { apiKeyScopes: ['project:read'] }],
    ])('does not reuse a cached answer for another %s', async (_label, caller) => {
        const redis = makeGuidanceRedis()
        const { state, request } = makeState()
        await new GuidanceProductState(redis, state).hasErrorTrackingIssues()
        await new GuidanceProductState(redis, { ...state, ...caller }).hasErrorTrackingIssues()
        expect(request).toHaveBeenCalledTimes(2)
    })

    it.each([
        ['a rejected request', async () => Promise.reject(new Error('boom'))],
        ['an unexpected response', async () => ({ unexpected: true })],
    ])('treats %s as unknown and does not cache it', async (_label, requestImpl) => {
        const redis = makeGuidanceRedis()
        const { state, request } = makeState({ request: requestImpl })

        await expect(new GuidanceProductState(redis, state).hasErrorTrackingIssues()).resolves.toBeUndefined()
        await expect(new GuidanceProductState(redis, state).hasErrorTrackingIssues()).resolves.toBeUndefined()

        expect(request).toHaveBeenCalledTimes(2)
    })

    it('returns on the budget and lets the slow lookup fill the cache', async () => {
        vi.useFakeTimers()
        const redis = makeGuidanceRedis()
        let finish: (value: unknown) => void = () => {}
        const { state, request } = makeState({
            request: () => new Promise((resolve) => (finish = resolve)),
        })

        const pending = new GuidanceProductState(redis, state).hasErrorTrackingIssues()
        await vi.advanceTimersByTimeAsync(300)
        await expect(pending).resolves.toBeUndefined()

        finish({ exists: true })
        await vi.advanceTimersByTimeAsync(0)

        await expect(new GuidanceProductState(redis, state).hasErrorTrackingIssues()).resolves.toBe(true)
        expect(request).toHaveBeenCalledTimes(1)
    })

    it('shares one budget across the lookups of an evaluation', async () => {
        vi.useFakeTimers()
        const after = (ms: number, value: unknown) => (): Promise<unknown> =>
            new Promise((resolve) => setTimeout(() => resolve(value), ms))
        const { state } = makeState({
            project: after(200, { ingested_event: true }),
            request: after(200, { exists: true }),
        })
        const productState = new GuidanceProductState(makeGuidanceRedis(), state)

        const ingested = productState.hasIngestedData()
        await vi.advanceTimersByTimeAsync(200)
        await expect(ingested).resolves.toBe(true)

        const issues = productState.hasErrorTrackingIssues()
        await vi.advanceTimersByTimeAsync(100)
        await expect(issues).resolves.toBeUndefined()
    })

    it('treats a failing project read as unknown', async () => {
        const { state } = makeState({ project: async () => Promise.reject(new Error('boom')) })
        await expect(new GuidanceProductState(makeGuidanceRedis(), state).hasIngestedData()).resolves.toBeUndefined()
    })
})
