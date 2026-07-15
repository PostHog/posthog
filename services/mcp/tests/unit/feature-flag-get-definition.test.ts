import { describe, expect, it, vi } from 'vitest'

import { PostHogApiError, ToolInputValidationError } from '@/lib/errors'
import featureFlagGetDefinition from '@/tools/featureFlags/getDefinition'
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

describe('feature-flag-get-definition', () => {
    const tool = featureFlagGetDefinition()

    it('fetches directly by numeric id', async () => {
        const request = vi.fn().mockResolvedValue(flag(1234, 'my-flag'))
        await tool.handler(createMockContext(request), { id: 1234 })

        expect(request).toHaveBeenCalledTimes(1)
        expect(request).toHaveBeenCalledWith({
            method: 'GET',
            path: '/api/projects/42/feature_flags/1234/',
        })
    })

    it('accepts a stringified integer id', async () => {
        const request = vi.fn().mockResolvedValue(flag(1234, 'my-flag'))
        await tool.handler(createMockContext(request), { id: '1234' })

        expect(request).toHaveBeenCalledWith({
            method: 'GET',
            path: '/api/projects/42/feature_flags/1234/',
        })
    })

    it('resolves a key passed in the `key` param, then fetches by resolved id', async () => {
        const request = vi.fn().mockImplementation((opts: { path: string }) => {
            if (opts.path.endsWith('/feature_flags/')) {
                return Promise.resolve({ results: [flag(7, 'new-checkout')] })
            }
            return Promise.resolve(flag(7, 'new-checkout'))
        })

        await tool.handler(createMockContext(request), { key: 'new-checkout' })

        expect(request).toHaveBeenCalledWith({
            method: 'GET',
            path: '/api/projects/42/feature_flags/',
            query: { search: 'new-checkout', limit: 100 },
        })
        expect(request).toHaveBeenCalledWith({
            method: 'GET',
            path: '/api/projects/42/feature_flags/7/',
        })
    })

    it('treats a non-numeric string in `id` as a key', async () => {
        const request = vi.fn().mockImplementation((opts: { path: string }) => {
            if (opts.path.endsWith('/feature_flags/')) {
                return Promise.resolve({ results: [flag(7, 'new-checkout')] })
            }
            return Promise.resolve(flag(7, 'new-checkout'))
        })

        await tool.handler(createMockContext(request), { id: 'new-checkout' })

        expect(request).toHaveBeenCalledWith({
            method: 'GET',
            path: '/api/projects/42/feature_flags/7/',
        })
    })

    it('picks the exact key when search returns substring matches too', async () => {
        const request = vi.fn().mockImplementation((opts: { path: string }) => {
            if (opts.path.endsWith('/feature_flags/')) {
                return Promise.resolve({ results: [flag(7, 'checkout'), flag(8, 'checkout-v2')] })
            }
            return Promise.resolve(flag(7, 'checkout'))
        })

        await tool.handler(createMockContext(request), { key: 'checkout' })

        expect(request).toHaveBeenCalledWith({
            method: 'GET',
            path: '/api/projects/42/feature_flags/7/',
        })
    })

    it('raises a validation error naming the missing key when no flag matches', async () => {
        const request = vi.fn().mockResolvedValue({ results: [flag(8, 'checkout-v2')] })

        await expect(tool.handler(createMockContext(request), { key: 'checkout' })).rejects.toBeInstanceOf(
            ToolInputValidationError
        )
        // Never reaches a retrieve call.
        expect(request).toHaveBeenCalledTimes(1)
    })

    it('raises a validation error when neither id nor key is provided', async () => {
        const request = vi.fn()
        await expect(tool.handler(createMockContext(request), {})).rejects.toBeInstanceOf(ToolInputValidationError)
        expect(request).not.toHaveBeenCalled()
    })

    it('turns a 404 on a numeric id into an actionable 4xx error', async () => {
        const request = vi.fn().mockRejectedValue(
            new PostHogApiError({
                status: 404,
                statusText: 'Not Found',
                body: 'Not found.',
                url: '/api/projects/42/feature_flags/999/',
                method: 'GET',
            })
        )

        const error = await tool.handler(createMockContext(request), { id: 999 }).catch((e) => e)
        expect(error).toBeInstanceOf(PostHogApiError)
        expect(error.status).toBe(404)
        expect(error.message).toContain('No feature flag with ID 999')
        expect(error.message).toContain('key')
    })
})
