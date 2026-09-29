import { describe, expect, it, vi } from 'vitest'

import { ToolInputValidationError } from '@/lib/errors'
import experimentGetByFlagKey from '@/tools/experiments/getByFlagKey'
import type { Context } from '@/tools/types'

function createMockContext(requestMock: ReturnType<typeof vi.fn>): Context {
    return {
        api: {
            request: requestMock,
            getProjectBaseUrl: (projectId: string) => `https://us.posthog.com/project/${projectId}`,
        } as any,
        stateManager: { getProjectId: vi.fn().mockResolvedValue('42') } as any,
        env: {} as any,
        sessionManager: {} as any,
        cache: {} as any,
        getDistinctId: async () => 'test-distinct-id',
        trackEvent: async () => {},
    }
}

const flag = (
    id: number,
    key: string,
    experimentIds: number[] = []
): { id: number; key: string; name: string; experiment_set: number[] } => ({
    id,
    key,
    name: key,
    experiment_set: experimentIds,
})
const experiment = (
    id: number,
    key: string,
    extra: Record<string, unknown> = {}
): { id: number; name: string; feature_flag_key: string } => ({
    id,
    name: `Experiment ${id}`,
    feature_flag_key: key,
    ...extra,
})

const FLAG_LIST = { method: 'GET', path: '/api/projects/42/feature_flags/', query: { key: 'new-checkout', limit: 20 } }
const FLAG_LIST_ARCHIVED = {
    method: 'GET',
    path: '/api/projects/42/feature_flags/',
    query: { key: 'new-checkout', archived: true, limit: 20 },
}
const EXPERIMENTS_LIVE = {
    method: 'GET',
    path: '/api/projects/42/experiments/',
    query: { feature_flag_id: 7, limit: 50 },
}
const EXPERIMENTS_ARCHIVED = {
    method: 'GET',
    path: '/api/projects/42/experiments/',
    query: { feature_flag_id: 7, archived: true, limit: 50 },
}
const EXPERIMENT_GET = (id: number): { method: string; path: string } => ({
    method: 'GET',
    path: `/api/projects/42/experiments/${id}/`,
})

describe('experiment-get-by-flag-key', () => {
    const tool = experimentGetByFlagKey()

    it('resolves the flag key to its single linked experiment and returns the full experiment', async () => {
        const request = vi
            .fn()
            .mockResolvedValueOnce({ results: [flag(7, 'new-checkout', [11])] })
            .mockResolvedValueOnce({ ...experiment(11, 'new-checkout'), metrics: [] })

        const result = await tool.handler(createMockContext(request), { feature_flag_key: 'new-checkout' })

        // The flag row already lists its experiments: one list call, then the full experiment.
        expect(request).toHaveBeenCalledTimes(2)
        expect(request).toHaveBeenNthCalledWith(1, FLAG_LIST)
        expect(request).toHaveBeenNthCalledWith(2, EXPERIMENT_GET(11))
        expect(result).toMatchObject({ id: 11, feature_flag_key: 'new-checkout', metrics: [], found: true })
        expect((result as { _posthogUrl?: string })._posthogUrl).toContain('/experiments/11')
    })

    it('finds the experiment behind an archived flag, which the flag list hides by default', async () => {
        const request = vi
            .fn()
            .mockResolvedValueOnce({ results: [] })
            .mockResolvedValueOnce({ results: [{ ...flag(7, 'new-checkout', [11]), archived: true }] })
            .mockResolvedValueOnce({ ...experiment(11, 'new-checkout'), archived: true })

        const result = await tool.handler(createMockContext(request), { feature_flag_key: 'new-checkout' })

        expect(request).toHaveBeenNthCalledWith(2, FLAG_LIST_ARCHIVED)
        expect(result).toMatchObject({ id: 11, archived: true, found: true })
    })

    it('picks the exact-case flag when the key filter also returns a same-key different-case duplicate', async () => {
        const request = vi
            .fn()
            .mockResolvedValueOnce({ results: [flag(7, 'new-checkout', [11]), flag(8, 'New-Checkout', [12])] })
            .mockResolvedValueOnce(experiment(11, 'new-checkout'))

        const result = await tool.handler(createMockContext(request), { feature_flag_key: 'new-checkout' })

        expect(request).toHaveBeenNthCalledWith(2, EXPERIMENT_GET(11))
        expect(result).toMatchObject({ id: 11, found: true })
    })

    it('returns a non-error found:false result when no flag has the key, live or archived', async () => {
        const request = vi.fn().mockResolvedValue({ results: [] })

        const result = await tool.handler(createMockContext(request), { feature_flag_key: 'new-checkout' })

        expect(result).toMatchObject({ found: false, reason: 'no_flag', feature_flag_key: 'new-checkout' })
        expect((result as { message: string }).message).toContain('new-checkout')
        expect(request).toHaveBeenCalledTimes(2)
        expect(request).toHaveBeenNthCalledWith(2, FLAG_LIST_ARCHIVED)
    })

    it('returns a non-error found:false result when the flag exists but no experiment is linked to it', async () => {
        const request = vi.fn().mockResolvedValueOnce({ results: [flag(7, 'new-checkout')] })

        const result = await tool.handler(createMockContext(request), { feature_flag_key: 'new-checkout' })

        expect(result).toMatchObject({ found: false, reason: 'no_experiment', feature_flag_key: 'new-checkout' })
        expect((result as { message: string }).message).toContain('ID 7')
        expect(request).toHaveBeenCalledTimes(1)
    })

    describe('several experiments on one flag (experiment-duplicate reuses the source flag)', () => {
        it('picks the single live experiment over archived re-runs', async () => {
            const request = vi
                .fn()
                .mockResolvedValueOnce({ results: [flag(7, 'new-checkout', [11, 12, 13])] })
                .mockResolvedValueOnce({ results: [experiment(13, 'new-checkout')] })
                .mockResolvedValueOnce(experiment(13, 'new-checkout'))

            const result = await tool.handler(createMockContext(request), { feature_flag_key: 'new-checkout' })

            expect(request).toHaveBeenNthCalledWith(2, EXPERIMENTS_LIVE)
            expect(request).toHaveBeenNthCalledWith(3, EXPERIMENT_GET(13))
            expect(result).toMatchObject({ id: 13, found: true })
        })

        it('picks the single archived experiment when none is live', async () => {
            const request = vi
                .fn()
                .mockResolvedValueOnce({ results: [flag(7, 'new-checkout', [11, 12])] })
                .mockResolvedValueOnce({ results: [] })
                .mockResolvedValueOnce({ results: [experiment(12, 'new-checkout', { archived: true })] })
                .mockResolvedValueOnce(experiment(12, 'new-checkout', { archived: true }))

            const result = await tool.handler(createMockContext(request), { feature_flag_key: 'new-checkout' })

            expect(request).toHaveBeenNthCalledWith(3, EXPERIMENTS_ARCHIVED)
            expect(result).toMatchObject({ id: 12, found: true })
        })

        it('returns the candidates as data when none stands out', async () => {
            const request = vi
                .fn()
                .mockResolvedValueOnce({ results: [flag(7, 'new-checkout', [11, 12, 13])] })
                .mockResolvedValueOnce({
                    results: [
                        experiment(12, 'new-checkout', { status: 'running', created_at: '2026-08-01T00:00:00Z' }),
                        experiment(13, 'new-checkout', { status: 'draft', created_at: '2026-09-01T00:00:00Z' }),
                    ],
                })
                .mockResolvedValueOnce({ results: [experiment(11, 'new-checkout', { status: 'stopped' })] })

            const result = await tool.handler(createMockContext(request), { feature_flag_key: 'new-checkout' })

            expect(request).toHaveBeenCalledTimes(3)
            expect(result).toMatchObject({ found: false, reason: 'ambiguous', feature_flag_key: 'new-checkout' })
            expect((result as { candidates: unknown[] }).candidates).toEqual([
                expect.objectContaining({
                    id: 12,
                    status: 'running',
                    archived: false,
                    created_at: '2026-08-01T00:00:00Z',
                }),
                expect.objectContaining({ id: 13, status: 'draft', archived: false }),
                expect.objectContaining({ id: 11, status: 'stopped', archived: true }),
            ])
            expect((result as { message: string }).message).toContain('experiment-get')
        })
    })

    it('raises a validation error when a key matches multiple flags only case-insensitively', async () => {
        const request = vi.fn().mockResolvedValueOnce({ results: [flag(7, 'Checkout', [1]), flag(8, 'CHECKOUT', [2])] })

        await expect(tool.handler(createMockContext(request), { feature_flag_key: 'checkout' })).rejects.toBeInstanceOf(
            ToolInputValidationError
        )
    })

    it('raises a validation error for a blank key without calling the API', async () => {
        const request = vi.fn()

        await expect(tool.handler(createMockContext(request), { feature_flag_key: '   ' })).rejects.toBeInstanceOf(
            ToolInputValidationError
        )
        expect(request).not.toHaveBeenCalled()
    })

    describe('input aliases', () => {
        it.each([
            ['feature_flag_key', { feature_flag_key: 'new-checkout' }],
            ['flagKey', { flagKey: 'new-checkout' }],
            ['flag_key', { flag_key: 'new-checkout' }],
            ['featureFlagKey', { featureFlagKey: 'new-checkout' }],
            ['key', { key: 'new-checkout' }],
        ])('accepts %s', (_label, input) => {
            const result = tool.schema.safeParse(input)
            expect(result.success).toBe(true)
            expect(result.data).toEqual({ feature_flag_key: 'new-checkout' })
        })

        it('prefers the canonical name on conflict', () => {
            const result = tool.schema.safeParse({ feature_flag_key: 'a', key: 'b' })
            expect(result.data).toEqual({ feature_flag_key: 'a' })
        })

        it('still rejects a call with no key', () => {
            expect(tool.schema.safeParse({}).success).toBe(false)
        })
    })
})
