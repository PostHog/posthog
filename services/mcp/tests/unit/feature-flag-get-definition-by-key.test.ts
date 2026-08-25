import { describe, expect, it, vi } from 'vitest'

import { ToolInputValidationError } from '@/lib/errors'
import featureFlagGetDefinitionByKey from '@/tools/featureFlags/getDefinitionByKey'
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

const flag = (id: number, key: string): { id: number; key: string; name: string } => ({ id, key, name: key })

describe('feature-flag-get-definition-by-key', () => {
    const tool = featureFlagGetDefinitionByKey()

    it('resolves a key from the search result, without a second fetch', async () => {
        const request = vi.fn().mockResolvedValue({ results: [flag(7, 'new-checkout')] })

        const result = await tool.handler(createMockContext(request), { key: 'new-checkout' })

        // The search result already has the full flag, so it's returned directly instead of
        // triggering a redundant fetch-by-id round trip.
        expect(request).toHaveBeenCalledTimes(1)
        expect(request).toHaveBeenCalledWith({
            method: 'GET',
            path: '/api/projects/42/feature_flags/',
            query: { key: 'new-checkout', limit: 5 },
        })
        expect(result).toMatchObject({ id: 7, key: 'new-checkout', found: true })
    })

    it('picks the exact-case match when the key filter also returns a same-key different-case duplicate', async () => {
        const request = vi.fn().mockResolvedValue({ results: [flag(7, 'checkout'), flag(8, 'Checkout')] })

        const result = await tool.handler(createMockContext(request), { key: 'checkout' })

        expect(result).toMatchObject({ id: 7, key: 'checkout', found: true })
    })

    it('resolves a key case-insensitively when no exact-case match exists', async () => {
        const request = vi.fn().mockResolvedValue({ results: [flag(7, 'New-Checkout')] })

        const result = await tool.handler(createMockContext(request), { key: 'new-checkout' })

        expect(result).toMatchObject({ id: 7, key: 'New-Checkout', found: true })
    })

    it('raises a validation error when a key matches multiple flags only case-insensitively', async () => {
        const request = vi.fn().mockResolvedValue({ results: [flag(7, 'Checkout'), flag(8, 'CHECKOUT')] })

        await expect(tool.handler(createMockContext(request), { key: 'checkout' })).rejects.toBeInstanceOf(
            ToolInputValidationError
        )
    })

    it('returns a non-error found:false result naming the missing key when no flag matches', async () => {
        const request = vi.fn().mockResolvedValue({ results: [] })

        const result = await tool.handler(createMockContext(request), { key: 'checkout' })

        expect(result).toMatchObject({ found: false, key: 'checkout' })
        expect((result as { message: string }).message).toContain('checkout')
        expect(request).toHaveBeenCalledTimes(1)
    })

    it('raises a validation error for a blank key without calling the API', async () => {
        const request = vi.fn()

        await expect(tool.handler(createMockContext(request), { key: '   ' })).rejects.toBeInstanceOf(
            ToolInputValidationError
        )
        expect(request).not.toHaveBeenCalled()
    })

    // Agents reconstruct this call from the tool name in exec mode and send the
    // key as `flagKey` / `flag_key` / `feature_flag_key`; production traces show
    // that mismatch as the dominant validation failure. Every alias must
    // normalize onto `key` (canonical wins on conflict) or those failures return.
    describe('key aliases', () => {
        it.each([
            ['key', { key: 'new-checkout' }],
            ['flagKey', { flagKey: 'new-checkout' }],
            ['flag_key', { flag_key: 'new-checkout' }],
            ['feature_flag_key', { feature_flag_key: 'new-checkout' }],
            ['featureFlagKey', { featureFlagKey: 'new-checkout' }],
            ['key over an alias on conflict', { key: 'new-checkout', flagKey: 'other' }],
        ])('normalizes %s to `key`', (_label, input) => {
            const result = tool.schema.safeParse(input)
            expect(result.success).toBe(true)
            const data = result.data as Record<string, unknown>
            expect(data.key).toBe('new-checkout')
            for (const alias of ['flagKey', 'flag_key', 'feature_flag_key', 'featureFlagKey']) {
                expect(data).not.toHaveProperty(alias)
            }
        })

        it('still rejects a call with no key under any accepted name', () => {
            expect(tool.schema.safeParse({}).success).toBe(false)
        })
    })
})
