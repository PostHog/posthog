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
const experiment = (id: number, key: string): { id: number; name: string; feature_flag_key: string } => ({
    id,
    name: `Experiment ${id}`,
    feature_flag_key: key,
})

const FLAG_LIST_CALL = {
    method: 'GET',
    path: '/api/projects/42/feature_flags/',
    query: { key: 'new-checkout', limit: 5 },
}

describe('experiment-get-by-flag-key', () => {
    const tool = experimentGetByFlagKey()

    it('resolves the flag key to its linked experiment and returns the full experiment', async () => {
        const request = vi
            .fn()
            .mockResolvedValueOnce({ results: [flag(7, 'new-checkout', [11])] })
            .mockResolvedValueOnce({ ...experiment(11, 'new-checkout'), metrics: [] })

        const result = await tool.handler(createMockContext(request), { feature_flag_key: 'new-checkout' })

        // The flag row already lists its experiments, so the lookup is one list call plus
        // the fetch of the full experiment: no experiments-list call in between.
        expect(request).toHaveBeenCalledTimes(2)
        expect(request).toHaveBeenNthCalledWith(1, FLAG_LIST_CALL)
        expect(request).toHaveBeenNthCalledWith(2, { method: 'GET', path: '/api/projects/42/experiments/11/' })
        expect(result).toMatchObject({ id: 11, feature_flag_key: 'new-checkout', metrics: [], found: true })
        expect((result as { _posthogUrl?: string })._posthogUrl).toContain('/experiments/11')
    })

    it('picks the exact-case flag when the key filter also returns a same-key different-case duplicate', async () => {
        const request = vi
            .fn()
            .mockResolvedValueOnce({ results: [flag(7, 'new-checkout', [11]), flag(8, 'New-Checkout', [12])] })
            .mockResolvedValueOnce(experiment(11, 'new-checkout'))

        const result = await tool.handler(createMockContext(request), { feature_flag_key: 'new-checkout' })

        expect(request).toHaveBeenNthCalledWith(2, { method: 'GET', path: '/api/projects/42/experiments/11/' })
        expect(result).toMatchObject({ id: 11, found: true })
    })

    it('returns a non-error found:false result when no flag has the key', async () => {
        const request = vi.fn().mockResolvedValueOnce({ results: [] })

        const result = await tool.handler(createMockContext(request), { feature_flag_key: 'new-checkout' })

        expect(result).toMatchObject({ found: false, feature_flag_key: 'new-checkout' })
        expect((result as { message: string }).message).toContain('new-checkout')
        expect(request).toHaveBeenCalledTimes(1)
    })

    it('returns a non-error found:false result when the flag exists but no experiment is linked to it', async () => {
        const request = vi.fn().mockResolvedValueOnce({ results: [flag(7, 'new-checkout')] })

        const result = await tool.handler(createMockContext(request), { feature_flag_key: 'new-checkout' })

        expect(result).toMatchObject({ found: false, feature_flag_key: 'new-checkout' })
        expect((result as { message: string }).message).toContain('ID 7')
        expect(request).toHaveBeenCalledTimes(1)
    })

    it('raises a validation error naming the ids when several experiments are linked to the flag', async () => {
        const request = vi.fn().mockResolvedValueOnce({ results: [flag(7, 'new-checkout', [11, 12])] })

        await expect(tool.handler(createMockContext(request), { feature_flag_key: 'new-checkout' })).rejects.toThrow(
            /11, 12/
        )
        expect(request).toHaveBeenCalledTimes(1)
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
